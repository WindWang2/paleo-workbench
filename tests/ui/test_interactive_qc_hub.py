"""M4 交互式质检修复向导（QuickFix / 平滑定位 / 撤销粒度）。

对应 docs/development/paleo-ui-workbench/03-tdd-ui-test-plan.md 矩阵 M4 与
01-interaction-specs.md S4 验收标准（00-decisions D8/D9）。
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shapely")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.vector_layer import VectorFeature  # noqa: E402


def _controller():
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    return CompositeEditController()


def _poly(coords, fid, **attrs):
    return VectorFeature(
        feature_id=fid,
        geometry={"type": "Polygon", "coordinates": [coords]},
        attributes=dict(attrs),
    )


def _line(coords, fid, **attrs):
    return VectorFeature(
        feature_id=fid,
        geometry={"type": "LineString", "coordinates": coords},
        attributes=dict(attrs),
    )


def _layer_with(*features, name="相带"):
    controller = _controller()
    layer = controller.create_layer(name, "polygon", template="facies")
    controller.import_layer_features(layer.id, list(features))
    session, reason = controller.ensure_layer_session(layer.id)
    assert session is not None, reason
    from paleo_workbench.mapping.qc_quickfix import QuickFixContext

    ctx = QuickFixContext(layer=layer, session=session, tolerance=1.0)
    return controller, layer, session, ctx


# ---------------------------------------------------------------------------
# 纯域：碎多边形吸附合并（D8：共享边最长的相邻优势相；并列取面积大者）
# ---------------------------------------------------------------------------

SLIVER = [
    (0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0),
]
BIG_EAST = [
    (2.0, -3.0), (6.0, -3.0), (6.0, 3.0), (2.0, 3.0), (2.0, -3.0),
]
SMALL_WEST = [
    (-4.0, -1.0), (0.0, -1.0), (0.0, 2.0), (-4.0, 2.0), (-4.0, -1.0),
]


def test_sliver_merge_into_dominant_neighbor():
    from paleo_workbench.mapping.qc_quickfix import QUICK_FIX_ACTIONS

    controller, layer, session, ctx = _layer_with(
        _poly(SLIVER, "F07", facies="孤岛"),
        _poly(BIG_EAST, "F03", facies="三角洲"),
        _poly(SMALL_WEST, "F09", facies="潮坪"),
    )
    issue = {"rule": "sliver_polygon", "layer_id": layer.id,
             "feature_id": "F07", "message": "孤岛相带"}
    action = next(a for a in QUICK_FIX_ACTIONS if a.action_id == "sliver_merge")
    ok, reason = action.availability(issue, ctx)
    assert ok, reason
    assert action.apply(issue, ctx) is True

    ids = {f.feature_id for f in session.features()}
    assert "F07" not in ids  # 碎屑要素被并入
    merged = session.feature("F03")
    area = _area(merged.geometry)
    assert area == pytest.approx(_area_poly(SLIVER) + _area_poly(BIG_EAST),
                                 rel=1e-6)
    assert merged.attributes["facies"] == "三角洲"  # 属性取优势相

    # 单一撤销命令整体复原
    depth = len(session.undo_stack)
    session.undo()
    assert len(session.undo_stack) == depth - 1
    restored = {f.feature_id for f in session.features()}
    assert restored == {"F07", "F03", "F09"}
    assert _area(session.feature("F03").geometry) == pytest.approx(
        _area_poly(BIG_EAST), rel=1e-6)


def test_sliver_merge_tie_break_by_area():
    """共享边并列时并入面积更大的相邻相。"""
    from paleo_workbench.mapping.qc_quickfix import apply_sliver_merge

    # 上下两个等共享边邻居，南邻居面积更大 → 并入南侧
    sliver = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    north = [(0.0, 1.0), (2.0, 1.0), (2.0, 1.5), (0.0, 1.5), (0.0, 1.0)]
    south = [(0.0, -9.0), (2.0, -9.0), (2.0, 0.0), (0.0, 0.0), (0.0, -9.0)]
    controller, layer, session, ctx = _layer_with(
        _poly(sliver, "S", facies="孤岛"),
        _poly(north, "N", facies="北"),
        _poly(south, "B", facies="南"),
    )
    issue = {"rule": "sliver_polygon", "layer_id": layer.id,
             "feature_id": "S"}
    assert apply_sliver_merge(issue, ctx) is True
    ids = {f.feature_id for f in session.features()}
    assert "S" not in ids and "N" in ids and "B" in ids
    # 并入南侧（面积大）：南要素面积增大
    assert _area(session.feature("B").geometry) > _area_poly(south)
    assert _area(session.feature("N").geometry) == pytest.approx(
        _area_poly(north), rel=1e-6)


def test_sliver_merge_no_neighbor_unavailable():
    from paleo_workbench.mapping.qc_quickfix import QUICK_FIX_ACTIONS

    isolated = [(100.0, 100.0), (102.0, 100.0), (102.0, 101.0),
                (100.0, 101.0), (100.0, 100.0)]
    controller, layer, session, ctx = _layer_with(
        _poly(isolated, "LONE"), _poly(BIG_EAST, "F03"))
    issue = {"rule": "sliver_polygon", "layer_id": layer.id,
             "feature_id": "LONE"}
    action = next(a for a in QUICK_FIX_ACTIONS if a.action_id == "sliver_merge")
    ok, reason = action.availability(issue, ctx)
    assert not ok and reason


def _area(geometry):
    from shapely.geometry import shape

    return float(shape(dict(geometry)).area)


def _area_poly(coords):
    from shapely.geometry import Polygon

    return float(Polygon(coords).area)


# ---------------------------------------------------------------------------
# 纯域：未封闭边界沿切线延伸闭合（D8）
# ---------------------------------------------------------------------------

def test_tangent_close_within_tolerance():
    from paleo_workbench.mapping.qc_quickfix import QUICK_FIX_ACTIONS

    # 内收开口线：两端切线相向（容差 1.0、端距 2.0）→ 沿切线延伸数步闭合
    line = [(1.0, 0.0), (0.0, 3.0), (0.0, 10.0), (4.0, 10.0), (4.0, 3.0),
            (3.0, 0.0)]
    controller, layer, session, ctx = _layer_with(_line(line, "L2"))
    issue = {"rule": "unclosed_boundary", "layer_id": layer.id,
             "feature_id": "L2"}
    action = next(a for a in QUICK_FIX_ACTIONS
                  if a.action_id == "tangent_close")
    ok, reason = action.availability(issue, ctx)
    assert ok, reason
    assert action.apply(issue, ctx) is True
    coords = session.feature("L2").geometry["coordinates"]
    assert coords[0] == coords[-1]  # 闭合环
    depth = len(session.undo_stack)
    session.undo()
    assert len(session.undo_stack) == depth - 1
    coords = session.feature("L2").geometry["coordinates"]
    assert coords[0] != coords[-1]  # 撤销复原开口


def test_tangent_close_unreachable_disables():
    from paleo_workbench.mapping.qc_quickfix import QUICK_FIX_ACTIONS

    line = [(0.0, 0.0), (0.0, 10.0)]  # 端点相距 10，容差 1 → 最大延伸 8 不够
    controller, layer, session, ctx = _layer_with(_line(line, "L9"))
    issue = {"rule": "unclosed_boundary", "layer_id": layer.id,
             "feature_id": "L9"}
    action = next(a for a in QUICK_FIX_ACTIONS
                  if a.action_id == "tangent_close")
    ok, reason = action.availability(issue, ctx)
    assert not ok
    assert "距离" in reason or "容差" in reason


# ---------------------------------------------------------------------------
# 平滑平移（D9：180ms ease-in-out，4-12 帧，中心单调，历史恰 1 条）
# ---------------------------------------------------------------------------

class FakeCanvas:
    def __init__(self, extent=(0.0, 0.0, 100.0, 100.0)):
        self._extent = tuple(extent)
        self.calls: list[tuple[tuple, dict]] = []

    def view_extent(self):
        return self._extent

    def set_extent(self, extent, *args, **kwargs):
        self.calls.append((tuple(extent), kwargs))
        self._extent = tuple(extent)


def _center(extent):
    return ((extent[0] + extent[2]) / 2.0, (extent[1] + extent[3]) / 2.0)


def test_smooth_pan_frames_and_history(qtbot):
    from paleo_workbench.ui.components.interactive_qc_hub import SmoothPanController

    canvas = FakeCanvas()
    pan = SmoothPanController(parent=None)
    pan.pan_to_extent(canvas, (200.0, 200.0, 220.0, 220.0), pad=0.10)
    qtbot.wait(400)
    assert len(canvas.calls) >= 4 and len(canvas.calls) <= 12
    final_extent, final_kwargs = canvas.calls[-1]
    assert final_extent == (199.0, 199.0, 221.0, 221.0)  # bbox + 10% pad
    history = [kwargs for _, kwargs in canvas.calls
               if kwargs.get("record_history")]
    assert len(history) == 1  # 末帧单独记录一次
    centers = [_center(extent) for extent, _ in canvas.calls]
    dx = [b[0] - a[0] for a, b in zip(centers, centers[1:])]
    assert all(d >= -1e-9 for d in dx)  # 中心 x 单调向目标


def test_smooth_pan_cancelled_by_user(qtbot):
    from paleo_workbench.ui.components.interactive_qc_hub import SmoothPanController

    canvas = FakeCanvas()
    pan = SmoothPanController(parent=None)
    pan.pan_to_extent(canvas, (800.0, 800.0, 820.0, 820.0))
    qtbot.wait(40)
    pan.cancel()  # 用户输入打断
    count = len(canvas.calls)
    qtbot.wait(400)
    assert len(canvas.calls) == count  # 取消后零新帧


# ---------------------------------------------------------------------------
# 向导面板：聚合 / 详情 / 快速修复按钮 / 键盘流
# ---------------------------------------------------------------------------

def _hub(qtbot, ctx=None):
    from paleo_workbench.ui.components.interactive_qc_hub import InteractiveQCHub

    hub = InteractiveQCHub()
    qtbot.addWidget(hub)
    hub.resize(720, 360)
    hub.show()
    qtbot.wait(20)
    if ctx is not None:
        hub.set_fix_context(lambda issue: ctx)
    return hub


def _issue(fid="F07", rule="sliver_polygon", severity="error"):
    return {
        "rule": rule, "severity": severity,
        "message": f"孤岛相带 {fid}", "feature_id": fid,
        "feature_kind": "layer", "bbox": [200.0, 200.0, 220.0, 220.0],
        "layer_id": "L1",
    }


def test_hub_merges_sources_and_counts(qtbot):
    hub = _hub(qtbot)
    hub.set_issues("carto", [_issue("F1"), _issue("F2", severity="warning")])
    hub.set_issues("topology", [_issue("F3", rule="dangle")])
    assert hub.issue_count() == 3
    assert "2 错误" in hub.counts_label.text()
    assert "1 警告" in hub.counts_label.text()


def test_hub_double_click_focuses_issue(qtbot):
    hub = _hub(qtbot)
    focused: list[dict] = []
    hub.issue_focused.connect(focused.append)
    hub.set_issues("carto", [_issue("F9")])
    hub.issue_list.item(0).setSelected(True)
    rect = hub.issue_list.visualItemRect(hub.issue_list.item(0))
    qtbot.mouseClick(hub.issue_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=rect.center())
    qtbot.mouseDClick(hub.issue_list.viewport(), Qt.MouseButton.LeftButton,
                      pos=rect.center())
    assert focused and focused[0]["feature_id"] == "F9"


def test_hub_quickfix_button_availability_and_request(qtbot):
    controller, layer, session, ctx = _layer_with(
        _poly(SLIVER, "F07"), _poly(BIG_EAST, "F03"))
    hub = _hub(qtbot)
    hub.set_issues("carto", [_issue("F07")])
    hub.issue_list.item(0).setSelected(True)
    hub._show_detail(hub.issue_list.item(0))
    button = hub.fix_button("sliver_merge")
    assert button is None or not button.isEnabled()  # 无上下文 → 不可用

    hub.set_fix_context(lambda issue: ctx)
    hub._show_detail(hub.issue_list.item(0))
    button = hub.fix_button("sliver_merge")
    assert button is not None and button.isEnabled()

    requested: list[tuple[dict, str]] = []
    hub.fix_requested.connect(
        lambda issue, action_id: requested.append((issue, action_id)))
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert requested and requested[0][1] == "sliver_merge"


def test_hub_keyboard_enter_focus_f_fix(qtbot):
    controller, layer, session, ctx = _layer_with(
        _poly(SLIVER, "F07"), _poly(BIG_EAST, "F03"))
    hub = _hub(qtbot, ctx=ctx)
    focused: list[dict] = []
    fixed: list[tuple[dict, str]] = []
    hub.issue_focused.connect(focused.append)
    hub.fix_requested.connect(
        lambda issue, action_id: fixed.append((issue, action_id)))
    hub.set_issues("carto", [_issue("F07")])
    hub.issue_list.setCurrentItem(hub.issue_list.item(0))
    hub.issue_list.setFocus()
    qtbot.keyClick(hub.issue_list, Qt.Key_Return)
    assert focused and focused[0]["feature_id"] == "F07"
    qtbot.keyClick(hub.issue_list, Qt.Key_F)
    assert fixed and fixed[0][1] == "sliver_merge"


def test_hub_mark_resolved_removes_issue(qtbot):
    hub = _hub(qtbot)
    hub.set_issues("carto", [_issue("F07")])
    hub.mark_resolved(_issue("F07"))
    assert hub.issue_count() == 0


# ---------------------------------------------------------------------------
# 集成：CompositeDocument 全链路（定位 → 修复 → 撤销 → 复现）
# ---------------------------------------------------------------------------

def _composite(qtbot, monkeypatch):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("QC 测试"))
    qtbot.addWidget(doc)
    doc.resize(1200, 800)
    doc.show()
    qtbot.wait(30)
    return doc


def test_composite_focus_smooth_pans(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    extents: list[tuple] = []
    original = doc.canvas.set_extent

    def _spy(extent, *a, **k):
        extents.append(tuple(extent))
        return original(extent, *a, **k)

    monkeypatch.setattr(doc.canvas, "set_extent", _spy)
    doc.qc_hub.set_issues("carto", [_issue("F07")])
    doc.qc_hub.issue_focused.emit(_issue("F07"))
    qtbot.wait(400)
    assert extents, "smooth pan produced no extent writes"
    assert extents[-1] == (199.0, 199.0, 221.0, 221.0)


def test_composite_fix_end_to_end_and_undo(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.import_layer_features(layer.id, [
        _poly(SLIVER, "F07", facies="孤岛"),
        _poly(BIG_EAST, "F03", facies="三角洲"),
    ])
    session, reason = controller.ensure_layer_session(layer.id)
    assert session is not None, reason

    issue = {"rule": "sliver_polygon", "layer_id": layer.id,
             "feature_id": "F07", "message": "孤岛相带 F07",
             "bbox": [0.0, 0.0, 6.0, 3.0]}
    doc.qc_hub.set_issues("topology", [issue])
    assert doc.qc_hub.issue_count() == 1
    doc._apply_quick_fix(issue, "sliver_merge")
    assert doc.qc_hub.issue_count() == 0  # 修复后列表移除
    ids = {f.feature_id for f in session.features()}
    assert "F07" not in ids

    session.undo()  # 一次撤销完整复原
    ids = {f.feature_id for f in session.features()}
    assert "F07" in ids
    doc.qc_hub.set_issues("topology", [issue])  # 重新检查 → 问题复现
    assert doc.qc_hub.issue_count() == 1


def test_cartographic_issues_adapted_for_hub():
    from paleo_workbench.mapping.cartographic_qa import issues_for_interactive_hub
    from paleo_workbench.project.models import ProjectDocument

    issues = issues_for_interactive_hub(ProjectDocument.new("QA 适配"))
    assert isinstance(issues, list)
    for issue in issues:
        assert "rule" in issue and "severity" in issue
        assert "layer_id" in issue  # 向导修复上下文解析依赖
