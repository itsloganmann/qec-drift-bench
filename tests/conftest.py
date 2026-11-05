"""Keep test runs out of the repo's trajectories folder."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_trajectories(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("QEC_DRIFT_TRAJECTORIES", str(tmp_path_factory.mktemp("trajectories")))
