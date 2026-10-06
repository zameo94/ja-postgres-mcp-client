"""FastAPI application entry point.

The app is created through :func:`create_app` so tests get a fresh instance;
``app`` is the module-level object the ASGI server imports.

The lifespan loads and validates the settings once and builds the shared MCP
client, so a missing or invalid configuration fails at startup rather than on the
first request.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.mcp.client import StreamableHTTPMCPClient

APP_NAME = "ja-postgres-mcp-client"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("starting %s (environment=%s)", APP_NAME, settings.environment)
    app.state.settings = settings
    app.state.mcp = StreamableHTTPMCPClient(settings.mcp_server_url)
    try:
        yield
    finally:
        await app.state.mcp.aclose()
        logger.info("stopped %s", APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app = create_app()


def run() -> None:
    """Run the ASGI server using the configured host, port and log level."""
    import uvicorn

    settings: Settings = get_settings()
    reload = settings.reload if settings.reload is not None else settings.is_development
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=reload,
    )
