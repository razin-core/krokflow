"""FastAPI application factory for KROK Trainer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, get_settings
from app.db import init_db
from app.routers import auth, catalog, exam, health, quiz, stats


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


_SPA_PREFIXES = ("/module/", "/topic/", "/mode/", "/subject/")
_SPA_EXACT = {"/", "/exam", "/flashcards", "/search", "/profile"}


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

    @app.get("/", include_in_schema=False)
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
    def serve_spa_named() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/robots.txt", include_in_schema=False)
    def serve_robots() -> PlainTextResponse:
        return PlainTextResponse(
            "User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: https://krokflow.pp.ua/sitemap.xml\n"
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def serve_sitemap() -> Response:
        urls = [
            "https://krokflow.pp.ua/",
            "https://krokflow.pp.ua/module/1",
            "https://krokflow.pp.ua/module/2",
            "https://krokflow.pp.ua/module/3",
            "https://krokflow.pp.ua/module/4",
            "https://krokflow.pp.ua/module/5",
            "https://krokflow.pp.ua/exam",
            "https://krokflow.pp.ua/flashcards",
        ]
        entries = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
        return Response(content=xml, media_type="application/xml")

    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app()
