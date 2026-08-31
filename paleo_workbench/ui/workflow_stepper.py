from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from paleo_workbench import tokens
from paleo_workbench.ui.navigation import STAGE_DEFINITIONS, get_subpages_for_stage


class WorkflowStepper(QFrame):
    """Slim progressive workflow stepper (28px) for the command header.

    Renders the four pipeline stages as numbered pills joined by connector
    lines that fill with the primary color up to the active stage, so the
    bar reads as progress through the pipeline rather than four loose
    buttons. Designed to live inside the MenuBar command header; it owns no
    border of its own.
    """

    stage_changed = Signal(int)

    _HEIGHT = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkflowStepper")
        # The header row sizes this bar; keep a sane standalone default.
        self.setFixedHeight(self._HEIGHT)
        self._active_stage_index = 0
        self._theme = "light"
        self.stage_buttons: list[QPushButton] = []
        self._connectors: list[QLabel] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_1)

        for idx, stage in enumerate(STAGE_DEFINITIONS):
            if idx > 0:
                connector = QLabel()
                connector.setObjectName("StepperConnector")
                connector.setFixedSize(16, 2)
                layout.addWidget(connector)
                self._connectors.append(connector)

            btn = QPushButton(f"{stage['badge']} {stage['name']}")
            btn.setToolTip(self._stage_tooltip(idx, stage))
            btn.setProperty("stageItem", True)
            btn.setProperty("active", idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Inline from token values: [stageItem] QSS ships 13px text with
            # comfortable padding, too tall for this slim bar.
            btn.setStyleSheet(
                f"font-size: {tokens.FONT_SIZE_STATUS}; padding: 1px 10px;"
            )

            # Store closure index safely
            btn.clicked.connect(lambda _checked=False, i=idx: self._on_stage_clicked(i))

            self.stage_buttons.append(btn)
            layout.addWidget(btn)

        self._apply_connectors()

    def _apply_connectors(self) -> None:
        """Connector fill state from the active palette (theme re-apply safe)."""
        palette = tokens.palette_for(self._theme)
        for seg, connector in enumerate(self._connectors):
            reached = seg < self._active_stage_index
            connector.setStyleSheet(
                "background: {};".format(
                    palette["PRIMARY"] if reached else palette["BORDER_STRONG"]
                )
            )

    def refresh_theme(self, theme: str = "light") -> None:
        """Switch the palette backing the inline connector colors."""
        self._theme = theme
        self._apply_connectors()

    @staticmethod
    def _stage_tooltip(idx: int, stage: dict) -> str:
        subpages = " · ".join(
            tokens.PAGE_NAMES[p] for p in get_subpages_for_stage(idx)
        )
        return f"阶段 {idx + 1}: {stage['name']}\n包含: {subpages}\n快捷键 Ctrl+{idx + 1}"

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

        # Progressive connectors: filled up to the active stage.
        self._apply_connectors()

    def _on_stage_clicked(self, index: int) -> None:
        self.set_active_stage(index)
        self.stage_changed.emit(index)
