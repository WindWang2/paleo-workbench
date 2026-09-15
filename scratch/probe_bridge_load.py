"""Decisive experiment: does the Qt 6.8.0 (deps) vs 6.11.2 (PySide6) split break
the bridge load, or is it only the missing geo DLL search paths?

Run modes:
  pyfirst  — deps DLL dirs on PATH, import PySide6 FIRST, then the bridge
             (this is what the real app does)
  qgisfirst— deps Qt 6.8.0 bin FIRST, then import the bridge, then PySide6

Usage:  python scratch/probe_bridge_load.py <pyfirst|qgisfirst>
Writes .workbuddy/bridge_load_<mode>.txt
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODE = sys.argv[1] if len(sys.argv) > 1 else "pyfirst"
OUT = REPO / ".workbuddy" / f"bridge_load_{MODE}.txt"

QT_BIN = Path("C:/deps/Qt/6.8.0/msvc2022_64/bin")
DEPS_BINS = [
    QT_BIN,
    Path("C:/deps/vcpkg/installed/x64-windows/bin"),
    Path("C:/deps/kc-install/bin"),
    Path("C:/deps/qca-install/bin"),
    Path("C:/deps/qscintilla-install/bin"),
]
VENDOR_BIN = REPO / "native/qgis_render_bridge/build/qgis-vendor/output/bin"
PROJ_DATA = Path("C:/deps/vcpkg/installed/x64-windows/share/proj")


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")
log(f"mode     = {MODE}")
log(f"exe      = {sys.executable}")

for d in DEPS_BINS:
    if d.is_dir():
        os.add_dll_directory(str(d))
os.add_dll_directory(str(VENDOR_BIN))
os.environ["PATH"] = (
    os.pathsep.join([str(p) for p in DEPS_BINS] + [str(VENDOR_BIN)])
    + os.pathsep
    + os.environ.get("PATH", "")
)
os.environ.setdefault("PROJ_DATA", str(PROJ_DATA))
os.environ.setdefault("PROJ_LIB", str(PROJ_DATA))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
log(f"PATH head = {os.pathsep.join([str(p) for p in DEPS_BINS])[:200]}")
log("")


def try_pyside(tag: str) -> bool:
    try:
        import PySide6.QtCore as qtcore

        log(f"[{tag}] PySide6 OK  Qt={qtcore.qVersion()}")
        return True
    except BaseException as exc:  # noqa: BLE001
        log(f"[{tag}] PySide6 FAILED: {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return False


def try_bridge(tag: str) -> bool:
    try:
        import qgis_render_bridge as b

        log(f"[{tag}] BRIDGE IMPORT OK  {b.__file__}")
        for fn in ("version", "runtime_facts"):
            obj = getattr(b, fn, None)
            if obj is None:
                continue
            try:
                log(f"[{tag}]   {fn}() -> {obj() if callable(obj) else obj}")
            except BaseException as exc:  # noqa: BLE001
                log(f"[{tag}]   {fn}() raised {type(exc).__name__}: {exc}")
        return True
    except BaseException as exc:  # noqa: BLE001
        log(f"[{tag}] BRIDGE IMPORT FAILED: {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return False


if MODE == "pyfirst":
    ok_py = try_pyside("1st")
    log("")
    ok_b = try_bridge("2nd")
else:
    ok_b = try_bridge("1st")
    log("")
    ok_py = try_pyside("2nd")

log("")
log("=== END ===")
