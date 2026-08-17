import json

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt

from paleo_workbench.project.models import FactorMapTask, MapReferenceLayer, PaleoMapDocument
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from tests.qgis_support import QGIS_SKIP_REASON


def test_mapping_page_assembles_gis_shell(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.objectName() == "MappingPage"
    assert isinstance(page.toolbar, MapEditToolbar)
    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.reference_panel, MapReferencePanel)
    assert isinstance(page.edit_view, MapEditView)
    assert isinstance(page.unified_canvas, UnifiedMapCanvas)
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


def test_mapping_page_syncs_the_active_document_into_the_unified_scene(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(
        id="map-1",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]}
        ],
    )

    page.update_state([document], project_crs="EPSG:3857")

    layer = page.unified_scene.registry.get("map-1:facies")
    assert layer is not None
    assert layer.crs == "EPSG:3857"
    assert page.unified_scene.vector_features("map-1:facies")[0]["id"] == "f1"


def test_native_layer_tree_add_layer_imports_an_immutable_reference_into_unified_composition(
    tmp_path, monkeypatch, qtbot
):
    source = tmp_path / "faults.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Fault A"},
                        "geometry": {"type": "LineString", "coordinates": [[120.0, 30.0], [120.1, 30.1]]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-ref", name="Map", linked_target_horizon="H1")
    page.update_state([document], project_crs="EPSG:3857")
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.mapping_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )

    assert page._native_layer_tree is not None
    page._native_layer_tree.add_layer_action.trigger()

    assert len(document.reference_layers) == 1
    reference = document.reference_layers[0]
    layer_id = f"map-ref:reference:{reference.id}"
    rendered = page.unified_scene.registry.get(layer_id)
    assert rendered is not None
    assert rendered.source_ref == f"reference:{reference.id}"
    assert page.unified_scene.vector_features(layer_id)[0]["properties"]["name"] == "Fault A"
    # Import stores a source descriptor only; it never rewrites the raw file.
    assert source.is_file()

    page._on_reference_visibility_changed(reference.id, False)
    hidden = page.unified_scene.registry.get(layer_id)
    assert hidden is not None
    assert hidden.visible is False


@pytest.mark.qgis
def test_mapping_page_uses_the_qgis_unified_canvas_when_the_bridge_is_available(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    if page.unified_canvas.backend.backend_name != "qgis":
        pytest.skip(QGIS_SKIP_REASON)
    document = PaleoMapDocument(
        id="map-1",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]}
        ],
    )
    page.resize(900, 600)
    page.show()
    page.update_state([document], project_crs="EPSG:3857")
    page.set_preview_mode(True)

    qtbot.waitUntil(lambda: page.unified_canvas.last_frame is not None, timeout=5_000)
    assert page.preview_canvas_stack.currentWidget() is page.unified_canvas
    assert page.unified_canvas.last_frame is not None


