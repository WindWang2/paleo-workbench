"""Verify the freshly wired 创建派生副本 button in the data inspector.

Checks, against the real InspectorPanel:
  1. an asset in RAW stage  -> button enabled, hint explains the derive
  2. an asset in DERIVED    -> button disabled, hint explains why
  3. no asset               -> button disabled
  4. clicking on a RAW asset emits create_derived_requested with that asset

Writes .workbuddy/inspector_derived_test.txt
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = REPO / ".workbuddy" / "inspector_derived_test.txt"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")

import paleo_workbench  # noqa: E402,F401
from PySide6.QtWidgets import QApplication  # noqa: E402

from paleo_workbench.ui.pages.data_view_models import (  # noqa: E402
    AssetView,
    DataStage,
    IntegrityState,
    LineageView,
)
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
integrity = list(IntegrityState)[0]


def make_asset(name: str, stage: DataStage) -> AssetView:
    return AssetView(
        id=f"asset_{name}",
        name=name,
        type="grid",
        type_label="栅格",
        format="tif",
        stage=stage,
        current_version="v1",
        versions=[],
        tags=[],
        managed=True,
        integrity_state=integrity,
        checksum=None,
        path=f"C:/tmp/{name}.tif",
        size_bytes=1024,
        size_formatted="1.0 KB",
        created_at="2026-09-14 10:00",
        modified_at="2026-09-14 10:00",
        source="导入",
        lineage=LineageView(),
    )


panel = InspectorPanel()
captured: list[object] = []
panel.create_derived_requested.connect(lambda a: captured.append(a))

log("=== 1. no asset ===")
panel.update_asset(None)
log(f"  enabled = {panel.create_derived_btn.isEnabled()}   (expect False)")
log(f"  hint    = {panel.create_derived_hint.text()!r}")

log("")
log("=== 2. RAW asset ===")
raw = make_asset("地震相预测", DataStage.RAW)
panel.update_asset(raw)
log(f"  enabled = {panel.create_derived_btn.isEnabled()}   (expect True)")
log(f"  hint    = {panel.create_derived_hint.text()!r}")

log("")
log("=== 3. DERIVED asset ===")
derived = make_asset("地震相预测_derived", DataStage.DERIVED)
panel.update_asset(derived)
log(f"  enabled = {panel.create_derived_btn.isEnabled()}   (expect False)")
log(f"  hint    = {panel.create_derived_hint.text()!r}")

log("")
log("=== 4. click on a RAW asset -> signal ===")
panel.update_asset(raw)
captured.clear()
panel.create_derived_btn.click()
log(f"  emitted count = {len(captured)}   (expect 1)")
if captured:
    got = captured[0]
    log(f"  emitted asset id = {getattr(got, 'id', None)!r}   (expect 'asset_地震相预测')")
    log(f"  is the same object as the selected asset = {got is raw}")

log("")
log("=== 5. click while DERIVED (must NOT emit) ===")
panel.update_asset(derived)
captured.clear()
panel.create_derived_btn.click()
log(f"  emitted count = {len(captured)}   (expect 0)")

log("")
log("=== END ===")
