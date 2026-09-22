"""Repro + component timing for #389 (tool operation recomposes whole document)."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.mapping.map_tools import MeasureDistanceTool, SelectTool, AddPointTool
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage

app = QApplication.instance() or QApplication([])

N = 10_000


def build_document(n: int) -> PaleoMapDocument:
    rows = []
    for i in range(n):
        x = (i % 100) * 3.0
        y = (i // 100) * 3.0
        rows.append(
            {
                "id": f"f{i}",
                "name": f"F{i}",
                "coordinates": [[x, y], [x + 2, y], [x, y + 2]],
            }
        )
    return PaleoMapDocument(
        id="perf-map",
        name="Perf",
        linked_target_horizon="H1",
        facies_polygons=rows,
    )


def timed(label: str, fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    print(f"{label}: {best * 1000:.1f} ms")
    return best


page = MappingPage()
page.resize(800, 600)
page.show()
doc = build_document(N)
t0 = time.perf_counter()
page.update_state([doc])
print(f"update_state: {(time.perf_counter() - t0) * 1000:.1f} ms")
assert page._authoring_document is not None

timed("data-edit refresh (_refresh_unified_composition)", page._refresh_unified_composition, repeats=3)
timed("selection-only handler (_on_unified_tool_operation(False))", lambda: page._on_unified_tool_operation(edits_data=False), repeats=5)

snapshot_calls = {"n": 0}
original = document_render_snapshot


def spy(*args, **kwargs):
    snapshot_calls["n"] += 1
    return original(*args, **kwargs)


import paleo_workbench.mapping.map_scene_adapter as msa

msa.document_render_snapshot = spy

canvas = page.unified_canvas
canvas.resize(600, 400)


def send_move(x: float, y: float) -> None:
    ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, ev)


def send_press(x: float, y: float, button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, ev)


# --- measure tool drag: expect 0 snapshot calls ---
snapshot_calls["n"] = 0
measure = MeasureDistanceTool(measurement_ready=lambda _d: None)
from paleo_workbench.mapping.map_tools import MapToolController

controller = MapToolController()
controller.set_active_tool(measure)
canvas.set_map_tool_controller(controller)
send_press(100, 100)
for i in range(20):
    send_move(100 + i, 100 + i)
QApplication.processEvents()
print(f"measure drag 20 moves -> document_render_snapshot calls: {snapshot_calls['n']}")

# --- select press: expect 0 snapshot calls, selection updated ---
snapshot_calls["n"] = 0
authoring = page._authoring_document
index = page._active_authoring_index()
layer = authoring.active_layer
select = SelectTool(layer, identify=lambda point: index.identify(point, 8.0 * canvas.map_units_per_pixel))
controller.set_active_tool(select)
send_press(20, 20)  # inside first facies polygon at map (20,20)
QApplication.processEvents()
print(f"select press -> document_render_snapshot calls: {snapshot_calls['n']}")
print(f"  selection: {sorted(layer.selection)[:3]}")

# --- digitize point: expect exactly 1 snapshot call + revision bump ---
snapshot_calls["n"] = 0
authoring.start_editing("well")
session = authoring.active_session
before = authoring.data_revisions()
add = AddPointTool(session, feature_id_factory=lambda: "new-1")
controller.set_active_tool(add)
send_press(50, 50)
QApplication.processEvents()
after = authoring.data_revisions()
print(f"add-point press -> document_render_snapshot calls: {snapshot_calls['n']}")
print(f"  revision bump: {before} -> {after}")

# which scene layers got set_vector_features?
scene = page.unified_scene
updates = {}
original_set = scene.set_vector_features
def spy_set(layer_id, features, **kw):
    updates[layer_id] = updates.get(layer_id, 0) + 1
    return original_set(layer_id, features, **kw)
scene.set_vector_features = spy_set
snapshot_calls["n"] = 0
add2 = AddPointTool(session, feature_id_factory=lambda: "new-2")
controller.set_active_tool(add2)
send_press(55, 55)
QApplication.processEvents()
print(f"second add-point press -> snapshot calls: {snapshot_calls['n']}, set_vector_features: {updates}")

# profile data-edit refresh components
import time as _t
t0 = _t.perf_counter(); page._authoring_document.records(); print(f"  records(): {(_t.perf_counter()-t0)*1000:.1f} ms")
t0 = _t.perf_counter(); msa.document_render_snapshot(doc, project_crs="EPSG:3857", records=page._authoring_document.records(), layer_revisions=page._authoring_document.data_revisions()); print(f"  document_render_snapshot(counters): {(_t.perf_counter()-t0)*1000:.1f} ms")

