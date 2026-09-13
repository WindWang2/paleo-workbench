# -*- coding: utf-8 -*-
"""拓扑编辑迁移 M4：检查器——宿主侧（规格 §8 → §5）。

场景 13（忽略豁免保存放行 / 灰显可恢复 / 恢复后再阻断）、
场景 16（保存成功后镜像=真源、台账对齐、fid 表、审计含手势溯源）、
门禁合并、双豁免持久化、面板灰显。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.edit_session_set import (
    SESSION_SET,
    reset_session_set,
)
from paleo_workbench.mapping.native_edit_session import (
    NativeEditSessionController,
)
from paleo_workbench.mapping.qgis_mirror import (
    reset_publish_ledger,
)
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.fixture(autouse=True)
def _clean_m4_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


def _square(feature_id: str, x0=0.0, y0=0.0) -> dict:
    return {
        "id": feature_id,
        "geometry": {"type": "Polygon", "coordinates": [[
            [x0, y0], [x0 + 2.0, y0], [x0 + 2.0, y0 + 2.0], [x0, y0 + 2.0],
            [x0, y0]]]},
        "properties": {"__pwb_fid": feature_id, "name": "f"},
    }


_OVERLAP_ERROR = {
    "id": "0",
    "rule": "overlap",
    "layer_id": "draft-b",
    "feature_id": "fb",
    "other_feature_id": "fa",
    "message": "Overlap",
    "fixable": True,
    "bbox": [1.0, 1.0, 2.0, 2.0],
    "methods": [{"id": 0, "name": "Subtract", "description": "裁掉重叠"}],
}


class FakeCheckerStack:
    """M1 原生面 + M4 检查器面。"""

    def __init__(self):
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.committed_callback = None
        self.mirror: dict[str, list[dict]] = {}
        self.pending_delta: dict[str, dict] = {}
        self.check_errors: list[dict] = []
        self.fixed: list[tuple] = []
        self.extent = [0.0, 0.0, 10.0, 10.0]
        self.highlights: list[str] = []

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

    def undo_mirror_edit(self, doc_id):
        self.calls.append(("undo", doc_id))
        return ""

    def redo_mirror_edit(self, doc_id):
        self.calls.append(("redo", doc_id))
        return ""

    def set_committed_callback(self, canvas, callback):
        self.committed_callback = callback

    def run_geometry_checks(self, canvas, config_json):
        self.calls.append(("check", json.loads(config_json)
                           if isinstance(config_json, str) else config_json))
        return json.dumps({"errors": list(self.check_errors)})

    def fix_geometry_error(self, canvas, error_id, method):
        self.fixed.append((str(error_id), int(method)))
        return json.dumps({"ok": True, "errors": []})

    def fix_geometry_errors(self, canvas, ids_json, method):
        ids = json.loads(ids_json) if isinstance(ids_json, str) else ids_json
        for error_id in ids:
            self.fixed.append((str(error_id), int(method)))
        self.check_errors = []
        return json.dumps({"ok": True, "errors": []})

    def highlight_checker_errors(self, canvas, ids_json):
        ids = json.loads(ids_json) if isinstance(ids_json, str) else ids_json
        self.highlights = [str(i) for i in ids]

    def highlight_count(self, canvas):
        return len(self.highlights)

    def set_canvas_extent(self, canvas, xmin, ymin, xmax, ymax):
        self.extent = [xmin, ymin, xmax, ymax]

    def canvas_extent(self, canvas):
        return list(self.extent)


def _layer(layer_id="draft-1", features=("a",)) -> VectorLayer:
    return VectorLayer(
        id=layer_id, name=layer_id, crs="",
        features=[VectorFeature(fid, _square(fid)["geometry"],
                                {"name": "f"}) for fid in features],
    )


def _allow_all(layer_id):
    return True, ""


def _two_layer_setup():
    stack = FakeCheckerStack()
    layer_a = _layer("draft-a", ("fa",))
    layer_b = _layer("draft-b", ("fb",))
    stack.mirror["draft-a"] = [_square("fa")]
    stack.mirror["draft-b"] = [_square("fb")]
    controller = NativeEditSessionController()
    assert controller.open(stack, layer_a, gate=_allow_all)[0]
    assert controller.open(stack, layer_b, gate=_allow_all)[0]
    return stack, controller, layer_a, layer_b


def test_scenario13_ignore_exemption_allows_save_restore_blocks():
    """场景 13：忽略重叠保存放行；恢复后再次阻断。"""
    from paleo_workbench.mapping.topology_checker import TopologyChecker

    stack, controller, _layer_a, _layer_b = _two_layer_setup()
    stack.check_errors = [dict(_OVERLAP_ERROR)]
    topology = TopologyService(enabled=True)
    assert isinstance(topology.checker, TopologyChecker)

    ok, reason = controller.commit_all(
        gate=_allow_all, topology=topology, on_committed=None)
    assert not ok and "拓扑" in reason
    assert stack.calls.count(("commit", "draft-a")) == 0
    assert SESSION_SET.is_open

    topology.checker.ignore(_OVERLAP_ERROR, reason="地质上可接受")
    blocking = topology.checker.blocking_errors()
    assert blocking == []

    ok, reason = controller.commit_all(
        gate=_allow_all, topology=topology, on_committed=None)
    assert ok, reason
    assert stack.calls.count(("commit", "draft-a")) == 1
    assert stack.calls.count(("commit", "draft-b")) == 1

    # 新会话：恢复忽略后再阻断。
    stack2, controller2, _a2, _b2 = _two_layer_setup()
    stack2.check_errors = [dict(_OVERLAP_ERROR)]
    topology.checker.restore(_OVERLAP_ERROR)
    ok, reason = controller2.commit_all(
        gate=_allow_all, topology=topology, on_committed=None)
    assert not ok and "拓扑" in reason
    assert stack2.calls.count(("commit", "draft-a")) == 0


def test_ignore_and_allowed_gaps_persist_with_project():
    """双豁免随工程持久化：忽略列表 + 缝隙白名单。"""
    from paleo_workbench.mapping.topology_checker import TopologyChecker

    checker = TopologyChecker()
    checker.ignore(_OVERLAP_ERROR, reason="accepted")
    gap = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    checker.add_allowed_gap(gap)
    snapshot = checker.persist()
    assert snapshot["ignored"]
    assert snapshot["allowed_gaps"]

    restored = TopologyChecker()
    restored.restore_state(snapshot)
    assert restored.is_ignored(_OVERLAP_ERROR)
    assert restored.allowed_gaps
    restored.restore(_OVERLAP_ERROR)
    assert not restored.is_ignored(_OVERLAP_ERROR)


def test_panel_greys_ignored_errors_and_emits_zoom(qapp):
    """面板：被忽略灰显可恢复；点击发出缩放/高亮。"""
    from paleo_workbench.ui.workstation.topology_checker_panel import (
        TopologyCheckerPanel,
    )

    panel = TopologyCheckerPanel()
    zooms = []
    panel.zoom_requested.connect(lambda bbox: zooms.append(list(bbox)))
    panel.set_errors(
        [_OVERLAP_ERROR, {
            **_OVERLAP_ERROR, "id": "1", "feature_id": "fc",
            "message": "Overlap 2",
        }],
        ignored_keys={("overlap", "draft-b", "fb", "fa")},
    )
    assert panel.error_list.count() == 2
    ignored_item = panel.error_list.item(0)
    live_item = panel.error_list.item(1)
    ignored_color = ignored_item.foreground().color()
    live_color = live_item.foreground().color()
    assert ignored_color.lightness() > live_color.lightness() or \
        ignored_color.alpha() < 255 or \
        ignored_item.font().italic()
    panel.error_list.setCurrentItem(ignored_item)
    panel.error_list.itemClicked.emit(ignored_item)
    assert zooms and zooms[-1] == [1.0, 1.0, 2.0, 2.0]
    panel.close()


def test_scenario16_commit_aligns_ledger_and_records_gesture_audit():
    """场景 16：保存成功后真源对齐、台账 authoritative、审计含手势溯源。"""
    from paleo_workbench.mapping.qgis_mirror import (
        _MIRROR_LEDGER,
        _ledger_key,
        align_publish_ledger_for_layer,
    )

    stack, controller, layer_a, _layer_b = _two_layer_setup()
    stack.check_errors = []
    topology = TopologyService(enabled=True)
    controller.gestures.finish(
        "g-moved", undo_text="Moved vertex", layer_ids=["draft-a"])
    stack.pending_delta["draft-a"] = {
        "geometry_changes": [{
            "feature_id": "fa",
            "geometry": _square("fa", x0=1.0)["geometry"]}],
    }
    # 先占台账条目（模拟此前已发布），对齐才生效。
    from paleo_workbench.mapping.qgis_mirror import _LedgerEntry
    _MIRROR_LEDGER[_ledger_key(stack, "draft-a")] = _LedgerEntry(
        1, "style", True, 1.0, "Polygon", {"fa": True},
        name="draft-a", scale_range=None, authoritative=False)

    aligned = []
    ok, reason = controller.commit_all(
        gate=_allow_all, topology=topology,
        on_committed=lambda layer: (
            aligned.append(layer.id),
            align_publish_ledger_for_layer(stack, layer)),
    )
    assert ok, reason
    assert aligned == ["draft-a", "draft-b"]
    assert list(layer_a.feature("fa").geometry["coordinates"][0][0]) == [1.0, 0.0]
    entry = _MIRROR_LEDGER[_ledger_key(stack, "draft-a")]
    assert entry.authoritative is True
    journal = layer_a.commit_audit()
    assert journal, "提交审计流应含写回记录"
    assert any(record.get("source_tool") == "native" for record in journal)
    assert any(
        "Moved vertex" in str(record.get("gestures") or record.get("undo_text") or "")
        or (record.get("gestures") or [])
        for record in journal
    ) or any(
        g.get("undo_text") == "Moved vertex"
        for record in journal
        for g in (record.get("gestures") or [])
    )


def test_save_edits_python_path_uses_checker_when_present(qapp):
    """Python 会话 save_edits 门禁校验**工作副本**，且共用忽略豁免。

    回归：门禁曾把 Python 会话交给桥检查器（只读镜像），未提交的坏几何
    因不在镜像里而被静默放行——镜像里查不到，保存就过了。
    """
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    stack = FakeCheckerStack()
    canvas = type("Canvas", (), {})()
    canvas.canvas_address = 1
    canvas.stack = stack
    canvas.set_map_tool_controller = lambda tools: None
    canvas.set_overlay_provider = lambda overlay: None

    controller = CompositeEditController()
    # FakeCheckerStack 具备原生编辑面——本用例钉 Python 会话路径，显式关掉
    # 原生翻转（原生会话的门禁见 test_scenario13 / test_qgis_topo_m4_checker）。
    controller._native_session_eligible = lambda _layer: False
    layer = controller.create_layer("相带", "polygon", template="facies")
    # 桥检查器面在位但零错误：阻断只能来自工作副本（这正是回归点）。
    stack.check_errors = []
    controller.attach_canvas(canvas)
    controller.set_topology(True)
    controller.start_editing()
    assert layer.edit_session is not None
    layer.edit_session.add_feature(VectorFeature(
        "bad",
        {"type": "Polygon", "coordinates": [
            [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]]},
        {},
    ))

    reason = controller.save_edits()
    assert reason and "拓扑" in reason, reason
    assert layer.edit_session is not None

    # 忽略豁免归检查器：面板判"地质上可接受"后同一会话保存放行。
    for issue in controller.topology.validate([layer]):
        controller.topology.checker.ignore(issue, reason="accepted")
    assert controller.save_edits() is None
    assert layer.edit_session is None


def test_panel_badge_shows_count_and_timestamp(qapp):
    """徽章 = 上次未忽略条数 + 时间。"""
    from paleo_workbench.ui.workstation.topology_checker_panel import (
        TopologyCheckerPanel,
    )

    panel = TopologyCheckerPanel()
    assert "尚未检查" in panel.badge.text()
    panel.set_errors(
        [_OVERLAP_ERROR],
        ignored_keys=set(),
        last_run_at="2026-09-12T12:00:00+00:00",
    )
    text = panel.badge.text()
    assert "1 处未忽略" in text
    assert "2026-09-12" in text
    panel.set_errors(
        [_OVERLAP_ERROR],
        ignored_keys={("overlap", "draft-b", "fb", "fa")},
    )
    assert "0 处未忽略" in panel.badge.text()
    panel.close()


def test_panel_context_menu_emits_declared_fix_method(qapp):
    """单条右键出 check 声明的方法列表并按所选 method id 修复。"""
    from paleo_workbench.ui.workstation.topology_checker_panel import (
        TopologyCheckerPanel,
    )

    panel = TopologyCheckerPanel()
    fixes = []
    panel.fix_requested.connect(lambda eid, mid: fixes.append((eid, mid)))
    panel.set_errors([_OVERLAP_ERROR])
    menu = panel.menu_for(_OVERLAP_ERROR)
    labels = [action.text() for action in menu.actions()]
    assert labels, "右键应列出 check 声明的修复方法"
    assert any("Subtract" in text or "裁" in text or "重叠" in text
               for text in labels)
    menu.actions()[0].trigger()
    assert fixes == [("0", 0)]
    panel.close()


def test_load_from_project_copies_workarea_into_checker(qapp):
    """工区余量用工程工区边界（规格：工区边界图层，缺则兜底）。"""
    from paleo_workbench.project.domain import ensure_workarea
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    project = ProjectDocument.new("工区")
    workarea = ensure_workarea(project)
    workarea.boundary = [
        [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0],
    ]
    controller = CompositeEditController()
    controller.load_from_project(project)
    workspace = controller.topology.checker.workspace
    assert workspace and workspace.get("type") == "Polygon"
    ring = workspace["coordinates"][0]
    assert ring[0] == [0.0, 0.0]
    assert ring[-1] == [0.0, 0.0]
