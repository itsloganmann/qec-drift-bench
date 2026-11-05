"""Anthropic Messages API client.

`anthropic.Anthropic()` reads the API key and `ANTHROPIC_BASE_URL` from the
environment. Default model: `ANTHROPIC_MODEL` else `claude-sonnet-5-5`.

The installed SDK (2.x) pins API version 2026-10-21, which rejects `temperature`
on every model, and the 5.x models reject `budget_tokens`. So by default this
client sends neither. `req.reasoning_effort` maps to `output_config.effort`.
Knobs in `req.extra`:

- `thinking: "summarized"` sends `{"type": "adaptive", "display": "summarized"}`
  so the thinking summary lands in `reasoning_text` (5.x models, default
  display is omitted).
- `thinking: "off"` sends `{"type": "between_tools"}` (Sonnet 5.5, effort <= high).
- `thinking_budget: N` (legacy, pre-4.6 models only) sends
  `{"type": "enabled", "budget_tokens": N}` with `temperature=1.0`.
- `send_temperature: true` sends `req.temperature` (older API versions only).
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from qec_drift.llm.types import Completion, Request

PROVIDER = "anthropic"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
_FINISH = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError | APITimeoutError | APIConnectionError):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


_RETRY = retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception(_is_retryable),
)


def _thinking(req: Request) -> dict[str, Any] | None:
    budget = req.extra.get("thinking_budget")
    if budget:
        return {"type": "enabled", "budget_tokens": int(budget)}
    mode = req.extra.get("thinking")
    if mode == "summarized":
        return {"type": "adaptive", "display": "summarized"}
    if mode == "off":
        return {"type": "between_tools"}
    return None


def build_kwargs(req: Request) -> dict[str, Any]:
    """Keyword arguments for `client.messages.create`."""
    kwargs: dict[str, Any] = {
        "model": req.model,
        "system": req.system,
        "messages": [{"role": "user", "content": req.user}],
        "max_tokens": int(req.max_tokens),
    }
    thinking = _thinking(req)
    if thinking is not None:
        kwargs["thinking"] = thinking
    if req.reasoning_effort:
        kwargs["output_config"] = {"effort": req.reasoning_effort}
    if req.extra.get("thinking_budget"):
        kwargs["temperature"] = 1.0
    elif req.extra.get("send_temperature"):
        kwargs["temperature"] = float(req.temperature)
    return kwargs


def sent_temperature(req: Request) -> float | None:
    """The temperature that goes on the wire for `req`, or None when none is sent."""
    return build_kwargs(req).get("temperature")


def _dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return dict(obj) if isinstance(obj, dict) else {}


def _split_blocks(content: list[Any]) -> tuple[str, str | None]:
    texts: list[str] = []
    thoughts: list[str] = []
    for block in content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            texts.append(getattr(block, "text", "") or "")
        elif kind == "thinking":
            thought = getattr(block, "thinking", "") or ""
            if thought:
                thoughts.append(thought)
    return "".join(texts), ("\n\n".join(thoughts) or None)


def _input_tokens(usage: Any) -> int:
    total = 0
    for name in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total += int(getattr(usage, name, 0) or 0)
    return total


def to_completion(msg: Any) -> Completion:
    text, reasoning = _split_blocks(getattr(msg, "content", None) or [])
    stop = getattr(msg, "stop_reason", None) or "stop"
    usage = getattr(msg, "usage", None)
    return Completion(
        text=text,
        reasoning_text=reasoning,
        finish_reason=_FINISH.get(stop, str(stop)),
        input_tokens=_input_tokens(usage),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        answer_logprob_sum=None,
        answer_logprob_mean=None,
        raw=_dump(msg),
    )


class AnthropicClient:
    """`complete(req)` with 6 exponential-backoff attempts on 429, timeouts and 5xx."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else Anthropic()

    def complete(self, req: Request, sample_k: int = 0) -> Completion:
        # sample_k only diversifies the cache key; the API has no seed per sample.
        msg, body, request_id = self._create_with_body(build_kwargs(req))
        comp = to_completion(msg)
        comp.raw_body, comp.request_id = body, request_id
        return comp

    def _create(self, kwargs: dict[str, Any]) -> Any:
        return self._create_with_body(kwargs)[0]

    @_RETRY
    def _create_with_body(self, kwargs: dict[str, Any]) -> tuple[Any, str, str | None]:
        """The parsed message, the exact response body, and the request id header."""
        raw = self._client.messages.with_raw_response.create(**kwargs)
        return raw.parse(), raw.http_response.content.decode("utf-8"), raw.headers.get("request-id")
