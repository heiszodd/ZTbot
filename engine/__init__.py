"""Engine package with phase engine modules and legacy engine compatibility."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from . import ict_engine, phase_engine, rules, session_journal

_legacy = None
legacy_path = Path(__file__).resolve().parent.parent / "engine.py"
if legacy_path.exists():
    spec = spec_from_file_location("legacy_engine", legacy_path)
    _legacy = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(_legacy)


def __getattr__(name):
    if _legacy and hasattr(_legacy, name):
        return getattr(_legacy, name)
    raise AttributeError(name)


__all__ = ["ict_engine", "phase_engine", "rules", "session_journal"]
