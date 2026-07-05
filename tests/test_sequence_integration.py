from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage


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

    assert page.target_panel.target_value.text() == "ZJ2"
    assert page.boundary_table.table.rowCount() == 2
    assert page.scheme_summary.boundary_count_value.text() == "2 个"
