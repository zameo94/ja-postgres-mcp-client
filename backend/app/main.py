"""FastAPI application entry point.

The app is created through :func:`create_app` so tests get a fresh instance;
``app`` is the module-level object the ASGI server imports.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router

APP_NAME = "ja-postgres-mcp-client"


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME)
    app.include_router(health_router)
    return app


app = create_app()
