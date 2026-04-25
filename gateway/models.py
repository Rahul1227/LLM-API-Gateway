from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stream: bool = False
    user: str | None = None
    metadata: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    object: str | None = None
    created: int | None = None
    model: str | None = None
    choices: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None

