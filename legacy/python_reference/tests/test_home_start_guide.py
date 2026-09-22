from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.service import home_workflow_steps, dashboard_state


def test_home_start_guide_visibility_empty(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    doc = ProjectDocument.new("Empty")
    state = dashboard_state(doc)
    steps = home_workflow_steps(doc)
    page.update_state(state, steps, project=doc)
    # process events for visibility
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()

    assert page.start_guide_card.isVisible() is True
    assert page.onboarding_report_card.isVisible() is False


def test_home_start_guide_buttons_emit(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)

    emitted_new = []
    emitted_open = []
    emitted_sample = []
    page.new_project_requested.connect(lambda: emitted_new.append(1))
    page.open_project_requested.connect(lambda: emitted_open.append(1))
    page.open_sample_requested.connect(lambda: emitted_sample.append(1))

    page.start_guide_card.new_project_button.click()
    page.start_guide_card.open_project_button.click()
    page.start_guide_card.open_sample_button.click()

    assert emitted_new == [1]
    assert emitted_open == [1]
    assert emitted_sample == [1]


def test_home_onboarding_report_visible_with_data(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage
    from paleo_workbench.project.models import ResourceItem

    page = HomePage()
    qtbot.addWidget(page)
    page.show()

    doc = ProjectDocument.new("WithReport")
    doc.resources.append(ResourceItem(name="r1", path="/tmp/a.las", type="well_log", format="las"))
    doc.onboarding_report = {
        "source_folder": "/tmp/src",
        "imported_count": 5,
        "by_type": {"测井": 5, "层位": 3},
        "wells_total": 4,
        "wells_with_coords": 3,
        "surveys": 1,
        "entities": 2,
        "extent": [0, 10.123, 0, 20.456],
        "issues": [],
        "warnings": [],
    }
    state = dashboard_state(doc)
    steps = home_workflow_steps(doc)
    page.update_state(state, steps, project=doc)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()

    assert page.start_guide_card.isVisible() is False
    assert page.onboarding_report_card.isVisible() is True
    assert "井 4 口" in page.onboarding_report_card.report_summary_label.text()
    assert "有坐标" in page.onboarding_report_card.report_summary_label.text()


def test_create_project_from_document(tmp_path: Path, qtbot, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    controller = window.project_controller

    # ensure session gate passes (no workers)
    monkeypatch.setattr(window, "_show_project_error", lambda *a, **k: None)

    doc = ProjectDocument.new("DemoProj")
    doc.onboarding_report = {"imported_count": 1}
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()

    ok = controller.create_project_from_document(doc, intermediate)
    assert ok is True
    expected = intermediate / "DemoProj.paleo.json"
    assert expected.is_file()
    assert window.project_path == expected
    assert window.project is doc


def test_create_project_from_document_target_exists(tmp_path: Path, qtbot, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    controller = window.project_controller

    shown = []
    monkeypatch.setattr(window, "_show_project_error", lambda t, m: shown.append((t, m)))

    doc = ProjectDocument.new("ExistsProj")
    intermediate = tmp_path / "inter"
    intermediate.mkdir()
    target = intermediate / "ExistsProj.paleo.json"
    target.write_text("{}", encoding="utf-8")

    ok = controller.create_project_from_document(doc, intermediate)
    assert ok is False
    assert shown  # error shown
