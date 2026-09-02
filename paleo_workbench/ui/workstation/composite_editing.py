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

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from PySide6.QtCore import QObject, Signal

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.map_interaction import SnappingService
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.map_styles import (
    STYLE_LIBRARY,
    LinePattern,
    VectorStyle,
    default_style_for,
)
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
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.project.models import UserVectorFeature, UserVectorLayer
from paleo_workbench.ui.map_action_controller import MapActionState

__all__ = [
    "CompositeEditController",
    "GEOMETRY_KINDS",
    "GEOMETRY_KIND_LABELS",
    "GEO_TEMPLATES",
    "GeoTemplate",
    "TemplateField",
    "fields_to_schema",
    "schema_fields",
    "template_by_key",
]

GEOMETRY_KINDS: tuple[str, ...] = ("point", "line", "polygon")
GEOMETRY_KIND_LABELS: dict[str, str] = {"point": "点", "line": "线", "polygon": "面"}

# default_style_for 的符号库预设：点 → 井符号标记，线 → 线型，面 → 相带填充。
_KIND_STYLE_PRESET = {"point": "well", "line": "line", "polygon": "facies"}


@dataclass(frozen=True, slots=True)
class TemplateField:
    """地质图层字段描述：数据驱动的可扩展 schema（不硬编码进 UI 控件树）。

    ``kind`` ∈ text / number / choice；choice 字段携带候选值。default 是
    新要素的初始属性值；required 驱动属性校验（标记缺失，不阻断数字化）。
    """

    name: str
    label: str = ""
    kind: str = "text"
    choices: tuple[str, ...] = ()
    default: object = ""
    required: bool = False

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "label": self.label or self.name,
            "kind": self.kind,
            "required": self.required,
        }
        if self.choices:
            data["choices"] = list(self.choices)
        if self.default not in ("", None):
            data["default"] = self.default
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TemplateField":
        if not isinstance(data, Mapping) or not str(data.get("name") or ""):
            raise ValueError("template field requires a name")
        kind = str(data.get("kind") or "text")
        if kind not in {"text", "number", "choice"}:
            kind = "text"
        choices = tuple(str(c) for c in (data.get("choices") or ()) if str(c))
        if kind == "choice" and not choices:
            kind = "text"
        default = data.get("default", "")
        if kind == "number":
            try:
                default = float(default) if default not in ("", None) else ""
            except (TypeError, ValueError):
                default = ""
        return cls(
            name=str(data["name"]),
            label=str(data.get("label") or data["name"]),
            kind=kind,
            choices=choices,
            default=default,
            required=bool(data.get("required")),
        )


def fields_to_schema(fields: Iterable["TemplateField"]) -> dict[str, object]:
    return {"fields": [field.to_dict() for field in fields]}


def schema_fields(schema: Mapping[str, object] | None) -> tuple[TemplateField, ...]:
    raw = (schema or {}).get("fields") if isinstance(schema, Mapping) else None
    fields: list[TemplateField] = []
    for item in raw or ():
        try:
            fields.append(TemplateField.from_dict(item))
        except (ValueError, TypeError):
            continue
    return tuple(fields)


@dataclass(frozen=True, slots=True)
class GeoTemplate:
    """地质矢量图层模板：角色 + 几何类型 + 字段 schema + 默认样式。

    模板是专业编修的起点（QGIS「新建 Shapefile 图层」的地质版）：字段
    schema 数据驱动，属性表 / 图层属性 / 校验全部从 schema 生成。
    """

    key: str
    label: str
    kind: str
    style: VectorStyle
    fields: tuple[TemplateField, ...] = ()

    def field_defaults(self) -> dict[str, object]:
        return {field.name: field.default for field in self.fields if field.default != ""}


def _field(
    name: str, label: str, *, kind: str = "text", choices: tuple[str, ...] = (),
    default: object = "", required: bool = False,
) -> TemplateField:
    return TemplateField(name, label, kind, choices, default, required)


_CONFIDENCE = ("高", "中", "低")

