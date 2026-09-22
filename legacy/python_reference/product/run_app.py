"""Launcher for Paleo Workbench on Windows (crash instrumentation + guard).

Why this wrapper exists
-----------------------
The application runs, but the process can fault (0xC0000005) while Qt is
tearing down. Two different teardown crashes have been observed:

* After ``QApplication.exec()`` returns (offscreen reproduction): an extension
  object's destructor touches freed memory. faulthandler reports only
  ``Garbage-collecting`` / ``<no Python frame>``.
* Before ``exec()`` returns (real GUI): the window/destruction path taken on
  close. Nothing after ``exec()`` helps here.

This wrapper therefore does two things:

1. **Instrument** — faulthandler writes every fault to
   ``.workbuddy/gui_crash.log`` (all threads), and a run log with a 5-second
   heartbeat goes to ``.workbuddy/gui_run.log``. The heartbeat tells us whether
   the process died during steady-state running or during shutdown.
2. **Guard** — as the *last* ``aboutToQuit`` handler (so the app's own
   ``_shutdown_render_backends`` / ``_shutdown_task_scheduler`` still run), it
   flushes and calls ``os._exit(0)``, skipping the remaining Qt/CPython
   finalization that faults.

Set ``PALEO_NO_HARD_EXIT=1`` to disable only the guard (instrumentation stays
on) when you want to observe the raw teardown crash instead.

Remove this wrapper once the native teardown bug is fixed upstream.

Usage:  .venv/Scripts/python.exe run_app.py
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG_DIR = REPO_ROOT / ".workbuddy"
CRASH_LOG = LOG_DIR / "gui_crash.log"
RUN_LOG = LOG_DIR / "gui_run.log"

_START = time.monotonic()
_HARD_EXIT = os.environ.get("PALEO_NO_HARD_EXIT", "").strip() not in {"1", "true", "yes"}
_run_fh = None


def _log(msg: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp} +{time.monotonic() - _START:7.1f}s] {msg}"
    try:
        print(f"[run_app] {line}", flush=True)
    except Exception:
        pass
    if _run_fh is not None:
        try:
            _run_fh.write(line + "\n")
            _run_fh.flush()
        except Exception:
            pass


def _rss_mb() -> float | None:
    """Working set in MiB, or None when the platform query is unavailable."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = _PMC()
        pmc.cb = ctypes.sizeof(pmc)
        kernel32 = ctypes.windll.kernel32
        try:
            get_info = kernel32.K32GetProcessMemoryInfo  # Win7+ preferred name
        except AttributeError:
            get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        # Without explicit argtypes/restype the call silently fails on 64-bit.
        get_info.restype = wintypes.BOOL
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        ok = get_info(
            wintypes.HANDLE(kernel32.GetCurrentProcess()), ctypes.byref(pmc), pmc.cb
        )
        return round(pmc.WorkingSetSize / (1024 * 1024), 1) if ok else None
    except Exception:
        return None


def _thread_dump() -> str:
    lines = []
    for t in threading.enumerate():
        lines.append(f"    {t.name!r} daemon={t.daemon} alive={t.is_alive()}")
    return "\n".join(lines)


