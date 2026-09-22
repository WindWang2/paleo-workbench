"""Verify that stopping the global task scheduler before exit removes the
0xC0000005 teardown crash.

Root cause: paleo_workbench.runtime.ensure_global_governance() starts two daemon
worker threads (paleo-heavy-task / paleo-interactive-task) and registers no exit
hook, so they outlive Qt's teardown and QThreadStorage gets destroyed on a live
thread.

Usage: .venv/Scripts/python.exe scratch/verify_scheduler_fix.py
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

faulthandler.enable(
    file=open(REPO_ROOT / ".workbuddy" / "verify_crash.log", "w"), all_threads=True
)


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
    window.show()

    QTimer.singleShot(1200, app.quit)
    app.exec()

    print(f"threads before shutdown: {threading.active_count()}", flush=True)

    # THE FIX: stop scheduler workers before interpreter/Qt teardown.
    from paleo_workbench.runtime import reset_global_scheduler

    reset_global_scheduler()

    survivors = [
        t.name for t in threading.enumerate() if t is not threading.main_thread()
    ]
    print(f"threads after shutdown: {threading.active_count()} -> {survivors}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
