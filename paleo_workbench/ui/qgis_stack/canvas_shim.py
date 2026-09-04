"""QgisCanvasShim：QGIS 画布承载，暴露 CompositeDocument 现行消费的
QgisCanvasShim（原 UnifiedMapCanvas）子集契约。M1 只承诺 pan/zoom 与图层镜像；
编辑类 tool_operation 在 M1 通过原生 pan/zoom 交互的 extent 变更时以
tool_operation(False) 发出（与 UnifiedMapCanvas 的鼠标/键盘路径语义对齐），
纯数据编辑的 True 语义 M3 由原生 QgsMapTool 编辑栈接管。"""
from __future__ import annotations

import json
import sys
import weakref

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "Polygon", "MultiPolygon": "Polygon"}


def _load_mapstack():
    try:
        from qgis_render_bridge.mapstack import QgisMapStack

        return QgisMapStack
    except ImportError as exc:
        raise RuntimeError(
            f"QGIS 渲染桥未安装或构建失败（qgis_render_bridge.mapstack 无法导入）；"
            f"请执行 PALEO_WITH_QGIS_RENDERER=1 {sys.executable} -m pip install -e native/qgis_render_bridge 重新构建安装"
            "（首次构建 vendored QGIS 需数小时）"
        ) from exc


class QgisCanvasShim(QWidget):
    # 实际消费者 CompositeDocument 消费的信号契约与 QgisCanvasShim（原 UnifiedMapCanvas）一致：
    # tool_operation(bool), extent_changed(tuple), map_position_changed(tuple),
    # backend_status_changed(str)。Brief 中的 Signal(str)/Signal() 为过时描述，
    # 此处以真实调用点为准（见复合文档 _on_tool_operation 签名）。
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    backend_status_changed = Signal(str)
    tool_operation = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        QgisMapStack = _load_mapstack()

        self.stack = QgisMapStack()
        self.stack.initialize()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._host = QgisCanvasHost(self.stack, self)
        layout.addWidget(self._host)
        self.canvas = self._host.canvas  # 真 QgsMapCanvas（测试可达）
        self._canvas_address = self._host.canvas_address
        self._native_canvas_address = int(self._canvas_address or 0)
        self._canvas_created = bool(self._native_canvas_address)
        self._canvas_destroyed = False
        self.events = StackEvents(self)
        self.events.attach(self.stack, self._canvas_address)
        # StackEvents emits (float,4) / (float,2); shim converts to unified tuple signatures.
        self.events.extent_changed.connect(self._on_stack_extent)
        self.events.map_position_changed.connect(self._on_stack_position)
        self._overlay_provider = None
        self._mirrored_layers: list[str] = []
        self._mirrored_doc_ids: list[str] = []
        self._shutdown_done = False
        self._tool_controller = None
        self._pending_programmatic = 0
        self._expected_programmatic_extents: list[tuple[float, float, float, float]] = []
        self._last_emitted_extent: tuple[float, float, float, float] | None = None
        self._tools_original_set_active = None
        self._tools_wrapped_target = None
        self._wrapped_func = None
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
        self._last_emitted_extent = initial

    def _is_fitted_compatible(self, expected: tuple[float, float, float, float], actual: tuple[float, float, float, float]) -> bool:
        if expected == actual:
            return True
        # QGIS aspect-fit expands one axis keeping center: actual should contain expected with same center
        ex_cx = (expected[0] + expected[2]) * 0.5
        ex_cy = (expected[1] + expected[3]) * 0.5
        ac_cx = (actual[0] + actual[2]) * 0.5
        ac_cy = (actual[1] + actual[3]) * 0.5
        if abs(ex_cx - ac_cx) > 1e-6 or abs(ex_cy - ac_cy) > 1e-6:
            return False
        # actual must contain expected
        if not (actual[0] <= expected[0] + 1e-9 and actual[2] >= expected[2] - 1e-9 and actual[1] <= expected[1] + 1e-9 and actual[3] >= expected[3] - 1e-9):
            return False
        return True

    def _on_stack_extent(self, xmin, ymin, xmax, ymax) -> None:
        extent = (float(xmin), float(ymin), float(xmax), float(ymax))
        # F2/F4: differentiate programmatic set_extent vs user pan/zoom (native tool)
        # Use expected list with fitted-compatibility to avoid consuming pending for unrelated resize events
        is_programmatic = False
        expected_list: list = getattr(self, "_expected_programmatic_extents", [])
        if expected_list:
            # Find first compatible expected extent
            compat_idx = -1
            for idx, exp in enumerate(expected_list):
                if self._is_fitted_compatible(exp, extent):
                    compat_idx = idx
                    break
                if exp == extent:
                    compat_idx = idx
                    break
            if compat_idx >= 0:
                is_programmatic = True
                # consume up to and including the compatible entry
                del expected_list[: compat_idx + 1]
                self._pending_programmatic = max(0, int(getattr(self, "_pending_programmatic", 0) or 0) - (compat_idx + 1))
            else:
                # Check pending counter fallback for exact equality without fitted logic (legacy)
                pending = int(getattr(self, "_pending_programmatic", 0) or 0)
                if pending > 0 and expected_list and expected_list[0] == extent:
                    is_programmatic = True
                    expected_list.pop(0)
                    self._pending_programmatic = max(0, pending - 1)
        else:
            pending = int(getattr(self, "_pending_programmatic", 0) or 0)
            if pending > 0:
                # No expected list but pending>0 — likely old path, treat as programmatic and decrement
                # Only consume if extent matches last history or last emitted to avoid stealing user events
                last_hist = self._extent_history[-1] if self._extent_history else None
                if last_hist is not None and (extent == last_hist or self._is_fitted_compatible(last_hist, extent)):
                    is_programmatic = True
                    self._pending_programmatic = max(0, pending - 1)
        if is_programmatic:
            # Programmatic path already emitted synchronously via set_extent.
            # If QGIS fitted extent differs from requested, silently correct history/last_emitted without second signal.
            if self._extent_history and self._extent_history[-1] != extent:
                if self._extent_history_index == len(self._extent_history) - 1:
                    self._extent_history[-1] = extent
                    self._last_emitted_extent = extent
                else:
                    if self._extent_history_index < len(self._extent_history) - 1:
                        self._extent_history = self._extent_history[: self._extent_history_index + 1]
                    self._extent_history.append(extent)
                    if len(self._extent_history) > 100:
                        self._extent_history.pop(0)
                    else:
                        self._extent_history_index = len(self._extent_history) - 1
                    self._last_emitted_extent = extent
            return
        # User-initiated (native pan/zoom) path
        if self._extent_history and self._extent_history[-1] == extent:
            if self._last_emitted_extent != extent:
                self.extent_changed.emit(extent)
                self._last_emitted_extent = extent
                try:
                    self.tool_operation.emit(False)
                except Exception:
                    pass
            return
        if self._extent_history_index < len(self._extent_history) - 1:
            self._extent_history = self._extent_history[: self._extent_history_index + 1]
        if not self._extent_history or self._extent_history[-1] != extent:
            self._extent_history.append(extent)
            if len(self._extent_history) > 100:
                self._extent_history.pop(0)
            else:
                self._extent_history_index = len(self._extent_history) - 1
        if self._last_emitted_extent != extent:
            self.extent_changed.emit(extent)
            self._last_emitted_extent = extent
        try:
            self.tool_operation.emit(False)
        except Exception:
            pass

    def _on_stack_position(self, x, y) -> None:
        self.map_position_changed.emit((float(x), float(y)))

    # --- 状态与几何 ---------------------------------------------------
    @property
    def backend_status(self) -> str:
        return "qgis: ready"

    @property
    def canvas_address(self) -> int:
        addr = int(getattr(self, "_canvas_address", 0) or 0)
        if addr:
            return addr
        # M-fix: only fallback if host still valid
        try:
            import shiboken6
            host = getattr(self, "_host", None)
            if host is not None and shiboken6.isValid(host):
                return int(getattr(host, "canvas_address", 0) or 0)
        except Exception:
            pass
        return 0

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
        # Track programmatic origin for F2/F4 deduplication (async StackEvents will be suppressed)
        self._pending_programmatic = int(getattr(self, "_pending_programmatic", 0) or 0) + 1
        lst = getattr(self, "_expected_programmatic_extents", None)
        if lst is not None:
            lst.append(tup)
        try:
            self.stack.set_canvas_extent(self.canvas_address, *tup)
        except Exception:
            self._pending_programmatic = max(0, int(getattr(self, "_pending_programmatic", 0) or 0) - 1)
            if lst is not None and lst and lst[-1] == tup:
                lst.pop()
            raise
        # Synchronous emit with dedupe against last emitted (F4)
        if getattr(self, "_last_emitted_extent", None) != tup:
            self.extent_changed.emit(tup)
            self._last_emitted_extent = tup
        else:
            # Already emitted same extent; pending will still be consumed by async handler without second emit
            pass

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
            # F3: use QGIS aspect-fitted extent (canvas_extent) for uniform mupp semantics
            try:
                xmin, ymin, xmax, ymax = tuple(self.stack.canvas_extent(self.canvas_address))
            except Exception:
                xmin, ymin, xmax, ymax = self.view_extent
            w = max(1, int(self.canvas.width() or self.width() or 1))
            h = max(1, int(self.canvas.height() or self.height() or 1))
            return max((xmax - xmin) / w, (ymax - ymin) / h) if w and h else 1.0
        except Exception:
            return 1.0

    def map_to_screen(self, point) -> tuple[float, float]:
        return tuple(self.stack.map_to_screen(self.canvas_address, float(point[0]), float(point[1])))

    def screen_to_map(self, point) -> tuple[float, float]:
        return tuple(self.stack.screen_to_map(self.canvas_address, float(point[0]), float(point[1])))

    def set_overlay_provider(self, provider) -> None:
        self._overlay_provider = provider  # M1 存而不画

    def _restore_tool_patch(self) -> None:
        try:
            tools = getattr(self, "_tools_wrapped_target", None)
            orig = getattr(self, "_tools_original_set_active", None)
            wrapped = getattr(self, "_wrapped_func", None)
            if tools is not None and orig is not None:
                cur = getattr(tools, "set_active_tool", None)
                if cur is wrapped:
                    tools.set_active_tool = orig  # type: ignore[method-assign]
        except Exception:
            pass
        self._tools_original_set_active = None
        self._tools_wrapped_target = None
        self._wrapped_func = None

    def set_map_tool_controller(self, controller) -> None:
        """Host 工具控制器绑定：M1 仅把 pan/zoom 映射到 QGIS 原生工具，其余保持 pan。"""
        self._tool_controller = controller
        try:
            self.stack.set_map_tool(self.canvas_address, "pan")
        except Exception:
            pass
        try:
            tools = getattr(controller, "tools", None)
            if tools is not None and hasattr(tools, "set_active_tool"):
                if getattr(self, "_tools_wrapped_target", None) is tools and getattr(self, "_wrapped_func", None) is not None:
                    return
                original = tools.set_active_tool
                self._tools_original_set_active = original
                self._tools_wrapped_target = tools
                self_ref = weakref.ref(self)

                def _wrapped(tool):
                    try:
                        original(tool)
                    except Exception:
                        pass
                    shim = self_ref()
                    if shim is None or getattr(shim, "_shutdown_done", False):
                        return
                    try:
                        addr = shim.canvas_address
                        if not addr:
                            return
                    except Exception:
                        return
                    tool_id = getattr(tool, "tool_id", "") if tool is not None else "pan"
                    kind = "pan"
                    if tool_id == "zoom_in":
                        kind = "zoomIn"
                    elif tool_id == "zoom_out":
                        kind = "zoomOut"
                    elif tool_id == "pan":
                        kind = "pan"
                    else:
                        kind = "pan"
                    try:
                        shim.stack.set_map_tool(addr, kind)
                    except Exception:
                        pass
                    try:
                        shim.setFocus()
                    except Exception:
                        pass

                self._wrapped_func = _wrapped
                tools.set_active_tool = _wrapped  # type: ignore[method-assign]
        except Exception:
            pass

    # --- 图层镜像 ------------------------------------------------------
    def set_layer_snapshot(self, snapshot) -> None:
        """Mirror snapshot vector layers into the QGIS project (incremental).

        Note (M2): reconcile by ``pwb/doc_id`` — unchanged layers keep their
        QgsVectorLayer object, tree state and renderer across publishes.
        Note (F3 gap, tracked for M2+): legacy ``scale_range`` 仍未转发。
        """
        if getattr(self, "_shutdown_done", False):
            return
        if snapshot.project_crs:
            try:
                self.stack.set_destination_crs(self.canvas_address, str(snapshot.project_crs))
            except Exception:
                pass
        seen: list[str] = []
        mirrored_qgis_ids: list[str] = []
        for layer in snapshot.layers:
            if layer.layer_type != "vector":
                continue
            features = [
                {"type": "Feature",
                 "geometry": f.get("geometry"),
                 "properties": dict(f.get("properties") or {})}
                for f in layer.features
            ]
            # 零要素图层同样上树（QGIS memory layer 零要素合法）——否则新建
            # 图层在首次数字化前从图层树消失（M2 终局审查 I1）。几何类型改由
            # metadata.geometry_kind 兜底（点/线/面），无则 Point。
            metadata = getattr(layer, "metadata", None) or {}
            if features:
                geom_raw = features[0].get("geometry") if isinstance(features[0], dict) else None
                geom_type = str(geom_raw.get("type", "")) if isinstance(geom_raw, dict) else ""
                geom = _GEOMETRY_TYPE.get(geom_type, "Point")
            else:
                _KIND_GEOM = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
                geom = _KIND_GEOM.get(str(metadata.get("geometry_kind") or ""), "Point")
            style_raw = getattr(layer, "style", None) or {}
            if not isinstance(style_raw, dict):
                try:
                    style_raw = dict(style_raw)
                except Exception:
                    style_raw = {}
            qgis_style = style_raw.get("qgis_style") if isinstance(style_raw, dict) else None
            has_qgis_renderer = False
            has_qgis_labeling = False
            renderer_xml = ""
            labeling_xml = ""
            legacy_style = None
            if isinstance(qgis_style, dict):
                renderer_xml = str(qgis_style.get("renderer_xml") or "")
                labeling_xml = str(qgis_style.get("labeling_xml") or "")
                has_qgis_renderer = bool(renderer_xml.strip())
                has_qgis_labeling = bool(labeling_xml.strip())
                if has_qgis_renderer or has_qgis_labeling:
                    legacy_style = None
                else:
                    legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"}
                    if not legacy_style:
                        legacy_style = None
            else:
                legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"} if isinstance(style_raw, dict) else None
                if legacy_style is not None and not legacy_style:
                    legacy_style = None
            try:
                qgis_id = self.stack.upsert_mirror_layer(
                    layer.id, layer.name or layer.id, geom,
                    layer.crs or snapshot.project_crs,
                    json.dumps({"type": "FeatureCollection", "features": features}),
                    renderer_xml, labeling_xml, legacy_style,
                    bool(layer.visible), float(layer.opacity),
                    is_reference=metadata.get("reference") == "true",
                    is_editable=metadata.get("editable") == "true",
                )
            except Exception as exc:
                if has_qgis_renderer or has_qgis_labeling:
                    msg = str(exc).lower()
                    if "renderer" in msg or "labeling" in msg or "invalid" in msg:
                        raise
                continue
            seen.append(layer.id)
            mirrored_qgis_ids.append(qgis_id)
        try:
            self.stack.remove_mirror_layers_except(seen)
            self.stack.set_mirror_layer_order(seen)
            self.stack.refresh_canvas(self.canvas_address)
        except Exception:
            pass
        try:
            # _mirrored_layers 保持 M1 语义：存 QGIS layer id；doc id 另存
            # _mirrored_doc_ids（reconcile 后两者一一对应，顺序同 snapshot）。
            self._mirrored_layers = list(mirrored_qgis_ids)
            self._mirrored_doc_ids = list(seen)
        except Exception:
            pass
        try:
            self.backend_status_changed.emit(self.backend_status)
        except Exception:
            pass

    def _cleanup_canvas(self) -> None:
        if getattr(self, "_canvas_destroyed", False):
            return
        addr = int(getattr(self, "_canvas_address", 0) or getattr(self, "_native_canvas_address", 0) or 0)
        if not addr and getattr(self, "_canvas_created", False):
            try:
                import shiboken6
                host = getattr(self, "_host", None)
                if host is not None and shiboken6.isValid(host):
                    addr = int(getattr(host, "canvas_address", 0) or 0)
            except Exception:
                addr = 0
        if not addr:
            self._canvas_destroyed = True
            return
        self._canvas_destroyed = True
        try:
            self.stack.clear_project_layers()
        except Exception:
            pass
        try:
            self.stack.destroy_canvas(int(addr))
        except Exception:
            pass

    def shutdown(self) -> None:
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._restore_tool_patch()
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
