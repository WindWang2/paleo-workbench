from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from paleo_workbench.ui import tokens

TOOL_IDS = ("select", "move", "vertex", "line", "label")
TOOL_LABELS = {
    "select": "选择",
    "move": "移动",
    "vertex": "节点",
    "line": "线",
    "label": "注记",
}


class MapEditToolbar(QWidget):
    """Exclusive edit tools plus snap, undo/redo, and save draft actions."""

    tool_changed = Signal(str)
    snap_toggled = Signal(bool)
    save_draft_requested = Signal()
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
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QPushButton] = {}

        for tool_id in TOOL_IDS:
            btn = QPushButton(TOOL_LABELS[tool_id])
            btn.setObjectName("SecondaryButton")
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
        self.snap_btn.setCheckable(True)
        self.snap_btn.toggled.connect(self.snap_toggled.emit)
        layout.addWidget(self.snap_btn)

        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("SecondaryButton")
        self.undo_btn.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("重做")
        self.redo_btn.setObjectName("SecondaryButton")
        self.redo_btn.clicked.connect(self.redo_requested.emit)
        layout.addWidget(self.redo_btn)

        layout.addStretch(1)

        self.save_draft_btn = QPushButton("保存编图草稿")
        self.save_draft_btn.setObjectName("PrimaryButton")
        self.save_draft_btn.clicked.connect(self.save_draft_requested.emit)
        layout.addWidget(self.save_draft_btn)

        self._current_tool = "select"

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
