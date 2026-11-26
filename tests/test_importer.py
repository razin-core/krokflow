"""Unit tests for positional PDF parsing, homoglyph normalization, glued splitting, and dedup."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.db import db_session
from importer.krok_importer import (
    ParsedQuestion,
    _validate_question,
    clean_display_text,
    compute_norm_hash,
    import_questions,
    parse_catdoc_doc,
    parse_dense_kkr_pdf,
    parse_module_pdf,
    split_glued_options_line,
)


def test_homoglyph_normalization_and_dedup_hash():
    # Latin 'i' inside Cyrillic words should clean up for FTS5 while Latin taxa stay intact.
    cleaned = clean_display_text("Мiкробiологiя та Staphylococcus aureus у препаратi")
    assert cleaned == "Мікробіологія та Staphylococcus aureus у препараті"

    h1 = compute_norm_hash("12. В лабораторії виявлено збудника?")
    h2 = compute_norm_hash("В лабoратoрії виявленo збудника?")  # mixed Latin o/i
    assert h1 == h2


def test_glued_options_splitting_kkr_patterns():
    opts1 = split_glued_options_line("Стафілококи Диплококи Мікрококи Стрептококи Тетракоки")
    assert opts1 == ["Стафілококи", "Диплококи", "Мікрококи", "Стрептококи", "Тетракоки"]

    opts2 = split_glued_options_line("Метод Ціля-Нільсена Метод Грама")
    assert opts2 == ["Метод Ціля-Нільсена", "Метод Грама"]

    opts3 = split_glued_options_line("Rotavirus Adenovirus Coxsacki-virus")
    assert opts3 == ["Rotavirus", "Adenovirus", "Coxsacki-virus"]

    opts4 = split_glued_options_line("Ig E Ig А Ig D Ig G Ig M")
    assert opts4 == ["Ig E", "Ig А", "Ig D", "Ig G", "Ig M"]

    opts5 = split_glued_options_line("Проба Манту Проба Шика Нашкірна проба з тулярином Проба Бюрне")
    assert opts5 == ["Проба Манту", "Проба Шика", "Нашкірна проба з тулярином", "Проба Бюрне"]


def test_import_dedup_merges_tags_and_quarantines_bad_counts(tmp_path: Path):
    db_path = tmp_path / "dedup.db"
    q1 = ParsedQuestion(
        stem="У пацієнта з фурункулом виділено Гр+ коки у вигляді грона винограду. Що це?",
        options=["Стафілококи", "Стрептококи", "Диплококи", "Мікрококи", "Тетракоки"],
        topic_title="1. Коки",
        module_no=1,
        status="verified",
    )
    q1_dup = ParsedQuestion(
        stem="У пацієнта з фурункулом виділено Гр+ коки у вигляді грона винограду. Що це?",
        options=["Стафілококи", "Стрептококи", "Диплококи", "Мікрококи", "Тетракоки"],
        topic_title="ККР",
        module_no=4,
        status="verified",
    )
    q_bad = ParsedQuestion(
        stem="Питання без п'ятого варіанта відповіді в джерелі?",
        options=["А", "Б", "В", "Г"],
        topic_title="1. Коки",
        module_no=1,
        status="needs_review",
        review_reason="options_count=4",
    )

    st1 = import_questions(
        [q1, q_bad],
        subject_slug="microbiology",
        subject_title="Мікробіологія",
        subject_icon="🧬",
        source_tag="Загальна мікробіологія",
        file_name="f1.pdf",
        module_no_default=1,
        db_path=db_path,
    )
    assert st1.inserted == 2
    assert st1.verified == 1
    assert st1.needs_review == 1

    st2 = import_questions(
        [q1_dup],
        subject_slug="microbiology",
        subject_title="Мікробіологія",
        subject_icon="🧬",
        source_tag="ККР",
        file_name="kkr.pdf",
        module_no_default=4,
        db_path=db_path,
    )
    assert st2.inserted == 0
    assert st2.duplicates_merged == 1

    with db_session(db_path, read_only=True) as conn:
        rows = conn.execute("SELECT status, source_tags FROM questions ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["status"] == "verified"
        assert json.loads(rows[0]["source_tags"]) == ["Загальна мікробіологія", "ККР"]
        assert rows[1]["status"] == "needs_review"


def test_validate_quarantines_glued_options_and_stems():
    q_opt = _validate_question(
        "Які антитіла з'являються першими?",
        ["IgM", "IgG", "IgA", "IgD", "IgE 2. Наступне питання? A *Так"],
        topic_title="1. Імунологія",
        module_no=1,
        page=1,
    )
    assert q_opt.status == "needs_review"
    assert q_opt.review_reason == "glued_option"

    q_stem = _validate_question(
        "Назвіть ці тільця Гварнієрі Арагао Пашена Люпшютца У дитини 8 років кліщовий енцефаліт?",
        ["Аліментарний", "Контактний", "Молоко кіз", "Пиловий", "Крапельний"],
        topic_title="ККР",
        module_no=4,
        page=1,
    )
    assert q_stem.status == "needs_review"
    assert q_stem.review_reason == "glued_stem"


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def test_real_inbox_parses_without_glued_regression():
    env_inbox = os.environ.get("KROK_INBOX_DIR")
    inbox = Path(env_inbox) if env_inbox else Path.home() / "taildrop_inbox"
    kkr_pdf = inbox / "ККР.pdf"
    vir_pdf = inbox / "База тестових завдань КРОК 1. Вірусологія.pdf"
    doc_file = inbox / "тести по мікробі.doc"

    if _safe_is_file(kkr_pdf):
        kkr_all = parse_dense_kkr_pdf(kkr_pdf)
        kkr_qs = [q for q in kkr_all if q.status == "verified"]
        assert not any(
            "Назвіть ці тільця" in q.stem and "кліщового енцефаліту" in q.stem
            for q in kkr_qs
        )
        assert any("Назвіть ці тільця" in q.stem for q in kkr_all)

    if _safe_is_file(vir_pdf):
        vir_qs = [q for q in parse_module_pdf(vir_pdf, default_module_no=2) if q.status == "verified"]
        assert any("Назвіть ці тільця" in q.stem for q in vir_qs)
        assert any("Ретровірусів" in q.stem and "СНІД" not in q.stem for q in vir_qs)
        assert any("перехід ВІЛ-інфекції в СНІД" in q.stem for q in vir_qs)
        assert any("нагадують колесо" in q.stem and "краснухи" not in q.stem for q in vir_qs)
        assert any("IgM до вірусу краснухи" in q.stem for q in vir_qs)

    if _safe_is_file(doc_file):
        doc_qs = [q for q in parse_catdoc_doc(doc_file) if q.status == "verified"]
        assert len(doc_qs) >= 265
        assert not any("?" in o or len(o) > 220 for q in doc_qs for o in q.options)
