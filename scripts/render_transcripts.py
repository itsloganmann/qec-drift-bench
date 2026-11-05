"""Render every trajectory archive into Markdown transcripts (agent/transcripts.py).

uv run python scripts/render_transcripts.py                 # all archives under trajectories/
uv run python scripts/render_transcripts.py trajectories/agent_launch/decoder_<arm>.jsonl.gz
"""

from __future__ import annotations

import sys
from pathlib import Path

from qec_drift import paths
from qec_drift.agent import transcripts


def main() -> None:
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            archive = Path(arg)
            arm = archive.name.removesuffix(".jsonl.gz").removeprefix("decoder_")
            table = paths.DATA / archive.parent.name / f"{arm}.parquet"
            print(transcripts.render_archive(archive, table))
        return
    for folder in transcripts.render_all():
        print(folder)


if __name__ == "__main__":
    main()
