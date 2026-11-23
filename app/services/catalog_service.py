"""Catalog queries for subjects, modules, topics, and health counters."""

from __future__ import annotations

import sqlite3
import time

from app.config import APP_VERSION, get_settings
from app.schemas import (
    HealthOut,
    ModuleOut,
    SourceTagCount,
    SubjectOut,
    SubjectsResponse,
    TopicOut,
    UserOut,
)

MODULE_TITLES: dict[int, str] = {
    1: "Модуль 1 · Загальна мікробіологія",
    2: "Модуль 2 · Вірусологія",
    3: "Модуль 3 · Спеціальна бактеріологія",
    4: "Модуль 4 · ККР (додаткові)",
    5: "Модуль 5 · Збірник тестів з мікробіології",
}


def get_health_stats(conn: sqlite3.Connection) -> HealthOut:
    settings = get_settings()
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) AS verified_q,
            SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) AS review_q
        FROM questions
        """
    ).fetchone()
    subj_cnt = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    topic_cnt = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    exp_cnt = conn.execute("SELECT COUNT(*) FROM question_explanations").fetchone()[0]
    return HealthOut(
        status="ok",
        version=APP_VERSION,
        verified_questions=int(row["verified_q"] or 0),
        needs_review_questions=int(row["review_q"] or 0),
        subjects_count=int(subj_cnt),
        topics_count=int(topic_cnt),
        cached_explanations=int(exp_cnt),
        telegram_auth_enabled=settings.telegram_auth_enabled,
    )


def list_subjects(conn: sqlite3.Connection, user: UserOut | None = None) -> SubjectsResponse:
    now_ts = int(time.time())
    subjects_rows = conn.execute(
        "SELECT id, slug, title_uk, icon FROM subjects ORDER BY sort_order, id"
    ).fetchall()

    subjects: list[SubjectOut] = []
    for srow in subjects_rows:
        sid = int(srow["id"])
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_q,
                SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM json_each(q.source_tags) WHERE json_each.value = 'ККР'
                ) THEN 1 ELSE 0 END) AS kkr_q
            FROM questions q
            WHERE q.subject_id = ? AND q.status = 'verified'
            """,
            (sid,),
        ).fetchone()

        tag_rows = conn.execute(
            """
            SELECT j.value AS tag, COUNT(*) AS cnt
            FROM questions q
            JOIN json_each(q.source_tags) j
            WHERE q.subject_id = ? AND q.status = 'verified'
            GROUP BY j.value
            ORDER BY cnt DESC, j.value
            """,
            (sid,),
        ).fetchall()

        if user is not None:
            topic_rows = conn.execute(
                """
                SELECT
                    t.id,
                    t.module_no,
                    t.title_uk,
                    COUNT(q.id) AS q_cnt,
                    SUM(CASE WHEN (COALESCE(up.correct_cnt, 0) + COALESCE(up.wrong_cnt, 0)) > 0 THEN 1 ELSE 0 END) AS att_cnt,
                    COALESCE(SUM(up.correct_cnt), 0) AS cor_cnt,
                    COALESCE(SUM(up.wrong_cnt), 0) AS wrg_cnt,
                    SUM(CASE WHEN up.next_review_ts > 0 AND up.next_review_ts <= ? THEN 1 ELSE 0 END) AS due_cnt
                FROM topics t
                LEFT JOIN questions q
                    ON q.topic_id = t.id AND q.status = 'verified'
                LEFT JOIN user_progress up
                    ON up.question_id = q.id AND up.user_id = ?
                WHERE t.subject_id = ?
                GROUP BY t.id
                HAVING q_cnt > 0
                ORDER BY t.module_no, t.sort_order, t.id
                """,
                (now_ts, user.id, sid),
            ).fetchall()
        else:
            topic_rows = conn.execute(
                """
                SELECT
                    t.id,
                    t.module_no,
                    t.title_uk,
                    COUNT(q.id) AS q_cnt,
                    0 AS att_cnt,
                    0 AS cor_cnt,
                    0 AS wrg_cnt,
                    0 AS due_cnt
                FROM topics t
                LEFT JOIN questions q
                    ON q.topic_id = t.id AND q.status = 'verified'
                WHERE t.subject_id = ?
                GROUP BY t.id
                HAVING q_cnt > 0
                ORDER BY t.module_no, t.sort_order, t.id
                """,
                (sid,),
            ).fetchall()

        unassigned_rows = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM questions
            WHERE subject_id = ? AND topic_id IS NULL AND status = 'verified'
            """,
            (sid,),
        ).fetchone()

        modules_map: dict[int, list[TopicOut]] = {}
        mod_cor_wrg: dict[int, list[int]] = {}
        subj_att = 0
        subj_cor = 0
        subj_wrg = 0
        subj_due = 0

        for trow in topic_rows:
            mod_no = int(trow["module_no"])
            q_cnt = int(trow["q_cnt"])
            att = int(trow["att_cnt"] or 0)
            cor = int(trow["cor_cnt"] or 0)
            wrg = int(trow["wrg_cnt"] or 0)
            due = int(trow["due_cnt"] or 0)
            ans_total = cor + wrg

            subj_att += att
            subj_cor += cor
            subj_wrg += wrg
            subj_due += due
            pair = mod_cor_wrg.setdefault(mod_no, [0, 0])
            pair[0] += cor
            pair[1] += wrg

            modules_map.setdefault(mod_no, []).append(
                TopicOut(
                    id=int(trow["id"]),
                    module_no=mod_no,
                    title_uk=trow["title_uk"],
                    question_count=q_cnt,
                    attempted_count=att,
                    progress_pct=round((att / q_cnt) * 100.0, 1) if q_cnt else 0.0,
                    accuracy_pct=round((cor / ans_total) * 100.0, 1) if ans_total else 0.0,
                    due_count=due,
                )
            )

        modules: list[ModuleOut] = []
        for mod_no in sorted(modules_map):
            tlist = modules_map[mod_no]
            mq = sum(t.question_count for t in tlist)
            ma = sum(t.attempted_count for t in tlist)
            md = sum(t.due_count for t in tlist)
            mc, mw = mod_cor_wrg.get(mod_no, [0, 0])
            mans = mc + mw
            modules.append(
                ModuleOut(
                    module_no=mod_no,
                    title_uk=MODULE_TITLES.get(mod_no, f"Модуль {mod_no}"),
                    question_count=mq,
                    attempted_count=ma,
                    progress_pct=round((ma / mq) * 100.0, 1) if mq else 0.0,
                    accuracy_pct=round((mc / mans) * 100.0, 1) if mans else 0.0,
                    due_count=md,
                    topics=tlist,
                )
            )

        if int(unassigned_rows["cnt"] or 0) > 0 and 0 not in modules_map:
            modules.append(
                ModuleOut(
                    module_no=0,
                    title_uk="Інші питання",
                    question_count=int(unassigned_rows["cnt"]),
                    topics=[],
                )
            )

        total_q = int(totals["total_q"] or 0)
        subj_ans = subj_cor + subj_wrg
        subjects.append(
            SubjectOut(
                id=sid,
                slug=srow["slug"],
                title_uk=srow["title_uk"],
                icon=srow["icon"],
                total_questions=total_q,
                kkr_questions=int(totals["kkr_q"] or 0),
                attempted_count=subj_att,
                progress_pct=round((subj_att / total_q) * 100.0, 1) if total_q else 0.0,
                accuracy_pct=round((subj_cor / subj_ans) * 100.0, 1) if subj_ans else 0.0,
                due_count=subj_due,
                source_tags=[SourceTagCount(tag=r["tag"], count=int(r["cnt"])) for r in tag_rows],
                modules=modules,
            )
        )

    return SubjectsResponse(subjects=subjects)
