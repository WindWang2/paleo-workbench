"""首页工区地图井位点击 → well_activated 跳转信号。

Covers the canvas map_clicked emission (click vs drag) and HomePage's
pixel-space hit test against the well layers.
"""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from paleo_workbench.project.domain import CoordinateStatus, WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.home_page import HomePage
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


def _click(widget, pos: QPointF, button=Qt.MouseButton.LeftButton):
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos, button, button, Qt.KeyboardModifier.NoModifier
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos, button, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)
    widget.mouseReleaseEvent(release)


def _click_map(canvas, pos: QPointF, button=Qt.MouseButton.LeftButton):
    """Click the native QgsMapCanvas when present; else the widget itself."""
    native = getattr(canvas, "canvas", None)
    if native is None or native is canvas:
        _click(canvas, pos, button=button)
        return
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos, button, button, Qt.KeyboardModifier.NoModifier
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos, button, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(native, press)
    QApplication.sendEvent(native, release)


def test_canvas_emits_map_clicked_on_bare_left_click(qtbot):
    canvas = UnifiedMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.show()
    canvas.set_extent((0.0, 0.0, 100.0, 100.0))
    seen = []
    canvas.map_clicked.connect(seen.append)

    _click(canvas, QPointF(200, 150))

    assert len(seen) == 1
    x, y = seen[0]
    assert abs(x - 50.0) < 1.0
    assert abs(y - 50.0) < 1.0


def test_canvas_drag_does_not_emit_map_clicked(qtbot):
    canvas = UnifiedMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.show()
    canvas.set_extent((0.0, 0.0, 100.0, 100.0))
    seen = []
    canvas.map_clicked.connect(seen.append)

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(100, 100),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(180, 160),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press)
    canvas.mouseReleaseEvent(release)

    assert seen == []


def _project_with_wells() -> ProjectDocument:
    doc = ProjectDocument.new("P")
    doc.wells.append(
        WellEntity(name="A1", project_x=25.0, project_y=50.0,
                   coordinate_status=CoordinateStatus.OK)
    )
    doc.wells.append(
        WellEntity(name="A2", project_x=75.0, project_y=50.0,
                   coordinate_status=CoordinateStatus.OK)
    )
    return doc


def test_home_map_well_click_emits_well_activated(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.update_state({}, [], _project_with_wells())
    page.show()

    canvas = page.map_canvas
    canvas.resize(800, 380)
    canvas.set_extent((0.0, 0.0, 100.0, 100.0))

    activated = []
    page.well_activated.connect(activated.append)

    # 画布按纵横比适配 extent — 用它自己的变换取 A1 的屏幕坐标。
    target = canvas.map_to_screen((25.0, 50.0))
    _click_map(canvas, target)

    assert len(activated) == 1
    well_id = activated[0]
    names = {w.id: w.name for w in page._project.wells}
    assert names[well_id] == "A1"


def test_home_map_click_far_from_wells_emits_nothing(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.update_state({}, [], _project_with_wells())
    page.show()

    canvas = page.map_canvas
    canvas.resize(800, 380)
    canvas.set_extent((0.0, 0.0, 100.0, 100.0))

    activated = []
    page.well_activated.connect(activated.append)

    _click_map(canvas, QPointF(400, 20))  # 顶部中间，离两口井都远

    assert activated == []


def test_home_page_uses_display_canvas_when_bridge_present(qtbot, qapp):
    from tests.qgis_support import QGIS_SKIP_REASON

    pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
    from paleo_workbench.ui.pages.home_page import HomePage
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    page = HomePage()
    qtbot.addWidget(page)
    assert isinstance(page.map_canvas, QgisDisplayCanvas)
