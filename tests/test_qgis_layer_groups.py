"""V5 QGIS 原生分组桥测试：组 CRUD/嵌套/放置/上提/XML 往返/事件回声。

覆盖（V5 §81）：create group / nested / move layer / move group / group
visibility / partial checkbox / rename / delete(hoist) / reopen；桥回调
schema 2 typed events + 全层级 tree 快照；LayerGroupController 增量
reconcile 与 QGIS 树 ↔ domain 无 echo 环。
"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC_POINT = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
     "properties": {}}]}
_FC_POLYGON = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "geometry": {"type": "Polygon",
                  "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
     "properties": {}}]}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    # 编辑栈共享进程级 QgsProject::instance()：组节点不属 owned_layers，
    # shutdown 不清——残留组会跨测试污染后续断言（此处显式清空）。
    try:
        s.remove_groups_except([])
    except Exception:
        pass
    s.shutdown()


class _ShimLikeCanvas:
    """controller.attach_canvas 需要 duck-type 画布（stack/canvas_address）。"""

    def __init__(self, stack, canvas_address):
        self.stack = stack
        self.canvas_address = canvas_address


def _mirror(stack, doc, name, geom="Point", visible=True):
    fc = _FC_POINT if geom == "Point" else _FC_POLYGON
    return stack.upsert_mirror_layer(
        doc, name, geom, "EPSG:4326", json.dumps(fc), "", "", "", visible, 1.0)


def _snapshot_ids(stack):
    payload = json.loads(stack.tree_snapshot_json())

    def walk(nodes, depth=0):
        out = []
        for node in nodes:
            out.append((node["type"], node["id"]))
            out.extend(walk(node.get("children") or [], depth + 1))
        return out
    return walk(payload["children"])


# ---------------------------------------------------------------------------
# 组 CRUD / 放置
# ---------------------------------------------------------------------------

def test_create_and_nest_groups(stack):
    stack.upsert_group("phase2.factors", "单因素图", "")
    stack.upsert_group("factor.f1", "砂体厚度", "phase2.factors")
    ids = _snapshot_ids(stack)
    assert ("group", "phase2.factors") in ids
    assert ("group", "factor.f1") in ids
    # 嵌套父子关系正确。
    payload = json.loads(stack.tree_snapshot_json())
    factors = [n for n in payload["children"] if n["id"] == "phase2.factors"][0]
    assert any(c["id"] == "factor.f1" for c in factors["children"])


def test_move_layer_to_group_and_back(stack):
    _mirror(stack, "doc-a", "相图", geom="Polygon")
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.move_layer_to_group("doc-a", "phase1.initial_facies", 0)
    assert ("layer", "doc-a") in _snapshot_ids(stack)
    # 图层仍在工程中（组放置不注销图层）。
    assert stack.project_layer_count() == 1
    stack.move_layer_to_group("doc-a", "", 0)
    payload = json.loads(stack.tree_snapshot_json())
    assert any(n["id"] == "doc-a" and n["type"] == "layer"
               for n in payload["children"])


def test_move_group_rejects_descendant_target(stack):
    stack.upsert_group("g-parent", "父组", "")
    stack.upsert_group("g-child", "子组", "g-parent")
    with pytest.raises(Exception):
        stack.move_group("g-parent", "g-child", 0)


def test_rename_group(stack):
    stack.upsert_group("phase1.aux", "辅助图层", "")
    stack.rename_group("phase1.aux", "改名后")
    payload = json.loads(stack.tree_snapshot_json())
    assert any(n["id"] == "phase1.aux" and n["name"] == "改名后"
               for n in payload["children"])


def test_remove_groups_except_hoists_layers_never_deletes(stack):
    _mirror(stack, "doc-a", "相图", geom="Polygon")
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.move_layer_to_group("doc-a", "phase1.initial_facies", 0)
    removed = stack.remove_groups_except([])  # 全删
    assert removed == 1
    ids = _snapshot_ids(stack)
    assert ("group", "phase1.initial_facies") not in ids
    assert ("layer", "doc-a") in ids  # 图层上提到 root，绝不删除
    assert stack.project_layer_count() == 1


# ---------------------------------------------------------------------------
# 组可见性与事件
# ---------------------------------------------------------------------------

def test_group_visibility_programmatic_does_not_echo(qtbot, stack):
    canvas = stack.create_canvas()
    tree = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree, events.append)
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.set_group_visibility("phase1.initial_facies", False)
    qtbot.wait(150)
    assert events == []
    payload = json.loads(stack.tree_snapshot_json())
    assert [n for n in payload["children"]][0]["visible"] is False


def test_group_visibility_user_toggle_reports_typed_event(qtbot, stack):
    canvas = stack.create_canvas()
    tree = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree, events.append)
    _mirror(stack, "doc-b", "相图", geom="Polygon")
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.move_layer_to_group("doc-b", "phase1.initial_facies", 0)
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree) >= 1, timeout=2000)
    qtbot.wait(150)
    events.clear()

    top_ids = [n["id"] for n in json.loads(stack.tree_snapshot_json())["children"]]
    row = top_ids.index("phase1.initial_facies")
    stack.tree_view_set_row_checked(tree, row, False)
    qtbot.waitUntil(
        lambda: any(json.loads(e).get("events") for e in events), timeout=2000)
    payload = json.loads([e for e in events if json.loads(e).get("events")][-1])
    assert payload.get("schema") == 2
    group_events = [e for e in payload["events"] if e["node_type"] == "group"]
    assert any(e["type"] == "visibility"
               and e["node_id"] == "phase1.initial_facies"
               and e["value"] is False for e in group_events)


def test_programmatic_group_operations_do_not_echo(qtbot, stack):
    canvas = stack.create_canvas()
    tree = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree, events.append)
    _mirror(stack, "doc-a", "相图", geom="Polygon")
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.move_layer_to_group("doc-a", "phase1.initial_facies", 0)
    stack.move_layer_to_group("doc-a", "", 0)
    qtbot.wait(200)
    assert events == []


# ---------------------------------------------------------------------------
# XML 信封往返（组结构 + 放置 + 样式保持）
# ---------------------------------------------------------------------------

def test_project_xml_roundtrip_restores_groups(stack):
    _mirror(stack, "doc-a", "相图", geom="Polygon")
    _mirror(stack, "doc-b", "解释", geom="Polygon")
    stack.upsert_group("phase1.initial_facies", "初始沉积相", "")
    stack.upsert_group("phase2.factors", "单因素图", "")
    stack.upsert_group("factor.f1", "砂厚", "phase2.factors")
    stack.move_layer_to_group("doc-a", "phase1.initial_facies", 0)
    stack.move_layer_to_group("doc-b", "factor.f1", 0)
    xml = stack.write_project_xml()

    # 清空组（图层上提）再恢复。
    stack.remove_groups_except([])
    assert stack.project_layer_count() == 2
    applied = stack.apply_project_xml(xml)
    assert applied == 2
    ids = _snapshot_ids(stack)
    assert ("group", "phase1.initial_facies") in ids
    assert ("group", "factor.f1") in ids
    # doc-b 回到 factor.f1 组内。
    payload = json.loads(stack.tree_snapshot_json())
    factors = [n for n in payload["children"] if n["id"] == "phase2.factors"][0]
    factor_group = [c for c in factors["children"] if c["id"] == "factor.f1"][0]
    assert any(c["id"] == "doc-b" for c in factor_group["children"])
    assert stack.project_layer_count() == 2


# ---------------------------------------------------------------------------
# LayerGroupController ↔ 真实栈 reconcile
# ---------------------------------------------------------------------------

class _Snap:
    def __init__(self, layer_id, name):
        self.id = layer_id
        self.name = name
        self.metadata = {}
        self.template = ""


def _make_controller():
    from paleo_workbench.mapping_workspace.layer_group_controller import (
        LayerGroupController,
    )
    from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState

    state = MappingWorkspaceState()
    controller = LayerGroupController(state)
    return controller, state


def test_controller_reconcile_places_layers_by_role(qtbot, stack):
    canvas = stack.create_canvas()
    controller, state = _make_controller()
    controller.attach_canvas(_ShimLikeCanvas(stack, canvas))
    assert controller.groups_available

    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    controller.register_layer("doc-raw", LayerRole.INITIAL_FACIES_SOURCE)
    controller.register_layer("doc-draft", LayerRole.INITIAL_FACIES_DRAFT)
    controller.register_layer("doc-pl", LayerRole.PROVENANCE_LINE)
    controller.register_layer("doc-fac", LayerRole.INTEGRATED_FACIES)
    _mirror(stack, "doc-raw", "原始相图", geom="Polygon")
    _mirror(stack, "doc-draft", "解释草稿", geom="Polygon")
    _mirror(stack, "doc-pl", "物源线", geom="Point")
    _mirror(stack, "doc-fac", "综合相", geom="Polygon")

    controller.reconcile([
        _Snap("doc-raw", "原始相图"), _Snap("doc-draft", "解释草稿"),
        _Snap("doc-pl", "物源线"), _Snap("doc-fac", "综合相")])
    qtbot.wait(100)

    assert controller.placement_of("doc-raw") == "phase1.initial_facies"
    assert controller.placement_of("doc-draft") == "phase1.interpretation"
    assert controller.placement_of("doc-pl") == "phase2.constraints"
    assert controller.placement_of("doc-fac") == "phase3.integrated"
    # 系统组全部就位。
    ids = set(gid for _type, gid in _snapshot_ids(stack))
    from paleo_workbench.mapping_workspace.layer_groups import (
        SYSTEM_GROUP_TEMPLATES,
    )
    for template in SYSTEM_GROUP_TEMPLATES:
        assert template.group_id in ids


def test_controller_factor_group_organization(qtbot, stack):
    """factor 任务结果自动组织成 nested factor 组（V5 §21）。"""
    canvas = stack.create_canvas()
    controller, state = _make_controller()
    controller.attach_canvas(_ShimLikeCanvas(stack, canvas))
    controller.sync_factor_titles({"f1": "砂体厚度"})

    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    controller.register_layer(
        "fac-input", LayerRole.FACTOR_INPUT, factor_task_id="f1")
    controller.register_layer(
        "fac-contour", LayerRole.FACTOR_CONTOUR, factor_task_id="f1")
    _mirror(stack, "fac-input", "井点")
    _mirror(stack, "fac-contour", "等值线")

    controller.reconcile([_Snap("fac-input", "井点"), _Snap("fac-contour", "等值线")])
    qtbot.wait(100)
    ids = _snapshot_ids(stack)
    assert ("group", "factor.f1") in ids
    assert controller.placement_of("fac-input") == "factor.f1"
    # factor 组内顺序：input 在 contour 前（FACTOR_CHILD_ORDER）。
    payload = json.loads(stack.tree_snapshot_json())
    factors = [n for n in payload["children"] if n["id"] == "phase2.factors"][0]
    group = [c for c in factors["children"] if c["id"] == "factor.f1"][0]
    assert [c["id"] for c in group["children"]] == ["fac-input", "fac-contour"]


def test_controller_incremental_reconcile_no_op_second_time(qtbot, stack):
    """第二次 reconcile（无变化）不重建树（增量，V5 §68/§70）。"""
    canvas = stack.create_canvas()
    controller, state = _make_controller()
    controller.attach_canvas(_ShimLikeCanvas(stack, canvas))
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    controller.register_layer("doc-a", LayerRole.PROVENANCE_LINE)
    _mirror(stack, "doc-a", "物源线")
    controller.reconcile([_Snap("doc-a", "物源线")])
    qtbot.wait(50)
    before = stack.tree_snapshot_json()
    controller.reconcile([_Snap("doc-a", "物源线")])
    qtbot.wait(50)
    after = stack.tree_snapshot_json()
    assert before == after  # 结构稳定（无抖动/无重建）


def test_controller_user_move_into_wrong_system_group_rejected(qtbot, stack):
    """角色路由冲突的放置被拒（期望树保持语义组归属，V5 §51）。"""
    canvas = stack.create_canvas()
    controller, state = _make_controller()
    controller.attach_canvas(_ShimLikeCanvas(stack, canvas))
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    controller.register_layer("fac-g", LayerRole.FACTOR_GRID, factor_task_id="f1")
    _mirror(stack, "fac-g", "栅格", geom="Polygon")
    controller.reconcile([_Snap("fac-g", "栅格")])
    qtbot.wait(50)
    # 用户把 factor 栅格拖进 phase1.well_predictions → observe 拒绝。
    accepted = controller.observe_tree_nodes([
        {"type": "group", "id": "phase1.well_predictions", "name": "测井预测相",
         "children": [{"type": "layer", "id": "fac-g", "name": "栅格", "visible": True}]},
    ])
    assert accepted is False
    # 领域放置未变（下一次 reconcile 会把树拉回正确位置）。
    assert controller.placement_of("fac-g") == "factor.f1"

def test_invalid_move_self_heals_via_force_reconcile(qtbot, stack):
    """P1 修复回归：非法放置被拒后，宿主的 force reconcile 把树拉回。"""
    canvas = stack.create_canvas()
    controller, state = _make_controller()
    controller.attach_canvas(_ShimLikeCanvas(stack, canvas))
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    controller.register_layer("fac-g", LayerRole.FACTOR_GRID, factor_task_id="f1")
    controller.sync_factor_titles({"f1": "砂厚"})
    _mirror(stack, "fac-g", "栅格", geom="Polygon")
    snapshots = [_Snap("fac-g", "栅格")]

    class _LayerSnap:
        def __init__(self, layer_id, name):
            self.id = layer_id
            self.name = name
            self.metadata = {}
            self.template = ""

    controller.reconcile([_LayerSnap("fac-g", "栅格")])
    qtbot.wait(50)

    # 用户把 factor 栅格拖进 phase1.well_predictions → 拒绝 + 标记。
    accepted = controller.observe_tree_nodes([
        {"type": "group", "id": "phase1.well_predictions", "name": "测井预测相",
         "children": [{"type": "layer", "id": "fac-g", "name": "栅格",
                       "visible": True}]},
    ])
    assert accepted is False
    assert controller.last_observe_rejected is True

    # 宿主路径：拒绝 → force reconcile → QGIS 树回到领域权威位置。
    controller.reconcile([_LayerSnap("fac-g", "栅格")], force=True)
    qtbot.wait(50)
    payload = json.loads(stack.tree_snapshot_json())
    factors = [n for n in payload["children"] if n["id"] == "phase2.factors"]
    assert factors, "factor root exists"
    factor_group = [c for c in factors[0]["children"] if c["id"] == "factor.f1"]
    assert factor_group and any(
        g["id"] == "fac-g" for g in factor_group[0]["children"]), \
        "fac-g must be back in its factor group"
