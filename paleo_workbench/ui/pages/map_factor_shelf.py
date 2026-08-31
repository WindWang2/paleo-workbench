from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid

_ICONS_DIR = Path(__file__).parent.parent.parent / "ui" / "assets" / "icons" / "map"


def _panel_icon(name: str) -> QIcon:
    path = _ICONS_DIR / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


class MapFactorShelf(QWidget):
    """Mapping bottom-tab shelf: factor cards + geological factor mapping actions."""

    contour_draft_requested = Signal()
    factor_overlay_requested = Signal(str)
    create_factor_map_requested = Signal()
    fault_interpretation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        actions = QHBoxLayout()
        actions.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, 0)

        self.create_factor_map_btn = QPushButton("新建单因素地质编图")
        self.create_factor_map_btn.setObjectName("PrimaryButton")
        self.create_factor_map_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.create_factor_map_btn.setToolTip("从井点属性执行空间克里金插值，生成包含栅格、等值线及井位标注的 GIS 图件")
        self.create_factor_map_btn.clicked.connect(self.create_factor_map_requested.emit)
        actions.addWidget(self.create_factor_map_btn)

        self.contour_draft_btn = QPushButton(_panel_icon("btn-contour-draft"), "从单因素生成等值线初稿")
        self.contour_draft_btn.setObjectName("SecondaryButton")
        self.contour_draft_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.contour_draft_btn.setToolTip(
            "对已完成网格的单因素任务提取 ContourDraft 并写入当前工程图件"
        )
        self.contour_draft_btn.clicked.connect(self.contour_draft_requested.emit)
        actions.addWidget(self.contour_draft_btn)

        self.fault_interpretation_btn = QPushButton("断层约束→解释版本")
        self.fault_interpretation_btn.setObjectName("SecondaryButton")
        self.fault_interpretation_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.fault_interpretation_btn.setToolTip(
            "把当前图件中断线/断层多段线提升为正式断层解释，保存为不可变解释版本（目录血缘）"
        )
        self.fault_interpretation_btn.clicked.connect(self.fault_interpretation_requested.emit)
        actions.addWidget(self.fault_interpretation_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.grid = FactorPreviewGrid()
        self.grid.card_clicked.connect(self._on_card_clicked)
        layout.addWidget(self.grid, 1)

        # Latest edit-view state, mirrored for card extent/cursor display.
        # FactorPreviewGrid has no extent/cursor paint hook, so the state is
        # stored only (display-only consumers can read it later).
        self._view_state: dict = {"center": (0.0, 0.0), "scale": 1.0}
        self._cursor_position: tuple[float, float] = (0.0, 0.0)

    def update_state(self, tasks: list) -> None:
        self.grid.update_state(tasks)

    def set_view_state(self, state: dict) -> None:
        self._view_state = dict(state)

    def view_state(self) -> dict:
        return dict(self._view_state)

    def set_cursor_position(self, xy: tuple[float, float]) -> None:
        self._cursor_position = (float(xy[0]), float(xy[1]))

    def cursor_position(self) -> tuple[float, float]:
        return self._cursor_position

    def _on_card_clicked(self, task) -> None:
        """Request the clicked factor card's output as a map overlay."""
        outputs = list(getattr(task, "output_resource_ids", None) or [])
        overlay_id = str(outputs[0]) if outputs else str(getattr(task, "id", "") or "")
        if overlay_id:
            self.factor_overlay_requested.emit(overlay_id)
