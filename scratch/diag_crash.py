"""Locate the 0xC0000005 crash on exit.

The app runs fine (window constructs, event loop returns 0) and only dies
during interpreter teardown, so we enable faulthandler and additionally try an
os._exit() path that skips cleanup entirely to confirm the phase.

Usage:  .venv/Scripts/python.exe scratch/diag_crash.py [--skip-cleanup]
"""
from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CRASH_LOG = REPO_ROOT / ".workbuddy" / "crash.log"
SKIP_CLEANUP = "--skip-cleanup" in sys.argv


def main() -> int:
    log = open(CRASH_LOG, "w", buffering=1)
    faulthandler.enable(file=log, all_threads=True)
    print(f"faulthandler -> {CRASH_LOG}")

    from paleo_workbench.env_bootstrap import load_local_env

    load_local_env()

    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    prepare_bridge_load()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=None)
    window.show()
    print("WINDOW OK", flush=True)

    QTimer.singleShot(1200, app.quit)
    rc = app.exec()
    print(f"EXEC RC={rc}", flush=True)

    # Drop references explicitly before teardown to see whether the crash is
    # driven by PyObject destruction order.
    del window
    del app

    print("about to exit", flush=True)
    if SKIP_CLEANUP:
        # Bypass interpreter/atexit cleanup entirely.
        os._exit(0)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
