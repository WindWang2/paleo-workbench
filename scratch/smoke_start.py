"""Offscreen boot smoke test.

Constructs the real main window the same way paleo_workbench.main.main() does,
but quits shortly after show() so it can run unattended. Never opens a real
window and never starts the interactive loop for long.

Usage:  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scratch/smoke_start.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from paleo_workbench.env_bootstrap import load_local_env

    load_local_env()

    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    prepare_bridge_load()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("paleo-workbench-smoke")

    from paleo_workbench.app import PaleoWorkbenchWindow

    try:
        window = PaleoWorkbenchWindow(project=None)
    except Exception:
        print("WINDOW CONSTRUCTION FAILED", file=sys.stderr)
        traceback.print_exc()
        return 1

    window.show()
    title = window.windowTitle()
    size = (window.width(), window.height())
    print(f"WINDOW OK title={title!r} size={size}")

    # Let one event loop pass settle construction/threads, then exit.
    QTimer.singleShot(1200, app.quit)
    rc = app.exec()
    print(f"EXEC RC={rc}")
    return 0 if rc == 0 else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
