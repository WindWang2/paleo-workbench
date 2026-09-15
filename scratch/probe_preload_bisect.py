"""Bisect the bridge's direct dependencies: load each one by absolute path with
ctypes in the app-like context, and report which one raises.

The one that raises is the module whose imports cannot be satisfied -> the
ERROR_PROC_NOT_FOUND culprit.

Writes .workbuddy/preload_bisect.txt
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "preload_bisect.txt"
VENDOR_BIN = REPO / "native/qgis_render_bridge/build/qgis-vendor/output/bin"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM", "windows")

log("step 1: import paleo_workbench (loader claims the DLL dirs)")
import paleo_workbench  # noqa: E402

log("  OK")
log("")

log("step 2: QApplication on the real platform")
from PySide6.QtCore import qVersion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
log(f"  QApplication OK  Qt={qVersion()}")
log("")

CANDIDATES = [
    "qgis_core.dll",
    "qgis_gui.dll",
    "qgis_analysis.dll",
    "qgis_native.dll",
    "Qt6Core5Compat.dll",
    "qt6keychain.dll",
    "qca-qt6.dll",
    "qscintilla2_qt6.dll",
    "Qt6Xml.dll", "Qt6Svg.dll", "Qt6PrintSupport.dll", "Qt6Network.dll",
    "Qt6Sql.dll", "Qt6Concurrent.dll", "Qt6Multimedia.dll", "Qt6Widgets.dll",
    "Qt6Gui.dll", "Qt6Core.dll", "Qt6DBus.dll",
    "gdal.dll", "proj_9.dll", "geos_c.dll", "geos.dll", "zstd.dll",
    "sqlite3.dll", "z.dll", "libexpat.dll", "spatialite.dll", "zip.dll",
    "libprotobuf-lite.dll", "libxml2.dll", "libcurl.dll", "tiff.dll",
]

log("step 3: preload each candidate by absolute path")
failures: list[str] = []
for name in CANDIDATES:
    # resolve via the paths the loader registered; fall back to vendor bin
    hit = None
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and (Path(d) / name).is_file():
            hit = Path(d) / name
            break
    if hit is None:
        log(f"  {name:<24} NOT FOUND on PATH")
        continue
    try:
        ctypes.WinDLL(str(hit))
        log(f"  {name:<24} OK        {hit.parent}")
    except OSError as exc:
        log(f"  {name:<24} *** FAILED: {exc}")
        failures.append(f"{name}: {exc}")
log("")

if failures:
    log("=== FAILING MODULES ===")
    for f in failures:
        log(f"  {f}")
else:
    log("=== no candidate failed to load ===")
log("")

log("step 4: import the bridge")
try:
    import qgis_render_bridge as b

    log(f"  BRIDGE IMPORT OK -> {b.__file__}")
except BaseException as exc:  # noqa: BLE001
    log(f"  BRIDGE IMPORT FAILED: {type(exc).__name__}: {exc}")
log("=== END ===")
