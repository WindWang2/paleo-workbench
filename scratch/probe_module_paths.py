"""Reproduce the app context (QApplication on the real platform) and report
WHICH Qt/qgis DLLs actually got loaded from WHERE.

This is the "who won the DLL slot" diagnostic: anaconda base's Library/bin is on
the machine PATH and ships its own Qt6Core.dll, so a mixed Qt set is a real risk.

Writes .workbuddy/module_paths.txt
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "module_paths.txt"
PLATFORM = os.environ.get("QT_QPA_PLATFORM", "windows")


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def loaded_modules() -> dict[str, str]:
    """basename -> full path for every module in the process."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    pid = k32.GetCurrentProcessId()
    h = k32.OpenProcess(0x1000 | 0x0400, False, pid)  # QUERY_INFO | VM_READ
    if not h:
        return {}
    result: dict[str, str] = {}
    try:
        needed = wintypes.DWORD(0)
        psapi.EnumProcessModules(h, None, 0, ctypes.byref(needed))
        count = needed.value // ctypes.sizeof(ctypes.c_void_p)
        arr = (ctypes.c_void_p * count)()
        if psapi.EnumProcessModules(h, arr, needed, ctypes.byref(needed)):
            buf = ctypes.create_unicode_buffer(32768)
            for i in range(count):
                if psapi.GetModuleFileNameExW(h, arr[i], buf, 32768):
                    p = buf.value
                    result[os.path.basename(p).lower()] = p
    finally:
        k32.CloseHandle(h)
    return result


OUT.write_text("", encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = PLATFORM
log(f"exe      = {sys.executable}")
log(f"platform = {PLATFORM}")
log("")

log("=== PATH entries that contain a Qt6Core.dll (in order) ===")
for d in os.environ.get("PATH", "").split(os.pathsep):
    if d and (Path(d) / "Qt6Core.dll").is_file():
        log(f"  {d}")
log("")

log("step 1: import paleo_workbench")
try:
    import paleo_workbench  # noqa: F401

    log("  OK")
except BaseException as exc:  # noqa: BLE001
    log(f"  FAILED {type(exc).__name__}: {exc}")
log("")

log("step 2: QApplication (real platform) — loads PySide6's Qt fully")
try:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    import PySide6.QtCore as qc

    log(f"  QApplication OK  Qt={qc.qVersion()}  platformName={app.platformName()}")
except BaseException as exc:  # noqa: BLE001
    log(f"  FAILED {type(exc).__name__}: {exc}")
    log(traceback.format_exc())
log("")

mods = loaded_modules()
log(f"=== Qt/qgis/gdal modules loaded BEFORE bridge import ({len(mods)} total) ===")
for k in sorted(mods):
    if k.startswith(("qt6", "qgis", "gdal", "proj", "geos", "qca", "qt6key", "zstd", "shiboken")):
        log(f"  {k:<28} {mods[k]}")
log("")

log("step 3: import qgis_render_bridge")
try:
    import qgis_render_bridge as b

    log(f"  BRIDGE IMPORT OK -> {b.__file__}")
except BaseException as exc:  # noqa: BLE001
    log(f"  BRIDGE IMPORT FAILED: {type(exc).__name__}: {exc}")

mods2 = loaded_modules()
log("")
log("=== Qt/qgis modules loaded AFTER bridge import attempt ===")
for k in sorted(mods2):
    if k.startswith(("qt6", "qgis", "gdal", "proj", "geos", "qca", "qt6key", "zstd", "shiboken")):
        old = mods.get(k)
        flag = "  (new)" if old is None else ""
        log(f"  {k:<28} {mods2[k]}{flag}")
log("")
log("=== END ===")
