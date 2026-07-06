from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


CATEGORIES = {
    "全部": None,
    "输入数据": "input",
    "成果": "artifact",
    "参考资料": "reference",
    "异常": "issue",
    "测井": "well_log",
    "地震": "seismic",
    "层位": "horizon",
    "井分层": "well_stratification",
    "时深": "time_depth",
    "表格": "tabular",
    "文档": "document",
    "影像": "image_reference",
    "参考图": "reference_map",
    "未知": "unknown",
}


class DataCatalogPanel(QFrame):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataCatalogPanel")
        self.setFixedWidth(180)
        self.setStyleSheet(
            f"QFrame#DataCatalogPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.title_label = QLabel("数据目录")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.category_labels: dict[str, QPushButton] = {}
        for label in CATEGORIES:
            button = QPushButton(f"{label} 0")
            button.setObjectName("SecondaryButton")
            button.clicked.connect(
                lambda _checked=False, name=label: self.category_changed.emit(name)
            )
            self.category_labels[label] = button
            layout.addWidget(button)

        layout.addStretch()

    def update_counts(self, resources: list, artifacts: list) -> None:
        counts = Counter(resource.type for resource in resources)
        role_counts = Counter(resource.artifact_role or "input" for resource in resources)
        issue_count = sum(
            1
            for resource in resources
            if resource.status in {"missing", "warning", "failed", "error"}
        )
        values = {
            "全部": len(resources) + len(artifacts),
            "输入数据": role_counts["input"],
            "成果": len(artifacts) + role_counts["derived"] + role_counts["export"],
            "参考资料": sum(
                counts[key]
                for key in (
                    "document",
                    "image_reference",
                    "reference_map",
                    "well_reference",
                )
            ),
            "异常": issue_count,
        }

        for label, resource_type in CATEGORIES.items():
            count = values.get(label, counts[resource_type] if resource_type else 0)
            self.category_labels[label].setText(f"{label} {count}")
