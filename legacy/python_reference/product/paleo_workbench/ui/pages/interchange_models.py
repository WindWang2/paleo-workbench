"""UI integration models (I19): thin, headless-testable Qt table models.

These models expose preflight reports, batch results and package plans to
dialogs/pages. They are pure model layer — no dialogs, no global QSS — so a
page can consume them with the existing design-system widgets and tests can
drive them with an offscreen QApplication.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from paleo_workbench.interchange.batch import BatchResult
from paleo_workbench.interchange.contracts import VerificationState
from paleo_workbench.interchange.package.builder import PackagePlan


class PreflightIssueModel(QAbstractTableModel):
    """Issues of one preflight report, worst first."""

    _HEADERS = ("级别", "代码", "说明")
    _SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
    _SEVERITY_LABELS = {"error": "错误", "warning": "警告", "info": "提示"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, str, str]] = []
        self._ok = True
        self._recommendation = ""

    def set_report(self, report) -> None:
        self.beginResetModel()
        rows = [
            (self._SEVERITY_LABELS.get(issue.severity, issue.severity),
             issue.code, issue.message)
            for issue in report.issues
        ]
        rows.sort(key=lambda r: self._SEVERITY_ORDER.get(
            {v: k for k, v in self._SEVERITY_LABELS.items()}.get(r[0], "info"), 9
        ))
        self._rows = rows
        self._ok = report.ok
        self._recommendation = report.recommendation
        self.endResetModel()

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def recommendation(self) -> str:
        return self._recommendation

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        return self._rows[index.row()][index.column()]


class BatchResultModel(QAbstractTableModel):
    """Per-item outcomes of a batch conversion."""

    _HEADERS = ("源文件", "输出", "状态", "校验", "耗时(ms)", "说明")
    _STATUS_LABELS = {
        "converted": "已转换",
        "failed": "失败",
        "skipped": "跳过",
        "cancelled": "已取消",
        "pending": "等待",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._summary: dict = {}

    def set_result(self, result: BatchResult) -> None:
        self.beginResetModel()
        self._rows = [r.to_dict() for r in result.results]
        self._summary = result.summary()
        self.endResetModel()

    @property
    def summary(self) -> dict:
        return dict(self._summary)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        if index.column() == 2:
            return self._STATUS_LABELS.get(row["status"], row["status"])
        if index.column() == 3:
            return row.get("verification_state") or "—"
        return row.get(self._field_for(index.column()), "")


    @classmethod
    def _field_for(cls, column: int) -> str:
        return ("source", "target", "status", "verification_state",
                "duration_ms", "detail")[column]


class PackagePlanModel(QAbstractTableModel):
    """What a package build will include / exclude — nothing silent."""

    _HEADERS = ("名称", "阶段", "状态", "大小(B)", "说明")
    _STATUS_LABELS = {
        "included": "打包",
        "external": "外部引用",
        "missing": "缺失",
        "stale": "内容可疑",
        "excluded": "排除",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list = []
        self._summary: dict = {}

    def set_plan(self, plan: PackagePlan) -> None:
        self.beginResetModel()
        self._items = list(plan.items)
        self._summary = plan.summary()
        self.endResetModel()

    @property
    def summary(self) -> dict:
        return dict(self._summary)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        item = self._items[index.row()]
        if index.column() == 0:
            return Path(item.path).name
        if index.column() == 1:
            return item.stage
        if index.column() == 2:
            return self._STATUS_LABELS.get(item.status, item.status)
        if index.column() == 3:
            return item.size_bytes
        return item.detail
