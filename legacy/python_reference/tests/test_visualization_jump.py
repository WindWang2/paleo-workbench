from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. TEST:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def _wait_preview_idle(qtbot, data_page, timeout: int = 5000) -> None:
    """Drain async data-page preview work before open_ref / teardown."""
    controller = data_page._preview_controller
    qtbot.waitUntil(
        lambda: controller._active_job.thread is None and controller._pending is None,
        timeout=timeout,
    )


def test_data_page_jump_switches_to_visualization(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    window.project.resources.append(res)
    window._apply_project_to_shell()

    data_page = window.app_shell.data_page_widget()
    data_page._set_selected_asset(res)
    assert data_page.open_visualization_btn.isEnabled() is True

    # Avoid offscreen abort: live preview QThreads + open_ref / widget teardown.
    _wait_preview_idle(qtbot, data_page)

    data_page.open_visualization_btn.click()
    assert window.app_shell.page_stack.currentIndex() == PAGE_INDEX_VISUALIZATION
    # Ribbon 删除后导航态以页栈为准（B2）。
    assert window.app_shell.page_stack.currentIndex() == PAGE_INDEX_VISUALIZATION

    viz = window.app_shell.page_stack.widget(PAGE_INDEX_VISUALIZATION)
    assert viz._current_ref is not None
    assert viz._current_ref.source == "data_page"
    assert viz._current_ref.kind == "well_log"
    qtbot.waitUntil(viz.composite_panel.has_well_log_loaded, timeout=10_000)
    assert viz.composite_panel.has_well_log_loaded()
    data_page._preview_controller.shutdown()


def test_visualization_button_disabled_for_unsupported(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    res = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    window.project.resources.append(res)
    window._apply_project_to_shell()

    data_page = window.app_shell.data_page_widget()
    data_page._preview_controller.request = lambda *a, **k: None
    data_page._set_selected_asset(res)
    assert data_page.open_visualization_btn.isEnabled() is False
