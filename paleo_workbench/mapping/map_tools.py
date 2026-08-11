"""QGIS-inspired renderer-independent map-tool state machines."""

from __future__ import annotations

import math
from typing import Callable, Iterable

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.vector_layer import VectorEditSession, VectorFeature, VectorLayer

__all__ = [
    "AddLineTool",
    "AddPointTool",
    "AddPolygonTool",
    "MapTool",
    "MapToolController",
    "MeasureDistanceTool",
    "MoveFeatureTool",
    "PanTool",
    "RectangleSelectTool",
    "SelectTool",
    "VertexTool",
    "ZoomTool",
]

Point = tuple[float, float]


class MapTool:
    """One exclusive interactive operation; rendering overlays remain external."""

    tool_id = "tool"

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

    def __init__(self, *, measurement_ready: Callable[[float], None] | None = None) -> None:
        super().__init__()
        self._measurement_ready = measurement_ready
        self.start: Point | None = None
        self.current: Point | None = None

    @property
    def points(self) -> list[Point]:
        return [point for point in (self.start, self.current) if point is not None]

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button == "right":
            return self.cancel()
        if button != "left":
            return False
        if self.start is None:
            self.start = point
            self.current = point
            return True
        distance = math.dist(self.start, point)
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
        if "ctrl" in mods:
            self.layer.set_selection(self.layer.selection | selected)
        elif "shift" in mods:
            self.layer.set_selection(self.layer.selection ^ selected)
        else:
            self.layer.set_selection(selected)
        return True

    def cancel(self) -> bool:
        had_start = self.start is not None
        self.start = None
        return had_start


class _CaptureTool(MapTool):
    geometry_type = ""
    tool_id = "capture"

    def __init__(
        self,
        session: VectorEditSession,
        *,
        feature_id_factory: Callable[[], str] | None = None,
        snap: Callable[[Point], Point] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._feature_id_factory = feature_id_factory or (lambda: new_feature_id(self.tool_id))
        self._snap = snap or (lambda point: (float(point[0]), float(point[1])))
        self.points: list[Point] = []

    def mouse_press(self, point: Point, *, button: str = "left", modifiers: Iterable[str] = ()) -> bool:
        if button == "right":
            return self.finish()
        if button != "left":
            return False
        self.points.append(self._snap(point))
        return self.geometry_type == "Point" and self.finish()

    def double_click(self, point: Point, *, modifiers: Iterable[str] = ()) -> bool:
        self.points.append(self._snap(point))
        return self.finish()

    def cancel(self) -> bool:
        had_points = bool(self.points)
        self.points.clear()
        return had_points or True

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
        self.session.add_feature(VectorFeature(self._feature_id_factory(), geometry))
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
        self.session.move_feature(feature_id, point[0] - origin[0], point[1] - origin[1])
        return True

    def cancel(self) -> bool:
        had_drag = self._feature_id is not None
        self._feature_id = None
        self._origin = None
        return had_drag


class VertexTool(MapTool):
    tool_id = "vertex"

    def __init__(
        self,
        session: VectorEditSession,
        *,
        identify_vertex: Callable[[Point], tuple[str, tuple[int, ...]] | None],
        on_vertex_committed: Callable[[str, tuple[int, ...], Point, Point], None] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._identify_vertex = identify_vertex
        self._on_vertex_committed = on_vertex_committed
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
        origin = self._origin
        self._target = None
        self._origin = None
        self.session.set_vertex(feature_id, path, point)
        if origin is not None and self._on_vertex_committed is not None:
            self._on_vertex_committed(feature_id, path, origin, point)
        return True

    def cancel(self) -> bool:
        had_target = self._target is not None
        self._target = None
        self._origin = None
        return had_target
