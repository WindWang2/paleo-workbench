"""CompositeDocument GIS-authority regressions (CRS chain + convergence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.composite_editing import (
    GEO_TEMPLATES,
    CompositeEditController,
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


def test_layer_properties_dialog_legacy_symbology_path(qtbot, tmp_path, monkeypatch):
    """桥未构建环境：对话框走 legacy 快速字段并产出可应用 payload。

    用 monkeypatch 强制无桥——本测试的对象就是降级路径本身，不得随
    构建环境漂移（桥已构建的机器上同样必须可跑）。
    """
    from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
    from paleo_workbench.ui.workstation.composite_document import (
        _LayerPropertiesAdapter,
    )

    monkeypatch.setattr(
        "paleo_workbench.mapping.qgis_style.qgis_bridge_available",
        lambda: False,
    )
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    adapter = _LayerPropertiesAdapter(layer, opacity=1.0, metadata={})
    dialog = MapLayerPropertiesDialog(
        adapter, style=dict(layer.style), features=(), fields=("name", "fault_type")
    )
    assert dialog._qgis_symbology is False
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


# --- review 回归：会话失效后的工具重绑（Blocker #1） --------------------------


def test_tool_rebinds_after_save_edits(qtbot, tmp_path):
    """保存编辑后继续数字化必须进入新会话，不得写进已脱钩的旧缓冲。"""
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    controller.activate_tool("add_line")
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0), button="left")
    tool.mouse_press((1.0, 0.0), button="left")
    tool.mouse_press((1.0, 0.0), button="right")
    assert len(layer.features()) == 0 and len(layer.edit_session.features()) == 1

    assert controller.save_edits() is None
    assert layer.edit_session is None
    assert len(layer.features()) == 1

    controller.start_editing()
    controller.activate_tool("add_line")
    tool2 = controller.tools.active_tool
    assert tool2 is not tool
    assert tool2.session is layer.edit_session
    tool2.mouse_press((2.0, 0.0), button="left")
    tool2.mouse_press((3.0, 0.0), button="left")
    tool2.mouse_press((3.0, 0.0), button="right")
    assert len(layer.edit_session.features()) == 2, "新数字化必须进入新会话"
    assert controller.save_edits() is None
    assert len(layer.features()) == 2


def test_tool_falls_back_to_pan_after_flush(qtbot, tmp_path):
    """工程保存 flush 提交会话后，会话级工具回落 pan（不静默丢数字化）。"""
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    controller.activate_tool("add_line")
    assert controller.tools.active_tool.tool_id == "add_line"
    committed, blocked = controller.flush_edit_sessions()
    assert committed == 1 and not blocked
    assert controller.tools.active_tool.tool_id == "pan"


# --- review 回归：flush 拓扑门禁（High #3） ---------------------------------


def test_flush_respects_topology_gate(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.start_editing()
    layer.edit_session.add_feature(
        VectorFeature(
            "bad",
            {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]],
            },
        )
    )
    controller.set_topology(True)
    committed, blocked = controller.flush_edit_sessions()
    assert committed == 0
    assert blocked and "拓扑" in blocked[0]
    assert layer.edit_session is not None, "被阻断的会话保持打开（可回滚/修复）"
    # 修复后 flush 通过。
    assert controller.repair_layer_geometries(layer.id) >= 1
    committed, blocked = controller.flush_edit_sessions()
    assert committed == 1 and not blocked


# --- review 回归：显示状态持久化与顺序保持（High #4） -------------------------


def test_display_state_persists_on_save_without_sessions(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    first = controller.create_layer("断层线", "line", template="fault")
    second = controller.create_layer("相带", "polygon", template="facies")
    doc._sync_composition()

    doc.layer_manager.set_layer_visible(first.id, False)
    doc.layer_manager.set_layer_opacity(second.id, 0.4)
    committed = doc.flush_edit_sessions()
    assert committed == 0
    records = {r.id: r for r in doc._project.user_vector_layers}
    assert records[first.id].visible is False
    assert records[second.id].opacity == pytest.approx(0.4)


def test_layer_reorder_survives_composition_resync(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    first = controller.create_layer("断层线", "line", template="fault")
    second = controller.create_layer("相带", "polygon", template="facies")
    doc._sync_composition()
    # 用户把 second 上移到顶部。
    doc.layer_manager.move_layer(second.id, +1)
    ids_before = [s.id for s in doc.layer_manager._layers if s.id.startswith("composite:")]
    assert ids_before[0] == second.id
    # 内容变化触发重组：顺序必须保持（不回到插入序）。
    doc._sync_composition()
    ids_after = [s.id for s in doc.layer_manager._layers if s.id.startswith("composite:")]
    assert ids_after[0] == second.id
    controller.sync_to_project(doc._project)
    persisted = [r.id for r in doc._project.user_vector_layers]
    assert persisted[0] == second.id


def test_identify_respects_hidden_layer(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    layer.start_editing()
    layer.edit_session.add_feature(
        VectorFeature("l1", {"type": "LineString", "coordinates": [[0.0, 0.0], [2.0, 0.0]]})
    )
    doc._sync_composition()
    assert doc._identify_with_results((1.0, 0.0)) == "l1"
    doc.layer_manager.set_layer_visible(layer.id, False)
    doc._sync_composition()
    results = controller.identify_all((1.0, 0.0))
    assert all(r["layer_id"] != layer.id for r in results), "隐藏图层不得再命中识别"


# --- review 回归：每图层容差像素换算（High #2） -------------------------------


def test_layer_tolerance_converts_pixels_to_map_units(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    layer.start_editing()
    layer.edit_session.add_feature(
        VectorFeature("l1", {"type": "LineString", "coordinates": [[0.0, 0.0], [10.0, 0.0]]})
    )
    snapping = controller.snapping
    snapping.enabled = True
    snapping.modes = {"vertex"}
    # 3px 覆盖 × 0.002 地图单位/像素 = 0.006 容差：距离 0.5 的顶点不该命中。
    snapping.layer_tolerance[layer.id] = 3.0
    snapped = snapping.snap(
        (0.0, 0.5), tolerance=10.0, layers=[layer], map_units_per_pixel=0.002
    )
    assert snapped == (0.0, 0.5)
    # 全局容差 10.0（地图单位，调用方换算后）则命中。
    snapping.layer_tolerance.pop(layer.id)
    snapped = snapping.snap(
        (0.0, 0.5), tolerance=10.0, layers=[layer], map_units_per_pixel=0.002
    )
    assert snapped == (0.0, 0.0)


# --- review 回归：幂等 shutdown（Medium #8） ----------------------------------


def test_double_shutdown_does_not_rewrite_layout(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.shell import WorkstationFrame
    from PySide6.QtWidgets import QStackedWidget
    from PySide6.QtCore import QSettings

    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    frame._settings = QSettings(str(tmp_path / "ws.ini"), QSettings.Format.IniFormat)
    frame._settings.clear()
    frame.show()
    qtbot.waitExposed(frame)
    assert frame.shutdown_workers() is True
    state_first = frame._settings.value("layout/windowState")
    # 第二次（_refresh_shell 路径）不得重写已拆除的布局。
    assert frame.shutdown_workers() is True
    state_second = frame._settings.value("layout/windowState")
    assert state_second == state_first


# --- review 回归：repair 不留幽灵会话（Low #12） ------------------------------


def test_repair_without_issues_leaves_no_session(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    layer.start_editing()
    layer.edit_session.add_feature(_polygon("ok"))
    assert controller.save_edits() is None
    assert layer.edit_session is None
    assert controller.repair_layer_geometries(layer.id) == 0
    assert layer.edit_session is None, "无修复时不得留下幽灵会话"


# --- review 回归：井位参考点捕捉接线（Low #10） -------------------------------


def test_well_snap_checkbox_wires_reference_points(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.composite_panels import SnappingSettingsDialog

    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    controller.create_layer("断层线", "line", template="fault")
    dialog = SnappingSettingsDialog(controller, well_points=[(1.0, 1.0), (2.0, 2.0)])
    dialog._global_enable.setChecked(True)
    dialog._well_snap.setChecked(True)
    dialog.accept()
    snapping = controller.snapping
    assert "reference" in snapping.modes
    assert (1.0, 1.0) in snapping.reference_points
    # 取消勾选后参考点清空。
    dialog2 = SnappingSettingsDialog(controller, well_points=[(1.0, 1.0)])
    dialog2._global_enable.setChecked(True)
    dialog2._well_snap.setChecked(False)
    dialog2.accept()
    assert "reference" not in controller.snapping.modes
    assert not controller.snapping.reference_points


# --- 二轮 review 回归：undo 后选集修剪（Medium） ------------------------------


def test_undo_prunes_stale_selection(qtbot, tmp_path):
    """撤销删除要素后选集不得残留失效 id（merge 计数与几何命令的完整性）。"""
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    layer.start_editing()
    layer.edit_session.add_feature(_polygon("p1", 0.0, 0.0, 2.0, 2.0))
    layer.edit_session.add_feature(_polygon("p2", 2.0, 0.0, 4.0, 2.0))
    layer.set_selection({"p1", "p2"})
    assert controller.action_state().compatible_polygon_count == 2

    layer.edit_session.undo()
    layer.edit_session.undo()
    # 撤销两个添加后选集应为空；merge 不再可用。
    assert layer.selection == set()
    assert controller.action_state().compatible_polygon_count == 0
    ok, message = controller.geometry_command("merge")
    assert ok is False


def test_merge_after_partial_undo_is_safe(qtbot, tmp_path):
    """部分撤销后 merge 只作用于工作副本中真实存在的选中要素。"""
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    layer.start_editing()
    layer.edit_session.add_feature(_polygon("p1", 0.0, 0.0, 2.0, 2.0))
    layer.edit_session.add_feature(_polygon("p2", 2.0, 0.0, 4.0, 2.0))
    layer.set_selection({"p1", "p2"})
    layer.edit_session.undo()  # p2 消失，选集修剪为 {p1}
    assert layer.selection == {"p1"}
    ok, message = controller.geometry_command("merge")
    assert ok is False, "单要素不满足合并条件，但不得抛未捕获异常"


# -- 会话内大图层增量快照 -------------------------------------------------------


def test_session_change_journal_covers_undo_redo_and_rollback(qtbot):
    """changes_since 日志按修订覆盖增删改 / 撤销 / 重做；回滚后不可恢复。"""
    from paleo_workbench.mapping.vector_layer import VectorLayer, VectorFeature

    layer = VectorLayer(id="vl", name="层", crs="EPSG:4326")
    session = layer.start_editing()
    session.add_feature(VectorFeature("a", {"type": "Point", "coordinates": [0.0, 0.0]}))
    session.add_feature(VectorFeature("b", {"type": "Point", "coordinates": [1.0, 1.0]}))
    assert session.changes_since(0) == (("a",), ("b",))

    settled = session.revision
    assert session.changes_since(settled) == ()
    session.move_feature("a", 0.5, 0.5)
    assert session.changes_since(settled) == (("a",),)

    settled = session.revision
    assert session.undo() is True
    assert session.changes_since(settled) == (("a",),)
    assert session.redo() is True
    assert session.changes_since(settled) == (("a",), ("a",))

    settled = session.revision
    session.delete_feature("b")
    assert session.changes_since(settled) == (("b",),)

    # 未来修订不可查询。
    assert session.changes_since(session.revision + 1) is None

    settled = session.revision
    session.rollback_changes()
    assert session.changes_since(settled) is None


def test_session_journal_trim_falls_back_to_none(qtbot):
    """日志截断后，早于保留窗口的修订回落全量重建（None）。"""
    from paleo_workbench.mapping.vector_layer import (
        VectorEditSession,
        VectorLayer,
        VectorFeature,
    )

    layer = VectorLayer(id="vl", name="层", crs="EPSG:4326")
    session = layer.start_editing()
    session.add_feature(VectorFeature("a", {"type": "Point", "coordinates": [0.0, 0.0]}))
    old = session.revision
    for index in range(VectorEditSession.JOURNAL_LIMIT + 4):
        session.add_feature(
            VectorFeature(f"f{index}", {"type": "Point", "coordinates": [0.0, 0.0]})
        )
    assert session.revision - old > VectorEditSession.JOURNAL_LIMIT
    assert session.changes_since(old) is None
    # 近期修订仍在窗口内。
    recent = session.revision - 1
    assert session.changes_since(recent) is not None


def test_snapshot_layers_incremental_matches_full_rebuild(qtbot):
    """settle 增量重建与全量重建逐要素一致（内容与顺序），未触及 record 复用。"""
    import random

    controller = CompositeEditController(project_crs="EPSG:4326")
    reference = CompositeEditController(project_crs="EPSG:4326")
    layer = controller.create_layer("bench", "point")
    mirror = reference.create_layer("bench", "point")
    layer.start_editing()
    mirror.start_editing()

    rng = random.Random(20260902)
    script: list[tuple[str, str]] = []
    known: list[str] = []
    for index in range(40):
        op = rng.choice(("add", "add", "move", "attr", "delete", "undo", "redo"))
        if op == "add":
            target = f"f{index}"
            known.append(target)
        else:
            target = rng.choice(known) if known else ""
        script.append((op, target))

    previous_records: dict[str, dict] = {}
    for op, target in script:
        for session in (layer.edit_session, mirror.edit_session):
            try:
                if op == "add":
                    session.add_feature(
                        VectorFeature(target, {"type": "Point", "coordinates": [0.1, 0.2]})
                    )
                elif op == "move" and target:
                    session.move_feature(target, 0.01, 0.01)
                elif op == "attr" and target:
                    session.change_attribute(target, "kind", "well")
                elif op == "delete" and target:
                    session.delete_feature(target)
                elif op == "undo":
                    session.undo()
                elif op == "redo":
                    session.redo()
            except (KeyError, ValueError):
                pass
        snapshot = controller.snapshot_layers()[0]
        current = {record["id"]: record for record in snapshot.features}
        if op in {"add", "move", "attr", "delete"} and target:
            for feature_id, record in previous_records.items():
                if feature_id != target and feature_id in current:
                    assert current[feature_id] is record, "未触及要素必须复用 record 对象"
        previous_records = current

    incremental = controller.snapshot_layers()[0]
    exact = reference.snapshot_layers()[0]
    assert [record["id"] for record in incremental.features] == [
        record["id"] for record in exact.features
    ]
    assert list(incremental.features) == list(exact.features)


def test_snapshot_extent_grows_in_session_and_exact_after_commit(qtbot):
    """会话内 extent 单调并集（宁大勿缺）；提交后回到精确范围。"""
    controller = CompositeEditController(project_crs="EPSG:4326")
    layer = controller.create_layer("bench", "point")
    layer.start_editing()
    session = layer.edit_session
    session.add_feature(VectorFeature("near", {"type": "Point", "coordinates": [0.0, 0.0]}))
    baseline = controller.snapshot_layers()[0]
    assert baseline.extent == (0.0, 0.0, 0.0, 0.0)

    session.add_feature(VectorFeature("far", {"type": "Point", "coordinates": [80.0, 60.0]}))
    grown = controller.snapshot_layers()[0]
    assert grown.extent == (0.0, 0.0, 80.0, 60.0)

    # 删除远点：会话内范围保守（包含旧范围），不收缩出错。
    session.delete_feature("far")
    shrunk = controller.snapshot_layers()[0]
    assert shrunk.extent[2:] == (80.0, 60.0)

    # 提交（保存编辑）后 data_revision 变化 → 全量精确重建。
    session.commit_changes()
    committed = controller.snapshot_layers()[0]
    assert committed.extent == (0.0, 0.0, 0.0, 0.0)


# -- 引用矢量图层导入 Composite -------------------------------------------------


def _write_reference_points_geojson(path) -> None:
    import json

    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"label": "A"},
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
            },
            {
                "type": "Feature",
                "properties": {"label": "B"},
                "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class _MessageLog:
    def __init__(self, doc) -> None:
        self.messages: list[str] = []
        doc.status_message.connect(self.messages.append)


def test_composite_imports_reference_vector_layer(qtbot, tmp_path):
    """GDAL 矢量导入 Composite：渲染、合成顺序、持久化与重载。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    doc.edit_controller.create_layer("断层线", "line", template="fault")

    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    assert doc.import_reference_layers([str(source)]) == 1

    layers = doc.layer_manager._layers
    reference = next(
        (layer for layer in layers if layer.metadata.get("reference") == "true"), None
    )
    assert reference is not None
    assert len(reference.features) == 2
    assert reference.metadata.get("geometry_kind") == "point"
    # 合成顺序：引用垫底（基础工区 → 引用 → 编修图层）。
    user = next(
        (layer for layer in layers if layer.metadata.get("editable") == "true"), None
    )
    assert user is not None
    assert layers.index(reference) < layers.index(user)

    # 工程持久化（内存写回；磁盘保存走工程保存流程）。
    assert len(project.workstation_reference_layers) == 1
    persisted = project.workstation_reference_layers[0]
    assert persisted.source_kind == "vector"
    assert str(source) in str(persisted.source_path)

    # 重新打开工程：引用图层恢复。
    reopened = CompositeDocument(project)
    qtbot.addWidget(reopened)
    assert len(reopened._reference_layers) == 1
    assert reopened._reference_layers[0].id == persisted.id


