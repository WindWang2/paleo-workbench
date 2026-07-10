from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from paleo_workbench.ui import tokens

TOOL_IDS = ("select", "move", "vertex", "facies", "line", "label")
TOOL_LABELS = {
    "select": "选择",
    "move": "移动",
    "vertex": "节点",
    "facies": "相带",
    "line": "线",
    "label": "注记",
}


class MapEditToolbar(QWidget):
    """Exclusive edit tools plus snap, undo/redo, preview, and save draft actions."""

    tool_changed = Signal(str)
    snap_toggled = Signal(bool)
    preview_toggled = Signal(bool)
    topology_rebuild_requested = Signal()
    merge_facies_requested = Signal()
    split_facies_requested = Signal()
    save_draft_requested = Signal()
    generate_demo_draft_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapEditToolbar")
        self.setStyleSheet(
            f"QWidget#MapEditToolbar {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        layout.setSpacing(tokens.SPACE_1)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QPushButton] = {}

        for tool_id in TOOL_IDS:
            btn = QPushButton(TOOL_LABELS[tool_id])
            btn.setObjectName("SecondaryButton")
            btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
            btn.setCheckable(True)
            btn.setProperty("tool_id", tool_id)
            self._tool_group.addButton(btn)
            layout.addWidget(btn)
            self._tool_buttons[tool_id] = btn
            setattr(self, f"{tool_id}_btn", btn)

        self.select_btn.setChecked(True)
        self._tool_group.buttonClicked.connect(self._on_tool_clicked)

        self.snap_btn = QPushButton("捕捉")
        self.snap_btn.setObjectName("SecondaryButton")
        self.snap_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.snap_btn.setCheckable(True)
        self.snap_btn.toggled.connect(self.snap_toggled.emit)
        layout.addWidget(self.snap_btn)

        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("SecondaryButton")
        self.undo_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.undo_btn.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("重做")
        self.redo_btn.setObjectName("SecondaryButton")
        self.redo_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.redo_btn.clicked.connect(self.redo_requested.emit)
        layout.addWidget(self.redo_btn)

        self.preview_btn = QPushButton("图面预览")
        self.preview_btn.setObjectName("SecondaryButton")
        self.preview_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("切换 PaleoMapCanvas 图面预览（含图例/指北针/比例尺）")
        self.preview_btn.toggled.connect(self.preview_toggled.emit)
        layout.addWidget(self.preview_btn)

        self.topology_btn = QPushButton("重建拓扑")
        self.topology_btn.setObjectName("SecondaryButton")
        self.topology_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.topology_btn.setToolTip("共享节点捕捉 + 自交/邻接校验")
        self.topology_btn.clicked.connect(self.topology_rebuild_requested.emit)
        layout.addWidget(self.topology_btn)

        self.merge_btn = QPushButton("合并相带")
        self.merge_btn.setObjectName("SecondaryButton")
        self.merge_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.merge_btn.setToolTip("合并选中的两个相带多边形")
        self.merge_btn.clicked.connect(self.merge_facies_requested.emit)
        layout.addWidget(self.merge_btn)

        self.split_btn = QPushButton("分割相带")
        self.split_btn.setObjectName("SecondaryButton")
        self.split_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.split_btn.setToolTip("用选中的线分割选中的一个相带")
        self.split_btn.clicked.connect(self.split_facies_requested.emit)
        layout.addWidget(self.split_btn)

        layout.addStretch(1)

        self.generate_demo_draft_btn = QPushButton("生成演示草稿")
        self.generate_demo_draft_btn.setObjectName("SecondaryButton")
        self.generate_demo_draft_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.generate_demo_draft_btn.setToolTip("从预测相带区域生成可编辑的演示级编图草稿")
        self.generate_demo_draft_btn.clicked.connect(self.generate_demo_draft_requested.emit)
        layout.addWidget(self.generate_demo_draft_btn)

        self.save_draft_btn = QPushButton("保存编图草稿")
        self.save_draft_btn.setObjectName("PrimaryButton")
        self.save_draft_btn.setMinimumHeight(tokens.CONTROL_HEIGHT_LG)
        self.save_draft_btn.clicked.connect(self.save_draft_requested.emit)
        layout.addWidget(self.save_draft_btn)

        self._current_tool = "select"
        self._preview_mode = False

    def is_preview_mode(self) -> bool:
        return self._preview_mode

    def set_preview_mode(self, enabled: bool) -> None:
        """Sync button + disable exclusive edit tools while preview is on."""
        enabled = bool(enabled)
        self._preview_mode = enabled
        if self.preview_btn.isChecked() != enabled:
            self.preview_btn.blockSignals(True)
            self.preview_btn.setChecked(enabled)
            self.preview_btn.blockSignals(False)
        for btn in self._tool_buttons.values():
            btn.setEnabled(not enabled)
        self.snap_btn.setEnabled(not enabled)
        self.topology_btn.setEnabled(not enabled)
        self.merge_btn.setEnabled(not enabled)
        self.split_btn.setEnabled(not enabled)

    def current_tool(self) -> str:
        return self._current_tool

    def set_tool(self, tool_id: str) -> None:
        if tool_id not in self._tool_buttons:
            raise ValueError(f"Unknown tool: {tool_id}")
        btn = self._tool_buttons[tool_id]
        if not btn.isChecked():
            btn.setChecked(True)
        self._apply_tool(tool_id)

    def _on_tool_clicked(self, button: QPushButton) -> None:
        tool_id = button.property("tool_id")
        self._apply_tool(str(tool_id))

    def _apply_tool(self, tool_id: str) -> None:
        if tool_id == self._current_tool:
            return
        self._current_tool = tool_id
        self.tool_changed.emit(tool_id)
