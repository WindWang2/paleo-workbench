from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


class ActionPanel(QFrame):
    """Right-hand action panel for data import and conversion commands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionPanel")
        self.setFixedWidth(180)
        self.setStyleSheet(
            f"QFrame#ActionPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.import_btn = QPushButton("导入文件")
        self.import_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.import_btn)

        self.import_folder_btn = QPushButton("导入目录")
        self.import_folder_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.import_folder_btn)

        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.rescan_btn)

        self.remove_btn = QPushButton("移出项目")
        self.remove_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.remove_btn)

        self.open_folder_btn = QPushButton("打开目录")
        self.open_folder_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.open_folder_btn)

        self.open_visualization_btn = QPushButton("在可视化中打开")
        self.open_visualization_btn.setObjectName("SecondaryButton")
        self.open_visualization_btn.setEnabled(False)
        layout.addWidget(self.open_visualization_btn)

        self.selection_status_label = QLabel("等待选择")
        self.selection_status_label.setWordWrap(True)
        self.selection_status_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        layout.addWidget(self.selection_status_label)

        self.operation_status_label = QLabel("等待操作")
        self.operation_status_label.setWordWrap(True)
        self.operation_status_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        layout.addWidget(self.operation_status_label)
        self.status_label = self.operation_status_label

        layout.addStretch()

    def update_selection_state(
        self,
        has_resource: bool,
        has_asset: bool,
        reader_mode: str,
        asset_kind: str = "none",
    ) -> None:
        self.rescan_btn.setEnabled(has_resource)
        self.remove_btn.setEnabled(has_asset)
        self.open_folder_btn.setEnabled(has_asset)
        if has_asset:
            kind_label = "资源" if asset_kind == "resource" else "成果"
            self.selection_status_label.setText(f"已选{kind_label} · 阅读器: {reader_mode}")
        else:
            self.selection_status_label.setText("等待选择")
