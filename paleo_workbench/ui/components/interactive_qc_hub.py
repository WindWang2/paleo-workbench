"""交互式质检修复向导中心（M4）——问题聚合 / 平滑定位 / 快速修复。

部件（:class:`InteractiveQCHub`）只负责呈现与请求信号；定位动画在
:class:`SmoothPanController`（00-decisions D9：180ms ease-in-out、4-12 插值
帧、历史恰 1 条、用户输入可打断）；修复执行在宿主（CompositeDocument，
把 :mod:`paleo_workbench.mapping.qc_quickfix` 的动作套进编辑会话）。
"""
from __future__ import annotations

import math
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.qc_quickfix import actions_for_rule

#: 平移时长与帧间隔（D9）。
PAN_DURATION_MS = 180
PAN_TICK_MS = 20
#: bbox 外扩比例（与既有 _zoom 定位 10% pad 一致）。
FOCUS_PAD = 0.10


def _padded_bbox(bbox, pad: float = FOCUS_PAD) -> tuple[float, float, float, float]:
    values = [float(v) for v in bbox]
    if len(values) != 4:
        return (0.0, 0.0, 1.0, 1.0)
    xmin, ymin, xmax, ymax = values
    dx = max((xmax - xmin) * (1.0 + pad), (xmax - xmin) + 2.0 * pad)
    dy = max((ymax - ymin) * (1.0 + pad), (ymax - ymin) + 2.0 * pad)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    return (cx - dx / 2.0, cy - dy / 2.0, cx + dx / 2.0, cy + dy / 2.0)


