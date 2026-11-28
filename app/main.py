"""FastAPI application factory for KROK Trainer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import STATIC_DIR, get_settings
from app.db import db_session, init_db
from app.routers import auth, catalog, exam, health, quiz, stats


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


_SPA_PREFIXES = ("/module/", "/topic/", "/mode/", "/subject/")
_SPA_EXACT = {"/", "/exam", "/flashcards", "/search", "/profile", "/bookmarks"}


def _is_spa_path(path: str) -> bool:
    return path in _SPA_EXACT or path.startswith(_SPA_PREFIXES)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        # Allow Telegram Login OAuth popup communication (modern-web-guidance security §3.4).
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        if _is_spa_path(request.url.path) or request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(catalog.router, prefix="/api/v1")
    app.include_router(quiz.router, prefix="/api/v1")
    app.include_router(exam.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def serve_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/module/{module_no}", include_in_schema=False)
    def serve_spa_module(module_no: int) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/topic/{topic_id}", include_in_schema=False)
    def serve_spa_topic(topic_id: int) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/mode/{mode_name}", include_in_schema=False)
    def serve_spa_mode(mode_name: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/subject/{subject_id}", include_in_schema=False)
    def serve_spa_subject(subject_id: int) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/exam", include_in_schema=False)
    @app.get("/flashcards", include_in_schema=False)
    @app.get("/search", include_in_schema=False)
    @app.get("/profile", include_in_schema=False)
    @app.get("/bookmarks", include_in_schema=False)
    def serve_spa_named() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/robots.txt", include_in_schema=False)
    def serve_robots() -> PlainTextResponse:
        return PlainTextResponse(
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Disallow: /auth/\n"
            "Sitemap: https://krokflow.pp.ua/sitemap.xml\n"
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def serve_sitemap() -> Response:
        urls = [
            "https://krokflow.pp.ua/",
            "https://krokflow.pp.ua/search",
            "https://krokflow.pp.ua/exam",
            "https://krokflow.pp.ua/flashcards",
        ]
        try:
            with db_session() as conn:
                rows = conn.execute("SELECT id FROM subjects ORDER BY id").fetchall()
            for row in rows:
                urls.append(f"https://krokflow.pp.ua/subject/{int(row['id'])}")
        except Exception:
            pass
        entries = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
        return Response(content=xml, media_type="application/xml")

    @app.get("/manifest.json", include_in_schema=False)
    def serve_manifest() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "manifest.json",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon() -> Response:
        return Response(status_code=204)

    _NOT_FOUND_HTML = f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>404 · Сторінку не знайдено · KrokFlow</title>
  <link rel="stylesheet" href="/static/css/app.css?v={settings.app_version}">
</head>
<body>
  <main class="container app-main" style="max-width:620px;margin-top:48px">
    <section class="card stack-md" style="text-align:center;padding:32px 24px">
      <div style="font-size:42px;font-weight:800;letter-spacing:-0.03em;color:var(--accent-primary)">404</div>
      <h1 style="margin:0">Сторінку не знайдено</h1>
      <p class="muted" style="margin:0">Запитаної адреси не існує в KrokFlow. Можливо, посилання застаріло або містить помилку.</p>
      <div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:8px">
        <a href="/" class="btn btn-primary" style="text-decoration:none">← Повернутися на головну KrokFlow</a>
      </div>
    </section>
  </main>
</body>
</html>"""

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            return HTMLResponse(content=_NOT_FOUND_HTML, status_code=404)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app


app = create_app()
