"""QgisCanvasShim：QGIS 画布承载，暴露 CompositeDocument 现行消费的
UnifiedMapCanvas 子集契约。M1 只承诺 pan/zoom 与图层镜像；编辑类
tool_operation 记录状态消息，M3 由原生 QgsMapTool 编辑栈接管。"""
from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "Polygon", "MultiPolygon": "Polygon"}


class QgisCanvasShim(QWidget):
    # 实际消费者 CompositeDocument 消费的信号契约与 UnifiedMapCanvas 一致：
    # tool_operation(bool), extent_changed(tuple), map_position_changed(tuple),
    # backend_status_changed(str)。Brief 中的 Signal(str)/Signal() 为过时描述，
    # 此处以真实调用点为准（见复合文档 _on_tool_operation 签名）。
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    backend_status_changed = Signal(str)
    tool_operation = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        from qgis_render_bridge.mapstack import QgisMapStack

        self.stack = QgisMapStack()
        self.stack.initialize()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._host = QgisCanvasHost(self.stack, self)
        layout.addWidget(self._host)
        self.canvas = self._host.canvas  # 真 QgsMapCanvas（测试可达）
        self._canvas_address = self._host.canvas_address
        self.events = StackEvents(self)
        self.events.attach(self.stack, self._canvas_address)
        # StackEvents emits (float,4) / (float,2); shim converts to unified tuple signatures.
        self.events.extent_changed.connect(self._on_stack_extent)
        self.events.map_position_changed.connect(self._on_stack_position)
        self._overlay_provider = None
        self._mirrored_layers: list[str] = []
        self._shutdown_done = False
        self._tool_controller = None
        # 确保父部件销毁时也能回收桥接，避免 stale QgsLayerTreeMapCanvasBridge
        try:
            self.destroyed.connect(lambda _obj=None: self.shutdown())
        except Exception:
            pass
        try:
            self.canvas.destroyed.connect(lambda _obj=None: self.shutdown())
        except Exception:
            pass
        # 局部范围历史，映射 UnifiedMapCanvas 的 can_previous/can_next
        try:
            initial = tuple(self.stack.canvas_extent(self._canvas_address))
        except Exception:
            initial = (0.0, 0.0, 1.0, 1.0)
        self._extent_history: list[tuple[float, float, float, float]] = [initial]
        self._extent_history_index = 0

    def _on_stack_extent(self, xmin, ymin, xmax, ymax) -> None:
        extent = (float(xmin), float(ymin), float(xmax), float(ymax))
        # 同步更新本地历史（避免 duplicate：若已是最新则不追加）
        if self._extent_history and self._extent_history[-1] == extent:
            self.extent_changed.emit(extent)
            return
        # 若当前不在历史末端（用户回退后又平移），截断前方
        if self._extent_history_index < len(self._extent_history) - 1:
            self._extent_history = self._extent_history[: self._extent_history_index + 1]
        if not self._extent_history or self._extent_history[-1] != extent:
            self._extent_history.append(extent)
            if len(self._extent_history) > 100:
                self._extent_history.pop(0)
            else:
                self._extent_history_index = len(self._extent_history) - 1
        self.extent_changed.emit(extent)

    def _on_stack_position(self, x, y) -> None:
        self.map_position_changed.emit((float(x), float(y)))

    # --- 状态与几何 ---------------------------------------------------
    @property
    def backend_status(self) -> str:
        return "qgis: ready"

    @property
    def canvas_address(self) -> int:
        return getattr(self, "_canvas_address", 0) or getattr(self._host, "canvas_address", 0)

    @property
    def view_extent(self) -> tuple[float, float, float, float]:
        if getattr(self, "_shutdown_done", False):
            return self._extent_history[self._extent_history_index] if getattr(self, "_extent_history", None) else (0.0, 0.0, 1.0, 1.0)
        try:
            return tuple(self.stack.canvas_extent(self.canvas_address))
        except Exception:
            return self._extent_history[self._extent_history_index] if getattr(self, "_extent_history", None) else (0.0, 0.0, 1.0, 1.0)

    @property
    def can_previous_extent(self) -> bool:
        return self._extent_history_index > 0

    @property
    def can_next_extent(self) -> bool:
        return self._extent_history_index + 1 < len(self._extent_history)

    def set_extent(self, extent, *, record_history: bool = True, coalesce_history: bool = False) -> None:
        if self._shutdown_done:
            return
        tup = tuple(float(v) for v in extent)
        if record_history:
            if self._extent_history_index < len(self._extent_history) - 1:
                self._extent_history = self._extent_history[: self._extent_history_index + 1]
            if coalesce_history and self._extent_history:
                self._extent_history[-1] = tup
            elif self._extent_history[-1] != tup:
                self._extent_history.append(tup)
                if len(self._extent_history) > 100:
                    self._extent_history.pop(0)
                self._extent_history_index = len(self._extent_history) - 1
        self.stack.set_canvas_extent(self.canvas_address, *tup)
        # 同步发射以匹配 Unified 的同步语义；StackEvents 的异步回射会被去重。
        self.extent_changed.emit(tup)

    def previous_extent(self) -> bool:
        if not self.can_previous_extent:
            return False
        self._extent_history_index -= 1
        self.set_extent(self._extent_history[self._extent_history_index], record_history=False)
        return True

    def next_extent(self) -> bool:
        if not self.can_next_extent:
            return False
        self._extent_history_index += 1
        self.set_extent(self._extent_history[self._extent_history_index], record_history=False)
        return True

    def zoom_by(self, factor: float, center: tuple[float, float] | None = None, *, coalesce_history: bool = False) -> None:
        if factor <= 0.0:
            raise ValueError("zoom factor must be positive")
        xmin, ymin, xmax, ymax = self.view_extent
        cx, cy = center if center is not None else ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        cx = float(cx); cy = float(cy)
        self.set_extent(
            (
                cx + (xmin - cx) * factor,
                cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor,
                cy + (ymax - cy) * factor,
            ),
            coalesce_history=coalesce_history,
        )

    @property
    def map_units_per_pixel(self) -> float:
        try:
            xmin, ymin, xmax, ymax = self.view_extent
            w = max(1, int(self.canvas.width() or self.width() or 1))
            h = max(1, int(self.canvas.height() or self.height() or 1))
            # Uniform after letterboxing placeholder: use max span
            return max((xmax - xmin) / w, (ymax - ymin) / h) if w and h else 1.0
        except Exception:
            return 1.0

    def map_to_screen(self, point) -> tuple[float, float]:
        return tuple(self.stack.map_to_screen(self.canvas_address, float(point[0]), float(point[1])))

    def screen_to_map(self, point) -> tuple[float, float]:
        return tuple(self.stack.screen_to_map(self.canvas_address, float(point[0]), float(point[1])))

    def set_overlay_provider(self, provider) -> None:
        self._overlay_provider = provider  # M1 存而不画

    def set_map_tool_controller(self, controller) -> None:
        """Host 工具控制器绑定：M1 仅把 pan/zoom 映射到 QGIS 原生工具，其余保持 pan。"""
        self._tool_controller = controller
        # 尝试把初始工具同步为 pan
        try:
            self.stack.set_map_tool(self.canvas_address, "pan")
        except Exception:
            pass
        # 包装 set_active_tool 以在工具切换时同步 QGIS 工具
        try:
            tools = getattr(controller, "tools", None)
            if tools is not None and hasattr(tools, "set_active_tool"):
                original = tools.set_active_tool

                def _wrapped(tool):
                    original(tool)
                    tool_id = getattr(tool, "tool_id", "") if tool is not None else "pan"
                    kind = "pan"
                    if tool_id == "zoom_in":
                        kind = "zoomIn"
                    elif tool_id == "zoom_out":
                        kind = "zoomOut"
                    elif tool_id == "pan":
                        kind = "pan"
                    else:
                        # 编辑类工具 M1 保持 pan，不抛异常，状态由宿主 CompositeDocument 处理
                        kind = "pan"
                    try:
                        self.stack.set_map_tool(self.canvas_address, kind)
                    except Exception:
                        pass
                    try:
                        self.setFocus()
                    except Exception:
                        pass

                tools.set_active_tool = _wrapped  # type: ignore[method-assign]
        except Exception:
            pass

    # --- 图层镜像 ------------------------------------------------------
    def set_layer_snapshot(self, snapshot) -> None:
        if getattr(self, "_shutdown_done", False):
            return
        if snapshot.project_crs:
            try:
                self.stack.set_destination_crs(self.canvas_address, str(snapshot.project_crs))
            except Exception:
                pass
        try:
            self.stack.clear_project_layers()
        except Exception:
            pass
        self._mirrored_layers.clear()
        for layer in snapshot.layers:
            if not layer.visible or layer.layer_type != "vector":
                continue
            features = [
                {"type": "Feature",
                 "geometry": f.get("geometry"),
                 "properties": dict(f.get("properties") or {})}
                for f in layer.features
            ]
            if not features:
                continue
            geom_raw = features[0].get("geometry") if isinstance(features[0], dict) else None
            geom_type = str(geom_raw.get("type", "")) if isinstance(geom_raw, dict) else ""
            geom = _GEOMETRY_TYPE.get(geom_type, "Point")
            try:
                layer_id = self.stack.add_vector_layer_geojson(
                    layer.name or layer.id, geom, layer.crs or snapshot.project_crs,
                    json.dumps({"type": "FeatureCollection", "features": features}),
                )
            except Exception:
                continue
            if layer.opacity < 1.0:
                try:
                    self.stack.set_layer_opacity(layer_id, float(layer.opacity))
                except Exception:
                    pass
            self._mirrored_layers.append(layer_id)
        try:
            self.stack.refresh_canvas(self.canvas_address)
        except Exception:
            pass
        try:
            self.backend_status_changed.emit(self.backend_status)
        except Exception:
            pass

    def _cleanup_canvas(self) -> None:
        addr = getattr(self, "_canvas_address", 0)
        if not addr:
            return
        try:
            self.stack.clear_project_layers()
        except Exception:
            pass
        try:
            self.stack.destroy_canvas(addr)
        except Exception:
            pass

    def shutdown(self) -> None:
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        try:
            self.events.extent_changed.disconnect(self._on_stack_extent)
        except Exception:
            pass
        try:
            self.events.map_position_changed.disconnect(self._on_stack_position)
        except Exception:
            pass
        self._cleanup_canvas()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    def update(self) -> None:  # noqa: A003 — Qt 契约
        super().update()
        if getattr(self, "_shutdown_done", False):
            return
        try:
            self.stack.refresh_canvas(self.canvas_address)
        except Exception:
            pass
