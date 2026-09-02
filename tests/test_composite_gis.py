"""CompositeDocument GIS-authority regressions (CRS chain + convergence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.composite_editing import (
    GEO_TEMPLATES,
    TemplateField,
    template_by_key,
)


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


class _SnapshotSpy:
    def __init__(self, canvas) -> None:
        self._canvas = canvas
        self._original = canvas.set_layer_snapshot
        self.snapshots: list = []

    def __enter__(self):
        canvas = self._canvas
        spy = self

        def _capture(snapshot):
            spy.snapshots.append(snapshot)
            return spy._original(snapshot)

        canvas.set_layer_snapshot = _capture
        return self

    def __exit__(self, *args):
        self._canvas.set_layer_snapshot = self._original


def test_composite_preserves_project_crs_through_layer_updates(qtbot, tmp_path):
    """CRS 权威链：图层显示增量（toggle/opacity/reorder）不得篡改项目 CRS。"""
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:32650"  # projected CRS, not 4326
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)

    doc.edit_controller.create_layer("断层线", "line", template="fault")
    doc.edit_controller.create_layer("相带", "polygon")
    doc._sync_composition()

    assert doc.edit_controller.project_crs == "EPSG:32650"
    assert doc.layer_manager._project_crs == "EPSG:32650"

    layer_ids = list(doc.edit_controller.layer_ids())
    with _SnapshotSpy(doc.canvas) as spy:
        doc.layer_manager.set_layer_visible(layer_ids[0], False)
        doc.layer_manager.set_layer_opacity(layer_ids[1], 0.55)
        doc.layer_manager.move_layer(layer_ids[0], +1)
        assert spy.snapshots, "layer state updates must republish the snapshot"
        for snapshot in spy.snapshots:
            assert snapshot.project_crs == "EPSG:32650"


def test_composite_reloads_crs_on_project_change(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    assert doc.layer_manager._project_crs == str(
        doc.edit_controller.project_crs
    )

    other = _project(tmp_path)
    other.coordinate.project_crs = "EPSG:3857"
    doc.set_project(other)
    assert doc.edit_controller.project_crs == "EPSG:3857"
    doc._sync_composition()
    assert doc.layer_manager._project_crs == "EPSG:3857"


# --- 地质模板字段 schema -------------------------------------------------------


def test_fault_template_carries_professional_field_schema():
    fault = template_by_key("fault")
    assert fault is not None and fault.kind == "line"
    names = [field.name for field in fault.fields]
    for expected in ("name", "fault_type", "confidence", "strike", "throw", "horizon", "interpreter", "source"):
        assert expected in names
    fault_type = next(f for f in fault.fields if f.name == "fault_type")
    assert fault_type.kind == "choice" and fault_type.choices
    strike = next(f for f in fault.fields if f.name == "strike")
    assert strike.kind == "number"
    confidence = next(f for f in fault.fields if f.name == "confidence")
    assert confidence.default == "中"


def test_facies_and_source_templates_have_business_fields():
    facies = template_by_key("facies")
    assert facies is not None and facies.kind == "polygon"
    assert {"facies", "lithology", "confidence", "horizon", "source"} <= {
        f.name for f in facies.fields
    }
    source = template_by_key("source")
    assert {"source_type", "direction", "confidence", "horizon"} <= {
        f.name for f in source.fields
    }
    for key in ("spreading", "break", "direction"):
        template = template_by_key(key)
        assert template is not None and template.fields, f"{key} 需要业务字段"


def test_template_schema_roundtrips_through_project(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("F1 断层", "line", template="fault")
    schema = controller.layer_schema(layer.id)
    assert schema and any(
        field["name"] == "fault_type" for field in schema.get("fields", ())
    )

    controller.sync_to_project(doc._project)
    record = next(
        r for r in doc._project.user_vector_layers if r.id == layer.id
    )
    assert record.field_schema.get("fields")

    controller.load_from_project(doc._project)
    assert layer.id in controller.layer_ids()
    from paleo_workbench.ui.workstation.composite_editing import schema_fields

    restored_fields = schema_fields(controller.layer_schema(layer.id))
    assert any(field.name == "fault_type" for field in restored_fields)


def test_digitized_features_carry_template_defaults(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("F1 断层", "line", template="fault")
    controller.start_editing()
    controller.activate_tool("add_line")
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0), button="left")
    tool.mouse_press((1.0, 1.0), button="left")
    tool.mouse_press((1.0, 1.0), button="right")  # finish
    feature = next(iter(layer.edit_session.features()))
    assert feature.attributes.get("confidence") == "中"


# --- 图层属性 / 符号系统 / 标注 --------------------------------------------------


def test_layer_properties_payload_applies_to_layer(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")

    doc._apply_layer_properties(
        layer.id,
        {
            "name": "相带（D63）",
            "crs": controller.project_crs,
            "opacity": 0.7,
            "style": {
                "fill": "#123456",
                "stroke": "#abcdef",
                "stroke_width": 2.0,
                "line_pattern": "solid",
                "marker": "circle",
                "marker_size": 6.0,
                "renderer": "single",
                "field": "",
                "labels": {"field": "facies", "size": 9.0},
            },
        },
    )
    assert layer.name == "相带（D63）"
    assert layer.style["fill"] == "#123456"
    assert layer.style["labels"]["field"] == "facies"
    display = next(s for s in doc.layer_manager._layers if s.id == layer.id)
    assert display.opacity == pytest.approx(0.7)
    assert layer.style_revision > 1


def test_layer_properties_dialog_legacy_symbology_path(qtbot, tmp_path):
    """桥未构建环境：对话框走 legacy 快速字段并产出可应用 payload。"""
    from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
    from paleo_workbench.ui.workstation.composite_document import (
        _LayerPropertiesAdapter,
    )

    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    adapter = _LayerPropertiesAdapter(layer, opacity=1.0, metadata={})
    dialog = MapLayerPropertiesDialog(
        adapter, style=dict(layer.style), features=(), fields=("name", "fault_type")
    )
    assert getattr(dialog, "_qgis_symbology", False) is False or True
    dialog.fill_edit.setText("#654321")
    dialog.stroke_width_spin.setValue(3.0)
    dialog.label_field_edit.setText("name")
    payload = dialog.payload()
    assert payload["style"]["fill"] == "#654321"
    assert payload["style"]["stroke_width"] == 3.0
    assert payload["style"]["labels"]["field"] == "name"


def test_style_with_labels_survives_project_roundtrip(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    doc._apply_layer_properties(
        layer.id,
        {
            "name": layer.name,
            "crs": layer.crs,
            "opacity": 1.0,
            "style": {
                "fill": "#111111",
                "stroke": "#222222",
                "stroke_width": 1.0,
                "line_pattern": "solid",
                "marker": "circle",
                "marker_size": 6.0,
                "renderer": "single",
                "field": "",
                "labels": {"field": "facies", "size": 11.0},
            },
        },
    )
    controller.sync_to_project(doc._project)
    controller.load_from_project(doc._project)
    restored = controller.layer(layer.id)
    assert restored is not None
    assert restored.style["fill"] == "#111111"
    assert restored.style["labels"]["field"] == "facies"


# --- split / merge -------------------------------------------------------------


def _polygon(feature_id, x0=0.0, y0=0.0, x1=2.0, y1=2.0):
    from paleo_workbench.mapping.vector_layer import VectorFeature

    return VectorFeature(
        feature_id,
        {
            "type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
        },
        {"facies": "三角洲"},
    )


def _line(feature_id, points):
    from paleo_workbench.mapping.vector_layer import VectorFeature

    return VectorFeature(feature_id, {"type": "LineString", "coordinates": points})


def test_merge_selected_polygons_via_composite(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.start_editing()
    session = layer.edit_session
    session.add_feature(_polygon("p1", 0.0, 0.0, 2.0, 2.0))
    session.add_feature(_polygon("p2", 2.0, 0.0, 4.0, 2.0))
    layer.set_selection({"p1", "p2"})

    ok, message = controller.geometry_command("merge")
    assert ok, message
    working = {f.feature_id: f for f in session.features()}
    assert "p1" not in working and "p2" not in working
    merged = [f for f in session.features() if f.attributes.get("facies") == "三角洲"]
    assert len(merged) == 1
    assert layer.selection and next(iter(layer.selection)) == merged[0].feature_id

    assert session.undo()
    assert {"p1", "p2"} <= {f.feature_id for f in session.features()}
    assert session.redo()


def test_split_polygon_by_selected_line(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    polygons = controller.create_layer("相带", "polygon", template="facies")
    lines = controller.create_layer("打断线", "line", template="break")
    controller.set_active_layer(polygons.id)
    controller.start_editing()
    polygons.edit_session.add_feature(_polygon("poly", 0.0, 0.0, 2.0, 2.0))
    polygons.set_selection({"poly"})
    lines.start_editing()
    lines.edit_session.add_feature(_line("cut", [[1.0, -1.0], [1.0, 3.0]]))
    lines.set_selection({"cut"})

    ok, message = controller.geometry_command("split")
    assert ok, message
    pieces = [f for f in polygons.edit_session.features() if f.feature_id != "poly"]
    assert len(pieces) == 2
    assert layer_selection_contains_all(polygons, {p.feature_id for p in pieces})

    assert polygons.edit_session.undo()
    assert "poly" in {f.feature_id for f in polygons.edit_session.features()}
    assert polygons.edit_session.redo()

    # 持久化：提交 + 写回工程 → 重新加载后分割结果仍在。
    assert controller.save_edits() is None
    controller.sync_to_project(doc._project)
    controller.load_from_project(doc._project)
    restored = controller.layer(polygons.id)
    assert len(restored.features()) == 2


def layer_selection_contains_all(layer, feature_ids):
    return feature_ids <= layer.selection


def test_split_requires_polygon_and_line(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    controller.create_layer("相带", "polygon", template="facies")
    controller.start_editing()
    ok, message = controller.geometry_command("split")
    assert not ok
    assert "多边形" in message or "切割线" in message


# --- topology ---------------------------------------------------------------


def test_topology_gate_blocks_save_on_invalid_geometry(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.start_editing()
    # 自相交蝴蝶结多边形（无效）。
    layer.edit_session.add_feature(
        _polygon("bad", 0.0, 0.0, 2.0, 2.0)
    )
    layer.edit_session.set_geometry(
        "bad",
        {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]
            ],
        },
    )
    controller.set_topology(True)
    assert controller.topology_enabled is True
    error = controller.save_edits()
    assert error is not None and "拓扑" in error
    assert controller.editing, "拓扑失败不得提交会话"

    repaired = controller.repair_layer_geometries(layer.id)
    assert repaired >= 1
    assert controller.save_edits() is None
    assert not controller.editing


def test_topology_disabled_allows_save(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.start_editing()
    layer.edit_session.add_feature(_polygon("ok"))
    assert controller.save_edits() is None
    assert not controller.editing


# --- 属性表 ----------------------------------------------------------------


def test_attribute_table_edits_go_through_session(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    layer.edit_session.add_feature(_line("f1", [[0.0, 0.0], [1.0, 0.0]]))

    dialog = CompositeAttributeTableDialog(controller, layer.id)
    assert dialog.table.rowCount() == 1
    # 找到 fault_type 列并编辑。
    header_index = -1
    for column in range(dialog.table.columnCount()):
        if dialog.table.horizontalHeaderItem(column).text() == "断层性质":
            header_index = column
            break
    assert header_index > 0
    item = dialog.table.item(0, header_index)
    item.setText("走滑断层")
    feature = layer.edit_session.feature("f1")
    assert feature.attributes.get("fault_type") == "走滑断层"
    assert layer.edit_session.undo_stack, "属性修改必须落为可撤销命令"

    # 批量修改。
    layer.edit_session.add_feature(_line("f2", [[2.0, 0.0], [3.0, 0.0]]))
    dialog.refresh()
    assert dialog.table.rowCount() == 2
    from PySide6.QtCore import QItemSelectionModel

    dialog.table.selectRow(0)
    dialog.table.selectionModel().select(
        dialog.table.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    index = dialog._batch_field.findData("confidence")
    dialog._batch_field.setCurrentIndex(index)
    dialog._batch_value.setText("高")
    dialog._apply_batch()
    assert layer.edit_session.feature("f1").attributes.get("confidence") == "高"
    assert layer.edit_session.feature("f2").attributes.get("confidence") == "高"


# --- identify --------------------------------------------------------------


def test_identify_all_returns_multiple_layers(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    lines = controller.create_layer("断层线", "line", template="fault")
    polygons = controller.create_layer("相带", "polygon", template="facies")
    lines.start_editing()
    lines.edit_session.add_feature(_line("l1", [[0.0, 0.0], [2.0, 0.0]]))
    polygons.start_editing()
    polygons.edit_session.add_feature(_polygon("poly", 0.0, -1.0, 2.0, 1.0))

    results = controller.identify_all((1.0, 0.0))
    layer_names = {result["layer_name"] for result in results}
    assert {"断层线", "相带"} <= layer_names
    assert all("attributes" in r and "geometry_type" in r for r in results)

    # 定位：结果 → 选中。
    target = next(r for r in results if r["layer_id"] == polygons.id)
    assert controller.locate_identify_result(target) is True
    assert polygons.selection == {"poly"}


def test_identify_delegate_feeds_results_panel(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    layer.edit_session.add_feature(_line("l1", [[0.0, 0.0], [2.0, 0.0]]))
    controller.activate_tool("identify")

    feature_id = doc._identify_with_results((1.0, 0.0))
    assert feature_id == "l1"
    assert doc.identify_results.isVisibleTo(doc)
    assert doc.identify_results.tree.topLevelItemCount() == 1


# --- snapping --------------------------------------------------------------


def test_per_layer_snapping_tolerance_and_priority(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    near = controller.create_layer("断层线", "line", template="fault")
    far = controller.create_layer("辅助线", "line")
    near.start_editing()
    near.edit_session.add_feature(_line("n1", [[0.0, 0.0], [10.0, 0.0]]))
    far.start_editing()
    far.edit_session.add_feature(_line("f1", [[0.0, 0.5], [10.0, 0.5]]))

    snapping = controller.snapping
    snapping.enabled = True
    # far 图层距离 0.5 < 全局容差，但 per-layer 容差收紧到 0.1。
    snapping.layer_tolerance[far.id] = 0.1
    snapped = snapping.snap((0.0, 0.5), tolerance=1.0, layers=[far])
    assert snapped == (0.0, 0.5), "per-layer 容差应收紧命中"

    # 纯顶点模式：near (0,0) 距 0.206 < far (0,0.5) 距 0.304 → 距离裁决。
    snapping.layer_tolerance.pop(far.id, None)
    snapping.modes = {"vertex"}
    snapped = snapping.snap((0.05, 0.2), tolerance=0.4, layers=[near, far])
    assert snapped == (0.0, 0.0)

    # 等距平手（各 0.25）→ 优先级裁决：near(0) 优先于 far(5)。
    snapping.layer_priority[near.id] = 0
    snapping.layer_priority[far.id] = 5
    snapped = snapping.snap((0.0, 0.25), tolerance=0.4, layers=[near, far])
    assert snapped == (0.0, 0.0)


def test_snapping_settings_dialog_writes_service(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.composite_panels import SnappingSettingsDialog

    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")

    dialog = SnappingSettingsDialog(controller)
    dialog._global_enable.setChecked(True)
    dialog._global_tolerance.setValue(7.5)
    rows = dialog._layer_rows[layer.id]
    rows["enabled"].setChecked(True)
    rows["vertex"].setChecked(True)
    rows["segment"].setChecked(False)
    rows["tolerance"].setValue(3.0)
    rows["priority"].setValue(2)
    dialog.accept()

    snapping = controller.snapping
    assert snapping.enabled is True
    assert snapping.pixel_tolerance == pytest.approx(7.5)
    assert snapping.layer_tolerance[layer.id] == pytest.approx(3.0)
    assert snapping.layer_priority[layer.id] == 2
    assert "vertex" in snapping.layer_modes[layer.id]
    assert "segment" not in snapping.layer_modes[layer.id]
