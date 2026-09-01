from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui.pages.home_page import HomePage


def test_app_shell_data_hub_hosts_home_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.hub_data.page("overview")
    assert isinstance(page, HomePage)
    assert window.app_shell.page_stack.currentIndex() == 0


def test_home_page_has_workflow_data(qtbot):
    project = ProjectDocument.new("Test Project")
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.hub_data.page("overview")
    assert isinstance(page, HomePage)
    # UI v2: workflow state lives in the module-relationship diagram, not a
    # separate progress strip.
    assert not hasattr(page, "workflow_progress")
    assert page.relationship_widget is not None
