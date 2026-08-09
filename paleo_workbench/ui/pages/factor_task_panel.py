from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens


class FactorTaskPanel(QFrame):
    """Left sidebar listing factor map tasks for the Preparation page."""

    generate_requested = Signal(str)  # interpolation method label
    contour_draft_requested = Signal()  # build ContourDraft from completed grids

    class Row(QWidget):
        """A single factor map task row."""

        def __init__(self, task, parent=None):
            super().__init__(parent)
            self.setObjectName("FactorTaskRow")
            self.setStyleSheet(
                f"QWidget#FactorTaskRow {{ background: {tokens.BG_SIDEBAR};"
                f" border-bottom: 1px solid {tokens.BORDER_LIGHT}; }}"
            )
            layout = QHBoxLayout(self)
            layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2)
            layout.setSpacing(tokens.SPACE_2)

            text_box = QVBoxLayout()
            text_box.setSpacing(tokens.SPACE_1)
            text_box.setContentsMargins(0, 0, 0, 0)
            self.name_label = QLabel(task.name)
            self.name_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
                " border: none; background: transparent;"
            )
            grid = task.parameters.get("grid", "50m") if task.parameters else "50m"
            self.sub_label = QLabel(f"{task.method} · {grid}")
            self.sub_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
                " border: none; background: transparent;"
            )
            text_box.addWidget(self.name_label)
            text_box.addWidget(self.sub_label)
            wrap = QWidget()
            wrap.setLayout(text_box)
            wrap.setStyleSheet("border: none; background: transparent;")
            layout.addWidget(wrap, 1)

            status_key = tokens.TASK_STATUS_LABELS.get(task.status, task.status)
            status_color = tokens.TASK_STATUS_COLORS.get(
                task.status, tokens.TEXT_SECONDARY
            )
            self.status_badge = QLabel(status_key)
            self.status_badge.setStyleSheet(
                f"color: {status_color}; font-size: {tokens.FONT_SIZE_STATUS}; font-weight: 500;"
                " border: none; background: transparent;"
            )
            layout.addWidget(self.status_badge)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FactorTaskPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        header = QHBoxLayout()
        header.setSpacing(tokens.SPACE_2)
        self.horizon_label = QLabel("层位: —")
        self.horizon_label.setObjectName("MapDockTitle")
        header.addWidget(self.horizon_label)
        header.addStretch()
        self.method_combo = QComboBox()
        self.method_combo.addItems(tokens.INTERPOLATION_METHODS)
        tooltips = getattr(tokens, "INTERPOLATION_METHOD_TOOLTIPS", {}) or {}
        for i, label in enumerate(tokens.INTERPOLATION_METHODS):
            tip = tooltips.get(label)
            if tip:
                self.method_combo.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
        default_tip = tooltips.get(tokens.INTERPOLATION_METHODS[0], "")
        self.method_combo.setToolTip(
            default_tip
            or "插值方法（克里金为真实变差函数普通克里金，含克里金方差）"
        )
        self.method_combo.currentTextChanged.connect(self._sync_method_tooltip)
        header.addWidget(self.method_combo)
        outer.addLayout(header)

        self.generate_btn = QPushButton("批量生成单因素图")
        self.generate_btn.setObjectName("PrimaryButton")
        self.generate_btn.clicked.connect(self._emit_generate)
        outer.addWidget(self.generate_btn)

        self.contour_draft_btn = QPushButton("生成等值线初稿")
        self.contour_draft_btn.setObjectName("SecondaryButton")
        self.contour_draft_btn.setToolTip(
            "从已完成的单因素网格提取等值线 ContourDraft，并推送到编图 line 图层"
        )
        self.contour_draft_btn.clicked.connect(self.contour_draft_requested.emit)
        outer.addWidget(self.contour_draft_btn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.task_container = QWidget()
        self.task_container.setStyleSheet("background: transparent;")
        self.task_layout = QVBoxLayout(self.task_container)
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(0)
        self.task_layout.addStretch()
        self.scroll.setWidget(self.task_container)
        outer.addWidget(self.scroll, 1)

        self.summary_label = QLabel("已制备 0 / 0 个单因素图")
        self.summary_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        outer.addWidget(self.summary_label)

    def _sync_method_tooltip(self, text: str) -> None:
        tooltips = getattr(tokens, "INTERPOLATION_METHOD_TOOLTIPS", {}) or {}
        self.method_combo.setToolTip(
            tooltips.get(text)
            or "插值方法（克里金为真实变差函数普通克里金，含克里金方差）"
        )

    def _emit_generate(self) -> None:
        self.generate_requested.emit(self.method_combo.currentText() or "IDW")

    def selected_method(self) -> str:
        return self.method_combo.currentText() or "IDW"

    def _clear_rows(self) -> None:
        while self.task_layout.count() > 1:
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def update_state(self, tasks: list) -> None:
        tasks = list(tasks)
        if tasks:
            self.horizon_label.setText(f"层位: {tasks[0].target_horizon}")
            methods = [t.method for t in tasks if t.method]
            common = Counter(methods).most_common(1)[0][0] if methods else None
            if common is not None:
                idx = self.method_combo.findText(common)
                if idx >= 0:
                    self.method_combo.setCurrentIndex(idx)
                else:
                    self.method_combo.setCurrentIndex(0)
            else:
                self.method_combo.setCurrentIndex(0)
        else:
            self.horizon_label.setText("层位: —")
            self.method_combo.setCurrentIndex(0)

        self._clear_rows()
        insert_at = self.task_layout.count() - 1  # before the stretch
        for task in tasks:
            row = FactorTaskPanel.Row(task)
            self.task_layout.insertWidget(insert_at, row)
            insert_at += 1

        total = len(tasks)
        complete = sum(1 for t in tasks if t.status == "complete")
        self.summary_label.setText(f"已制备 {complete} / {total} 个单因素图")
