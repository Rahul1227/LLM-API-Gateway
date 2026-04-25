from gateway.cost_tracker import estimate_cost, estimate_text_tokens


def test_estimate_text_tokens_counts_non_empty_text() -> None:
    assert estimate_text_tokens("hello") >= 1
    assert estimate_text_tokens("") == 0


def test_cost_estimate_uses_per_1k_pricing() -> None:
    assert estimate_cost("gpt-3.5-turbo", 1000, 500) == 0.00125


def test_ollama_models_are_free_for_local_project() -> None:
    assert estimate_cost("llama3", 1000, 500) == 0.0
