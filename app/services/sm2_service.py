"""SM-2 spaced repetition, personalized Smart Mix, weakest topics, and stats."""

from __future__ import annotations

import json
import sqlite3
import time

from app.schemas import (
    ExamHistoryItemOut,
    GuestAttemptItem,
    TopicProgressStatOut,
    UserOut,
    UserStatsOut,
    UserStatsSummaryOut,
    WeakTopicOut,
)


def compute_sm2(
    ease_factor: float,
    interval_days: float,
    reps: int,
    quality: int,
    now_ts: int,
) -> tuple[float, float, int, int]:
    """Compute next (ease_factor, interval_days, reps, next_review_ts) using SM-2."""
    q = max(0, min(5, int(quality)))
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = round(max(1.3, new_ef), 4)

    if q < 3:
        new_reps = 0
        new_interval = 1.0
        # Failed / 'Не знаю' items enter the immediate review queue right away.
        next_review_ts = now_ts
    else:
        if reps == 0:
            new_interval = 1.0
        elif reps == 1:
            new_interval = 6.0
        else:
            new_interval = round(max(1.0, interval_days) * new_ef, 2)
        new_reps = reps + 1
        next_review_ts = now_ts + int(new_interval * 86400)

    return new_ef, new_interval, new_reps, next_review_ts


def record_question_progress(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    question_id: int,
    is_correct: bool,
    quality: int | None = None,
    now_ts: int | None = None,
    commit: bool = True,
) -> dict[str, object]:
    """Update user_progress row using SM-2 for an authenticated user."""
    ts = int(time.time()) if now_ts is None else now_ts
    q = quality if quality is not None else (4 if is_correct else 1)

    existing = conn.execute(
        """
        SELECT ease_factor, interval_days, reps, correct_cnt, wrong_cnt, last_wrong_ts, bookmarked
        FROM user_progress
        WHERE user_id = ? AND question_id = ?
        """,
        (user_id, question_id),
    ).fetchone()

    if existing is None:
        ef, interval, reps = 2.5, 0.0, 0
        correct_cnt, wrong_cnt, last_wrong_ts, bookmarked = 0, 0, 0, 0
    else:
        ef = float(existing["ease_factor"])
        interval = float(existing["interval_days"])
        reps = int(existing["reps"])
        correct_cnt = int(existing["correct_cnt"])
        wrong_cnt = int(existing["wrong_cnt"])
        last_wrong_ts = int(existing["last_wrong_ts"])
        bookmarked = int(existing["bookmarked"])

    new_ef, new_interval, new_reps, next_review_ts = compute_sm2(ef, interval, reps, q, ts)
    if q >= 3:
        correct_cnt += 1
    else:
        wrong_cnt += 1
        last_wrong_ts = ts

    conn.execute(
        """
        INSERT INTO user_progress (
            user_id, question_id, ease_factor, interval_days, reps,
            next_review_ts, correct_cnt, wrong_cnt, last_wrong_ts, bookmarked, updated_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, question_id) DO UPDATE SET
            ease_factor = excluded.ease_factor,
            interval_days = excluded.interval_days,
            reps = excluded.reps,
            next_review_ts = excluded.next_review_ts,
            correct_cnt = excluded.correct_cnt,
            wrong_cnt = excluded.wrong_cnt,
            last_wrong_ts = excluded.last_wrong_ts,
            updated_ts = excluded.updated_ts
        """,
        (
            user_id,
            question_id,
            new_ef,
            new_interval,
            new_reps,
            next_review_ts,
            correct_cnt,
            wrong_cnt,
            last_wrong_ts,
            bookmarked,
            ts,
        ),
    )
    if commit:
        conn.commit()
    return {
        "ease_factor": new_ef,
        "interval_days": new_interval,
        "reps": new_reps,
        "next_review_ts": next_review_ts,
        "bookmarked": bool(bookmarked),
    }


