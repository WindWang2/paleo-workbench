from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.qc_helpers import derive_rule_result


class ResultSummary(QFrame):
    """Right-hand summary panel for the QC review page.

    Shows pass/warning/error counts derived from a QualityReport, an advisory
    line, and the list of exported artifacts.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("检查结果输出")
        self.title_label.setObjectName("MapDockTitle")
        layout.addWidget(self.title_label)

        self.pass_label = QLabel("通过项: 0")
        self._color_label(self.pass_label, tokens.SUCCESS)
        layout.addWidget(self.pass_label)

        self.warning_label = QLabel("警告项: 0")
        self._color_label(self.warning_label, tokens.WARNING)
        layout.addWidget(self.warning_label)

        self.error_label = QLabel("待处理项: 0")
        self._color_label(self.error_label, tokens.ERROR_RED)
        layout.addWidget(self.error_label)

        self.advisory_label = QLabel("全部通过，可输出成果")
        self._color_label(self.advisory_label, tokens.SUCCESS)
        layout.addWidget(self.advisory_label)

        # Divider
        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.Shape.HLine)
        self.divider.setStyleSheet(
            f"background: {tokens.BORDER}; border: none; max-height: 1px;"
        )
        layout.addWidget(self.divider)

        self.export_title = QLabel("导出图件")
        self._style_label(self.export_title, tokens.TEXT_PRIMARY, "13px", 600)
        layout.addWidget(self.export_title)

        self.export_container = QWidget()
        self.export_container.setStyleSheet("border: none; background: transparent;")
        self.export_layout = QVBoxLayout(self.export_container)
        self.export_layout.setContentsMargins(0, 0, 0, 0)
        self.export_layout.setSpacing(tokens.SPACE_1)
        layout.addWidget(self.export_container)

        layout.addStretch()

        # Initialize to empty state
        self.update_state([], [])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _style_label(label: QLabel, color: str, size: str, weight: int) -> None:
        label.setStyleSheet(
            f"color: {color}; font-size: {size}; font-weight: {weight};"
            " border: none; background: transparent;"
        )

    @staticmethod
    def _color_label(label: QLabel, color: str) -> None:
        label.setStyleSheet(
            f"color: {color}; font-size: {tokens.FONT_SIZE_BASE};"
            " border: none; background: transparent;"
        )

    def _clear_export(self) -> None:
        while self.export_layout.count():
            item = self.export_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_state(self, reports: list, artifacts: list) -> None:
        # Count pass / warning / error distinct rules, error taking precedence.
        pass_count = warning_count = error_count = 0
        if reports:
            report = reports[0]
            for rule in report.rules:
                severity, _text, _color = derive_rule_result(rule, report.issues)
                if severity == "error":
                    error_count += 1
                elif severity == "warning":
                    warning_count += 1
                else:
                    pass_count += 1

        self.pass_label.setText(f"通过项: {pass_count}")
        self.warning_label.setText(f"警告项: {warning_count}")
        self.error_label.setText(f"待处理项: {error_count}")

        if error_count > 0:
            self.advisory_label.setText("建议先处理待处理项后再输出成果")
            self._color_label(self.advisory_label, tokens.ERROR_RED)
        else:
            self.advisory_label.setText("全部通过，可输出成果")
            self._color_label(self.advisory_label, tokens.SUCCESS)

        # Rebuild export list
        self._clear_export()
        if not artifacts:
            empty = QLabel("暂无导出图件")
            empty.setObjectName("EmptyStateLabel")
            self.export_layout.addWidget(empty)
        else:
            for artifact in artifacts:
                row = QLabel(f"• {artifact.format} — {artifact.output_path}")
                self._color_label(row, tokens.TEXT_PRIMARY)
                self.export_layout.addWidget(row)
