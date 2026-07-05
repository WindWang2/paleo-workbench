from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui.pages.data_page import DataPage


def test_app_shell_page_one_is_data_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert isinstance(page, DataPage)


def test_data_page_has_resources(qtbot):
    project = ProjectDocument.new("Test")
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert isinstance(page, DataPage)
    assert page.resource_table.table.rowCount() == len(project.resources)
