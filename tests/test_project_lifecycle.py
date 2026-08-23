"""Tests for PaleoWorkbenchWindow project lifecycle (new/open/save/save-as)."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem


def test_new_project_clears_path(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    # Simulate a previously-saved project.
    window.project_path = Path("/tmp/saved.paleo.json")

    window.new_project()

    assert window.project_path is None
    assert "Untitled" in window.windowTitle()


def test_open_dialog_defaults_to_workspace_project_area(qtbot, monkeypatch):
    """打开工程对话框默认定位到工作区 data/project_area（无工程路径时）。"""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.project_path = None

    captured: dict[str, str] = {}

    def fake_dialog(parent, title, start_dir, filt):  # noqa: ARG001
        captured["start_dir"] = start_dir
        return "", ""

    monkeypatch.setattr(
        "paleo_workbench.ui.project_controller.QFileDialog.getOpenFileName",
        fake_dialog,
    )
    assert window.project_controller._choose_open_project() is None
    assert captured["start_dir"].endswith("data/project_area")


def test_open_dialog_prefers_current_project_dir(qtbot, monkeypatch, tmp_path: Path):
    """已保存工程存在时，对话框起始目录取工程文件所在目录。"""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.project_path = tmp_path / "X.paleo.json"

    captured: dict[str, str] = {}

    def fake_dialog(parent, title, start_dir, filt):  # noqa: ARG001
        captured["start_dir"] = start_dir
        return "", ""

    monkeypatch.setattr(
        "paleo_workbench.ui.project_controller.QFileDialog.getOpenFileName",
        fake_dialog,
    )
    assert window.project_controller._choose_open_project() is None
    assert captured["start_dir"] == str(tmp_path)


def test_new_project_uses_custom_name(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    window.new_project("X")

    assert window.project.meta.name == "X"
    assert window.windowTitle().startswith("X")


def test_save_as_writes_file_and_stores_path(qtbot, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    result = window.save_project_as(tmp_path / "p")

    expected = tmp_path / "p.paleo.json"
    assert result == expected
    assert expected.exists()
    assert window.project_path == expected


def test_save_as_normalizes_extension(qtbot, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    # ".json" gets ".paleo.json" appended (not stripped).
    result = window.save_project_as(tmp_path / "p.json")
    assert result == tmp_path / "p.paleo.json"
    assert (tmp_path / "p.paleo.json").exists()

    # An already-correct extension is not doubled.
    window2 = PaleoWorkbenchWindow()
    qtbot.addWidget(window2)
    result2 = window2.save_project_as(tmp_path / "p.paleo.json")
    assert result2 == tmp_path / "p.paleo.json"


def test_save_project_uses_existing_path(qtbot, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    target = tmp_path / "p.paleo.json"
    window.project_path = target

    result = window.save_project()

    assert result == target
    assert target.exists()


def test_save_project_without_path_returns_none(qtbot, monkeypatch):
    """When no path is set and the user cancels the save dialog, return None."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window.project_path is None

    # Avoid opening a real QFileDialog — simulate the user cancelling.
    monkeypatch.setattr(window, "_choose_save_project", lambda: None)

    assert window.save_project() is None
    assert window.project_path is None


def test_open_project_path_loads(qtbot, tmp_path: Path):
    # Build a project with a resource and save it.
    project = ProjectDocument.new("With Resource")
    project.resources.append(
        ResourceItem(name="r1", path="/tmp/r1.las", type="well_log", format="LAS", status="parsed")
    )
    target = tmp_path / "p.paleo.json"
    window0 = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window0)
    window0.save_project_as(target)
    qtbot.wait(10)

    # Fresh window, open the saved file.
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    ok = window.open_project_path(target)

    assert ok is True
    assert window.project_path == target
    assert window.project.meta.name == "With Resource"
    # Resource visible on data page.
    data_page = window.app_shell.data_page_widget()
    assert any(r.name == "r1" for r in window.project.resources)
    # Sanity: data page model holds at least the one resource.
    # (DataPage exposes ``asset_table`` (a DataAssetTable) whose ``model``
    # is the AssetTableModel; the prior ``hasattr(data_page, "table")`` guard
    # used the wrong name so this check never ran.)
    assert data_page.asset_table.model.rowCount() >= 1


