"""Chat endpoint request schema.

The backend is stateless: the client sends the full conversation so far, ending
with a user message, plus the provider it selected for this turn. The provider
connection details (base URL, model, API key) are **server configuration**
(environment), never sent by the browser.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProviderId = Literal["ollama", "external_api"]

MAX_MESSAGES = 100
MAX_MESSAGE_CHARS = 20000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    @field_validator("content")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    provider: ProviderId
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def _require_user_last(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self
