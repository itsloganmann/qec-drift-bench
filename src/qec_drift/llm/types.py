"""Provider-neutral request and completion records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Request:
    """One chat request. `extra` carries provider-specific knobs such as `thinking_budget`."""

    system: str
    user: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
    reasoning_effort: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Completion:
    """One model answer, normalised across providers.

    `answer_logprob_sum` and `answer_logprob_mean` are None for API providers.
    `raw` holds the provider response as a JSON-safe dict. `raw_body` is the exact HTTP response
    body as text when the client could read it (Anthropic, OpenAI, Ollama), else None.
    """

    text: str
    reasoning_text: str | None
    finish_reason: str
    input_tokens: int
    output_tokens: int
    answer_logprob_sum: float | None
    answer_logprob_mean: float | None
    raw: dict[str, Any]
    raw_body: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Completion:
        names = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in names})
