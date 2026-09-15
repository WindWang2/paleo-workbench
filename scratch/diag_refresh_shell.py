"""Minimal reproduction: does rebuilding the AppShell fault?

``open_project`` -> ``_refresh_shell`` -> old shell ``deleteLater()`` (deferred)
-> new AppShell built immediately -> new CompositeDocument -> new canvas.

The 12:00 crash trace pointed exactly here (canvas_shim.py:360 inside
QgisCanvasShim.__init__). Triggering _refresh_shell() directly reproduces it
without needing a project file.
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG_DIR = REPO_ROOT / ".workbuddy"
CRASH = LOG_DIR / "refresh_crash.log"
RUN = LOG_DIR / "refresh_run.log"
_START = time.monotonic()
_fh = None


def log(msg: str) -> None:
    line = f"[+{time.monotonic() - _START:6.1f}s] {msg}"
    print(f"[diag] {line}", flush=True)
    if _fh:
        _fh.write(line + "\n")
        _fh.flush()


def _apply_mode(mode: str) -> None:
    """mode=shim (as-is) | noshim (skip QgisCanvasShim) | syncdelete."""
    if mode == "noshim":
        from paleo_workbench.ui.workstation import composite_document as cd

        def _fallback_only(self):
            log("PATCH: UnifiedMapCanvas directly (shim skipped)")
            return cd.UnifiedMapCanvas(parent=self), False

        cd.CompositeDocument._create_canvas = _fallback_only
        log("mode=noshim installed")
    elif mode == "syncdelete":
        log("mode=syncdelete: old shell deleted synchronously before refresh")


def main() -> int:
    global _fh
    mode = sys.argv[1] if len(sys.argv) > 1 else "shim"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _fh = RUN.open("w", encoding="utf-8", errors="replace")
    faulthandler.enable(file=CRASH.open("w", encoding="utf-8", errors="replace"),
                        all_threads=True)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.app import PaleoWorkbenchWindow

    app = QApplication(sys.argv)
    window = PaleoWorkbenchWindow(project=None)
    window.show()
    log(f"window shown mode={mode}")

    _apply_mode(mode)

    def do_refresh() -> None:
        if mode == "syncdelete":
            import shiboken6

            old = window.app_shell
            try:
                old.hide()
                old.shutdown_workers()
                old.setParent(None)
                shiboken6.delete(old)
                log("old shell deleted synchronously")
            except Exception as exc:  # noqa: BLE001
                log(f"sync delete failed: {type(exc).__name__}: {exc}")
        log("calling _refresh_shell()")
        try:
            window._refresh_shell()
            log("_refresh_shell() OK")
        except Exception as exc:  # noqa: BLE001
            log(f"_refresh_shell() raised {type(exc).__name__}: {exc}")

    def finish() -> None:
        log(f"closing (threads={threading.active_count()})")
        window.close()

    QTimer.singleShot(6000, do_refresh)
    QTimer.singleShot(12000, finish)
    rc = app.exec()
    log(f"exec returned rc={rc}")
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
