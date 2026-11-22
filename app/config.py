"""Configuration settings for KROK Trainer."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB_PATH = BASE_DIR / "data" / "krok.db"
DEFAULT_ENV_PATH = BASE_DIR / ".env"
APP_VERSION = "2.0.0"


def _load_dotenv_file(env_path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from a local .env file without mutating os.environ."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def _load_or_create_secret(db_path: Path, env_map: dict[str, str]) -> str:
    env_secret = (os.environ.get("KROK_TOKEN_SECRET") or env_map.get("KROK_TOKEN_SECRET") or "").strip()
    if env_secret:
        return env_secret

    secret_file = db_path.parent / ".token_secret"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_file.exists():
        stored = secret_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = secrets.token_hex(32)
    secret_file.write_text(generated, encoding="utf-8")
    os.chmod(secret_file, 0o600)
    return generated


def _parse_bool_opt(raw: str | None) -> bool | None:
    if raw is None or not raw.strip():
        return None
    norm = raw.strip().lower()
    if norm in {"1", "true", "yes", "on"}:
        return True
    if norm in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            ids.add(int(p))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    db_path: Path
    host: str
    port: int
    token_secret: str
    telegram_login_bot_token: str
    telegram_login_bot_username: str
    admin_tg_ids: frozenset[int]
    gemini_api_key: str
    gemini_model: str
    explain_daily_limit: int
    cookie_name: str = "krok_session"
    session_ttl_sec: int = 30 * 86400
    auth_max_age_sec: int = 300
    cookie_secure_override: bool | None = None

    @property
    def telegram_auth_enabled(self) -> bool:
        return bool(self.telegram_login_bot_token and self.telegram_login_bot_username)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_override = os.environ.get("KROK_ENV_FILE")
    env_map = (
        {}
        if env_override == ""
        else _load_dotenv_file(Path(env_override) if env_override else DEFAULT_ENV_PATH)
    )

    def _get(name: str, default: str = "") -> str:
        val = os.environ.get(name)
        if val is not None:
            return val.strip()
        return env_map.get(name, default).strip()

    db_path = Path(_get("KROK_DB_PATH", str(DEFAULT_DB_PATH))).resolve()
    admin_raw = _get("KROK_ADMIN_TG_IDS", "")
    bot_username = _get("TELEGRAM_LOGIN_BOT_USERNAME", "").lstrip("@")

    return Settings(
        app_name="KrokFlow · КРОК-1 / ЄДКІ",
        app_version=APP_VERSION,
        db_path=db_path,
        host=_get("KROK_HOST", "127.0.0.1"),
        port=int(_get("KROK_PORT", "8780")),
        token_secret=_load_or_create_secret(db_path, env_map),
        telegram_login_bot_token=_get("TELEGRAM_LOGIN_BOT_TOKEN", ""),
        telegram_login_bot_username=bot_username,
        admin_tg_ids=_parse_admin_ids(admin_raw),
        gemini_api_key=_get("GEMINI_API_KEY", ""),
        gemini_model=_get("KROK_GEMINI_MODEL", "gemini-2.5-flash"),
        explain_daily_limit=max(1, int(_get("KROK_EXPLAIN_DAILY_LIMIT", "30"))),
        cookie_secure_override=_parse_bool_opt(_get("KROK_COOKIE_SECURE", "")),
    )
