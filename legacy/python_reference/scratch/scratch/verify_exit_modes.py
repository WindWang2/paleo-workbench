"""Bisect the teardown 0xC0000005 by exit strategy.

Modes (combinable):
  --stop-scheduler   reset_global_scheduler() before exit
  --gc-disable       gc.disable() before exit
  --del-window       drop the window reference before exit
  --window-only      construct QApplication + window but never show it

Usage: .venv/Scripts/python.exe scratch/verify_exit_modes.py [--flags]
"""
from __future__ import annotations

import faulthandler
import gc
import sys
import threading
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

faulthandler.enable(
    file=open(REPO_ROOT / ".workbuddy" / "modes_crash.log", "w"), all_threads=True
)

ARGS = set(sys.argv[1:])


def main() -> int:
    from paleo_workbench.env_bootstrap import load_local_env

    load_local_env()

    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    prepare_bridge_load()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=None)
    if "--window-only" not in ARGS:
        window.show()
        QTimer.singleShot(1200, app.quit)
        app.exec()

    if "--del-window" in ARGS:
        del window
    if "--stop-scheduler" in ARGS:
        from paleo_workbench.runtime import reset_global_scheduler

        reset_global_scheduler()
    if "--gc-disable" in ARGS:
        gc.disable()
        print("gc disabled", flush=True)

    print(
        f"mode={sorted(ARGS)} threads={threading.active_count()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
