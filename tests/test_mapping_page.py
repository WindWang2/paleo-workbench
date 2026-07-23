import pytest

from PySide6.QtCore import QPointF

from paleo_workbench.project.models import FactorMapTask, MapReferenceLayer, PaleoMapDocument
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_mapping_page_assembles_gis_shell(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.objectName() == "MappingPage"
    assert isinstance(page.toolbar, MapEditToolbar)
    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.reference_panel, MapReferencePanel)
    assert isinstance(page.edit_view, MapEditView)
    assert isinstance(page.attribute_table, MapAttributeTable)
    assert page.attribute_table.maximumHeight() == 220


def test_mapping_page_update_state_sets_layer_tree(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    docs = [
        PaleoMapDocument(name="Map A", linked_target_horizon="H1"),
        PaleoMapDocument(name="Map B", linked_target_horizon="H2"),
    ]
    page.update_state(docs)

    root = page.layer_tree.tree.topLevelItem(0)
    assert root.childCount() == 2
    assert root.child(0).text(0) == "Map A"
    assert root.child(1).text(0) == "Map B"
    # Active is last document — layers under Map B
    assert root.child(1).childCount() == 4


def test_mapping_page_context_snapshot(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    received: list[dict] = []
    page.mapping_context_changed.connect(received.append)

    page.update_state([
        PaleoMapDocument(name="Delta Map", linked_target_horizon="H3"),
    ])
    ctx = page.mapping_context()
    assert ctx["map_name"] == "Delta Map"
    assert ctx["horizon"] == "H3"
    assert ctx["dirty"] is False
    assert received
    assert received[-1]["map_name"] == "Delta Map"


def test_mapping_page_forwards_generate_demo_draft_signal(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    received = []
    page.generate_demo_draft_requested.connect(lambda: received.append(True))

    page.toolbar.generate_demo_draft_btn.click()
    assert received == [True]


def test_mapping_page_loads_completed_factor_maps_into_bottom_shelf(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    tasks = [
        FactorMapTask(name="厚度", target_horizon="H1", factor_type="厚度", method="IDW", status="complete"),
        FactorMapTask(name="待生成", target_horizon="H1", factor_type="砂地比", method="IDW", status="pending"),
    ]
    page.update_state([PaleoMapDocument(name="M", linked_target_horizon="H1")], factor_tasks=tasks, project_crs="EPSG:3857")
    cards = page.bottom_workbench.factor_shelf.grid.grid_container.findChildren(
        FactorPreviewGrid.FactorPreviewCard
    )
    assert len(cards) == 1


def _bowtie_map_doc():
    return PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "bowtie",
            "name": "A",
            "coordinates": [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]],
        }],
    )


def test_mapping_page_pushes_topology_issues_to_panel(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([_bowtie_map_doc()])
    scene = page.edit_view.scene()
    scene.refresh_topology()
    panel = page.bottom_workbench.topology_panel
    assert panel.table.rowCount() >= 1
    assert panel.table.item(0, 0).text() == "bowtie"


def test_mapping_page_locates_topology_issue_feature(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.resize(800, 600)
    page.show()
    qtbot.waitExposed(page)
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[100, 100], [200, 100], [200, 200], [100, 100]],
        }],
    )
    page.update_state([doc])

    page.bottom_workbench.topology_panel.locate_requested.emit("f1")

    scene = page.edit_view.scene()
    assert scene.selected_feature_ids() == ["f1"]
    center = page.edit_view.mapToScene(page.edit_view.viewport().rect().center())
    assert center.x() == pytest.approx(150.0, abs=10.0)
    assert center.y() == pytest.approx(150.0, abs=10.0)


def test_mapping_page_locate_skips_malformed_location_for_later_valid_issue(qtbot, monkeypatch):
    page = MappingPage()
    qtbot.addWidget(page)
    page.resize(800, 600)
    page.show()
    qtbot.waitExposed(page)
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[100, 100], [200, 100], [200, 200], [100, 100]],
        }],
    )
    page.update_state([doc])
    scene = page.edit_view.scene()
    # Two issues for the same feature: first has a malformed location, the
    # second a valid one — the valid location must win over the fallback.
    monkeypatch.setattr(scene, "topology_issues", lambda: [
        {"feature_id": "f1", "location": "malformed"},
        {"feature_id": "f1", "location": [1600.0, 1400.0]},
    ])

    centered: list[QPointF] = []
    monkeypatch.setattr(page.edit_view, "centerOn", lambda pt: centered.append(pt))

    page.bottom_workbench.topology_panel.locate_requested.emit("f1")

    assert len(centered) == 1
    assert centered[0].x() == pytest.approx(1600.0, abs=1e-3)
    assert centered[0].y() == pytest.approx(1400.0, abs=1e-3)


def test_mapping_page_wires_cursor_and_view_state_to_factor_shelf(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    shelf = page.bottom_workbench.factor_shelf
    page.edit_view.cursor_position_changed.emit((12.0, 34.0))
    assert shelf.cursor_position() == (12.0, 34.0)
    page.edit_view.view_state_changed.emit({"center": (5.0, 6.0), "scale": 2.0})
    assert shelf.view_state() == {"center": (5.0, 6.0), "scale": 2.0}


def test_mapping_page_overlay_request_shows_matching_reference_layer(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    layer = MapReferenceLayer(
        id="ref_grid",
        name="参考网格",
        source_path="/tmp/ref.tif",
        source_kind="raster",
        source_crs="EPSG:3857",
        project_crs="EPSG:3857",
        status="ready",
        visible=False,
    )
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1", reference_layers=[layer])
    page.update_state([doc])

    # Both the factor shelf and the (previously dangling) reference dock signal
    # route through the same overlay path.
    page.bottom_workbench.factor_shelf.factor_overlay_requested.emit("ref_grid")
    assert layer.visible is True

    layer.visible = False
    page.reference_panel.overlay_requested.emit("ref_grid")
    assert layer.visible is True


def test_canvas_priority_mode_collapses_side_panels(qtbot):
    """Canvas-priority hides layer tree, reference panel, and bottom shelf."""
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1")
    page.update_state([doc])

    page.set_canvas_priority(True)

    assert page.layer_tree.isHidden()
    assert page.reference_panel.isHidden()
    assert page.bottom_workbench.isHidden()
    assert not page.edit_view.isHidden()
    assert page.is_canvas_priority()


def test_canvas_priority_mode_restores_panels(qtbot):
    """Leaving canvas-priority restores all panels."""
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1")
    page.update_state([doc])

    page.set_canvas_priority(True)
    page.set_canvas_priority(False)

    assert not page.layer_tree.isHidden()
    assert not page.reference_panel.isHidden()
    assert not page.bottom_workbench.isHidden()
    assert not page.is_canvas_priority()


def test_canvas_priority_preserves_dirty_state(qtbot):
    """Toggling canvas-priority does not lose dirty state."""
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]],
        }],
    )
    page.update_state([doc])
    page.edit_view.scene().translate_features(["f1"], 1.0, 0.0)
    assert page.is_dirty()

    page.set_canvas_priority(True)
    assert page.is_dirty()

    page.set_canvas_priority(False)
    assert page.is_dirty()


def test_canvas_priority_toolbar_button_toggles_mode(qtbot):
    """Toolbar canvas_priority_btn toggles the mode."""
    page = MappingPage()
    qtbot.addWidget(page)
    page.toolbar.canvas_priority_btn.setChecked(True)
    assert page.is_canvas_priority()
    page.toolbar.canvas_priority_btn.setChecked(False)
    assert not page.is_canvas_priority()
