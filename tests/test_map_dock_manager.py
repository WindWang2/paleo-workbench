"""Dock rail / panel manager for the mapping workspace."""

from __future__ import annotations

from PySide6.QtWidgets import QToolBar, QToolButton

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def _make_page(qtbot) -> MappingPage:
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([PaleoMapDocument(name="M", linked_target_horizon="H1")])
    return page


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
    }
    assert keys == {"layers", "reference", "chrome", "bottom"}


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
