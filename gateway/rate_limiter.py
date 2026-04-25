from __future__ import annotations

import time

from fastapi import HTTPException
from redis.asyncio import Redis

from . import config


async def check_rate_limit(api_key: str, redis_client: Redis) -> None:
    rate_limit_capacity = float(config.RATE_LIMIT_REQUESTS)
    rate_limit_window = float(config.RATE_LIMIT_WINDOW_SECONDS)
    refill_rate = rate_limit_capacity / rate_limit_window
    current_time = time.time()
    redis_key = f"rate_limit:{api_key}"

    bucket = await redis_client.hgetall(redis_key)
    bucket_tokens = float(bucket.get("tokens", rate_limit_capacity))
    last_refill = float(bucket.get("last_refill", current_time))

    elapsed_seconds = max(0.0, current_time - last_refill)
    bucket_tokens = min(rate_limit_capacity, bucket_tokens + elapsed_seconds * refill_rate)

    if bucket_tokens < 1:
        pipeline = redis_client.pipeline()
        pipeline.hset(redis_key, mapping={"tokens": bucket_tokens, "last_refill": current_time})
        pipeline.expire(redis_key, max(1, int(rate_limit_window * 2)))
        await pipeline.execute()
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    bucket_tokens -= 1
    pipeline = redis_client.pipeline()
    pipeline.hset(redis_key, mapping={"tokens": bucket_tokens, "last_refill": current_time})
    pipeline.expire(redis_key, max(1, int(rate_limit_window * 2)))
    await pipeline.execute()
