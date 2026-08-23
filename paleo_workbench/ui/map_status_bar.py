"""Compact status readout for the unified GIS canvas."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.ui import tokens

__all__ = ["MapStatusBar"]


class MapStatusBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapStatusBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_3)
        self.coordinate = QLabel("X: —  Y: —", self)
        self.scale = QLabel("Scale: —", self)
        self.crs = QLabel("CRS: —", self)
        self.render = QLabel("Renderer: —", self)
        self.selection = QLabel("Selection: 0", self)
        self.edit = QLabel("Read-only", self)
        for label in (self.coordinate, self.scale, self.crs, self.render, self.selection):
            label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; border: none; background: transparent; padding: 0 2px;"
            )
            layout.addWidget(label)
        # Read-only/Editing reads as a compact pill at the row end.
        self.edit.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER_LIGHT}; border-radius: 4px; padding: 1px 8px;"
        )
        layout.addWidget(self.edit)
        layout.addStretch(1)

    def update_state(
        self,
        *,
        point: tuple[float, float] | None = None,
        extent: tuple[float, float, float, float] | None = None,
        crs: str = "",
        renderer: str = "",
        selection_count: int = 0,
        editing: bool = False,
    ) -> None:
        if point is not None:
            self.coordinate.setText(f"X: {point[0]:.6g}  Y: {point[1]:.6g}")
        if extent is not None:
            width = max(0.0, extent[2] - extent[0])
            self.scale.setText(f"Width: {width:.6g}")
        self.crs.setText(f"CRS: {crs or 'unspecified'}")
        self.render.setText(f"Renderer: {renderer or '—'}")
        self.selection.setText(f"Selection: {int(selection_count)}")
        self.edit.setText("Editing" if editing else "Read-only")
        self.edit.setStyleSheet(
            f"color: {'#ffffff' if editing else tokens.TEXT_SECONDARY};"
            f" background: {tokens.PRIMARY if editing else tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.PRIMARY if editing else tokens.BORDER_LIGHT};"
            " border-radius: 4px; padding: 1px 8px;"
        )
