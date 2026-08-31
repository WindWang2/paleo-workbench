from PySide6.QtGui import QShortcut

from paleo_workbench.ui.app_shell import AppShell


def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.menu_bar is not None
    assert not hasattr(shell, "header_toolbar")
    assert shell.menu_bar.search_box.objectName() == "SearchBox"
    assert shell.icon_rail is not None
    assert shell.page_stack is not None
    assert shell.status_bar is not None


def test_app_shell_has_eleven_pages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # 11 pages: 井位地图 absorbed into the Data page as a collapsible panel.
    assert shell.page_stack.count() == 11


def test_app_shell_default_page_is_zero(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0


def test_app_shell_icon_rail_switches_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.icon_rail.nav_buttons[4].click()
    assert shell.page_stack.currentIndex() == 4


def test_app_shell_geological_modeling_3d_page_navigation(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # Click 11th button (index 10: 井震联合)
    shell.icon_rail.nav_buttons[10].click()
    assert shell.page_stack.currentIndex() == 10
    geomodel_page = shell.page_stack.widget(10)
    assert geomodel_page.objectName() == "GeologicalModeling3DPage"
    assert geomodel_page.model_tree is not None
    assert geomodel_page.gl_widget is not None
    assert geomodel_page.btn_run is not None


def test_app_shell_set_project_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in shell.status_bar.status_label.text()


def test_app_shell_object_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.objectName() == "AppShell"


def test_app_shell_has_workflow_stepper(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert hasattr(shell, "workflow_stepper")
    assert shell.workflow_stepper is not None
    assert shell.workflow_stepper.objectName() == "WorkflowStepper"


def test_app_shell_embeds_stepper_in_command_header(qtbot):
    """M2: the workflow stepper lives inside the 36px menu-bar command row."""
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.workflow_stepper.parent() is shell.menu_bar
    assert shell.menu_bar._header_center is shell.workflow_stepper


def test_app_shell_stepper_switches_stage_and_recalls_subpage(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    # Landing page (首页 = index 0) belongs to stage 1: the stepper starts
    # at the FIRST stage on launch, not the last one.
    assert shell.workflow_stepper.active_stage_index == 0
    assert shell.page_stack.currentIndex() == 0

    # Click Stepper Stage 1 (综合解释) -> remembered page 测井预测 (2)
    shell.workflow_stepper.stage_buttons[1].click()
    assert shell.page_stack.currentIndex() == 2
    assert shell.workflow_stepper.active_stage_index == 1

    # Click Stepper Stage 2 (古地理编图) -> should switch to PAGE_INDEX_MAPPING (8)
    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 8
    assert shell.workflow_stepper.active_stage_index == 2

    # Switch subpage within Stage 2 to PAGE_INDEX_VISUALIZATION (6)
    shell._switch_page(6)
    assert shell.page_stack.currentIndex() == 6

    # Stage 0 recalls its remembered page (首页, the landing page)…
    shell.workflow_stepper.stage_buttons[0].click()
    assert shell.page_stack.currentIndex() == 0

    # …then back to Stage 2 -> should recall PAGE_INDEX_VISUALIZATION (6)
    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 6


# --- Command palette (Ctrl+K) ----------------------------------------------

def _palette_escape_event():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )


def test_command_palette_lists_pages_and_stages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # No shell.show(): offscreen GL pages crash on native-window exposure
    # (suite convention); isHidden() tracks popup state without a window.

    shell.command_palette.popup()
    assert not shell.command_palette.isHidden()
    # 11 pages + 4 stages
    assert shell.command_palette.result_list.count() == 15

    shell.command_palette.filter_input.setText("编图")
    assert 0 < shell.command_palette.result_list.count() < 15


def test_command_palette_page_result_navigates(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.command_palette.popup()
    shell.command_palette.filter_input.setText("地震预测")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == 3
    assert shell.command_palette.isHidden()


def test_command_palette_stage_result_respects_memory(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(6)  # 可视化 becomes the 古地理编图 stage's remembered page

    shell.command_palette.popup()
    # "古地理编图" matches only the stage ❸ command (page hints differ).
    shell.command_palette.filter_input.setText("古地理编图")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == 6
    assert shell.command_palette.isHidden()


def test_command_palette_escape_dismisses(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    palette = shell.command_palette

    # Esc works from the filter box…
    palette.popup()
    assert palette.eventFilter(palette.filter_input, _palette_escape_event()) is True
    assert palette.isHidden()

    # …and from the result list (r1 p3: keyboard users on the list keep Esc).
    palette.popup()
    assert palette.eventFilter(palette.result_list, _palette_escape_event()) is True
    assert palette.isHidden()


def test_ctrl_k_toggles_command_palette(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    keys = [
        sc.key().toString() for sc in shell.findChildren(QShortcut)
    ]
    assert "Ctrl+K" in keys

    shell._toggle_command_palette()
    assert not shell.command_palette.isHidden()
    shell._toggle_command_palette()
    assert shell.command_palette.isHidden()


def test_switch_page_dismisses_palette(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.command_palette.popup()
    shell._switch_page(1)
    assert shell.command_palette.isHidden()