def test_mapping_page_composes_factor_grid_with_document_layers_in_unified_scene(qtbot):
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 10.0],
            "grid_y": [0.0, 10.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    task = FactorMapTask(
        id="porosity-task",
        name="Porosity",
        target_horizon="H1",
        factor_type="Porosity",
        method="IDW",
        status="complete",
        parameters=result.to_legacy_dict(),
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state(
        [
            PaleoMapDocument(
                id="map-1",
                name="Map",
                linked_target_horizon="H1",
                facies_polygons=[
                    {"id": "f1", "name": "delta", "coordinates": [[0, 0], [10, 0], [0, 10]]}
                ],
            )
        ],
        factor_tasks=[task],
        project_crs="EPSG:3857",
    )

    page.bottom_workbench.factor_shelf.factor_overlay_requested.emit(task.id)

    assert page.unified_scene.scalar_layer(task.id) is not None
    assert page.unified_scene.registry.index_of(task.id) == 0
    assert page.unified_scene.registry.get("map-1:facies") is not None
    assert page.preview_canvas_stack.currentWidget() is page.unified_canvas
    assert page.is_preview_mode() is False


def test_unified_canvas_actions_drive_host_edit_session_and_undo_redo(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.resize(900, 640)
    page.show()
    document = PaleoMapDocument(
        id="map-actions",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}
        ],
    )
    page.update_state([document], project_crs="EPSG:3857")
    canvas = page.unified_canvas
    qtbot.waitUntil(lambda: canvas.width() > 100 and canvas.height() > 100)
    center = canvas.map_to_screen((5.0, 5.0)).toPoint()

    page.action_controller.actions["select"].trigger()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)
    assert page._authoring_document.active_layer.selection == {"f1"}

    page.action_controller.actions["toggle_editing"].trigger()
    page.action_controller.actions["move_feature"].trigger()
    target = canvas.map_to_screen((7.0, 5.0)).toPoint()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    session = page._authoring_document.active_session
    assert session is not None
    assert session.feature("f1").geometry["coordinates"][0][0][0] == pytest.approx(2.0)

    page.action_controller.actions["undo"].trigger()
    assert session.feature("f1").geometry["coordinates"][0][0][0] == pytest.approx(0.0)
    page.action_controller.actions["redo"].trigger()
    assert session.feature("f1").geometry["coordinates"][0][0][0] == pytest.approx(2.0)
    assert page.save_draft()
    assert document.facies_polygons[0]["coordinates"][0][0] == pytest.approx(2.0)


