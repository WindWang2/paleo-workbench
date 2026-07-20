from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from paleo_workbench.tokens import BORDER, PRIMARY, SPACE_2, TEXT_SECONDARY
from paleo_workbench.ui.pages.table_preview_widget import TablePreviewWidget


class SummaryTablePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11.5px;")
        layout.addWidget(self.message_label)

        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                border-radius: 6px;
                background: #ffffff;
            }}
            QTabBar::tab {{
                background: #f8fafc;
                color: #64748b;
                border: 1px solid {BORDER};
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 6px 14px;
                margin-right: 3px;
                font-weight: 500;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background: #ffffff;
                color: {PRIMARY};
                font-weight: 600;
                border-bottom: 2px solid {PRIMARY};
            }}
            QTabBar::tab:hover:!selected {{
                background: #f1f5f9;
                color: #334155;
            }}
            """
        )

        # Tab 1: Curve definitions and metadata summary
        self.info_tab = QWidget()
        info_layout = QVBoxLayout(self.info_tab)
        info_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        info_layout.setSpacing(SPACE_2)

        # Stat cards bar
        self.stat_bar = QWidget()
        stat_layout = QHBoxLayout(self.stat_bar)
        stat_layout.setContentsMargins(2, 2, 2, 4)
        stat_layout.setSpacing(8)

        self.chip_well = self._create_stat_chip("📌 井名", "—", "#1e40af", "#eff6ff")
        self.chip_curves = self._create_stat_chip("📊 曲线数", "0 条", "#0f766e", "#f0fdf4")
        self.chip_samples = self._create_stat_chip("📏 采样点", "0 点", "#6b21a8", "#faf5ff")

        stat_layout.addWidget(self.chip_well)
        stat_layout.addWidget(self.chip_curves)
        stat_layout.addWidget(self.chip_samples)
        stat_layout.addStretch()

        info_layout.addWidget(self.stat_bar)

        self.summary_table = TablePreviewWidget()
        self.detail_table = TablePreviewWidget()

        info_layout.addWidget(self.summary_table)
        info_layout.addWidget(self.detail_table, 1)

        self.tabs.addTab(self.info_tab, "曲线定义与元数据")

        # Tab 2: Curve data rows preview
        self.data_tab = QWidget()
        data_layout = QVBoxLayout(self.data_tab)
        data_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        data_layout.setSpacing(SPACE_2)

        self.data_table = TablePreviewWidget()
        data_layout.addWidget(self.data_table, 1)

        self.tabs.addTab(self.data_tab, "数据内容")

        layout.addWidget(self.tabs, 1)

    @staticmethod
    def _create_stat_chip(title: str, default_val: str, fg_color: str, bg_color: str) -> QWidget:
        box = QWidget()
        box.setStyleSheet(
            f"""
            QWidget {{
                background-color: {bg_color};
                border: 1px solid {fg_color}33;
                border-radius: 6px;
            }}
            """
        )
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 10, 4)
        lay.setSpacing(6)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"color: {fg_color}; font-size: 11px; font-weight: 500;")
        val_lbl = QLabel(default_val)
        val_lbl.setObjectName("chip_val")
        val_lbl.setStyleSheet(f"color: {fg_color}; font-size: 12px; font-weight: 700;")

        lay.addWidget(t_lbl)
        lay.addWidget(val_lbl)
        return box

    def _update_chip_val(self, chip: QWidget, text: str) -> None:
        lbl = chip.findChild(QLabel, "chip_val")
        if lbl:
            lbl.setText(text)

    def _adjust_summary_height(self) -> None:
        total = self.summary_table.horizontalHeader().height() or 28
        for row in range(self.summary_table.rowCount()):
            total += self.summary_table.rowHeight(row)
        total += 6
        self.summary_table.setFixedHeight(min(max(total, 60), 120))

    def load_summary(
        self,
        summary_rows: tuple[tuple[str, str], ...],
        detail_headers: tuple[str, ...],
        detail_rows: tuple[tuple[str, ...], ...],
        message: str = "",
        data_headers: tuple[str, ...] = (),
        data_rows: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        self.message_label.setText(message)
        self.summary_table.load_table(("属性", "值"), summary_rows)
        self._adjust_summary_height()

        # Update stat chips from summary rows
        row_map = {str(k).strip(): str(v).strip() for k, v in summary_rows}
        if "井名" in row_map:
            self._update_chip_val(self.chip_well, row_map["井名"])
        if "曲线数" in row_map:
            self._update_chip_val(self.chip_curves, f"{row_map['曲线数']} 条")
        if "采样点" in row_map:
            val_str = row_map["采样点"]
            try:
                val_str = f"{int(val_str):,}"
            except ValueError:
                pass
            self._update_chip_val(self.chip_samples, f"{val_str} 点")

        self.detail_table.load_table(detail_headers, detail_rows)

        if data_headers and data_rows:
            self.data_table.load_table(data_headers, data_rows)
            self.tabs.setTabEnabled(1, True)
            self.tabs.setCurrentIndex(0)
        else:
            self.data_table.load_table(("",), ())
            self.tabs.setTabEnabled(1, False)
            self.tabs.setCurrentIndex(0)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.summary_table.apply_settings(settings)
        self.detail_table.apply_settings(settings)
        self.data_table.apply_settings(settings)
