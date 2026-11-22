"""FastAPI application factory for KROK Trainer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, get_settings
from app.db import init_db
from app.routers import auth, catalog, exam, health, quiz, stats


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


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
        if request.url.path == "/" or request.url.path.startswith("/static/"):
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

    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app()
