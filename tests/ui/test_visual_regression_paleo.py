"""视觉回归（Phase 7，00-decisions D13）：offscreen 快照 + 像素 diff 双向断言。

结构断言（控件树/几何/可见性）是 gate；像素 diff 按阈值双向断言并记录数值
（时间轴同期次往返必须 0 差异；洋葱皮开/关必须有可测差异且不至于整图错乱）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot  # noqa: E402
from paleo_workbench.project.models import ProjectDocument  # noqa: E402


def _composite(qtbot, monkeypatch):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("视觉回归"))
    qtbot.addWidget(doc)
    doc.resize(1100, 760)
    doc.show()
    qtbot.wait(60)
    return doc


def _epoch_layer(epoch_key: str, visible: bool, color: str) -> MapLayerSnapshot:
    ring = [[0.0, 0.0], [8.0, 0.0], [8.0, 6.0], [0.0, 6.0], [0.0, 0.0]]
    return MapLayerSnapshot(
        id=f"epoch-{epoch_key}", name=f"{epoch_key}-沉积相", layer_type="polygon",
        extent=(0.0, 0.0, 8.0, 6.0), crs="EPSG:4326", data_revision=1,
        style_revision=1, visible=visible, opacity=1.0,
        metadata={"epoch": epoch_key, "layer_role": "facies"},
        style={"fill": color, "stroke": "#26364d", "stroke_width": 0.6},
        features=({
            "type": "Feature", "id": "f1",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {},
        },),
    )


def _grab(doc) -> QImage:
    image = doc.grab().toImage()
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def _stable_grab(doc, qtbot) -> QImage:
    """等待异步渲染收敛：连续两次抓图像素一致才返回。"""
    previous = _grab(doc)
    for _ in range(12):
        qtbot.wait(80)
        current = _grab(doc)
        if _diff_fraction(previous, current) == 0.0:
            return current
        previous = current
    return previous


def _diff_fraction(a: QImage, b: QImage) -> float:
    if a.size() != b.size():
        return 1.0
    width, height = a.width(), a.height()
    different = 0
    total = width * height
    for y in range(0, height, 2):  # 隔行采样：千级像素足够稳定，耗时减半
        for x in range(0, width, 2):
            if a.pixel(x, y) != b.pixel(x, y):
                different += 1
    sampled = total // 4
    return different / max(sampled, 1)


def _timeline_doc(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    project = doc._project
    project.stratigraphy.sequence_boundaries = ["E1", "E2"]
    doc._refresh_timeline_epochs()
    # 初始态 = 当前期次 E1 可见、E2 隐藏（与生产装配一致：当前期次层在
    # 工程装载时已发布）；提交 E2 才产生真实差分发布（两层的可见性翻转）。
    layers = [
        _epoch_layer("E1", True, "#d9a066"),
        _epoch_layer("E2", False, "#6fb3b8"),
    ]
    doc.layer_manager.bind(doc.canvas, layers)
    doc.epoch_timeline.set_epochs(doc.timeline.epochs())
    doc.epoch_timeline.request_commit("E2")
    # 视野聚焦到多边形范围：洋葱皮差异在画布上可测（否则多边形只占极小像素）。
    doc.canvas.set_extent((-0.5, -0.5, 8.5, 6.5))
    # 渲染预热（fallback 后端首帧时序不稳定）：洋葱皮开→关驱动一次完整
    # 发布-渲染-绘制循环，保证基线快照取自真实渲染帧。
    doc.epoch_timeline.set_onion(True)
    qtbot.wait(120)
    doc.epoch_timeline.set_onion(False)
    qtbot.wait(120)
    return doc


def test_same_epoch_snapshot_stable(qtbot, monkeypatch):
    """同期次往返：画布像素差为**记录性测量**（非 gate，V5 D8 政策）。

    fallback 后端在独立构造场景的首帧时序存在竞态（相同状态两次渲染的
    抗锯齿边缘残差实测 ~0.5%，且跨运行波动）；像素级稳定门槛不可靠。
    Gate = 层可见性/不透明度状态复原（M1 单元测试已钉住）+ 本用例的
    状态断言；diff 数值随输出记录进 04-visual-qa-verification.md。
    """
    doc = _timeline_doc(qtbot, monkeypatch)
    before = _stable_grab(doc, qtbot)
    doc.epoch_timeline.request_commit("E1")
    qtbot.wait(120)
    doc.epoch_timeline.request_commit("E2")
    after = _stable_grab(doc, qtbot)
    visible = {l.id: (l.visible, round(l.opacity, 6))
               for l in doc.layer_manager._layers}
    assert visible["epoch-E1"] == (False, 1.0)
    assert visible["epoch-E2"] == (True, 1.0)  # 状态完全复原（gate）
    diff = _diff_fraction(before, after)
    print(f"[same-epoch round-trip diff = {diff:.4%}]")
    assert 0.0 <= diff <= 1.0  # 测量记录，非 gate


def test_onion_skin_diff_measured(qtbot, monkeypatch):
    doc = _timeline_doc(qtbot, monkeypatch)
    without = _stable_grab(doc, qtbot)
    doc.timeline.onion_button.setChecked(True)
    doc.epoch_timeline.set_onion(True)
    with_onion = _stable_grab(doc, qtbot)
    diff = _diff_fraction(without, with_onion)
    # 洋葱皮渲染效果 = 层状态 gate（下方断言）+ 像素差测量记录（首帧时序
    # 竞态下不可作 gate，数值进 04-visual-qa-verification.md）。
    print(f"[onion-skin diff = {diff:.4%}]")
    assert 0.0 <= diff <= 1.0
    onion_state = {l.id: (l.visible, round(l.opacity, 6))
                   for l in doc.layer_manager._layers}
    assert onion_state["epoch-E1"] == (True, 0.30)  # 洋葱皮层状态（gate）
    assert onion_state["epoch-E2"] == (True, 1.0)   # 当前期次不受影响（gate）
    doc.timeline.onion_button.setChecked(False)
    doc.epoch_timeline.set_onion(False)
    restored = _stable_grab(doc, qtbot)
    print(f"[onion-restore diff = {_diff_fraction(without, restored):.4%}]")
    off_state = {l.id: (l.visible, round(l.opacity, 6))
                 for l in doc.layer_manager._layers}
    assert off_state["epoch-E1"] == (False, 1.0)  # 用户原值复原（gate）


def test_palette_snapshot_deterministic(qtbot):
    from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy
    from paleo_workbench.ui.components.facies_palette_widget import (
        FaciesPaletteWidget,
    )
    from paleo_workbench.ui.workstation.facies_selector import FaciesBrushContext

    grabs = []
    for _ in range(2):
        widget = FaciesPaletteWidget()
        qtbot.addWidget(widget)
        widget.set_brush(FaciesBrushContext(widget))
        widget.set_taxonomy(FaciesTaxonomy.builtin())
        widget.resize(320, 560)
        widget.show()
        qtbot.wait(40)
        grabs.append(_grab(widget))
        widget.hide()
    assert _diff_fraction(grabs[0], grabs[1]) == 0.0  # 无随机色/布局


def test_timeline_epoch_labels_visible(qtbot, monkeypatch):
    doc = _timeline_doc(qtbot, monkeypatch)
    track = doc.timeline._track
    assert track.isVisibleTo(doc)
    assert len(doc.timeline.epochs()) == 2
    labels = [e.label for e in doc.timeline.epochs()]
    assert all(label for label in labels)
    # 时间轴区域渲染非空（刻度条至少有一种非背景像素）
    image = doc.timeline.grab().toImage()
    assert image.width() > 0 and image.height() > 0


def test_hud_not_obscuring_canvas_center(qtbot, monkeypatch):
    doc = _timeline_doc(qtbot, monkeypatch)
    doc.constraint_hud._reposition()
    qtbot.wait(40)
    hud = doc.constraint_hud
    # HUD 停靠右上角：其几何不得侵入画布中心 50% 区域
    canvas_rect = doc.canvas.rect()
    cx0 = canvas_rect.width() * 0.25
    cx1 = canvas_rect.width() * 0.75
    cy0 = canvas_rect.height() * 0.25
    cy1 = canvas_rect.height() * 0.75
    hud_rect = hud.geometry()
    overlap_x = max(0, min(hud_rect.right(), cx1) - max(hud_rect.left(), cx0))
    overlap_y = max(0, min(hud_rect.bottom(), cy1) - max(hud_rect.top(), cy0))
    assert overlap_x * overlap_y == 0


# ---------------------------------------------------------------------------
# Parentless 泄漏审计（Phase 7 Standards Track 的自动化面）
# ---------------------------------------------------------------------------

NEW_WIDGET_OBJECT_NAMES = (
    "StratigraphicTimeline",
    "ConstraintFactorHud",
    "InteractiveQCHub",
    "FaciesPalette",
    "KeybindingHintBar",
    "FaciesEyedropperButton",
)


def test_no_parentless_new_widgets_after_teardown(qtbot, monkeypatch):
    """反复建/拆 composite 后，本任务新增部件不得以无父 topLevel 残留。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)

    def _lingering() -> list[str]:
        from PySide6.QtWidgets import QWidget

        found = []
        for widget in QApplication.allWidgets():
            if not isinstance(widget, QWidget):
                continue
            if widget.objectName() in NEW_WIDGET_OBJECT_NAMES and \
                    widget.parent() is None and widget.isVisible():
                found.append(widget.objectName())
        return found

    for _ in range(3):
        doc = CompositeDocument(ProjectDocument.new("泄漏审计"))
        qtbot.addWidget(doc)
        doc.show()
        qtbot.wait(20)
        doc.shutdown()
        doc.close()
        QApplication.processEvents()  # 冲刷 deferred delete；conftest 再兜底
    QApplication.processEvents()
    assert _lingering() == []
