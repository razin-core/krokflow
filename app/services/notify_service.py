"""Non-blocking Telegram notifications for admin alerts (e.g., new question reports)."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def send_report_telegram_alert(
    *,
    bot_token: str,
    chat_id: str,
    report_id: int,
    question_id: int,
    reason: str,
    comment: str = "",
    reporter: str = "guest",
) -> bool:
    """Send a concise plain-text alert via Telegram Bot API. Never raises."""
    if not bot_token or not chat_id:
        return False

    clean_comment = " ".join((comment or "").strip().split())[:300] or "—"
    text = (
        f"[KrokFlow] Нова скарга #{report_id}\n"
        f"Питання: #{question_id}\n"
        f"Причина: {reason}\n"
        f"Від: {reporter}\n"
        f"Коментар: {clean_comment}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=5.0,
        )
        if resp.status_code != 200:
            logger.warning("Telegram alert HTTP %s for report #%s", resp.status_code, report_id)
            return False
        return True
    except Exception as exc:  # pragma: no cover - defensive network guard
        logger.warning("Telegram alert failed for report #%s: %s", report_id, exc)
        return False
