"""``MappingStageBar``：编图阶段切换控件（AppBar 附近的紧凑分段条）。

风格（V5 §34/§62/§63）：compact / professional / desktop workstation，
不是大卡片；不做整页彩色主题，阶段只经 active 指示 + 小徽标表达。
切换瞬时（组可见性增量），绝不重载工程/画布。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from paleo_workbench.mapping_workspace.stages import STAGE_ORDER, MappingStage


def _badge_tone(badge: str) -> str:
    if "!" in badge:
        return "error"
    if "~" in badge:
        return "warn"
    if "✓" in badge:
        return "ok"
    return "info"


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    for child in widget.findChildren(QWidget):
        style.unpolish(child)
        style.polish(child)


class _StageSegment(QFrame):
    """单个阶段：序号圆点 + 短名 + 状态徽标。"""

    clicked = Signal()

    def __init__(self, stage: MappingStage, parent: QWidget | None = None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("MappingStageSegment")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(stage.description)
        self.setAccessibleName(stage.label)
        self._active = False
        self._badge = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 10, 3)
        row.setSpacing(6)

        self._index = QLabel(str(stage.order + 1), self)
        self._index.setObjectName("MappingStageIndex")
        self._index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._index.setFixedSize(18, 18)
        row.addWidget(self._index, 0)

        self._name = QLabel(stage.short_label, self)
        self._name.setObjectName("MappingStageName")
        row.addWidget(self._name, 0)

        self._badge_label = QLabel("", self)
        self._badge_label.setObjectName("MappingStageBadge")
        self._badge_label.hide()
        row.addWidget(self._badge_label, 0)

        self._refresh()

    def text(self) -> str:
        parts = [self.stage.short_label]
        if self._badge:
            parts.append(self._badge)
        return "  ".join(parts)

    def isChecked(self) -> bool:
        return self._active

    def click(self) -> None:
        self.clicked.emit()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh()

    def set_badge(self, badge: str) -> None:
        self._badge = str(badge or "")
        self._refresh()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh(self) -> None:
        self.setProperty("active", self._active)
        self.setProperty("stageIndex", self.stage.order)
        if self._badge:
            self._badge_label.setText(self._badge)
            self._badge_label.setProperty("tone", _badge_tone(self._badge))
            self._badge_label.show()
        else:
            self._badge_label.hide()
            self._badge_label.setText("")
        _repolish(self)


class MappingStageBar(QFrame):
    """阶段切换条：层位选择 + [ 智能预测 ] — [ 约束/单因素 ] — [ 综合编图 ]。

    相图按层位进行；层位是工程预设或从数据发现的目录，下拉选择后写入
    ``project.stratigraphy.target_horizon``（不可手输）。
    """

    stage_requested = Signal(str)  # MappingStage.value
    horizon_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MappingStageBar")
        self._buttons: dict[MappingStage, _StageSegment] = {}
        self._tracks: list[QFrame] = []
        self._suppress_horizon = False
        self._last_committed_horizon: str | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(8)

        self.horizon_label = QLabel("层位", self)
        self.horizon_label.setObjectName("MappingStageMetaLabel")
        row.addWidget(self.horizon_label)
        self.horizon_combo = QComboBox(self)
        self.horizon_combo.setObjectName("MappingHorizonCombo")
        self.horizon_combo.setEditable(False)
        self.horizon_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.horizon_combo.setFixedWidth(160)
        self.horizon_combo.setPlaceholderText("选择层位")
        # R2 P2-3：紧凑视口隐藏「层位」前缀标签后，选中态唯一的语境说明；
        # 屏幕阅读器需要显式名（组合框本身不读占位文本）。
        self.horizon_combo.setAccessibleName("层位")
        self.horizon_combo.setToolTip(
            "编图层位：从工程层序格架或导入的层位数据中选择（相图按层位进行）")
        self.horizon_combo.currentIndexChanged.connect(
            lambda _i: self._commit_horizon())
        row.addWidget(self.horizon_combo, 0)

        divider = QFrame(self)
        divider.setObjectName("MappingStageDivider")
        divider.setFixedSize(1, 18)
        row.addWidget(divider)

        for index, stage in enumerate(STAGE_ORDER):
            segment = _StageSegment(stage, self)
            segment.clicked.connect(
                lambda value=stage.value: self.stage_requested.emit(value))
            self._buttons[stage] = segment
            row.addWidget(segment, 0)
            if index < len(STAGE_ORDER) - 1:
                track = QFrame(self)
                track.setObjectName("MappingStageTrack")
                track.setFixedSize(28, 2)
                row.addWidget(track, 0, Qt.AlignmentFlag.AlignVCenter)
                self._tracks.append(track)
        row.addStretch(1)

    def set_viewport_class(self, viewport) -> None:
        """V9 viewport 策略：紧凑视口隐藏「层位」前缀标签（下拉自带占位
        文案，语义不丢失），换取阶段条横向空间。"""
        from paleo_workbench.ui.dock_framework import ViewportClass

        self.horizon_label.setVisible(viewport is not ViewportClass.COMPACT)

    # -- 状态同步（由宿主/MappingStageController 驱动） --------------------------

    def set_current_stage(self, stage_value: str) -> None:
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        stage = stage_from_value(stage_value)
        for button_stage, button in self._buttons.items():
            button.set_active(stage is not None and button_stage == stage)
        current_order = stage.order if stage is not None else -1
        for index, track in enumerate(self._tracks):
            track.setProperty("complete", index < current_order)
            _repolish(track)

    def set_stage_badge(self, stage: MappingStage, badge: str) -> None:
        button = self._buttons.get(stage)
        if button is not None:
            button.set_badge(badge)

    def refresh_badges(self, badges: dict[str, str]) -> None:
        """批量更新徽标（key = stage.value）。"""
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        for value, badge in (badges or {}).items():
            stage = stage_from_value(value)
            if stage is not None:
                self.set_stage_badge(stage, badge)

    def current_horizon(self) -> str:
        return self.horizon_combo.currentText().strip()

    def set_horizon_state(self, horizon: str, options: list[str] | None = None) -> None:
        """同步工程层位到选择框（不发 ``horizon_requested``）。"""
        target = str(horizon or "").strip()
        choices: list[str] = []
        for name in list(options or []):
            text = str(name or "").strip()
            if text and text not in choices:
                choices.append(text)
        if target and target not in choices:
            choices.insert(0, target)
        self._suppress_horizon = True
        self.horizon_combo.clear()
        if choices:
            self.horizon_combo.addItems(choices)
        if target:
            index = self.horizon_combo.findText(target)
            if index < 0:
                self.horizon_combo.insertItem(0, target)
                index = 0
            self.horizon_combo.setCurrentIndex(index)
        else:
            self.horizon_combo.setCurrentIndex(-1)
        self._last_committed_horizon = target or None
        self._suppress_horizon = False

    def _commit_horizon(self) -> None:
        if self._suppress_horizon:
            return
        text = self.current_horizon()
        if text == self._last_committed_horizon:
            return
        self._last_committed_horizon = text or None
        self.horizon_requested.emit(text)
