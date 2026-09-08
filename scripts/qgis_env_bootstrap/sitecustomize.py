"""Auto-imported by every Python child launched with PYTHONPATH pointing here.

Runs BEFORE any test/user import, so the MSVCP pre-pin and the QGIS loader
dirs win the race against numpy's trimmed msvcp140 (V7 loader bisection).
Kept under scripts/ so the repo root stays clean; opt-in via PYTHONPATH.
"""

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_LAUNCHER = _REPO / "scripts" / "run_qgis_env.py"


def _apply() -> None:
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_pwb_qgis_env", _LAUNCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.prepare()
        os.environ["PALEO_QGIS_BOOTSTRAP_APPLIED"] = "1"
    except Exception:
        if os.environ.get('PALEO_QGIS_ENV_DEBUG'):
            import traceback; traceback.print_exc()
        # Environment bootstrap must never break the interpreter; the bridge
        # tests skip honestly when the load fails.
        pass


if os.environ.get("PALEO_QGIS_ENV_BOOTSTRAP", "1") not in ("0", "false", "no"):
    _apply()
