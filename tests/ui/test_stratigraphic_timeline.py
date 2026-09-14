"""M1 多期次地层时间轴：期次目录 / 差分切换 / 洋葱皮（无桥 fallback 路径）。

对应 docs/development/paleo-ui-workbench/03-tdd-ui-test-plan.md 矩阵 M1 与
01-interaction-specs.md S1 验收标准。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from paleo_workbench.project.models import ProjectDocument

QApplication.instance() or QApplication([])

from paleo_workbench.workflow.stratigraphic_epochs import (  # noqa: E402
    BUILTIN_PERIOD_SCHEME,
    build_epoch_catalog,
)
from paleo_workbench.mapping_workspace.epoch_switching import (  # noqa: E402
    build_epoch_switch_plan,
    build_onion_layers,
    default_epoch_classifier,
    is_facies_layer,
)


# ---------------------------------------------------------------------------
# 纯域：期次目录（D1）
# ---------------------------------------------------------------------------

def _project_with_horizons(*names: str) -> ProjectDocument:
    project = ProjectDocument.new("时间轴测试")
    project.stratigraphy.sequence_boundaries = list(names)
    return project


def test_builtin_period_scheme_orders_oldest_first():
    ages = [epoch.age_ma for epoch in BUILTIN_PERIOD_SCHEME]
    assert all(a > b for a, b in zip(ages, ages[1:]))
    labels = [epoch.label for epoch in BUILTIN_PERIOD_SCHEME]
    assert "寒武系" in labels and "奥陶系" in labels and "石炭系" in labels


def test_epoch_catalog_merges_builtin_ages_and_project_order():
    project = _project_with_horizons("沙一期", "奥陶系底界", "寒武系底界")
    catalog = build_epoch_catalog(project)
    # 年代可识别者按底界年龄老→新排前；不可识别者保持声明序追加（D1）。
    assert [e.key for e in catalog] == ["寒武系底界", "奥陶系底界", "沙一期"]
    by_key = {e.key: e for e in catalog}
    assert by_key["寒武系底界"].age_ma is not None
    assert by_key["寒武系底界"].age_ma > by_key["奥陶系底界"].age_ma
    assert by_key["沙一期"].age_ma is None


def test_epoch_catalog_dedups_target_horizon():
    project = _project_with_horizons("寒武系底界")
    from paleo_workbench.workflow.stratigraphy import set_target_from_boundary

    set_target_from_boundary(project, "寒武系底界")
    catalog = build_epoch_catalog(project)
    assert [e.key for e in catalog] == ["寒武系底界"]


def test_epoch_catalog_empty_project_is_empty():
    catalog = build_epoch_catalog(ProjectDocument.new("空"))
    assert catalog == []


def test_epoch_catalog_includes_map_document_horizons():
    project = _project_with_horizons("寒武系底界")
    doc = SimpleNamespace(linked_target_horizon="石炭系底界")
    project.paleomap_documents.append(doc)
    catalog = build_epoch_catalog(project)
    assert [e.key for e in catalog] == ["寒武系底界", "石炭系底界"]


# ---------------------------------------------------------------------------
# 纯域：差分切换计划（D3）
# ---------------------------------------------------------------------------

def _layer(layer_id: str, epoch: str | None, visible=True, role="facies",
           opacity=1.0):
    return SimpleNamespace(
        id=layer_id,
        name=f"{layer_id}-相带" if role == "facies" else layer_id,
        visible=visible,
        opacity=opacity,
        metadata={} if epoch is None else {"epoch": epoch, "layer_role": role},
    )


def test_switch_plan_is_symmetric_diff_only():
    layers = [
        _layer("A1", "EA"),
        _layer("A2", "EA", visible=False),  # 已隐藏的同期层不应被触碰
        _layer("B1", "EB", visible=False),
        _layer("BASE", None),
    ]
    plan = build_epoch_switch_plan(layers, current="EA", target="EB")
    assert sorted(plan.show) == ["B1"]
    assert sorted(plan.hide) == ["A1"]
    assert plan.target == "EB"


def test_switch_plan_same_epoch_is_empty():
    layers = [_layer("A1", "EA"), _layer("B1", "EB", visible=False)]
    plan = build_epoch_switch_plan(layers, current="EA", target="EA")
    assert list(plan.show) == [] and list(plan.hide) == []


def test_switch_plan_ignores_unaffiliated_layers():
    layers = [_layer("WELLS", None), _layer("REF", None, role="reference")]
    plan = build_epoch_switch_plan(layers, current="EA", target="EB")
    assert list(plan.show) == [] and list(plan.hide) == []


def test_default_classifier_matches_name_and_metadata():
    classifier = default_epoch_classifier(
        [
            SimpleNamespace(key="寒武系底界", label="寒武系"),
            SimpleNamespace(key="沙一期", label="沙一"),
        ]
    )
    assert classifier(_layer("x", None)) is None  # 无标签 → 无归属
    named = SimpleNamespace(
        id="n", name="寒武系-沉积相", visible=True, opacity=1.0, metadata={}
    )
    assert classifier(named) == "寒武系底界"


def test_onion_layers_pick_prev_epoch_facies_only():
    epochs = [SimpleNamespace(key=k) for k in ("E1", "E2", "E3")]
    layers = [
        _layer("F2", "E2"),  # 前一期次相带层 → 洋葱
        _layer("W2", "E2", role="reference"),  # 前一期次非相带 → 排除
        _layer("F3", "E3"),  # 当前期次 → 排除
        _layer("F1", "E1"),  # 更早期次 → 排除（仅相邻前一期，D2）
    ]
    assert build_onion_layers(layers, epochs, current="E3") == ["F2"]


def test_is_facies_layer_honests_on_non_facies():
    assert is_facies_layer(_layer("F", "A"))
    assert not is_facies_layer(_layer("R", "A", role="reference"))


# ---------------------------------------------------------------------------
# 执行器：差分应用 / 回滚 / horizon 写穿（D3）
# ---------------------------------------------------------------------------

class FakeLayerManager:
    """LayerManagerPanel 鸭子面（set_layer_visible/opacity/move_layer + _layers）。"""

    def __init__(self, layers):
        self._layers = list(layers)
        self.visible_calls: list[tuple[str, bool]] = []
        self.opacity_calls: list[tuple[str, float]] = []
        self.move_calls: list[tuple[str, int]] = []

    def move_layer(self, layer_id, direction):
        """direction=+1 → index 变小（朝渲染底部）；-1 → 朝渲染顶部。"""
        self.move_calls.append((str(layer_id), int(direction)))
        for index, layer in enumerate(self._layers):
            if str(layer.id) == str(layer_id):
                target = index - int(direction)
                if 0 <= target < len(self._layers):
                    self._layers[index], self._layers[target] = (
                        self._layers[target], self._layers[index])
                return

    def layer_by_id(self, layer_id):
        return next((l for l in self._layers if l.id == layer_id), None)

    def set_layer_visible(self, layer_id, visible, *, reload_tree=True):
        self.visible_calls.append((layer_id, visible))
        layer = self.layer_by_id(layer_id)
        if layer is not None:
            layer.visible = visible

    def set_layer_opacity(self, layer_id, opacity):
        self.opacity_calls.append((layer_id, opacity))
        layer = self.layer_by_id(layer_id)
        if layer is not None:
            layer.opacity = opacity


def _controller(qtbot, layers, epochs, project=None):
    from paleo_workbench.ui.components.stratigraphic_timeline_slider import (
        EpochTimelineController,
    )

    manager = FakeLayerManager(layers)
    status: list[str] = []
    controller = EpochTimelineController(parent=None)
    controller.bind(layer_manager=manager, project=project, status_sink=status.append)
    controller.set_epochs(epochs)
    return controller, manager, status


def test_executor_applies_minimal_diff(qtbot):
    layers = [_layer("A1", "EA"), _layer("B1", "EB", visible=False), _layer("BASE", None)]
    epochs = [SimpleNamespace(key=k) for k in ("EA", "EB")]
    controller, manager, _ = _controller(qtbot, layers, epochs)
    controller.request_commit("EB")
    assert manager.visible_calls == [("A1", False), ("B1", True)]
    assert manager.opacity_calls == []


def test_executor_writes_horizon_metadata(qtbot):
    project = _project_with_horizons("寒武系底界", "奥陶系底界")
    epochs = [SimpleNamespace(key=k) for k in ("寒武系底界", "奥陶系底界")]
    controller, _, _ = _controller(
        qtbot, [_layer("A1", "寒武系底界")], epochs, project=project)
    controller.request_commit("奥陶系底界")
    assert project.stratigraphy.target_horizon == "奥陶系底界"


def test_executor_no_layers_status_is_honest(qtbot):
    epochs = [SimpleNamespace(key=k) for k in ("EA", "EB")]
    controller, manager, status = _controller(qtbot, [_layer("BASE", None)], epochs)
    controller.request_commit("EB")
    assert manager.visible_calls == []
    assert status and any("暂无图层" in s for s in status)


def test_executor_rolls_back_on_failure(qtbot):
    layers = [_layer("A1", "EA"), _layer("B1", "EB", visible=False)]
    epochs = [SimpleNamespace(key=k) for k in ("EA", "EB")]
    controller, manager, _ = _controller(qtbot, layers, epochs)

    original = manager.set_layer_visible

    def _boom(layer_id, visible, *, reload_tree=True):
        if layer_id == "B1":
            raise RuntimeError("bridge exploded")
        original(layer_id, visible, reload_tree=reload_tree)

    manager.set_layer_visible = _boom
    with pytest.raises(RuntimeError):
        controller.request_commit("EB")
    # 回滚：可见性恢复切换前快照（A1 可见、B1 隐藏）。
    assert layers[0].visible is True
    assert layers[1].visible is False


def test_onion_controller_sets_30pct_and_restores(qtbot):
    layers = [
        _layer("F2", "E2", visible=False, opacity=1.0),
        _layer("F3", "E3"),
    ]
    epochs = [SimpleNamespace(key=k) for k in ("E1", "E2", "E3")]
    controller, manager, _ = _controller(qtbot, layers, epochs)
    controller.request_commit("E3")
    controller.set_onion(True)
    assert ("F2", 0.30) in manager.opacity_calls
    assert ("F2", True) in manager.visible_calls
    assert all(op != 0.30 for lid, op in manager.opacity_calls if lid == "F3")
    manager.opacity_calls.clear()
    manager.visible_calls.clear()
    controller.set_onion(False)
    assert ("F2", 1.0) in manager.opacity_calls
    assert ("F2", False) in manager.visible_calls


def test_onion_raises_prev_epoch_layer_to_render_top(qtbot):
    """B2（review）：洋葱层须置于渲染栈顶（列表末位=最后绘制=在上）。"""
    layers = [
        _layer("BASE", None),
        _layer("F2", "E2", visible=False),
        _layer("F3", "E3"),
    ]
    epochs = [SimpleNamespace(key=k) for k in ("E1", "E2", "E3")]
    controller, manager, _ = _controller(qtbot, layers, epochs)
    controller.request_commit("E3")
    order_before = [l.id for l in manager._layers]
    controller.set_onion(True)
    order_onion = [l.id for l in manager._layers]
    assert order_onion[-1] == "F2"  # 洋葱层在渲染顶
    assert set(order_onion) == set(order_before)
    controller.set_onion(False)
    assert [l.id for l in manager._layers] == order_before  # 层序复原


def test_onion_first_epoch_is_inert(qtbot):
    layers = [_layer("F1", "E1")]
    epochs = [SimpleNamespace(key=k) for k in ("E1", "E2")]
    controller, manager, status = _controller(qtbot, layers, epochs)
    controller.set_onion(True)
    assert manager.opacity_calls == [] and manager.visible_calls == []
    assert any("无相邻前一期次" in s for s in status)


# ---------------------------------------------------------------------------
# 部件：拖拽去抖 / 键盘步进 / 洋葱皮开关（D4/D2）
# ---------------------------------------------------------------------------

def _widget(qtbot, n=3):
    from paleo_workbench.ui.components.stratigraphic_timeline_slider import (
        StratigraphicTimelineWidget,
    )

    widget = StratigraphicTimelineWidget()
    qtbot.addWidget(widget)
    widget.set_epochs([SimpleNamespace(key=f"E{i}", label=f"期次{i}",
                                       age_ma=500 - i) for i in range(n)])
    widget.resize(640, 48)
    widget.show()
    qtbot.wait(20)
    return widget


def _track_x(widget, index: int) -> QPoint:
    track = widget._track
    return QPoint(int(track.width() * (index + 0.5) / len(widget.epochs())), 8)


def test_drag_scrub_no_commit_until_release(qtbot):
    widget = _widget(qtbot)
    scrubbed: list[str] = []
    committed: list[str] = []
    widget.epoch_scrubbed.connect(scrubbed.append)
    widget.epoch_committed.connect(committed.append)

    qtbot.mousePress(widget._track, Qt.MouseButton.LeftButton, pos=_track_x(widget, 0))
    qtbot.mouseMove(widget._track, pos=_track_x(widget, 1))
    qtbot.mouseMove(widget._track, pos=_track_x(widget, 2))
    assert len(scrubbed) >= 2
    assert committed == []
    qtbot.mouseRelease(widget._track, Qt.MouseButton.LeftButton, pos=_track_x(widget, 2))
    qtbot.wait(250)
    assert committed == ["E2"]


def test_rapid_key_steps_single_commit(qtbot):
    widget = _widget(qtbot)
    committed: list[str] = []
    widget.epoch_committed.connect(committed.append)
    widget.setFocus()
    for _ in range(3):
        qtbot.keyClick(widget, Qt.Key_Right)
    qtbot.wait(250)
    assert committed == ["E2"]


def test_key_steps_clamp_at_ends(qtbot):
    widget = _widget(qtbot)
    committed: list[str] = []
    widget.epoch_committed.connect(committed.append)
    widget.setFocus()
    for _ in range(9):
        qtbot.keyClick(widget, Qt.Key_Right)
    for _ in range(9):
        qtbot.keyClick(widget, Qt.Key_Left)
    qtbot.wait(250)
    assert committed == ["E0"]
    assert widget.current_epoch() == "E0"


def test_onion_button_toggles_signal(qtbot):
    widget = _widget(qtbot)
    states: list[bool] = []
    widget.onion_toggled.connect(states.append)
    qtbot.mouseClick(widget.onion_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(widget.onion_button, Qt.MouseButton.LeftButton)
    assert states == [True, False]


def test_empty_epochs_shows_placeholder(qtbot):
    from paleo_workbench.ui.components.stratigraphic_timeline_slider import (
        StratigraphicTimelineWidget,
    )

    widget = StratigraphicTimelineWidget()
    qtbot.addWidget(widget)
    widget.set_epochs([])
    widget.show()
    qtbot.wait(20)
    assert widget._placeholder.isVisible()
    assert widget._track.isHidden()


# ---------------------------------------------------------------------------
# 集成：CompositeDocument 挂载 + 增量发布（无重建）
# ---------------------------------------------------------------------------

def _composite(qtbot, monkeypatch, project):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    doc.resize(1200, 800)
    doc.show()
    qtbot.wait(30)
    return doc


def test_timeline_mounted_in_composite_document(qtbot, monkeypatch):
    project = _project_with_horizons("寒武系底界", "奥陶系底界")
    doc = _composite(qtbot, monkeypatch, project)
    assert doc.timeline.objectName() == "StratigraphicTimeline"
    assert [e.key for e in doc.timeline.epochs()] == [
        "寒武系底界", "奥陶系底界"]


def test_composite_commit_switches_layers_incrementally(qtbot, monkeypatch):
    project = _project_with_horizons("寒武系底界", "奥陶系底界")
    doc = _composite(qtbot, monkeypatch, project)
    # 注入两个期次图层到图层管理器（模拟既有工程载入期次层）。
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    layers = list(doc.layer_manager._layers)

    def _ensure(epoch_key, visible):
        layers.append(MapLayerSnapshot(
            id=f"epoch-{epoch_key}", name=f"{epoch_key}-沉积相", layer_type="polygon",
            extent=(0, 0, 1, 1), crs="EPSG:4326", data_revision=1,
            style_revision=1, visible=visible, opacity=1.0,
            metadata={"epoch": epoch_key, "layer_role": "facies"},
        ))

    _ensure("寒武系底界", True)
    _ensure("奥陶系底界", False)
    doc.layer_manager.bind(doc.canvas, layers)

    publish_calls: list[object] = []
    original = doc.canvas.set_layer_snapshot

    def _spy(snapshot, *a, **k):
        publish_calls.append(snapshot)
        return original(snapshot, *a, **k)

    monkeypatch.setattr(doc.canvas, "set_layer_snapshot", _spy)
    doc.epoch_timeline.request_commit("奥陶系底界")
    assert project.stratigraphy.target_horizon == "奥陶系底界"
    assert doc.timeline.current_epoch() == "奥陶系底界"
    visible = {l.id: l.visible for l in doc.layer_manager._layers}
    assert visible["epoch-奥陶系底界"] is True
    assert visible["epoch-寒武系底界"] is False
    # 增量断言：发布次数 == 差分大小（2 次可见性变更），无全量重建路径。
    assert len(publish_calls) == 2
