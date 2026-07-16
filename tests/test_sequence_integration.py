from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import FactorMapTask, PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.workflow.service import create_compilation_run


def test_app_shell_page_four_is_sequence_framework_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(4)
    assert isinstance(page, SequenceFrameworkPage)


def test_sequence_framework_page_receives_project_stratigraphy(qtbot):
    project = ProjectDocument.new("Test")
    project.stratigraphy.target_horizon = "ZJ2"
    project.stratigraphy.systems_tract_scheme = "三级层序格架"
    project.stratigraphy.sequence_boundaries = ["SB1", "SB2"]

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(4)

    assert page.target_panel.current_target() == "ZJ2"
    assert page.boundary_table.table.rowCount() == 2
    assert page.scheme_summary.boundary_count_value.text() == "2 个"


def test_sequence_save_binds_target_to_maps_and_run(qtbot):
    project = ProjectDocument.new("Save Bind")
    project.stratigraphy.target_horizon = "H1"
    project.stratigraphy.sequence_boundaries = ["H1", "H2", "H3"]
    project.stratigraphy.systems_tract_scheme = "LST/TST/HST"
    create_compilation_run(project, "R1", "H1", "LST/TST/HST")
    project.paleomap_documents.append(
        PaleoMapDocument(name="Map", linked_target_horizon="H1")
    )
    project.factor_map_tasks.append(
        FactorMapTask(
            name="H1 厚度",
            target_horizon="H1",
            factor_type="厚度",
            method="IDW",
            status="complete",
        )
    )

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.sequence_framework_page_widget()
    assert isinstance(page, SequenceFrameworkPage)

    # Select H2 in target combo and save
    idx = page.target_panel.target_combo.findText("H2")
    assert idx >= 0
    page.target_panel.target_combo.setCurrentIndex(idx)
    assert page.save_scheme() is True

    assert window.project.stratigraphy.target_horizon == "H2"
    assert window.project.compilation_runs[-1].target_horizon == "H2"
    assert window.project.paleomap_documents[0].linked_target_horizon == "H2"
    assert window.project.factor_map_tasks[0].target_horizon == "H2"
    assert "H2" in page.scheme_summary.status_value.text()
