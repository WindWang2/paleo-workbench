"""CompositeView — 油藏综合图 host surface (Phase-2, T7 / #251).

Hosts a ``CartographyLayoutWindow`` scene (paper sheet + chrome +
FigurePanelGraphicsItem panels) inside a QGraphicsView. Subscribes to
``plot_bus.plot_changed`` and refreshes the panel whose ``source_plot_id``
matches (live: update() - the QGraphicsProxyWidget repaints itself;
snapshot: re-grab the source widget pixmap).

GL/engine source plots (section / fence_3d) must use snapshot mode; the
host wires the pixmap via ``panel.set_snapshot_pixmap(source.grab())``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from well_log_workstation.events import plot_bus
from well_log_workstation.plot_document import PanelRef
from well_log_workstation.workspace import Workspace


class CompositeView(QWidget):
    """Paper layout for the composite figure; refreshes embedded panels."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompositeView")
        self._workspace: Workspace | None = None
        self._layout_window: Any | None = None
        self._source_widgets: dict[str, Any] = {}  # plot_id -> source widget

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("来源图件："))
        self._source_combo = QComboBox()
        bar.addWidget(self._source_combo, 1)
        self._render_combo = QComboBox()
        self._render_combo.addItems(["live", "snapshot"])
        bar.addWidget(QLabel("渲染："))
        bar.addWidget(self._render_combo)
        add_btn = QPushButton("添加面板")
        add_btn.clicked.connect(self._on_add_panel)
        bar.addWidget(add_btn)
        root.addLayout(bar)

        # Paper view
        self._view_host = QWidget()
        vh = QVBoxLayout(self._view_host)
        vh.setContentsMargins(0, 0, 0, 0)
        self._paper_view: QGraphicsView | None = None
        root.addWidget(self._view_host, 1)

        # Subscribe to the plot bus (T7 dynamic refresh).
        plot_bus.plot_changed.connect(self._on_plot_changed)

    # -- workspace wiring ----------------------------------------------

    def set_workspace(self, ws: Workspace | None) -> None:
        """Bind the workspace; populate the panel source palette."""
        self._workspace = ws
        self._source_combo.clear()
        if ws is None:
            return
        plot_ids = [p.id for p in ws.plots if p.type != "composite"]
        self._source_combo.addItems(plot_ids)
        self._ensure_layout_window()
        if self._layout_window is not None:
            self._layout_window.set_plot_sources(plot_ids)

    def register_source_widget(self, plot_id: str, widget: Any) -> None:
        """Register the live widget for a source plot (for snapshot grabs)."""
        self._source_widgets[plot_id] = widget

    # -- layout window --------------------------------------------------

    def _ensure_layout_window(self):
        """Lazily construct the cartography layout window's scene/view."""
        if self._layout_window is not None:
            return self._layout_window
        try:
            from geoviz_paleo_map.cartography.window import (
                CartographyLayoutWindow,
            )
        except Exception:
            return None
        win = CartographyLayoutWindow()
        self._layout_window = win
        # Re-parent the paper view into this widget.
        view = win._view
        view.setParent(self._view_host)
        self._view_host.layout().addWidget(view)
        self._paper_view = view
        if self._workspace is not None:
            win.set_plot_sources(
                [p.id for p in self._workspace.plots if p.type != "composite"]
            )
        return win

    # -- panels ---------------------------------------------------------

    def _on_add_panel(self) -> None:
        source = self._source_combo.currentText()
        if not source:
            return
        win = self._ensure_layout_window()
        if win is None:
            return
        render_mode = self._render_combo.currentText()
        source_type = "single_well"
        if self._workspace is not None:
            entry = next(
                (p for p in self._workspace.plots if p.id == source), None
            )
            if entry is not None:
                source_type = entry.type
        item = win.add_figure_panel(
            source,
            source_plot_type=source_type,
            render_mode=render_mode,
        )
        # Snapshot mode: grab the source widget now (if registered).
        if render_mode == "snapshot":
            widget = self._source_widgets.get(source)
            if widget is not None:
                try:
                    item.set_snapshot_pixmap(widget.grab())
                except Exception:
                    pass

    def figure_panels(self):
        win = self._layout_window
        if win is None:
            return []
        return win.figure_panels()

    def add_panel_ref(self, panel: PanelRef) -> None:
        """Add a panel from a persisted PanelRef (open_plot_document path)."""
        win = self._ensure_layout_window()
        if win is None:
            return
        rect = None
        if panel.rect_mm is not None and len(panel.rect_mm) == 4:
            rect = QRectF(*panel.rect_mm)
        item = win.add_figure_panel(
            panel.plot_id,
            source_plot_type=panel.source_plot_type,
            render_mode=panel.render_mode,
            rect_mm=rect,
        )
        if panel.render_mode == "snapshot":
            widget = self._source_widgets.get(panel.plot_id)
            if widget is not None:
                try:
                    item.set_snapshot_pixmap(widget.grab())
                except Exception:
                    pass

    # -- refresh --------------------------------------------------------

    def _on_plot_changed(self, plot_id: str, revision: int) -> None:
        """Refresh the panel whose source plot changed (T7)."""
        for panel in self.figure_panels():
            if panel.source_plot_id != plot_id:
                continue
            if panel.render_mode == "snapshot":
                widget = self._source_widgets.get(plot_id)
                if widget is not None:
                    try:
                        panel.set_snapshot_pixmap(widget.grab())
                    except Exception:
                        pass
            else:
                panel.refresh()  # live proxy repaints itself; update() only
