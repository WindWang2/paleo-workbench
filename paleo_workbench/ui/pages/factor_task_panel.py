from __future__ import annotations

from collections import Counter

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
            layout.setContentsMargins(4, 6, 4, 6)
            layout.setSpacing(8)

            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            text_box.setContentsMargins(0, 0, 0, 0)
            self.name_label = QLabel(task.name)
            self.name_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
                " border: none; background: transparent;"
            )
            grid = task.parameters.get("grid", "50m") if task.parameters else "50m"
            self.sub_label = QLabel(f"{task.method} · {grid}")
            self.sub_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
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
                f"color: {status_color}; font-size: 11px; font-weight: 500;"
                " border: none; background: transparent;"
            )
            layout.addWidget(self.status_badge)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FactorTaskPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.horizon_label = QLabel("层位: —")
        self.horizon_label.setObjectName("MapDockTitle")
        header.addWidget(self.horizon_label)
        header.addStretch()
        self.method_combo = QComboBox()
        self.method_combo.addItems(tokens.INTERPOLATION_METHODS)
        header.addWidget(self.method_combo)
        outer.addLayout(header)

        self.generate_btn = QPushButton("批量生成单因素图")
        self.generate_btn.setObjectName("PrimaryButton")
        outer.addWidget(self.generate_btn)

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