def test_reference_display_state_writes_back_to_reference_authority(qtbot, tmp_path):
    """面板可见性 / 不透明度写回 MapReferenceLayer（保存前 flush 落盘）。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    doc.import_reference_layers([str(source)])
    reference_id = doc._reference_layers[0].id

    doc.layer_manager.set_layer_visible(reference_id, False)
    doc.layer_manager.set_layer_opacity(reference_id, 0.4)
    doc._sync_composition_now()

    reference = doc._reference_layers[0]
    assert reference.visible is False
    assert abs(reference.opacity - 0.4) < 1e-6
    assert project.workstation_reference_layers[0].visible is False


def test_reference_source_offline_degrades_honestly(qtbot, tmp_path):
    """源文件消失：要素撤空、名称标注（不可用）、状态一条不漏。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    log = _MessageLog(doc)
    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    doc.import_reference_layers([str(source)])
    reference_id = doc._reference_layers[0].id

    source.unlink()
    doc._refresh_reference_layer(reference_id)
    doc._sync_composition_now()

    reference = next(
        layer
        for layer in doc.layer_manager._layers
        if layer.id == reference_id
    )
    assert reference.features == ()
    assert "不可用" in reference.name
    assert any("refs" in message or "状态" in message for message in log.messages)


def test_reference_import_rejects_broken_sources(qtbot, tmp_path):
    """缺文件 / 坏文件：导入数为 0，失败原因经状态栏告知，无残留图层。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    log = _MessageLog(doc)

    assert doc.import_reference_layers([str(tmp_path / "missing.geojson")]) == 0
    broken = tmp_path / "broken.geojson"
    broken.write_text("not json at all", encoding="utf-8")
    assert doc.import_reference_layers([str(broken)]) == 0
    assert doc._reference_layers == []
    assert log.messages, "失败必须可见，不得静默"


def test_reference_import_without_gdal_reports_actionably(qtbot, tmp_path, monkeypatch):
    """无 GDAL 环境：导入失败给出可操作信息，Composite 不崩。"""
    from paleo_workbench.mapping.reference_layers import (
        ReferenceLayerError,
        ReferenceLayerService,
    )

    def _no_gdal(self, path, project_crs):
        raise ReferenceLayerError("参考图功能需要 GDAL（osgeo）；请安装/修复 GDAL 后重试")

    monkeypatch.setattr(ReferenceLayerService, "import_layer", _no_gdal)
    project = _project(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    log = _MessageLog(doc)
    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    assert doc.import_reference_layers([str(source)]) == 0
    assert doc._reference_layers == []
    assert any("GDAL" in message for message in log.messages)


def test_reference_snap_participation_and_removal(qtbot, tmp_path):
    """参与捕捉开关接入参考点通道；移除引用清理面板与工程文档。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    doc.import_reference_layers([str(source)])
    assert doc._reference_layer_snap_points() == []

    reference_id = doc._reference_layers[0].id
    doc._toggle_reference_snap(reference_id)
    points = doc._reference_layer_snap_points()
    assert (1.0, 2.0) in points and (3.0, 4.0) in points
    assert project.workstation_reference_layers[0].participates_in_snap is True

    doc._remove_reference_layer(reference_id)
    assert doc._reference_layers == []
    assert project.workstation_reference_layers == []
    assert all(
        layer.metadata.get("reference") != "true"
        for layer in doc.layer_manager._layers
    )


