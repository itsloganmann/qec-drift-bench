"""List prices in USD per 1M tokens, used only to cap and report spend.

`estimate_usd` returns None for an unknown (provider, model). None means "unknown",
not "free": the runner counts it as 0, prints a warning, and does not enforce
`max_usd` for that model. Add rows here or under `pricing:` in `configs/models.yaml`.

Sources (standard tier, short context, no cache discounts):
- OpenAI: https://developers.openai.com/api/docs/pricing (read 2026-10-28)
- Anthropic: claude-api skill model table (cached 2026-10-06)
- Google: https://ai.google.dev/gemini-api/docs/pricing (page dated 2026-10-28,
  prompts up to 200k tokens)
"""

from __future__ import annotations

import re
from functools import lru_cache

from qec_drift import paths

# (provider, model) -> (input_usd_per_mtok, output_usd_per_mtok)
PRICES: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-5.6-sol"): (4.00, 20.00),
    ("openai", "gpt-5.6-terra"): (2.00, 12.00),
    ("openai", "gpt-5.6-luna"): (0.20, 1.20),
    ("openai", "gpt-5.2"): (1.75, 14.00),
    ("openai", "gpt-5.1"): (1.25, 10.00),
    ("openai", "gpt-5"): (1.25, 10.00),
    ("openai", "gpt-5-mini"): (0.25, 2.00),
    ("openai", "gpt-5-nano"): (0.05, 0.40),
    ("anthropic", "claude-opus-5-5"): (4.00, 20.00),
    ("anthropic", "claude-sonnet-5-5"): (2.00, 10.00),
    ("anthropic", "claude-haiku-5-5"): (0.10, 0.50),
    ("anthropic", "claude-opus-5"): (5.00, 25.00),
    ("anthropic", "claude-sonnet-5"): (2.00, 10.00),
    ("anthropic", "claude-opus-4-8"): (5.00, 25.00),
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-haiku-4-5"): (1.00, 5.00),
    ("gemini", "gemini-2.5-pro"): (1.25, 10.00),
    ("gemini", "gemini-2.5-flash"): (0.30, 2.50),
}

_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")


@lru_cache(maxsize=1)
def _table() -> dict[tuple[str, str], tuple[float, float]]:
    """Builtin table plus the optional `pricing:` section of configs/models.yaml."""
    table = dict(PRICES)
    overrides = paths.models_config().get("pricing") or {}
    for provider, models in overrides.items():
        for model, row in (models or {}).items():
            table[(provider, model)] = (float(row["input"]), float(row["output"]))
    return table


def lookup(provider: str, model: str) -> tuple[float, float] | None:
    """Prices for a model; a trailing `-YYYY-MM-DD` snapshot suffix is ignored.

    Local providers (ollama) cost nothing, whatever the model.
    """
    if provider == "ollama":
        return (0.0, 0.0)
    table = _table()
    hit = table.get((provider, model))
    if hit is None:
        hit = table.get((provider, _DATE_SUFFIX.sub("", model)))
    return hit


def known(provider: str, model: str) -> bool:
    return lookup(provider, model) is not None


def estimate_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Spend for one call, or None when the model is not in the table."""
    prices = lookup(provider, model)
    if prices is None:
        return None
    in_price, out_price = prices
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0
