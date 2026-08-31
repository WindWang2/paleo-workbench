from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QSplitter

from paleo_workbench.ui.layout_persistence import LayoutPersistence
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


def test_review_export_page_uses_resizable_splitter(qtbot):
    page = ReviewExportPage()
    qtbot.addWidget(page)

    splitter = page.content_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.objectName() == "ReviewExportSplitter"
    assert splitter.count() == 2
    assert splitter.widget(0) is page.qc_table
    assert splitter.widget(1) is page.result_summary
    # The summary keeps its design width as a resizable minimum.
    assert page.result_summary.minimumWidth() < page.result_summary.maximumWidth()

    page.resize(1280, 800)
    page.show()
    before = splitter.sizes()
    page.resize(1680, 800)
    QApplication.processEvents()
    after = splitter.sizes()

    # 质检表 stays the stretchy center and absorbs the extra width.
    assert before[0] > before[1]
    assert after[0] - before[0] > after[1] - before[1]


def test_review_export_page_summary_float_round_trip(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    page = ReviewExportPage(persistence=LayoutPersistence(settings))
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()

    key = "review:summary"
    assert page.float_controller.toggle(key) is True
    floating = page.float_controller.floating_panel(key)
    qtbot.addWidget(floating)
    assert page.result_summary.parentWidget() is floating.content_host
    # The QC table never floats — no entry point exists for it.
    assert "review:qc_table" not in page._floatable
    assert page.qc_table.parentWidget() is page.content_splitter

    assert page.float_controller.toggle(key) is True
    assert page.content_splitter.widget(1) is page.result_summary


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
