"""API contract tests for KROK Trainer FastAPI endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_subjects_catalog(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["verified_questions"] == 7
    assert body["needs_review_questions"] == 1
    assert body["subjects_count"] == 1

    r2 = client.get("/api/v1/subjects")
    assert r2.status_code == 200
    subj = r2.json()["subjects"][0]
    assert subj["slug"] == "microbiology"
    assert subj["total_questions"] == 7
    assert len(subj["modules"]) == 1
    assert len(subj["modules"][0]["topics"]) == 2


def test_fts5_search_precision_and_no_answer_leak(client: TestClient):
    r = client.get("/api/v1/search", params={"q": "шанкеру"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["elapsed_ms"] < 50.0
    item = data["items"][0]
    assert "correct_idx" not in item
    assert len(item["options"]) == 5

    # Special punctuation should never trigger FTS5 syntax errors.
    r_special = client.get("/api/v1/search", params={"q": "Staphylococcus-aureus (плазм)!"})
    assert r_special.status_code == 200
    assert r_special.json()["total"] == 6

    r_no_crash = client.get("/api/v1/search", params={"q": "Staphylococcus-aureus (123)!"})
    assert r_no_crash.status_code == 200
    assert r_no_crash.json()["total"] == 0

    # Distractor-only match must NOT surface; matching the correct option MUST surface.
    r_distractor = client.get("/api/v1/search", params={"q": "Гіалуронідаза"})
    assert r_distractor.status_code == 200
    assert r_distractor.json()["total"] == 0

    r_correct_opt = client.get("/api/v1/search", params={"q": "Плазмокоагулаза"})
    assert r_correct_opt.status_code == 200
    c_data = r_correct_opt.json()
    assert c_data["total"] == 6
    assert all(it["matched_in_options"] is True for it in c_data["items"])

    # Reveal endpoint returns the ground truth answer for search spoiler / flashcards.
    rev = client.get(f"/api/v1/questions/{item['id']}/reveal", params={"salt": item["shuffle_salt"]})
    assert rev.status_code == 200
    assert rev.json()["correct_text"] == "Сифіліс"
    assert rev.json()["correct_option_id"] is not None


def test_quiz_session_fisher_yates_shuffle_and_answer_verification(client: TestClient):
    # Over 40 sessions, the correct answer must NOT always appear at index 0.
    correct_positions: set[int] = set()
    sample_q = None
    for _ in range(40):
        resp = client.post("/api/v1/quiz/session", json={"mode": "train", "limit": 7})
        assert resp.status_code == 200
        questions = resp.json()["questions"]
        assert len(questions) == 7
        target = next(q for q in questions if "твердого шанкеру" in q["stem"])
        sample_q = target
        idx_pos = next(i for i, opt in enumerate(target["options"]) if opt["text"] == "Сифіліс")
        correct_positions.add(idx_pos)

    assert len(correct_positions) >= 3, f"Shuffle seems biased: positions={correct_positions}"

    # Verify right answer grading.
    right_opt = next(o for o in sample_q["options"] if o["text"] == "Сифіліс")
    wrong_opt = next(o for o in sample_q["options"] if o["text"] != "Сифіліс")

    ans_ok = client.post(
        "/api/v1/quiz/answer",
        json={"question_id": sample_q["id"], "selected_option_id": right_opt["option_id"]},
    )
    assert ans_ok.status_code == 200
    assert ans_ok.json()["is_correct"] is True
    assert ans_ok.json()["correct_option_id"] == right_opt["option_id"]

    ans_bad = client.post(
        "/api/v1/quiz/answer",
        json={"question_id": sample_q["id"], "selected_option_id": wrong_opt["option_id"]},
    )
    assert ans_bad.status_code == 200
    assert ans_bad.json()["is_correct"] is False
    assert ans_bad.json()["correct_option_id"] == right_opt["option_id"]

    # Tampered option token must fail cleanly with 400.
    tampered = client.post(
        "/api/v1/quiz/answer",
        json={"question_id": sample_q["id"], "selected_option_id": "deadbeef.0.badsignature"},
    )
    assert tampered.status_code == 400


def test_exam_simulator_grading_threshold_and_breakdown(client: TestClient):
    start = client.post("/api/v1/exam/start", json={"question_count": 7})
    assert start.status_code == 200
    ex = start.json()
    assert ex["total_questions"] == 7
    assert ex["pass_threshold_pct"] == 64

    # Answer 5 right (71.4% >= 64% -> passed) and 2 wrong.
    answers = []
    for idx, q in enumerate(ex["questions"]):
        rev = client.get(f"/api/v1/questions/{q['id']}/reveal", params={"salt": q["shuffle_salt"]}).json()
        if idx < 5:
            opt_id = rev["correct_option_id"]
        else:
            opt_id = next(o["option_id"] for o in q["options"] if o["option_id"] != rev["correct_option_id"])
        answers.append({"question_id": q["id"], "selected_option_id": opt_id})

    sub = client.post(
        "/api/v1/exam/submit",
        json={"exam_id": ex["exam_id"], "duration_sec": 120, "answers": answers},
    )
    assert sub.status_code == 200
    res = sub.json()
    assert res["correct_count"] == 5
    assert res["score_pct"] == 71.4
    assert res["passed"] is True
    assert len(res["breakdown"]) == 2
    assert len(res["weakest_topic_ids"]) >= 1


def test_spa_routes_and_seo_endpoints(client: TestClient):
    for path in ("/", "/module/4", "/topic/1", "/mode/train", "/exam", "/flashcards", "/search?q=тест", "/bookmarks"):
        r = client.get(path)
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    r_bmk_empty = client.get("/api/v1/bookmarks")
    assert r_bmk_empty.status_code == 200
    assert r_bmk_empty.json() == {"total": 0, "items": []}

    search_hit = client.get("/api/v1/search?q=Staphylococcus").json()["items"][0]
    r_bmk_guest = client.get(f"/api/v1/bookmarks?ids={search_hit['id']}")
    assert r_bmk_guest.status_code == 200
    assert r_bmk_guest.json()["total"] == 1
    assert r_bmk_guest.json()["items"][0]["id"] == search_hit["id"]

    r_bmk_sess = client.post("/api/v1/quiz/session", json={"mode": "bookmarks", "question_ids": [search_hit["id"]]})
    assert r_bmk_sess.status_code == 200
    assert r_bmk_sess.json()["total_questions"] == 1

    r_api_404 = client.get("/api/v1/nonexistent")
    assert r_api_404.status_code == 404
    assert r_api_404.headers["content-type"].startswith("application/json")

    r_html_404 = client.get("/nonexistent-qa-test")
    assert r_html_404.status_code == 404
    assert r_html_404.headers["content-type"].startswith("text/html")
    assert "KrokFlow" in r_html_404.text
    assert "404" in r_html_404.text

    r_robots = client.get("/robots.txt")
    assert r_robots.status_code == 200
    assert "Sitemap: https://krokflow.pp.ua/sitemap.xml" in r_robots.text

    r_sitemap = client.get("/sitemap.xml")
    assert r_sitemap.status_code == 200
    assert "<urlset" in r_sitemap.text
    assert "https://krokflow.pp.ua/module/4" in r_sitemap.text

    r_manifest = client.get("/manifest.json")
    assert r_manifest.status_code == 200
    assert "application/manifest+json" in r_manifest.headers["content-type"]
    manifest_data = r_manifest.json()
    assert manifest_data["id"] == "/"
    assert manifest_data["display"] == "standalone"
    assert any(ic.get("sizes") == "192x192" for ic in manifest_data.get("icons", []))

    for icon_path in ("/static/icons/icon-192.png", "/static/icons/icon-512.png"):
        r_icon = client.get(icon_path)
        assert r_icon.status_code == 200
        assert r_icon.headers["content-type"].startswith("image/png")


def test_multi_topic_and_source_tags_filters(client: TestClient):
    subjects = client.get("/api/v1/subjects").json()["subjects"]
    topics = subjects[0]["modules"][0]["topics"]
    topic_ids = [t["id"] for t in topics]
    assert len(topic_ids) == 2

    # Quiz session accepts multiple topic_ids
    r_quiz = client.post("/api/v1/quiz/session", json={"mode": "train", "topic_ids": topic_ids, "limit": 20})
    assert r_quiz.status_code == 200
    assert r_quiz.json()["total_questions"] == 7

    # Single topic_ids filter restricts properly
    r_one = client.post("/api/v1/quiz/session", json={"mode": "train", "topic_ids": [topic_ids[0]], "limit": 20})
    assert r_one.status_code == 200
    assert r_one.json()["total_questions"] == topics[0]["question_count"]
    assert all(q["topic_id"] == topic_ids[0] for q in r_one.json()["questions"])

    # Exam simulator also supports topic_ids filtering
    r_exam = client.post("/api/v1/exam/start", json={"topic_ids": [topic_ids[0]], "question_count": 20})
    assert r_exam.status_code == 200
    assert r_exam.json()["total_questions"] == topics[0]["question_count"]
    assert all(q["topic_id"] == topic_ids[0] for q in r_exam.json()["questions"])
