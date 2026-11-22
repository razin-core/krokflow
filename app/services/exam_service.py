"""KROK-1 Exam simulator assembly, SM-2 logging, and topic heatmap grading."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time

from app.schemas import (
    ExamReviewItem,
    ExamStartRequest,
    ExamStartResponse,
    ExamSubmitRequest,
    ExamSubmitResponse,
    TopicBreakdownItem,
    UserOut,
)
from app.services.quiz_service import (
    build_question_out,
    decode_option_token,
    select_filtered_questions,
)
from app.services.sm2_service import record_question_progress

PASS_THRESHOLD_PCT = 64


def start_exam(conn: sqlite3.Connection, req: ExamStartRequest) -> ExamStartResponse:
    rows = select_filtered_questions(
        conn,
        subject_id=req.subject_id,
        module_no=req.module_no,
        source_tag=req.source_tag,
        limit=req.question_count,
    )
    # Never expose markers during an exam simulation (SDD Section 1.2).
    questions = [build_question_out(r, include_markers=False) for r in rows]
    total = len(questions)
    return ExamStartResponse(
        exam_id=secrets.token_hex(8),
        started_ts=int(time.time()),
        duration_sec=max(total * 60, 60),
        pass_threshold_pct=PASS_THRESHOLD_PCT,
        total_questions=total,
        questions=questions,
    )


def _accuracy_band(pct: float) -> str:
    if pct < 64.0:
        return "red"
    if pct <= 80.0:
        return "amber"
    return "green"


def submit_exam(
    conn: sqlite3.Connection,
    req: ExamSubmitRequest,
    *,
    user: UserOut | None = None,
) -> ExamSubmitResponse:
    if not req.answers:
        return ExamSubmitResponse(
            exam_id=req.exam_id,
            total_questions=0,
            answered_count=0,
            correct_count=0,
            score_pct=0.0,
            passed=False,
            pass_threshold_pct=PASS_THRESHOLD_PCT,
            duration_sec=req.duration_sec,
            saved_to_profile=False,
            breakdown=[],
            weakest_topic_ids=[],
            review_items=[],
        )

    dedup_answers: dict[int, str | None] = {}
    for item in req.answers:
        dedup_answers[item.question_id] = item.selected_option_id

    qids = list(dedup_answers.keys())
    placeholders = ",".join("?" for _ in qids)
    rows = conn.execute(
        f"""
        SELECT
            q.id,
            q.topic_id,
            COALESCE(t.module_no, 1) AS module_no,
            COALESCE(t.title_uk, 'Загальні питання') AS topic_title,
            q.stem,
            q.options_json,
            q.correct_idx,
            q.source_tags
        FROM questions q
        LEFT JOIN topics t ON t.id = q.topic_id
        WHERE q.id IN ({placeholders}) AND q.status = 'verified'
        """,
        qids,
    ).fetchall()

    row_map = {int(r["id"]): r for r in rows}

    answered_count = 0
    correct_count = 0
    topic_stats: dict[tuple[int | None, int, str], list[int]] = {}
    review_items: list[ExamReviewItem] = []
    now_ts = int(time.time())

    for qid in qids:
        row = row_map.get(qid)
        if row is None:
            continue
        options: list[str] = json.loads(row["options_json"])
        correct_idx = int(row["correct_idx"])
        correct_text = options[correct_idx]
        selected_token = dedup_answers[qid]

        selected_text: str | None = None
        is_correct = False
        if selected_token:
            answered_count += 1
            orig_idx, _ = decode_option_token(qid, selected_token)
            if not (0 <= orig_idx < len(options)):
                raise ValueError("Option index out of bounds")
            selected_text = options[orig_idx]
            is_correct = orig_idx == correct_idx
            if is_correct:
                correct_count += 1
            if user is not None:
                record_question_progress(
                    conn,
                    user_id=user.id,
                    question_id=qid,
                    is_correct=is_correct,
                    now_ts=now_ts,
                    commit=False,
                )

        tid = int(row["topic_id"]) if row["topic_id"] is not None else None
        mod_no = int(row["module_no"])
        ttitle = str(row["topic_title"])
        key = (tid, mod_no, ttitle)
        pair = topic_stats.setdefault(key, [0, 0])
        pair[0] += 1
        if is_correct:
            pair[1] += 1

        review_items.append(
            ExamReviewItem(
                question_id=qid,
                stem=row["stem"],
                selected_text=selected_text,
                correct_text=correct_text,
                is_correct=is_correct,
                topic_title=ttitle,
                source_tags=json.loads(row["source_tags"]),
            )
        )

    total_q = len(review_items)
    score_pct = round((correct_count / total_q) * 100.0, 1) if total_q else 0.0

    breakdown: list[TopicBreakdownItem] = []
    for (tid, mod_no, ttitle), (tot, cor) in topic_stats.items():
        pct = round((cor / tot) * 100.0, 1) if tot else 0.0
        breakdown.append(
            TopicBreakdownItem(
                topic_id=tid,
                module_no=mod_no,
                title_uk=ttitle,
                total=tot,
                correct=cor,
                accuracy_pct=pct,
                band=_accuracy_band(pct),
            )
        )
    breakdown.sort(key=lambda b: (b.accuracy_pct, -b.total, b.module_no, b.title_uk))

    weakest_topic_ids = [
        b.topic_id
        for b in breakdown
        if b.topic_id is not None and b.accuracy_pct < 100.0
    ][:3]

    saved_to_profile = False
    if user is not None and total_q > 0:
        breakdown_json = json.dumps([b.model_dump() for b in breakdown], ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO exam_sessions (user_id, subject_id, mode, total_q, correct_q, duration_sec, breakdown, finished_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                req.subject_id,
                req.mode,
                total_q,
                correct_count,
                req.duration_sec,
                breakdown_json,
                now_ts,
            ),
        )
        conn.commit()
        saved_to_profile = True

    return ExamSubmitResponse(
        exam_id=req.exam_id,
        total_questions=total_q,
        answered_count=answered_count,
        correct_count=correct_count,
        score_pct=score_pct,
        passed=(score_pct >= PASS_THRESHOLD_PCT),
        pass_threshold_pct=PASS_THRESHOLD_PCT,
        duration_sec=req.duration_sec,
        saved_to_profile=saved_to_profile,
        breakdown=breakdown,
        weakest_topic_ids=weakest_topic_ids,
        review_items=review_items,
    )