# 新建矢量图层的地质模板（QGIS「新建 Shapefile 图层」对话框的专业化版本）。
# 样式取自符号库预设或按地质制图惯例定制：断层走 FAULT 长短线，展布线
# 用蓝色虚线，成图范围用无填充的橙色边界。字段 schema 覆盖断层 / 相带 /
# 物源线 / 展布线 / 打断线 / 方向线的实际业务字段。
GEO_TEMPLATES: tuple[GeoTemplate, ...] = (
    GeoTemplate(
        "well_point", "测井点", "point", default_style_for("well"),
        fields=(
            _field("name", "井名", required=True),
            _field("operator", "作业者"),
            _field("purpose", "井别", kind="choice", choices=("探井", "评价井", "开发井", "参数井")),
            _field("spud_date", "开钻日期"),
            _field("source", "资料来源"),
        ),
    ),
    GeoTemplate(
        "fault", "断层线", "line", STYLE_LIBRARY["fault"],
        fields=(
            _field("name", "断层名称", required=True),
            _field("fault_type", "断层性质", kind="choice",
                   choices=("正断层", "逆断层", "走滑断层", "逆掩断层", "未定")),
            _field("confidence", "可信度", kind="choice", choices=_CONFIDENCE, default="中"),
            _field("strike", "走向（°）", kind="number"),
            _field("throw", "断距（m）", kind="number"),
            _field("horizon", "层位"),
            _field("interpreter", "解释人"),
            _field("source", "资料来源"),
        ),
    ),
    GeoTemplate(
        "facies", "相带", "polygon", default_style_for("facies"),
        fields=(
            _field("facies", "相带类型", kind="choice",
                   choices=("冲积扇", "河流", "三角洲", "滨浅湖", "半深湖", "深湖", "海底扇", "浊积", "碳酸盐岩台地")),
            _field("lithology", "岩性"),
            _field("confidence", "可信度", kind="choice", choices=_CONFIDENCE, default="中"),
            _field("horizon", "层位", required=True),
            _field("source", "资料来源"),
        ),
    ),
    GeoTemplate(
        "source", "物源线", "line",
        VectorStyle(fill="transparent", stroke="#d62728", stroke_width=2.5),
        fields=(
            _field("source_type", "物源类型", kind="choice",
                   choices=("点物源", "多物源", "侧向物源", "未知")),
            _field("direction", "方向（如 NNE）"),
            _field("confidence", "可信度", kind="choice", choices=_CONFIDENCE, default="中"),
            _field("horizon", "层位"),
        ),
    ),
    GeoTemplate(
        "spreading", "展布线", "line",
        VectorStyle(
            fill="transparent",
            stroke="#1c7ed6",
            stroke_width=2.0,
            line_pattern=LinePattern.DASH,
        ),
        fields=(
            _field("spreading_type", "展布类型", kind="choice", choices=("边界展布", "内部展布", "推测展布")),
            _field("horizon", "层位"),
            _field("confidence", "可信度", kind="choice", choices=_CONFIDENCE, default="中"),
        ),
    ),
    GeoTemplate(
        "break", "打断线", "line",
        VectorStyle(
            fill="transparent",
            stroke="#868e96",
            stroke_width=1.5,
            line_pattern=LinePattern.DASH,
        ),
        fields=(
            _field("break_type", "打断类型", kind="choice", choices=("剥蚀", "构造缺失", "资料缺失")),
            _field("horizon", "层位"),
            _field("related", "关联层位"),
        ),
    ),
    GeoTemplate(
        "direction", "方向线", "line",
        VectorStyle(fill="transparent", stroke="#2f9e44", stroke_width=2.0),
        fields=(
            _field("direction", "方向（如 NE45°）", required=True),
            _field("horizon", "层位"),
            _field("confidence", "可信度", kind="choice", choices=_CONFIDENCE, default="中"),
        ),
    ),
    GeoTemplate(
        "extent", "成图范围", "polygon", STYLE_LIBRARY["formation_boundary"],
        fields=(
            _field("name", "范围名称", required=True),
            _field("phase", "编制阶段", kind="choice", choices=("普查", "详查", "精查")),
            _field("remark", "备注"),
        ),
    ),
)

_TEMPLATE_BY_KEY: dict[str, GeoTemplate] = {t.key: t for t in GEO_TEMPLATES}


def template_by_key(key: str) -> GeoTemplate | None:
    return _TEMPLATE_BY_KEY.get(str(key))

_LAYER_ID_PREFIX = "composite:"

_LAYER_BOUND_TOOLS = frozenset(
    {"identify", "select", "select_rectangle", "move_feature", "vertex"}
)
_KIND_BOUND_TOOLS = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}


def _coords_to_lists(value: Any) -> Any:
    """GeoJSON 坐标归一化：shapely mapping() 返回 tuple，比较前统一为 list。"""
    if isinstance(value, (list, tuple)):
        return [_coords_to_lists(item) for item in value]
    return value


def _geometry_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return str(left.get("type")) == str(right.get("type")) and (
        _coords_to_lists(left.get("coordinates")) == _coords_to_lists(right.get("coordinates"))
    )


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


