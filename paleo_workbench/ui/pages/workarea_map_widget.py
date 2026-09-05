"""WorkAreaMapWidget — 可复用的 GIS 工区地图（井位 + 地震工区 + 边界）。

整个面板就是一张工区图：渲染走与首页/编图一致的
:func:`~paleo_workbench.ui.qgis_stack.display_canvas.create_display_canvas`
（桥可用为 QgsMapCanvas），数据来自纯生产者
:mod:`~paleo_workbench.mapping.workarea_map_snapshot`。只读交互：滚轮缩放、
中键/空格拖拽平移、左键拾取井位（选中 + 高亮 + 激活）。

工作站的井震联合「平面图」窗格与首页共用这一套，不再维护手绘地图副本。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.mapping.workarea_map_snapshot import (
    WELLS_FLAGGED_LAYER_ID,
    WELLS_LAYER_ID,
    WORKAREA_LEGEND_ITEMS,
    build_workarea_map_snapshot,
    domain_signature,
    workarea_view_extent,
)
from paleo_workbench.ui.qgis_stack.display_canvas import create_display_canvas

# 井符号拾取容差（屏幕像素），与首页一致。
_WELL_PICK_RADIUS_PX = 16.0


class WorkAreaMapWidget(QWidget):
    """整张工区地图：set_project 喂数据，点击井位发信号。"""

    well_selected = Signal(str)    # 单击选中（well_id）
    well_activated = Signal(str)   # 单击激活（well_id）——联合窗格直接开井

    def __init__(self, parent=None, *, title: str = "", show_legend: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("WorkAreaMapWidget")
        self._project = None
        self._snapshot = None
        self._signature: object = None
        self._selected_well_id = ""
        self._title = title
        # 小窗格（如井震联合平面图）可关掉图例，避免遮挡井位。
        self._show_legend = bool(show_legend)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.map_canvas = create_display_canvas(parent=self)
        self.map_canvas.set_overlay_provider(self._overlay_state)
        self.map_canvas.map_clicked.connect(self._on_map_clicked)
        layout.addWidget(self.map_canvas, 1)

    def shutdown(self) -> None:
        """Stop the render backend before the host destroys the widget.

        Canvas ``shutdown`` is idempotent; hidden panes (linked
        workspace 平面图) never get a reliable ``closeEvent``, so the host
        must call this on project switch / teardown.
        """
        self.map_canvas.shutdown()

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Rebind the project; snapshot rebuilds only on domain change."""
        self._project = project
        if project is None:
            self._snapshot = None
            self._signature = None
            return
        signature = domain_signature(project)
        if signature == self._signature:
            return
        self._signature = signature
        snapshot = build_workarea_map_snapshot(project)
        self._snapshot = snapshot
        self.map_canvas.set_layer_snapshot(snapshot)
        extent = workarea_view_extent(snapshot)
        if extent is not None:
            self.map_canvas.set_extent(extent)

    def zoom_to_all(self) -> None:
        if self._snapshot is None:
            return
        extent = workarea_view_extent(self._snapshot)
        if extent is not None:
            self.map_canvas.set_extent(extent)

    # ------------------------------------------------------------------
    # selection
    # ------------------------------------------------------------------

    def select_well(self, well_id: str, *, zoom: bool = False, emit: bool = False) -> None:
        """Highlight a well (yellow ring via overlay); optionally zoom to it."""
        well_id = str(well_id or "")
        self._selected_well_id = well_id
        feature = self._well_feature(well_id)
        if zoom and feature is not None:
            coords = (feature.get("geometry") or {}).get("coordinates") or ()
            if len(coords) >= 2:
                x, y = float(coords[0]), float(coords[1])
                half = self._current_half_span() * 0.2
                self.map_canvas.set_extent((x - half, y - half, x + half, y + half))
        self.map_canvas.update()
        if emit and well_id:
            self.well_selected.emit(well_id)

    def selected_well_id(self) -> str:
        return self._selected_well_id

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _overlay_state(self) -> dict:
        elements = ["比例尺", "指北针"]
        if self._title:
            elements.append("标题栏")
        if self._show_legend:
            elements.append("图例")
        state: dict = {
            "decorations": {
                "title": self._title,
                "elements": tuple(elements),
                "legend_items": [
                    {"label": label, "color": color} for label, color in WORKAREA_LEGEND_ITEMS
                ],
            }
        }
        feature = self._well_feature(self._selected_well_id)
        if feature is not None:
            state["selected_features"] = (feature,)
        return state

    def _well_feature(self, well_id: str) -> dict | None:
        if not well_id or self._snapshot is None:
            return None
        for layer in self._snapshot.layers:
            if layer.id not in (WELLS_LAYER_ID, WELLS_FLAGGED_LAYER_ID):
                continue
            for feature in layer.features:
                props = feature.get("properties") or {}
                if str(props.get("well_id") or "") == well_id:
                    return feature
        return None

    def _current_half_span(self) -> float:
        xmin, ymin, xmax, ymax = self.map_canvas.view_extent
        return max((xmax - xmin) / 2.0, (ymax - ymin) / 2.0, 1.0)

    def _on_map_clicked(self, point) -> None:
        """Left-click: pick the nearest well within the screen tolerance."""
        if self._snapshot is None:
            return
        try:
            click_screen = self.map_canvas.map_to_screen(
                (float(point[0]), float(point[1]))
            )
        except (TypeError, ValueError, IndexError, ArithmeticError):
            # #1166: ZeroDivisionError 是 ArithmeticError（退化 extent），
            # 原清单漏了它——“以为守了其实没守”。
            return
        best_id = ""
        best_dist = _WELL_PICK_RADIUS_PX
        for layer in self._snapshot.layers:
            if layer.id not in (WELLS_LAYER_ID, WELLS_FLAGGED_LAYER_ID):
                continue
            for feature in layer.features:
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates")
                if geometry.get("type") != "Point" or not coords:
                    continue
                screen = self.map_canvas.map_to_screen(
                    (float(coords[0]), float(coords[1]))
                )
                dx = screen.x() - click_screen.x()
                dy = screen.y() - click_screen.y()
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= best_dist:
                    best_dist = dist
                    best_id = str((feature.get("properties") or {}).get("well_id") or "")
        if best_id:
            self.select_well(best_id)
            self.well_selected.emit(best_id)
            self.well_activated.emit(best_id)