def test_open_project_path_invalid_returns_false(qtbot, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    original_name = window.project.meta.name

    # Nonexistent file -> OSError/FileNotFoundError -> False.
    ok = window.open_project_path(tmp_path / "does_not_exist.paleo.json")
    assert ok is False
    assert window.project.meta.name == original_name

    # Invalid JSON file -> JSONDecodeError -> False.
    bad = tmp_path / "bad.paleo.json"
    bad.write_text("{not json", encoding="utf-8")
    ok2 = window.open_project_path(bad)
    assert ok2 is False
    assert window.project.meta.name == original_name


# --- Task 3: file dialog helpers + toolbar signal wiring ---

def test_save_project_uses_dialog_when_no_path(qtbot, tmp_path: Path, monkeypatch):
    """When project_path is None, save_project() invokes the save dialog."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window.project_path is None

    chosen = tmp_path / "from_dialog.paleo.json"
    monkeypatch.setattr(window, "_choose_save_project", lambda: chosen)

    result = window.save_project()

    assert result == chosen
    assert chosen.exists()
    assert window.project_path == chosen


def test_cancel_save_dialog_returns_none(qtbot, monkeypatch):
    """Cancelling the save dialog returns None and writes no file."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window.project_path is None

    monkeypatch.setattr(window, "_choose_save_project", lambda: None)

    assert window.save_project() is None
    assert window.project_path is None


def test_open_handler_reports_error_on_failure(qtbot, tmp_path: Path, monkeypatch):
    """A failed open via the handler reports an error and leaves the project unchanged."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    original_name = window.project.meta.name

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_show_project_error", lambda title, msg: calls.append((title, msg)))
    bad_path = tmp_path / "missing.paleo.json"
    monkeypatch.setattr(window, "_choose_open_project", lambda: bad_path)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)

    window._on_open_project()

    assert len(calls) == 1
    assert "不存在" in calls[0][1]
    assert window.project.meta.name == original_name
    assert window.project_path is None


def test_open_handler_distinguishes_corrupt_json(qtbot, tmp_path: Path, monkeypatch):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    bad = tmp_path / "bad.paleo.json"
    bad.write_text("{not-json", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_show_project_error", lambda title, msg: calls.append((title, msg)))
    monkeypatch.setattr(window, "_choose_open_project", lambda: bad)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)

    window._on_open_project()

    assert len(calls) == 1
    assert "JSON" in calls[0][1] or "损坏" in calls[0][1]


def test_save_project_oserror_shows_error_and_returns_none(qtbot, tmp_path: Path, monkeypatch):
    """OSError on save is reported and does not claim success."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    target = tmp_path / "p.paleo.json"
    window.project_path = target

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_show_project_error", lambda title, msg: calls.append((title, msg)))

    from paleo_workbench.project import manager as mgr_mod

    def boom(self, project):
        raise OSError("disk full")

    monkeypatch.setattr(mgr_mod.ProjectManager, "save", boom)

    result = window.save_project()
    assert result is None
    assert len(calls) == 1
    assert "保存" in calls[0][0]
    assert "disk full" in calls[0][1]


def test_project_menu_signals_wired_after_refresh(qtbot, monkeypatch):
    """After a shell rebuild the project-menu signals still reach handlers."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    counter = {"n": 0}
    monkeypatch.setattr(
        window, "_on_new_project", lambda: counter.__setitem__("n", counter["n"] + 1)
    )

    # Force a shell rebuild — _refresh_shell must re-wire the new menu bar.
    window.new_project("After Refresh")

    # Emit on the freshly built menu bar; the patched handler should fire.
    window.app_shell.menu_bar.new_project_requested.emit()

    assert counter["n"] == 1


# --- Task 4: properties dialog + error handling completeness ---

def test_properties_text_contains_fields(qtbot):
    """project_properties_text() shows every field label + value, and "未保存" when no path."""
    project = ProjectDocument.new("MyProject", region="Tarim Basin")
    project.resources.extend(
        [
            ResourceItem(name="r1", path="/tmp/r1.las", type="well_log", format="LAS"),
            ResourceItem(name="r2", path="/tmp/r2.las", type="well_log", format="LAS"),
        ]
    )
    project.export_artifacts.append(
        ExportArtifact(linked_id="map_1", format="PNG", output_path="/tmp/out.png")
    )
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    window.project_path = None

    text = window.project_properties_text()

    assert "工程名称: MyProject" in text
    assert "区域: Tarim Basin" in text
    assert "工程文件: 未保存" in text
    assert "资源数量: 2" in text
    assert "导出图件: 1" in text
    assert f"显示坐标系: {project.coordinate.display_crs}" in text
    assert f"版本: {project.meta.version}" in text


def test_properties_text_shows_path_when_saved(qtbot, tmp_path: Path):
    """After save_project_as, project_properties_text() shows the path, not "未保存"."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window.project_path is None

    target = window.save_project_as(tmp_path / "saved")

    text = window.project_properties_text()
    assert str(target) in text
    assert "未保存" not in text


def test_properties_text_region_dash_when_empty(qtbot):
    """An empty region renders as the em-dash placeholder."""
    window = PaleoWorkbenchWindow(project=ProjectDocument.new("NoRegion"))
    qtbot.addWidget(window)
    assert window.project.meta.region == ""

    text = window.project_properties_text()
    assert "区域: —" in text


def test_open_handles_corrupt_json(qtbot, tmp_path: Path):
    """A file with invalid JSON returns False and leaves the active project unchanged."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    original_name = window.project.meta.name

    bad = tmp_path / "corrupt.paleo.json"
    bad.write_text("{ not json", encoding="utf-8")

    ok = window.open_project_path(bad)

    assert ok is False
    assert window.project.meta.name == original_name
    assert window.project_path is None


def test_save_as_handles_write_error(qtbot, tmp_path: Path, monkeypatch):
    """An OSError during save shows an error and returns None, leaving path unset."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_show_project_error", lambda title, msg: errors.append((title, msg)))

    from paleo_workbench.project import manager as manager_module

    def boom(self, project):
        raise OSError("disk full")

    monkeypatch.setattr(manager_module.ProjectManager, "save", boom)

    result = window.save_project_as(tmp_path / "doomed")

    assert result is None
    assert len(errors) == 1
    assert errors[0][0] == "保存工程失败"
    assert window.project_path is None


