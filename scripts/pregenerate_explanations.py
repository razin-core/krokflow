"""Admin batch CLI to pre-warm question_explanations without burning guest quota."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.db import db_session, init_db
from app.services.explain_service import (
    extract_krok_triggers,
    generate_gemini_explanation,
    save_explanation,
)


def pregenerate_batch(
    *,
    mode: str = "triggers",
    limit: int = 0,
    sleep_sec: float = 0.8,
    upgrade_triggers: bool = False,
    refresh_triggers: bool = False,
    subject_slug: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    """Populate question_explanations in deterministic triggers mode or Gemini Flash batch mode."""
    init_db(db_path)
    settings = get_settings()
    if mode == "gemini" and not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is empty. Configure .env first.")

    with db_session(db_path) as conn:
        clauses = ["q.status = 'verified'"]
        params: list[object] = []
        if subject_slug:
            clauses.append("s.slug = ?")
            params.append(subject_slug)

        if (upgrade_triggers and mode == "gemini") or (refresh_triggers and mode == "triggers"):
            clauses.append("(qe.question_id IS NULL OR qe.model_id = 'trigger-index-v1')")
        else:
            clauses.append("qe.question_id IS NULL")

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT q.id, q.stem, q.options_json, q.correct_idx, s.slug AS subject_slug
            FROM questions q
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            WHERE {where_sql}
            ORDER BY q.id
        """
        if limit > 0:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()

        processed = 0
        errors = 0
        for row in rows:
            qid = int(row["id"])
            stem = row["stem"]
            options: list[str] = json.loads(row["options_json"])
            correct_idx = int(row["correct_idx"])
            correct_text = options[correct_idx]

            if mode == "triggers":
                markers, anchor = extract_krok_triggers(
                    stem,
                    correct_text,
                    subject_slug=row["subject_slug"],
                )
                save_explanation(
                    conn,
                    qid=qid,
                    markers=markers,
                    anchor_uk=anchor,
                    explanation_uk="",
                    distractors_uk="",
                    model_id="trigger-index-v1",
                    commit=False,
                )
                processed += 1
            elif mode == "gemini":
                try:
                    out = generate_gemini_explanation(
                        stem=stem,
                        options=options,
                        correct_idx=correct_idx,
                        api_key=settings.gemini_api_key,
                        model=settings.gemini_model,
                    )
                    save_explanation(
                        conn,
                        qid=qid,
                        markers=out.markers,
                        anchor_uk=out.anchor_uk,
                        explanation_uk=out.explanation_uk,
                        distractors_uk=out.distractors_uk,
                        model_id=out.model_id,
                        commit=True,
                    )
                    processed += 1
                    if sleep_sec > 0:
                        time.sleep(sleep_sec)
                except Exception as exc:
                    errors += 1
                    print(f"[ERR qid={qid}] {exc}", file=sys.stderr)
            else:
                raise ValueError(f"Unknown mode: {mode}")

        conn.commit()
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_verified,
                SUM(CASE WHEN qe.question_id IS NOT NULL THEN 1 ELSE 0 END) AS cached_any,
                SUM(CASE WHEN qe.model_id = 'trigger-index-v1' THEN 1 ELSE 0 END) AS triggers_only,
                SUM(CASE WHEN qe.model_id IS NOT NULL AND qe.model_id != 'trigger-index-v1' THEN 1 ELSE 0 END) AS llm_cached
            FROM questions q
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            WHERE q.status = 'verified'
            """
        ).fetchone()
        return {
            "processed": processed,
            "errors": errors,
            "total_verified": int(totals["total_verified"] or 0),
            "cached_any": int(totals["cached_any"] or 0),
            "triggers_only": int(totals["triggers_only"] or 0),
            "llm_cached": int(totals["llm_cached"] or 0),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-generate cached KROK markers & explanations")
    parser.add_argument("--mode", choices=["triggers", "gemini"], default="triggers")
    parser.add_argument("--limit", type=int, default=0, help="Max questions to process (0 = all)")
    parser.add_argument("--sleep", type=float, default=0.8, help="Delay between Gemini calls (sec)")
    parser.add_argument("--upgrade-triggers", action="store_true", help="Upgrade trigger-index-v1 rows with Gemini")
    parser.add_argument("--refresh-triggers", action="store_true", help="Recompute trigger-index-v1 rows offline")
    parser.add_argument("--subject", default=None, help="Filter by subject slug (e.g. pharmacology)")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)

    res = pregenerate_batch(
        mode=args.mode,
        limit=args.limit,
        sleep_sec=args.sleep,
        upgrade_triggers=args.upgrade_triggers,
        refresh_triggers=args.refresh_triggers,
        subject_slug=args.subject,
        db_path=args.db,
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
