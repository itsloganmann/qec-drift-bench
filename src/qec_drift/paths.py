"""Repository paths and config loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = REPO_ROOT / "configs"
DATA = REPO_ROOT / "data"
RESULTS = REPO_ROOT / "results"


def trajectories_dir() -> Path:
    """Where every model call is archived. `QEC_DRIFT_TRAJECTORIES` overrides it (tests do)."""
    return Path(os.environ.get("QEC_DRIFT_TRAJECTORIES") or REPO_ROOT / "trajectories")


def load_yaml(name: str) -> dict[str, Any]:
    """Load `configs/<name>.yaml`."""
    with (CONFIGS / f"{name}.yaml").open() as fh:
        return yaml.safe_load(fh)


def models_config() -> dict[str, Any]:
    return load_yaml("models")
