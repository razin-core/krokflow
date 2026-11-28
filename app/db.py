"""SQLite WAL + FTS5 database connection and schema initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    title_uk    TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    icon        TEXT NOT NULL DEFAULT '🧬'
);

CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    module_no   INTEGER NOT NULL DEFAULT 1,
    title_uk    TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(subject_id, module_no, title_uk)
);

CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id   INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    topic_id     INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    norm_hash    TEXT NOT NULL UNIQUE,
    stem         TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_idx  INTEGER NOT NULL DEFAULT 0 CHECK (correct_idx BETWEEN 0 AND 4),
    source_tags  TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'verified',
    created_ts   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_subject_topic
    ON questions(subject_id, topic_id, status);

CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
    stem,
    options_json,
    content='questions',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS trg_q_ai AFTER INSERT ON questions BEGIN
    INSERT INTO questions_fts(rowid, stem, options_json)
    VALUES (new.id, new.stem, new.options_json);
END;

CREATE TRIGGER IF NOT EXISTS trg_q_ad AFTER DELETE ON questions BEGIN
    INSERT INTO questions_fts(questions_fts, rowid, stem, options_json)
    VALUES ('delete', old.id, old.stem, old.options_json);
END;

CREATE TRIGGER IF NOT EXISTS trg_q_au AFTER UPDATE ON questions BEGIN
    INSERT INTO questions_fts(questions_fts, rowid, stem, options_json)
    VALUES ('delete', old.id, old.stem, old.options_json);
    INSERT INTO questions_fts(rowid, stem, options_json)
    VALUES (new.id, new.stem, new.options_json);
END;

CREATE TABLE IF NOT EXISTS question_explanations (
    question_id     INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    markers_json    TEXT NOT NULL DEFAULT '[]',
    anchor_uk       TEXT NOT NULL,
    explanation_uk  TEXT NOT NULL,
    distractors_uk  TEXT NOT NULL DEFAULT '',
    model_id        TEXT NOT NULL DEFAULT '',
    updated_ts      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id        INTEGER NOT NULL UNIQUE,
    username     TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    photo_url    TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT 'student',
    created_ts   INTEGER NOT NULL,
    last_seen_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_id    INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    ease_factor    REAL NOT NULL DEFAULT 2.5,
    interval_days  REAL NOT NULL DEFAULT 0.0,
    reps           INTEGER NOT NULL DEFAULT 0,
    next_review_ts INTEGER NOT NULL DEFAULT 0,
    correct_cnt    INTEGER NOT NULL DEFAULT 0,
    wrong_cnt      INTEGER NOT NULL DEFAULT 0,
    last_wrong_ts  INTEGER NOT NULL DEFAULT 0,
    bookmarked     INTEGER NOT NULL DEFAULT 0,
    updated_ts     INTEGER NOT NULL,
    PRIMARY KEY (user_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_progress_due
    ON user_progress(user_id, next_review_ts);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id   INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    mode         TEXT NOT NULL,
    total_q      INTEGER NOT NULL,
    correct_q    INTEGER NOT NULL,
    duration_sec INTEGER NOT NULL,
    breakdown    TEXT NOT NULL DEFAULT '{}',
    finished_ts  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exam_sessions_user
    ON exam_sessions(user_id, finished_ts DESC);

CREATE TABLE IF NOT EXISTS explain_usage (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_ymd TEXT NOT NULL,
    cnt     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day_ymd)
);

CREATE TABLE IF NOT EXISTS live_rooms (
    code          TEXT PRIMARY KEY,
    host_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    question_ids  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'lobby',
    time_limit_s  INTEGER NOT NULL DEFAULT 900,
    created_ts    INTEGER NOT NULL,
    expires_ts    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS live_room_participants (
    room_code      TEXT NOT NULL REFERENCES live_rooms(code) ON DELETE CASCADE,
    participant_id TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    score          INTEGER NOT NULL DEFAULT 0,
    answered_cnt   INTEGER NOT NULL DEFAULT 0,
    finished_ts    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (room_code, participant_id)
);

CREATE TABLE IF NOT EXISTS question_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    likes_cnt   INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'published',
    created_ts  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS question_note_likes (
    note_id INTEGER NOT NULL REFERENCES question_notes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, user_id)
);

CREATE TABLE IF NOT EXISTS question_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason      TEXT NOT NULL,
    comment     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    created_ts  INTEGER NOT NULL
);
"""


def connect_db(db_path: Path | str | None = None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a configured SQLite connection with WAL and foreign keys."""
    resolved = Path(db_path) if db_path is not None else get_settings().db_path
    if not read_only:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(resolved), timeout=10.0, check_same_thread=False)
    else:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not read_only:
        conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str | None = None) -> Path:
    """Initialize schema in SQLite database and return resolved path."""
    resolved = Path(db_path) if db_path is not None else get_settings().db_path
    conn = connect_db(resolved)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    return resolved


@contextmanager
def db_session(db_path: Path | str | None = None, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Context-managed DB connection with automatic close."""
    conn = connect_db(db_path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency yielding a request-scoped SQLite connection."""
    conn = connect_db()
    try:
        yield conn
    finally:
        conn.close()
