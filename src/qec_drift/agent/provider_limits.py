from __future__ import annotations

import re

LIMIT = re.compile(
    r"usage limit|hit your limit|rate limit|rate_limit|too many requests|\b429\b|\b529\b|"
    r"overloaded|out of extra usage|weekly limit|limit resets|capacity",
    re.I,
)


def interrupted(events: list[dict]) -> bool:
    for event in reversed(events):
        kind = event.get("type")
        if kind == "turn.completed":
            return False
        if kind == "turn.failed":
            return bool(LIMIT.search(str((event.get("error") or {}).get("message", ""))))
        if kind == "result":
            return bool(event.get("is_error") and LIMIT.search(str(event.get("result", ""))))
        if kind == "error" and LIMIT.search(str(event.get("message", ""))):
            return True
    return False
