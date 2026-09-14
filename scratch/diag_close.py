"""Reproduce the exit crash along the *real* close path.

Previous diagnostics only ever let exec() return immediately (offscreen has no
window system, so closeEvent/destruction never ran). The user's real GUI crash
happens before "[run_app] exec() returned" is printed, i.e. inside the loop.

Modes:
  close        -- timer fires window.close(); teardown runs normally
  close-quit   -- timer calls app.quit() without closing the window
  noop         -- just exec() (previous behaviour, offscreen returns at once)
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG = REPO_ROOT / ".workbuddy" / "close_crash.log"


def _dump_threads(tag: str, fh) -> None:
    print(f"--- threads [{tag}] total={threading.active_count()} ---", file=fh, flush=True)
    for t in threading.enumerate():
        print(f"    {t.name!r} daemon={t.daemon} alive={t.is_alive()}", file=fh, flush=True)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "close"
    fh = LOG.open("w", encoding="utf-8", errors="replace")
    faulthandler.enable(file=fh, all_threads=True)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.main import (
        _shutdown_render_backends,
        _shutdown_task_scheduler,
    )
    from paleo_workbench.runtime import ensure_global_governance

    try:
        ensure_global_governance()
    except Exception as exc:  # noqa: BLE001
        print(f"governance failed: {exc!r}", file=fh, flush=True)

    app = QApplication(sys.argv)
    print("APP CREATED", file=fh, flush=True)
    window = PaleoWorkbenchWindow(project=None)
    window.show()
    print("WINDOW SHOWN", file=fh, flush=True)

    app.aboutToQuit.connect(_shutdown_render_backends)
    app.aboutToQuit.connect(_shutdown_task_scheduler)
    app.aboutToQuit.connect(lambda: print("ABOUT_TO_QUIT reached", file=fh, flush=True))
    app.aboutToQuit.connect(lambda: _dump_threads("aboutToQuit", fh))

    def fire() -> None:
        print(f"TIMER firing mode={mode}", file=fh, flush=True)
        if mode == "close":
            window.close()
        elif mode == "close-quit":
            app.quit()
        else:
            pass

    QTimer.singleShot(2500, fire)

    rc = app.exec()
    print(f"EXEC RETURNED rc={rc}", file=fh, flush=True)
    _dump_threads("after-exec", fh)
    print("PYTHON TEARDOWN STARTING", file=fh, flush=True)
    return int(rc)


if __name__ == "__main__":
    code = main()
    with LOG.open("a", encoding="utf-8", errors="replace") as fh:
        print(f"CLEAN RETURN rc={code}", file=fh, flush=True)
    sys.exit(code)
