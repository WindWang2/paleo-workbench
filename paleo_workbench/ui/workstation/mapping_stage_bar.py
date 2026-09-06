"""``MappingStageBar``：编图阶段切换控件（AppBar 附近的紧凑分段条）。

风格（V5 §34/§62/§63）：compact / professional / desktop workstation，
不是大卡片；不做整页彩色主题，阶段只经 active 指示 + 小徽标表达。
切换瞬时（组可见性增量），绝不重载工程/画布。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping_workspace.stages import STAGE_ORDER, MappingStage


class _StageButton(QPushButton):
    """单个阶段分段按钮：短标签 + 状态徽标（active/ready/warning/stale）。"""

    def __init__(self, stage: MappingStage, parent: QWidget | None = None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("WorkstationContextButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(stage.description)
        self._badge = ""
        self._refresh()

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self._refresh()

    def set_badge(self, badge: str) -> None:
        self._badge = str(badge or "")
        self._refresh()

    def _refresh(self) -> None:
        parts = [self.stage.short_label]
        if self._badge:
            parts.append(self._badge)
        self.setText("  ".join(parts))
        self.setProperty("stageIndex", self.stage.order)
        self.style().unpolish(self)
        self.style().polish(self)


class MappingStageBar(QFrame):
    """阶段切换条：[ 初始相图 ] — [ 约束/单因素 ] — [ 综合编图 ]。"""

    stage_requested = Signal(str)  # MappingStage.value

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MappingStageBar")
        self._buttons: dict[MappingStage, _StageButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        title_row = QHBoxLayout()
        title = QLabel("编图阶段", self)
        title.setObjectName("WorkstationPanelFootnote")
        title_row.addWidget(title)
        title_row.addStretch(1)
        outer.addLayout(title_row)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(4)
        for index, stage in enumerate(STAGE_ORDER):
            button = _StageButton(stage, self)
            button.clicked.connect(
                lambda _checked=False, value=stage.value: self.stage_requested.emit(value))
            self._buttons[stage] = button
            buttons_row.addWidget(button, 1)
            if index < len(STAGE_ORDER) - 1:
                connector = QLabel("—", self)
                connector.setObjectName("WorkstationPanelFootnote")
                connector.setAlignment(Qt.AlignmentFlag.AlignCenter)
                connector.setSizePolicy(
                    QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                buttons_row.addWidget(connector)
        outer.addLayout(buttons_row)

    # -- 状态同步（由宿主/MappingStageController 驱动） --------------------------

    def set_current_stage(self, stage_value: str) -> None:
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        stage = stage_from_value(stage_value)
        for button_stage, button in self._buttons.items():
            button.set_active(stage is not None and button_stage == stage)

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
