from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class DataToolbar(QWidget):
    import_files_requested = Signal()
    import_folder_requested = Signal()
    rescan_requested = Signal()
    catalog_toggled = Signal()
    reader_toggled = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataToolbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.import_btn = QPushButton("导入文件")
        self.import_btn.setObjectName("PrimaryButton")
        self.import_btn.clicked.connect(self.import_files_requested.emit)
        layout.addWidget(self.import_btn)

        self.import_folder_btn = QPushButton("导入目录")
        self.import_folder_btn.setObjectName("SecondaryButton")
        self.import_folder_btn.clicked.connect(self.import_folder_requested.emit)
        layout.addWidget(self.import_folder_btn)

        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.setObjectName("SecondaryButton")
        self.rescan_btn.clicked.connect(self.rescan_requested.emit)
        layout.addWidget(self.rescan_btn)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._pending_search = ""
        self._search_timer.timeout.connect(self._emit_debounced_search)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索文件名 / 类型 / 格式 / 路径...")
        self.search_box.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_box, 1)

        self.column_settings_slot = QWidget(self)
        self.column_settings_slot.setObjectName("ColumnSettingsSlot")
        column_settings_layout = QHBoxLayout(self.column_settings_slot)
        column_settings_layout.setContentsMargins(0, 0, 0, 0)
        column_settings_layout.setSpacing(0)
        layout.addWidget(self.column_settings_slot)

        self.catalog_btn = QPushButton("目录")
        self.catalog_btn.setObjectName("SecondaryButton")
        self.catalog_btn.setCheckable(True)
        self.catalog_btn.clicked.connect(self.catalog_toggled.emit)
        layout.addWidget(self.catalog_btn)

        self.reader_btn = QPushButton("阅读器")
        self.reader_btn.setObjectName("SecondaryButton")
        self.reader_btn.setCheckable(True)
        self.reader_btn.clicked.connect(self.reader_toggled.emit)
        layout.addWidget(self.reader_btn)

    def set_column_settings_button(self, button: QPushButton) -> None:
        self.column_settings_slot.layout().addWidget(button)

    def _on_search_text_changed(self, text: str) -> None:
        self._pending_search = text
        self._search_timer.start()

    def _emit_debounced_search(self) -> None:
        self.search_changed.emit(self._pending_search)
