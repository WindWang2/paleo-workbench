"""V11 原生树事务窗口合同（begin/end_tree_update + 修订号 + 计数器）。

结构性断言（非计时）：窗口内 N 次镜像 upsert 只产生 1 轮画布同步；
expand-preserving placements；token/嵌套/修订号语义。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def _bridge():
    from qgis_render_bridge import mapstack

    return mapstack.QgisMapStack()


@pytest.fixture()
def stack(qapp):
    s = _bridge()
    s.initialize()
    yield s
    try:
        s.remove_groups_except([])
    except Exception:
        pass
    s.shutdown()


def _facts(stack) -> dict:
    facts = stack.runtime_facts()
    return facts if isinstance(facts, dict) else json.loads(facts)


def _upsert(stack, doc: str, x: float = 1.0):
    fc = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point",
                                         "coordinates": [x, 1.0]},
         "properties": {}}]})
    return stack.upsert_mirror_layer(
        doc, doc, "Point", "EPSG:4326", fc, "", "", "", True, 1.0)


class TestWindowBasics:
    def test_window_coalesces_canvas_syncs(self, stack, qapp):
        canvas = stack.create_canvas()
        before = _facts(stack)["canvas_sync_count"]
        token = stack.begin_tree_update()
        for i in range(50):
            _upsert(stack, f"doc{i}", float(i))
        # 窗口内零同步
        assert _facts(stack)["canvas_sync_count"] == before
        result = json.loads(stack.end_tree_update(token))
        assert result["deferred_sync"] is True
        after = _facts(stack)["canvas_sync_count"]
        assert after == before + 1  # 50 次 upsert = 恰 1 轮同步
        assert _facts(stack)["tree_update_windows"] >= 1

    def test_without_window_each_upsert_syncs(self, stack, qapp):
        canvas = stack.create_canvas()
        before = _facts(stack)["canvas_sync_count"]
        for i in range(5):
            _upsert(stack, f"solo{i}", float(i))
        assert _facts(stack)["canvas_sync_count"] == before + 5

    def test_empty_window_no_sync(self, stack, qapp):
        canvas = stack.create_canvas()
        before = _facts(stack)["canvas_sync_count"]
        token = stack.begin_tree_update()
        result = json.loads(stack.end_tree_update(token))
        assert result["deferred_sync"] is False
        assert _facts(stack)["canvas_sync_count"] == before

    def test_token_mismatch_throws(self, stack, qapp):
        token = stack.begin_tree_update()
        with pytest.raises(RuntimeError):
            stack.end_tree_update(token + 999)

    def test_end_without_begin_throws(self, stack, qapp):
        with pytest.raises(RuntimeError):
            stack.end_tree_update(1)

    def test_nested_windows_one_sync(self, stack, qapp):
        canvas = stack.create_canvas()
        before = _facts(stack)["canvas_sync_count"]
        outer = stack.begin_tree_update()
        _upsert(stack, "a")
        inner = stack.begin_tree_update()
        _upsert(stack, "b")
        assert _facts(stack)["canvas_sync_count"] == before
        r1 = json.loads(stack.end_tree_update(inner))
        assert r1["deferred_sync"] is True  # 仍在外层窗口内
        assert _facts(stack)["canvas_sync_count"] == before
        r2 = json.loads(stack.end_tree_update(outer))
        assert _facts(stack)["canvas_sync_count"] == before + 1

    def test_revision_monotonic_and_in_window(self, stack, qapp):
        r0 = stack.tree_revision()
        token = stack.begin_tree_update()
        _upsert(stack, "r1")
        r1 = stack.tree_revision()
        assert r1 > r0  # 窗口内变更推进修订号（挂起也计数）
        stack.end_tree_update(token)
        assert stack.tree_revision() >= r1


class TestExpandPreservation:
    def test_placements_do_not_expand_collapsed_group(self, stack, qapp):
        canvas = stack.create_canvas()
        tree = stack.create_layer_tree_view(canvas)
        _upsert(stack, "layer_a")
        stack.upsert_group("g1", "组一", "")
        stack.apply_tree_placements(json.dumps(
            [{"node": "layer_a", "parent": "g1", "index": 0}]))
        # 用户收起组
        stack.set_group_expanded(tree, "g1", False)
        assert stack.tree_view_row_count(tree) >= 1
        # 再次批量放置（例如新图层入组）——收起状态必须保持
        _upsert(stack, "layer_b")
        stack.apply_tree_placements(json.dumps(
            [{"node": "layer_b", "parent": "g1", "index": 1}]))
        # 收起后行数不含子节点：组 + root 剩余 —— 具体行数随树内容而定，
        # 关键断言：layer_b 不可见（组仍收起）
        names = [stack.tree_view_layer_name(tree, i)
                 for i in range(stack.tree_view_row_count(tree))]
        joined = "\n".join(names)
        assert "layer_a" not in joined  # 仍收起（D3-native 修复）


class TestEchoRevision:
    def test_user_tree_edit_payload_carries_revision(self, stack, qapp, monkeypatch):
        # R4-P1：空断言修复——回声必须到达（非空），且携带递增修订号。
        canvas = stack.create_canvas()
        _upsert(stack, "e1")
        tree = stack.create_layer_tree_view(canvas)
        events: list[str] = []
        stack.set_tree_change_callback(
            tree, lambda payload: events.append(payload))
        r0 = stack.tree_revision()
        # 模拟用户树编辑：treeViewSetRowChecked 走用户路径
        # 找到行 0 并勾选（触发 visibility 变更批次）
        stack.tree_view_set_row_checked(tree, 0, False)
        # 批次经 QTimer(0) —— qapp.processEvents 触发
        qapp.processEvents()
        assert events, "user tree edit must flush exactly one echo batch"
        payload = json.loads(events[-1])
        assert payload.get("tree_revision", 0) > r0


class TestScaleStructural:
    def test_thousand_layer_publish_one_sync(self, stack, qapp):
        canvas = stack.create_canvas()
        before = _facts(stack)["canvas_sync_count"]
        token = stack.begin_tree_update()
        for i in range(1000):
            _upsert(stack, f"bulk{i}", float(i % 90))
        stack.end_tree_update(token)
        assert _facts(stack)["canvas_sync_count"] == before + 1
        assert stack.project_layer_count() == 1000
