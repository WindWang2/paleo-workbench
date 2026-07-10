from __future__ import annotations

from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument


def test_open_sample_project_loads_resources(qtbot, tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    (data / "井曲线").mkdir(parents=True)
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (data / "层位").mkdir()
    (data / "层位" / "C6.dat").write_text("h", encoding="utf-8")

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: data,
    )
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)

    ok = window.open_sample_project()
    assert ok is True
    assert window.project.meta.name == "惠西南样例工程"
    assert len(window.project.resources) >= 2
    assert window.project_path is None
    page = window.app_shell.data_page_widget()
    assert page is not None


def test_open_sample_project_cancel_confirm_keeps_project(qtbot, monkeypatch, tmp_path: Path):
    window = PaleoWorkbenchWindow(project=ProjectDocument.new("KeepMe"))
    qtbot.addWidget(window)
    data = tmp_path / "data"
    data.mkdir()
    (data / "A1.Las").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: data,
    )
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: False)

    ok = window.open_sample_project()
    assert ok is False
    assert window.project.meta.name == "KeepMe"


def test_open_sample_project_missing_data_returns_false(qtbot, monkeypatch, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    def _boom(explicit=None, **kwargs):
        raise FileNotFoundError("no data")
    monkeypatch.setattr("paleo_workbench.app.resolve_sample_data_root", _boom)
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)
    monkeypatch.setattr(window, "_show_project_error", lambda *a, **k: None)

    assert window.open_sample_project() is False


def test_open_sample_project_binds_demo_prediction(qtbot, tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    (data / "井曲线").mkdir(parents=True)
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (data / "层位").mkdir()
    (data / "层位" / "C6.dat").write_text("h", encoding="utf-8")

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: data,
    )
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)

    ok = window.open_sample_project()
    assert ok is True
    assert window.project.prediction_tasks
    task = window.project.prediction_tasks[-1]
    assert task.input_refs.get("well_log_resource_ids")
