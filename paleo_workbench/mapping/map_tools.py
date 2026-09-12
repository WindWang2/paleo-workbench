"""QGIS-inspired renderer-independent map-tool state machines.

**Execution-path status (Goal V7)**: on hosts with the QGIS bridge the native
``QgsMapTool`` layer (canvas_shim → qgis_render_bridge) is the *production*
interaction executor; the mouse-driven state machines here are the explicit
**fallback** for the renderer-independent canvas, headless tests and hosts
without the bridge. The ``commit_*`` entry points are the native tools'
landing zone into the Paleo session authority and stay production code.
The fallback must not gain professional capabilities the native path lacks
(Goal V7 §5); divergences are defects.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Iterable, Mapping

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.vector_layer import VectorEditSession, VectorFeature, VectorLayer

__all__ = [
    "AddLineTool",
    "AddPointTool",
    "AddPolygonTool",
    "IdentifyTool",
    "MapTool",
    "MapToolController",
    "MeasureDistanceTool",
    "MoveFeatureTool",
    "PanTool",
    "PartCaptureTool",
    "RectangleSelectTool",
    "ReshapeTool",
    "RingCaptureTool",
    "SelectTool",
    "VertexTool",
    "ZoomTool",
]

Point = tuple[float, float]

_logger = logging.getLogger(__name__)


def _commit_vertex(
    session: VectorEditSession,
    feature_id: str,
    path: tuple[int, ...],
    point,
    *,
    source_suffix: str,
) -> bool:
    """顶点提交公共实现。主编辑由 begin/end_edit_command 合成单命令。"""
    try:
        feature = session.feature(str(feature_id))
    except Exception:
        return False

    session.begin_edit_command()
    try:
        with session.edit_source(f"vertex({source_suffix})"):
            session.set_vertex(feature.feature_id, path, point)
    except Exception as exc:
        session.destroy_edit_command()
        _logger.debug("vertex commit rejected: %s", exc)
        return False
    session.end_edit_command()
    return True


class MapTool:
    """One exclusive interactive operation; rendering overlays remain external."""

    tool_id = "tool"
    # Whether a handled operation mutates document data.  Hosts use this to
    # distinguish data edits (composition resync) from pure pointer/selection
    # feedback (overlay repaint only), so 60 Hz pointer events never recompose.
    edits_data = False

    def __init__(self) -> None:
        self.active = False

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.cancel()
        self.active = False

    def mouse_press(self, _point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        return False

    def mouse_move(self, _point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        return False

    def mouse_release(self, _point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        return False

    def double_click(self, point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        return self.mouse_press(point, button="left", modifiers=modifiers)

    def key_press(self, key: str) -> bool:
        if str(key).lower() == "escape":
            return self.cancel()
        return False

    def cancel(self) -> bool:
        return False


class MapToolController:
    """Owns exclusive activation state shared by toolbar/menu/context actions."""

    def __init__(self) -> None:
        self.active_tool: MapTool | None = None

    def set_active_tool(self, tool: MapTool | None) -> None:
        if tool is self.active_tool:
            return
        if self.active_tool is not None:
            self.active_tool.deactivate()
        self.active_tool = tool
        if tool is not None:
            tool.activate()

    def key_press(self, key: str) -> bool:
        return bool(self.active_tool is not None and self.active_tool.key_press(key))


class PanTool(MapTool):
    tool_id = "pan"


class ZoomTool(MapTool):
    """A one-shot zoom tool; the canvas owns its viewport transform."""

    def __init__(self, *, zoom: Callable[[float, Point], None], factor: float, tool_id: str) -> None:
        super().__init__()
        self._zoom = zoom
        self._factor = float(factor)
        self.tool_id = tool_id

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        self._zoom(self._factor, point)
        return True


class MeasureDistanceTool(MapTool):
    tool_id = "measure_distance"

    def __init__(
        self,
        *,
        measurement_ready: Callable[[float], None] | None = None,
        crs: str = "",
    ) -> None:
        super().__init__()
        self._measurement_ready = measurement_ready
        self.start: Point | None = None
        self.current: Point | None = None
        # 最近一次完成的分段长度。QGIS 画布路径（canvas_shim 事件路由）没有
        # measurement_ready 回调可用——宿主经该只读状态 + 信号给出分段距离。
        self.last_distance: float | None = None
        # V9 W8：地理 CRS 下平面 math.dist 是度不是米——经 crs_contract
        # 的 Geod 走测地线（米）；投影/未知 CRS 保持平面（单位 = 地图单位）。
        # ``last_geodesic`` 让宿主能诚实标注「测地(米)」vs「平面(地图单位)」。
        self._geod = None
        if str(crs or "").strip():
            from paleo_workbench.mapping.crs_contract import geod_for_crs

            self._geod = geod_for_crs(crs)
        self.last_geodesic = False

    @property
    def points(self) -> list[Point]:
        return [point for point in (self.start, self.current) if point is not None]

    def _measure(self, start: Point, end: Point) -> float:
        if self._geod is not None:
            try:
                _azimuth1, _azimuth2, distance = self._geod.inv(
                    float(start[0]), float(start[1]), float(end[0]), float(end[1]))
                if math.isfinite(distance):
                    self.last_geodesic = True
                    return float(distance)
            except Exception:
                pass
        self.last_geodesic = False
        return math.dist(start, end)

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button == "right":
            return self.cancel()
        if button != "left":
            return False
        if self.start is None:
            self.start = point
            self.current = point
            return True
        distance = self._measure(self.start, point)
        self.last_distance = distance
        if self._measurement_ready is not None:
            self._measurement_ready(distance)
        self.start = point
        self.current = point
        return True

    def mouse_move(self, point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        if self.start is None:
            return False
        self.current = point
        return True

    def cancel(self) -> bool:
        had_measurement = self.start is not None
        self.start = None
        self.current = None
        self.last_distance = None
        return had_measurement


class SelectTool(MapTool):
    tool_id = "select"

    def __init__(self, layer: VectorLayer, *, identify: Callable[[Point], str | None]) -> None:
        super().__init__()
        self.layer = layer
        self._identify = identify

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        feature_id = self._identify(point)
        mods = {str(value).lower() for value in modifiers}
        if feature_id is None:
            if not mods:
                self.layer.set_selection(())
            return True
        if "ctrl" in mods or "shift" in mods:
            self.layer.toggle_selection(feature_id)
        else:
            self.layer.set_selection((feature_id,))
        return True

    def commit_selection(
        self, feature_ids: Iterable[str], modifiers: Iterable[str] = ()
    ) -> bool:
        """QGIS 原生选择工具结果落图层选集（M3）。

        修饰键语义对齐 QGIS 桌面：无=替换，Ctrl=并集，Shift=差集，
        Ctrl+Shift=交集。
        """
        ids = {str(value) for value in feature_ids}
        mods = {str(value).lower() for value in modifiers}
        current = set(self.layer.selection)
        if "ctrl" in mods and "shift" in mods:
            new = current & ids
        elif "ctrl" in mods:
            new = current | ids
        elif "shift" in mods:
            new = current - ids
        else:
            new = ids
        self.layer.set_selection(new)
        return True


class RectangleSelectTool(MapTool):
    tool_id = "select_rectangle"

    def __init__(self, layer: VectorLayer, *, select_rectangle: Callable[[Point, Point], set[str]]) -> None:
        super().__init__()
        self.layer = layer
        self._select_rectangle = select_rectangle
        self.start: Point | None = None

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        self.start = point
        return True

    def mouse_release(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left" or self.start is None:
            return False
        start = self.start
        self.start = None
        selected = self._select_rectangle(start, point)
        mods = {str(value).lower() for value in modifiers}
        # 修饰键语义对齐 QGIS 桌面与原生 commit_selection（P2-4）：
        # Ctrl=并集，Shift=差集，Ctrl+Shift=交集。
        if "ctrl" in mods and "shift" in mods:
            self.layer.set_selection(self.layer.selection & selected)
        elif "ctrl" in mods:
            self.layer.set_selection(self.layer.selection | selected)
        elif "shift" in mods:
            self.layer.set_selection(self.layer.selection - selected)
        else:
            self.layer.set_selection(selected)
        return True

    def cancel(self) -> bool:
        had_start = self.start is not None
        self.start = None
        return had_start


class IdentifyTool(MapTool):
    """无层识别工具（无编修图层时 identify 的 fallback 绑定）。

    只把点击喂给多图层识别回调（面板 + 悬浮框由回调的副作用呈现），
    不碰任何图层选集——没有可绑定的活动层，也就没有可写的选择集。
    """

    tool_id = "identify"

    def __init__(self, *, identify: Callable[[Point], object]) -> None:
        super().__init__()
        self._identify = identify

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        self._identify(point)
        return True


class _CaptureTool(MapTool):
    geometry_type = ""
    tool_id = "capture"

    def __init__(
        self,
        session: VectorEditSession,
        *,
        feature_id_factory: Callable[[], str] | None = None,
        snap: Callable[[Point], Point] | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._feature_id_factory = feature_id_factory or (lambda: new_feature_id(self.tool_id))
        self._snap = snap or (lambda point: (float(point[0]), float(point[1])))
        # 模板默认字段值：新要素直接携带地质 schema 的初始属性。
        self._default_attributes = dict(attributes or {})
        self.points: list[Point] = []

    @property
    def edits_data(self) -> bool:
        # 采集中（points 非空）只动 overlay（轻量重绘，rubber band 跟手）；
        # 要素落地 / 会话回空后才需要全量重组合快照。
        return not self.points

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button == "right":
            return self.finish()
        if button != "left":
            return False
        self.points.append(self._snap(point))
        if self.geometry_type == "Point":
            return self.finish()
        # 已消费该次采点：返回 True 让画布重绘 overlay（新顶点 + 橡皮筋）。
        return True

    def mouse_move(self, point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        # 采集中鼠标移动 = 橡皮筋终点变化，需要逐帧重绘 overlay。
        return bool(self.points)

    def double_click(self, point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        self.points.append(self._snap(point))
        return self.finish()

    def cancel(self) -> bool:
        had_points = bool(self.points)
        self.points.clear()
        return had_points

    def finish(self) -> bool:
        if self.geometry_type == "Point":
            if len(self.points) != 1:
                return False
            geometry = {"type": "Point", "coordinates": list(self.points[0])}
        elif self.geometry_type == "LineString":
            if len(self.points) < 2:
                return False
            geometry = {"type": "LineString", "coordinates": [list(point) for point in self.points]}
        else:
            if len(self.points) < 3:
                return False
            ring = [list(point) for point in self.points]
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            geometry = {"type": "Polygon", "coordinates": [ring]}
        with self.session.edit_source(f"{self.tool_id}(python-fallback)"):
            self.session.add_feature(
                VectorFeature(self._feature_id_factory(), geometry, self._default_attributes)
            )
        self.points.clear()
        return True

    def commit_geometry(self, geometry: Mapping[str, object]) -> bool:
        """QGIS 原生采点工具的完成几何直接落会话（M3）。

        原生 QgsMapToolDigitizeFeature 负责逐点输入/rubber band/捕捉，
        完成后把 GeoJSON geometry 交这里——要素写入权威仍是本会话
        （命令模式/undo/持久化链不变）。
        """
        if not geometry or "type" not in geometry:
            return False
        gtype = str(geometry.get("type"))
        expected = self.geometry_type
        if gtype != expected and gtype != f"Multi{expected}":
            return False
        with self.session.edit_source(f"{self.tool_id}(native)"):
            self.session.add_feature(
                VectorFeature(
                    self._feature_id_factory(), dict(geometry), self._default_attributes
                )
            )
        self.points.clear()
        return True


class AddPointTool(_CaptureTool):
    tool_id = "add_point"
    geometry_type = "Point"


class AddLineTool(_CaptureTool):
    tool_id = "add_line"
    geometry_type = "LineString"


class AddPolygonTool(_CaptureTool):
    tool_id = "add_polygon"
    geometry_type = "Polygon"


class MoveFeatureTool(MapTool):
    tool_id = "move_feature"
    edits_data = True

    def __init__(self, session: VectorEditSession, *, identify: Callable[[Point], str | None]) -> None:
        super().__init__()
        self.session = session
        self._identify = identify
        self._feature_id: str | None = None
        self._origin: Point | None = None

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        self._feature_id = self._identify(point)
        self._origin = point if self._feature_id is not None else None
        return self._feature_id is not None

    def mouse_release(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left" or self._feature_id is None or self._origin is None:
            return False
        feature_id, origin = self._feature_id, self._origin
        self._feature_id = None
        self._origin = None
        with self.session.edit_source(f"{self.tool_id}(python-fallback)"):
            self.session.move_feature(feature_id, point[0] - origin[0], point[1] - origin[1])
        return True

    def cancel(self) -> bool:
        had_drag = self._feature_id is not None
        self._feature_id = None
        self._origin = None
        return had_drag

    def commit_move(self, feature_id: str, dx: float, dy: float) -> bool:
        """QGIS 原生移动工具完成位移落会话（M3）；feature 不在本会话则拒绝。"""
        try:
            with self.session.edit_source(f"{self.tool_id}(native)"):
                self.session.move_feature(str(feature_id), float(dx), float(dy))
        except Exception as exc:
            _logger.debug("native move commit rejected (%s): %s", feature_id, exc)
            return False
        return True


class ReshapeTool(MapTool):
    """V7 重塑（native-only）：原生 addLine 数字化器采重塑线 → 会话几何替换。

    无鼠标路径（fallback 画布不提供 reshape——Goal V7 §5：fallback 不获得
    QGIS 路径没有的专业功能）。几何计算走桥 ``geometry.reshape``
    （QgsGeometry::reshapeGeometry），结果经 ``SetGeometryCommand`` 落会话。
    """

    tool_id = "reshape"
    edits_data = True

    def __init__(
        self,
        session: VectorEditSession,
        *,
        feature_id: str,
        apply_reshape: Callable[[Mapping[str, object]], bool],
    ) -> None:
        super().__init__()
        self.session = session
        self.feature_id = str(feature_id)
        self._apply_reshape = apply_reshape

    def commit_geometry(self, geometry: Mapping[str, object]) -> bool:
        """原生数字化的重塑线完成 → 应用 reshape → 落会话。"""
        if not geometry or str(geometry.get("type")) not in {"LineString", "MultiLineString"}:
            return False
        with self.session.edit_source(f"{self.tool_id}(native)"):
            ok = bool(self._apply_reshape(geometry))
        if not ok:
            _logger.debug("reshape application rejected for feature %s", self.feature_id)
        return ok


class VertexTool(MapTool):
    tool_id = "vertex"
    edits_data = True

    def __init__(
        self,
        session: VectorEditSession,
        *,
        identify_vertex: Callable[[Point], tuple[str, tuple[int, ...]] | None],
    ) -> None:
        super().__init__()
        self.session = session
        self._identify_vertex = identify_vertex
        self._target: tuple[str, tuple[int, ...]] | None = None
        self._origin: Point | None = None

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left":
            return False
        self._target = self._identify_vertex(point)
        if self._target is not None:
            feature_id, path = self._target
            geometry = self.session.feature(feature_id).geometry["coordinates"]
            current = geometry
            if not path and self.session.feature(feature_id).geometry["type"] == "Point":
                self._origin = (float(current[0]), float(current[1]))
            else:
                for index in path:
                    current = current[index]
                self._origin = (float(current[0]), float(current[1]))
        return self._target is not None

    def mouse_release(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button != "left" or self._target is None:
            return False
        feature_id, path = self._target
        self._target = None
        self._origin = None
        return _commit_vertex(
            self.session, feature_id, path, point,
            source_suffix="python-fallback",
        )

    def cancel(self) -> bool:
        had_target = self._target is not None
        self._target = None
        self._origin = None
        return had_target

    def commit_vertex_move(
        self, feature_id: str, path: tuple[int, ...], point: Point
    ) -> bool:
        """QGIS 原生顶点工具拖动完成落会话（M3）。

        feature 不在本会话 / 路径无效 / 几何校验失败均拒绝（返回 False）。
        """
        return _commit_vertex(
            self.session,
            str(feature_id),
            tuple(int(i) for i in path),
            point,
            source_suffix="native",
        )

    def commit_vertex_insert(
        self, feature_id: str, path: tuple[int, ...], point: Point
    ) -> bool:
        """V10 原生双击段上插点落会话（native-only，无 fallback 输入路径）。

        一个手势 = 一个宏 = 一个 undo 单元。最少顶点守卫在 session，
        失败即拒绝（False）。
        """
        try:
            self.session.begin_edit_command()
            with self.session.edit_source("vertex(native)"):
                self.session.insert_vertex(
                    str(feature_id), tuple(int(i) for i in path), point)
        except Exception as exc:
            self.session.destroy_edit_command()
            _logger.debug("native vertex insert rejected: %s", exc)
            return False
        self.session.end_edit_command()
        return True

    def commit_vertex_delete(self, feature_id: str, path: tuple[int, ...]) -> bool:
        """V10 原生 Delete 键删点落会话（native-only）。守卫同 insert。"""
        try:
            self.session.begin_edit_command()
            with self.session.edit_source("vertex(native)"):
                self.session.delete_vertex(str(feature_id), tuple(int(i) for i in path))
        except Exception as exc:
            self.session.destroy_edit_command()
            _logger.debug("native vertex delete rejected: %s", exc)
            return False
        self.session.end_edit_command()
        return True


class RingCaptureTool(MapTool):
    """V10 添加内环（native-only）：原生 addPolygon 数字化器采环 → 会话 add_ring。

    无鼠标路径（fallback 不获得 native 专属能力，V7 §5）。环几何取捕获
    面要素的外环坐标（数字化器输出），session.add_ring 负责 ≥3 点与自动
    闭合守卫。
    """

    tool_id = "add_ring"
    edits_data = True

    def __init__(
        self,
        session: VectorEditSession,
        *,
        feature_id: str,
        apply_ring: Callable[[Mapping[str, object]], bool],
    ) -> None:
        super().__init__()
        self.session = session
        self.feature_id = str(feature_id)
        self._apply_ring = apply_ring

    def commit_geometry(self, geometry: Mapping[str, object]) -> bool:
        if not geometry or str(geometry.get("type")) not in {"Polygon", "MultiPolygon"}:
            return False
        with self.session.edit_source(f"{self.tool_id}(native)"):
            return bool(self._apply_ring(geometry))


class PartCaptureTool(MapTool):
    """V10 添加部件（native-only）：原生数字化器采部件 → 桥 add_part → 会话。

    部件几何类型随图层 kind（addPoint/addLine/addPolygon digitizer）。
    """

    tool_id = "add_part"
    edits_data = True

    def __init__(
        self,
        session: VectorEditSession,
        *,
        feature_id: str,
        apply_part: Callable[[Mapping[str, object]], bool],
    ) -> None:
        super().__init__()
        self.session = session
        self.feature_id = str(feature_id)
        self._apply_part = apply_part

    def commit_geometry(self, geometry: Mapping[str, object]) -> bool:
        if not geometry or "type" not in geometry:
            return False
        with self.session.edit_source(f"{self.tool_id}(native)"):
            return bool(self._apply_part(geometry))
