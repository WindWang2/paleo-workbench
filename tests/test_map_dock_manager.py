"""Dock rail / panel manager for the mapping workspace."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QFrame, QToolBar, QToolButton

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.pages.map_dock_manager import MapDockManager
from paleo_workbench.ui.pages.mapping_page import MappingPage


class _FakeFloatController(QObject):
    """Minimal M4-shaped FloatController surface for dock-manager tests."""

    float_changed = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.floating: dict[str, bool] = {}
        self.panels: dict[str, QFrame] = {}
        self.toggled_keys: list[str] = []

    def is_floating(self, key: str) -> bool:
        return self.floating.get(key, False)

    def floating_panel(self, key: str) -> QFrame | None:
        return self.panels.get(key)

    def toggle(self, key: str) -> bool:
        self.toggled_keys.append(key)
        if self.floating.get(key):
            self.floating[key] = False
            panel = self.panels.pop(key, None)
            if panel is not None:
                panel.deleteLater()
        else:
            self.floating[key] = True
            self.panels[key] = QFrame()
        self.float_changed.emit(key, self.floating[key])
        return self.floating[key]


@pytest.fixture(autouse=True)
def _hermetic_layout_store(monkeypatch, tmp_path):
    """Isolate the QSettings-backed layout store (and float restore) per test."""
    import paleo_workbench.ui.pages.mapping_page as mapping_page_module

    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(
        mapping_page_module,
        "LayoutPersistence",
        lambda: LayoutPersistence(settings),
    )


def _make_page(qtbot) -> MappingPage:
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([PaleoMapDocument(name="M", linked_target_horizon="H1")])
    return page


def _bare_manager(qtbot, keys=("layers", "reference"), float_key="{key}") -> tuple[MapDockManager, dict]:
    manager = MapDockManager()
    widgets = {}
    for i, key in enumerate(keys):
        widget = QFrame()
        qtbot.addWidget(widget)
        widgets[key] = widget
        manager.add_panel(
            key, f"面板{key}", "panel-layers", widget,
            side="left" if i == 0 else "right", checked=True,
            float_key=float_key.format(key=key),
        )
    return manager, widgets


def test_single_toolbar_strip_carries_every_action(qtbot) -> None:
    page = _make_page(qtbot)

    toolbars = page.map_toolbars.findChildren(QToolBar)
    assert len(toolbars) == 1
    action_ids = {
        action.objectName().removeprefix("MapAction:")
        for action in toolbars[0].actions()
        if action.objectName().startswith("MapAction:")
    }
    assert action_ids == set(page.action_controller.actions.keys())

    menu_button = page.map_toolbars.findChild(QToolButton, "MapPanelsMenuButton")
    assert menu_button is not None and menu_button.menu() is not None
    keys = {
        action.objectName().removeprefix("MapPanelMenu:")
        for action in menu_button.menu().actions()
        if action.objectName().startswith("MapPanelMenu:")
    }
    assert keys == {"layers", "reference", "chrome", "composer", "bottom"}


def test_default_panel_visibility(qtbot) -> None:
    page = _make_page(qtbot)
    manager = page.dock_manager

    assert manager.is_panel_visible("layers")
    assert manager.is_panel_visible("reference")
    assert manager.is_panel_visible("chrome") is False
    assert not page.layer_tree_stack.isHidden()
    assert not page.reference_panel.isHidden()
    assert page.chrome_panel.isHidden()
    assert not manager.left_dock.area.isHidden()
    assert not manager.right_dock.area.isHidden()


def test_rail_collapse_leaves_only_the_icon_rail(qtbot) -> None:
    page = _make_page(qtbot)
    manager = page.dock_manager

    manager.set_panel_visible("layers", False)
    assert page.layer_tree_stack.isHidden()
    assert manager.left_dock.area.isHidden()
    assert not manager.left_dock.rail.isHidden()

    manager.set_panel_visible("layers", True)
    assert not page.layer_tree_stack.isHidden()
    assert not manager.left_dock.area.isHidden()


def test_collapsing_every_right_panel_hides_the_right_area(qtbot) -> None:
    page = _make_page(qtbot)
    manager = page.dock_manager

    manager.set_panel_visible("chrome", True)
    assert not page.chrome_panel.isHidden()
    manager.set_panel_visible("chrome", False)
    manager.set_panel_visible("reference", False)
    assert manager.right_dock.area.isHidden()
    manager.set_panel_visible("reference", True)
    assert not manager.right_dock.area.isHidden()


def test_panels_menu_action_drives_rail_and_stays_synced(qtbot) -> None:
    page = _make_page(qtbot)
    manager = page.dock_manager
    menu = page.map_toolbars.findChild(QToolButton, "MapPanelsMenuButton").menu()
    action = next(a for a in menu.actions() if a.objectName() == "MapPanelMenu:reference")

    action.trigger()
    assert page.reference_panel.isHidden()
    assert manager.is_panel_visible("reference") is False
    assert manager.panel_button("reference").isChecked() is False
    assert action.isChecked() is False

    manager.panel_button("reference").click()
    assert not page.reference_panel.isHidden()
    assert action.isChecked() is True


def test_bottom_workbench_user_collapse_combines_with_preview_mode(qtbot) -> None:
    page = _make_page(qtbot)
    manager = page.dock_manager
    assert not page.bottom_workbench.isHidden()

    manager.set_panel_visible("bottom", False)
    assert page.bottom_workbench.isHidden()
    manager.set_panel_visible("bottom", True)
    assert not page.bottom_workbench.isHidden()

    # Preview mode still forces the bottom workbench hidden, then restores it.
    page.set_preview_mode(True)
    assert page.bottom_workbench.isHidden()
    page.set_preview_mode(False)
    assert not page.bottom_workbench.isHidden()


def test_panel_instances_are_reused_inside_the_docks(qtbot) -> None:
    page = _make_page(qtbot)
    assert page.layer_tree.parent() is page.layer_tree_stack
    assert page.layer_tree_stack.parent() is page.dock_manager.left_dock.area
    assert page.reference_panel.parent() is page.dock_manager.right_dock.area
    assert page.chrome_panel.parent() is page.dock_manager.right_dock.area


# ---------------------------------------------------------------------------
# Panel float (浮动) wiring in the dock manager
# ---------------------------------------------------------------------------


def test_panels_menu_gains_a_float_toggle_per_panel(qtbot) -> None:
    manager, _ = _bare_manager(qtbot)
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)

    menu = manager.panels_menu()
    float_actions = {
        action.objectName().removeprefix("MapPanelFloat:"): action
        for action in menu.actions()
        if action.objectName().startswith("MapPanelFloat:")
    }
    assert set(float_actions) == {"layers", "reference"}
    assert all(action.isCheckable() for action in float_actions.values())
    assert all(not action.isChecked() for action in float_actions.values())

    float_actions["layers"].trigger()
    assert controller.is_floating("layers")
    assert manager.is_floating("layers")
    assert float_actions["layers"].isChecked()


def test_no_float_actions_without_a_controller(qtbot) -> None:
    manager, _ = _bare_manager(qtbot)

    menu = manager.panels_menu()
    assert [a for a in menu.actions() if a.objectName().startswith("MapPanelFloat:")] == []
    assert manager.is_floating("layers") is False
    manager.toggle_float("layers")  # no controller attached: harmless no-op


def test_rail_button_context_menu_carries_the_float_toggle(qtbot) -> None:
    manager, _ = _bare_manager(qtbot)
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)

    button = manager.panel_button("layers")
    assert button.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    menu = manager.rail_context_menu("layers")
    actions = [a for a in menu.actions() if a.objectName() == "MapPanelFloat:layers"]
    assert len(actions) == 1 and actions[0].isCheckable()

    actions[0].trigger()
    assert controller.is_floating("layers")


def test_float_changed_syncs_menu_action_and_keeps_rail_checked(qtbot) -> None:
    manager, _ = _bare_manager(qtbot)
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)
    menu = manager.panels_menu()
    layers_float = next(a for a in menu.actions() if a.objectName() == "MapPanelFloat:layers")

    controller.floating["layers"] = True
    controller.float_changed.emit("layers", True)
    assert layers_float.isChecked()
    assert manager.panel_button("layers").isChecked()

    controller.floating["layers"] = False
    controller.float_changed.emit("layers", False)
    assert layers_float.isChecked() is False


def test_rail_toggle_hides_the_floating_window_not_the_bare_widget(qtbot) -> None:
    manager, widgets = _bare_manager(qtbot)
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)
    manager.panels_menu()
    events: list[tuple[str, bool]] = []
    manager.panel_toggled.connect(lambda key, on: events.append((key, on)))

    controller.toggle("layers")

    manager.panel_button("layers").setChecked(False)
    assert controller.panels["layers"].isHidden()  # floating window hidden
    assert not widgets["layers"].isHidden()  # bare widget untouched while floating

    manager.panel_button("layers").setChecked(True)
    assert not controller.panels["layers"].isHidden()
    assert ("layers", False) in events and ("layers", True) in events


def test_dock_back_restores_button_visibility_semantics(qtbot) -> None:
    manager, widgets = _bare_manager(qtbot)
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)
    manager.panels_menu()

    # Floating turns the (checked) rail button into a window show.
    controller.toggle("layers")
    assert not widgets["layers"].isHidden()

    # Dock back while the user hid the panel: it returns hidden, per button.
    manager.panel_button("layers").setChecked(False)
    controller.toggle("layers")
    assert widgets["layers"].isHidden()


def test_namespaced_float_keys_reach_the_controller(qtbot) -> None:
    manager, _ = _bare_manager(qtbot, float_key="mapping:{key}")
    controller = _FakeFloatController()
    manager.attach_float_controller(controller)
    menu = manager.panels_menu()
    layers_float = next(a for a in menu.actions() if a.objectName() == "MapPanelFloat:layers")

    layers_float.trigger()
    assert controller.is_floating("mapping:layers")
    assert manager.is_floating("layers")

    # float_changed carries the controller (namespaced) key back
    controller.toggle("mapping:layers")
    assert layers_float.isChecked() is False
    assert manager.is_floating("layers") is False