def _ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class SmoothPanController(QObject):
    """画布平滑平移：cubic ease-in-out 插值 set_extent。

    历史记录只在末帧写一次（``record_history=True``）；中间帧
    ``coalesce_history=True`` 合并——既不污染撤销也不丢后退（D9）。
    对画布鸭子面编程（QgisCanvasShim / UnifiedMapCanvas / 测试 Fake）。
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._canvas: Any = None
        self._start: tuple[float, float, float, float] | None = None
        self._target: tuple[float, float, float, float] | None = None
        self._elapsed = 0
        self._timer = QTimer(self)
        self._timer.setInterval(PAN_TICK_MS)
        self._timer.timeout.connect(self._tick)

    def pan_to_extent(self, canvas: Any, extent, *, pad: float = 0.0) -> None:
        """平滑平移居中到目标 extent（先做 pad 外扩）。"""
        target = _padded_bbox(extent, pad) if pad else tuple(
            float(v) for v in extent)
        try:
            current = tuple(float(v) for v in canvas.view_extent())
        except Exception:
            current = (0.0, 0.0, 1.0, 1.0)
        self._canvas = canvas
        self._start = current
        self._target = tuple(target)
        self._elapsed = 0
        self._timer.start()

    def cancel(self) -> None:
        """用户输入打断（立即停止，不再写帧）。"""
        self._timer.stop()
        self._canvas = None

    def _tick(self) -> None:
        if self._canvas is None or self._start is None or self._target is None:
            self._timer.stop()
            return
        self._elapsed += PAN_TICK_MS
        t = _ease_in_out(self._elapsed / float(PAN_DURATION_MS))
        extent = tuple(
            a + (b - a) * t for a, b in zip(self._start, self._target))
        done = self._elapsed >= PAN_DURATION_MS
        try:
            if done:
                self._canvas.set_extent(
                    self._target, record_history=True, coalesce_history=True)
            else:
                self._canvas.set_extent(
                    extent, record_history=False, coalesce_history=True)
        except TypeError:
            # 宽容鸭子面（无 kwargs 形态的画布/假件）。
            self._canvas.set_extent(
                self._target if done else extent)
        if done:
            self._timer.stop()
            self._canvas = None


class InteractiveQCHub(QWidget):
    """质检修复向导：问题列表 + 详情/修复区（双栏，dock 或内嵌均宜）。"""

    issue_focused = Signal(dict)
    fix_requested = Signal(dict, str)
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InteractiveQCHub")
        self._sources: dict[str, list[dict]] = {}
        self._items: list[dict] = []  # 当前展示的 issue 列表（稳定序）
        self._fix_context_provider: Callable[[dict], Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self._refresh_button = QToolButton(self)
        self._refresh_button.setText("重新检查")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        self._filter_combo = QComboBox(self)
        self._filter_combo.addItems(["全部", "错误", "警告", "可修复"])
        self._filter_combo.currentTextChanged.connect(
            lambda _text: self._reload())
        self.counts_label = QLabel("0 错误 · 0 警告", self)
        self.counts_label.setObjectName("QCHubCounts")
        top.addWidget(self._refresh_button)
        top.addWidget(self._filter_combo)
        top.addStretch(1)
        top.addWidget(self.counts_label)
        layout.addLayout(top)

        from PySide6.QtWidgets import QSplitter

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.issue_list = QListWidget(splitter)
        self.issue_list.setObjectName("QCHubIssueList")
        self.issue_list.itemDoubleClicked.connect(
            lambda item: self.issue_focused.emit(
                dict(item.data(Qt.ItemDataRole.UserRole) or {})))
        self.issue_list.itemSelectionChanged.connect(self._on_selection)
        # 键盘流（S5-2）：QAbstractItemView 吞掉未知按键不透传父级，
        # 用事件过滤器在列表上直接接 Enter（定位）与 F（修复）。
        self.issue_list.installEventFilter(self)
        splitter.addWidget(self.issue_list)

        detail = QWidget(splitter)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(6, 6, 6, 6)
        self._detail_title = QLabel("选择一个问题查看详情", detail)
        self._detail_title.setWordWrap(True)
        self._detail_meta = QLabel("", detail)
        self._detail_meta.setWordWrap(True)
        locate_button = QPushButton("定位", detail)
        locate_button.clicked.connect(self._locate_selected)
        self._locate_button = locate_button
        detail_layout.addWidget(self._detail_title)
        detail_layout.addWidget(self._detail_meta)
        detail_layout.addWidget(locate_button)
        self._fix_area_label = QLabel("—— 快速修复 ——", detail)
        detail_layout.addWidget(self._fix_area_label)
        self._fix_buttons: dict[str, QPushButton] = {}
        detail_layout.addStretch(1)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    # -- 数据 ---------------------------------------------------------------

    def set_issues(self, source: str, issues: list[dict]) -> None:
        """按来源增量更新（cartographic / topology …；S4-4 聚合）。"""
        self._sources[str(source)] = [dict(issue) for issue in issues or []]
        self._reload()

    def _reload(self) -> None:
        merged: list[dict] = []
        for source in sorted(self._sources):
            merged.extend(self._sources[source])
        self._items = merged
        errors = sum(1 for i in merged if i.get("severity") == "error")
        warnings = sum(1 for i in merged if i.get("severity") == "warning")
        self.counts_label.setText(f"{errors} 错误 · {warnings} 警告")
        self.issue_list.clear()
        for issue in merged:
            label = issue.get("message") or issue.get("rule") or "?"
            glyph = "▲" if issue.get("severity") == "error" else "▼"
            rule = str(issue.get("rule") or "")
            fixable = "修复可用" if actions_for_rule(rule) else "—"
            item = QListWidgetItem(
                f"{glyph} {issue.get('rule', '')}  "
                f"{issue.get('feature_id', '')}  {fixable}  | {label}")
            item.setData(Qt.ItemDataRole.UserRole, dict(issue))
            self.issue_list.addItem(item)

    def issue_count(self) -> int:
        return len(self._items)

    def mark_resolved(self, issue: dict) -> None:
        """从展示中移除一个已修复问题（各来源同步剔除）。"""
        key = (str(issue.get("rule")), str(issue.get("feature_id")))
        for source, issues in list(self._sources.items()):
            self._sources[source] = [
                i for i in issues
                if (str(i.get("rule")), str(i.get("feature_id"))) != key]
        self._reload()

    # -- 详情 / 修复 -----------------------------------------------------------

    def set_fix_context(self, provider: Callable[[dict], Any]) -> None:
        """注入修复上下文 provider（issue → QuickFixContext|None）。"""
        self._fix_context_provider = provider
        self._refresh_detail()

    def _on_selection(self) -> None:
        item = self.issue_list.currentItem()
        self._show_detail(item)

    def _show_detail(self, item: QListWidgetItem | None) -> None:
        issue = dict(item.data(Qt.ItemDataRole.UserRole) or {}) \
            if item is not None else {}
        self._current_issue = issue
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        issue = getattr(self, "_current_issue", {}) or {}
        if not issue:
            self._detail_title.setText("选择一个问题查看详情")
            self._detail_meta.setText("")
            return
        self._detail_title.setText(
            str(issue.get("message") or issue.get("rule") or ""))
        self._detail_meta.setText(
            f"图层：{issue.get('layer_id', '—')}  要素："
            f"{issue.get('feature_id', '—')}")
        for button in self._fix_buttons.values():
            button.hide()
        for action in actions_for_rule(str(issue.get("rule") or "")):
            button = self._fix_buttons.get(action.action_id)
            if button is None:
                button = QPushButton(action.title, self)
                button.setObjectName(f"QCHubFix_{action.action_id}")
                button.clicked.connect(
                    lambda _checked=False, aid=action.action_id:
                    self._request_fix(aid))
                # 按钮挂到详情区（在 stretch 之前插入）
                self._fix_buttons[action.action_id] = button
                self._detail_meta.parentWidget().layout().insertWidget(
                    self._detail_meta.parentWidget().layout().count() - 1,
                    button)
            ctx = (self._fix_context_provider(issue)
                   if self._fix_context_provider else None)
            if ctx is None:
                button.setEnabled(False)
                button.setToolTip("无修复上下文（图层/会话不可用）")
            else:
                ok, reason = action.availability(issue, ctx)
                button.setEnabled(ok)
                button.setToolTip(reason if ok else f"不可修复：{reason}")
            button.show()

    def fix_button(self, action_id: str) -> QPushButton | None:
        return self._fix_buttons.get(action_id)

    def _current_issue_dict(self) -> dict:
        issue = getattr(self, "_current_issue", {}) or {}
        if issue:
            return dict(issue)
        item = self.issue_list.currentItem()
        if item is not None:
            return dict(item.data(Qt.ItemDataRole.UserRole) or {})
        return {}

    def _request_fix(self, action_id: str) -> None:
        issue = self._current_issue_dict()
        if issue:
            self.fix_requested.emit(dict(issue), str(action_id))

    def _locate_selected(self) -> None:
        item = self.issue_list.currentItem()
        if item is not None:
            self.issue_focused.emit(
                dict(item.data(Qt.ItemDataRole.UserRole) or {}))

    # -- 键盘流（↑↓ 列表原生；Enter 定位；F 修复，S5-2） ------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if obj is self.issue_list and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._locate_selected()
                return True
            if event.key() == Qt.Key.Key_F:
                issue = self._current_issue_dict()
                actions = actions_for_rule(str(issue.get("rule") or ""))
                if issue and actions:
                    self.fix_requested.emit(dict(issue), actions[0].action_id)
                    return True
        return super().eventFilter(obj, event)
