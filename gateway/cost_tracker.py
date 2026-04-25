from __future__ import annotations

from . import config


def estimate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    prompt_cost, completion_cost = config.TOKEN_COSTS.get(model_name, (0.0, 0.0))
    return round((prompt_cost * prompt_tokens + completion_cost * completion_tokens) / 1000, 6)


def estimate_text_tokens(text: str) -> int:
    stripped_text = text.strip()
    if not stripped_text:
        return 0
    return max(1, (len(stripped_text) + 3) // 4)


def content_to_text(content: str | list[dict[str, object]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for content_part in content:
        part_text = content_part.get("text") or content_part.get("content")
        if isinstance(part_text, str):
            text_parts.append(part_text)
    return "\n".join(text_parts)


def estimate_prompt_tokens(messages: list[object]) -> int:
    prompt_tokens = 0
    for message in messages:
        message_content = getattr(message, "content", None)
        message_role = str(getattr(message, "role", ""))
        prompt_tokens += 4
        prompt_tokens += estimate_text_tokens(message_role)
        prompt_tokens += estimate_text_tokens(content_to_text(message_content))
    return prompt_tokens


def extract_token_counts(response_body: dict[str, object]) -> tuple[int, int]:
    usage = response_body.get("usage")
    if isinstance(usage, dict):
        prompt_tokens = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("prompt_eval_count")
            or 0
        )
        completion_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("eval_count")
            or 0
        )
        return prompt_tokens, completion_tokens

    prompt_tokens = int(response_body.get("prompt_eval_count") or 0)
    completion_tokens = int(response_body.get("eval_count") or 0)
    return prompt_tokens, completion_tokens
