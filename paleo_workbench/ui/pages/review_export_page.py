from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.pages.qc_issue_table import QCIssueTable
from paleo_workbench.ui.pages.result_summary import ResultSummary


class ReviewExportPage(QWidget):
    """Display-only 成图审核 page: assembles action header, QC issue table, result summary."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReviewExportPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)

        self.action_header = ActionHeader()
        outer.addWidget(self.action_header, 0)

        content = QHBoxLayout()
        content.setSpacing(16)

        self.qc_table = QCIssueTable()
        content.addWidget(self.qc_table, 1)

        self.result_summary = ResultSummary()
        content.addWidget(self.result_summary, 0)

        outer.addLayout(content, 1)

    def update_state(self, reports: list, map_documents: list, artifacts: list) -> None:
        self.action_header.update_state(reports, map_documents)
        self.qc_table.update_state(reports)
        self.result_summary.update_state(reports, artifacts)