def test_unified_canvas_polygon_capture_and_escape_keep_the_edit_buffer(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.resize(900, 640)
    page.show()
    page.update_state([PaleoMapDocument(id="map-capture", name="Map", linked_target_horizon="H1")])
    canvas = page.unified_canvas
    qtbot.waitUntil(lambda: canvas.width() > 100 and canvas.height() > 100)

    page.action_controller.actions["toggle_editing"].trigger()
    page.action_controller.actions["add_polygon"].trigger()
    points = [canvas.map_to_screen(point).toPoint() for point in ((0.1, 0.1), (0.8, 0.1), (0.5, 0.8))]
    for point in points:
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseClick(canvas, Qt.MouseButton.RightButton, pos=points[-1])

    session = page._authoring_document.active_session
    assert session is not None
    assert len(session.features()) == 1
    qtbot.keyClick(canvas, Qt.Key.Key_Escape)
    assert len(session.features()) == 1


def test_unified_layer_properties_change_only_style_and_status_tracks_editing(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(
        id="map-style",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[{"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]}],
    )
    page.update_state([document], project_crs="EPSG:3857")
    layer_id = "map-style:facies"
    layer = page.unified_scene.registry.get(layer_id)
    data_revision = layer.data_revision

    page._apply_layer_properties(layer_id, {
        "name": "Styled Facies", "crs": "EPSG:3857", "opacity": 0.6,
        "style": {"fill": "#e03131", "stroke": "#ffffff", "stroke_width": 2.0, "labels": {"field": "name", "size": 9}},
    })

    assert layer.data_revision == data_revision
    assert page.unified_scene.vector_style(layer_id)["fill"] == "#e03131"
    assert page.is_dirty()
    assert page.save_draft()
    assert document.layer_state["vector_layers"][0]["style"]["fill"] == "#e03131"
    page.action_controller.actions["toggle_editing"].trigger()
    assert page.status_bar.edit.text() == "Editing"
    assert "EPSG:3857" in page.status_bar.crs.text()


def test_unified_map_and_attribute_feature_selector_share_selection_ids(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(
        id="map-attribute-selection",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]},
            {"id": "f2", "name": "slope", "coordinates": [[5, 0], [9, 0], [5, 4]]},
        ],
    )
    page.update_state([document])
    authoring = page._authoring_document
    assert authoring is not None

    authoring.active_layer.set_selection(("f1",))
    page._on_unified_tool_operation()
    selector = page.attribute_table.feature_combo
    assert selector.currentData() == "f1"

    selector.setCurrentIndex(selector.findData("f2"))
    assert authoring.active_layer.selection == {"f2"}

    page.action_controller.actions["select_all"].trigger()
    assert authoring.active_layer.selection == {"f1", "f2"}
    page.action_controller.actions["invert_selection"].trigger()
    assert authoring.active_layer.selection == set()


def test_native_layer_remove_persists_a_composition_exclusion_without_mutating_geometry(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(
        id="map-remove-layer",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[{"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]}],
    )
    page.update_state([document])
    tree = page._native_layer_tree
    assert tree is not None
    tree.tree.setCurrentIndex(tree.model._index_for_id("map-remove-layer:facies"))
    tree.remove_action.trigger()

    assert page.unified_scene.registry.get("map-remove-layer:facies") is None
    assert document.facies_polygons[0]["id"] == "f1"
    assert page.is_dirty()
    assert page.save_draft()
    assert document.layer_state["removed_layer_ids"] == ["map-remove-layer:facies"]

    page.update_state([document])
    assert page.unified_scene.registry.get("map-remove-layer:facies") is None


def test_map_chrome_controls_update_decorations_without_a_data_render_rebuild(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-chrome", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    before = page.unified_canvas.last_frame

    page.chrome_panel.title_edit.setText("Final Map")
    page.chrome_panel.title_edit.editingFinished.emit()

    assert document.map_chrome["title"] == "Final Map"
    assert page.is_dirty()
    # Map decorations are an overlay: changing them cannot call interpolation or
    # force a new layer snapshot. The existing frame object remains valid.
    assert page.unified_canvas.last_frame is before


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


def test_factor_overlay_value_error_is_user_visible(qtbot, monkeypatch):
    """#657: factor-card overlay failures must surface, not silently return."""
    from PySide6.QtWidgets import QMessageBox

    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 10.0],
            "grid_y": [0.0, 10.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    task = FactorMapTask(
        id="porosity-task",
        name="Porosity",
        target_horizon="H1",
        factor_type="Porosity",
        method="IDW",
        status="complete",
        parameters=result.to_legacy_dict(),
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state(
        [
            PaleoMapDocument(
                id="map-1",
                name="Map",
                linked_target_horizon="H1",
                facies_polygons=[
                    {"id": "f1", "name": "delta", "coordinates": [[0, 0], [10, 0], [0, 10]]}
                ],
            )
        ],
        factor_tasks=[task],
        project_crs="EPSG:3857",
    )

    def _boom(*_args, **_kwargs):
        raise ValueError("grid artifact missing")

    monkeypatch.setattr(
        "paleo_workbench.viz.native_factor_map.scene_from_factor_task",
        _boom,
    )
    warnings: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    page.bottom_workbench.factor_shelf.factor_overlay_requested.emit(task.id)

    assert warnings, "overlay failure must show a user-visible error"
    assert "grid artifact missing" in " ".join(str(item) for item in warnings[0])


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
    assert not page.unified_canvas.isHidden()
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


def test_update_state_same_id_new_object_keeps_dirty_legacy_scene(qtbot):
    """A programmatic refresh delivering the SAME document id as a NEW object
    must not wipe unsaved legacy scene edits (the id-equality guard must not
    require object identity) (#423)."""
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])

    from paleo_workbench.ui.pages.map_edit_scene import MapEditScene

    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)
    assert scene._bound_document is document

    # Unsaved edits in the legacy scene.
    scene.set_dirty(True)

    # Same id, different instance (project refresh / deep-copied shell state).
    swapped = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    assert swapped is not document
    page.update_state([swapped])

    # Scene must not have been reloaded: edits and undo stack preserved.
    assert scene.is_dirty() is True
    assert scene._bound_document is document


def test_update_state_different_id_prompts_instead_of_silently_wiping(qtbot, monkeypatch):
    """A refresh resolving a DIFFERENT document id while the scene is dirty must
    ask Save/Discard/Cancel instead of silently discarding the edits (#532)."""
    from PySide6.QtWidgets import QMessageBox

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    scene = page.edit_view.scene()
    scene.set_dirty(True)

    other = PaleoMapDocument(id="map-2", name="Map 2", linked_target_horizon="H2")

    asked = []

    def ask(*args, **kwargs):
        asked.append(True)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))
    page.update_state([other])

    assert asked, "cross-document dirty refresh must prompt"
    # Cancel keeps the previous document and its unsaved scene.
    assert page.active_document() is document
    assert scene.is_dirty() is True
    assert scene._bound_document is document


def test_update_state_discard_switches_and_reloads_different_document(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    scene = page.edit_view.scene()
    scene.set_dirty(True)

    other = PaleoMapDocument(id="map-2", name="Map 2", linked_target_horizon="H2")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard),
    )
    page.update_state([other])

    assert page.active_document() is other
    assert scene.is_dirty() is False
    assert scene._bound_document is other


def test_update_state_save_persists_before_switching_documents(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    page.edit_view.scene().set_dirty(True)

    other = PaleoMapDocument(id="map-2", name="Map 2", linked_target_horizon="H2")
    saved = []

    def fake_save_draft() -> bool:
        saved.append(True)
        return True

    monkeypatch.setattr(page, "save_draft", fake_save_draft)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save),
    )
    page.update_state([other])

    assert saved == [True], "Save choice must persist the dirty document first"
    assert page.active_document() is other


