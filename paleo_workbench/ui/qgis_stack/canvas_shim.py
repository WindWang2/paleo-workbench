"""QgisCanvasShim：QGIS 画布承载，暴露 CompositeDocument 现行消费的
QgisCanvasShim（原 UnifiedMapCanvas）子集契约。M1 只承诺 pan/zoom 与图层镜像；
编辑类 tool_operation 在 M1 通过原生 pan/zoom 交互的 extent 变更时以
tool_operation(False) 发出（与 UnifiedMapCanvas 的鼠标/键盘路径语义对齐），
纯数据编辑的 True 语义 M3 由原生 QgsMapTool 编辑栈接管。

B8（identify/measure/export 接线）：
- identify：工具映射表直连桥 QgsMapToolIdentifyFeature（kind "identify"），
  回调结果经 :attr:`native_identified` 转发——原生路径的单一识别入口。
- measure：桥无原生量距工具，激活期由 :class:`_CanvasMouseRouter` 把画布
  视口鼠标事件换算为地图坐标喂给活动 Python 工具（MapToolController 权威
  不变），分段距离经 :attr:`measure_segment` / :attr:`measure_preview` 发出。
- export：``export_png/export_svg/export_pdf/export_capabilities`` 与
  UnifiedMapCanvas 同契约，export_service 经能力探测识别本类。
"""
from __future__ import annotations

import json
import math
import sys
import time
import weakref

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from paleo_workbench.resources.exporters import ExportError
from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost


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


class _CanvasMouseRouter(QObject):
    """B8：measure_distance 激活期把画布视口鼠标事件路由给活动 Python 工具。

    QGIS 画布的鼠标输入默认只进原生 QgsMapTool（桥无 measure 工具）。
    该过滤器装在 ``canvas.viewport()`` 上：按键类事件（press/release/
    dblclick）拦截消费、换算地图坐标喂给活动 Python 工具（右键=取消）；
    MouseMove 只读不拦（转发回画布），保住状态条 xyCoordinates 跟手，
    也不会让 QgsMapToolPan 起拖（press 已被拦，pan 的 mDragging 不置位）。
    """

    _ROUTED_TYPES = (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseMove,
    )

    def __init__(self, shim: "QgisCanvasShim") -> None:
        super().__init__(shim)
        self._shim_ref = weakref.ref(shim)
        self.active = False
        self._installed_on: QWidget | None = None

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        shim = self._shim_ref()
        viewport = shim._canvas_viewport() if shim is not None else None
        if self._installed_on is not None and self._installed_on is not viewport:
            self._installed_on.removeEventFilter(self)
            self._installed_on = None
        if active and viewport is not None and self._installed_on is not viewport:
            viewport.installEventFilter(self)
            self._installed_on = viewport

    def detach(self) -> None:
        self.active = False
        if self._installed_on is not None:
            try:
                self._installed_on.removeEventFilter(self)
            except Exception:
                pass
            self._installed_on = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        shim = self._shim_ref()
        if shim is None or not self.active or getattr(shim, "_shutdown_done", False):
            return False
        if event.type() not in self._ROUTED_TYPES:
            return False
        try:
            return shim._route_measure_mouse(event)
        except Exception:
            return False


