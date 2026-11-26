"""Regression tests ensuring SQLite text columns contain only valid alphabet characters."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.db import db_session

_ALLOWED_TEXT_RE = re.compile(
    r"^[a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9\s\.,;:!\?\-\–\—\(\)\[\]\"'«»“”‘’№%°\+/=<>\*→•·_~&αβγδμΩΑΒΓΔΜ]+$"
)
_FORBIDDEN_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\u007f-\u009f\u4e00-\u9fff\u0800-\u083f\u1600-\u1cff\u3100-\u312f€¤¨ÄÊÌÎ]"
)
_ESCAPED_PERCENT_RE = re.compile(r"\\%")


def _assert_clean_text(value: str, ctx: str) -> None:
    if not value:
        return
    assert not _FORBIDDEN_CHAR_RE.search(value), f"Forbidden char in {ctx}: {value!r}"
    assert not _ESCAPED_PERCENT_RE.search(value), f"Unescaped \\% in {ctx}: {value!r}"
    assert "сифил" not in value.lower(), f"Russianism typo 'сифил*' in {ctx}: {value!r}"
    assert "тести по мікробі" not in value.lower(), f"Colloquial tag 'Тести по мікробі' in {ctx}: {value!r}"
    bad = sorted({ch for ch in value if not _ALLOWED_TEXT_RE.match(ch)})
    assert not bad, f"Unexpected chars {bad} in {ctx}: {value!r}"


def _audit_database(db_path: Path) -> None:
    with db_session(db_path, read_only=True) as conn:
        for r in conn.execute("SELECT id, title_uk FROM subjects"):
            _assert_clean_text(r["title_uk"], f"subjects.id={r['id']}")

        for r in conn.execute("SELECT id, module_no, title_uk FROM topics"):
            _assert_clean_text(r["title_uk"], f"topics.id={r['id']}(M{r['module_no']})")

        for r in conn.execute("SELECT id, stem, options_json, source_tags FROM questions"):
            _assert_clean_text(r["stem"], f"questions.stem id={r['id']}")
            for idx, opt in enumerate(json.loads(r["options_json"])):
                _assert_clean_text(opt, f"questions.opt[{idx}] id={r['id']}")
            for tag in json.loads(r["source_tags"]):
                _assert_clean_text(tag, f"questions.tag id={r['id']}")

        for r in conn.execute(
            "SELECT question_id, markers_json, anchor_uk, explanation_uk, distractors_uk FROM question_explanations"
        ):
            for m in json.loads(r["markers_json"]):
                _assert_clean_text(m, f"explanations.marker qid={r['question_id']}")
            _assert_clean_text(r["anchor_uk"], f"explanations.anchor qid={r['question_id']}")
            _assert_clean_text(r["explanation_uk"], f"explanations.explanation qid={r['question_id']}")
            _assert_clean_text(r["distractors_uk"], f"explanations.distractors qid={r['question_id']}")


def test_fixture_db_text_encoding(test_db_path: Path) -> None:
    _audit_database(test_db_path)


def test_production_db_text_encoding() -> None:
    live_db = Path(__file__).resolve().parents[1] / "data" / "krok.db"
    try:
        has_live_db = live_db.is_file()
    except OSError:
        return
    if has_live_db:
        _audit_database(live_db)
