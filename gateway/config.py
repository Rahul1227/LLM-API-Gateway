from __future__ import annotations

import os


REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
POSTGRES_DSN: str = os.getenv("POSTGRES_DSN", "postgresql://gateway:gateway@localhost:5432/gatewaydb")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_VERSION: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))

TOKEN_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "llama3.2:1b": (0.00001, 0.00002),  # Local Ollama model - nominal pricing
}
