"""综合编修矢量编辑控制：图层新建 / QGIS 式编辑会话 / 数字化工具装配。

搬运 QGIS 的图层编辑语义（本仓库 ``mapping`` 模块即是该套实现的宿主移植）：

- ``VectorLayer`` 是数据权威；``VectorEditSession`` 提供编辑缓冲、
  撤销 / 重做、提交（保存编辑）与回滚。
- ``MapToolController`` 独占装配平移 / 缩放 / 识别 / 选择 / 框选 / 测距 /
  加点 / 加线 / 加面 / 移动要素 / 节点编辑工具。
- 命中测试与捕捉经 ``SnappingService`` 的 ``FeatureSpatialIndex``
  （修订缓存，编辑会话工作副本即时可见）。

控制器不持有任何面板部件：图层快照经 :meth:`snapshot_layers` 交给图层管理
面板合并进渲染快照，选择 / 捕捉 / 采点状态经 :meth:`overlay_state` 交给
画布 overlay 绘制。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from PySide6.QtCore import QObject, Signal

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.map_interaction import SnappingService
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.map_styles import default_style_for
from paleo_workbench.mapping.map_tools import (
    AddLineTool,
    AddPointTool,
    AddPolygonTool,
    MapToolController,
    MeasureDistanceTool,
    MoveFeatureTool,
    PanTool,
    RectangleSelectTool,
    SelectTool,
    VertexTool,
    ZoomTool,
)
from paleo_workbench.mapping.vector_layer import VectorLayer
from paleo_workbench.ui.map_action_controller import MapActionState

__all__ = ["CompositeEditController", "GEOMETRY_KINDS", "GEOMETRY_KIND_LABELS"]

GEOMETRY_KINDS: tuple[str, ...] = ("point", "line", "polygon")
GEOMETRY_KIND_LABELS: dict[str, str] = {"point": "点", "line": "线", "polygon": "面"}

# default_style_for 的符号库预设：点 → 井符号标记，线 → 线型，面 → 相带填充。
_KIND_STYLE_PRESET = {"point": "well", "line": "line", "polygon": "facies"}

_LAYER_ID_PREFIX = "composite:"

_LAYER_BOUND_TOOLS = frozenset(
    {"identify", "select", "select_rectangle", "move_feature", "vertex"}
)
_KIND_BOUND_TOOLS = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}


def _feature_extent(features: Iterable[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                xs.append(float(node[0]))
                ys.append(float(node[1]))
                return
            for child in node:
                walk(child)

    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, Mapping) else None
        if isinstance(geometry, Mapping):
            walk(geometry.get("coordinates"))
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))


class CompositeEditController(QObject):
    """综合编修文档的用户矢量图层与数字化会话。"""

    layers_changed = Signal()
    # 某一图层内容（几何 / 属性）发生变化，携带 layer_id。
    content_changed = Signal(str)
    # 选择 / 编辑态 / 撤销栈等纯状态变化（驱动工具条使能）。
    state_changed = Signal()

    def __init__(self, *, project_crs: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_crs = str(project_crs)
        self.tools = MapToolController()
        self._snapping = SnappingService()
        self._layers: dict[str, VectorLayer] = {}
        self._kinds: dict[str, str] = {}
        self._active_layer_id: str | None = None
        self._active_tool_action = "pan"
        self._canvas = None

    # -- 画布绑定 -------------------------------------------------------------

    def attach_canvas(self, canvas) -> None:
        """绑定 UnifiedMapCanvas：工具控制器与 overlay 提供者。"""
        self._canvas = canvas
        canvas.set_map_tool_controller(self.tools)
        canvas.set_overlay_provider(self.overlay_state)

    # -- 图层 CRUD -------------------------------------------------------------

    def layer_ids(self) -> tuple[str, ...]:
        return tuple(self._layers)

    def layer(self, layer_id: str) -> VectorLayer | None:
        return self._layers.get(str(layer_id))

    def kind_of(self, layer_id: str) -> str:
        return self._kinds.get(str(layer_id), "")

    @staticmethod
    def is_composite_layer(layer_id: str) -> bool:
        return str(layer_id).startswith(_LAYER_ID_PREFIX)

    def create_layer(self, name: str, kind: str) -> VectorLayer:
        kind = str(kind)
        if kind not in GEOMETRY_KINDS:
            raise ValueError(f"unsupported geometry kind {kind!r}")
        layer_id = f"{_LAYER_ID_PREFIX}{new_feature_id('layer')}"
        layer = VectorLayer(
            id=layer_id,
            name=str(name) or f"编修图层 {len(self._layers) + 1}",
            crs=self.project_crs,
            style=default_style_for(_KIND_STYLE_PRESET[kind]).to_dict(),
        )
        self._layers[layer_id] = layer
        self._kinds[layer_id] = kind
        self._active_layer_id = layer_id
        self.layers_changed.emit()
        self.state_changed.emit()
        return layer

    def remove_layer(self, layer_id: str) -> None:
        layer_id = str(layer_id)
        layer = self._layers.pop(layer_id, None)
        if layer is None:
            return
        if layer.edit_session is not None:
            layer.edit_session.rollback_changes()
        self._kinds.pop(layer_id, None)
        if self._active_layer_id == layer_id:
            self._active_layer_id = next(iter(self._layers), None)
            self._rebind_active_tool()
        self.layers_changed.emit()
        self.state_changed.emit()

    # -- 活动图层与编辑会话 -------------------------------------------------------

    @property
    def active_layer_id(self) -> str | None:
        return self._active_layer_id

    @property
    def active_layer(self) -> VectorLayer | None:
        return self._layers.get(self._active_layer_id or "")

    @property
    def editing(self) -> bool:
        layer = self.active_layer
        return layer is not None and layer.edit_session is not None

    def set_active_layer(self, layer_id: str | None) -> None:
        layer_id = str(layer_id) if layer_id else None
        if layer_id is not None and layer_id not in self._layers:
            layer_id = None
        if layer_id == self._active_layer_id:
            return
        self._active_layer_id = layer_id
        self._rebind_active_tool()
        self.state_changed.emit()

    def start_editing(self) -> None:
        layer = self.active_layer
        if layer is None or layer.edit_session is not None:
            return
        layer.start_editing()
        self.state_changed.emit()

    def save_edits(self) -> None:
        layer = self.active_layer
        if layer is None or layer.edit_session is None:
            return
        layer.edit_session.commit_changes()
        self.content_changed.emit(layer.id)
        self.state_changed.emit()

    def rollback_edits(self) -> None:
        layer = self.active_layer
        if layer is None or layer.edit_session is None:
            return
        layer.edit_session.rollback_changes()
        self.content_changed.emit(layer.id)
        self.state_changed.emit()

    # -- 工具装配 ---------------------------------------------------------------

    def _tolerance(self) -> float:
        canvas = self._canvas
        if canvas is None:
            return self._snapping.pixel_tolerance
        return self._snapping.pixel_tolerance * canvas.map_units_per_pixel

    def _snap(self, point: tuple[float, float]) -> tuple[float, float]:
        return self._snapping.snap(
            point, tolerance=self._tolerance(), layers=list(self._layers.values())
        )

    def activate_tool(self, action_id: str) -> None:
        canvas = self._canvas
        if action_id == "pan":
            tool = PanTool()
        elif action_id in {"zoom_in", "zoom_out"}:
            if canvas is None:
                return
            tool = ZoomTool(
                zoom=canvas.zoom_by,
                factor=0.5 if action_id == "zoom_in" else 2.0,
                tool_id=action_id,
            )
        elif action_id == "measure_distance":
            tool = MeasureDistanceTool()
        else:
            layer = self.active_layer
            if layer is None:
                return
            index = self._snapping.index_for(layer)
            if action_id in {"identify", "select"}:
                tool = SelectTool(layer, identify=lambda point: index.identify(point, self._tolerance()))
            elif action_id == "select_rectangle":
                tool = RectangleSelectTool(layer, select_rectangle=index.select_rectangle)
            else:
                session = layer.edit_session
                if session is None:
                    return
                # 加点 / 加线 / 加面只在与图层几何类型一致时激活，
                # 否则保持当前工具（不劫持用户的图层选择）。
                kind_required = _KIND_BOUND_TOOLS.get(action_id)
                if kind_required is not None and kind_required != self._kinds.get(layer.id):
                    return
                if action_id == "add_point":
                    tool = AddPointTool(session, snap=self._snap)
                elif action_id == "add_line":
                    tool = AddLineTool(session, snap=self._snap)
                elif action_id == "add_polygon":
                    tool = AddPolygonTool(session, snap=self._snap)
                elif action_id == "move_feature":
                    tool = MoveFeatureTool(session, identify=lambda point: index.identify(point, self._tolerance()))
                elif action_id == "vertex":
                    tool = VertexTool(session, identify_vertex=lambda point: index.identify_vertex(point, self._tolerance()))
                else:
                    return
        self._active_tool_action = action_id
        self.tools.set_active_tool(tool)
        if canvas is not None:
            canvas.setFocus()
        self.state_changed.emit()

    def _rebind_active_tool(self) -> None:
        action = self._active_tool_action
        if action in _LAYER_BOUND_TOOLS:
            if self.active_layer is None:
                self.activate_tool("pan")
            else:
                self.activate_tool(action)
        elif action in _KIND_BOUND_TOOLS:
            self.activate_tool("pan")

    # -- 命令 ------------------------------------------------------------------

    def set_snapping(self, enabled: bool) -> None:
        self._snapping.enabled = bool(enabled)

    def cancel_active_tool(self) -> None:
        self.tools.key_press("escape")
        self.state_changed.emit()

    def selection_command(self, command_id: str) -> None:
        layer = self.active_layer
        if layer is None:
            return
        if command_id == "clear_selection":
            layer.set_selection(())
        elif command_id == "select_all":
            layer.select_all()
        elif command_id == "invert_selection":
            layer.invert_selection()
        else:
            return
        self.state_changed.emit()

    def edit_command(self, command_id: str) -> bool:
        """执行编辑命令；返回 True 表示图层内容已变（宿主需重组快照）。"""
        layer = self.active_layer
        session = layer.edit_session if layer is not None else None
        if command_id == "undo" and session is not None:
            if session.undo():
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True
            return False
        if command_id == "redo" and session is not None:
            if session.redo():
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True
            return False
        if command_id == "delete_selected" and session is not None and layer.selection:
            for feature_id in sorted(layer.selection):
                session.delete_feature(feature_id)
            layer.set_selection(())
            self.content_changed.emit(layer.id)
            self.state_changed.emit()
            return True
        return False

    # -- 快照与状态 -------------------------------------------------------------

    def snapshot_layers(self, *, display: Mapping[str, MapLayerSnapshot] | None = None) -> tuple[MapLayerSnapshot, ...]:
        """所有用户图层的渲染快照（自下而上）。

        ``display`` 提供图层管理面板当前持有的快照（可见性 / 不透明度 /
        用户改名以其为准）；内容与修订永远由编辑权威（VectorLayer /
        编辑会话工作副本）重建。
        """
        display = display or {}
        snapshots: list[MapLayerSnapshot] = []
        for layer_id, layer in self._layers.items():
            session = layer.edit_session
            source = session.features() if session is not None else layer.features()
            features = tuple(feature.as_record() for feature in source)
            revision = layer.data_revision if session is None else (layer.data_revision << 32) + session.revision
            previous = display.get(layer_id)
            snapshots.append(
                MapLayerSnapshot(
                    id=layer.id,
                    name=layer.name,
                    layer_type="vector",
                    extent=_feature_extent(features),
                    crs=layer.crs,
                    data_revision=revision,
                    style_revision=layer.style_revision,
                    features=features,
                    style=dict(layer.style),
                    visible=True if previous is None else bool(previous.visible),
                    opacity=1.0 if previous is None else float(previous.opacity),
                    metadata={
                        "editable": "true",
                        "geometry_kind": self._kinds.get(layer_id, ""),
                        "editing": "true" if session is not None else "false",
                    },
                )
            )
        return tuple(snapshots)

    def action_state(self, *, can_previous_extent: bool = False, can_next_extent: bool = False) -> MapActionState:
        layer = self.active_layer
        session = layer.edit_session if layer is not None else None
        return MapActionState(
            has_active_vector_layer=layer is not None,
            vector_layer_writable=layer is not None,
            editing=session is not None,
            selected_count=len(layer.selection) if layer is not None else 0,
            can_undo=bool(session and session.undo_stack),
            can_redo=bool(session and session.redo_stack),
            can_previous_extent=can_previous_extent,
            can_next_extent=can_next_extent,
        )

    def overlay_state(self) -> dict[str, Any]:
        """画布 overlay：选中要素高亮 / 采点预览 / 捕捉标记。"""
        selected = []
        for layer in self._layers.values():
            if not layer.selection:
                continue
            session = layer.edit_session
            source = session.features() if session is not None else layer.features()
            selected.extend(
                feature for feature in source if feature.feature_id in layer.selection
            )
        tool = self.tools.active_tool
        capture = list(getattr(tool, "points", ()) or ())
        snap = self._snapping.last_match.point if self._snapping.last_match is not None else None
        return {
            "selected_features": selected,
            "capture_points": capture,
            "snap_point": snap,
        }