def _segments(value: Any) -> Iterable[tuple[tuple[float, float], tuple[float, float]]]:
    """展平 GeoJSON coordinates 为线段序列（含 Polygon 环）。"""
    points: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                points.append((float(node[0]), float(node[1])))
                return
            for child in node:
                walk(child)

    walk(value)
    for index in range(len(points) - 1):
        yield points[index], points[index + 1]


def _point_in_ring(point: tuple[float, float], ring: Any) -> bool:
    points: list[tuple[float, float]] = []
    for node in ring or ():
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 2
            and isinstance(node[0], (int, float))
            and isinstance(node[1], (int, float))
        ):
            points.append((float(node[0]), float(node[1])))
    if len(points) < 3:
        return False
    inside = False
    x, y = point
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def _geometry_hit(point: tuple[float, float], geometry: Mapping[str, Any], tolerance: float) -> bool:
    """快照记录的粗命中测试：点距 / 线距 / 多边形 even-odd。"""
    import math as _math

    kind = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        try:
            return _math.dist(point, (float(coordinates[0]), float(coordinates[1]))) <= tolerance
        except (TypeError, ValueError, IndexError):
            return False
    if kind in {"LineString", "MultiLineString"}:
        for start, end in _segments(coordinates):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_squared = dx * dx + dy * dy
            if length_squared <= 0.0:
                if _math.dist(point, start) <= tolerance:
                    return True
                continue
            t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
            if _math.dist(point, (start[0] + t * dx, start[1] + t * dy)) <= tolerance:
                return True
        return False
    if kind == "Polygon":
        rings = list(coordinates or [])
        if rings and _point_in_ring(point, rings[0]):
            return all(not _point_in_ring(point, ring) for ring in rings[1:])
        return any(_math.dist(point, vertex) <= tolerance for vertex, _path in _ring_vertices(rings))
    if kind == "MultiPolygon":
        return any(_geometry_hit(point, {"type": "Polygon", "coordinates": poly}, tolerance) for poly in coordinates or ())
    return False


def _ring_vertices(rings: Any) -> Iterable[tuple[tuple[float, float], tuple[int, ...]]]:
    for ring_index, ring in enumerate(rings or ()):
        for point_index, node in enumerate(ring or ()):
            if (
                isinstance(node, (list, tuple))
                and len(node) >= 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
            ):
                yield (float(node[0]), float(node[1])), (ring_index, point_index)


