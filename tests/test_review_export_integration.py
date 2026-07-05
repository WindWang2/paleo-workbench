from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.qc import run_basic_qc


def test_app_shell_page_eight_is_review_export_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(8)
    assert isinstance(page, ReviewExportPage)


def test_review_export_page_receives_data(qtbot):
    project = ProjectDocument.new("Test")
    doc = PaleoMapDocument(name="ZJ-2 图", linked_target_horizon="ZJ-2")
    project.paleomap_documents.append(doc)
    run_basic_qc(project, doc.id)
    record_export(
        project,
        linked_id=doc.id,
        output_path="/tmp/map.tif",
        fmt="GeoTIFF",
        source_task_ids=[],
    )

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(8)
    assert isinstance(page, ReviewExportPage)
    assert page.qc_table.table.rowCount() > 0
