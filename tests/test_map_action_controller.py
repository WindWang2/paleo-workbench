"""QAction enablement and exclusive map-tool contracts."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from paleo_workbench.ui.map_action_controller import MapActionController, MapActionState


def test_action_controller_disables_editing_without_a_vector_layer(qtbot) -> None:
    controller = MapActionController()
    qtbot.addWidget(controller.toolbar("Digitizing", ("toggle_editing", "add_polygon", "undo")))

    controller.update_state(MapActionState())

    assert controller.actions["toggle_editing"].isEnabled() is False
    assert controller.actions["add_polygon"].isEnabled() is False
    assert controller.actions["undo"].isEnabled() is False
    assert controller.actions["select_all"].isEnabled() is False


def test_action_controller_synchronizes_exclusive_tools_and_context_state(qtbot) -> None:
    controller = MapActionController()
    chosen: list[str] = []
    controller.tool_requested.connect(chosen.append)
    controller.update_state(
        MapActionState(
            has_active_vector_layer=True,
            vector_layer_writable=True,
            editing=True,
            selected_count=2,
            compatible_polygon_count=2,
            can_undo=True,
            can_redo=True,
        )
    )

    controller.actions["select"].trigger()
    controller.actions["add_polygon"].trigger()

    assert controller.actions["add_polygon"].isChecked()
    assert not controller.actions["select"].isChecked()
    assert chosen == ["select", "add_polygon"]
    assert controller.actions["delete_selected"].isEnabled()
    assert controller.actions["merge"].isEnabled()
    assert controller.actions["undo"].shortcut() == QKeySequence("Ctrl+Z")
    assert controller.actions["cancel"].shortcut() == QKeySequence("Esc")
    assert controller.actions["previous_extent"].isEnabled() is False


def test_action_controller_creates_real_grouped_qtoolbars(qtbot) -> None:
    controller = MapActionController()
    toolbar = controller.toolbar("Navigation", ("pan", "zoom_in", "zoom_out", "full_extent"))
    qtbot.addWidget(toolbar)

    assert toolbar.actions()[0] is controller.actions["pan"]
    assert toolbar.actions()[-1] is controller.actions["full_extent"]


def test_action_controller_tracks_bounded_extent_history_state() -> None:
    controller = MapActionController()
    controller.update_state(MapActionState(can_previous_extent=True, can_next_extent=False))

    assert controller.actions["previous_extent"].isEnabled()
    assert not controller.actions["next_extent"].isEnabled()


def test_every_action_carries_a_qgis_theme_icon_and_chinese_tooltip() -> None:
    controller = MapActionController()

    for action_id, action in controller.actions.items():
        assert not action.icon().isNull(), f"action {action_id} has no icon"
        assert action.toolTip(), f"action {action_id} has no tooltip"


def test_toolbar_groups_get_separators_and_icon_only_style(qtbot) -> None:
    from PySide6.QtCore import Qt

    controller = MapActionController()
    toolbar = controller.toolbar(
        "Digitize",
        (
            ("toggle_editing", "save_edits"),
            ("add_point", "add_line"),
        ),
    )
    qtbot.addWidget(toolbar)

    assert toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    # Two groups -> one separator between them, actions in group order.
    widget_actions = [a for a in toolbar.actions() if not a.isSeparator()]
    separators = [a for a in toolbar.actions() if a.isSeparator()]
    assert widget_actions == [
        controller.actions["toggle_editing"],
        controller.actions["save_edits"],
        controller.actions["add_point"],
        controller.actions["add_line"],
    ]
    assert len(separators) == 1
    flat = controller.toolbar("Flat", ("pan", "zoom_in", "zoom_out"))
    assert not any(a.isSeparator() for a in flat.actions())
