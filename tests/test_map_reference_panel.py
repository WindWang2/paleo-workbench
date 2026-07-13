from __future__ import annotations

from paleo_workbench.project.models import MapReferenceLayer
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel


def _layer() -> MapReferenceLayer:
    return MapReferenceLayer(
        id="ref_1", name="构造参考", source_path="/tmp/ref.geojson", source_kind="vector",
        source_crs="EPSG:4326", project_crs="EPSG:3857", status="ready",
    )


def test_reference_panel_lists_aligned_layer_and_emits_controls(qtbot):
    panel = MapReferencePanel()
    qtbot.addWidget(panel)
    seen = []
    panel.reference_visibility_changed.connect(lambda *args: seen.append(args))
    panel.set_layers([_layer()])

    assert panel.layer_list.count() == 1
    assert "坐标已对齐" in panel.status_label.text()
    panel.layer_list.item(0).setCheckState(panel._unchecked)
    assert seen == [("ref_1", False)]


def test_map_edit_view_applies_shared_view_state(qtbot):
    view = MapEditView()
    qtbot.addWidget(view)
    view.apply_view_state({"center": (25.0, 30.0), "scale": 2.0})

    state = view.view_state()
    assert state["center"] == (25.0, 30.0)
    assert state["scale"] == 2.0
