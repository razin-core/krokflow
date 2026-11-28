"""Quiz session assembly, SM-2 prioritization, Fisher-Yates shuffling, and answer grading."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import time
from typing import TypeVar

from fastapi import HTTPException, status

from app.config import get_settings
from app.schemas import (
    BookmarksListResponse,
    OptionOut,
    QuestionOut,
    QuestionReportResponse,
    QuizAnswerResponse,
    QuizSessionRequest,
    QuizSessionResponse,
    RevealOut,
    UserOut,
)
from app.services.explain_service import get_cached_explanation
from app.services.sm2_service import get_weakest_topic_ids, record_question_progress

_T = TypeVar("_T")
_SYS_RNG = random.SystemRandom()


def fisher_yates_shuffle(items: list[_T]) -> list[_T]:
    """Return a newly shuffled copy using unbiased Fisher-Yates."""
    arr = list(items)
    for i in range(len(arr) - 1, 0, -1):
        j = _SYS_RNG.randrange(i + 1)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def _option_mask(qid: int, salt: str, secret: str) -> int:
    digest = hashlib.sha256(f"{secret}:mask:{qid}:{salt}".encode("utf-8")).digest()
    return digest[0] & 0x07


def encode_option_token(qid: int, orig_idx: int, salt: str, secret: str | None = None) -> str:
    """Create an opaque HMAC-signed option_id that conceals orig_idx."""
    sec = secret or get_settings().token_secret
    obf = orig_idx ^ _option_mask(qid, salt, sec)
    sig = hmac.new(
        sec.encode("utf-8"),
        f"{qid}:{salt}:{obf}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]
    return f"{salt}.{obf}.{sig}"


def decode_option_token(qid: int, token: str, secret: str | None = None) -> tuple[int, str]:
    """Validate option_id signature and recover (orig_idx, salt)."""
    sec = secret or get_settings().token_secret
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed option token")
    salt, obf_str, sig = parts
    if not salt or not sig:
        raise ValueError("Malformed option token")
    try:
        obf = int(obf_str)
    except ValueError as exc:
        raise ValueError("Invalid option token index") from exc

    expected_sig = hmac.new(
        sec.encode("utf-8"),
        f"{qid}:{salt}:{obf}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Option token signature mismatch")

    orig_idx = obf ^ _option_mask(qid, salt, sec)
    if not (0 <= orig_idx <= 4):
        raise ValueError("Option index out of range")
    return orig_idx, salt


def build_question_out(
    row: sqlite3.Row,
    *,
    secret: str | None = None,
    include_markers: bool = True,
) -> QuestionOut:
    """Convert a DB question row into QuestionOut with Fisher-Yates shuffled options."""
    qid = int(row["id"])
    raw_options: list[str] = json.loads(row["options_json"])
    salt = secrets.token_hex(4)
    indices = fisher_yates_shuffle(list(range(len(raw_options))))
    shuffled = [
        OptionOut(
            option_id=encode_option_token(qid, orig_idx, salt, secret),
            text=raw_options[orig_idx],
        )
        for orig_idx in indices
    ]

    row_keys = row.keys()
    bookmarked = bool(row["bookmarked"]) if "bookmarked" in row_keys and row["bookmarked"] is not None else False
    markers: list[str] = []
    if include_markers and "markers_json" in row_keys and row["markers_json"]:
        try:
            markers = json.loads(row["markers_json"])
        except Exception:
            markers = []

    return QuestionOut(
        id=qid,
        subject_id=int(row["subject_id"]),
        subject_title=row["subject_title"],
        module_no=int(row["module_no"] or 1),
        topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
        topic_title=row["topic_title"],
        stem=row["stem"],
        options=shuffled,
        source_tags=json.loads(row["source_tags"]),
        shuffle_salt=salt,
        bookmarked=bookmarked,
        markers=markers,
    )


def _fetch_question_candidates(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    subject_id: int | None = None,
    module_no: int | None = None,
    topic_id: int | None = None,
    topic_ids: list[int] | None = None,
    question_ids: list[int] | None = None,
    source_tag: str | None = None,
    source_tags: list[str] | None = None,
) -> list[sqlite3.Row]:
    clauses = ["q.status = 'verified'"]
    params: list[object] = []

    if user_id is not None:
        params.append(user_id)

    if subject_id is not None:
        clauses.append("q.subject_id = ?")
        params.append(subject_id)
    if module_no is not None:
        clauses.append("t.module_no = ?")
        params.append(module_no)
    if topic_id is not None:
        clauses.append("q.topic_id = ?")
        params.append(topic_id)

    clean_topic_ids = [int(tid) for tid in (topic_ids or []) if int(tid) > 0]
    clean_source_tags = [str(st).strip() for st in (source_tags or []) if str(st).strip()]
    if clean_topic_ids and clean_source_tags:
        t_ph = ",".join("?" for _ in clean_topic_ids)
        s_ph = ",".join("?" for _ in clean_source_tags)
        clauses.append(
            f"(q.topic_id IN ({t_ph}) OR EXISTS (SELECT 1 FROM json_each(q.source_tags) WHERE json_each.value IN ({s_ph})))"
        )
        params.extend(clean_topic_ids)
        params.extend(clean_source_tags)
    elif clean_topic_ids:
        t_ph = ",".join("?" for _ in clean_topic_ids)
        clauses.append(f"q.topic_id IN ({t_ph})")
        params.extend(clean_topic_ids)
    elif clean_source_tags:
        s_ph = ",".join("?" for _ in clean_source_tags)
        clauses.append(f"EXISTS (SELECT 1 FROM json_each(q.source_tags) WHERE json_each.value IN ({s_ph}))")
        params.extend(clean_source_tags)

    if question_ids:
        clean_qids = [int(qid) for qid in question_ids[:200] if int(qid) > 0]
        if not clean_qids:
            return []
        placeholders = ",".join("?" for _ in clean_qids)
        clauses.append(f"q.id IN ({placeholders})")
        params.extend(clean_qids)
    if source_tag:
        clauses.append("EXISTS (SELECT 1 FROM json_each(q.source_tags) WHERE json_each.value = ?)")
        params.append(source_tag)

    where_sql = " AND ".join(clauses)
    if user_id is not None:
        sql = f"""
            SELECT
                q.id,
                q.subject_id,
                s.title_uk AS subject_title,
                q.topic_id,
                t.module_no,
                t.title_uk AS topic_title,
                q.stem,
                q.options_json,
                q.correct_idx,
                q.source_tags,
                qe.markers_json,
                COALESCE(up.bookmarked, 0) AS bookmarked,
                COALESCE(up.next_review_ts, 0) AS next_review_ts,
                COALESCE(up.correct_cnt, 0) AS correct_cnt,
                COALESCE(up.wrong_cnt, 0) AS wrong_cnt,
                COALESCE(up.last_wrong_ts, 0) AS last_wrong_ts
            FROM questions q
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN topics t ON t.id = q.topic_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            LEFT JOIN user_progress up ON up.question_id = q.id AND up.user_id = ?
            WHERE {where_sql}
        """
    else:
        sql = f"""
            SELECT
                q.id,
                q.subject_id,
                s.title_uk AS subject_title,
                q.topic_id,
                t.module_no,
                t.title_uk AS topic_title,
                q.stem,
                q.options_json,
                q.correct_idx,
                q.source_tags,
                qe.markers_json,
                0 AS bookmarked,
                0 AS next_review_ts,
                0 AS correct_cnt,
                0 AS wrong_cnt,
                0 AS last_wrong_ts
            FROM questions q
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN topics t ON t.id = q.topic_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            WHERE {where_sql}
        """
    return list(conn.execute(sql, params).fetchall())


def select_filtered_questions(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    subject_id: int | None = None,
    module_no: int | None = None,
    topic_id: int | None = None,
    topic_ids: list[int] | None = None,
    source_tag: str | None = None,
    source_tags: list[str] | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    rows = _fetch_question_candidates(
        conn,
        user_id=user_id,
        subject_id=subject_id,
        module_no=module_no,
        topic_id=topic_id,
        topic_ids=topic_ids,
        source_tag=source_tag,
        source_tags=source_tags,
    )
    return fisher_yates_shuffle(rows)[:limit]


def create_quiz_session(
    conn: sqlite3.Connection,
    req: QuizSessionRequest,
    *,
    user: UserOut | None = None,
) -> QuizSessionResponse:
    now_ts = int(time.time())
    user_id = user.id if user is not None else None
    effective_topic_ids = req.topic_ids
    hints_requested = bool(req.hints_enabled or req.mode == "hints")

    if hints_requested and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Режим з підказками (маркери КРОК до відповіді) доступний після входу через Telegram",
        )

    if req.mode == "mistakes" and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Черга помилок та SM-2 доступні після входу через Telegram",
        )

    if req.mode == "weak_topics":
        if user is None and not effective_topic_ids:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Закриття слабких тем за статистикою доступне після входу через Telegram",
            )
        if user is not None and not effective_topic_ids:
            effective_topic_ids = get_weakest_topic_ids(conn, user.id, limit=3)

    if req.mode == "bookmarks":
        if user is None and not req.question_ids:
            return QuizSessionResponse(
                session_id=secrets.token_hex(8),
                mode=req.mode,
                hints_enabled=hints_requested,
                total_questions=0,
                questions=[],
            )
        rows = _fetch_question_candidates(
            conn,
            user_id=user_id,
            subject_id=req.subject_id,
            module_no=req.module_no,
            topic_id=req.topic_id,
            topic_ids=effective_topic_ids,
            question_ids=req.question_ids if user is None else None,
            source_tag=req.source_tag,
            source_tags=req.source_tags,
        )
        if user is not None:
            rows = [r for r in rows if bool(r["bookmarked"])]
        chosen_rows = fisher_yates_shuffle(rows)[: req.limit]
    else:
        rows = _fetch_question_candidates(
            conn,
            user_id=user_id,
            subject_id=req.subject_id,
            module_no=req.module_no,
            topic_id=req.topic_id,
            topic_ids=effective_topic_ids,
            question_ids=req.question_ids,
            source_tag=req.source_tag,
            source_tags=req.source_tags,
        )

        if user is not None and req.mode == "mistakes":
            mistake_rows = [
                r
                for r in rows
                if int(r["wrong_cnt"]) > 0 or (0 < int(r["next_review_ts"]) <= now_ts)
            ]
            mistake_rows.sort(
                key=lambda r: (
                    -(int(r["wrong_cnt"]) - int(r["correct_cnt"])),
                    -int(r["last_wrong_ts"]),
                    int(r["next_review_ts"]),
                )
            )
            chosen_rows = mistake_rows[: req.limit]
        elif user is not None and req.mode in ("smart_mix", "weak_topics"):
            due_rows = [r for r in rows if 0 < int(r["next_review_ts"]) <= now_ts]
            due_rows.sort(key=lambda r: (int(r["next_review_ts"]), -int(r["wrong_cnt"])))
            seen_ids = {int(r["id"]) for r in due_rows}

            unseen_rows = fisher_yates_shuffle(
                [
                    r
                    for r in rows
                    if int(r["id"]) not in seen_ids
                    and int(r["correct_cnt"]) == 0
                    and int(r["wrong_cnt"]) == 0
                ]
            )
            for r in unseen_rows:
                seen_ids.add(int(r["id"]))

            rest_rows = fisher_yates_shuffle([r for r in rows if int(r["id"]) not in seen_ids])
            # Balance overdue SM-2 reviews (up to 60%) with unseen / remaining items.
            due_cap = max(1, int(req.limit * 0.6)) if (unseen_rows or rest_rows) else req.limit
            chosen_rows = due_rows[:due_cap] + unseen_rows + due_rows[due_cap:] + rest_rows
            chosen_rows = chosen_rows[: req.limit]
        else:
            chosen_rows = fisher_yates_shuffle(rows)[: req.limit]

    questions = [build_question_out(r, include_markers=hints_requested) for r in chosen_rows]
    return QuizSessionResponse(
        session_id=secrets.token_hex(8),
        mode=req.mode,
        hints_enabled=hints_requested,
        total_questions=len(questions),
        questions=questions,
    )


def grade_quiz_answer(
    conn: sqlite3.Connection,
    qid: int,
    selected_option_id: str,
    *,
    user: UserOut | None = None,
) -> QuizAnswerResponse:
    row = conn.execute(
        "SELECT id, options_json, correct_idx FROM questions WHERE id = ? AND status = 'verified'",
        (qid,),
    ).fetchone()
    if row is None:
        raise LookupError("Question not found")

    orig_idx, salt = decode_option_token(qid, selected_option_id)
    options: list[str] = json.loads(row["options_json"])
    correct_idx = int(row["correct_idx"])
    if not (0 <= orig_idx < len(options)) or not (0 <= correct_idx < len(options)):
        raise ValueError("Option index out of bounds")

    is_correct = orig_idx == correct_idx
    correct_option_id = encode_option_token(qid, correct_idx, salt)
    explanation = get_cached_explanation(conn, qid)

    sm2_saved = False
    next_review_ts: int | None = None
    if user is not None:
        prog = record_question_progress(
            conn,
            user_id=user.id,
            question_id=qid,
            is_correct=is_correct,
        )
        sm2_saved = True
        next_review_ts = int(prog["next_review_ts"])

    return QuizAnswerResponse(
        question_id=qid,
        is_correct=is_correct,
        selected_option_id=selected_option_id,
        correct_option_id=correct_option_id,
        correct_text=options[correct_idx],
        explanation=explanation,
        sm2_saved=sm2_saved,
        next_review_ts=next_review_ts,
    )


def reveal_question(conn: sqlite3.Connection, qid: int, salt: str | None = None) -> RevealOut:
    row = conn.execute(
        "SELECT id, options_json, correct_idx FROM questions WHERE id = ? AND status = 'verified'",
        (qid,),
    ).fetchone()
    if row is None:
        raise LookupError("Question not found")
    options: list[str] = json.loads(row["options_json"])
    correct_idx = int(row["correct_idx"])
    correct_option_id = encode_option_token(qid, correct_idx, salt) if salt else None
    return RevealOut(
        question_id=qid,
        correct_text=options[correct_idx],
        correct_option_id=correct_option_id,
        explanation=get_cached_explanation(conn, qid),
    )


def list_bookmarked_questions(
    conn: sqlite3.Connection,
    *,
    user: UserOut | None = None,
    ids: list[int] | None = None,
) -> BookmarksListResponse:
    """Return verified bookmarked questions for an authenticated user or guest ID list."""
    if user is not None:
        rows = conn.execute(
            """
            SELECT
                q.id,
                q.subject_id,
                s.title_uk AS subject_title,
                q.topic_id,
                t.module_no,
                t.title_uk AS topic_title,
                q.stem,
                q.options_json,
                q.source_tags,
                qe.markers_json,
                1 AS bookmarked
            FROM user_progress up
            JOIN questions q ON q.id = up.question_id AND q.status = 'verified'
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN topics t ON t.id = q.topic_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            WHERE up.user_id = ? AND up.bookmarked = 1
            ORDER BY up.updated_ts DESC, q.id DESC
            LIMIT 200
            """,
            (user.id,),
        ).fetchall()
        items = [build_question_out(r) for r in rows]
        return BookmarksListResponse(total=len(items), items=items)

    clean_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in ids or []:
        if raw_id > 0 and raw_id not in seen:
            seen.add(raw_id)
            clean_ids.append(raw_id)
        if len(clean_ids) >= 200:
            break
    if not clean_ids:
        return BookmarksListResponse(total=0, items=[])

    placeholders = ",".join("?" for _ in clean_ids)
    rows = conn.execute(
        f"""
        SELECT
            q.id,
            q.subject_id,
            s.title_uk AS subject_title,
            q.topic_id,
            t.module_no,
            t.title_uk AS topic_title,
            q.stem,
            q.options_json,
            q.source_tags,
            qe.markers_json,
            1 AS bookmarked
        FROM questions q
        JOIN subjects s ON s.id = q.subject_id
        LEFT JOIN topics t ON t.id = q.topic_id
        LEFT JOIN question_explanations qe ON qe.question_id = q.id
        WHERE q.status = 'verified' AND q.id IN ({placeholders})
        """,
        clean_ids,
    ).fetchall()
    by_id = {int(r["id"]): build_question_out(r) for r in rows}
    ordered = [by_id[qid] for qid in reversed(clean_ids) if qid in by_id]
    return BookmarksListResponse(total=len(ordered), items=ordered)


def submit_question_report(
    conn: sqlite3.Connection,
    *,
    question_id: int,
    reason: str,
    comment: str = "",
    user: UserOut | None = None,
) -> QuestionReportResponse:
    """Persist an error report on a verified question with basic duplicate suppression."""
    exists = conn.execute(
        "SELECT id FROM questions WHERE id = ? AND status = 'verified'",
        (question_id,),
    ).fetchone()
    if exists is None:
        raise LookupError("Питання не знайдено")

    clean_comment = " ".join((comment or "").strip().split())[:500]
    if reason == "other" and not clean_comment:
        raise ValueError("Для причини «Інше» коротко опишіть помилку")

    now_ts = int(time.time())
    if user is not None:
        dup = conn.execute(
            """
            SELECT id, reason, status
            FROM question_reports
            WHERE question_id = ? AND user_id = ? AND status = 'open' AND created_ts >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (question_id, user.id, now_ts - 86400),
        ).fetchone()
    else:
        dup = conn.execute(
            """
            SELECT id, reason, status
            FROM question_reports
            WHERE question_id = ? AND user_id IS NULL AND reason = ? AND comment = ?
              AND status = 'open' AND created_ts >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (question_id, reason, clean_comment, now_ts - 600),
        ).fetchone()

    if dup is not None:
        return QuestionReportResponse(
            id=int(dup["id"]),
            question_id=question_id,
            reason=dup["reason"],
            status=dup["status"],
            already_reported=True,
        )

    cur = conn.execute(
        """
        INSERT INTO question_reports (question_id, user_id, reason, comment, status, created_ts)
        VALUES (?, ?, ?, ?, 'open', ?)
        """,
        (question_id, user.id if user is not None else None, reason, clean_comment, now_ts),
    )
    conn.commit()
    return QuestionReportResponse(
        id=int(cur.lastrowid),
        question_id=question_id,
        reason=reason,
        status="open",
        already_reported=False,
    )
