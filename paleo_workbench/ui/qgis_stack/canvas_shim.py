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
from PySide6.QtGui import QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import logging

from paleo_workbench.resources.exporters import ExportError
from paleo_workbench.ui.qgis_stack.events import StackEvents

# 跨测试/跨文档的活 shim 注册表：QgsMapStack（非 display 模式）把镜像层放
# 进进程级 QgsProject::instance()，宿主销毁路径若不显式 shutdown（Qt 析构
# 期间禁止重入 QGIS API），镜像层会泄漏进共享工程污染后续用例。弱引用集合
# + shutdown_live_shims() 给宿主（conftest / 壳层 teardown）一个确定性
# 清理点，不改变单实例生命周期语义。
_LIVE_SHIMS: "weakref.WeakSet[QgisCanvasShim]" = weakref.WeakSet()


def shutdown_live_shims() -> int:
    """显式收尾所有存活 shim；返回收尾数量（测试卫生/壳层 teardown 用）。"""
    cleaned = 0
    for shim in list(_LIVE_SHIMS):
        try:
            if not shim._shutdown_done:
                shim.shutdown()
                cleaned += 1
        except RuntimeError:
            pass  # 底层 C++ 已析构
    return cleaned
from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost, canvas_viewport


def _load_mapstack():
    # Windows V7：vendored QGIS 运行时 DLL 目录必须先进 loader 路径。
    from paleo_workbench.mapping.qgis_style import ensure_qgis_bridge_dll_dirs

    ensure_qgis_bridge_dll_dirs()
    try:
        from qgis_render_bridge.mapstack import QgisMapStack

        return QgisMapStack
    except ImportError as exc:
        raise RuntimeError(
            f"QGIS 渲染桥未安装或构建失败（qgis_render_bridge.mapstack 无法导入）；"
            f"请执行 PALEO_WITH_QGIS_RENDERER=1 {sys.executable} -m pip install -e native/qgis_render_bridge 重新构建安装"
            "（首次构建 vendored QGIS 需数小时）"
        ) from exc


# V10：桥 manifest 特性 flag 的进程级缓存（capability_manifest 是编译期
# 注册表，无 QGIS init 成本；缓存避免每次调用重读）。桥不可导入 → 空表
# （所有特性诚实为 False，消费方按旧语义降级）。
_BRIDGE_FEATURES: dict[str, bool] | None = None


def _bridge_features() -> dict[str, bool]:
    global _BRIDGE_FEATURES
    if _BRIDGE_FEATURES is None:
        try:
            import qgis_render_bridge

            manifest = qgis_render_bridge.capability_manifest()
            features = manifest.get("features") or {}
            if isinstance(features, dict):
                _BRIDGE_FEATURES = {
                    str(k): bool(v) for k, v in features.items()}
            else:
                _BRIDGE_FEATURES = {str(f): True for f in features}
        except Exception:
            _BRIDGE_FEATURES = {}
    return _BRIDGE_FEATURES


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


