from __future__ import annotations

from fastapi import HTTPException

from .config import OLLAMA_BASE_URL


def pick_provider(model_name: str) -> str:
    normalized_model_name = model_name.lower()
    if normalized_model_name.startswith("gpt-"):
        return "https://api.openai.com/v1/chat/completions"
    if normalized_model_name.startswith("claude-"):
        return "https://api.anthropic.com/v1/messages"
    if normalized_model_name:
        return f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    raise HTTPException(status_code=400, detail="Unknown model")
