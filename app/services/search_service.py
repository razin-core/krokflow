"""FTS5 full-text search service (<10 ms latency target)."""

from __future__ import annotations

import json
import re
import sqlite3
import time

from app.schemas import SearchItemOut, SearchResponse, UserOut
from app.services.quiz_service import build_question_out

_CYR_I_LEFT_RE = re.compile(r"(?<=[а-яіїєґА-ЯІЇЄҐ])i")
_CYR_I_RIGHT_RE = re.compile(r"i(?=[а-яіїєґА-ЯІЇЄҐ])")
_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9]+")


def _norm_for_match(text: str) -> str:
    """Repair Cyrillic i homoglyphs and lowercase for match verification."""
    fixed = _CYR_I_LEFT_RE.sub("і", text)
    fixed = _CYR_I_RIGHT_RE.sub("і", fixed)
    return fixed.lower()


def normalize_search_tokens(raw_query: str) -> list[str]:
    """Extract safe alphanumeric search tokens with Cyrillic i repair."""
    q = _CYR_I_LEFT_RE.sub("і", raw_query)
    q = _CYR_I_RIGHT_RE.sub("і", q)
    tokens = [t.strip() for t in _TOKEN_RE.findall(q) if t.strip()]
    # If there are multi-char tokens, drop stray single-char tokens that make prefix search noisy.
    long_tokens = [t for t in tokens if len(t) >= 2]
    return long_tokens if long_tokens else tokens


def build_fts5_match_expr(tokens: list[str]) -> str:
    """Build safe quoted prefix FTS5 query string."""
    if not tokens:
        return ""
    escaped = [t.replace('"', '""') for t in tokens[:8]]
    return " ".join(f'"{t}"*' for t in escaped)


def search_questions(
    conn: sqlite3.Connection,
    *,
    q: str,
    subject_id: int | None = None,
    module_no: int | None = None,
    source_tag: str | None = None,
    limit: int = 30,
    user: UserOut | None = None,
) -> SearchResponse:
    t0 = time.perf_counter()
    tokens = normalize_search_tokens(q)
    fts_expr = build_fts5_match_expr(tokens)
    if not fts_expr:
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        return SearchResponse(query=q, query_terms=[], elapsed_ms=elapsed, total=0, items=[])

    clauses = ["questions_fts MATCH ?", "q.status = 'verified'"]
    params: list[object] = []
    if user is not None:
        params.append(user.id)
    params.append(fts_expr)

    if subject_id is not None:
        clauses.append("q.subject_id = ?")
        params.append(subject_id)
    if module_no is not None:
        clauses.append("t.module_no = ?")
        params.append(module_no)
    if source_tag:
        clauses.append("EXISTS (SELECT 1 FROM json_each(q.source_tags) WHERE json_each.value = ?)")
        params.append(source_tag)

    candidate_limit = max(limit * 6, 180)
    params.append(candidate_limit)
    where_sql = " AND ".join(clauses)

    if user is not None:
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
                COALESCE(up.bookmarked, 0) AS bookmarked
            FROM questions_fts
            JOIN questions q ON q.id = questions_fts.rowid
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN topics t ON t.id = q.topic_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            LEFT JOIN user_progress up ON up.question_id = q.id AND up.user_id = ?
            WHERE {where_sql}
            ORDER BY bm25(questions_fts)
            LIMIT ?
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
                0 AS bookmarked
            FROM questions_fts
            JOIN questions q ON q.id = questions_fts.rowid
            JOIN subjects s ON s.id = q.subject_id
            LEFT JOIN topics t ON t.id = q.topic_id
            LEFT JOIN question_explanations qe ON qe.question_id = q.id
            WHERE {where_sql}
            ORDER BY bm25(questions_fts)
            LIMIT ?
        """

    rows = conn.execute(sql, params).fetchall()

    items: list[SearchItemOut] = []
    lower_terms = [t.lower() for t in tokens]
    for row in rows:
        options: list[str] = json.loads(row["options_json"])
        correct_idx = int(row["correct_idx"])
        correct_text = options[correct_idx] if 0 <= correct_idx < len(options) else ""
        stem_norm = _norm_for_match(row["stem"])
        correct_norm = _norm_for_match(correct_text)

        # Every query token must match in stem or in the correct option (never only in distractors).
        if not all(term in stem_norm or term in correct_norm for term in lower_terms):
            continue

        q_out = build_question_out(row)
        matched_in_opts = any(term not in stem_norm and term in correct_norm for term in lower_terms)
        items.append(
            SearchItemOut(
                **q_out.model_dump(),
                matched_in_options=matched_in_opts,
            )
        )
        if len(items) >= limit:
            break

    elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
    return SearchResponse(
        query=q,
        query_terms=tokens,
        elapsed_ms=elapsed,
        total=len(items),
        items=items,
    )
