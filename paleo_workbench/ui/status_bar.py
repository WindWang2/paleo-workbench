from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSpacerItem, QSizePolicy


class StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self._project_name = "未命名工程"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)
        self.status_label = QLabel(f"就绪 · {self._project_name}")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.coord_label = QLabel(
            "X: 0  Y: 0  深度: 0 m  层位: -  CGCS2000 / EPSG:4326"
        )
        layout.addWidget(self.coord_label)

    def set_project_name(self, name: str) -> None:
        self._project_name = name
        self.status_label.setText(f"就绪 · {name}")
