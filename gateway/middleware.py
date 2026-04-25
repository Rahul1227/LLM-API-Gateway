from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .cost_tracker import estimate_cost, extract_token_counts
from .db import log_request


class CostTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.monotonic()
        response = await call_next(request)
        response_body = b""
        async for body_chunk in response.body_iterator:
            response_body += body_chunk

        latency_ms = int((time.monotonic() - start_time) * 1000)
        await self._record_request(request, response, response_body, latency_ms)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )

    async def _record_request(
        self,
        request: Request,
        response: Response,
        response_body: bytes,
        latency_ms: int,
    ) -> None:
        if request.url.path != "/v1/chat/completions":
            return

        postgres_pool = getattr(request.app.state, "postgres_pool", None)
        if postgres_pool is None:
            return

        api_key = str(getattr(request.state, "api_key", "unknown"))
        team_id = str(getattr(request.state, "team_id", "unknown"))
        model_name = str(getattr(request.state, "model_name", "unknown"))
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response_json = json.loads(response_body.decode("utf-8")) if response_body else {}
            if isinstance(response_json, dict):
                prompt_tokens, completion_tokens = extract_token_counts(response_json)
                model_name = self._extract_model_name(response_json, model_name)
        except json.JSONDecodeError:
            logging.error("Failed to parse response body for cost tracking")

        cost_usd = estimate_cost(model_name, prompt_tokens, completion_tokens)
        try:
            await log_request(
                postgres_pool,
                api_key,
                team_id,
                model_name,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                latency_ms,
                response.status_code,
            )
        except Exception as exc:
            logging.error("Failed to log request usage: %s", exc)

    @staticmethod
    def _extract_model_name(response_json: dict[str, Any], fallback_model_name: str) -> str:
        response_model = response_json.get("model")
        if isinstance(response_model, str) and response_model:
            return response_model
        return fallback_model_name