class QgisCanvasShim(QWidget):
    # 实际消费者 CompositeDocument 消费的信号契约与 QgisCanvasShim（原 UnifiedMapCanvas）一致：
    # tool_operation(bool), extent_changed(tuple), map_position_changed(tuple),
    # backend_status_changed(str)。Brief 中的 Signal(str)/Signal() 为过时描述，
    # 此处以真实调用点为准（见复合文档 _on_tool_operation 签名）。
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    backend_status_changed = Signal(str)
    tool_operation = Signal(bool)
    # B8：原生 identify 结果（桥 QgsMapToolIdentifyFeature → 回调转发）。
    # payload: {"layer_doc_id": str, "feature_id": str}；原生路径的单一识别
    # 结果入口（消费方仍以 Python feature_query_index 面板为权威，未接双面板）。
    native_identified = Signal(dict)
    # B8：量距分段完成 / 实时预览（地图单位）。
    measure_segment = Signal(float)
    measure_preview = Signal(float)

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
        self._mirror_failures: list[str] = []
        self._shutdown_done = False
        self._tool_controller = None
        self._pending_programmatic = 0
        self._expected_programmatic_extents: list[tuple[float, float, float, float]] = []
        self._last_emitted_extent: tuple[float, float, float, float] | None = None
        self._tools_original_set_active = None
        self._tools_wrapped_target = None
        self._wrapped_func = None
        # B8：量距事件路由（仅 measure_distance 激活期挂画布视口过滤器）。
        self._measure_router = _CanvasMouseRouter(self)
        self._last_measure_emit: float | None = None
        # Qt 树析构期间触发的 destroyed 回调只做状态记账：半析构画布上再进
        # destroy_canvas/unsetMapTool 会踩悬空子对象（native 栈已证实）。
        # 画布的桥表回收由桥在 canvas destroyed 时自行完成；orderly 关闭仍走
        # shutdown()（宿主在拆树前显式调用）。
        try:
            self.destroyed.connect(lambda _obj=None: self._mark_disposed())
        except Exception:
            pass
        try:
            self.canvas.destroyed.connect(lambda _obj=None: self._mark_disposed())
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
        failures = getattr(self, "_mirror_failures", None) or []
        if failures:
            return f"qgis: degraded ({len(failures)} mirror failures)"
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
        # #1165: inf/NaN 会在 set_extent 生成非有限坐标直通 C++（现在
        # setCanvasExtent 也会拒绝，这里是第一道入口守卫）。
        factor = float(factor)
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("zoom factor must be finite and positive")
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

    def set_snapping_config(self, config: dict) -> None:
        """捕捉配置下推 QGIS canvas snappingUtils（M3）。

        config 形如 ``{"enabled": bool, "mode": "all_layers"|"active_layer",
        "tolerance_px": float, "types": [...], "reference_enabled": bool,
        "layers": {doc_id: {"enabled": bool, "types": [...], "tolerance_px": float}}}``；
        状态权威仍是 Python SnappingService，这里只是投影。grid 捕捉为
        Python 专有模式，QGIS 端无对应物，不下推。
        """
        if getattr(self, "_shutdown_done", False) or not self.canvas_address:
            return
        try:
            self.stack.set_snapping_config(self.canvas_address, json.dumps(config))
        except Exception:
            pass

    def set_current_layer(self, doc_id: str) -> None:
        """画布当前图层（原生选择/identify 的目标图层）；空串/未知 id 忽略。"""
        if getattr(self, "_shutdown_done", False) or not self.canvas_address:
            return
        if not doc_id:
            return
        try:
            self.stack.set_current_layer(self.canvas_address, str(doc_id))
        except Exception:
            pass

    def native_tool_busy(self) -> bool:
        """原生工具是否占有 Esc 语义（M3 Task 5）：采点中/顶点·移动拖动中。

        busy 时 Esc 应直接派发画布（原生工具取消本次捕捉/拖动，工具保持
        激活），不走 Python 工具栈的取消——否则原生工具还停在激活态而
        Python 侧已切走，状态错乱。
        """
        if getattr(self, "_shutdown_done", False) or not self.canvas_address:
            return False
        try:
            return bool(self.stack.native_tool_busy(self.canvas_address))
        except Exception:
            return False

    def cancel_native_tool(self) -> None:
        """把 Esc 直接派发画布（postEvent）：采点工具经 canvas keyPressEvent
        转发触发 digitizingCanceled；顶点/移动拖动中经 canvas keyPressed
        信号（拖动中画布不转发 keyPressEvent）触发 cancelDrag。"""
        if getattr(self, "_shutdown_done", False):
            return
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        try:
            QApplication.postEvent(
                canvas,
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                          Qt.KeyboardModifier.NoModifier))
        except Exception:
            pass

    # --- B8：measure 事件路由（画布视口 → 活动 Python 工具）--------------
    def _canvas_viewport(self):
        """画布视口控件（QgsMapCanvas 事件的落点，measure 路由挂这里）。

        QgisCanvasHost 以 QWidget 类型包装画布，而 shiboken 对同一地址只
        认首次包装类型——QAbstractScrollArea.viewport() 未必可达。Qt6 的
        视口是画布的无名 QWidget 直接子控件（qt_scrollarea_h/vcontainer
        是滚动条容器，objectName 非空）；优先走 viewport()，不可达时按
        此识别。
        """
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return None
        viewport_attr = getattr(canvas, "viewport", None)
        if callable(viewport_attr):
            try:
                vp = viewport_attr()
                if vp is not None:
                    return vp
            except Exception:
                pass
        try:
            for child in canvas.children():
                try:
                    if (child.metaObject().className() == "QWidget"
                            and not child.objectName()):
                        return child
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _route_measure_mouse(self, event) -> bool:
        """把画布视口按键类鼠标事件喂给活动 MeasureDistanceTool。

        返回 True 表示事件已消费（不进原生 QgsMapTool）；MouseMove 不拦。
        """
        controller = getattr(self, "_tool_controller", None)
        tool = getattr(controller, "active_tool", None) if controller is not None else None
        if tool is None or getattr(tool, "tool_id", "") != "measure_distance":
            return False
        et = event.type()
        if et == QEvent.Type.MouseMove:
            # 只喂预览不拦：画布继续收 move（状态条 xy 跟手；pan 无 press 不起拖）。
            self._emit_measure_preview(tool)
            return False
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            btn = "left"
        elif button == Qt.MouseButton.RightButton:
            btn = "right"
        else:
            btn = "middle"
        modifiers = event.modifiers()
        mods = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mods.append("ctrl")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mods.append("shift")
        pos = event.position()
        try:
            mx, my = self.stack.screen_to_map(
                self.canvas_address, float(pos.x()), float(pos.y()))
        except Exception:
            return True  # 换算失败也吞掉：measure 激活期画布不接按键事件
        point = (mx, my)
        if et == QEvent.Type.MouseButtonPress:
            tool.mouse_press(point, button=btn, modifiers=tuple(mods))
        elif et == QEvent.Type.MouseButtonRelease:
            tool.mouse_release(point, button=btn, modifiers=tuple(mods))
        else:
            tool.double_click(point, modifiers=tuple(mods))
        distance = getattr(tool, "last_distance", None)
        if distance != self._last_measure_emit:
            self._last_measure_emit = distance
            if distance is not None:
                try:
                    self.measure_segment.emit(float(distance))
                except Exception:
                    pass
        return True

    def _emit_measure_preview(self, tool) -> None:
        start = getattr(tool, "start", None)
        current = getattr(tool, "current", None)
        if start is None or current is None:
            return
        try:
            distance = math.dist(start, current)
        except Exception:
            return
        try:
            self.measure_preview.emit(float(distance))
        except Exception:
            pass

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
        """Host 工具控制器绑定：pan/zoom/编辑工具映射到 QGIS 原生工具。

        调用方既可能传 CompositeEditController（.tools 属性）也可能直传
        MapToolController 工具栈本体（composite_editing.attach_canvas 走后者）——
        两者都接，否则包装静默不装、原生工具永远停在 pan（真机回归）。
        """
        self._tool_controller = controller
        try:
            self.stack.set_map_tool(self.canvas_address, "pan")
        except Exception:
            pass
        try:
            if hasattr(controller, "set_active_tool"):
                tools = controller  # 直传工具栈
            else:
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
                    # M3：编辑类工具映射到原生 QgsMapTool（采点/线/面/顶点/移动）。
                    # B8：identify 直连桥 QgsMapToolIdentifyFeature；measure 桥级
                    # 无原生工具——原生侧落 pan 清掉编辑/识别工具占用，画布鼠标
                    # 事件由 _CanvasMouseRouter 路由给活动 Python 工具。
                    measure_active = tool_id == "measure_distance"
                    kind = {
                        "zoom_in": "zoomIn",
                        "zoom_out": "zoomOut",
                        "add_point": "addPoint",
                        "add_line": "addLine",
                        "add_polygon": "addPolygon",
                        "vertex": "vertex",
                        "move_feature": "move",
                        "select": "select",
                        "select_rectangle": "select",
                        "identify": "identify",
                        "pan": "pan",
                    }.get(tool_id, "pan")
                    try:
                        shim.stack.set_map_tool(addr, kind)
                    except Exception:
                        pass
                    try:
                        shim._measure_router.set_active(measure_active)
                        if not measure_active:
                            shim._last_measure_emit = None
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

        # M3 Task 2：原生采点完成几何 → 活动 Python 采点工具的会话（权威不变）。
        self_ref = weakref.ref(self)

        def _on_digitize(status: str, geom_json: str) -> None:
            shim = self_ref()
            if shim is None or getattr(shim, "_shutdown_done", False):
                return
            if status != "completed":
                # M3 Task 5：canceled（Esc/右键空取消）时工具条状态回流，
                # 工具保持激活——只是本次捕捉作废。
                shim.tool_operation.emit(False)
                return
            controller = getattr(shim, "_tool_controller", None)
            tool = getattr(controller, "active_tool", None) if controller is not None else None
            commit = getattr(tool, "commit_geometry", None)
            if commit is None:
                return
            try:
                if commit(json.loads(geom_json)):
                    shim.tool_operation.emit(True)
            except Exception:
                pass

        try:
            self.stack.set_digitize_callback(self.canvas_address, _on_digitize)
        except Exception:
            pass

        # M3 Task 3：原生顶点/移动工具完成 → 活动 Python 工具的会话。
        def _on_edit_pick(action: str, payload_json: str) -> None:
            shim = self_ref()
            if shim is None or getattr(shim, "_shutdown_done", False):
                return
            if action == "pick_miss":
                return
            controller = getattr(shim, "_tool_controller", None)
            tool = getattr(controller, "active_tool", None) if controller is not None else None
            if tool is None:
                return
            try:
                payload = json.loads(payload_json)
            except Exception:
                return
            ok = False
            try:
                if action == "vertex_moved":
                    commit = getattr(tool, "commit_vertex_move", None)
                    if commit is not None:
                        ok = bool(commit(
                            payload["feature_id"],
                            tuple(payload["path"]),
                            (float(payload["x"]), float(payload["y"])),
                        ))
                elif action == "feature_moved":
                    commit = getattr(tool, "commit_move", None)
                    if commit is not None:
                        ok = bool(commit(
                            payload["feature_id"],
                            float(payload["dx"]), float(payload["dy"]),
                        ))
            except Exception:
                ok = False
            if ok:
                try:
                    shim.tool_operation.emit(True)
                except Exception:
                    pass

        try:
            self.stack.set_edit_pick_callback(self.canvas_address, _on_edit_pick)
        except Exception:
            pass

        # M3 Task 4：原生选择/identify 结果 → Python 选集（权威）+ 高亮投影。
        def _on_selection(action: str, payload_json: str) -> None:
            shim = self_ref()
            if shim is None or getattr(shim, "_shutdown_done", False):
                return
            try:
                payload = json.loads(payload_json)
            except Exception:
                return
            if action == "identify":
                # B8：原生 identify 结果 → Python 信号（单一转发入口）；
                # 识别面板消费仍走 Python feature_query_index 权威路径。
                try:
                    shim.native_identified.emit(dict(payload))
                except Exception:
                    pass
                return
            if action != "selection":
                return
            controller = getattr(shim, "_tool_controller", None)
            tool = getattr(controller, "active_tool", None) if controller is not None else None
            commit = getattr(tool, "commit_selection", None)
            if commit is None:
                return
            try:
                ok = bool(commit(payload.get("feature_ids") or (),
                                 payload.get("modifiers") or ()))
            except Exception:
                ok = False
            if not ok:
                return
            # 高亮投影：Python 选集是权威，QgsHighlight 只是视觉投影
            layer = getattr(tool, "layer", None)
            if layer is None:
                return
            try:
                selection = sorted(str(i) for i in layer.selection)
                if selection:
                    shim.stack.highlight_features(
                        shim.canvas_address, str(layer.id), json.dumps(selection))
                else:
                    shim.stack.clear_highlights(shim.canvas_address)
            except Exception:
                pass
            try:
                shim.tool_operation.emit(False)
            except Exception:
                pass

        try:
            self.stack.set_selection_callback(self.canvas_address, _on_selection)
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
        mirrored_qgis_ids, seen, failures = mirror_snapshot_to_stack(
            self.stack, self.canvas_address, snapshot)
        # B8：保留最近快照供矢量导出（export_svg/export_pdf 经桥级
        # export_vector 以同一份快照离屏渲染，见 _export_vector）。
        self._last_snapshot = snapshot
        # #1164: 镜像失败（非法 CRS/坏 GeoJSON/删除排序刷新失败）进入公开
        # 诊断列表并反映到 backend_status，宿主可感知镜层与文档失同步。
        self._mirror_failures = list(failures)
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

    # --- 导出（B8：与 UnifiedMapCanvas 同契约，export_service 能力探测识别）---
    def export_capabilities(self) -> tuple[str, ...]:
        """诚实能力声明：PNG 总可导；SVG/PDF 需有图层快照且桥可用。"""
        caps = ["PNG"]
        if self._vector_export_available():
            caps.extend(("SVG", "PDF"))
        return tuple(caps)

    def _vector_export_available(self) -> bool:
        if getattr(self, "_last_snapshot", None) is None:
            return False
        try:
            import qgis_render_bridge  # noqa: F401
        except ImportError:
            return False
        return True

    def export_png(self, path) -> None:
        """QGIS 画布 PNG 导出：真出图（等待在途渲染完成后抓画布帧）。

        先触发一次刷新并泵事件等渲染收尾，保证帧反映当前图层与范围
        （画布从未渲染过时也能拿到首帧）；失败抛 ExportError。
        """
        if getattr(self, "_shutdown_done", False) or self.stack is None or not self.canvas_address:
            raise ExportError("QGIS 画布已关闭，无法导出")
        try:
            self.stack.refresh_canvas(self.canvas_address)
        except Exception:
            pass
        deadline = time.monotonic() + 5.0
        while not getattr(self, "_shutdown_done", False):
            try:
                rendering = bool(self.stack.is_canvas_rendering(self.canvas_address))
            except Exception:
                break
            if not rendering or time.monotonic() > deadline:
                break
            QApplication.processEvents()
        pixmap = self.canvas.grab()
        if pixmap.isNull():
            raise ExportError("QGIS 画布无可用帧，无法导出 PNG")
        if not pixmap.save(str(path), "PNG"):
            raise ExportError("PNG 保存失败")

    def export_svg(self, path) -> None:
        self._export_vector(str(path), "svg")

    def export_pdf(self, path) -> None:
        self._export_vector(str(path), "pdf")

    def _export_vector(self, path: str, fmt: str) -> None:
        """桥级真矢量导出：以 retained 快照喂独立 QgisRenderBridge。

        QgisMapStack 的镜像层与 QgisRenderBridge 的 mirrors 是两套表，桥的
        export_vector 不能直接渲画布内容；经 QgisMapRenderBackend 用同一份
        快照离屏渲染（与屏幕共用 QGIS 渲染器配置，见
        tests/test_qgis_screen_export_parity.py）。无快照/桥不可用时诚实报错。
        """
        if getattr(self, "_shutdown_done", False):
            raise ExportError("QGIS 画布已关闭，无法导出")
        snapshot = getattr(self, "_last_snapshot", None)
        if snapshot is None:
            raise ExportError("QGIS 画布尚无图层快照，无法矢量导出；请使用 PNG")
        try:
            from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend
        except Exception as exc:
            raise ExportError(f"QGIS 矢量导出模块不可用: {exc}") from exc
        backend = QgisMapRenderBackend()
        if not backend.is_available:
            raise ExportError("QGIS 渲染桥不可用，无法矢量导出；请使用 PNG")
        backend.initialize()
        try:
            backend.set_layer_snapshot(snapshot)
            try:
                backend.set_extent(tuple(self.view_extent))
            except ValueError:
                raise ExportError("QGIS 画布范围为空，无法矢量导出")
            width = max(64, int(self.canvas.width() or 800))
            height = max(64, int(self.canvas.height() or 600))
            if not backend.export_map_body(path, fmt, width, height, 96.0):
                raise ExportError(f"QGIS 矢量导出失败（{fmt.upper()}）；请使用 PNG")
        finally:
            try:
                backend.shutdown()
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
            self._measure_router.detach()
        except Exception:
            pass
        try:
            self.events.extent_changed.disconnect(self._on_stack_extent)
        except Exception:
            pass
        try:
            self.events.map_position_changed.disconnect(self._on_stack_position)
        except Exception:
            pass
        self._cleanup_canvas()

    def _mark_disposed(self) -> None:
        """Qt 树析构期间的记账：纯 Python 状态，绝不进桥/QGIS。"""
        self._restore_tool_patch()
        self._shutdown_done = True
        self._canvas_destroyed = True
        # 画布总是先于本组件析构（host 子孙链），桥内 destroyed 连接已在
        # C++ 侧回收 bridge/tool 表；这里放开唯一引用，让 ~QgisMapStack →
        # shutdown() 走 null-QPointer 守卫路径把自有图层移出共享 QgsProject，
        # 避免泄漏到后续画布。栈内层删除不再有任何活画布可被重入。
        self.stack = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    # #1156: QWidget.update() 的旧重载把任意宿主重绘都升级成一次全量
    # refresh_canvas（此前还含同步渲染等待 + 事件泵，可在 C++ 栈深处重入
    # Python/销毁路径）。刷新只发生在显式的快照/extent 变更点；普通重绘
    # 就是普通重绘，删除本重载。
