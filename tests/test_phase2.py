"""Phase 2 tests: Telegram Auth HMAC, SM-2 scheduling, guest sync, and KROK markers/explanations."""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import db_session
from app.schemas import ExplanationOut
from app.services.explain_service import extract_krok_triggers
from app.services.sm2_service import compute_sm2


def _sign_telegram_payload(
    *,
    bot_token: str,
    tg_id: int = 1101846945,
    first_name: str = "Євгеній",
    username: str | None = "Razin_Sarinum",
    auth_date: int | None = None,
) -> dict[str, object]:
    ts = auth_date if auth_date is not None else int(time.time())
    payload: dict[str, object] = {
        "id": tg_id,
        "first_name": first_name,
        "auth_date": ts,
    }
    if username is not None:
        payload["username"] = username
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload.keys()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return payload


def _configure_telegram(monkeypatch, *, bot_token: str = "123456:TEST_BOT_TOKEN") -> str:
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_TOKEN", bot_token)
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_USERNAME", "krokflow_bot")
    monkeypatch.setenv("KROK_ADMIN_TG_IDS", "1101846945")
    get_settings.cache_clear()
    return bot_token


def test_security_headers_include_coop(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.headers["cross-origin-opener-policy"] == "same-origin-allow-popups"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_telegram_auth_lifecycle_and_proxy_secure_cookie(client: TestClient, monkeypatch) -> None:
    # Unconfigured by default
    st0 = client.get("/api/v1/auth/status")
    assert st0.status_code == 200
    assert st0.json()["enabled"] is False
    assert st0.json()["authenticated"] is False

    r_unconf = client.post(
        "/api/v1/auth/telegram",
        json={"id": 1, "first_name": "Guest", "auth_date": int(time.time()), "hash": "0" * 64},
    )
    assert r_unconf.status_code == 503

    token = _configure_telegram(monkeypatch)
    st1 = client.get("/api/v1/auth/status")
    assert st1.json()["enabled"] is True
    assert st1.json()["bot_username"] == "krokflow_bot"

    # Expired payload (> 300s)
    expired_payload = _sign_telegram_payload(bot_token=token, auth_date=int(time.time()) - 3600)
    r_exp = client.post("/api/v1/auth/telegram", json=expired_payload)
    assert r_exp.status_code == 401

    # Tampered hash
    bad_payload = _sign_telegram_payload(bot_token=token)
    bad_payload["first_name"] = "Tampered"
    r_bad = client.post("/api/v1/auth/telegram", json=bad_payload)
    assert r_bad.status_code == 401

    # Valid admin login over simulated Cloudflare HTTPS header -> Secure flag set
    ok_payload = _sign_telegram_payload(bot_token=token, tg_id=1101846945)
    r_https = client.post(
        "/api/v1/auth/telegram",
        json=ok_payload,
        headers={"X-Forwarded-Proto": "https"},
    )
    assert r_https.status_code == 200
    body = r_https.json()
    assert body["authenticated"] is True
    assert body["user"]["role"] == "admin"
    assert body["user"]["username"] == "Razin_Sarinum"
    set_cookie = r_https.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie

    # Normal HTTP login checks cookie works across requests
    user_payload = _sign_telegram_payload(bot_token=token, tg_id=999000111, first_name="Student", username="student_med")
    r_ok = client.post("/api/v1/auth/telegram", json=user_payload)
    assert r_ok.status_code == 200
    assert r_ok.json()["user"]["role"] == "student"

    st2 = client.get("/api/v1/auth/status")
    assert st2.json()["authenticated"] is True
    assert st2.json()["user"]["tg_id"] == 999000111

    r_out = client.post("/api/v1/auth/logout")
    assert r_out.status_code == 200
    st3 = client.get("/api/v1/auth/status")
    assert st3.json()["authenticated"] is False


def test_sm2_math_transitions() -> None:
    now = 1_700_000_000
    # First good recall: interval = 1 day, reps = 1
    ef1, iv1, reps1, next1 = compute_sm2(ease_factor=2.5, interval_days=0.0, reps=0, quality=5, now_ts=now)
    assert reps1 == 1
    assert iv1 == 1.0
    assert next1 == now + 86400

    # Second good recall: interval = 6 days, reps = 2
    ef2, iv2, reps2, _next2 = compute_sm2(ease_factor=ef1, interval_days=iv1, reps=reps1, quality=5, now_ts=now)
    assert reps2 == 2
    assert iv2 == 6.0

    # Lapse (quality=1): resets reps and schedules immediate review
    ef3, iv3, reps3, next3 = compute_sm2(ease_factor=ef2, interval_days=iv2, reps=reps2, quality=1, now_ts=now)
    assert reps3 == 0
    assert iv3 == 1.0
    assert next3 == now
    assert ef3 >= 1.3


def test_sm2_sessions_bookmarks_guest_sync_and_stats(client: TestClient, test_db_path, monkeypatch) -> None:
    # Guest cannot use mistakes mode or stats
    assert client.get("/api/v1/stats/me").status_code == 401
    assert client.post("/api/v1/quiz/session", json={"mode": "mistakes"}).status_code == 401

    token = _configure_telegram(monkeypatch)
    login_res = client.post("/api/v1/auth/telegram", json=_sign_telegram_payload(bot_token=token, tg_id=777111))
    assert login_res.status_code == 200

    # Start training session and submit 1 wrong + 1 right answer
    sess = client.post("/api/v1/quiz/session", json={"mode": "train", "limit": 5}).json()
    q_wrong = sess["questions"][0]
    q_right = sess["questions"][1]

    rev_wrong = client.get(f"/api/v1/questions/{q_wrong['id']}/reveal?salt={q_wrong['shuffle_salt']}").json()
    wrong_opt = next(o["option_id"] for o in q_wrong["options"] if o["option_id"] != rev_wrong["correct_option_id"])
    ans_wrong = client.post(
        "/api/v1/quiz/answer",
        json={"question_id": q_wrong["id"], "selected_option_id": wrong_opt},
    ).json()
    assert ans_wrong["is_correct"] is False

    rev_right = client.get(f"/api/v1/questions/{q_right['id']}/reveal?salt={q_right['shuffle_salt']}").json()
    ans_right = client.post(
        "/api/v1/quiz/answer",
        json={"question_id": q_right["id"], "selected_option_id": rev_right["correct_option_id"]},
    ).json()
    assert ans_right["is_correct"] is True

    # Flashcard SM-2 rating + Bookmark toggle
    fc_res = client.post("/api/v1/flashcards/rate", json={"question_id": q_right["id"], "quality": 5})
    assert fc_res.status_code == 200
    assert fc_res.json()["reps"] == 2

    bm_res = client.post(f"/api/v1/questions/{q_wrong['id']}/bookmark", json={"bookmarked": True})
    assert bm_res.status_code == 200
    assert bm_res.json()["bookmarked"] is True

    # Force q_wrong overdue so smart_mix & mistakes pick it up deterministically
    with db_session(test_db_path) as conn:
        conn.execute(
            "UPDATE user_progress SET next_review_ts = ? WHERE question_id = ?",
            (int(time.time()) - 120, q_wrong["id"]),
        )
        conn.commit()

    mistakes_sess = client.post("/api/v1/quiz/session", json={"mode": "mistakes", "limit": 5}).json()
    assert q_wrong["id"] in [q["id"] for q in mistakes_sess["questions"]]

    weak_sess = client.post("/api/v1/quiz/session", json={"mode": "weak_topics", "limit": 5})
    assert weak_sess.status_code == 200
    assert len(weak_sess.json()["questions"]) >= 1

    # Sync guest progress on another question
    q_extra = sess["questions"][2]
    sync_res = client.post(
        "/api/v1/stats/merge-guest",
        json={
            "attempts": [
                {
                    "question_id": q_extra["id"],
                    "is_correct": True,
                    "quality": 5,
                    "ts": int(time.time()),
                }
            ],
            "bookmarks": [q_extra["id"]],
        },
    )
    assert sync_res.status_code == 200
    assert sync_res.json()["merged_attempts"] == 1
    assert sync_res.json()["merged_bookmarks"] == 1

    # Submit an exam and verify persistence in /stats/me
    ex = client.post("/api/v1/exam/start", json={"question_count": 5}).json()
    ex_answers = [{"question_id": q["id"], "selected_option_id": q["options"][0]["option_id"]} for q in ex["questions"]]
    ex_sub = client.post("/api/v1/exam/submit", json={"exam_id": ex["exam_id"], "duration_sec": 45, "answers": ex_answers})
    assert ex_sub.status_code == 200

    stats = client.get("/api/v1/stats/me").json()
    assert stats["summary"]["attempted_count"] >= 3
    assert stats["bookmarked_questions"]
    assert len(stats["exam_history"]) == 1

    subjects = client.get("/api/v1/subjects").json()
    assert subjects["subjects"][0]["attempted_count"] >= 3
    assert subjects["subjects"][0]["progress_pct"] > 0


def test_cached_explanations_bookmarks_and_no_runtime_llm_endpoint(client: TestClient, test_db_path, monkeypatch) -> None:
    stem = "При темнопольній мікроскопії матеріалу із твердого шанкеру виявлено рухливі спірохети."
    markers, anchor = extract_krok_triggers(stem, "Сифіліс")
    assert markers
    for m in markers:
        assert m in stem
    assert "Сифіліс" in anchor

    # Ensure word-boundary guard never matches short 'ige' inside 'Shigella'
    shigella_stem = "При бактеріологічному дослідженні випорожнень хворого виділена Shigella sonnei."
    shig_markers, _ = extract_krok_triggers(shigella_stem, "Реакція аглютинації")
    assert "ige" not in [m.lower() for m in shig_markers]
    assert any("Shigella sonnei" in m for m in shig_markers)

    # Ensure blue-green pigment / jasmine odor stem matches rich clinical markers
    pseudo_stem = (
        "У хворого з нагноєнням рани при бактеріологічному дослідженні виявлено грамнегативну паличку, "
        "яка на МПА утворює напівпрозорі слизові колонії синьо-зеленого кольору. "
        "Культура має специфічний запах фіалок або жасмину."
    )
    pseudo_markers, _ = extract_krok_triggers(pseudo_stem, "P.aeruginosa")
    assert len(pseudo_markers) >= 2
    assert any("жасмину" in m for m in pseudo_markers)

    # Guest cannot start hints_enabled / mode='hints' session -> 401
    r_guest_hints = client.post("/api/v1/quiz/session", json={"mode": "hints", "hints_enabled": True, "limit": 3})
    assert r_guest_hints.status_code == 401

    search = client.get("/api/v1/search?q=темнопольн").json()
    qid = search["items"][0]["id"]

    # Runtime on-demand LLM /explain endpoint must NOT exist (0 LLM spend at runtime).
    r_explain = client.post(f"/api/v1/questions/{qid}/explain")
    assert r_explain.status_code in (404, 405)

    # Login user, pre-seed cached explanation in SQLite, verify hints + bookmarks endpoint & mode
    token = _configure_telegram(monkeypatch)
    client.post("/api/v1/auth/telegram", json=_sign_telegram_payload(bot_token=token, tg_id=555222, first_name="U"))

    from app.db import db_session
    from app.services.explain_service import save_explanation

    with db_session(test_db_path) as conn:
        save_explanation(
            conn,
            qid=qid,
            markers=["темнопольній мікроскопії", "твердого шанкеру"],
            anchor_uk="твердий шанкр → Treponema pallidum",
            explanation_uk="Первинний сифіліс виявляють темнопільною мікроскопією.",
            distractors_uk="Борелії більші за розміром.",
            model_id="pregen-cache-v1",
            commit=True,
        )

    r_auth_hints = client.post("/api/v1/quiz/session", json={"mode": "hints", "hints_enabled": True, "limit": 3})
    assert r_auth_hints.status_code == 200
    assert r_auth_hints.json()["hints_enabled"] is True

    rev = client.get(f"/api/v1/questions/{qid}/reveal").json()
    assert rev["explanation"]["anchor_uk"] == "твердий шанкр → Treponema pallidum"

    client.post(f"/api/v1/questions/{qid}/bookmark", json={"bookmarked": True})
    r_bmk = client.get("/api/v1/bookmarks")
    assert r_bmk.status_code == 200
    assert r_bmk.json()["total"] == 1
    assert r_bmk.json()["items"][0]["id"] == qid

    r_bmk_sess = client.post("/api/v1/quiz/session", json={"mode": "bookmarks", "limit": 10})
    assert r_bmk_sess.status_code == 200
    assert r_bmk_sess.json()["total_questions"] == 1
    assert r_bmk_sess.json()["questions"][0]["id"] == qid


def test_reset_user_stats_keep_and_clear_bookmarks(client: TestClient, monkeypatch) -> None:
    assert client.post("/api/v1/stats/reset").status_code == 401
    token = _configure_telegram(monkeypatch)

    # User A logs in, answers 1 question, bookmarks it, and completes 1 exam session
    client.post(
        "/api/v1/auth/telegram",
        json=_sign_telegram_payload(bot_token=token, tg_id=888101, first_name="UserA", username="user_a"),
    )
    sess = client.post("/api/v1/quiz/session", json={"mode": "train", "limit": 3}).json()
    q1 = sess["questions"][0]
    rev1 = client.get(f"/api/v1/questions/{q1['id']}/reveal?salt={q1['shuffle_salt']}").json()
    wrong_opt = next(o["option_id"] for o in q1["options"] if o["option_id"] != rev1["correct_option_id"])
    client.post("/api/v1/quiz/answer", json={"question_id": q1["id"], "selected_option_id": wrong_opt})
    client.post(f"/api/v1/questions/{q1['id']}/bookmark", json={"bookmarked": True})

    ex = client.post("/api/v1/exam/start", json={"question_count": 5}).json()
    ex_answers = [{"question_id": q["id"], "selected_option_id": q["options"][0]["option_id"]} for q in ex["questions"]]
    client.post("/api/v1/exam/submit", json={"exam_id": ex["exam_id"], "duration_sec": 30, "answers": ex_answers})

    # User B logs in and records 1 answer (must NOT be affected when User A resets)
    client.post(
        "/api/v1/auth/telegram",
        json=_sign_telegram_payload(bot_token=token, tg_id=888102, first_name="UserB", username="user_b"),
    )
    q_b = client.post("/api/v1/quiz/session", json={"mode": "train", "limit": 2}).json()["questions"][0]
    client.post("/api/v1/quiz/answer", json={"question_id": q_b["id"], "selected_option_id": q_b["options"][0]["option_id"]})
    assert client.get("/api/v1/stats/me").json()["summary"]["attempted_count"] == 1

    # Switch back to User A and reset keeping bookmarks
    client.post(
        "/api/v1/auth/telegram",
        json=_sign_telegram_payload(bot_token=token, tg_id=888101, first_name="UserA", username="user_a"),
    )
    r_keep = client.post("/api/v1/stats/reset", json={"keep_bookmarks": True})
    assert r_keep.status_code == 200
    assert r_keep.json()["reset"] is True
    assert r_keep.json()["reset_bookmarked_rows"] == 1
    assert r_keep.json()["deleted_exam_sessions"] == 1

    st_after_keep = client.get("/api/v1/stats/me").json()
    assert st_after_keep["summary"]["attempted_count"] == 0
    assert st_after_keep["summary"]["due_count"] == 0
    assert st_after_keep["summary"]["mistakes_count"] == 0
    assert st_after_keep["summary"]["bookmarked_count"] == 1
    assert st_after_keep["exam_history"] == []

    # Reset clearing bookmarks as well
    r_wipe = client.post("/api/v1/stats/reset", json={"keep_bookmarks": False})
    assert r_wipe.status_code == 200
    st_after_wipe = client.get("/api/v1/stats/me").json()
    assert st_after_wipe["summary"]["bookmarked_count"] == 0

    # User B's analytics remain completely intact
    client.post(
        "/api/v1/auth/telegram",
        json=_sign_telegram_payload(bot_token=token, tg_id=888102, first_name="UserB", username="user_b"),
    )
    assert client.get("/api/v1/stats/me").json()["summary"]["attempted_count"] == 1


def test_pharmacology_and_pathomorphology_offline_triggers() -> None:
    pharm_stem = (
        "Після закапування в око крапель у хворого на глаукому розвинувся міоз і короткозорість. "
        "Внутрішньоочний тиск знизився."
    )
    pharm_markers, pharm_anchor = extract_krok_triggers(
        pharm_stem,
        "М-холіноміметики",
        subject_slug="pharmacology",
    )
    assert pharm_markers
    for m in pharm_markers:
        assert m in pharm_stem
    assert "М-холіноміметики" in pharm_anchor

    path_stem = "На розтині померлого виявлено тигрове серце, при забарвленні Судан III — жирову дистрофію міокарда."
    path_markers, path_anchor = extract_krok_triggers(
        path_stem,
        "Паренхіматозна жирова дистрофія",
        subject_slug="pathomorphology",
    )
    assert path_markers
    for m in path_markers:
        assert m in path_stem
    assert "Паренхіматозна жирова дистрофія" in path_anchor


def test_question_report_endpoint_validation_dedup_and_ratelimit(client: TestClient, monkeypatch) -> None:
    from app.services.rate_limit import report_ip_limiter

    report_ip_limiter.reset()
    try:
        assert client.post("/api/v1/questions/999999/report", json={"reason": "wrong_key"}).status_code == 404

        search_hit = client.get("/api/v1/search?q=Staphylococcus").json()["items"][0]
        qid = search_hit["id"]

        r_bad_other = client.post(f"/api/v1/questions/{qid}/report", json={"reason": "other", "comment": "   "})
        assert r_bad_other.status_code == 400

        r_guest = client.post(
            f"/api/v1/questions/{qid}/report",
            json={"reason": "wrong_key", "comment": "  Ключ   B  "},
        )
        assert r_guest.status_code == 200
        d1 = r_guest.json()
        assert d1["question_id"] == qid
        assert d1["already_reported"] is False
        assert d1["status"] == "open"

        r_guest_dup = client.post(
            f"/api/v1/questions/{qid}/report",
            json={"reason": "wrong_key", "comment": "Ключ B"},
        )
        assert r_guest_dup.status_code == 200
        assert r_guest_dup.json()["id"] == d1["id"]
        assert r_guest_dup.json()["already_reported"] is True

        token = _configure_telegram(monkeypatch)
        client.post(
            "/api/v1/auth/telegram",
            json=_sign_telegram_payload(bot_token=token, tg_id=777999, first_name="RepUser", username="rep_user"),
        )
        r_auth = client.post(
            f"/api/v1/questions/{qid}/report",
            json={"reason": "text_error", "comment": "Одрук у варіанті A"},
        )
        assert r_auth.status_code == 200
        d2 = r_auth.json()
        assert d2["already_reported"] is False

        r_auth_dup = client.post(
            f"/api/v1/questions/{qid}/report",
            json={"reason": "duplicate", "comment": "Повтор"},
        )
        assert r_auth_dup.status_code == 200
        assert r_auth_dup.json()["id"] == d2["id"]
        assert r_auth_dup.json()["already_reported"] is True

        statuses = [
            client.post(f"/api/v1/questions/{qid}/report", json={"reason": "duplicate", "comment": f"burst {i}"}).status_code
            for i in range(6)
        ]
        assert 429 in statuses
    finally:
        report_ip_limiter.reset()
