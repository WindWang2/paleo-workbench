"""L4 correlation link/tops attribute editor (stratigraphy correlation page).

A modal editor over the working :class:`CorrelationInterpretationDraft`:

* LINKS table — add a manual link between any two tops (comboboxes),
  remove a link (adjacency removal records the suppression so save-time
  regeneration cannot resurrect it), edit method/notes;
* TOPS table — edit the scientific metadata of a top (method, confidence
  free text, status active/tentative/rejected, notes); depth and identity
  stay owned by the canvas picks.

Every mutation goes through the copy-on-edit session ops
(:func:`add_manual_link` / :func:`remove_link` / :func:`edit_link`) — the
dialog never constructs links or bumps the draft by hand.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.workflow.correlation_session import (
    add_manual_link,
    edit_link,
    remove_link,
)
from paleo_workbench.workflow.stratigraphy_models import CorrelationMethod

logger = logging.getLogger(__name__)

_METHOD_LABELS = {
    CorrelationMethod.MANUAL: "手工",
    CorrelationMethod.DTW_ASSISTED: "DTW 辅助",
    CorrelationMethod.CURVE_SHAPE_ASSISTED: "曲线形态辅助",
    CorrelationMethod.IMPORTED: "导入",
}
_STATUS_LABELS = ("active", "tentative", "rejected")


def _method_label(method) -> str:
    try:
        return _METHOD_LABELS.get(CorrelationMethod(method), str(method))
    except ValueError:
        return str(method)


class CorrelationLinkEditor(QDialog):
    def __init__(self, draft, parent: QWidget | None = None):
        super().__init__(parent)
        self._draft = draft
        self.setWindowTitle("相关链接与顶点属性编辑")
        self.resize(760, 520)
        root = QVBoxLayout(self)
        # NOTE: _top_by_id is REBUILT in _rebuild_tables — a DTW worker can
        # finish while this modal dialog is open and extend the draft's tops
        # through the nested event loop (review R3-M3).
        self._top_by_id = {t.id: t for t in draft.payload.tops}

        root.addWidget(QLabel("井间相关链接（保存后进入解释版本）"))
        self.link_table = QTableWidget(0, 5)
        self.link_table.setHorizontalHeaderLabels(
            ["层位", "井 A → 井 B", "方法", "邻接", "备注"]
        )
        self.link_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.link_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.link_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.link_table, 2)

        link_buttons = QHBoxLayout()
        add_btn = QPushButton("新增链接…")
        add_btn.clicked.connect(self._add_link)
        remove_btn = QPushButton("删除链接")
        remove_btn.clicked.connect(self._remove_link)
        method_btn = QPushButton("改方法/备注…")
        method_btn.clicked.connect(self._edit_link)
        link_buttons.addWidget(add_btn)
        link_buttons.addWidget(remove_btn)
        link_buttons.addWidget(method_btn)
        link_buttons.addStretch(1)
        root.addLayout(link_buttons)

        root.addWidget(QLabel("顶点属性（方法 / 置信度 / 状态 / 备注）"))
        self.top_table = QTableWidget(0, 5)
        self.top_table.setHorizontalHeaderLabels(
            ["井", "层位", "深度", "方法", "置信度"]
        )
        self.top_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.top_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.top_table, 2)

        top_buttons = QHBoxLayout()
        top_btn = QPushButton("编辑顶点属性…")
        top_btn.clicked.connect(self._edit_top)
        top_buttons.addWidget(top_btn)
        top_buttons.addStretch(1)
        root.addLayout(top_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(
            lambda _b: self.reject()
            if buttons.standardButton(_b) == QDialogButtonBox.StandardButton.Close
            else None
        )
        root.addWidget(buttons)

        self._rebuild_tables()

    # -- tables ----------------------------------------------------------------

    def _rebuild_tables(self) -> None:
        self._top_by_id = {t.id: t for t in self._draft.payload.tops}
        top_by_id = self._top_by_id
        links = sorted(
            self._draft.payload.links,
            key=lambda ln: (ln.top_a_id, ln.top_b_id, ln.id),
        )
        self.link_table.setRowCount(len(links))
        for row, ln in enumerate(links):
            a = top_by_id.get(ln.top_a_id)
            b = top_by_id.get(ln.top_b_id)
            marker = a.marker if a else "?"
            pair = f"{(a.well_name if a else '?')} → {(b.well_name if b else '?')}"
            values = [
                marker,
                pair,
                _method_label(ln.method),
                "是" if ln.adjacent_only else "否",
                ln.notes,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.ItemDataRole.UserRole, ln.id)
                self.link_table.setItem(row, col, item)

        tops = sorted(
            self._draft.payload.tops,
            key=lambda t: (t.well_name, t.marker, t.depth),
        )
        self.top_table.setRowCount(len(tops))
        for row, top in enumerate(tops):
            values = [
                top.well_name,
                top.marker,
                f"{top.depth:.2f} {top.depth_domain.value}",
                _method_label(top.method),
                top.confidence or "—",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, top.id)
                self.top_table.setItem(row, col, item)

    def _selected_link_id(self) -> str | None:
        item = self.link_table.item(self.link_table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_top_id(self) -> str | None:
        item = self.top_table.item(self.top_table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # -- link operations ---------------------------------------------------------

    def _add_link(self) -> None:
        tops = sorted(
            self._draft.payload.tops,
            key=lambda t: (t.well_name, t.marker),
        )
        if len(tops) < 2:
            QMessageBox.information(self, "新增链接", "至少需要两个顶点。")
            return
        # Unique labels map directly to the top objects: two tops can share
        # well+marker (+depth), and labels.index() would silently pick the
        # first (review R1-M6).
        labels = {f"{t.well_name} · {t.marker} ({t.depth:.1f}) #{i}": t
                  for i, t in enumerate(tops)}
        label_list = list(labels)
        a_label, ok_a = QInputDialog.getItem(
            self, "新增链接", "顶点 A", label_list, 0, editable=False
        )
        if not ok_a:
            return
        b_label, ok_b = QInputDialog.getItem(
            self, "新增链接", "顶点 B", label_list, 1, editable=False
        )
        if not ok_b:
            return
        top_a = labels[a_label]
        top_b = labels[b_label]
        try:
            add_manual_link(self._draft, top_a.id, top_b.id)
        except ValueError as exc:
            QMessageBox.warning(self, "新增链接", str(exc))
            return
        self._rebuild_tables()

    def _remove_link(self) -> None:
        link_id = self._selected_link_id()
        if link_id is None:
            return
        remove_link(self._draft, link_id)
        self._rebuild_tables()

    def _edit_link(self) -> None:
        link_id = self._selected_link_id()
        if link_id is None:
            return
        link = next(
            (ln for ln in self._draft.payload.links if ln.id == link_id), None
        )
        if link is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("链接属性")
        from PySide6.QtWidgets import QFormLayout

        form = QFormLayout(dialog)
        method_combo = QComboBox()
        for method in CorrelationMethod:
            method_combo.addItem(_method_label(method), method)
        method_combo.setCurrentText(_method_label(link.method))
        notes_edit = QLineEdit(link.notes)
        form.addRow("方法", method_combo)
        form.addRow("备注", notes_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edit_link(
            self._draft,
            link_id,
            method=method_combo.currentData(),
            notes=notes_edit.text().strip(),
        )
        self._rebuild_tables()

    # -- top attribute editing ---------------------------------------------------

    def _edit_top(self) -> None:
        top_id = self._selected_top_id()
        if top_id is None:
            return
        top = self._top_by_id.get(top_id)
        if top is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"顶点属性 · {top.well_name} {top.marker}")
        from PySide6.QtWidgets import QFormLayout

        form = QFormLayout(dialog)
        method_combo = QComboBox()
        for method in CorrelationMethod:
            method_combo.addItem(_method_label(method), method)
        method_combo.setCurrentText(_method_label(top.method))
        confidence_edit = QLineEdit(top.confidence)
        confidence_edit.setPlaceholderText("自由文本（如 高 / 中 / 0.8）")
        status_combo = QComboBox()
        for status in _STATUS_LABELS:
            status_combo.addItem(status)
        status_combo.setCurrentText(top.status)
        notes_edit = QLineEdit(top.notes)
        form.addRow("方法", method_combo)
        form.addRow("置信度", confidence_edit)
        form.addRow("状态", status_combo)
        form.addRow("备注", notes_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        top.method = method_combo.currentData()
        top.confidence = confidence_edit.text().strip()
        top.status = status_combo.currentText()
        top.notes = notes_edit.text().strip()
        self._draft.bump()
        self._rebuild_tables()


def run_link_editor(parent, draft, *, on_changed=None) -> None:
    """Modal editor; fires *on_changed* when the draft's generation moved."""
    generation_before = draft.generation
    dialog = CorrelationLinkEditor(draft, parent)
    dialog.exec()
    if draft.generation != generation_before and on_changed is not None:
        on_changed()