def test_reference_withheld_on_project_crs_change_until_refresh(qtbot, tmp_path):
    """工程 CRS 变更后引用归一坐标过期：扣发 + 提示；刷新按新 CRS 重读。"""
    pytest.importorskip("osgeo.gdal")
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:4326"
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    source = tmp_path / "refs.geojson"
    _write_reference_points_geojson(source)
    doc.import_reference_layers([str(source)])
    reference_id = doc._reference_layers[0].id

    # 模拟工程坐标系变更（WGS84 → UTM 50N）。
    project.coordinate.project_crs = "EPSG:32650"
    doc.edit_controller.project_crs = "EPSG:32650"
    doc._sync_composition_now()
    withheld = next(
        layer for layer in doc.layer_manager._layers if layer.id == reference_id
    )
    assert withheld.features == ()
    assert "不一致" in withheld.name

    # 刷新引用：按当前工程 CRS 重读源文件，恢复渲染与身份/显示态
    # （显示态经面板提交——面板是显示增量的唯一提交口）。
    doc.layer_manager.set_layer_visible(reference_id, False)
    doc._refresh_reference_layer(reference_id)
    refreshed_model = doc._reference_layers[0]
    assert refreshed_model.id == reference_id
    assert refreshed_model.visible is False
    assert refreshed_model.project_crs == "EPSG:32650"
    restored = next(
        layer for layer in doc.layer_manager._layers if layer.id == reference_id
    )
    assert len(restored.features) == 2
