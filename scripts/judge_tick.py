from __future__ import annotations

import math

import judge_transcripts as judge
import usage

LIMIT = 8
CONCURRENCY = 2
MAX_USED = 85


def quota_available() -> bool:
    data = usage.probe(usage.codex)
    raw = [data.get(f"{window}-used-percent") for window in ("primary", "secondary")]
    try:
        if any(isinstance(value, bool) for value in raw):
            raise ValueError("invalid quota")
        values = [float(value) for value in raw]
        if any(not math.isfinite(value) or not 0 <= value <= 100 for value in values):
            raise ValueError("invalid quota")
    except (TypeError, ValueError):
        print("judge quota unknown; skipping reviews", flush=True)
        return False
    allowed = data.get("http-status") == 200 and max(values) < MAX_USED
    print(
        f"judge quota primary {values[0]:g}%, secondary {values[1]:g}%; "
        f"review launches {'allowed' if allowed else 'blocked'}; threshold {MAX_USED}%",
        flush=True,
    )
    return allowed


def main() -> None:
    if quota_available():
        work = judge.pending()[:LIMIT]
        for start in range(0, len(work), CONCURRENCY):
            if not quota_available():
                break
            judge.run(work[start : start + CONCURRENCY], CONCURRENCY)
    judge.DOC.write_text(judge.report())
    print(f"wrote {judge.DOC}", flush=True)


if __name__ == "__main__":
    main()