# --- Task 5: end-to-end integration smoke tests ---


def _data_page_row_count(window) -> int:
    """Visible asset rows shown on the data page's asset table."""
    data_page = window.app_shell.page_stack.widget(1)
    return data_page.asset_table.table.model().rowCount()


def test_full_new_open_save_cycle(qtbot, tmp_path: Path, monkeypatch):
    """New -> save-as -> new -> open round-trips a resource end-to-end."""
    # Window holding project A with one resource.
    project_a = ProjectDocument.new("Project A")
    project_a.resources.append(
        ResourceItem(name="r1", path="/tmp/r1.las", type="well_log", format="LAS", status="parsed")
    )
    window = PaleoWorkbenchWindow(project=project_a)
    qtbot.addWidget(window)
    assert _data_page_row_count(window) == 1

    # save-as writes a.paleo.json to the temp dir.
    saved = window.save_project_as(tmp_path / "a")
    expected = tmp_path / "a.paleo.json"
    assert saved == expected
    assert expected.exists()

    # new_project() clears the path and empties the data page.
    window.new_project()
    assert window.project_path is None
    assert _data_page_row_count(window) == 0

    # Monkeypatch the open dialog and trigger the toolbar open handler.
    monkeypatch.setattr(window, "_choose_open_project", lambda: expected)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)
    window._on_open_project()

    # Resource is visible again and the path is the saved one.
    assert window.project_path == expected
    assert _data_page_row_count(window) == 1
    assert window.project.meta.name == "Project A"
    assert any(r.name == "r1" for r in window.project.resources)


def test_window_title_updates_on_project_change(qtbot, tmp_path: Path, monkeypatch):
    """The window title tracks the active project name across new/open."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window.project.meta.name in window.windowTitle()

    window.new_project("Z")
    assert "Z" in window.windowTitle()

    # Save and reopen via the handler; title carries the loaded name.
    project = ProjectDocument.new("Loaded Name")
    target = tmp_path / "loaded.paleo.json"
    save_window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(save_window)
    save_window.save_project_as(target)

    monkeypatch.setattr(window, "_choose_open_project", lambda: target)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)
    window._on_open_project()
    assert "Loaded Name" in window.windowTitle()


def test_status_bar_updates_on_project_change(qtbot, tmp_path: Path, monkeypatch):
    """The status bar project name mirrors new/open transitions."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    window.new_project("StatusBarProj")
    status_text = window.app_shell.status_bar.status_label.text()
    assert "StatusBarProj" in status_text

    # Open a different saved project and confirm the status bar follows.
    project = ProjectDocument.new("OpenedProj")
    target = tmp_path / "opened.paleo.json"
    save_window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(save_window)
    save_window.save_project_as(target)

    monkeypatch.setattr(window, "_choose_open_project", lambda: target)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)
    window._on_open_project()
    opened_text = window.app_shell.status_bar.status_label.text()
    assert "OpenedProj" in opened_text
