from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from paleo_workbench import tokens
from paleo_workbench.ui.navigation import STAGE_DEFINITIONS


class WorkflowStepper(QFrame):
    """Top 44px ergonomic workflow stage stepper bar."""

    stage_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkflowStepper")
        self.setFixedHeight(44)
        self._active_stage_index = 0
        self.stage_buttons: list[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_1, tokens.SPACE_3, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_2)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        for idx, stage in enumerate(STAGE_DEFINITIONS):
            btn = QPushButton(f"{stage['badge']} {stage['name']}")
            btn.setToolTip(f"阶段 {idx + 1}: {stage['name']} · 快捷键 Ctrl+{idx + 1}")
            btn.setProperty("stageItem", True)
            btn.setProperty("active", idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(36)

            # Store closure index safely
            btn.clicked.connect(lambda _checked=False, i=idx: self._on_stage_clicked(i))

            self.stage_buttons.append(btn)
            layout.addWidget(btn)

            if idx < len(STAGE_DEFINITIONS) - 1:
                sep = QLabel("›")
                sep.setObjectName("StepperArrow")
                sep.setProperty("stepperArrow", True)
                layout.addWidget(sep)

        layout.addStretch()

    @property
    def active_stage_index(self) -> int:
        return self._active_stage_index

    def set_active_stage(self, index: int) -> None:
        if not (0 <= index < len(self.stage_buttons)):
            return
        if index == self._active_stage_index and self.stage_buttons[index].property("active"):
            return

        old = self._active_stage_index
        self._active_stage_index = index

        self.stage_buttons[old].setProperty("active", False)
        self.stage_buttons[index].setProperty("active", True)

        # Force stylesheet unpolish/polish refresh for Qt dynamic property
        for button in (self.stage_buttons[old], self.stage_buttons[index]):
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_stage_clicked(self, index: int) -> None:
        self.set_active_stage(index)
        self.stage_changed.emit(index)
