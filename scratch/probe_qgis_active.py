"""Is the QGIS render stack actually ACTIVE (not the fallback)?

Checks the capability probe, the display canvas factory, and the composite
document canvas factory — i.e. every place the app decides QGIS vs fallback.

Writes .workbuddy/qgis_active.txt
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "qgis_active.txt"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
log(f"exe = {sys.executable}")
log("")

import paleo_workbench  # noqa: E402  (runs prepare_bridge_load)

log("=== 1. capability probe ===")
from paleo_workbench.mapping.qgis_style import (  # noqa: E402
    qgis_bridge_available,
    qgis_scalar_pipeline_ready,
)

log(f"  qgis_bridge_available()     = {qgis_bridge_available()}")
log(f"  qgis_scalar_pipeline_ready() = {qgis_scalar_pipeline_ready()}")
log("")

log("=== 2. canvas_shim.bridge_available() (the crash-guard predicate) ===")
from paleo_workbench.ui.qgis_stack.canvas_shim import bridge_available  # noqa: E402

log(f"  bridge_available() = {bridge_available()}")
log("")

log("=== 3. display canvas factory (home / read-only pages) ===")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from paleo_workbench.ui.qgis_stack.display_canvas import (  # noqa: E402
    create_display_canvas,
)

w = create_display_canvas()
log(f"  create_display_canvas() -> {type(w).__module__}.{type(w).__name__}")
log("")

log("=== 4. composite document canvas factory (综合编修区) ===")
try:
    from paleo_workbench.ui.workstation.composite_document import (  # noqa: E402
        CompositeDocument,
    )

    doc = CompositeDocument()
    canvas, is_qgis = doc._create_canvas()
    log(f"  _create_canvas() -> {type(canvas).__module__}.{type(canvas).__name__}  qgis={is_qgis}")
    try:
        doc.deleteLater()
    except Exception:
        pass
except BaseException as exc:  # noqa: BLE001
    import traceback

    log(f"  FAILED: {type(exc).__name__}: {exc}")
    log(traceback.format_exc())
log("")

log("=== 5. live QgisRenderBridge instance ===")
try:
    import qgis_render_bridge as b

    log(f"  module      : {b.__file__}")
    log(f"  QgisMapStack: {b.mapstack.QgisMapStack}")
    log(f"  capability_manifest keys: {list(b.capability_manifest().keys())[:12]}")
except BaseException as exc:  # noqa: BLE001
    log(f"  FAILED: {type(exc).__name__}: {exc}")
log("")
log("=== END ===")
