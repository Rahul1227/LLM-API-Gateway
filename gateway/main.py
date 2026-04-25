from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from redis.asyncio import Redis

from . import config
from .db import init_db_pool, log_violation
from .middleware import CostTrackingMiddleware
from .models import ChatRequest
from .rate_limiter import check_rate_limit
from .router import pick_provider

app = FastAPI(title="LLM API Gateway")
app.add_middleware(CostTrackingMiddleware)


@app.on_event("startup")
async def startup() -> None:
    app.state.redis = Redis.from_url(config.REDIS_URL, decode_responses=True)
    app.state.postgres_pool = await init_db_pool()


@app.on_event("shutdown")
async def shutdown() -> None:
    redis_client: Redis | None = getattr(app.state, "redis", None)
    postgres_pool = getattr(app.state, "postgres_pool", None)
    if redis_client is not None:
        await redis_client.aclose()
    if postgres_pool is not None:
        await postgres_pool.close()


@app.get("/health")
async def health() -> dict[str, str]:
    await app.state.redis.ping()
    async with app.state.postgres_pool.acquire() as connection:
        await connection.fetchval("SELECT 1")
    return {"status": "ok", "redis": "ok", "db": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(
    chat_request: ChatRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_team_id: str | None = Header(default=None),
) -> Response:
    api_key = _extract_api_key(authorization)
    team_id = x_team_id or "default"

    request.state.api_key = api_key
    request.state.team_id = team_id
    request.state.model_name = chat_request.model

    try:
        await check_rate_limit(api_key, request.app.state.redis)
    except HTTPException:
        await log_violation(request.app.state.postgres_pool, api_key, team_id)
        raise

    provider_url = pick_provider(chat_request.model)
    request_body = await request.body()
    upstream_response = await _forward_to_provider(provider_url, request_body, chat_request)
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type", "application/json"),
    )


def _extract_api_key(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    auth_scheme, _, api_key = authorization.partition(" ")
    if auth_scheme.lower() != "bearer" or not api_key.strip():
        raise HTTPException(status_code=401, detail="Use Authorization: Bearer <api_key>")
    return api_key.strip()


async def _forward_to_provider(
    provider_url: str,
    request_body: bytes,
    chat_request: ChatRequest,
) -> httpx.Response:
    if provider_url == "https://api.openai.com/v1/chat/completions":
        return await _call_openai(provider_url, request_body)
    if provider_url == "https://api.anthropic.com/v1/messages":
        return await _call_anthropic(provider_url, chat_request)
    return await _call_ollama(provider_url, chat_request)


async def _call_openai(provider_url: str, request_body: bytes) -> httpx.Response:
    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as http_client:
        try:
            response = await http_client.post(
                provider_url,
                content=request_body,
                headers={
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            logging.error("OpenAI request failed: %s", exc)
            raise HTTPException(status_code=502, detail="OpenAI request failed") from exc
    return _response_or_error(response, "OpenAI")


async def _call_anthropic(provider_url: str, chat_request: ChatRequest) -> httpx.Response:
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    anthropic_payload = _to_anthropic_payload(chat_request)
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as http_client:
        try:
            response = await http_client.post(
                provider_url,
                headers={
                    "x-api-key": config.ANTHROPIC_API_KEY,
                    "anthropic-version": config.ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
                json=anthropic_payload,
            )
        except httpx.HTTPError as exc:
            logging.error("Anthropic request failed: %s", exc)
            raise HTTPException(status_code=502, detail="Anthropic request failed") from exc
    return _response_or_error(response, "Anthropic")


async def _call_ollama(provider_url: str, chat_request: ChatRequest) -> httpx.Response:
    ollama_payload = {
        "model": chat_request.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in chat_request.messages
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as http_client:
        try:
            response = await http_client.post(provider_url, json=ollama_payload)
        except httpx.HTTPError as exc:
            logging.error("Ollama request failed: %s", exc)
            raise HTTPException(status_code=502, detail="Ollama request failed") from exc
    return _response_or_error(response, "Ollama")


def _to_anthropic_payload(chat_request: ChatRequest) -> dict[str, Any]:
    system_messages: list[str] = []
    user_messages: list[dict[str, str]] = []
    for message in chat_request.messages:
        message_content = str(message.content or "")
        if message.role in {"system", "developer"}:
            system_messages.append(message_content)
        else:
            user_messages.append({"role": message.role, "content": message_content})

    anthropic_payload: dict[str, Any] = {
        "model": chat_request.model,
        "messages": user_messages,
        "max_tokens": chat_request.max_tokens or chat_request.max_completion_tokens or 512,
    }
    if system_messages:
        anthropic_payload["system"] = "\n\n".join(system_messages)
    if chat_request.temperature is not None:
        anthropic_payload["temperature"] = chat_request.temperature
    return anthropic_payload


def _response_or_error(response: httpx.Response, provider_name: str) -> httpx.Response:
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    try:
        response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{provider_name} returned a non-JSON response",
        ) from exc
    return response
