from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from paleo_workbench.ui import tokens


class DataToolbar(QWidget):
    import_files_requested = Signal()
    import_folder_requested = Signal()
    rescan_requested = Signal()
    remove_requested = Signal()
    open_folder_requested = Signal()
    visualize_requested = Signal()
    clear_preview_cache_requested = Signal()
    reader_toggled = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataToolbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_1)

        self.import_btn = QPushButton("导入文件")
        self.import_btn.setObjectName("PrimaryButton")
        self.import_btn.setMinimumHeight(tokens.CONTROL_HEIGHT_LG)
        self.import_btn.setToolTip("导入数据文件")
        self.import_btn.clicked.connect(self.import_files_requested.emit)
        layout.addWidget(self.import_btn)

        self.import_folder_btn = QPushButton("导入目录")
        self.import_folder_btn.setObjectName("SecondaryButton")
        self.import_folder_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.import_folder_btn.setToolTip("导入整个目录")
        self.import_folder_btn.clicked.connect(self.import_folder_requested.emit)
        layout.addWidget(self.import_folder_btn)

        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.setObjectName("SecondaryButton")
        self.rescan_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.rescan_btn.setToolTip("重新扫描选中项")
        self.rescan_btn.clicked.connect(self.rescan_requested.emit)
        layout.addWidget(self.rescan_btn)

        self.remove_btn = QPushButton("移出项目")
        self.remove_btn.setObjectName("SecondaryButton")
        self.remove_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.remove_btn.setToolTip("移出项目（不删源文件）")
        self.remove_btn.clicked.connect(self.remove_requested.emit)
        layout.addWidget(self.remove_btn)

        self.open_folder_btn = QPushButton("打开目录")
        self.open_folder_btn.setObjectName("SecondaryButton")
        self.open_folder_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.open_folder_btn.setToolTip("在文件管理器中打开")
        self.open_folder_btn.clicked.connect(self.open_folder_requested.emit)
        layout.addWidget(self.open_folder_btn)

        self.visualize_btn = QPushButton("可视化")
        self.visualize_btn.setObjectName("SecondaryButton")
        self.visualize_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.visualize_btn.setToolTip("在可视化页面打开")
        self.visualize_btn.clicked.connect(self.visualize_requested.emit)
        layout.addWidget(self.visualize_btn)

        self.clear_preview_cache_btn = QPushButton("清除预览缓存")
        self.clear_preview_cache_btn.setObjectName("SecondaryButton")
        self.clear_preview_cache_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.clear_preview_cache_btn.setToolTip("清除项目预览磁盘缓存")
        self.clear_preview_cache_btn.clicked.connect(
            self.clear_preview_cache_requested.emit
        )
        layout.addWidget(self.clear_preview_cache_btn)

        self.operation_status_label = QLabel("")
        self.operation_status_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        layout.addWidget(self.operation_status_label)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._pending_search = ""
        self._search_timer.timeout.connect(self._emit_debounced_search)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索文件名 / 类型 / 格式 / 路径...")
        self.search_box.setToolTip("搜索文件名/类型/格式/路径")
        self.search_box.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_box, 1)

        self.column_settings_slot = QWidget(self)
        self.column_settings_slot.setObjectName("ColumnSettingsSlot")
        column_settings_layout = QHBoxLayout(self.column_settings_slot)
        column_settings_layout.setContentsMargins(0, 0, 0, 0)
        column_settings_layout.setSpacing(0)
        layout.addWidget(self.column_settings_slot)

        self.reader_btn = QPushButton("阅读器")
        self.reader_btn.setObjectName("SecondaryButton")
        self.reader_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.reader_btn.setCheckable(True)
        self.reader_btn.setToolTip("切换阅读器面板")
        self.reader_btn.clicked.connect(self.reader_toggled.emit)
        layout.addWidget(self.reader_btn)

    def set_column_settings_button(self, button: QPushButton) -> None:
        self.column_settings_slot.layout().addWidget(button)

    def _on_search_text_changed(self, text: str) -> None:
        self._pending_search = text
        self._search_timer.start()

    def _emit_debounced_search(self) -> None:
        self.search_changed.emit(self._pending_search)
