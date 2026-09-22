"""拓扑编辑迁移 M1 原生编辑 MVP——宿主侧（规格 §8 → §2/§3）。

纯 Python（fake stack，无桥）：NativeEditSessionController 的会话生命周期、
三段门禁的进前/提交段、全或无保存、committed 增量写回、快照基线回滚、
手势管理器（层宏 + 逆序撤销）。真桥面（顶点 v2 场景 5 等）在
qgis-marked 测试（test_qgis_topo_m1_native_editing.py）。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.edit_gesture_manager import EditGestureManager
from paleo_workbench.mapping.edit_session_set import (
    SESSION_SET,
    reset_session_set,
)
from paleo_workbench.mapping.native_edit_session import (
    NativeEditSessionController,
)
from paleo_workbench.mapping.qgis_mirror import (
    _MIRROR_LEDGER,
    _ledger_key,
    reset_publish_ledger,
)
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.fixture(autouse=True)
def _clean_m1_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


# --------------------------------------------------------------------------- #
# 仿栈：M1 原生编辑面（能力完整 / 能力缺失两个形态）
# --------------------------------------------------------------------------- #

def _square(feature_id: str, x0=0.0, y0=0.0) -> dict:
    return {
        "id": feature_id,
        "geometry": {"type": "Polygon", "coordinates": [[
            [x0, y0], [x0 + 2.0, y0], [x0 + 2.0, y0 + 2.0], [x0, y0 + 2.0],
            [x0, y0]]]},
        "properties": {"__pwb_fid": feature_id, "name": "f"},
    }


class FakeNativeStack:
    """具备 M1 原生编辑面的假栈：记录调用、同步触发 committed 回调。"""

    def __init__(self):
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.committed_callback = None
        # doc_id → 读回要素（含编辑缓冲的「当前态」；测试直接改写）
        self.mirror: dict[str, list[dict]] = {}
        # doc_id → commit 时触发的 committed 增量
        self.pending_delta: dict[str, dict] = {}
        self.undo_texts: list[str] = []

    # -- 发布面（M0 既有，简化）-------------------------------------------
    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, *args, **kwargs):
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass

    # -- M1 原生编辑面 ------------------------------------------------------

    def start_mirror_layer_editing(self, doc_id):
        self.calls.append(("start", doc_id))
        self.editing.add(doc_id)
        return ""

    def roll_back_mirror_layer(self, doc_id):
        self.calls.append(("rollback", doc_id))
        self.editing.discard(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id):
        if doc_id not in self.editing:
            return "layer not editing"
        self.calls.append(("commit", doc_id))
        self.editing.discard(doc_id)
        delta = self.pending_delta.pop(doc_id, {"doc_id": doc_id})
        delta["doc_id"] = doc_id
        if self.committed_callback is not None:
            self.committed_callback(doc_id, json.dumps(delta))
        return ""

    def mirror_features_json(self, doc_id, limit=0):
        return json.dumps({"exists": bool(doc_id in self.mirror),
                           "features": self.mirror.get(doc_id, [])})

    def add_mirror_feature(self, doc_id, geojson):
        self.calls.append(("add_feature", doc_id))
        feature = json.loads(geojson)
        self.mirror.setdefault(doc_id, []).append({
            "id": feature.get("properties", {}).get("__pwb_fid", "new"),
            "geometry": feature.get("geometry"),
            "properties": feature.get("properties", {}),
        })
        return ""

    def undo_mirror_edit(self, doc_id):
        self.calls.append(("undo", doc_id))
        return ""

    def redo_mirror_edit(self, doc_id):
        self.calls.append(("redo", doc_id))
        return ""

    def set_committed_callback(self, canvas, callback):
        self.committed_callback = callback


class _NoNativeStack(FakeNativeStack):
    """旧桥：无原生编辑面（方法缺席——能力探测应判不支持）。"""

    start_mirror_layer_editing = None
    commit_mirror_layer = None


def _layer(layer_id="draft-1", features=("a",)) -> VectorLayer:
    return VectorLayer(
        id=layer_id, name=layer_id, crs="",
        features=[VectorFeature(fid, _square(fid)["geometry"],
                                {"name": "f"}) for fid in features],
    )


def _allow_all(layer_id):
    return True, ""


def _reject_raw(layer_id):
    return False, "图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑"


# --------------------------------------------------------------------------- #
# 场景 1：RAW 保护（进前拒绝，无 startEditing 发生）
# --------------------------------------------------------------------------- #

def test_scenario1_raw_layer_never_starts_editing():
    stack = FakeNativeStack()
    layer = _layer("raw-1")
    controller = NativeEditSessionController()
    ok, reason = controller.open(stack, layer, gate=_reject_raw)
    assert not ok and "RAW" in reason
    assert ("start", "raw-1") not in stack.calls, "拒绝则不开 startEditing"
    assert not SESSION_SET.is_open


def test_open_rejects_when_bridge_lacks_surface():
    controller = NativeEditSessionController()
    ok, reason = controller.open(_NoNativeStack(), _layer(), gate=_allow_all)
    assert not ok and "桥" in reason


def test_open_starts_editing_and_opens_session_set():
    stack = FakeNativeStack()
    layer = _layer("draft-1")
    controller = NativeEditSessionController()
    ok, reason = controller.open(stack, layer, gate=_allow_all)
    assert ok, reason
    assert ("start", "draft-1") in stack.calls
    assert SESSION_SET.contains("draft-1")
    assert SESSION_SET.active_layer_ids(stack) == ("draft-1",), "停发窗口生效"
    # 幂等：重复开启不二次 startEditing
    ok, _ = controller.open(stack, layer, gate=_allow_all)
    assert ok
    assert stack.calls.count(("start", "draft-1")) == 1


# --------------------------------------------------------------------------- #
# 场景 4：崩溃易失（未提交编辑不落盘——真源只含已提交状态）
# --------------------------------------------------------------------------- #

def test_scenario4_uncommitted_edits_never_reach_truth():
    stack = FakeNativeStack()
    layer = _layer("draft-1")
    controller = NativeEditSessionController()
    controller.open(stack, layer, gate=_allow_all)
    # 编辑发生在镜像缓冲（假栈 mirror 态变化），Python 真源不动。
    stack.mirror["draft-1"] = [_square("a", x0=5.0)]
    assert list(layer.feature("a").geometry["coordinates"][0][0]) == [0.0, 0.0]
    # 工程持久化读 layer.features()（只含已提交状态）——未提交编辑即丢。
    persisted = [f.as_record() for f in layer.features()]
    assert list(persisted[0]["geometry"]["coordinates"][0][0]) == [0.0, 0.0]


# --------------------------------------------------------------------------- #
# committed 增量写回（§2 回写通道：EditCommand 同族 → user_vector_layers）
# --------------------------------------------------------------------------- #

def test_apply_committed_delta_geometry_change():
    layer = _layer(features=("a",))
    before_revision = layer.data_revision
    delta = {
        "doc_id": "draft-1",
        "geometry_changes": [{
            "feature_id": "a",
            "geometry": {"type": "Polygon", "coordinates": [[
                [1.0, 1.0], [3.0, 1.0], [3.0, 3.0], [1.0, 3.0], [1.0, 1.0]]]},
        }],
    }
    records = layer.apply_committed_delta(delta, session_id="s1",
                                          source_tool="vertex(native)")
    assert list(layer.feature("a").geometry["coordinates"][0][0]) == [1.0, 1.0]
    assert layer.data_revision == before_revision + 1
    assert records and records[0]["feature_ids"] == ["a"]
    assert "vertex(native)" in str(records[0])


def test_apply_committed_delta_add_remove_attribute():
    layer = _layer(features=("a",))
    delta = {
        "doc_id": "draft-1",
        "added": [{
            "id": "b",
            "geometry": _square("b", x0=10.0)["geometry"],
            "properties": {"__pwb_fid": "b", "name": "new"},
        }],
        "attribute_changes": [{
            "feature_id": "a", "changes": {"name": "renamed"},
        }],
        "removed": [],
    }
    layer.apply_committed_delta(delta, session_id="s1",
                                source_tool="native")
    assert layer.feature("b").attributes["name"] == "new"
    assert layer.feature("a").attributes["name"] == "renamed"
    remove_delta = {"doc_id": "draft-1", "removed": ["a"]}
    layer.apply_committed_delta(remove_delta, session_id="s1",
                                source_tool="native")
    assert layer.feature_ids() == ("b",)


# --------------------------------------------------------------------------- #
# 场景 3：保存全或无（会话集合判定 → 全过同提交 / 任一失败全保持）
# ---------------------------------------------------------------------------

def _two_layer_setup():
    stack = FakeNativeStack()
    layer_a = _layer("draft-a", ("fa",))
    layer_b = _layer("draft-b", ("fb",))
    stack.mirror["draft-a"] = [_square("fa")]
    stack.mirror["draft-b"] = [_square("fb")]
    controller = NativeEditSessionController()
    assert controller.open(stack, layer_a, gate=_allow_all)[0]
    assert controller.open(stack, layer_b, gate=_allow_all)[0]
    return stack, controller, layer_a, layer_b


def test_scenario3_blocked_topology_keeps_whole_set():
    stack, controller, layer_a, layer_b = _two_layer_setup()
    stack.mirror["draft-b"] = [{  # 自相交坏几何（蝴蝶结）
        "id": "fb",
        "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]},
        "properties": {"__pwb_fid": "fb"},
    }]
    aligned, committed_layers = [], []
    ok, reason = controller.commit_all(
        gate=_allow_all, topology=TopologyService(enabled=True),
        on_committed=lambda layer: (
            aligned.append(layer.id),
            committed_layers.append(layer)),
    )
    assert not ok and "draft-b" in reason and "拓扑" in reason
    # 全集合保持会话、无任何层提交
    assert stack.calls.count(("commit", "draft-a")) == 0
    assert stack.calls.count(("commit", "draft-b")) == 0
    assert SESSION_SET.is_open
    assert aligned == []

    # 修复后（读回恢复合法几何）保存 → 两层同提交 + 增量写回 + 台账对齐
    stack.mirror["draft-b"] = [_square("fb")]
    stack.pending_delta["draft-a"] = {
        "geometry_changes": [{
            "feature_id": "fa",
            "geometry": _square("fa", x0=1.0)["geometry"]}],
    }
    ok, reason = controller.commit_all(
        gate=_allow_all, topology=TopologyService(enabled=True),
        on_committed=lambda layer: (
            aligned.append(layer.id), committed_layers.append(layer)),
    )
    assert ok, reason
    assert stack.calls.count(("commit", "draft-a")) == 1
    assert stack.calls.count(("commit", "draft-b")) == 1
    assert aligned == ["draft-a", "draft-b"]
    # 增量已写回真源（fa 移动到 x0=1）
    assert list(layer_a.feature("fa").geometry["coordinates"][0][0]) == [1.0, 0.0]
    assert not SESSION_SET.is_open, "提交后关闭停发窗口"


def test_commit_all_aborts_when_gate_rejects_layer():
    stack, controller, layer_a, layer_b = _two_layer_setup()
    def gate(layer_id):
        return (False, "当前结果已冻结——不可编辑") if layer_id == "draft-b" else (True, "")
    ok, reason = controller.commit_all(
        gate=gate, topology=TopologyService(enabled=False),
        on_committed=None)
    assert not ok and "draft-b" in reason
    assert stack.calls.count(("commit", "draft-a")) == 0


def test_rollback_restores_baseline_and_closes_window():
    stack = FakeNativeStack()
    layer = _layer("draft-1")
    controller = NativeEditSessionController()
    controller.open(stack, layer, gate=_allow_all)
    stack.mirror["draft-1"] = [_square("a", x0=99.0)]  # 缓冲区编辑
    ok, reason = controller.rollback("draft-1")
    assert ok, reason
    assert ("rollback", "draft-1") in stack.calls
    assert not SESSION_SET.is_open
    assert list(layer.feature("a").geometry["coordinates"][0][0]) == [0.0, 0.0]


# --------------------------------------------------------------------------- #
# 手势管理器（§2 不变式：层宏 + 逆序撤销 / 正序重做）
# --------------------------------------------------------------------------- #

def test_gesture_manager_undo_plan_is_reverse_order():
    manager = EditGestureManager()
    manager.finish("g1", undo_text="Moved vertex", layer_ids=["L1"])
    manager.finish("g2", undo_text="Moved vertex",
                   layer_ids=["L1", "L2", "L3"])
    # 最近手势 g2：整手势撤销 = 逆序逐层
    assert manager.undo_plan() == ["L3", "L2", "L1"]
    manager.mark_undone("g2")
    assert manager.undo_plan() == ["L1"], "回退到上一手势"
    # 重做正序（g2 先于更早手势？重做栈 LIFO：g2 的重做在前）
    assert manager.redo_plan() == ["L1", "L2", "L3"]
    manager.mark_redone("g2")
    assert manager.redo_plan() == []


def test_gesture_manager_clear_on_commit():
    manager = EditGestureManager()
    manager.finish("g1", undo_text="Moved vertex", layer_ids=["L1"])
    manager.clear()  # 提交/回滚后手势历史作废（QGIS commit 清 undo 栈）
    assert manager.undo_plan() == []


def test_gesture_manager_audit_record():
    manager = EditGestureManager()
    manager.finish("g1", undo_text="Moved vertex", layer_ids=["L1"])
    records = manager.audit_records()
    assert records[0]["gesture_id"] == "g1"
    assert records[0]["undo_text"] == "Moved vertex"
    assert records[0]["layer_ids"] == ["L1"]
