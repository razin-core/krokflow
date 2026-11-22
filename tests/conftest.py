"""Pytest fixtures providing isolated temp SQLite database and TestClient."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services.rate_limit import auth_ip_limiter, explain_ip_limiter
from importer.krok_importer import ParsedQuestion, import_questions


@pytest.fixture()
def test_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "krok_test.db"
    monkeypatch.setenv("KROK_ENV_FILE", "")
    monkeypatch.setenv("KROK_DB_PATH", str(db_path))
    monkeypatch.setenv("KROK_TOKEN_SECRET", "test-secret-key-for-pytest-only-32bytes")
    auth_ip_limiter.reset()
    explain_ip_limiter.reset()
    get_settings.cache_clear()

    # Seed realistic sample questions across 2 topics + 1 cached explanation + 1 quarantine row.
    sample_questions = [
        ParsedQuestion(
            stem=f"У пацієнта {i} з ранового вмісту виділено Staphylococcus aureus. Який фермент забезпечує коагуляцію плазми?",
            options=["Плазмокоагулаза", "Гіалуронідаза", "Каталаза", "Лецитиназа", "Фібринолізин"],
            topic_title="1. Стафілококи і стрептококи",
            module_no=3,
            status="verified",
            page=i,
        )
        for i in range(1, 7)
    ] + [
        ParsedQuestion(
            stem="При темнопольній мікроскопії матеріалу із твердого шанкеру виявлено рухливі спірохети. Збудник якого захворювання це?",
            options=["Сифіліс", "Бореліоз", "Лептоспіроз", "Поворотний тиф", "Гонорея"],
            topic_title="14. Спірохети",
            module_no=3,
            status="verified",
            page=10,
        ),
        ParsedQuestion(
            stem="Дефектне тестове питання з чотирма варіантами відповіді?",
            options=["Варіант 1", "Варіант 2", "Варіант 3", "Варіант 4"],
            topic_title="14. Спірохети",
            module_no=3,
            status="needs_review",
            review_reason="options_count=4",
            page=11,
        ),
    ]
    import_questions(
        sample_questions,
        subject_slug="microbiology",
        subject_title="Мікробіологія",
        subject_icon="🧬",
        source_tag="Спеціальна бактеріологія",
        file_name="test.pdf",
        module_no_default=3,
        db_path=db_path,
    )
    yield db_path
    get_settings.cache_clear()


@pytest.fixture()
def client(test_db_path: Path) -> TestClient:
    app = create_app()
    with TestClient(app) as tc:
        yield tc
