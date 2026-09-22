"""Is the missing QGIS bridge responsible for the teardown crash?

Replaces ``CompositeDocument._create_canvas`` with a plain QWidget *before* the
window is built, so neither the QGIS shim nor the fallback UnifiedMapCanvas is
ever constructed. Then the app is run for real and allowed to tear down
completely (no os._exit guard), which is the configuration that reproducibly
faults with -1073741819.

    crash still happens -> QGIS/fallback canvas is NOT the culprit
    clean exit          -> the culprit lives in the canvas path
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_app  # noqa: E402  (sets up logging/instrumentation)


def _patch() -> None:
    from PySide6.QtWidgets import QWidget

    from paleo_workbench.ui.workstation import composite_document as cd

    def _plain_canvas(self) -> tuple:
        run_app._log("PATCH: plain QWidget canvas (no QGIS shim, no fallback)")
        return QWidget(self), False

    cd.CompositeDocument._create_canvas = _plain_canvas
    run_app._log("patched CompositeDocument._create_canvas")


if __name__ == "__main__":
    # Disable the guard so the real teardown runs and the fault is observable.
    run_app._HARD_EXIT = False
    _patch()
    code = run_app.main()
    sys.exit(code)  # full CPython finalization — crashes if the bug is present
