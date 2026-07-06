"""Tests for PaleoWorkbenchWindow project lifecycle (new/open/save/save-as)."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument, ResourceItem


def test_new_project_clears_path(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    # Simulate a previously-saved project.
    window.project_path = Path("/tmp/saved.paleo.json")

    window.new_project()

    assert window.project_path is None
    assert "Untitled" in window.windowTitle()


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
    data_page = window.app_shell.page_stack.widget(1)
    assert any(r.name == "r1" for r in window.project.resources)
    # Sanity: data page model holds at least the one resource.
    if hasattr(data_page, "table") and hasattr(data_page.table, "model"):
        assert data_page.table.model().rowCount() >= 1


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

    window._on_open_project()

    assert len(calls) == 1
    assert window.project.meta.name == original_name
    assert window.project_path is None


def test_toolbar_signals_wired_after_refresh(qtbot, monkeypatch):
    """After a shell rebuild the toolbar signals still reach handlers."""
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    counter = {"n": 0}
    monkeypatch.setattr(
        window, "_on_new_project", lambda: counter.__setitem__("n", counter["n"] + 1)
    )

    # Force a shell rebuild — _refresh_shell must re-wire the *new* toolbar.
    window.new_project("After Refresh")

    # Emit on the freshly built toolbar; the patched handler should fire.
    window.app_shell.header_toolbar.new_project_requested.emit()

    assert counter["n"] >= 1
