from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_app_shell_page_seven_is_mapping_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(7)
    assert isinstance(page, MappingPage)


def test_mapping_page_receives_project_map_documents(qtbot):
    project = ProjectDocument.new("Test")
    doc = PaleoMapDocument(
        name="ZJ2 Map",
        linked_target_horizon="ZJ2",
        facies_polygons=[{"type": "Feature", "properties": {"facies": "三角洲"}}],
        well_overlays=[{"name": "HZ26-7", "lng": 115.0, "lat": 25.0}],
    )
    project.paleomap_documents.append(doc)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(7)

    assert page.document_panel.name_value.text() == "ZJ2 Map"
    assert page.canvas_panel.canvas._period_name == "ZJ2"
    assert page.chrome_panel.title_value.text() == "ZJ2 Map"