def _install_guard() -> None:
    """Patch QApplication.exec so our hooks are the last aboutToQuit handlers."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    original_exec = QApplication.exec

    def _exec(self, *args, **kwargs):  # noqa: ANN002, ANN003
        try:
            platform = self.platformName()
        except Exception:
            platform = "?"
        _log(f"EXEC ENTER platform={platform} hardExit={_HARD_EXIT}")

        def _beat() -> None:
            _log(f"ALIVE threads={threading.active_count()} rss={_rss_mb()}MB")

        timer = QTimer(self)
        timer.setInterval(5000)
        timer.timeout.connect(_beat)
        timer.start()
        self._run_app_heartbeat = timer  # keep a reference alive

        # Diagnostic: close every top-level window after N seconds so the
        # shutdown path can be exercised unattended (PALEO_AUTO_QUIT_SECONDS=8).
        auto_quit = os.environ.get("PALEO_AUTO_QUIT_SECONDS", "").strip()
        if auto_quit:
            try:
                delay_ms = int(float(auto_quit) * 1000)
            except ValueError:
                delay_ms = 0
            if delay_ms > 0:

                def _auto_quit() -> None:
                    _log("AUTO QUIT: closing top-level windows")
                    for widget in self.topLevelWidgets():
                        try:
                            widget.close()
                        except Exception:
                            _log(f"close() failed for {widget!r}")

                QTimer.singleShot(delay_ms, _auto_quit)

        def _on_quit() -> None:
            _log(f"ABOUT_TO_QUIT threads={threading.active_count()}\n{_thread_dump()}")
            if _HARD_EXIT:
                _log("HARD EXIT: skipping Qt/CPython finalization (os._exit 0)")
                if _run_fh is not None:
                    try:
                        _run_fh.flush()
                        os.fsync(_run_fh.fileno())
                    except Exception:
                        pass
                os._exit(0)

        # Connected at exec() entry -> runs AFTER main()'s own cleanup hooks.
        self.aboutToQuit.connect(_on_quit)

        # PySide6 exposes QApplication.exec as a no-argument static slot that
        # operates on the C++ singleton, so `self` must NOT be forwarded.
        rc = original_exec()
        _log(f"EXEC RETURNED rc={rc}")
        return rc

    QApplication.exec = _exec  # type: ignore[method-assign]


def main() -> int:
    global _run_fh

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _run_fh = RUN_LOG.open("w", encoding="utf-8", errors="replace")
    crash_fh = CRASH_LOG.open("w", encoding="utf-8", errors="replace")
    faulthandler.enable(file=crash_fh, all_threads=True)

    _log(f"START python={sys.version.split()[0]} cwd={os.getcwd()}")
    _log(f"argv={sys.argv!r}")
    _log(f"logs: crash={CRASH_LOG} run={RUN_LOG}")
    _log(f"guard={'ON' if _HARD_EXIT else 'OFF (PALEO_NO_HARD_EXIT)'}")

    try:
        # The vendored-QGIS loader must claim the DLL search order BEFORE the
        # first `import PySide6.*` (loader.py: "callers on this recipe must run
        # prepare_bridge_load at boot, before any import PySide6.*").
        # _install_guard() below imports PySide6, and on this machine
        # C:\ProgramData\anaconda3\Library\bin sits on PATH shipping its own
        # Qt6Core.dll — so a PySide6-first import lets the wrong Qt take the
        # process slot and the bridge later fails with ERROR_PROC_NOT_FOUND.
        # paleo_workbench.main also prepares the loader, but only when IT is
        # imported, which happens after the guard. Best-effort: never fatal.
        try:
            from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

            report = prepare_bridge_load()
            _log(
                f"QGIS loader prepared recipe={report.recipe} "
                f"dll_dirs={report.dll_dirs} warnings={report.warnings}"
            )
        except Exception:
            _log("QGIS loader prepare skipped:\n" + traceback.format_exc())

        _install_guard()
        from paleo_workbench.main import main as app_main

        _log("APP MODULE IMPORTED")
        rc = app_main()
        rc = int(rc) if isinstance(rc, int) else 0
    except SystemExit as exc:  # main() may raise SystemExit for CLI paths
        rc = int(exc.code) if isinstance(exc.code, int) else 0
        _log(f"SYSTEMEXIT rc={rc}")
    except BaseException:
        _log("UNCAUGHT EXCEPTION\n" + traceback.format_exc())
        raise
    finally:
        _log("MAIN RETURNED")

    _log(f"EXIT rc={rc}")
    return rc


if __name__ == "__main__":
    code = main()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    if _HARD_EXIT:
        # Bypass interpreter finalization; the app's own aboutToQuit cleanup
        # has already run (or the guard exited us from inside the loop).
        os._exit(code)
    # Guard disabled: run the real teardown so the fault is observable.
    sys.exit(code)
