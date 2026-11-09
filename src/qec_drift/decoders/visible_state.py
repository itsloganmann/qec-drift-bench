from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pymatching
import stim

from qec_drift.decoders import adaptive

FORMAT = "visible-adaptive-v1"


def save_bank(bank: adaptive.Adaptive, keys: list[tuple[int, ...]], folder: Path) -> None:
    np.savez_compressed(
        folder / "bank.npz",
        base=bank.base,
        w_on=bank.w_on,
        w_off=bank.w_off,
        support=np.array(bank.support, dtype=bool),
    )
    metadata = {
        "format": FORMAT,
        "margin": float(bank.margin),
        "hypotheses": [[sorted(region), factor, kind] for region, factor, kind in bank.hypotheses],
        "warm_keys": keys,
    }
    for i, key in enumerate(keys):
        circuit = bank.stale
        for h in key:
            region, factor, kind = bank.hypotheses[h]
            circuit = adaptive._scaled(circuit, region, factor, kind)
        dem = circuit.detector_error_model(decompose_errors=True)
        # Matchers are reconstructed from these visible-only DEMs within the score deadline.
        (folder / f"warm-{i}.dem").write_text(str(dem))
    (folder / "bank.json").write_text(json.dumps(metadata, indent=2) + "\n")


def load_bank(folder: Path) -> adaptive.Adaptive:
    metadata = json.loads((folder / "bank.json").read_text())
    if metadata["format"] != FORMAT:
        raise ValueError("Unsupported visible adaptive state format")
    bank = adaptive.Adaptive.__new__(adaptive.Adaptive)
    bank.stale = stim.Circuit.from_file(folder / "nominal.stim")
    with np.load(folder / "bank.npz", allow_pickle=False) as data:
        bank.base, bank.w_on, bank.w_off = (data[k] for k in ("base", "w_on", "w_off"))
        bank.support = list(data["support"])
    bank.hypotheses = [
        (frozenset(region), factor, kind) for region, factor, kind in metadata["hypotheses"]
    ]
    bank.margin = metadata["margin"]
    bank._matchers = {
        tuple(key): pymatching.Matching.from_detector_error_model(
            stim.DetectorErrorModel.from_file(folder / f"warm-{i}.dem"), enable_correlations=True
        )
        for i, key in enumerate(metadata["warm_keys"])
    }
    return bank


class Decoder:
    def __init__(self, folder: Path):
        state = json.loads((folder / "fit.json").read_text())
        if state["status"] != "ready":
            raise ValueError("Visible fit is not ready")
        self.mode = state["mode"]
        if self.mode == "adaptive":
            self.bank = load_bank(folder)
        elif self.mode in ("nominal", "refit"):
            self.matcher = pymatching.Matching.from_detector_error_model(
                stim.DetectorErrorModel.from_file(folder / "model.dem"), enable_correlations=True
            )
        else:
            raise ValueError("Unknown decoder mode")

    def decode(self, det: np.ndarray) -> np.ndarray:
        if self.mode == "adaptive":
            return self.bank.decode(det)
        return self.matcher.decode_batch(det, enable_correlations=True)
