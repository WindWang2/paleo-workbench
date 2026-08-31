"""Offscreen-safe tests for FloatingPanel and FloatController (M4)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, Qt
from PySide6.QtWidgets import QApplication, QSizeGrip, QSplitter, QWidget

from paleo_workbench.ui.floating_panel import FloatingPanel
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.panel_float_controller import FloatController


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def tracked(qapp):
    """Widgets created by a test get closed + scheduled for deletion."""
    created: list[QWidget] = []
    yield created
    for widget in created:
        widget.close()
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture()
def layout_persistence(tmp_path) -> LayoutPersistence:
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    return LayoutPersistence(settings)


def _make_splitter() -> tuple[QSplitter, list[QWidget]]:
    splitter = QSplitter()
    widgets = [QWidget() for _ in range(3)]
    for widget in widgets:
        splitter.addWidget(widget)
    return splitter, widgets


# --- FloatingPanel ------------------------------------------------------


def test_floating_panel_is_window_with_chrome(qapp, tracked):
    panel = FloatingPanel("mapping:layer_tree", "图层管理树")
    tracked.append(panel)

    assert panel.key == "mapping:layer_tree"
    assert bool(panel.windowFlags() & Qt.WindowType.Window)
    assert panel.windowTitle() == "图层管理树"
    assert panel.title_label.text() == "图层管理树"
    assert panel.dock_back_button is not None
    assert panel.close_button is not None
    # The size grip is part of the window chrome.
    assert panel.findChildren(QSizeGrip)


def test_floating_panel_content_round_trip(qapp, tracked):
    panel = FloatingPanel("p:key", "面板")
    tracked.append(panel)
    widget = QWidget()

    panel.set_content(widget)
    assert widget.parentWidget() is panel.content_host

    detached = panel.take_content()
    assert detached is widget
    assert widget.parent() is None
    assert panel.take_content() is None


def test_floating_panel_dock_back_signal(qapp, tracked):
    panel = FloatingPanel("p:key", "面板")
    tracked.append(panel)

    emitted = []
    panel.dock_back_requested.connect(emitted.append)
    panel.dock_back_button.click()
    assert emitted == ["p:key"]


def test_floating_panel_close_while_hosting_signals_hidden(qapp, tracked):
    panel = FloatingPanel("p:key", "面板")
    tracked.append(panel)
    panel.set_content(QWidget())
    panel.show()

    emitted = []
    panel.visibility_changed.connect(lambda key, visible: emitted.append((key, visible)))
    panel.close()
    assert emitted == [("p:key", False)]
    assert panel.isHidden()


def test_floating_panel_close_while_empty_is_silent(qapp, tracked):
    panel = FloatingPanel("p:key", "面板")
    tracked.append(panel)

    emitted = []
    panel.visibility_changed.connect(lambda key, visible: emitted.append((key, visible)))
    panel.close()
    assert emitted == []


def test_floating_panel_visibility_tracked_through_show_and_hide(qapp, tracked):
    """p2-3: show/hide (not just close) report visibility while hosting."""
    panel = FloatingPanel("p:key", "面板")
    tracked.append(panel)
    panel.set_content(QWidget())

    emitted = []
    panel.visibility_changed.connect(lambda key, visible: emitted.append((key, visible)))
    panel.show()
    panel.hide()
    # close() on the already-hidden panel must not re-emit.
    panel.close()
    assert emitted == [("p:key", True), ("p:key", False)]


# --- FloatController ----------------------------------------------------


def test_float_dock_round_trip_preserves_index_and_sizes(qapp, tracked):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    splitter.resize(1400, 500)
    splitter.show()
    splitter.setSizes([100, 300, 500])
    before = list(splitter.sizes())

    controller = FloatController(resolver={"w1": widgets[1]}.get)
    emitted = []
    controller.float_changed.connect(lambda key, floating: emitted.append((key, floating)))

    assert controller.float_panel("w1") is True
    assert controller.is_floating("w1")
    assert widgets[1].parentWidget() is controller.floating_panel("w1").content_host
    assert splitter.count() == 2
    assert controller.floating_panel("w1").isVisible()

    assert controller.dock_panel("w1") is True
    assert not controller.is_floating("w1")
    assert splitter.indexOf(widgets[1]) == 1
    assert list(splitter.sizes()) == before
    assert controller.floating_panel("w1") is None
    assert widgets[1].isVisible()
    assert emitted == [("w1", True), ("w1", False)]


def test_float_round_trip_without_splitter(qapp, tracked):
    host = QWidget()
    tracked.append(host)
    widget = QWidget(host)
    widget.setGeometry(QRect(20, 30, 200, 100))

    controller = FloatController()
    assert controller.float_panel("solo", widget) is True
    assert widget.parentWidget() is controller.floating_panel("solo").content_host

    assert controller.dock_panel("solo") is True
    assert widget.parentWidget() is host
    assert widget.geometry() == QRect(20, 30, 200, 100)


def test_float_panel_uses_saved_geometry(qapp, tracked, layout_persistence):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    saved_rect = QRect(64, 72, 480, 360)
    layout_persistence.save_float("w2", saved_rect)

    controller = FloatController(resolver={"w2": widgets[2]}.get, persistence=layout_persistence)
    assert controller.restore_saved("w2") is True
    assert controller.is_floating("w2")
    assert controller.floating_panel("w2").geometry() == saved_rect

    controller.dock_panel("w2")


def test_restore_saved_hidden_floating_keeps_store_in_sync(qapp, tracked, layout_persistence):
    """P1-1 regression: restoring a floating+hidden record must not leave
    ``visible:True`` in the store — the next launch would revive a panel the
    user hid."""
    layout_persistence.save_float("w1", QRect(10, 20, 300, 200))
    layout_persistence.save_visibility("w1", False)

    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    controller = FloatController(resolver={"w1": widgets[1]}.get, persistence=layout_persistence)
    assert controller.restore_saved("w1") is True
    assert controller.is_floating("w1")
    assert not controller.floating_panel("w1").isVisible()

    # Probe: the store must agree with the UI after the restore.
    probe = layout_persistence.load("w1")
    assert probe.floating is True
    assert probe.visible is False

    # And docking back heals the record to visible again.
    assert controller.dock_panel("w1") is True
    assert layout_persistence.load("w1").visible is True


def test_restore_saved_is_noop_without_record(qapp, tracked, layout_persistence):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)

    controller = FloatController(resolver={"w0": widgets[0]}.get, persistence=layout_persistence)
    assert controller.restore_saved("w0") is False
    assert not controller.is_floating("w0")
    assert controller.floating_panel("w0") is None
    assert widgets[0].isVisibleTo(splitter)


def test_restore_saved_docked_sizes_and_hidden(qapp, tracked, layout_persistence):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    splitter.resize(1400, 500)
    splitter.show()
    splitter.setSizes([600, 100, 100])
    layout_persistence.save_visibility("w0", False)

    controller = FloatController(resolver={"w0": widgets[0]}.get, persistence=layout_persistence)
    assert controller.restore_saved("w0") is True
    assert widgets[0].isHidden()

    widgets[0].setVisible(True)
    assert controller.dock_panel("w0") is False  # never floated


def test_float_reveals_widget_hidden_by_restore(qapp, tracked, layout_persistence):
    """A docked-hidden panel must not surface as an empty floating window."""
    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    layout_persistence.save_visibility("w0", False)

    controller = FloatController(resolver={"w0": widgets[0]}.get, persistence=layout_persistence)
    assert controller.restore_saved("w0") is True
    assert widgets[0].isHidden()

    assert controller.float_panel("w0") is True
    panel = controller.floating_panel("w0")
    assert panel.isVisible()
    assert widgets[0].isVisibleTo(panel)
    controller.dock_panel("w0")


def test_toggle_and_is_floating(qapp, tracked):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)

    controller = FloatController(resolver={"w1": widgets[1]}.get)
    assert controller.toggle("w1") is True
    assert controller.is_floating("w1")
    assert controller.toggle("w1") is True
    assert not controller.is_floating("w1")
    assert controller.floating_keys() == ()


def test_float_rejections(qapp, tracked):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)

    controller = FloatController(resolver={"w1": widgets[1]}.get)
    # Unknown key / no resolver hit.
    assert controller.float_panel("missing") is False
    assert controller.dock_panel("w1") is False
    # Double float is refused and state stays consistent.
    assert controller.float_panel("w1") is True
    assert controller.float_panel("w1") is False
    assert controller.is_floating("w1")
    controller.dock_panel("w1")
    assert not controller.is_floating("w1")


def test_controller_without_persistence_skips_restore(qapp, tracked):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)

    controller = FloatController(resolver={"w1": widgets[1]}.get)
    assert controller.restore_saved("w1") is False
    assert controller.float_panel("w1") is True
    # No persistence: nothing to write, float still works.
    assert controller.is_floating("w1")
    controller.dock_panel("w1")


def test_floating_panel_close_persists_visibility(qapp, tracked, layout_persistence):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)

    controller = FloatController(resolver={"w1": widgets[1]}.get, persistence=layout_persistence)
    assert controller.float_panel("w1") is True
    panel = controller.floating_panel("w1")
    panel.close()
    assert layout_persistence.load("w1").visible is False
    assert layout_persistence.load("w1").floating is True

    # Closing must not confuse the subsequent dock-back.
    assert controller.dock_panel("w1") is True
    record = layout_persistence.load("w1")
    assert record.floating is False
    assert record.visible is True


def test_float_changed_only_on_real_transitions(qapp, tracked):
    controller = FloatController()
    emitted = []
    controller.float_changed.connect(lambda key, floating: emitted.append((key, floating)))

    assert controller.float_panel("nope") is False
    assert controller.dock_panel("nope") is False
    assert emitted == []


def test_registry_title_via_namespaced_key(qapp, tracked):
    from paleo_workbench.ui.dock_manager import DockManager

    registry = DockManager()
    registry.register_panel("custom_panel", "自定义面板")
    controller = FloatController(title_for=lambda key: registry.panel_title(key) or key)

    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    assert controller.float_panel("mapping:custom_panel", widgets[0]) is True
    panel = controller.floating_panel("mapping:custom_panel")
    assert panel.windowTitle() == "自定义面板"
    controller.dock_panel("mapping:custom_panel")


def test_default_geometry_offsets_from_dock_parent(qapp, tracked):
    splitter, widgets = _make_splitter()
    tracked.append(splitter)
    splitter.move(QPoint(100, 100))

    controller = FloatController(resolver={"w0": widgets[0]}.get)
    assert controller.float_panel("w0") is True
    panel = controller.floating_panel("w0")
    assert panel.geometry().width() >= 420
    assert panel.geometry().height() >= 320
    controller.dock_panel("w0")
