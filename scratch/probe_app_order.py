"""Model the REAL app import order exactly:

  1. import paleo_workbench  ->  __init__ calls prepare_bridge_load()
  2. import qgis_render_bridge

No speculative raw import first (an earlier probe did that and may have poisoned
the process, masking the real result).

Writes .workbuddy/app_order_probe.txt
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "app_order_probe.txt"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")
log(f"exe = {sys.executable}")
log("")

log("step 1: import paleo_workbench  (runs prepare_bridge_load at package import)")
try:
    import paleo_workbench  # noqa: F401

    log("  OK")
    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    rep = prepare_bridge_load()
    log(f"  recipe={rep.recipe} prepared={rep.prepared}")
    log(f"  dll_dirs={rep.dll_dirs}")
    log(f"  warnings={rep.warnings}")
    log(f"  preload_failures={rep.preload_failures}")
except BaseException as exc:  # noqa: BLE001
    log(f"  FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())
log("")

log("step 2: import qgis_render_bridge")
try:
    import qgis_render_bridge as b

    log(f"  BRIDGE IMPORT OK -> {b.__file__}")
    names = sorted(n for n in dir(b) if not n.startswith("_"))
    log(f"  public names ({len(names)}): {names[:80]}")
except BaseException as exc:  # noqa: BLE001
    log(f"  BRIDGE IMPORT FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())
log("")

log("step 3: import PySide6.QtCore (must still work alongside)")
try:
    import PySide6.QtCore as c

    log(f"  PySide6 OK  Qt={c.qVersion()}")
except BaseException as exc:  # noqa: BLE001
    log(f"  PySide6 FAILED: {type(exc).__name__}: {exc}")
log("")
log("=== END ===")
