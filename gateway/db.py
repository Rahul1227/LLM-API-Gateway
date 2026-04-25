from __future__ import annotations

import asyncpg

from .config import POSTGRES_DSN


async def init_db_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=1, max_size=10)


async def log_request(
    pool: asyncpg.Pool,
    api_key: str,
    team_id: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
    status_code: int,
) -> None:
    await pool.execute(
        """
        INSERT INTO request_logs (
            api_key,
            team_id,
            model_name,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            latency_ms,
            status_code
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        api_key,
        team_id,
        model_name,
        prompt_tokens,
        completion_tokens,
        cost_usd,
        latency_ms,
        status_code,
    )


async def log_violation(
    pool: asyncpg.Pool,
    api_key: str,
    team_id: str,
) -> None:
    await pool.execute(
        """
        INSERT INTO rate_limit_violations (api_key, team_id)
        VALUES ($1, $2)
        """,
        api_key,
        team_id,
    )