def set_bookmark(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    question_id: int,
    bookmarked: bool | None = None,
) -> bool:
    """Toggle or explicitly set bookmark status for a question."""
    exists = conn.execute(
        "SELECT 1 FROM questions WHERE id = ? AND status = 'verified'",
        (question_id,),
    ).fetchone()
    if exists is None:
        raise LookupError("Question not found")

    now_ts = int(time.time())
    row = conn.execute(
        "SELECT bookmarked FROM user_progress WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    ).fetchone()
    if row is None:
        target = True if bookmarked is None else bookmarked
        conn.execute(
            """
            INSERT INTO user_progress (
                user_id, question_id, ease_factor, interval_days, reps,
                next_review_ts, correct_cnt, wrong_cnt, last_wrong_ts, bookmarked, updated_ts
            ) VALUES (?, ?, 2.5, 0.0, 0, 0, 0, 0, 0, ?, ?)
            """,
            (user_id, question_id, 1 if target else 0, now_ts),
        )
    else:
        target = (not bool(row["bookmarked"])) if bookmarked is None else bookmarked
        conn.execute(
            "UPDATE user_progress SET bookmarked = ?, updated_ts = ? WHERE user_id = ? AND question_id = ?",
            (1 if target else 0, now_ts, user_id, question_id),
        )
    conn.commit()
    return target


def merge_guest_progress(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    attempts: list[GuestAttemptItem],
    bookmarks: list[int],
) -> dict[str, int]:
    """Merge guest localStorage attempts and bookmarks into user_progress on login."""
    if not attempts and not bookmarks:
        return {"merged_attempts": 0, "merged_bookmarks": 0}

    valid_ids = {
        int(r["id"])
        for r in conn.execute("SELECT id FROM questions WHERE status = 'verified'").fetchall()
    }
    merged_attempts = 0
    for item in attempts[:300]:
        if item.question_id not in valid_ids:
            continue
        record_question_progress(
            conn,
            user_id=user_id,
            question_id=item.question_id,
            is_correct=item.is_correct,
            quality=item.quality,
            now_ts=item.ts,
            commit=False,
        )
        merged_attempts += 1

    merged_bookmarks = 0
    now_ts = int(time.time())
    for qid in set(bookmarks[:200]):
        if qid not in valid_ids:
            continue
        row = conn.execute(
            "SELECT bookmarked FROM user_progress WHERE user_id = ? AND question_id = ?",
            (user_id, qid),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO user_progress (
                    user_id, question_id, ease_factor, interval_days, reps,
                    next_review_ts, correct_cnt, wrong_cnt, last_wrong_ts, bookmarked, updated_ts
                ) VALUES (?, ?, 2.5, 0.0, 0, 0, 0, 0, 0, 1, ?)
                """,
                (user_id, qid, now_ts),
            )
            merged_bookmarks += 1
        elif not row["bookmarked"]:
            conn.execute(
                "UPDATE user_progress SET bookmarked = 1, updated_ts = ? WHERE user_id = ? AND question_id = ?",
                (now_ts, user_id, qid),
            )
            merged_bookmarks += 1

    conn.commit()
    return {"merged_attempts": merged_attempts, "merged_bookmarks": merged_bookmarks}


def reset_user_stats(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    keep_bookmarks: bool = True,
) -> dict[str, int]:
    """Reset SM-2 progress and exam history for a single user."""
    now_ts = int(time.time())
    if keep_bookmarks:
        cur_del = conn.execute(
            "DELETE FROM user_progress WHERE user_id = ? AND bookmarked = 0",
            (user_id,),
        )
        cur_rst = conn.execute(
            """
            UPDATE user_progress
            SET ease_factor = 2.5,
                interval_days = 0.0,
                reps = 0,
                next_review_ts = 0,
                correct_cnt = 0,
                wrong_cnt = 0,
                last_wrong_ts = 0,
                updated_ts = ?
            WHERE user_id = ? AND bookmarked = 1
            """,
            (now_ts, user_id),
        )
        deleted_progress = int(cur_del.rowcount or 0)
        reset_bookmarked = int(cur_rst.rowcount or 0)
    else:
        cur_del = conn.execute("DELETE FROM user_progress WHERE user_id = ?", (user_id,))
        deleted_progress = int(cur_del.rowcount or 0)
        reset_bookmarked = 0

    cur_exam = conn.execute("DELETE FROM exam_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    return {
        "deleted_progress_rows": deleted_progress,
        "reset_bookmarked_rows": reset_bookmarked,
        "deleted_exam_sessions": int(cur_exam.rowcount or 0),
    }


def get_weakest_topic_ids(conn: sqlite3.Connection, user_id: int, limit: int = 3) -> list[int]:
    """Identify up to 3 weakest topics based on historical accuracy and errors."""
    rows = conn.execute(
        """
        SELECT
            q.topic_id,
            SUM(up.correct_cnt) AS cor,
            SUM(up.wrong_cnt) AS wrg
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
          AND q.status = 'verified'
          AND q.topic_id IS NOT NULL
          AND (up.correct_cnt + up.wrong_cnt) > 0
        GROUP BY q.topic_id
        HAVING wrg > 0 OR (CAST(cor AS REAL) / (cor + wrg)) < 0.85
        ORDER BY (CAST(cor AS REAL) / (cor + wrg)) ASC, wrg DESC, q.topic_id ASC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [int(r["topic_id"]) for r in rows]


def _band_for_pct(pct: float) -> str:
    if pct < 64.0:
        return "red"
    if pct <= 80.0:
        return "amber"
    return "green"


def get_user_stats(conn: sqlite3.Connection, user: UserOut) -> UserStatsOut:
    """Aggregate complete SM-2 progress, topic heatmap, exam history, and bookmarks."""
    now_ts = int(time.time())
    total_verified = int(
        conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'verified'").fetchone()[0]
    )

    agg = conn.execute(
        """
        SELECT
            SUM(CASE WHEN (correct_cnt + wrong_cnt) > 0 THEN 1 ELSE 0 END) AS attempted,
            COALESCE(SUM(correct_cnt), 0) AS total_cor,
            COALESCE(SUM(wrong_cnt), 0) AS total_wrg,
            SUM(CASE WHEN next_review_ts > 0 AND next_review_ts <= ? THEN 1 ELSE 0 END) AS due_cnt,
            SUM(CASE WHEN wrong_cnt > 0 THEN 1 ELSE 0 END) AS mistakes_cnt,
            SUM(CASE WHEN bookmarked = 1 THEN 1 ELSE 0 END) AS bmk_cnt
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id AND q.status = 'verified'
        WHERE up.user_id = ?
        """,
        (now_ts, user.id),
    ).fetchone()

    attempted = int(agg["attempted"] or 0)
    total_cor = int(agg["total_cor"] or 0)
    total_wrg = int(agg["total_wrg"] or 0)
    total_answers = total_cor + total_wrg
    overall_acc = round((total_cor / total_answers) * 100.0, 1) if total_answers else 0.0

    topic_rows = conn.execute(
        """
        SELECT
            t.id AS topic_id,
            t.module_no,
            t.title_uk,
            s.title_uk AS subject_title,
            COUNT(q.id) AS total_q,
            SUM(CASE WHEN (COALESCE(up.correct_cnt, 0) + COALESCE(up.wrong_cnt, 0)) > 0 THEN 1 ELSE 0 END) AS attempted_q,
            COALESCE(SUM(up.correct_cnt), 0) AS cor,
            COALESCE(SUM(up.wrong_cnt), 0) AS wrg,
            SUM(CASE WHEN up.next_review_ts > 0 AND up.next_review_ts <= ? THEN 1 ELSE 0 END) AS due_q
        FROM topics t
        JOIN subjects s ON s.id = t.subject_id
        JOIN questions q ON q.topic_id = t.id AND q.status = 'verified'
        LEFT JOIN user_progress up ON up.question_id = q.id AND up.user_id = ?
        GROUP BY t.id
        ORDER BY t.module_no, t.sort_order, t.id
        """,
        (now_ts, user.id),
    ).fetchall()

    topic_map: list[TopicProgressStatOut] = []
    weak_candidates: list[WeakTopicOut] = []
    for r in topic_rows:
        tot_q = int(r["total_q"])
        att_q = int(r["attempted_q"] or 0)
        cor = int(r["cor"] or 0)
        wrg = int(r["wrg"] or 0)
        ans_sum = cor + wrg
        acc = round((cor / ans_sum) * 100.0, 1) if ans_sum else 0.0
        prog = round((att_q / tot_q) * 100.0, 1) if tot_q else 0.0
        band = _band_for_pct(acc) if ans_sum else "amber"
        topic_map.append(
            TopicProgressStatOut(
                topic_id=int(r["topic_id"]),
                module_no=int(r["module_no"]),
                subject_title=r["subject_title"],
                title_uk=r["title_uk"],
                total_questions=tot_q,
                attempted_questions=att_q,
                progress_pct=prog,
                accuracy_pct=acc,
                due_count=int(r["due_q"] or 0),
                band=band,
            )
        )
        if ans_sum > 0 and (wrg > 0 or acc < 85.0):
            weak_candidates.append(
                WeakTopicOut(
                    topic_id=int(r["topic_id"]),
                    module_no=int(r["module_no"]),
                    title_uk=r["title_uk"],
                    accuracy_pct=acc,
                    wrong_cnt=wrg,
                )
            )

    weak_candidates.sort(key=lambda w: (w.accuracy_pct, -w.wrong_cnt, w.topic_id))
    weakest_topics = weak_candidates[:3]

    exam_rows = conn.execute(
        """
        SELECT id, mode, total_q, correct_q, duration_sec, finished_ts
        FROM exam_sessions
        WHERE user_id = ?
        ORDER BY finished_ts DESC, id DESC
        LIMIT 20
        """,
        (user.id,),
    ).fetchall()
    exam_history = [
        ExamHistoryItemOut(
            id=int(er["id"]),
            mode=er["mode"],
            total_q=int(er["total_q"]),
            correct_q=int(er["correct_q"]),
            score_pct=round((int(er["correct_q"]) / int(er["total_q"])) * 100.0, 1) if er["total_q"] else 0.0,
            duration_sec=int(er["duration_sec"]),
            finished_ts=int(er["finished_ts"]),
        )
        for er in exam_rows
    ]

    bmk_rows = conn.execute(
        """
        SELECT q.id, q.stem, t.title_uk AS topic_title, q.source_tags
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id AND q.status = 'verified'
        LEFT JOIN topics t ON t.id = q.topic_id
        WHERE up.user_id = ? AND up.bookmarked = 1
        ORDER BY up.updated_ts DESC
        LIMIT 50
        """,
        (user.id,),
    ).fetchall()
    bookmarked = [
        {
            "question_id": int(br["id"]),
            "stem": br["stem"],
            "topic_title": br["topic_title"],
            "source_tags": json.loads(br["source_tags"]),
        }
        for br in bmk_rows
    ]

    return UserStatsOut(
        user=user,
        summary=UserStatsSummaryOut(
            total_verified=total_verified,
            attempted_count=attempted,
            total_correct=total_cor,
            total_wrong=total_wrg,
            overall_accuracy_pct=overall_acc,
            due_count=int(agg["due_cnt"] or 0),
            mistakes_count=int(agg["mistakes_cnt"] or 0),
            bookmarked_count=int(agg["bmk_cnt"] or 0),
        ),
        topic_map=topic_map,
        weakest_topics=weakest_topics,
        exam_history=exam_history,
        bookmarked_questions=bookmarked,
    )
