from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import style


class PagePlaceholder(QWidget):
    def __init__(self, page_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PagePlaceholder")
        self.name_label = QLabel(f"{page_name}\n(占位页, 待实现)")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # style.bind：占位页文字色随主题刷新（此前构造时快照 light 值）
        style.bind(
            self.name_label,
            lambda: f"color: {style.palette()['TEXT_SECONDARY']}; font-size: 16px;",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self.name_label)
        layout.addStretch()
