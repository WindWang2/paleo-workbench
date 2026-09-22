"""Check for surviving threads / worker jobs at teardown.

The crash log shows `QThreadStorage: entry 1 destroyed before end of thread`,
so a worker thread is very likely still alive when Qt tears down.

Usage: .venv/Scripts/python.exe scratch/diag_threads.py
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
    file=open(REPO_ROOT / ".workbuddy" / "threads_crash.log", "w"), all_threads=True
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

    print("=== threads alive after event loop ===", flush=True)
    for t in threading.enumerate():
        daemon = "daemon" if t.daemon else "NON-DAEMON"
        print(f"  {t.name!r} {daemon} alive={t.is_alive()}", flush=True)
    print(f"  total={threading.active_count()}", flush=True)

    non_main = [t for t in threading.enumerate() if t is not threading.main_thread()]
    print(f"  non-main threads={len(non_main)}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
