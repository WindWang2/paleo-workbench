from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.pages.qc_issue_table import QCIssueTable
from paleo_workbench.ui.pages.result_summary import ResultSummary
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage


def test_review_export_page_assembles_three_widgets(qtbot):
    page = ReviewExportPage()
    qtbot.addWidget(page)
    assert page.objectName() == "ReviewExportPage"
    assert isinstance(page.action_header, ActionHeader)
    assert isinstance(page.qc_table, QCIssueTable)
    assert isinstance(page.result_summary, ResultSummary)


def test_review_export_page_update_delegates(qtbot):
    page = ReviewExportPage()
    qtbot.addWidget(page)

    calls = {"action_header": [], "qc_table": [], "result_summary": []}

    page.action_header.update_state = lambda *a: calls["action_header"].append(a)
    page.qc_table.update_state = lambda *a: calls["qc_table"].append(a)
    page.result_summary.update_state = lambda *a: calls["result_summary"].append(a)

    reports = [{"id": 1}]
    map_documents = [{"id": 9}]
    artifacts = [{"id": 5}]
    page.update_state(reports, map_documents, artifacts)

    assert calls["action_header"] == [(reports, map_documents)]
    assert calls["qc_table"] == [(reports,)]
    assert calls["result_summary"] == [(reports, artifacts)]
