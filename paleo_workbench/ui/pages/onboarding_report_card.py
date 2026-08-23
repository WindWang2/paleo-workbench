from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens


class OnboardingReportCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("OnboardingReportCard")
        self.setStyleSheet(
            f"QFrame#OnboardingReportCard {{ background: {tokens.BG_SIDEBAR}; border: 1px solid {tokens.BORDER}; border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4)
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("数据盘点报告")
        self.title_label.setObjectName("report_title_label")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.source_label = QLabel("")
        self.source_label.setObjectName("report_source_label")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self.source_label)

        self.report_summary_label = QLabel("")
        self.report_summary_label.setObjectName("report_summary_label")
        self.report_summary_label.setWordWrap(True)
        self.report_summary_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-size: 12px;")
        layout.addWidget(self.report_summary_label)

        self.by_type_label = QLabel("")
        self.by_type_label.setObjectName("report_by_type_label")
        self.by_type_label.setWordWrap(True)
        self.by_type_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-size: 11px;")
        layout.addWidget(self.by_type_label)

        self.extent_label = QLabel("")
        self.extent_label.setObjectName("report_extent_label")
        self.extent_label.setWordWrap(True)
        self.extent_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self.extent_label)

        self.issues_label = QLabel("")
        self.issues_label.setObjectName("report_issues_label")
        self.issues_label.setWordWrap(True)
        self.issues_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 11px;")
        layout.addWidget(self.issues_label)

        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("report_warnings_label")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 11px;")
        layout.addWidget(self.warnings_label)

        self.setVisible(False)

    def set_report(self, report: dict | None) -> None:
        if not report:
            self.setVisible(False)
            return
        self.setVisible(True)

        source = report.get("source_folder") or report.get("intermediate_folder") or ""
        if source:
            self.source_label.setText(f"来源目录：{source}")
            self.source_label.setVisible(True)
        else:
            self.source_label.setVisible(False)

        imported_count = report.get("imported_count", 0)
        wells_total = report.get("wells_total", 0)
        wells_with_coords = report.get("wells_with_coords", 0)
        surveys = report.get("surveys", 0)
        entities = report.get("entities", 0)
        summary = f"导入 {imported_count} 项 · 井 {wells_total} 口（{wells_with_coords} 有坐标） · 地震 {surveys} 个 · 地质实体 {entities} 个"
        self.report_summary_label.setText(summary)
        self.report_summary_label.setVisible(True)

        by_type = report.get("by_type") or {}
        if by_type:
            sorted_items = sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)
            parts = [f"{k} {v}" for k, v in sorted_items]
            self.by_type_label.setText(" · ".join(parts))
            self.by_type_label.setVisible(True)
        else:
            self.by_type_label.setVisible(False)

        extent = report.get("extent")
        if extent and isinstance(extent, (list, tuple)) and len(extent) == 4 and all(v is not None for v in extent):
            try:
                xmin, xmax, ymin, ymax = [float(v) for v in extent]
                self.extent_label.setText(f"范围：[{xmin:.1f}, {xmax:.1f}] · [{ymin:.1f}, {ymax:.1f}]")
            except Exception:
                self.extent_label.setText("无坐标井位范围")
            self.extent_label.setVisible(True)
        else:
            self.extent_label.setText("无坐标井位范围")
            self.extent_label.setVisible(True)

        # issues and warnings capped at 5
        issues = list(report.get("issues") or [])
        warnings = list(report.get("warnings") or [])
        # prefer combined? spec: issues/warnings 非空时最多 5 条（warning 色）
        combined = []
        for item in issues:
            combined.append(str(item))
        for item in warnings:
            combined.append(str(item))
        # If issues separately? Show up to 5 total first issues/warnings
        # But keep two labels: issues_label and warnings_label for test flexibility
        if combined:
            display = combined[:5]
            self.issues_label.setText("\n".join(display))
            self.issues_label.setVisible(True)
            # warnings label hide to avoid duplicate when combined
            self.warnings_label.setVisible(False)
        else:
            self.issues_label.setVisible(False)
            self.warnings_label.setVisible(False)
