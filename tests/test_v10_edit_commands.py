"""V10 host-side edit commands: duplicate / explode / collect / ring / part.

控制器级事务链（一个动作 = 一个 undo 单元 / delta 映射 / 选集语义 / 诚实
拒绝消息）+ 工具可用性矩阵（contract v4 事实）。
"""

from pathlib import Path

import pytest

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def _document(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _polygon_layer_with(document, features):
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon")
    controller.start_editing()
    session = layer.edit_session
    from paleo_workbench.mapping.vector_layer import VectorFeature

    for feature_id, geometry in features:
        session.add_feature(VectorFeature(feature_id, geometry, {"facies_name": "delta"}))
    controller.save_edits()
    controller.start_editing()
    return controller, layer, layer.edit_session


_SQUARE_A = {"type": "Polygon", "coordinates": [
    [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]}
_SQUARE_B = {"type": "Polygon", "coordinates": [
    [[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0], [20.0, 0.0]]]}
_MULTI = {"type": "MultiPolygon", "coordinates": [
    _SQUARE_A["coordinates"], _SQUARE_B["coordinates"]]}


# -- duplicate_selected --------------------------------------------------------


def test_duplicate_selected_command(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, session = _polygon_layer_with(
        document, [("f1", _SQUARE_A)])
    layer.set_selection(("f1",))
    assert controller.edit_command("duplicate_selected")
    ids = {f.feature_id for f in session.features()}
    assert "f1" in ids and len(ids) == 2
    duplicate = next(f for f in session.features() if f.feature_id != "f1")
    assert duplicate.attributes["facies_name"] == "delta"
    # 选集切换到副本
    assert layer.selection == {duplicate.feature_id}
    # 一个动作 = 一个 undo 单元
    assert len(session.undo_stack) == 1
    assert session.undo()
    assert {f.feature_id for f in session.features()} == {"f1"}


def test_duplicate_requires_selection(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(document, [("f1", _SQUARE_A)])
    layer.set_selection(())
    assert not controller.edit_command("duplicate_selected")


# -- explode / collect ---------------------------------------------------------


def test_explode_multipart_command(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, session = _polygon_layer_with(document, [("f1", _MULTI)])
    layer.set_selection(("f1",))
    ok, message = controller.geometry_command("explode_multipart")
    assert ok, message
    features = list(session.features())
    assert len(features) == 2  # 1 → 2 单部件
    assert all(f.geometry["type"] == "Polygon" for f in features)
    # 属性全继承
    assert all(f.attributes["facies_name"] == "delta" for f in features)
    # 单一 undo 单元回到 multipart
    assert len(session.undo_stack) == 1
    assert session.undo_stack[0].command_type == "split_feature"
    assert session.undo()
    assert len(session.features()) == 1
    assert session.features()[0].geometry["type"] == "MultiPolygon"


def test_explode_rejects_singlepart_selection(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(document, [("f1", _SQUARE_A)])
    layer.set_selection(("f1",))
    ok, message = controller.geometry_command("explode_multipart")
    assert not ok and "多部件" in message


def test_collect_multipart_command(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, session = _polygon_layer_with(
        document, [("f1", _SQUARE_A), ("f2", _SQUARE_B)])
    layer.set_selection(("f1", "f2"))
    ok, message = controller.geometry_command("collect_multipart")
    assert ok, message
    features = list(session.features())
    assert len(features) == 1
    assert features[0].geometry["type"] == "MultiPolygon"
    assert len(features[0].geometry["coordinates"]) == 2  # collect 不 dissolve
    # 属性 = 首个选中要素（选择序 D2 策略）
    assert features[0].attributes["facies_name"] == "delta"
    assert len(session.undo_stack) == 1
    assert session.undo_stack[0].command_type == "merge_features"
    assert session.undo()
    assert len(session.features()) == 2


def test_collect_rejects_mixed_or_multipart(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(
        document, [("f1", _SQUARE_A), ("f2", _MULTI)])
    layer.set_selection(("f1", "f2"))
    ok, message = controller.geometry_command("collect_multipart")
    assert not ok


# -- ring / part 命令（pick_point API 面） ---------------------------------------


def test_delete_ring_command_by_pick_point(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    with_hole = {"type": "Polygon", "coordinates": [
        _SQUARE_A["coordinates"][0],
        [[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]],
    ]}
    controller, layer, session = _polygon_layer_with(document, [("f1", with_hole)])
    layer.set_selection(("f1",))
    ok, message = controller._ring_and_part_commands("delete_ring", pick_point=(5.0, 5.0))
    assert ok, message
    rings = session.feature("f1").geometry["coordinates"]
    assert len(rings) == 1
    assert len(session.undo_stack) == 1
    assert session.undo()
    assert len(session.feature("f1").geometry["coordinates"]) == 2


def test_delete_ring_without_interior_ring_rejected(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(document, [("f1", _SQUARE_A)])
    layer.set_selection(("f1",))
    ok, message = controller._ring_and_part_commands("delete_ring", pick_point=(5.0, 5.0))
    assert not ok


def test_move_part_command_by_pick_point(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, session = _polygon_layer_with(document, [("f1", _MULTI)])
    layer.set_selection(("f1",))
    ok, message = controller._ring_and_part_commands(
        "move_part", pick_point={"point": (25.0, 5.0), "delta": (5.0, 0.0)})
    assert ok, message
    parts = session.feature("f1").geometry["coordinates"]
    assert parts[1][0][0] == (25.0, 0.0)  # 部件 1 平移 +5；部件 0 原地
    assert parts[0][0][0] == (0.0, 0.0)
    assert len(session.undo_stack) == 1
    assert session.undo()
    assert session.feature("f1").geometry["coordinates"][1][0][0] == (20.0, 0.0)


def test_move_part_requires_delta_spec(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(document, [("f1", _MULTI)])
    layer.set_selection(("f1",))
    ok, message = controller._ring_and_part_commands("move_part", pick_point=(25.0, 5.0))
    assert not ok and "delta" in message


def test_ring_and_part_commands_need_single_selection(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer, _ = _polygon_layer_with(
        document, [("f1", _MULTI), ("f2", _SQUARE_A)])
    layer.set_selection(("f1", "f2"))
    ok, message = controller._ring_and_part_commands("delete_part", pick_point=(25.0, 5.0))
    assert not ok and "恰好" in message


# -- 工具可用性矩阵（contract v4 事实 → 新工具门禁） -----------------------------


def _context(**overrides):
    from paleo_workbench.mapping.tool_context import ToolContext

    base = dict(
        project_open=True,
        qgis_available=True,
        native_canvas_available=True,
        backend_mode="native",
        mapping_stage=None,
        active_layer_id="L1",
        active_layer_kind="polygon",
        vector_writable=True,
        edit_gate_open=True,
        editing=True,
        selection_count=1,
        selection_geometry_types=("polygon",),
        compatible_polygon_count=1,
        selection_multipart_count=1,
        collect_ready=False,
        capability_flags=frozenset({
            "qgis.native_tool.addPolygon", "qgis.native_tool.addLine",
            "qgis.geometry_op.reshape", "qgis.geometry_op.add_part",
        }),
        queryable_layer_count=1,
    )
    base.update(overrides)
    return ToolContext(**base)


def test_new_tools_availability_matrix():
    from paleo_workbench.mapping.tool_availability import evaluate_tool

    # 全条件满足：duplicate/explode 可用
    assert evaluate_tool("duplicate_selected", _context()).enabled
    assert evaluate_tool("explode_multipart", _context()).enabled
    assert evaluate_tool("add_ring", _context()).enabled
    assert evaluate_tool("add_part", _context()).enabled
    # collect 需要同类型单部件 ≥2（本上下文选的是 multipart）
    result = evaluate_tool("collect_multipart", _context())
    assert not result.enabled and "同类型" in result.disabled_reason

    # 选集为空 → duplicate 禁用
    result = evaluate_tool("duplicate_selected", _context(selection_count=0))
    assert not result.enabled and "选中" in result.disabled_reason

    # 非多部件选集 → explode 禁用
    result = evaluate_tool("explode_multipart", _context(selection_multipart_count=0))
    assert not result.enabled and "多部件" in result.disabled_reason

    # 非面图层 → add_ring 禁用
    result = evaluate_tool("add_ring", _context(active_layer_kind="line"))
    assert not result.enabled and "面图层" in result.disabled_reason

    # 选集非恰一个 → add_part/add_ring 禁用
    result = evaluate_tool("add_part", _context(selection_count=2))
    assert not result.enabled and "恰好" in result.disabled_reason
    result = evaluate_tool("add_ring", _context(selection_count=0))
    assert not result.enabled

    # 无原生画布 → add_ring/add_part 禁用（native-only 家族）
    result = evaluate_tool("add_ring", _context(native_canvas_available=False))
    assert not result.enabled and "原生" in result.disabled_reason
    result = evaluate_tool("add_part", _context(native_canvas_available=False))
    assert not result.enabled

    # 桥缺 add_part 算子 → add_part 禁用（诚实降级）
    result = evaluate_tool(
        "add_part",
        _context(capability_flags=["qgis.native_tool.addPolygon", "qgis.geometry_op.reshape"]),
    )
    assert not result.enabled and "add_part" in result.disabled_reason

    # collect 全条件
    assert evaluate_tool(
        "collect_multipart", _context(collect_ready=True, selection_count=2)).enabled


def test_collect_blocked_by_topology_errors():
    from paleo_workbench.mapping.tool_availability import evaluate_tool

    result = evaluate_tool(
        "collect_multipart",
        _context(collect_ready=True, selection_count=2, topology_error_count=3),
    )
    assert not result.enabled and "拓扑" in result.disabled_reason


def test_new_tools_in_canonical_groups():
    from paleo_workbench.mapping.tool_availability import TOOL_GROUPS, TOOL_IDS

    for tool_id in ("duplicate_selected", "add_ring", "add_part",
                    "explode_multipart", "collect_multipart"):
        assert tool_id in TOOL_IDS
        assert tool_id in TOOL_GROUPS["geometry"]
