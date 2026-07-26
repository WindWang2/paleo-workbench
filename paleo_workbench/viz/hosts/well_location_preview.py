from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from geoviz import (
    GeoVizEngine,
    PlotWidget,
    PreparedPreview,
    PreviewKind,
    XYPreviewPayload,
)


@dataclass(frozen=True)
class ActiveWell:
    """The selected well record for the lifetime of one prepared preview."""

    resource_id: str
    record_id: int
    point_index: int
    name: str
    x: float
    y: float


class WellLocationPreview(QWidget):
    """Workbench-owned well-location interaction around a generic XY plot."""

    active_well_changed = Signal(object)

    def __init__(
        self,
        engine: GeoVizEngine | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine or GeoVizEngine.default()
        plot = self.engine.create_widget(PreviewKind.XY_SCATTER, self)
        if not isinstance(plot, PlotWidget):
            raise TypeError("XY scatter backend must create a PlotWidget")
        self.plot = plot
        self.plot.set_equal_aspect(True)
        self.plot.point_hovered.connect(self._show_hovered_well)
        self.plot.point_hover_cleared.connect(self._clear_hover_tooltip)
        self.plot.point_clicked.connect(self._activate_clicked_well)
        self.plot.reset_requested.connect(self.reset_view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

        self.setFocusPolicy(Qt.StrongFocus)
        self._preview: PreparedPreview | None = None
        self._payload: XYPreviewPayload | None = None
        self.active_well: ActiveWell | None = None
        self._released = False

    def render(self, preview: PreparedPreview) -> None:
        if preview.kind is not PreviewKind.XY_SCATTER or not isinstance(
            preview.payload,
            XYPreviewPayload,
        ):
            raise TypeError("WellLocationPreview requires an XY well preview")
        if self._released:
            raise RuntimeError("cannot render a released WellLocationPreview")

        had_active_well = self.active_well is not None
        self._preview = preview
        self._payload = preview.payload
        self.active_well = None
        self.plot.setToolTip("")
        self.engine.render(self.plot, preview)
        if had_active_well:
            self.active_well_changed.emit(None)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self.engine.release(self.plot)

    def reset_view(self) -> None:
        had_active_well = self.active_well is not None
        self.active_well = None
        self.plot.clear_selected_point()
        self.plot.reset_view()
        if had_active_well:
            self.active_well_changed.emit(None)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.reset_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_hovered_well(
        self,
        _series_name: str,
        index: int,
        x: float,
        y: float,
    ) -> None:
        payload = self._payload
        if payload is None or index < 0 or index >= len(payload.names):
            self.plot.setToolTip("")
            return
        self.plot.setToolTip(
            f"{payload.names[index]}\nX {x:.3f}\nY {y:.3f}"
        )

    def _clear_hover_tooltip(self) -> None:
        self.plot.setToolTip("")

    def _activate_clicked_well(
        self,
        series_name: str,
        index: int,
        x: float,
        y: float,
    ) -> None:
        preview = self._preview
        payload = self._payload
        if (
            preview is None
            or payload is None
            or index < 0
            or index >= len(payload.names)
        ):
            return
        active_well = ActiveWell(
            resource_id=payload.resource_id or preview.title,
            record_id=(
                payload.record_ids[index]
                if index < len(payload.record_ids)
                else index
            ),
            point_index=index,
            name=payload.names[index],
            x=float(x),
            y=float(y),
        )
        self.active_well = active_well
        self.plot.set_selected_point(
            series_name,
            index,
            label=active_well.name,
        )
        self.plot.focus_point(x, y, zoom_factor=4.0)
        self.active_well_changed.emit(active_well)


__all__ = ["ActiveWell", "WellLocationPreview"]
