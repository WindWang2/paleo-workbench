"""Probe: can the freshly built qgis_render_bridge actually be imported?

Writes its findings to .workbuddy/bridge_import_probe.txt (never relies on
shell redirection, so a hard crash still leaves the earlier lines behind).
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "bridge_import_probe.txt"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")
log(f"python   = {sys.version}")
log(f"exe      = {sys.executable}")
log(f"cwd      = {os.getcwd()}")
log("")

# ---------------------------------------------------------------- raw import
log("=== 1. RAW import (no helper) ===")
try:
    import qgis_render_bridge  # noqa: F401

    log("RAW IMPORT OK (DLL closure satisfied already)")
except BaseException as exc:  # noqa: BLE001
    log(f"RAW IMPORT FAILED: {type(exc).__name__}: {exc}")
log("")

# ------------------------------------------------- 2. via the project's loader
log("=== 2. project loader + import ===")
try:
    from paleo_workbench.mapping.qgis_style import ensure_qgis_bridge_dll_dirs

    ensure_qgis_bridge_dll_dirs()
    log("ensure_qgis_bridge_dll_dirs() OK")
except BaseException as exc:  # noqa: BLE001
    log(f"ensure_qgis_bridge_dll_dirs() FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())

try:
    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    report = prepare_bridge_load()
    log(f"prepare_bridge_load() -> {report}")
except BaseException as exc:  # noqa: BLE001
    log(f"prepare_bridge_load() FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())
log("")

# ------------------------------------------------------------- 3. real import
log("=== 3. import after loader ===")
try:
    import qgis_render_bridge as bridge

    log(f"IMPORT OK  file = {bridge.__file__}")
    names = [n for n in dir(bridge) if not n.startswith("_")]
    log(f"public names ({len(names)}): {names[:60]}")
    for fn in ("version", "runtime_facts", "capability_manifest"):
        obj = getattr(bridge, fn, None)
        if obj is None:
            continue
        try:
            log(f"  {fn}() -> {obj() if callable(obj) else obj}")
        except BaseException as exc:  # noqa: BLE001
            log(f"  {fn}() raised {type(exc).__name__}: {exc}")
except BaseException as exc:  # noqa: BLE001
    log(f"IMPORT FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())

log("")
log("=== END ===")