def _prepare_chrome_widget(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    widget.setAutoFillBackground(False)


class _ScaleChrome(QWidget):
    """左下角比例尺（小控件，不能盖住整幅地图）。"""

    def __init__(self, host: "QgisCanvasShim", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        _prepare_chrome_widget(self)

    def paintEvent(self, _event) -> None:  # noqa: N802
        host = self._host
        if getattr(host, "_shutdown_done", False):
            return
        from paleo_workbench.ui.unified_map_canvas import (
            _CHROME_INK_ON_LIGHT_BODY,
            _paint_scale_bar_impl,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        map_width = max(1, int(host._chrome_map_size()[0]))
        _paint_scale_bar_impl(
            painter, host.view_extent, map_width, self.height(), 1.0,
            ink=_CHROME_INK_ON_LIGHT_BODY,
        )
        painter.end()


class _NorthChrome(QWidget):
    """左上角指北针。"""

    def __init__(self, host: "QgisCanvasShim", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        _prepare_chrome_widget(self)

    def paintEvent(self, _event) -> None:  # noqa: N802
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFont, QPen, QPolygonF
        from paleo_workbench.ui.unified_map_canvas import (
            _CHROME_INK_ON_DARK_BODY,
            _CHROME_INK_ON_LIGHT_BODY,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2.0, 28.0)
        painter.setPen(QPen(QColor(_CHROME_INK_ON_LIGHT_BODY), 1.5))
        painter.setBrush(QColor(_CHROME_INK_ON_DARK_BODY))
        painter.drawPolygon(QPolygonF([
            center + QPointF(0, -18),
            center + QPointF(-6, 10),
            center + QPointF(0, 5),
            center + QPointF(6, 10),
        ]))
        font = QFont(painter.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor(_CHROME_INK_ON_LIGHT_BODY))
        painter.drawText(center + QPointF(-5, -22), "N")
        painter.end()


class _LegendChrome(QWidget):
    """右下角工区图例。"""

    def __init__(self, host: "QgisCanvasShim", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        _prepare_chrome_widget(self)

    def paintEvent(self, _event) -> None:  # noqa: N802
        host = self._host
        if getattr(host, "_shutdown_done", False):
            return
        from paleo_workbench.ui.unified_map_canvas import paint_map_decorations

        provider = getattr(host, "_overlay_provider", None)
        state = provider() if callable(provider) else {}
        if not isinstance(state, dict):
            state = {}
        decorations = dict(state.get("decorations") or {})
        decorations["elements"] = ["图例"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_map_decorations(
            painter, decorations,
            width=self.width(), height=self.height(),
            extent=host.view_extent, dark_chrome=True,
        )
        painter.end()


def dispatch_edit_pick(shim, tool, action: str, payload: dict) -> bool:
    """edit-pick 回执的单一分发点（与 C++ ``edit_tools.cpp`` 回执词表对齐）。

    返回 ``True`` = 工具已接受并提交（``tool_operation(True)``）；否则按回执
    语义发 ``commit_rejected`` + ``tool_operation(False)``。

    V10（#1258）：此前这段判定内联在 ``_on_edit_pick`` 闭包里，无法在
    shim 层测试——`vertex_delete_rejected` 从 C++ 发出后在这里落空，Delete
    键仍是"无声死键"，而测试因为直接打裸回调而显示通过。提成模块级函数后
    "C++ 有回执 / shim 已消费" 这一对可以被纯 Python 测试钉住。
    """
    ok = False
    rejection = ""
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
        elif action == "vertex_inserted":
            commit = getattr(tool, "commit_vertex_insert", None)
            if commit is not None:
                ok = bool(commit(
                    payload["feature_id"],
                    tuple(payload["path"]),
                    (float(payload["x"]), float(payload["y"])),
                ))
        elif action == "vertex_deleted":
            commit = getattr(tool, "commit_vertex_delete", None)
            if commit is not None:
                ok = bool(commit(
                    payload["feature_id"],
                    tuple(payload["path"]),
                ))
        elif action == "vertex_delete_rejected":
            # 守卫拒绝（低于最少顶点 / 无悬停顶点）——C++ 已发回执，这里
            # 必须上浮成可感知的拒绝，不做无声死键。
            rejection = "节点删除未生效：低于最少顶点或未悬停在可删除的顶点上"
        elif action == "snap_feedback":
            # V10：捕捉反馈上浮（info-only 信号，与工具操作解耦）。
            try:
                shim.snap_feedback.emit(dict(payload))
            except Exception:
                pass
    except Exception:
        ok = False
    if ok:
        try:
            shim.tool_operation.emit(True)
        except Exception:
            pass
        return True
    if not rejection and action in {"vertex_inserted", "vertex_deleted"}:
        # ADV-2 同款回执（review-5 #25）：被拒绝的节点编辑必须可感知，
        # 不做无声死键（最常见原因：守卫拒绝/陈旧镜像路径）。
        rejection = (
            "节点编辑未写入：会话校验未通过（目标要素/路径已变化或低于最少顶点）")
    if rejection:
        try:
            shim.commit_rejected.emit(rejection)
            shim.tool_operation.emit(False)
        except Exception:
            pass
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
    # B8：量距分段完成 / 实时预览（地图单位）——fallback 路由路径（旧桥）。
    measure_segment = Signal(float)
    measure_preview = Signal(float)
    # V7：原生测距（PwbMeasureTool）结果。payload 见桥侧
    # PwbMeasureTool::payloadJson：{"action", "points", "segments", "total",
    # "ellipsoidal"}；action ∈ measure_updated|measure_completed。
    measure_updated = Signal(dict)
    # V10：捕捉反馈（层/要素/类型/距离）与捕获过程（点列/段长/总长 + snap）。
    snap_feedback = Signal(dict)
    capture_progress = Signal(dict)
    measure_canceled = Signal()
    # V7/ADV-2：原生交互提交被会话拒绝时的人类可读原因（坏几何/重复 id/
    # 脱钩会话），宿主转 status_message——采点完成必须有回执。
    commit_rejected = Signal(str)
    # V8/M1：原生 QgsMapTool 激活失败（payload: tool_id, reason）。宿主必须
    # 回退 pan 并同步工具条 checked——按钮亮着但画布工具没换是「点了没
    # 反应」类 UX 缺陷，必须可检测。
    native_tool_activation_failed = Signal(str, str)

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
        self._chrome_scale = None
        self._chrome_north = None
        self._chrome_legend = None
        self._overlay = None  # 兼容旧测试：指向比例尺控件
        self._chrome_filter_installed = False
        self._install_chrome_overlay()
        self._mirrored_layers: list[str] = []
        self._mirrored_doc_ids: list[str] = []
        self._mirror_failures: list[str] = []
        # V5 分层编图工作区：True 时镜像跳过 root 平铺顺序，组结构由
        # LayerGroupController 经 group API reconcile（默认 False 保持旧路径）。
        self.layer_groups_enabled: bool = False
        self._shutdown_done = False
        _LIVE_SHIMS.add(self)
        self._tool_controller = None
        # V10 M-B：最近一次镜像发布的工程 CRS（crs_chain_facts 投影用）。
        self._project_crs_hint: str = ""
        self._pending_programmatic = 0
        self._expected_programmatic_extents: list[tuple[float, float, float, float]] = []
        self._last_emitted_extent: tuple[float, float, float, float] | None = None
        self._tools_original_set_active = None
        self._tools_wrapped_target = None
        self._wrapped_func = None
        # B8：量距事件路由（仅 measure_distance 激活期挂画布视口过滤器）。
        self._measure_router = _CanvasMouseRouter(self)
        self._last_measure_emit: float | None = None
        # V7：原生测距可用性（capability manifest 声明 "measure" kind）。
        # 旧桥（<0.3.0）无原生测距——诚实降级为视口路由路径，不静默。
        self._native_measure_supported = self._probe_native_measure(QgisMapStack)
        self._measure_degrade_warned = False
        # V8/M1：最近一次成功激活的原生工具 (tool_id, kind)；初值 pan
        # （set_map_tool_controller 绑定时强制 pan）。
        self._last_native_tool: tuple[str, str] = ("pan", "pan")
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

    @staticmethod
    def _probe_native_measure(stack_cls) -> bool:
        """桥 capability manifest 是否声明原生测距（V7）。

        manifest 是桥能力的唯一权威；旧桥无 manifest 或未列 "measure"
        都返回 False（fallback 路由路径接管，不伪造能力）。
        """
        try:
            from paleo_workbench.mapping.qgis_style import ensure_qgis_bridge_dll_dirs

            ensure_qgis_bridge_dll_dirs()  # Windows V7: vendor DLL path
            import qgis_render_bridge as bridge

            manifest = bridge.capability_manifest()
            return "measure" in set(manifest.get("native_tools") or ())
        except Exception:
            return False

    def _is_fitted_compatible(self, expected: tuple[float, float, float, float], actual: tuple[float, float, float, float]) -> bool:
        if expected == actual:
            return True        # QGIS aspect-fit expands one axis keeping center: actual should contain expected with same center
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
        try:
            self._on_stack_extent_impl(xmin, ymin, xmax, ymax)
        finally:
            self._refresh_chrome_overlay()

    def _on_stack_extent_impl(self, xmin, ymin, xmax, ymax) -> None:
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
                    # 弹头后索引必须重算：pop(0) 让后续下标整体前移一位，
                    # 不重算则 can_previous/next 错位（review P2-5）。
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
        parts: list[str] = []
        if failures:
            parts.append(f"degraded ({len(failures)} mirror failures)")
        # V10 M-Q：运行时健康（proj 链/CRS 解析）进入后端状态——桥可加载
        # ≠ 空间运行时完整；降级原因必须可见，不得「画布能渲染就算健康」。
        # 进程级缓存探测（qgis_runtime.health），此处读取零成本。
        try:
            from paleo_workbench.qgis_runtime.health import probe_qgis_runtime

            health = probe_qgis_runtime()
            if health.qgis_available and health.degraded_reasons:
                parts.append(
                    "runtime degraded: " + "; ".join(
                        reason.split("\n")[0] for reason in health.degraded_reasons[:3]))
        except Exception:
            pass
        if parts:
            return "qgis: " + "; ".join(parts)
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
        self._overlay_provider = provider
        self._install_chrome_overlay()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize and obj is canvas_viewport(self.canvas):
            self._install_chrome_overlay()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._install_chrome_overlay()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._install_chrome_overlay()

    def _chrome_map_size(self) -> tuple[int, int]:
        host = canvas_viewport(self.canvas) or self
        return max(1, host.width()), max(1, host.height())

    def _install_chrome_overlay(self) -> None:
        host = canvas_viewport(self.canvas) or self
        if self._chrome_scale is None:
            self._chrome_scale = _ScaleChrome(self, host)
            self._chrome_north = _NorthChrome(self, host)
            self._chrome_legend = _LegendChrome(self, host)
            self._overlay = self._chrome_scale
        for piece in (self._chrome_scale, self._chrome_north, self._chrome_legend):
            if piece.parent() is not host:
                piece.setParent(host)
        map_w, map_h = self._chrome_map_size()
        from paleo_workbench.ui.unified_map_canvas import _scale_bar_spec_impl

        spec = _scale_bar_spec_impl(self.view_extent, map_w, 1.0)
        bar_w = int((spec[1] if spec else 120) + 40)
        self._chrome_scale.setGeometry(8, max(0, map_h - 44), min(bar_w, map_w - 16), 40)
        self._chrome_north.setGeometry(8, 48, 48, 56)
        provider = getattr(self, "_overlay_provider", None)
        state = provider() if callable(provider) else {}
        decorations = (state.get("decorations") or {}) if isinstance(state, dict) else {}
        from paleo_workbench.ui.unified_map_canvas import legend_chrome_size

        legend_w, legend_h = legend_chrome_size(decorations)
        if legend_w and legend_h:
            self._chrome_legend.setGeometry(
                max(0, map_w - legend_w - 8), max(0, map_h - legend_h - 8),
                legend_w, legend_h)
            self._chrome_legend.show()
            self._chrome_legend.raise_()
            self._chrome_legend.update()
        else:
            self._chrome_legend.hide()
        for piece in (self._chrome_scale, self._chrome_north):
            piece.raise_()
            piece.show()
            piece.update()
        if host is not self and not self._chrome_filter_installed:
            host.installEventFilter(self)
            self._chrome_filter_installed = True

    def _refresh_chrome_overlay(self) -> None:
        self._install_chrome_overlay()

    def set_snapping_config(self, config: dict) -> bool:
        """捕捉配置下推 QGIS canvas snappingUtils（M3）。

        config 形如 ``{"enabled": bool, "mode": "all_layers"|"active_layer",
        "tolerance_px": float, "types": [...], "reference_enabled": bool,
        "layers": {doc_id: {"enabled": bool, "types": [...], "tolerance_px": float}}}``；
        状态权威仍是 Python SnappingService，这里只是投影。grid 捕捉为
        Python 专有模式，QGIS 端无对应物，不下推。
        """
        if getattr(self, "_shutdown_done", False) or not self.canvas_address:
            return False
        try:
            self.stack.set_snapping_config(self.canvas_address, json.dumps(config))
        except Exception:
            logging.getLogger(__name__).warning(
                "native snapping config push failed", exc_info=True)
            return False
        return True

    def _bridge_feature(self, name: str) -> bool:
        """V10：桥 manifest 特性查询（进程级缓存；无桥 = False 诚实降级）。"""
        return bool(_bridge_features().get(name))

    def set_vertex_edit_scope(self, all_layers: bool) -> None:
        """M2 §4 顶点档位推送到桥（缺面 = 旧桥诚实跳过）。"""
        setter = getattr(self.stack, "set_vertex_edit_scope", None)
        if not callable(setter) or self._shutdown_done:
            return
        try:
            setter(self.canvas_address, bool(all_layers))
        except Exception:
            pass

    def set_tracing_enabled(self, enabled: bool) -> None:
        """M2 §4 追踪开关推送到桥（QgsMapCanvasTracer 注册 + QAction）。"""
        setter = getattr(self.stack, "set_tracing_enabled", None)
        if not callable(setter) or self._shutdown_done:
            return
        try:
            setter(self.canvas_address, bool(enabled))
        except Exception:
            pass

    def set_current_layer(self, doc_id: str) -> None:
        """画布当前图层（原生选择/identify 的目标图层）。

        V10 M-G（D5 漂移修复）：空 doc_id 现在是**显式清除**（选中参考
        图层等非编辑目标时，原生画布不得残留上一个编辑层——旧桥把空串
        当未知 id 抛错，Python 因此静默吞掉，三方漂移由此而生）。桥
        manifest 无 ``current_layer_clear``（<0.6.0a0）时保持旧 no-op
        语义（诚实降级）。未知 id 仍忽略（与既往一致）。
        """
        if getattr(self, "_shutdown_done", False) or not self.canvas_address:
            return
        if not doc_id:
            if self._bridge_feature("current_layer_clear"):
                try:
                    self.stack.set_current_layer(self.canvas_address, "")
                except Exception:
                    pass
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

    def active_map_tool_id(self) -> str | None:
        """画布当前实际原生工具的宿主侧 tool_id（原生画布不可用 → None）。

        V8/M1 checked-state 一致性读取面：工具条 checked 必须与本值一致
        （激活失败回退后尤其如此）。桥不要求新增 API——该值来自 shim 自身
        对 ``set_map_tool`` 成败的记录。
        """
        if not self._canvas_created or self._canvas_destroyed:
            return None
        return self._last_native_tool[0]

    def map_scale(self) -> float:
        """画布权威比例尺分母（V9 W1；0.0 = 未知/桥无此面）。

        直接读 ``QgsMapCanvas::scale()``（桥 ≥0.5.0a0）；旧桥/异常按
        诚实未知返回 0.0——宿主 ToolContext.scale_denominator 据此判定。
        """
        if not self._canvas_created or self._canvas_destroyed:
            return 0.0
        probe = getattr(self.stack, "canvas_scale", None)
        if not callable(probe):
            return 0.0
        try:
            value = float(probe(self.canvas_address))
        except Exception:
            return 0.0
        return value if value > 0.0 and math.isfinite(value) else 0.0

    def destination_crs(self) -> str:
        """画布当前目标 CRS auth id（V9 W7；"" = 未设/桥无此面）。"""
        if not self._canvas_created or self._canvas_destroyed:
            return ""
        probe = getattr(self.stack, "canvas_destination_crs", None)
        if not callable(probe):
            return ""
        try:
            return str(probe(self.canvas_address) or "")
        except Exception:
            return ""

    def map_units(self) -> str:
        """画布地图单位（V10 M-O；QgsUnitTypes 编码，如 "degrees"/"meters"）。

        权威来自 QGIS mapSettings；桥无此面（<0.6.0a0）→ ""（诚实未知，
        宿主不得自行估算）。
        """
        if not self._canvas_created or self._canvas_destroyed:
            return ""
        probe = getattr(self.stack, "canvas_map_units", None)
        if not callable(probe):
            return ""
        try:
            return str(probe(self.canvas_address) or "")
        except Exception:
            return ""

    def output_dpi(self) -> float:
        """画布输出 DPI（V10 M-O；0.0 = 未知/桥无此面）。"""
        if not self._canvas_created or self._canvas_destroyed:
            return 0.0
        probe = getattr(self.stack, "canvas_output_dpi", None)
        if not callable(probe):
            return 0.0
        try:
            value = float(probe(self.canvas_address))
        except Exception:
            return 0.0
        return value if value > 0.0 and math.isfinite(value) else 0.0

    def mirror_provider_facts(self, doc_id: str) -> dict | None:
        """镜像层 provider 能力快照（V10 M-H；None = 桥无自省面）。"""
        if self._shutdown_done or not self.canvas_address:
            return None
        probe = getattr(self.stack, "mirror_provider_facts", None)
        if not callable(probe):
            return None
        try:
            import json as _json

            return _json.loads(probe(str(doc_id)))
        except Exception:
            return None

    def crs_chain_facts(self, storage_crs: str = "") -> "object":
        """当前链事实投影（V10 M-B；供状态条/ToolContext 消费）。"""
        from paleo_workbench.mapping import crs_chain

        return crs_chain.CrsChainFacts(
            project_crs=getattr(self, "_project_crs_hint", "") or "",
            canvas_crs=self.destination_crs(),
            storage_crs=storage_crs,
            runtime_crs_capable=crs_chain.runtime_crs_capable(),
        )

    def set_map_tool_controller(self, controller) -> None:
        """Host 工具控制器绑定：pan/zoom/编辑工具映射到 QGIS 原生工具。

        调用方既可能传 CompositeEditController（.tools 属性）也可能直传
        MapToolController 工具栈本体（composite_editing.attach_canvas 走后者）——
        两者都接，否则包装静默不装、原生工具永远停在 pan（真机回归）。
        """
        self._tool_controller = controller
        try:
            self.stack.set_map_tool(self.canvas_address, "pan")
            self._last_native_tool = ("pan", "pan")
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
                    # B8：identify 直连桥 QgsMapToolIdentifyFeature。
                    # V7：measure 有原生 PwbMeasureTool 时直连；旧桥（无
                    # manifest 声明）诚实降级为视口路由路径（Python 工具执行）。
                    measure_active = tool_id == "measure_distance"
                    native_measure = measure_active and shim._native_measure_supported
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
                    if native_measure:
                        kind = "measure"
                    elif tool_id == "reshape":
                        # V7 重塑：原生 addLine 数字化器采重塑线；语义应用在
                        # Python 会话（ReshapeTool.commit_geometry）。
                        kind = "addLine"
                    elif tool_id == "add_ring":
                        # V10 捕获环：addPolygon 数字化器采环。
                        kind = "addPolygon"
                    elif tool_id == "add_part":
                        # V10 捕获部件：digitizer 随图层 kind（控制器注入属性）。
                        kind = getattr(tool, "native_digitize_kind", "pan")
                    try:
                        shim.stack.set_map_tool(addr, kind)
                        # V8/M1：记录最近一次成功的原生工具（可检测一致性的
                        # 读取面；checked 与画布实际工具不得漂移）。
                        shim._last_native_tool = (tool_id or "pan", kind)
                    except Exception as exc:
                        # ADV-1：原生工具切换失败必须可见——工具条 checked
                        # 与画布实际工具分叉是"点了没反应"类 UX 缺陷。
                        logging.getLogger(__name__).warning(
                            "原生工具切换失败（%s -> %s）：%s", tool_id, kind, exc)
                        try:
                            shim.backend_status_changed.emit(
                                f"qgis: 工具切换失败（{tool_id}）")
                            shim.native_tool_activation_failed.emit(
                                tool_id or "pan", str(exc))
                        except Exception:
                            pass
                    try:
                        # 视口路由只在「measure 激活 且 桥无原生测距」时挂载。
                        shim._measure_router.set_active(measure_active and not native_measure)
                        if not measure_active:
                            shim._last_measure_emit = None
                        elif not native_measure and not shim._measure_degrade_warned:
                            # 与 snapping endpoint/intersection 降级同款诚实
                            # 提示（review-2 P1-1）：旧桥上测距走 Python 平面
                            # 路径，地理 CRS 下无椭球修正。
                            shim._measure_degrade_warned = True
                            logging.getLogger(__name__).warning(
                                "原生测距工具不可用（旧 qgis_render_bridge）；"
                                "测距已降级为平面计算，地理坐标系下不含椭球修正"
                            )
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
            if status == "digitizing":
                # V10：捕获过程反馈（info-only，不驱动工具操作计数）。
                # 无消费者时跳过 json.loads（review-4 #5：长折线 payload 的
                # 解析在无人显示时是纯浪费）。
                try:
                    if shim.capture_progress.receivers() > 0:
                        shim.capture_progress.emit(dict(json.loads(geom_json)))
                except Exception:
                    pass
                return
            if status != "completed":
                # M3 Task 5：canceled（Esc/右键空取消）时工具条状态回流，
                # 工具保持激活——只是本次捕捉作废。
                shim.tool_operation.emit(False)
                controller = getattr(shim, "_tool_controller", None)
                cancel = getattr(controller, "cancel_native_capture", None)
                if callable(cancel):
                    cancel()
                return
            controller = getattr(shim, "_tool_controller", None)
            # 原生路由必须先于 Python commit_geometry：分割切线走 addLine
            # 但不激活 kind-bound 的 Python 加线工具，active_tool 可能没有
            # commit_geometry——若先 return 则切线永远到不了 split_mirror_features。
            native_route = getattr(controller, "commit_native_capture", None)
            if callable(native_route):
                try:
                    if native_route(json.loads(geom_json)):
                        shim.tool_operation.emit(True)
                        return
                except Exception:
                    pass  # 路由失败回落 Python 工具提交
            tool = getattr(controller, "active_tool", None) if controller is not None else None
            commit = getattr(tool, "commit_geometry", None)
            if commit is None:
                return
            # 拓扑编辑迁移 M0（§6 决议 #1285）：旧 digitize-commit CRS 门
            # （crs_chain.evaluate_commit_guard）退休——CRS 校验并入三段式
            # 「进前段」（进入编辑时拦截，会话期间 CRS 冻结），提交前不
            # 重复查。RAW/角色/成熟度保护同样在进前段由宿主门禁把守。
            # M1：活动层处于原生会话时数字化直写镜像缓冲（宿主路由，
            # add_mirror_feature 一宏），不经 Python 工具提交。
            # ADV-2：commit 被拒（坏几何/重复 id/脱钩会话）必须让用户感知，
            # 不得静默吞掉一次完成的采点。
            try:
                ok = bool(commit(json.loads(geom_json)))
            except Exception as exc:
                logging.getLogger(__name__).debug(
                    "digitize commit rejected: %s", exc)
                shim.commit_rejected.emit(f"要素未写入：{exc}")
                shim.tool_operation.emit(False)
                return
            if ok:
                shim.tool_operation.emit(True)
            else:
                shim.commit_rejected.emit("要素未写入：几何校验未通过")
                shim.tool_operation.emit(False)

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
            if action == "join_requested":
                # M2 §3 按需生长：全部层档手势波及邻层 → 宿主门禁复查
                # （同步——release 时入集层即可编辑；拒绝层不参与并提示）。
                joiner = getattr(controller, "join_native_layers", None)
                if callable(joiner):
                    try:
                        joiner((payload.get("layer_doc_ids")
                                if (payload := json.loads(payload_json))
                                else []) or [])
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "native layer join failed")
                return
            if action == "edit_gesture":
                # M1：原生手势记账（编辑发生在镜像缓冲——数据回调只有
                # 手势事实，无 Python 提交）。
                recorder = getattr(controller, "record_native_gesture", None)
                if callable(recorder):
                    try:
                        recorder(json.loads(payload_json))
                        shim.tool_operation.emit(True)
                    except Exception:
                        # 手势漏记会让撤销计划与桥 undoStack 失同步——可诊断。
                        logging.getLogger(__name__).exception(
                            "native edit gesture recording failed")
                return
            tool = getattr(controller, "active_tool", None) if controller is not None else None
            if tool is None:
                return
            try:
                payload = json.loads(payload_json)
            except Exception:
                return
            dispatch_edit_pick(shim, tool, action, payload)

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

        # V7：原生测距结果上浮（PwbMeasureTool → 状态栏/宿主信号）。
        def _on_measure(action: str, payload_json: str) -> None:
            shim = self_ref()
            if shim is None or getattr(shim, "_shutdown_done", False):
                return
            try:
                if action == "measure_canceled":
                    shim.measure_canceled.emit()
                    return
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            try:
                shim.measure_updated.emit(dict(payload))
            except Exception:
                pass

        try:
            self.stack.set_measure_callback(self.canvas_address, _on_measure)
        except Exception:
            pass

    # --- 图层镜像 ------------------------------------------------------
    def set_layer_snapshot(self, snapshot, changed_hints=None) -> None:
        """Mirror snapshot vector layers into the QGIS project (incremental).

        ``changed_hints``（V11）：``layer_id → touched fids``——宿主 settle
        的 session journal 提示；差分只重签提示集（O(touched)）。None =
        无提示（回落全量比较，正确性不变）。

        Note (M2): reconcile by ``pwb/doc_id`` — unchanged layers keep their
        QgsVectorLayer object, tree state and renderer across publishes.
        V10 M-O：``scale_range`` 经桥 upsert 的 min_scale/max_scale 通道
        下推（F3 gap 关闭；旧桥无该面 → 跳过，诚实）。
        V5：``layer_groups_enabled`` 为 True 时跳过 root 平铺顺序推送——
        组结构/放置由 LayerGroupController 经 group API reconcile。
        """
        if getattr(self, "_shutdown_done", False):
            return
        # V10 M-B：记录工程 CRS 供 crs_chain_facts 投影（normalize 与
        # crs_contract 一致；未声明 = ""）。
        try:
            self._project_crs_hint = str(getattr(snapshot, "project_crs", "") or "")
        except Exception:
            self._project_crs_hint = ""
        mirrored_qgis_ids, seen, failures = mirror_snapshot_to_stack(
            self.stack, self.canvas_address, snapshot,
            groups=bool(getattr(self, "layer_groups_enabled", False)),
            changed_hints=changed_hints)
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
        # 等待在途渲染收尾：事件循环排除用户输入（泵普通事件不泵鼠标
        # 键盘），加重入哨兵——泵里再触发导出/关窗是经典重入坑；超时是
        # 诚实失败（半渲染帧不冒充成品）。
        if getattr(self, "_exporting", False):
            raise ExportError("导出已在进行中")
        self._exporting = True
        try:
            from PySide6.QtCore import QEventLoop, QTimer

            deadline = time.monotonic() + 5.0
            timed_out = False
            while not getattr(self, "_shutdown_done", False):
                try:
                    rendering = bool(self.stack.is_canvas_rendering(self.canvas_address))
                except Exception:
                    break
                if not rendering:
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                loop = QEventLoop()
                QTimer.singleShot(20, loop.quit)
                loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            if getattr(self, "_shutdown_done", False) or self.stack is None:
                raise ExportError("QGIS 画布在导出期间被关闭")
            if timed_out:
                raise ExportError("QGIS 画布渲染未在时限内完成，取消导出")
            pixmap = self.canvas.grab()
        finally:
            self._exporting = False
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
