"""Load this environment's eval/_reference.py by path (maintainer shortcut for the checks below;
a submitted solution has no eval/ folder in a sealed run)."""
import importlib.util
from pathlib import Path


def reference():
    p = Path(__file__).resolve().parents[1] / "eval" / "_reference.py"
    spec = importlib.util.spec_from_file_location("_flux_reference", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
