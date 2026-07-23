from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.map_workbench_bottom import MapWorkbenchBottom


def test_bottom_workbench_has_attribute_topology_and_factor_tabs(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    assert [bottom.tabText(index) for index in range(bottom.count())] == ["属性", "拓扑问题", "单因素参考图"]
    bottom.set_collapsed(True)
    assert bottom.isHidden()
    bottom.set_collapsed(False)
    assert not bottom.isHidden()


def _complete_task(**overrides):
    kwargs = dict(
        name="厚度",
        target_horizon="H1",
        factor_type="厚度",
        method="IDW",
        status="complete",
        output_resource_ids=["grid_res_1"],
    )
    kwargs.update(overrides)
    return FactorMapTask(**kwargs)


def test_topology_panel_locate_requested_on_double_click(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    panel = bottom.topology_panel
    panel.set_issues([{"feature_id": "f1", "message": "自相交", "severity": "error"}])
    seen: list[str] = []
    panel.locate_requested.connect(seen.append)
    item = panel.table.item(0, 0)
    panel.table.itemDoubleClicked.emit(item)
    assert seen == ["f1"]


def test_topology_panel_locate_requested_on_enter(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    panel = bottom.topology_panel
    panel.set_issues([{"feature_id": "f2", "message": "自相交", "severity": "error"}])
    panel.table.setCurrentCell(0, 0)
    seen: list[str] = []
    panel.locate_requested.connect(seen.append)
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.table, press)
    assert seen == ["f2"]


def test_factor_shelf_emits_overlay_requested_on_card_click(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    shelf = bottom.factor_shelf
    shelf.update_state([_complete_task()])
    seen: list[str] = []
    shelf.factor_overlay_requested.connect(seen.append)
    cards = shelf.grid.grid_container.findChildren(FactorPreviewGrid.FactorPreviewCard)
    assert len(cards) == 1
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(5.0, 5.0),
        QPointF(5.0, 5.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cards[0].mouseReleaseEvent(release)
    assert seen == ["grid_res_1"]


def test_factor_shelf_overlay_falls_back_to_task_id(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    shelf = bottom.factor_shelf
    task = _complete_task(output_resource_ids=[])
    shelf.update_state([task])
    seen: list[str] = []
    shelf.factor_overlay_requested.connect(seen.append)
    cards = shelf.grid.grid_container.findChildren(FactorPreviewGrid.FactorPreviewCard)
    assert len(cards) == 1
    cards[0].clicked.emit(cards[0].task)
    assert seen == [task.id]


def test_factor_shelf_stores_view_state_and_cursor(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    shelf = bottom.factor_shelf
    shelf.set_view_state({"center": (1.0, 2.0), "scale": 3.0})
    shelf.set_cursor_position((4.0, 5.0))
    assert shelf.view_state() == {"center": (1.0, 2.0), "scale": 3.0}
    assert shelf.cursor_position() == (4.0, 5.0)
