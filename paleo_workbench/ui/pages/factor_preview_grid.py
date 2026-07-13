from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens


class FactorPreviewGrid(QWidget):
    """Center panel grid of completed factor map preview cards."""

    class FactorPreviewCard(QFrame):
        """A single preview card for one completed factor map."""

        def __init__(self, task, parent=None):
            super().__init__(parent)
            self.setObjectName("FactorPreviewCard")
            self.setMinimumSize(160, 100)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
            layout.setSpacing(tokens.SPACE_2)

            title = task.factor_type or task.name
            self.name_label = QLabel(title)
            self.name_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
                " border: none; background: transparent;"
            )
            layout.addWidget(self.name_label)

            metrics = task.quality_metrics or {}
            self.range_label = QLabel(str(metrics.get("range", "—")))
            self.range_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 12px;"
                " border: none; background: transparent;"
            )
            layout.addWidget(self.range_label)

            r_squared = metrics.get("r_squared")
            self.rsquared_label = QLabel("")
            self.rsquared_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
                " border: none; background: transparent;"
            )
            if r_squared is not None:
                self.rsquared_label.setText(f"R² {r_squared}")
                self.rsquared_label.show()
            else:
                self.rsquared_label.hide()
            layout.addWidget(self.rsquared_label)
            layout.addStretch()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FactorPreviewGrid")
        self.setStyleSheet(f"QWidget#FactorPreviewGrid {{ background: transparent; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        self.header_label = QLabel("单因素图集")
        self.header_label.setObjectName("MapDockTitle")
        outer.addWidget(self.header_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(tokens.SPACE_3)
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.scroll.setWidget(self.grid_container)
        outer.addWidget(self.scroll, 1)

        self._empty_label: QLabel | None = None

    def _clear_grid(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._empty_label = None

    def update_state(self, tasks: list) -> None:
        completed = [t for t in tasks if t.status == "complete"]

        self._clear_grid()
        if not completed:
            self.header_label.setText("单因素图集")
            self._empty_label = QLabel("暂无已生成的单因素图")
            self._empty_label.setObjectName("EmptyStateLabel")
            self.grid_layout.addWidget(self._empty_label, 0, 0, 1, 2)
            return

        first = completed[0]
        horizon = first.target_horizon
        method = first.method or "—"
        grid_value = (first.quality_metrics or {}).get("grid", "50×50")
        self.header_label.setText(
            f"{horizon} 单因素图集（{method}插值 · 网格 {grid_value} m）"
        )

        cols = 2
        for index, task in enumerate(completed):
            card = FactorPreviewGrid.FactorPreviewCard(task)
            row = index // cols
            col = index % cols
            self.grid_layout.addWidget(card, row, col)
