from PySide6.QtGui import QShortcut

from paleo_workbench.ui import navigation
from paleo_workbench.ui.app_shell import AppShell


def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # Ribbon 已删除（B2）：全局 chrome 由工作站 app bar 承担。
    assert not hasattr(shell, "ribbon")
    assert not hasattr(shell, "menu_bar")
    assert not hasattr(shell, "icon_rail")
    assert shell.workstation.app_bar.objectName() == "WorkstationAppBar"
    assert shell.page_stack is not None
    assert shell.status_bar is not None


def test_app_shell_has_five_hub_pages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # 4+1 hubs: 数据 / 井 / 地震 / 编图 / 可视化 (临时).
    assert shell.page_stack.count() == 5


def test_app_shell_default_page_is_zero(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0


def test_app_shell_navigation_request_switches_page(qtbot):
    """explorer → shell.navigation_requested → hub 页切换（原 ribbon tab 路径）。"""
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.workstation.navigation_requested.emit(1, "")
    assert shell.page_stack.currentIndex() == 1


def test_app_shell_geological_modeling_3d_page_navigation(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.navigate_to(navigation.PAGE_INDEX_SEISMIC, "geomodel")
    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_SEISMIC
    geomodel_page = shell.geomodel_page
    assert shell.hub_seismic.current_key() == "geomodel"
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


def test_app_shell_exposes_project_action_signals(qtbot):
    """Ribbon 删除后 AppShell 自带工程动作信号（app bar → 窗口处理器）。"""
    shell = AppShell()
    qtbot.addWidget(shell)
    for name in (
        "new_project_requested",
        "open_project_requested",
        "open_sample_project_requested",
        "save_project_requested",
        "properties_requested",
        "preview_settings_requested",
    ):
        assert hasattr(shell, name), f"AppShell 缺少 {name}"


def test_app_shell_hub_recalls_active_submodule(qtbot):
    """Re-entering a hub recalls its current sub-module (no reset to default)."""
    shell = AppShell()
    qtbot.addWidget(shell)

    # Landing hub (数据) starts on its default sub-module.
    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_DATA
    assert shell.hub_data.current_key() == "overview"

    # Switch within 井 hub to 地层对比…
    shell.navigate_to(navigation.PAGE_INDEX_WELL, "stratigraphy")
    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_WELL
    assert shell.hub_well.current_key() == "stratigraphy"

    # …leave for 数据, then come back: 地层对比 is recalled.
    shell.navigate_to(navigation.PAGE_INDEX_DATA)
    shell.navigate_to(navigation.PAGE_INDEX_WELL)
    assert shell.hub_well.current_key() == "stratigraphy"


def test_app_shell_submodule_switch_updates_hub_state(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.navigate_to(navigation.PAGE_INDEX_MAPPING, "review")
    assert shell.hub_mapping.current_key() == "review"


# --- Command palette (Ctrl+K) ----------------------------------------------

def _palette_escape_event():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )


def test_command_palette_lists_submodules(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    # No shell.show(): offscreen GL pages crash on native-window exposure
    # (suite convention); isHidden() tracks popup state without a window.

    shell.command_palette.popup()
    assert not shell.command_palette.isHidden()
    total = sum(len(navigation.submodule_keys(h)) for h in range(5))
    assert shell.command_palette.result_list.count() == total

    shell.command_palette.filter_input.setText("编图")
    assert 0 < shell.command_palette.result_list.count() < total


def test_command_palette_result_navigates(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.command_palette.popup()
    shell.command_palette.filter_input.setText("地震预测")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_SEISMIC
    assert shell.hub_seismic.current_key() == "seismic"
    assert shell.command_palette.isHidden()


def test_command_palette_hub_switch_preserves_submodule(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.navigate_to(navigation.PAGE_INDEX_WELL, "stratigraphy")

    shell.command_palette.popup()
    # "井" hub commands; picking 测井预测 jumps straight to the sub-module.
    shell.command_palette.filter_input.setText("测井预测")
    shell.command_palette._activate_item(
        shell.command_palette.result_list.currentItem()
    )

    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_WELL
    assert shell.hub_well.current_key() == "well_log"
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
