"""拓扑检查器面板（拓扑编辑迁移 M4 §5）。

错误列表、规则过滤、点击缩放/高亮、忽略灰显可恢复、单条/全部修复。
不嵌 QgsGeometryCheckerDialog（依赖 QgisInterface）。轻量 QWidget，
可作检查器 tab 或独立测。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.topology_checker import ignore_key

__all__ = ["TopologyCheckerPanel"]

_RULE_LABELS = {
    "": "全部规则",
    "overlap": "面重叠",
    "gap": "面缝隙",
    "is_valid": "几何有效性",
    "workspace_remainder": "工区余量",
    "dangle": "线悬挂点",
}


class TopologyCheckerPanel(QWidget):
    """错误列表 + 检查/修复/忽略。"""

    zoom_requested = Signal(list)  # bbox [xmin, ymin, xmax, ymax]
    highlight_requested = Signal(str)  # error id
    check_requested = Signal()
    fix_requested = Signal(str, int)  # error id, method
    fix_all_requested = Signal()
    ignore_requested = Signal(dict)
    restore_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopologyCheckerPanel")
        self._all_errors: list[dict] = []
        self._ignored_keys: set[tuple] = set()
        self._controller = None
        self._last_run_at = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.badge = QLabel("尚未检查", self)
        self.badge.setObjectName("TopologyCheckerBadge")
        layout.addWidget(self.badge)

        self.rule_filter = QComboBox(self)
        for key, label in _RULE_LABELS.items():
            self.rule_filter.addItem(label, key)
        self.rule_filter.currentIndexChanged.connect(self._rebuild)
        layout.addWidget(self.rule_filter)

        self.error_list = QListWidget(self)
        self.error_list.setObjectName("TopologyCheckerErrorList")
        self.error_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.error_list.itemClicked.connect(self._on_item_clicked)
        self.error_list.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self.error_list, 1)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("检查")
        self.fix_button = QPushButton("修复")
        self.fix_all_button = QPushButton("全部修复")
        self.ignore_button = QPushButton("忽略")
        self.restore_button = QPushButton("恢复")
        self.check_button.clicked.connect(self._on_check)
        self.fix_button.clicked.connect(self._on_fix)
        self.fix_all_button.clicked.connect(self.fix_all_requested.emit)
        self.ignore_button.clicked.connect(self._on_ignore)
        self.restore_button.clicked.connect(self._on_restore)
        for button in (self.check_button, self.fix_button, self.fix_all_button,
                       self.ignore_button, self.restore_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def bind(self, controller) -> None:
        """绑定综合编修控制器（检查/修复走其 TopologyChecker）。"""
        self._controller = controller

    def set_errors(self, errors, ignored_keys=(), last_run_at=None) -> None:
        self._all_errors = [dict(error) for error in errors or ()]
        self._ignored_keys = set(ignored_keys or ())
        if last_run_at:
            self._last_run_at = last_run_at
        blocking = sum(1 for error in self._all_errors
                       if ignore_key(error) not in self._ignored_keys)
        stamp = str(self._last_run_at or "")
        if stamp:
            self.badge.setText(f"{blocking} 处未忽略 · {stamp}")
        elif self._all_errors:
            self.badge.setText(f"{blocking} 处未忽略")
        else:
            self.badge.setText("尚未检查")
        self._rebuild()

    def _rebuild(self) -> None:
        rule = str(self.rule_filter.currentData() or "")
        self.error_list.clear()
        for error in self._all_errors:
            if rule and str(error.get("rule") or "") != rule:
                continue
            label = str(error.get("message") or error.get("rule") or "error")
            feature_id = str(error.get("feature_id") or "")
            if feature_id:
                label = f"{label}（{feature_id}）"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(error))
            if ignore_key(error) in self._ignored_keys:
                item.setForeground(QColor(160, 160, 160))
                font = QFont(item.font())
                font.setItalic(True)
                item.setFont(font)
            self.error_list.addItem(item)

    def _current_error(self) -> dict | None:
        item = self.error_list.currentItem()
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        return dict(payload) if isinstance(payload, dict) else None

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        error = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(error, dict):
            return
        bbox = error.get("bbox") or []
        if len(bbox) >= 4:
            self.zoom_requested.emit([float(bbox[0]), float(bbox[1]),
                                      float(bbox[2]), float(bbox[3])])
        error_id = str(error.get("id") or "")
        if error_id:
            self.highlight_requested.emit(error_id)

    def _on_check(self) -> None:
        controller = self._controller
        if controller is not None and hasattr(controller, "run_topology_checks"):
            errors = controller.run_topology_checks()
            checker = controller.topology.checker
            self.set_errors(errors, ignored_keys=checker.ignored_keys(),
                            last_run_at=checker.last_run_at)
            return
        self.check_requested.emit()

    def menu_for(self, error: dict) -> QMenu:
        """单条右键：check 声明的方法列表（含预览描述）。"""
        menu = QMenu(self)
        methods = error.get("methods") or [{"id": 0, "name": "修复"}]
        for method in methods:
            name = str(method.get("name") or "修复")
            desc = str(method.get("description") or "")
            label = f"{name} — {desc}" if desc else name
            action = menu.addAction(label)
            method_id = int(method.get("id") or 0)
            error_id = str(error.get("id") or "")
            action.triggered.connect(
                lambda *_, eid=error_id, mid=method_id:
                    self.fix_requested.emit(eid, mid))
        return menu

    def _on_menu(self, pos) -> None:
        error = self._current_error()
        if error is None:
            item = self.error_list.itemAt(pos)
            if item is not None:
                self.error_list.setCurrentItem(item)
                payload = item.data(Qt.ItemDataRole.UserRole)
                error = dict(payload) if isinstance(payload, dict) else None
        if error is None:
            return
        self.menu_for(error).exec(self.error_list.mapToGlobal(pos))

    def _on_fix(self) -> None:
        error = self._current_error()
        if error is None:
            return
        methods = error.get("methods") or [{"id": 0}]
        self.fix_requested.emit(
            str(error.get("id") or ""), int(methods[0].get("id") or 0))

    def _on_ignore(self) -> None:
        error = self._current_error()
        if error is not None:
            self.ignore_requested.emit(error)

    def _on_restore(self) -> None:
        error = self._current_error()
        if error is not None:
            self.restore_requested.emit(error)
