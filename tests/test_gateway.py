from fastapi import HTTPException

from gateway.main import _extract_api_key
from gateway.router import pick_provider


def test_pick_provider_routes_by_model_prefix() -> None:
    assert pick_provider("gpt-4o") == "https://api.openai.com/v1/chat/completions"
    assert pick_provider("claude-3-5-sonnet") == "https://api.anthropic.com/v1/messages"
    assert pick_provider("llama3").endswith("/api/chat")


def test_extract_api_key_requires_bearer_header() -> None:
    assert _extract_api_key("Bearer test-api-key-1") == "test-api-key-1"

    try:
        _extract_api_key("Basic abc")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected an auth exception")
