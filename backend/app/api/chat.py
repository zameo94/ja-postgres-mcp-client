"""Chat streaming endpoint: a thin SSE adapter over the application service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.sse import format_sse
from app.schemas.chat import ChatRequest
from app.services.chat import ChatService

router = APIRouter(tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    service = ChatService(settings=request.app.state.settings, mcp=request.app.state.mcp)

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream(payload):
            yield format_sse(event.name, event.data)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
