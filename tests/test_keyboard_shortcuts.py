"""Keyboard shortcut tests — Task 6 (UI Visual Consistency Polish).

These tests exercise the shortcut *callback methods* directly rather than
simulating raw keypresses, because QShortcut activation is Qt-version
sensitive and flaky under the pytest-qt offscreen platform. The contract
under test is: (a) the callbacks exist with the right behavior, and
(b) digit shortcuts are blocked while a text field has focus.
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*setActiveWindow.*")

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.pages.data_page import DataPage


def _shell_digit_shortcuts(shell: AppShell) -> list[QShortcut]:
    """Return only the 1-9/0 digit-keyed shortcuts owned by the shell
    (excludes the DataPage's Delete shortcut, which is also a descendant)."""
    out = []
    for sc in shell.findChildren(QShortcut):
        key = sc.key().toString()
        if key in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}:
            out.append(sc)
    return out


# --- AppShell digit shortcuts ---------------------------------------------

def test_digit_shortcut_switches_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0

    shell._shortcut_switch_page(2)

    assert shell.page_stack.currentIndex() == 2


def test_digit_shortcut_syncs_icon_rail_active_state(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.icon_rail.active_index == 0

    shell._shortcut_switch_page(4)

    assert shell.icon_rail.active_index == 4
    assert shell.page_stack.currentIndex() == 4


def test_digit_shortcut_blocked_in_text_field(qtbot):
    """Digit shortcuts must NOT fire when a QLineEdit has focus."""
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.show()
    QApplication.setActiveWindow(shell)
    # The data toolbar lives on page 1; switch there so its search box is the
    # current page and can actually take focus.
    shell.page_stack.setCurrentIndex(1)
    search = shell.page_stack.widget(1).data_toolbar.search_box
    search.setFocus()
    QApplication.processEvents()
    assert isinstance(QApplication.focusWidget(), QLineEdit)

    shell._shortcut_switch_page(2)  # should be a no-op

    assert shell.page_stack.currentIndex() == 1  # unchanged


def test_digit_shortcut_blocked_in_menu_bar_search(qtbot):
    """The header (menu-bar) search box is also a QLineEdit — must block."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.show()
    QApplication.setActiveWindow(window)
    shell = window.app_shell
    shell.menu_bar.search_box.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is shell.menu_bar.search_box

    shell._shortcut_switch_page(3)  # no-op

    assert shell.page_stack.currentIndex() == 0


def test_digit_shortcut_out_of_range_is_noop(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell._shortcut_switch_page(-1)
    assert shell.page_stack.currentIndex() == 0
    shell._shortcut_switch_page(999)
    assert shell.page_stack.currentIndex() == 0


def test_app_shell_registers_ten_digit_shortcuts(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    digit_shortcuts = _shell_digit_shortcuts(shell)
    assert sorted(sc.key().toString() for sc in digit_shortcuts) == [
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"
    ]


def test_direct_page_switch_out_of_range_preserves_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    original_page = shell.page_stack.currentIndex()

    shell._switch_page(-1)
    shell._switch_page(999)

    assert shell.page_stack.currentIndex() == original_page


# --- PaleoWorkbenchWindow project shortcuts -------------------------------

def _window_ctrl_shortcuts(window: PaleoWorkbenchWindow) -> list[QShortcut]:
    out = []
    for sc in window.findChildren(QShortcut):
        key = sc.key().toString()
        if key in {"Ctrl+S", "Ctrl+N", "Ctrl+O", "Ctrl+F"}:
            out.append(sc)
    return out


def test_window_registers_project_shortcuts(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    keys = sorted(sc.key().toString() for sc in _window_ctrl_shortcuts(window))
    assert keys == ["Ctrl+F", "Ctrl+N", "Ctrl+O", "Ctrl+S"]


def test_window_focus_search_targets_data_toolbar_when_data_page_active(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.show()
    QApplication.setActiveWindow(window)
    # Switch to data page and ensure it has a search box.
    window.app_shell.page_stack.setCurrentIndex(1)
    data_page = window.app_shell.data_page_widget()
    data_page.data_toolbar.search_box.setFocus()
    QApplication.processEvents()

    window._shortcut_focus_search()
    QApplication.processEvents()

    assert QApplication.focusWidget() is data_page.data_toolbar.search_box


def test_window_focus_search_falls_back_to_menu_bar(qtbot):
    """When the active page has no data_toolbar, focus the header search."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.show()
    QApplication.setActiveWindow(window)
    # Home page (index 0) has no data_toolbar.
    window.app_shell.page_stack.setCurrentIndex(0)

    window._shortcut_focus_search()
    QApplication.processEvents()

    assert QApplication.focusWidget() is window.app_shell.menu_bar.search_box


def test_window_shortcut_methods_callable(qtbot):
    """Smoke check that the project-op callbacks exist and are callable."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert callable(window.save_project)
    assert callable(window.new_project)
    assert callable(window._on_open_project)
    assert callable(window._shortcut_focus_search)


# --- DataPage Delete shortcut ----------------------------------------------

def test_data_page_registers_delete_shortcut(qtbot):
    page = DataPage()
    qtbot.addWidget(page)
    keys = [sc.key().toString() for sc in page.findChildren(QShortcut)]
    assert "Del" in keys


def test_data_page_delete_scoped_to_page(qtbot):
    """The Delete shortcut parent is the DataPage, so it only fires when
    the DataPage (or a child) has focus — verified here by the QShortcut's
    parent being the page itself."""
    page = DataPage()
    qtbot.addWidget(page)
    delete_shortcuts = [
        sc for sc in page.findChildren(QShortcut) if sc.key().toString() == "Del"
    ]
    assert len(delete_shortcuts) == 1
    sc = delete_shortcuts[0]
    assert sc.parent() is page
    assert sc.key().matches(QKeySequence("Delete"))


def test_data_page_delete_guarded_in_text_field(qtbot, tmp_path):
    """The Delete handler must not remove an asset while a text field has
    focus (otherwise typing Delete in the search box would delete assets)."""
    from paleo_workbench.project.models import ProjectDocument, ResourceItem

    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="r.txt", path=str(tmp_path / "r.txt"), type="document", format="txt"
    )
    project.resources.append(resource)

    window = PaleoWorkbenchWindow()
    window.project = project
    window._refresh_shell()
    qtbot.addWidget(window)
    window.show()
    QApplication.setActiveWindow(window)

    # Switch to data page
    window.app_shell.page_stack.setCurrentIndex(1)
    page = window.app_shell.data_page_widget()
    page._set_selected_asset(resource)
    page.data_toolbar.search_box.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is page.data_toolbar.search_box

    page._shortcut_remove_asset()  # must be a no-op

    assert resource in page.project.resources


def test_data_page_delete_removes_when_no_text_focus(qtbot, tmp_path):
    """When no text field has focus, the Delete shortcut removes the asset."""
    from paleo_workbench.project.models import ProjectDocument, ResourceItem

    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="r.txt", path=str(tmp_path / "r.txt"), type="document", format="txt"
    )
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(resource)

    page._shortcut_remove_asset()

    assert resource not in page.project.resources
