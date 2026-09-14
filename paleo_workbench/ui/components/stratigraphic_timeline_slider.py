"""多期次地层层序时间轴（M1）——滑块部件 + 差分切换执行器。

部件（:class:`StratigraphicTimelineWidget`）只负责手势与去抖（00-decisions D4）：
拖拽/键盘步进 → ``epoch_scrubbed`` 预览；停顿 150ms 或释放 → ``epoch_committed``
一次。执行器（:class:`EpochTimelineController`）消费 commit/onion 信号，把
:mod:`paleo_workbench.mapping_workspace.epoch_switching` 的计划应用到图层管理器
（既有 ``set_layer_visible`` / ``set_layer_opacity`` 增量路径，零画布重建），
并把期次写穿到 ``stratigraphy.target_horizon``（复用既有权威通道）。
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping_workspace.epoch_switching import (
    build_epoch_switch_plan,
    build_onion_layers,
    default_epoch_classifier,
)
from paleo_workbench.workflow.stratigraphy import active_target_horizon, set_target_from_boundary

#: 提交去抖（ms）：拖拽释放 / 键盘步进停顿后触发一次 commit（D4）。
COMMIT_DEBOUNCE_MS = 150
#: 洋葱皮不透明度（D2：alpha 0.30，作用于相邻前一期次相带层）。
ONION_OPACITY = 0.30


class _TimelineTrack(QWidget):
    """期次刻度轨道：绘制 + 拖拽手势（确定性 x→index 映射，可测）。"""

    scrub_started = Signal()
    scrub_moved = Signal(int)
    released = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TimelineTrack")
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._labels: list[str] = []
        self._current = -1
        self._preview = -1
        self._dragging = False

    # -- 数据 ---------------------------------------------------------------

    def set_epochs(self, labels: Sequence[str]) -> None:
        self._labels = [str(x) for x in labels]
        self._current = 0 if self._labels else -1
        self._preview = -1
        self.update()

    def set_current_index(self, index: int) -> None:
        if not self._labels:
            return
        self._current = max(0, min(index, len(self._labels) - 1))
        self._preview = -1
        self.update()

    def set_preview_index(self, index: int) -> None:
        self._preview = index
        self.update()

    def index_at(self, x: int) -> int:
        if not self._labels or self.width() <= 0:
            return -1
        return max(0, min(int(x * len(self._labels) / self.width()),
                          len(self._labels) - 1))

    # -- 手势 ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.index_at(event.position().toPoint().x())
            if index >= 0:
                self._dragging = True
                self._preview = index
                self.scrub_started.emit()
                self.scrub_moved.emit(index)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            index = self.index_at(event.position().toPoint().x())
            if index != self._preview:
                self._preview = index
                self.scrub_moved.emit(index)
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            released = self._preview
            self._preview = -1
            self.update()
            self.released.emit(released)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- 绘制 ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        margin, gap = 6, 3
        usable = self.width() - 2 * margin
        count = len(self._labels)
        if count == 0 or usable <= 0:
            painter.end()
            return
        seg = (usable - gap * (count - 1)) / count
        metrics = QFontMetrics(self.font())
        palette = self.palette()
        base = palette.button().color()
        highlight = palette.highlight().color()
        preview = palette.mid().color()
        text = palette.windowText().color()
        for i, label in enumerate(self._labels):
            rect = QRect(int(margin + i * (seg + gap)), 4,
                         int(seg), self.height() - 10)
            fill = base
            if i == self._current:
                fill = highlight
            if self._preview >= 0 and i == self._preview:
                fill = preview
            painter.fillRect(rect, fill)
            painter.setPen(QPen(palette.window().color(), 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            elided = metrics.elidedText(label, Qt.TextElideMode.ElideRight,
                                        rect.width() - 8)
            pen_color = text
            if i == self._current and QColor(highlight).lightness() > 150:
                pen_color = palette.window().color()
            painter.setPen(pen_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.end()


class StratigraphicTimelineWidget(QWidget):
    """时间轴横条：刻度轨道 + 步进按钮 + 洋葱皮开关。"""

    epoch_scrubbed = Signal(str)
    scrub_started = Signal()
    epoch_committed = Signal(str)
    onion_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StratigraphicTimeline")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._epochs: list[Any] = []
        self._current_index = -1
        self._preview_index = -1
        self._pending_key: str | None = None

        from PySide6.QtWidgets import QHBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(4)

        self._prev_button = QToolButton(self)
        self._prev_button.setText("◀")
        self._prev_button.setToolTip("上一期次（←）")
        self._prev_button.clicked.connect(lambda: self._step(-1))
        self._track = _TimelineTrack(self)
        self._track.scrub_started.connect(self.scrub_started.emit)
        self._track.scrub_moved.connect(self._on_scrub_index)
        self._track.released.connect(self._schedule_commit_index)
        self._next_button = QToolButton(self)
        self._next_button.setText("▶")
        self._next_button.setToolTip("下一期次（→）")
        self._next_button.clicked.connect(lambda: self._step(1))
        self.onion_button = QToolButton(self)
        self.onion_button.setObjectName("TimelineOnionButton")
        self.onion_button.setText("🧅")
        self.onion_button.setToolTip("洋葱皮：30% 半透明叠加相邻前一期次相带边界")
        self.onion_button.setCheckable(True)
        self.onion_button.toggled.connect(self.onion_toggled.emit)

        self._placeholder = QLabel("无期次数据 — 先在层序页建立层序界面目录", self)
        self._placeholder.setObjectName("TimelinePlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.hide()

        row.addWidget(self._prev_button)
        row.addWidget(self._track, 1)
        row.addWidget(self._next_button)
        row.addWidget(self.onion_button)

        layout.addLayout(row)
        layout.addWidget(self._placeholder)

        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(COMMIT_DEBOUNCE_MS)
        self._commit_timer.timeout.connect(self._flush_commit)

    # -- 数据 ---------------------------------------------------------------

    def set_epochs(self, epochs: Sequence[Any]) -> None:
        self._epochs = list(epochs)
        self._track.set_epochs([getattr(e, "label", None) or getattr(e, "key", "")
                                for e in self._epochs])
        empty = not self._epochs
        self._placeholder.setVisible(empty)
        self._track.setVisible(not empty)
        self._prev_button.setVisible(not empty)
        self._next_button.setVisible(not empty)
        self.onion_button.setVisible(not empty)
        self._current_index = 0 if self._epochs else -1
        self._preview_index = -1
        self._track.set_current_index(self._current_index)
        self._pending_key = None

    def epochs(self) -> list[Any]:
        return list(self._epochs)

    def current_epoch(self) -> str | None:
        if 0 <= self._current_index < len(self._epochs):
            return str(self._epochs[self._current_index].key)
        return None

    def set_current_epoch(self, key: str, *, suppress: bool = True) -> None:
        """程序化同步当前期次（不触发 commit；echo 断路）。"""
        for index, epoch in enumerate(self._epochs):
            if str(epoch.key) == str(key):
                self._current_index = index
                self._preview_index = -1
                self._track.set_current_index(index)
                if suppress:
                    self._pending_key = None
                return

    # -- 手势 / 键盘 ----------------------------------------------------------

    def _key_at(self, index: int) -> str | None:
        if 0 <= index < len(self._epochs):
            return str(self._epochs[index].key)
        return None

    def _on_scrub_index(self, index: int) -> None:
        key = self._key_at(index)
        if key is not None:
            self._track.set_preview_index(index)
            self.epoch_scrubbed.emit(key)

    def _schedule_commit_index(self, index: int) -> None:
        key = self._key_at(index)
        if key is not None:
            self._pending_key = key
            self._commit_timer.start()

    def _step(self, delta: int) -> None:
        if not self._epochs:
            return
        # 步进基准是预览位（连击时从上次预览继续），提交前不移动 current。
        base = self._preview_index if self._preview_index >= 0 else self._current_index
        target = max(0, min(base + delta, len(self._epochs) - 1))
        self._preview_index = target
        self._on_scrub_index(target)
        self._schedule_commit_index(target)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Left):
            self._step(1 if event.key() == Qt.Key.Key_Right else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _flush_commit(self) -> None:
        key = self._pending_key
        self._pending_key = None
        self._preview_index = -1
        if key is None:
            return
        self.set_current_epoch(key, suppress=False)
        self.epoch_committed.emit(key)


class EpochTimelineController(QObject):
    """期次差分切换执行器（纯 QObject；对图层管理器鸭子面编程）。"""

    #: 提交完成（含外部直调 request_commit 的自动化路径）→ 宿主回同步部件
    #: 高亮。只读广播：消费者不得再触发提交（echo 断路契约，02-FSM 同款）。
    epoch_changed = Signal(str)
    #: 洋葱皮实际生效状态（False = 无前期次层等场景按钮需回同步，F3）。
    onion_applied = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager: Any = None
        self._project: Any = None
        self._status_sink: Callable[[str], None] | None = None
        self._classifier: Callable[[Any], str | None] | None = None
        self._custom_classifier: Callable[[Any], str | None] | None = None
        self._epochs: list[Any] = []
        self._current_key: str | None = None
        self._onion = False
        self._onion_restore: list[tuple[str, bool, float]] = []

    # -- 绑定 ---------------------------------------------------------------

    def bind(
        self,
        *,
        layer_manager: Any,
        project: Any = None,
        status_sink: Callable[[str], None] | None = None,
        classifier: Callable[[Any], str | None] | None = None,
    ) -> None:
        self._manager = layer_manager
        self._project = project
        self._status_sink = status_sink
        self._classifier = classifier
        self._custom_classifier = classifier

    def set_project(self, project: Any) -> None:
        self._project = project
        if project is not None:
            try:
                horizon = active_target_horizon(project)
            except Exception:
                horizon = ""
            if horizon:
                self._current_key = horizon

    def set_epochs(self, epochs: Sequence[Any]) -> None:
        self._epochs = list(epochs)
        # 目录变化即重建默认分类器（工程装载时首建目录常为空；注入的自定义
        # 分类器不覆盖）。
        if self._custom_classifier is None:
            self._classifier = default_epoch_classifier(self._epochs)
        if self._current_key is None and self._epochs:
            self._current_key = str(self._epochs[0].key)

    def current_epoch(self) -> str | None:
        return self._current_key

    # -- 提交 -----------------------------------------------------------------

    def _layers(self) -> list[Any]:
        if self._manager is None:
            return []
        return list(getattr(self._manager, "_layers", None) or [])

    def _status(self, message: str) -> None:
        if self._status_sink is not None:
            self._status_sink(message)

    def request_commit(self, key: str) -> None:
        if self._manager is None:
            return
        target = str(key)
        plan = build_epoch_switch_plan(
            self._layers(), current=self._current_key, target=target,
            classifier=self._classifier,
        )
        touched: list[tuple[str, bool]] = []
        for layer_id in (*plan.show, *plan.hide):
            layer = self._find_layer(layer_id)
            touched.append((str(layer_id), bool(layer.visible if layer else True)))
        try:
            if self._onion:
                self._restore_onion()
            for layer_id in plan.hide:
                self._manager.set_layer_visible(layer_id, False)
            for layer_id in plan.show:
                self._manager.set_layer_visible(layer_id, True)
        except Exception:
            for layer_id, visible in touched:
                try:
                    self._manager.set_layer_visible(layer_id, visible)
                except Exception:
                    pass  # 回滚尽力而为；原始异常继续上抛
            raise
        self._current_key = target
        self._write_horizon(target)
        self.epoch_changed.emit(target)
        affiliated = any(self._classifier and self._classifier(layer) == target
                         for layer in self._layers())
        label = self._label_of(target)
        if not affiliated:
            self._status(f"期次「{label}」暂无图层——仅切换目标层位")
        elif not plan:
            self._status(f"期次「{label}」图层已就绪，无需切换可见性")
        else:
            self._status(f"已切换到期次「{label}」（隐藏 {len(plan.hide)} 层，"
                         f"显示 {len(plan.show)} 层）")
        if self._onion:
            self._apply_onion()

    def _find_layer(self, layer_id: str) -> Any:
        for layer in self._layers():
            if str(layer.id) == str(layer_id):
                return layer
        return None

    def _label_of(self, key: str) -> str:
        for epoch in self._epochs:
            if str(epoch.key) == key:
                return str(getattr(epoch, "label", "") or key)
        return key

    def _write_horizon(self, key: str) -> None:
        if self._project is None:
            return
        try:
            set_target_from_boundary(self._project, key)
        except Exception:
            pass  # 元数据写穿失败不阻断可见性切换（状态条已反馈）

    # -- 洋葱皮（D2） ----------------------------------------------------------

    def set_onion(self, enabled: bool) -> None:
        if enabled:
            if self._onion:
                self._restore_onion()
            self._apply_onion()
        else:
            self._restore_onion()
            self._status("洋葱皮已关闭")

    def _apply_onion(self) -> None:
        onion_ids = build_onion_layers(
            self._layers(), self._epochs, current=self._current_key or "",
            classifier=self._classifier,
        )
        if not onion_ids:
            self._onion = False
            label = self._label_of(self._current_key or "")
            self._status(f"期次「{label}」无相邻前一期次相带层可叠加")
            self.onion_applied.emit(False)  # F3：按钮态回同步
            return
        self._onion = True
        self._onion_restore = []
        raised = True
        for layer_id in onion_ids:
            layer = self._find_layer(layer_id)
            visible = bool(layer.visible) if layer is not None else True
            opacity = float(layer.opacity) if layer is not None else 1.0
            position = self._layer_position(layer_id)
            self._onion_restore.append((layer_id, visible, opacity, position))
            self._manager.set_layer_visible(layer_id, True)
            self._manager.set_layer_opacity(layer_id, ONION_OPACITY)
            raised = self._raise_layer_to_top(layer_id) and raised  # B2：置于当前层之上
        self.onion_applied.emit(True)
        hint = f"洋葱皮开启：前一期次「{self._prev_label()}」相带以 30% 半透明叠加"
        if not raised:
            # 分层模式下 root 平铺序不是权威（组结构由 LayerGroupController
            # 管），置顶推不动——如实说明，别让用户以为叠加层已在最上。
            hint += "（当前分组模式不支持跨组置顶：叠加层仍在其所属组内）"
        self._status(hint)

    def _prev_label(self) -> str:
        keys = [str(getattr(e, "key", "") or "") for e in self._epochs]
        current = self._current_key or ""
        if current in keys:
            index = keys.index(current)
            if index > 0:
                return self._label_of(keys[index - 1])
        return ""

    def _layer_position(self, layer_id: str) -> int:
        for index, layer in enumerate(self._layers()):
            if str(layer.id) == str(layer_id):
                return index
        return -1

    def _raise_layer_to_top(self, layer_id: str) -> bool:
        """把洋葱层移到渲染栈顶（列表末位 = 最后绘制 = 在上）。

        返回是否**真的应用**：分组模式下 ``move_layer`` 不推桥（root 平铺序
        不是权威），置顶落不了地——调用方据此如实呈现，不制造"已在最上"的
        假象（V12 D-C2：静默 no-op 是这一条最坏的表现形态）。

        move_layer(id, direction) 的 direction=+1 使 index 变小（朝底部）；
        B2 review 修正：渲染自底向上，"置于当前层之上" = 移向列表末位。
        """
        move = getattr(self._manager, "move_layer", None)
        if not callable(move):
            return False
        layers = self._layers()
        position = self._layer_position(layer_id)
        moved = max(len(layers) - 1 - position, 0)
        if moved == 0:
            return True  # 已在栈顶，无需移动
        applied = False
        for _ in range(moved):
            applied = bool(move(str(layer_id), -1))
        return applied

    def _lower_layer_to(self, layer_id: str, position: int) -> None:
        """复原到记录的原列表位置（index 大者在上，原位可能在中部）。"""
        move = getattr(self._manager, "move_layer", None)
        if not callable(move):
            return
        current = self._layer_position(layer_id)
        for _ in range(max(current - position, 0)):
            move(str(layer_id), 1)

    def _restore_onion(self) -> None:
        if not self._onion_restore:
            self._onion = False
            return
        for layer_id, visible, opacity, position in self._onion_restore:
            try:
                self._lower_layer_to(layer_id, position)  # B2：复原层序
                self._manager.set_layer_opacity(layer_id, opacity)
                self._manager.set_layer_visible(layer_id, visible)
            except Exception:
                pass
        self._onion_restore = []
        self._onion = False