def test_update_state_save_failure_keeps_previous_document(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    scene = page.edit_view.scene()
    scene.set_dirty(True)

    other = PaleoMapDocument(id="map-2", name="Map 2", linked_target_horizon="H2")
    monkeypatch.setattr(page, "save_draft", lambda: False)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save),
    )
    page.update_state([other])

    # A failed save must not abandon the dirty document.
    assert page.active_document() is document
    assert scene.is_dirty() is True


def test_update_state_same_id_dirty_refresh_never_prompts(qtbot, monkeypatch):
    """Same-id refreshes (the #423 path) must not prompt: unsaved edits are
    preserved silently, exactly as before."""
    from PySide6.QtWidgets import QMessageBox

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    page.update_state([document])
    scene = page.edit_view.scene()
    scene.set_dirty(True)

    swapped = PaleoMapDocument(id="map-1", name="Map", linked_target_horizon="H1")
    asked = []

    def ask(*args, **kwargs):
        asked.append(True)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))
    page.update_state([swapped])

    assert not asked
    assert scene.is_dirty() is True
    assert scene._bound_document is document


def test_on_contour_completed_defers_document_switch_to_update_state(qtbot, monkeypatch):
    """_on_contour_completed must route its preferred document through
    update_state's dirty guard instead of pre-mutating _active_document (#532)."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    import paleo_workbench.ui.pages.mapping_page as mod
    from paleo_workbench.project.models import ContourDraft

    page = MappingPage()
    qtbot.addWidget(page)
    doc_a = PaleoMapDocument(id="map-a", name="Map A", linked_target_horizon="H1")
    doc_b = PaleoMapDocument(id="map-b", name="Map B", linked_target_horizon="H2")
    page.update_state([doc_a])

    project = SimpleNamespace(paleomap_documents=[doc_a, doc_b], factor_map_tasks=[])

    class _Job:
        target = project

    page._project = project
    page._contour_job = _Job()

    draft = ContourDraft(
        id="draft-1",
        name="等值线",
        linked_factor_task_id="task-1",
        linked_map_document_id="map-b",
        segments=[],
    )
    monkeypatch.setattr(mod, "commit_contour_drafts", lambda target, result: [draft])
    captured = {}

    def fake_update_state(documents, **kwargs):
        captured["kwargs"] = kwargs

    monkeypatch.setattr(page, "update_state", fake_update_state)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    page._on_contour_completed(object())

    assert captured["kwargs"].get("prefer_id") == "map-b"
    # The active document was NOT mutated behind update_state's back; the
    # preference only flows through update_state's own guard.
    assert page.active_document() is doc_a

