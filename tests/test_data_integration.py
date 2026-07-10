from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage


def test_app_shell_page_one_is_data_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert isinstance(page, DataPage)


def test_data_page_receives_resources_and_artifacts(qtbot):
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    )
    project.export_artifacts.append(
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    )
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert page.asset_table.table.model().rowCount() == 2
