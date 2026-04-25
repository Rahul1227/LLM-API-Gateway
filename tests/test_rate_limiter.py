import asyncio

from fastapi import HTTPException

from gateway.rate_limiter import check_rate_limit


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}

    async def hgetall(self, redis_key: str) -> dict[str, str]:
        return self.values.get(redis_key, {})

    async def hset(self, redis_key: str, mapping: dict[str, float]) -> None:
        self.values[redis_key] = {key: str(value) for key, value in mapping.items()}

    async def expire(self, redis_key: str, seconds: int) -> None:
        return None

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, fake_redis: FakeRedis) -> None:
        self.fake_redis = fake_redis
        self.operations = []

    def hset(self, redis_key: str, mapping: dict[str, float]):
        self.operations.append(("hset", redis_key, mapping))
        return self

    def expire(self, redis_key: str, seconds: int):
        self.operations.append(("expire", redis_key, seconds))
        return self

    async def execute(self) -> None:
        for operation_name, redis_key, operation_value in self.operations:
            if operation_name == "hset":
                await self.fake_redis.hset(redis_key, operation_value)
            if operation_name == "expire":
                await self.fake_redis.expire(redis_key, operation_value)


def test_token_bucket_allows_first_request() -> None:
    fake_redis = FakeRedis()
    assert asyncio.run(check_rate_limit("api-key", fake_redis)) is None


def test_token_bucket_blocks_empty_bucket(monkeypatch) -> None:
    monkeypatch.setattr("gateway.config.RATE_LIMIT_REQUESTS", 1)
    monkeypatch.setattr("gateway.config.RATE_LIMIT_WINDOW_SECONDS", 60)
    fake_redis = FakeRedis()

    asyncio.run(check_rate_limit("api-key", fake_redis))

    try:
        asyncio.run(check_rate_limit("api-key", fake_redis))
    except HTTPException as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("Expected a rate-limit exception")
