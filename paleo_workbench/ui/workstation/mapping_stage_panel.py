"""``MappingStagePanel``：阶段上下文面板（QStackedWidget 三页，V5 §35）。

**中央地图不切**——只有本 dock 内容随阶段切换。每页包含：

* 阶段就绪度清单（可点击定位，V5 §54）；
* 阶段专属上下文动作（RAW→DERIVED 建稿 / typed 约束创建 / 证据选择…）；
* 阶段说明（折叠为脚注文本）。

面板只发请求信号；工作流执行在宿主（CompositeDocument/WorkstationFrame
的接线层），面板自身不触碰 QGIS/Catalog。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping_workspace.layer_roles import ConstraintKind
from paleo_workbench.mapping_workspace.readiness import (
    ReadinessItemStatus,
    StageReadiness,
)
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.ui.workstation.stage_actions import stage_context_actions

# V7 §6：就绪度 glyph 归一到 state_language（readiness 词表）。
from paleo_workbench.ui.workstation.state_language import state_token as _state_token

_STATUS_GLYPHS = {
    ReadinessItemStatus.OK: _state_token("readiness", "ok").glyph,
    ReadinessItemStatus.WARNING: _state_token("readiness", "warning").glyph,
    ReadinessItemStatus.ERROR: _state_token("readiness", "error").glyph,
    ReadinessItemStatus.INFO: _state_token("readiness", "info").glyph,
}


def _narrow_list(widget: QListWidget) -> None:
    """侧栏清单不得用长文本撑开 dock 最小宽度。"""
    widget.setMinimumWidth(0)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    widget.setWordWrap(True)
    widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    widget.setAlternatingRowColors(False)


class _ReadinessList(QListWidget):
    """就绪度清单：每项 status glyph + 标题；点击发定位请求。"""

    item_located = Signal(str)  # check target

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StageReadinessList")
        _narrow_list(self)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.itemClicked.connect(self._on_clicked)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def _on_clicked(self, item: QListWidgetItem) -> None:
        target = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if target:
            self.item_located.emit(target)

    def show_readiness(self, readiness: StageReadiness | None) -> None:
        self.clear()
        if readiness is None:
            return
        for item in readiness.sorted_items():
            glyph = _STATUS_GLYPHS.get(item.status, "·")
            label = f"{glyph}  {item.title}"
            if item.detail:
                label += f" — {item.detail}"
            row = QListWidgetItem(label, self)
            row.setData(Qt.ItemDataRole.UserRole, item.target)
            row.setToolTip(item.detail or item.title)


class _CommandList(QListWidget):
    """阶段动作清单：一行一个动作，点击执行。宽度跟随侧栏，不横向撑开。"""

    action_requested = Signal(str)

    def __init__(self, commands: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StageCommandList")
        _narrow_list(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.itemClicked.connect(self._on_clicked)
        for action_id, title in commands:
            row = QListWidgetItem(title, self)
            row.setData(Qt.ItemDataRole.UserRole, action_id)
            row.setToolTip(title)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        action_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if action_id:
            self.action_requested.emit(action_id)

    def sizeHint(self) -> QSize:
        rows = self.count()
        if rows <= 0:
            return QSize(0, 0)
        row_h = max(int(self.sizeHintForRow(0) or 0), 22)
        return QSize(0, rows * row_h + 2 * self.frameWidth() + 4)

    def minimumSizeHint(self) -> QSize:
        hint = self.sizeHint()
        return QSize(0, hint.height())


def _fill_button(title: str, parent: QWidget, tooltip: str = "") -> QPushButton:
    button = QPushButton(title, parent)
    button.setObjectName("WorkstationContextButton")
    button.setToolTip(tooltip or title)
    button.setMinimumWidth(0)
    button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class _StagePage(QFrame):
    """单阶段页：就绪度 + 上下文动作 + 说明脚注。"""

    action_requested = Signal(str)  # context action id
    locate_requested = Signal(str)

    def __init__(
        self,
        stage: MappingStage,
        actions: list[tuple[str, str]],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("PanelCard")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel(stage.label, self)
        header.setObjectName("WorkstationPanelHeader")
        header.setWordWrap(True)
        header.setMinimumWidth(0)
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(header)

        ready_row = QHBoxLayout()
        ready_row.setContentsMargins(0, 0, 0, 0)
        readiness_label = QLabel("就绪度", self)
        readiness_label.setObjectName("WorkstationPanelFootnote")
        self.readiness_status = QLabel("", self)
        self.readiness_status.setObjectName("WorkstationPanelFootnote")
        self.readiness_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ready_row.addWidget(readiness_label)
        ready_row.addStretch(1)
        ready_row.addWidget(self.readiness_status)
        layout.addLayout(ready_row)

        self.readiness = _ReadinessList(self)
        self.readiness.item_located.connect(self.locate_requested.emit)
        layout.addWidget(self.readiness, 1)

        self.actions: _CommandList | None = None
        if actions:
            actions_label = QLabel("阶段动作", self)
            actions_label.setObjectName("WorkstationPanelFootnote")
            layout.addWidget(actions_label)
            self.actions = _CommandList(list(actions), self)
            self.actions.action_requested.connect(self.action_requested.emit)
            layout.addWidget(self.actions, 0)

        footer = QLabel(stage.description, self)
        footer.setObjectName("WorkstationPanelFootnote")
        footer.setWordWrap(True)
        footer.setMinimumWidth(0)
        footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(footer)

    def show_readiness(self, readiness: StageReadiness | None) -> None:
        self.readiness.show_readiness(readiness)
        if readiness is not None:
            self.readiness_status.setText(readiness.label)


class MappingStagePanel(QWidget):
    """阶段上下文 dock 内容（QStackedWidget 三页；中央地图永不切换）。"""

    action_requested = Signal(str, str)  # (stage.value, action_id)
    locate_requested = Signal(str, str)  # (stage.value, target)
    stage_switch_requested = Signal(str)

    # V7 R2-F1：阶段动作词表派生自 dispatcher 单表（不再手维护第二份）。
    _PHASE1_ACTIONS = list(stage_context_actions("facies_calibration"))
    _PHASE2_ACTIONS = list(stage_context_actions("constraint_factor"))
    _PHASE3_ACTIONS = list(stage_context_actions("integrated_compilation"))
    _CONSTRAINT_ACTIONS = [
        (ConstraintKind.PROVENANCE_LINE, "物源线"),
        (ConstraintKind.SOURCE_DIRECTION, "物源方向"),
        (ConstraintKind.DISTRIBUTION_LINE, "展布线"),
        (ConstraintKind.PALEO_SHORELINE, "古岸线"),
        (ConstraintKind.FACIES_BOUNDARY, "相带边界"),
        (ConstraintKind.FAULT, "断层"),
        (ConstraintKind.MASK, "掩膜"),
    ]

    constraint_requested = Signal(str)  # ConstraintKind.value

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MappingStagePanel")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        self.stack.setMinimumWidth(0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._pages: dict[MappingStage, _StagePage] = {}
        self._constraints_row: QWidget | None = None
        for stage, actions in (
            (MappingStage.FACIES_CALIBRATION, self._PHASE1_ACTIONS),
            (MappingStage.CONSTRAINT_FACTOR, self._PHASE2_ACTIONS),
            (MappingStage.INTEGRATED_COMPILATION, self._PHASE3_ACTIONS),
        ):
            page = _StagePage(stage, actions, self)
            page.action_requested.connect(
                lambda action, value=stage.value: self.action_requested.emit(value, action))
            page.locate_requested.connect(
                lambda target, value=stage.value: self.locate_requested.emit(value, target))
            self._pages[stage] = page
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        # Phase 2 专属：typed 约束创建行（V5 §22/§50）。
        self._build_constraints_row(layout)
        self._update_constraints_visibility(MappingStage.FACIES_CALIBRATION)

    def _build_constraints_row(self, layout: QVBoxLayout) -> None:
        box = QFrame(self)
        box.setObjectName("PanelCard")
        box.setMinimumWidth(0)
        row = QVBoxLayout(box)
        row.setContentsMargins(8, 6, 8, 6)
        label = QLabel("新建地质约束", box)
        label.setObjectName("WorkstationPanelFootnote")
        row.addWidget(label)
        buttons = QGridLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        for index, (kind, title) in enumerate(self._CONSTRAINT_ACTIONS):
            button = _fill_button(
                title, box, tooltip=f"新建 {kind.label}（{kind.geometry_kind}）")
            button.clicked.connect(
                lambda _checked=False, value=kind.value: self.constraint_requested.emit(value))
            buttons.addWidget(button, index // 2, index % 2)
        row.addLayout(buttons)
        layout.addWidget(box)
        self._constraints_row = box

    def _update_constraints_visibility(self, stage: MappingStage) -> None:
        if self._constraints_row is not None:
            self._constraints_row.setVisible(stage == MappingStage.CONSTRAINT_FACTOR)

    # -- 状态驱动 ---------------------------------------------------------------

    def set_stage(self, stage_value: str) -> None:
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        stage = stage_from_value(stage_value)
        if stage is None:
            return
        page = self._pages.get(stage)
        if page is not None:
            self.stack.setCurrentWidget(page)
        self._update_constraints_visibility(stage)

    def show_readiness(self, stage: MappingStage, readiness: StageReadiness | None) -> None:
        page = self._pages.get(stage)
        if page is not None:
            page.show_readiness(readiness)