class CompositeEditController(QObject):
    """综合编修文档的用户矢量图层与数字化会话。"""

    layers_changed = Signal()
    # 某一图层内容（几何 / 属性）发生变化，携带 layer_id。
    content_changed = Signal(str)
    # 会话已提交 / 回滚（数据进入图层权威，宿主须立即同步工程文档）。
    sessions_committed = Signal()
    # 选择 / 编辑态 / 撤销栈等纯状态变化（驱动工具条使能）。
    state_changed = Signal()

    def __init__(self, *, project_crs: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_crs = str(project_crs)
        self.tools = MapToolController()
        self._snapping = SnappingService()
        self._topology = TopologyService()
        self._layers: dict[str, VectorLayer] = {}
        self._kinds: dict[str, str] = {}
        self._templates: dict[str, str] = {}
        self._schemas: dict[str, dict] = {}
        # 图层管理面板的显示态（可见性 / 不透明度），供持久化还原。
        self._display: dict[str, tuple[bool, float]] = {}
        self._active_layer_id: str | None = None
        self._active_tool_action = "pan"
        self._canvas = None
        # 宿主注入的多图层识别回调（Identify Results 面板）；缺省单图层命中。
        self.identify_delegate: Any = None
        # 修订键控的序列化缓存：数字化点击只重组变化图层，不整层重编码
        # （review #6：100k 要素时每次点击的全量 as_record 是 GUI 线程热点）。
        self._records_cache: dict[str, tuple[int, tuple, tuple]] = {}
        self._persist_cache: dict[str, tuple[int, list]] = {}

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

    def create_layer(self, name: str, kind: str, template: str = "") -> VectorLayer:
        kind = str(kind)
        if kind not in GEOMETRY_KINDS:
            raise ValueError(f"unsupported geometry kind {kind!r}")
        geo_template = _TEMPLATE_BY_KEY.get(str(template))
        schema: dict[str, object] = {}
        if geo_template is not None:
            kind = geo_template.kind
            style = geo_template.style.to_dict()
            schema = fields_to_schema(geo_template.fields)
            if not str(name).strip():
                name = geo_template.label
        else:
            template = ""
            style = default_style_for(_KIND_STYLE_PRESET[kind]).to_dict()
        layer_id = f"{_LAYER_ID_PREFIX}{new_feature_id('layer')}"
        layer = VectorLayer(
            id=layer_id,
            name=str(name) or f"编修图层 {len(self._layers) + 1}",
            crs=self.project_crs,
            schema=schema,
            style=style,
        )
        self._layers[layer_id] = layer
        self._kinds[layer_id] = kind
        self._templates[layer_id] = template
        self._schemas[layer_id] = dict(schema)
        self._active_layer_id = layer_id
        self.layers_changed.emit()
        self.state_changed.emit()
        return layer

    def rename_layer(self, layer_id: str, name: str) -> None:
        layer = self._layers.get(str(layer_id))
        name = str(name).strip()
        if layer is None or not name or layer.name == name:
            return
        layer.name = name
        self.layers_changed.emit()

    def layer_template(self, layer_id: str) -> str:
        return self._templates.get(str(layer_id), "")

    def layer_schema(self, layer_id: str) -> dict[str, object]:
        """图层字段 schema（模板 schema 或自定义空 schema）。"""
        layer = self._layers.get(str(layer_id))
        if layer is not None and layer.schema:
            return dict(layer.schema)
        return dict(self._schemas.get(str(layer_id), {}))

    def set_layer_style(self, layer_id: str, style: Mapping[str, object]) -> None:
        """写入图层样式（图层属性 / 符号系统 / 标注对话框的落地路径）。"""
        layer = self._layers.get(str(layer_id))
        if layer is None:
            return
        layer.style = dict(style)
        layer.style_revision += 1
        self.layers_changed.emit()
        self.state_changed.emit()

    def duplicate_layer(self, layer_id: str) -> VectorLayer | None:
        """复制图层（要素 + 样式 + schema，得到独立的新图层）。"""
        source = self._layers.get(str(layer_id))
        if source is None:
            return None
        kind = self._kinds.get(str(layer_id), "line")
        layer_id_new = f"{_LAYER_ID_PREFIX}{new_feature_id('layer')}"
        copy = VectorLayer(
            id=layer_id_new,
            name=f"{source.name} 副本",
            crs=source.crs,
            schema=dict(source.schema),
            style=dict(source.style),
            features=[
                VectorFeature(
                    feature_id=new_feature_id("copy"),
                    geometry=dict(feature.geometry),
                    attributes=dict(feature.attributes),
                )
                for feature in source.features()
            ],
        )
        copy.style_revision = source.style_revision + 1
        self._layers[layer_id_new] = copy
        self._kinds[layer_id_new] = kind
        self._templates[layer_id_new] = self._templates.get(str(layer_id), "")
        self._schemas[layer_id_new] = dict(source.schema)
        self._active_layer_id = layer_id_new
        self.layers_changed.emit()
        self.state_changed.emit()
        return copy

    def remove_layer(self, layer_id: str) -> None:
        layer_id = str(layer_id)
        layer = self._layers.pop(layer_id, None)
        if layer is None:
            return
        if layer.edit_session is not None:
            layer.edit_session.rollback_changes()
        self._kinds.pop(layer_id, None)
        self._templates.pop(layer_id, None)
        self._schemas.pop(layer_id, None)
        self._display.pop(layer_id, None)
        self._snapping.layer_enabled.pop(layer_id, None)
        self._snapping.layer_modes.pop(layer_id, None)
        self._snapping.layer_tolerance.pop(layer_id, None)
        self._snapping.layer_priority.pop(layer_id, None)
        self._records_cache.pop(layer_id, None)
        self._persist_cache.pop(layer_id, None)
        if self._active_layer_id == layer_id:
            self._active_layer_id = next(iter(self._layers), None)
            self._rebind_active_tool()
        self.layers_changed.emit()
        self.state_changed.emit()

    # -- 工程持久化（人工建数据纳入数据管理） --------------------------------------

    def load_from_project(self, project) -> None:
        """从工程文档恢复人工矢量图层（替换当前全部图层）。"""
        for layer in self._layers.values():
            if layer.edit_session is not None:
                layer.edit_session.rollback_changes()
        self._layers.clear()
        self._kinds.clear()
        self._templates.clear()
        self._schemas.clear()
        self._display.clear()
        self._records_cache.clear()
        self._persist_cache.clear()
        self._active_layer_id = None
        for record in list(getattr(project, "user_vector_layers", None) or []):
            kind = str(getattr(record, "geometry_kind", "") or "line")
            if kind not in GEOMETRY_KINDS:
                kind = "line"
            features = []
            for item in list(getattr(record, "features", None) or []):
                geometry = getattr(item, "geometry", None)
                if not isinstance(geometry, Mapping) or not geometry.get("type"):
                    continue
                features.append(
                    VectorFeature(
                        feature_id=str(item.id),
                        geometry=dict(geometry),
                        attributes=dict(getattr(item, "properties", None) or {}),
                    )
                )
            template = _TEMPLATE_BY_KEY.get(str(getattr(record, "template", "") or ""))
            style = dict(getattr(record, "style", None) or {})
            if not style:
                style = (
                    template.style.to_dict()
                    if template is not None
                    else default_style_for(_KIND_STYLE_PRESET[kind]).to_dict()
                )
            schema = dict(getattr(record, "field_schema", None) or {})
            if not schema and template is not None:
                schema = fields_to_schema(template.fields)
            layer = VectorLayer(
                id=str(record.id),
                name=str(getattr(record, "name", "") or "编修图层"),
                crs=str(getattr(record, "crs", "") or self.project_crs),
                schema=schema,
                style=style,
                features=features,
            )
            self._layers[layer.id] = layer
            self._kinds[layer.id] = kind
            self._templates[layer.id] = str(getattr(record, "template", "") or "")
            self._schemas[layer.id] = dict(schema)
            self._display[layer.id] = (
                bool(getattr(record, "visible", True)),
                float(getattr(record, "opacity", 1.0) or 1.0),
            )
        if self._layers:
            self._active_layer_id = next(iter(self._layers))
        self._rebind_active_tool()
        self.layers_changed.emit()
        self.state_changed.emit()

    def sync_to_project(self, project) -> None:
        """把当前人工矢量图层写回工程文档（磁盘保存走既有工程保存流程）。

        只序列化已提交的要素——进行中的编辑会话遵循 QGIS 语义，
        「保存编辑」后才成为图层内容。
        """
        records: list[UserVectorLayer] = []
        for layer_id, layer in self._layers.items():
            visible, opacity = self._display.get(layer_id, (True, 1.0))
            cached = self._persist_cache.get(layer_id)
            if cached is not None and cached[0] == layer.data_revision:
                persisted = cached[1]
            else:
                persisted = [
                    UserVectorFeature(
                        id=feature.feature_id,
                        geometry=dict(feature.geometry),
                        properties=dict(feature.attributes),
                    )
                    for feature in layer.features()
                ]
                self._persist_cache[layer_id] = (layer.data_revision, persisted)
            records.append(
                UserVectorLayer(
                    id=layer.id,
                    name=layer.name,
                    geometry_kind=self._kinds.get(layer_id, "line"),
                    template=self._templates.get(layer_id, ""),
                    crs=layer.crs,
                    style=dict(layer.style),
                    field_schema=dict(layer.schema or self._schemas.get(layer_id) or {}),
                    features=list(persisted),
                    visible=visible,
                    opacity=opacity,
                )
            )
        project.user_vector_layers = records

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

    def save_edits(self) -> str | None:
        """提交活动图层编辑会话；返回 None 表示成功，否则为阻断原因。

        拓扑编辑开启时执行与编图页一致的校验门禁（TopologyService）：
        无效几何阻断保存并给出原因，修复（make-valid）后可再保存。
        """
        layer = self.active_layer
        if layer is None or layer.edit_session is None:
            return None
        if self._topology.enabled:
            issues = self._topology.validate([layer])
            if issues:
                first = issues[0]
                return (
                    f"图层「{layer.name}」要素 {first.get('feature_id', '')} "
                    f"未通过拓扑检查：{first.get('message', '')}"
                )
        layer.edit_session.commit_changes()
        self.content_changed.emit(layer.id)
        # 会话已被图层收回：活动工具若持有旧 session 缓冲必须立刻重绑
        # （回落 pan），否则继续数字化会写进已脱钩的缓冲（review #1）。
        self._rebind_active_tool()
        self.sessions_committed.emit()
        self.state_changed.emit()
        return None

    def rollback_edits(self) -> None:
        layer = self.active_layer
        if layer is None or layer.edit_session is None:
            return
        layer.edit_session.rollback_changes()
        self.content_changed.emit(layer.id)
        self._rebind_active_tool()
        self.sessions_committed.emit()
        self.state_changed.emit()

    def flush_edit_sessions(self) -> tuple[int, list[str]]:
        """提交所有图层的进行中编辑会话（工程保存 / 切换前调用）。

        QGIS 语义下未「保存编辑」的数字化不进图层，但工程保存路径不能
        静默丢弃它们（#1126）：保存 = 提交全部会话 + 写回工程文档。
        拓扑门禁与「保存编辑」一致（review #3）：校验失败的会话保持打开
        （可回滚 / 可修复），不把无效几何写进工程。返回
        (提交数, 被阻断图层的用户可读原因)。
        """
        committed = 0
        blocked: list[str] = []
        for layer in self._layers.values():
            session = layer.edit_session
            if session is None:
                continue
            if self._topology.enabled:
                issues = self._topology.validate([layer])
                if issues:
                    first = issues[0]
                    blocked.append(
                        f"图层「{layer.name}」要素 {first.get('feature_id', '')} "
                        f"未通过拓扑检查（该图层编辑未提交）：{first.get('message', '')}"
                    )
                    continue
            session.commit_changes()
            committed += 1
            self.content_changed.emit(layer.id)
        if committed:
            self._rebind_active_tool()
            self.sessions_committed.emit()
            self.state_changed.emit()
        return committed, blocked

    # -- 工具装配 ---------------------------------------------------------------

    def _tolerance(self) -> float:
        canvas = self._canvas
        if canvas is None:
            return self._snapping.pixel_tolerance
        return self._snapping.pixel_tolerance * canvas.map_units_per_pixel

    def _snap(self, point: tuple[float, float]) -> tuple[float, float]:
        canvas = self._canvas
        mupp = canvas.map_units_per_pixel if canvas is not None else 1.0
        return self._snapping.snap(
            point,
            tolerance=self._tolerance(),
            layers=list(self._layers.values()),
            map_units_per_pixel=mupp,
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
                if action_id == "identify" and callable(self.identify_delegate):
                    identify_callable = self.identify_delegate
                else:
                    identify_callable = lambda point: index.identify(point, self._tolerance())
                tool = SelectTool(layer, identify=identify_callable)
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
                template = _TEMPLATE_BY_KEY.get(self._templates.get(layer.id, ""))
                defaults = template.field_defaults() if template is not None else {}
                if action_id == "add_point":
                    tool = AddPointTool(session, snap=self._snap, attributes=defaults)
                elif action_id == "add_line":
                    tool = AddLineTool(session, snap=self._snap, attributes=defaults)
                elif action_id == "add_polygon":
                    tool = AddPolygonTool(session, snap=self._snap, attributes=defaults)
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
        session_actions = {"add_point", "add_line", "add_polygon", "move_feature", "vertex"}
        if action in session_actions:
            layer = self.active_layer
            # 会话级工具在会话消失（保存/回滚/flush 提交）后必须回落 pan：
            # 旧工具持有的 session 缓冲已与图层脱钩，继续数字化会静默丢失。
            if layer is None or layer.edit_session is None:
                self.activate_tool("pan")
                return
            if (
                action in _KIND_BOUND_TOOLS
                and _KIND_BOUND_TOOLS[action] != self._kinds.get(layer.id)
            ):
                self.activate_tool("pan")
                return
            self.activate_tool(action)
        elif action in _LAYER_BOUND_TOOLS:
            if self.active_layer is None:
                self.activate_tool("pan")
            else:
                self.activate_tool(action)
        elif action in _KIND_BOUND_TOOLS:
            self.activate_tool("pan")

    # -- 命令 ------------------------------------------------------------------

    def set_snapping(self, enabled: bool) -> None:
        self._snapping.enabled = bool(enabled)

    @property
    def snapping(self) -> SnappingService:
        """捕捉配置面（per-layer enable/modes/tolerance/priority，#Phase9）。"""
        return self._snapping

    def set_topology(self, enabled: bool) -> None:
        """拓扑编辑开关：开启后保存编辑执行拓扑校验门禁。"""
        self._topology.enabled = bool(enabled)
        self.state_changed.emit()

    @property
    def topology_enabled(self) -> bool:
        return self._topology.enabled

    def validate_active_layer_topology(self) -> list[dict[str, object]]:
        """对活动图层（或其编辑工作副本）执行拓扑检查，返回问题清单。"""
        layer = self.active_layer
        if layer is None:
            return []
        return self._topology.validate([layer])

    def repair_layer_geometries(self, layer_id: str) -> int:
        """修复图层无效几何（QGIS make-valid 优先，shapely 兜底）。

        修复结果经 ``SetGeometryCommand`` 写入编辑会话：可撤销、可回滚、
        可审计，与直接改数据无缘。
        """
        from paleo_workbench.mapping.geometry_service import make_geometry_valid

        layer = self._layers.get(str(layer_id))
        if layer is None:
            return 0
        opened_session = layer.edit_session is None
        session = layer.edit_session or layer.start_editing()
        repaired = 0
        for feature in session.features():
            geometry = feature.as_record()["geometry"]
            if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            fixed = make_geometry_valid(geometry)
            if not _geometry_equal(fixed, geometry):
                session.set_geometry(feature.feature_id, fixed)
                repaired += 1
        if repaired:
            self.content_changed.emit(layer.id)
            self.state_changed.emit()
        elif opened_session:
            # 没有需要修复的要素时不留幽灵会话（review #12）。
            session.rollback_changes()
            self.state_changed.emit()
        return repaired

    # -- 几何命令（split / merge） -----------------------------------------------

    def _split_inputs(self):
        """定位分割输入：一个正在编辑且有多边形选中的图层 + 一条选中的切割线。"""
        polygon_layer = None
        active = self.active_layer
        if (
            active is not None
            and self._kinds.get(active.id) == "polygon"
            and active.selection
            and active.edit_session is not None
        ):
            polygon_layer = active
        else:
            for layer_id, kind in self._kinds.items():
                layer = self._layers[layer_id]
                if kind == "polygon" and layer.selection and layer.edit_session is not None:
                    polygon_layer = layer
                    break
        if polygon_layer is None:
            return None
        for layer_id, kind in self._kinds.items():
            if kind != "line":
                continue
            line_layer = self._layers[layer_id]
            if not line_layer.selection:
                continue
            line_id = next(iter(sorted(line_layer.selection)))
            source = line_layer.edit_session or line_layer
            try:
                line_feature = source.feature(line_id)
            except KeyError:
                continue
            polygon_id = next(iter(sorted(polygon_layer.selection)))
            return polygon_layer, polygon_id, line_feature
        return None

    def geometry_command(self, command_id: str) -> tuple[bool, str]:
        """执行 split / merge；返回 (是否成功, 用户可读消息)。

        几何计算走 ``geometry_service``（QGIS 桥可用时）或 ``vector_operations``
        的 shapely 兜底；结果一律落为 ``VectorEditSession`` 命令——undo/redo/
        commit/project 版本链保持完整，QGIS 从不直接改工程数据。
        """
        from paleo_workbench.mapping.vector_operations import (
            merge_selected_polygons,
            split_polygon_by_line,
        )

        layer = self.active_layer
        if layer is None:
            return False, "没有活动的矢量图层"
        session = layer.edit_session
        if session is None:
            return False, "请先开始编辑（几何操作需要编辑会话）"
        try:
            if command_id == "merge":
                if not layer.selection:
                    return False, "请先选择要合并的要素"
                new_id = merge_selected_polygons(session, layer.selection)
                layer.set_selection((new_id,))
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True, "已合并所选要素"
            if command_id == "split":
                inputs = self._split_inputs()
                if inputs is None:
                    return False, "分割需要一个选中多边形（正在编辑）与一条选中的切割线"
                polygon_layer, polygon_id, line_feature = inputs
                new_ids = split_polygon_by_line(
                    polygon_layer.edit_session, polygon_id, line_feature
                )
                polygon_layer.set_selection(new_ids)
                if polygon_layer is not layer:
                    self._active_layer_id = polygon_layer.id
                    self._rebind_active_tool()
                self.content_changed.emit(polygon_layer.id)
                self.state_changed.emit()
                return True, "已按切割线分割多边形"
        except (KeyError, RuntimeError, ValueError) as exc:
            return False, str(exc)
        return False, f"未知几何命令 {command_id}"

    # -- 多图层识别 -------------------------------------------------------------

    def identify_all(self, point: tuple[float, float], *, base_layers: Iterable[Any] = ()) -> list[dict[str, Any]]:
        """对全部可见可查询图层执行识别（QGIS Identify Results 语义）。

        编修图层经 ``FeatureSpatialIndex`` 命中（修订缓存）；基础工区快照
        图层（井位等只读要素）走几何粗命中。结果携带图层 / 要素 / 属性 /
        几何类型 / 来源 / 模板角色。
        """
        results: list[dict[str, Any]] = []
        tolerance = max(self._tolerance(), 1e-9)
        for layer in self._layers.values():
            visible, _opacity = self._display.get(layer.id, (True, 1.0))
            if not visible:
                continue
            feature_id = self._snapping.index_for(layer).identify(point, tolerance)
            if feature_id is None:
                continue
            session = layer.edit_session
            source = session.features() if session is not None else layer.features()
            feature = next((f for f in source if f.feature_id == feature_id), None)
            if feature is None:
                continue
            results.append(
                {
                    "layer_id": layer.id,
                    "layer_name": layer.name,
                    "feature_id": feature.feature_id,
                    "geometry_type": str(feature.geometry.get("type") or ""),
                    "attributes": dict(feature.attributes),
                    "source": "composite",
                    "template": self._templates.get(layer.id, ""),
                    "editable": True,
                    "record": feature.as_record(),
                }
            )
        for snapshot_layer in base_layers:
            if not getattr(snapshot_layer, "visible", True):
                continue
            layer_name = str(getattr(snapshot_layer, "name", ""))
            layer_id = str(getattr(snapshot_layer, "id", ""))
            for record in getattr(snapshot_layer, "features", ()) or ():
                geometry = record.get("geometry") if isinstance(record, Mapping) else None
                if not isinstance(geometry, Mapping):
                    continue
                if not _geometry_hit(point, geometry, tolerance):
                    continue
                properties = dict(record.get("properties") or {})
                results.append(
                    {
                        "layer_id": layer_id,
                        "layer_name": layer_name,
                        "feature_id": str(record.get("id") or ""),
                        "geometry_type": str(geometry.get("type") or ""),
                        "attributes": properties,
                        "source": str(getattr(snapshot_layer, "source_version_id", "") or "workarea"),
                        "template": "",
                        "editable": False,
                        "record": dict(record),
                    }
                )
        return results

    def locate_identify_result(self, result: Mapping[str, Any]) -> bool:
        """选中并定位一个识别结果（可编辑图层 → 选集 + 缩放到要素）。"""
        layer_id = str(result.get("layer_id") or "")
        feature_id = str(result.get("feature_id") or "")
        layer = self._layers.get(layer_id)
        if layer is None or not feature_id:
            return False
        self.set_active_layer(layer_id)
        layer.set_selection((feature_id,))
        self.state_changed.emit()
        return True

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
        编辑会话工作副本）重建。记录序列化按修订键控缓存——数字化
        点击只重编码变化图层（review #6）。
        """
        display = display or {}
        snapshots: list[MapLayerSnapshot] = []
        for layer_id, layer in self._layers.items():
            session = layer.edit_session
            revision = layer.data_revision if session is None else (layer.data_revision << 32) + session.revision
            cached = self._records_cache.get(layer_id)
            if cached is not None and cached[0] == revision:
                features, extent = cached[1], cached[2]
            else:
                source = session.features() if session is not None else layer.features()
                features = tuple(feature.as_record() for feature in source)
                extent = _feature_extent(features)
                self._records_cache[layer_id] = (revision, features, extent)
            previous = display.get(layer_id)
            if previous is not None:
                # 面板显示态回写为图层权威，供持久化还原。
                self._display[layer_id] = (bool(previous.visible), float(previous.opacity))
            visible, opacity = self._display.get(layer_id, (True, 1.0))
            snapshots.append(
                MapLayerSnapshot(
                    id=layer.id,
                    name=layer.name,
                    layer_type="vector",
                    extent=extent,
                    crs=layer.crs,
                    data_revision=revision,
                    style_revision=layer.style_revision,
                    features=features,
                    style=dict(layer.style),
                    visible=visible,
                    opacity=opacity,
                    metadata={
                        "editable": "true",
                        "geometry_kind": self._kinds.get(layer_id, ""),
                        "template": self._templates.get(layer_id, ""),
                        "editing": "true" if session is not None else "false",
                    },
                )
            )
        return tuple(snapshots)

    def apply_display_state(self, display_layers: Iterable[Any]) -> None:
        """把图层管理面板的显示态（顺序 / 可见性 / 不透明度）写回权威。

        面板是显示增量的唯一提交口；顺序变化重建内部图层序（dict 保持
        插入序），使 identify 可见性判定与工程持久化读到同一份状态。
        """
        order: list[str] = []
        seen: set[str] = set()
        for snapshot in display_layers:
            layer_id = str(getattr(snapshot, "id", ""))
            if layer_id in self._layers and layer_id not in seen:
                seen.add(layer_id)
                order.append(layer_id)
                self._display[layer_id] = (
                    bool(getattr(snapshot, "visible", True)),
                    min(1.0, max(0.05, float(getattr(snapshot, "opacity", 1.0)))),
                )
        if order:
            # 面板未覆盖的图层保守保持原序尾部（异常路径）。
            remaining = [lid for lid in self._layers if lid not in seen]
            self._layers = {lid: self._layers[lid] for lid in order + remaining}

    def action_state(self, *, can_previous_extent: bool = False, can_next_extent: bool = False) -> MapActionState:
        layer = self.active_layer
        session = layer.edit_session if layer is not None else None
        # selection ⊆ 会话可选要素（set_selection 过滤），计数无需遍历要素
        # （review #7：extent 变化高频触发本计算）。
        compatible_polygon_count = (
            len(layer.selection)
            if layer is not None and session is not None and self._kinds.get(layer.id) == "polygon"
            else 0
        )
        return MapActionState(
            has_active_vector_layer=layer is not None,
            vector_layer_writable=layer is not None,
            editing=session is not None,
            selected_count=len(layer.selection) if layer is not None else 0,
            compatible_polygon_count=compatible_polygon_count,
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
