from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QWidget

from paleo_workbench.ui import tokens

_ICONS_DIR = Path(__file__).parent.parent.parent / "ui" / "assets" / "icons" / "map"


def _icon(name: str) -> QIcon:
    path = _ICONS_DIR / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


class DataToolbar(QWidget):
    import_files_requested = Signal()
    import_folder_requested = Signal()
    rescan_requested = Signal()
    remove_requested = Signal()
    open_folder_requested = Signal()
    visualize_requested = Signal()
    clear_preview_cache_requested = Signal()
    verify_requested = Signal()
    # Data health entry: open the Catalog Health (audit) dialog.
    health_check_requested = Signal()
    reader_toggled = Signal()
    search_changed = Signal(str)
    # Multi-tag asset-table filter: (selected tag names, "and"|"or").
    tag_filter_changed = Signal(list, str)
    # Open the Tag Manager dialog (tags CRUD / merge / prune).
    tag_manager_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataToolbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_1)

        self.import_btn = QPushButton(_icon("btn-import"), "导入文件")
        self.import_btn.setObjectName("PrimaryButton")
        self.import_btn.setMinimumHeight(tokens.CONTROL_HEIGHT_LG)
        self.import_btn.setToolTip("导入文件并创建项目受管的不可变 RAW 副本")
        self.import_btn.clicked.connect(self.import_files_requested.emit)
        layout.addWidget(self.import_btn)

        self.import_folder_btn = QPushButton(_icon("btn-import-folder"), "导入目录")
        self.import_folder_btn.setObjectName("SecondaryButton")
        self.import_folder_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.import_folder_btn.setToolTip("导入整个目录")
        self.import_folder_btn.clicked.connect(self.import_folder_requested.emit)
        layout.addWidget(self.import_folder_btn)

        self.verify_btn = QPushButton(_icon("btn-verify"), "完整性校验")
        self.verify_btn.setObjectName("SecondaryButton")
        self.verify_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.verify_btn.setToolTip("后台校验数据资产完整性与 SHA-256")
        self.verify_btn.clicked.connect(self.verify_requested.emit)
        layout.addWidget(self.verify_btn)
        self._verify_running = False

        self.health_btn = QPushButton(_icon("btn-health"), "健康检查")
        self.health_btn.setObjectName("SecondaryButton")
        self.health_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.health_btn.setToolTip("数据目录健康体检：资产/版本统计、缺失、血缘断链、标签悬挂、孤儿文件")
        self.health_btn.clicked.connect(self.health_check_requested.emit)
        layout.addWidget(self.health_btn)

        self.rescan_btn = QPushButton(_icon("btn-rescan"), "重新扫描")
        self.rescan_btn.setObjectName("SecondaryButton")
        self.rescan_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.rescan_btn.setToolTip("重新扫描选中项")
        self.rescan_btn.clicked.connect(self.rescan_requested.emit)
        layout.addWidget(self.rescan_btn)

        self.remove_btn = QPushButton(_icon("btn-remove"), "移出项目")
        self.remove_btn.setObjectName("SecondaryButton")
        self.remove_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.remove_btn.setToolTip("移出项目（不删源文件）")
        self.remove_btn.clicked.connect(self.remove_requested.emit)
        layout.addWidget(self.remove_btn)

        self.open_folder_btn = QPushButton(_icon("btn-open-folder"), "打开目录")
        self.open_folder_btn.setObjectName("SecondaryButton")
        self.open_folder_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.open_folder_btn.setToolTip("在文件管理器中打开")
        self.open_folder_btn.clicked.connect(self.open_folder_requested.emit)
        layout.addWidget(self.open_folder_btn)

        self.visualize_btn = QPushButton(_icon("btn-visualize"), "可视化")
        self.visualize_btn.setObjectName("SecondaryButton")
        self.visualize_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.visualize_btn.setToolTip("在可视化页面打开")
        self.visualize_btn.clicked.connect(self.visualize_requested.emit)
        layout.addWidget(self.visualize_btn)

        self.clear_preview_cache_btn = QPushButton(_icon("btn-clear-cache"), "清除预览缓存")
        self.clear_preview_cache_btn.setObjectName("SecondaryButton")
        self.clear_preview_cache_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.clear_preview_cache_btn.setToolTip("清除项目预览磁盘缓存")
        self.clear_preview_cache_btn.clicked.connect(
            self.clear_preview_cache_requested.emit
        )
        layout.addWidget(self.clear_preview_cache_btn)

        # --- Tag tools -------------------------------------------------------
        # 标签筛选: checkable tag list + AND/OR + clear, applied immediately.
        self.tag_filter_btn = QPushButton(_icon("btn-tag-filter"), "标签筛选")
        self.tag_filter_btn.setObjectName("SecondaryButton")
        self.tag_filter_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.tag_filter_btn.setToolTip("按标签筛选资产表（支持多选与 AND/OR 组合）")
        self._tag_filter_menu = QMenu(self.tag_filter_btn)
        self._tag_filter_menu.aboutToShow.connect(self._rebuild_tag_filter_menu)
        self.tag_filter_btn.setMenu(self._tag_filter_menu)
        layout.addWidget(self.tag_filter_btn)

        self.tag_manager_btn = QPushButton(_icon("btn-tag-manager"), "标签管理")
        self.tag_manager_btn.setObjectName("SecondaryButton")
        self.tag_manager_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.tag_manager_btn.setToolTip("管理标签：新建 / 重命名 / 合并 / 清理")
        self.tag_manager_btn.clicked.connect(self.tag_manager_requested.emit)
        layout.addWidget(self.tag_manager_btn)

        self.operation_status_label = QLabel("")
        self.operation_status_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        layout.addWidget(self.operation_status_label)

        # Tag filter panel state (menu rebuilt lazily from candidates).
        self._tag_candidates: list[str] = []
        self._selected_tags: list[str] = []
        self._tag_operator: str = "and"
        self._tag_check_actions: list[QAction] = []

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._pending_search = ""
        self._search_timer.timeout.connect(self._emit_debounced_search)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索文件名 / 类型 / 阶段 / 标签 / 路径...")
        self.search_box.setToolTip("搜索文件名/类型/阶段/标签/路径")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_box, 1)

        self.column_settings_slot = QWidget(self)
        self.column_settings_slot.setObjectName("ColumnSettingsSlot")
        column_settings_layout = QHBoxLayout(self.column_settings_slot)
        column_settings_layout.setContentsMargins(0, 0, 0, 0)
        column_settings_layout.setSpacing(0)
        layout.addWidget(self.column_settings_slot)

        # Hides the whole right column (reader + inspector), not only the reader pane.
        self.reader_btn = QPushButton(_icon("btn-reader"), "预览栏")
        self.reader_btn.setObjectName("SecondaryButton")
        self.reader_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.reader_btn.setCheckable(True)
        self.reader_btn.setToolTip("显示或隐藏右侧预览与属性面板")
        self.reader_btn.clicked.connect(self.reader_toggled.emit)
        layout.addWidget(self.reader_btn)

    def set_verify_running(self, running: bool) -> None:
        self._verify_running = bool(running)
        if self._verify_running:
            self.verify_btn.setText("取消校验")
            self.verify_btn.setToolTip("取消正在进行的完整性校验")
        else:
            self.verify_btn.setText("完整性校验")
            self.verify_btn.setToolTip("后台校验数据资产完整性与 SHA-256")

    def set_column_settings_button(self, button: QPushButton) -> None:
        self.column_settings_slot.layout().addWidget(button)

    # --- Tag filter panel -----------------------------------------------------

    def set_tag_candidates(self, tags: list[str]) -> None:
        """Provide the selectable tag list (from FilterIndex counts or the
        catalog service). Rebuilds the menu on next open."""
        self._tag_candidates = sorted(
            {t for t in tags if t and str(t).strip()}
        )

    def tag_candidates(self) -> list[str]:
        return list(self._tag_candidates)

    def set_tag_operator(self, operator: str) -> None:
        if operator in ("and", "or"):
            self._tag_operator = operator

    def current_tag_selection(self) -> list[str]:
        # Read the filter state, not the lazily-built menu-action mirror: the
        # actions only exist after the menu was opened once, so reading them
        # here would silently report [] for programmatic applies (Tag Manager
        # 查看关联数据) and drop the tag filter on the next navigation click
        # (#413). The menu rebuild initializes its check states from
        # _selected_tags, so the mirror can never diverge from the source.
        return list(self._selected_tags)

    def current_tag_operator(self) -> str:
        return self._tag_operator

    def apply_tag_selection(self, tags: list[str], operator: str = "and") -> None:
        """Programmatically set the checked tag filter (single source of truth
        for the visible filter state, e.g. Tag Manager 双击查看关联数据)."""
        self._selected_tags = [t for t in tags if t and str(t).strip()]
        if operator in ("and", "or"):
            self._tag_operator = operator
        self._emit_tag_filter()

    def _rebuild_tag_filter_menu(self) -> None:
        self._tag_filter_menu.clear()
        self._tag_check_actions = []

        if not self._tag_candidates:
            empty = QAction("暂无可用标签", self._tag_filter_menu)
            empty.setEnabled(False)
            self._tag_filter_menu.addAction(empty)
            return

        for tag in self._tag_candidates:
            action = QAction(tag, self._tag_filter_menu)
            action.setCheckable(True)
            action.setChecked(tag in self._selected_tags)
            action.toggled.connect(
                lambda checked, name=tag: self._on_tag_toggled(name, checked)
            )
            self._tag_filter_menu.addAction(action)
            self._tag_check_actions.append(action)

        self._tag_filter_menu.addSeparator()

        operator_group = QActionGroup(self._tag_filter_menu)
        operator_group.setExclusive(True)
        for label, value in (("匹配全部 (AND)", "and"), ("匹配任一 (OR)", "or")):
            op_action = QAction(label, self._tag_filter_menu)
            op_action.setCheckable(True)
            op_action.setChecked(self._tag_operator == value)
            op_action.setActionGroup(operator_group)
            op_action.toggled.connect(
                lambda checked, op=value: self._on_operator_changed(op, checked)
            )
            self._tag_filter_menu.addAction(op_action)

        self._tag_filter_menu.addSeparator()

        clear_action = QAction("清除标签筛选", self._tag_filter_menu)
        clear_action.triggered.connect(self.clear_tag_filter)
        self._tag_filter_menu.addAction(clear_action)

    def _on_tag_toggled(self, tag_name: str, checked: bool) -> None:
        if checked and tag_name not in self._selected_tags:
            self._selected_tags.append(tag_name)
        elif not checked and tag_name in self._selected_tags:
            self._selected_tags.remove(tag_name)
        self._emit_tag_filter()

    def _on_operator_changed(self, operator: str, checked: bool) -> None:
        if not checked:
            return
        self._tag_operator = operator
        self._emit_tag_filter()

    def clear_tag_filter(self) -> None:
        self._selected_tags = []
        self._emit_tag_filter()

    def _emit_tag_filter(self) -> None:
        self.tag_filter_changed.emit(list(self._selected_tags), self._tag_operator)

    def _on_search_text_changed(self, text: str) -> None:
        self._pending_search = text
        self._search_timer.start()

    def _emit_debounced_search(self) -> None:
        self.search_changed.emit(self._pending_search)
