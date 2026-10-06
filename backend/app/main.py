"""FastAPI application entry point.

The app is created through :func:`create_app` so tests get a fresh instance;
``app`` is the module-level object the ASGI server imports.

The lifespan loads and validates the settings once, so a missing or invalid
configuration fails at startup rather than on the first request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings, get_settings

APP_NAME = "ja-postgres-mcp-client"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = get_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()


def run() -> None:
    """Run the ASGI server using the configured host, port and log level."""
    import uvicorn

    settings: Settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.is_development,
    )
