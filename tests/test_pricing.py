"""Pricing table: known models price, unknown models return None."""

from qec_drift.llm import pricing


def test_known_model_returns_positive_float():
    usd = pricing.estimate_usd("anthropic", "claude-sonnet-5-5", 1_000_000, 1_000_000)
    assert isinstance(usd, float)
    assert usd == 12.0
    assert pricing.known("anthropic", "claude-sonnet-5-5")


def test_openai_default_model_is_priced():
    usd = pricing.estimate_usd("openai", "gpt-5.6-sol", 1000, 500)
    assert usd is not None
    assert abs(usd - (1000 * 4.0 + 500 * 20.0) / 1e6) < 1e-12


def test_unknown_model_returns_none():
    assert pricing.estimate_usd("openai", "not-a-model", 10, 10) is None
    assert pricing.estimate_usd("nobody", "gpt-5", 10, 10) is None
    assert not pricing.known("openai", "not-a-model")


def test_date_suffix_is_ignored():
    assert pricing.lookup("openai", "gpt-5-2025-08-07") == pricing.lookup("openai", "gpt-5")


def test_zero_tokens_cost_zero():
    assert pricing.estimate_usd("gemini", "gemini-2.5-pro", 0, 0) == 0.0
