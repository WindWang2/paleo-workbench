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

import logging
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid as _cpp_alive

_logger = logging.getLogger(__name__)

from paleo_workbench.mapping.geometry_planar import (
    distance_to_segment,
    extent_of_geometries,
    point_in_ring_scalar,
)
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
    IdentifyTool,
    MapToolController,
    MeasureDistanceTool,
    MoveFeatureTool,
    PanTool,
    PartCaptureTool,
    RectangleSelectTool,
    ReshapeTool,
    RingCaptureTool,
    SelectTool,
    VertexTool,
    ZoomTool,
)
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.project.models import UserVectorFeature, UserVectorLayer

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

#: 快照 metadata["role"] 不落盘的角色：无成员资格的通用层（""）、旧工程
#: 未分类与用户通用层。这些角色没有字段 schema 语义（LEGACY 无 spec；
#: USER_GENERAL 为空字段表），写 role 会把它们从 legacy 无 schema 路径
#: （桥侧丢属性留几何）迁走——保持无 role 即保持既有行为（qgis_mirror
#: `_fields_json_for_metadata` 契约；test_legacy_untyped_mirror_stays_geometry_only）。
_SNAPSHOT_ROLELESS = frozenset({"", "legacy_unclassified", "user_general"})


def _normalize_layer_role(role: object) -> str:
    """LayerRole / 原始字符串 → 快照 metadata 用角色值（"" = 无角色）。"""
    value = getattr(role, "value", role)
    return str(value or "").strip()

_LAYER_BOUND_TOOLS = frozenset(
    {"identify", "select", "select_rectangle", "move_feature", "vertex"}
)
_KIND_BOUND_TOOLS = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}


def pick_topmost_visible_layer_id(layer_ids_bottom_up, visible_ids) -> str | None:
    """自上而下首个可见图层 id（纯函数）。

    输入顺序恒为组装顺序（自下而上：基础 → 引用 → 编修），故反向首个
    可见即最上。调用方负责把「从未显隐过的图层视为可见」的缺省解开成
    ``visible_ids``（此处不读任何权威，只做顺序选择）。
    """
    visible = set(visible_ids)
    for layer_id in reversed(tuple(layer_ids_bottom_up)):
        if layer_id in visible:
            return layer_id
    return None


def _plain_geometry(result):
    """facade GeometryResult/GeometryListResult → 纯 GeoJSON（engine 披露留给
    EditDelta 溯源；session 命令只消费纯几何）。"""
    return (
        getattr(result, "geometry", None)
        or getattr(result, "geometries", None)
        or result
    )


def _nearest_interior_ring(geometry: Mapping[str, Any], point) -> int | None:
    """内环定位（V10 delete_ring）：pick 点到各内环边段最近者。"""
    px, py = float(point[0]), float(point[1])
    coords = geometry.get("coordinates") or []
    best_index: int | None = None
    best = math.inf
    for index in range(1, len(coords)):
        ring = coords[index]
        for i in range(len(ring) - 1):
            d = distance_to_segment((px, py), ring[i], ring[i + 1])
            if d < best:
                best = d
                best_index = index
    return best_index


def _nearest_part(geometry: Mapping[str, Any], point) -> int | None:
    """部件定位（V10 delete/move_part）：Multi 几何中含 pick 点的部件，
    否则最近顶点距离的部件。非 Multi 几何返回 None。"""
    gtype = str(geometry.get("type") or "")
    if not gtype.startswith("Multi"):
        return None
    px, py = float(point[0]), float(point[1])
    parts = geometry.get("coordinates") or []
    best_index: int | None = None
    best = math.inf
    for index, part in enumerate(parts):
        ring = part[0] if gtype == "MultiPolygon" else part
        if gtype == "MultiPolygon" and point_in_ring_scalar(px, py, ring):
            return index
        for vertex in ring:
            d = math.hypot(px - float(vertex[0]), py - float(vertex[1]))
            if d < best:
                best = d
                best_index = index
    return best_index


def _crs_parseable(crs: str) -> bool:
    """ADV-6：CRS 有效性做真校验（pyproj 可解析），而非仅判非空。

    结果进程内缓存（帧级触发链上每次同步都问一次，pyproj 解析不便宜）。
    pyproj 缺失时回落为非空判断（不比原来更差）。
    """
    text = str(crs or "").split("/")[0].strip()
    if not text:
        return False
    cached = _crs_parseable._cache.get(text)  # type: ignore[attr-defined]
    if cached is not None:
        return cached
    try:
        from pyproj import CRS

        CRS(text)
        result = True
    except ImportError:
        result = True
    except Exception:
        result = False
    _crs_parseable._cache[text] = result  # type: ignore[attr-defined]
    return result


_crs_parseable._cache = {}  # type: ignore[attr-defined]


def _coords_to_lists(value: Any) -> Any:
    """GeoJSON 坐标归一化：shapely mapping() 返回 tuple，比较前统一为 list。"""
    if isinstance(value, (list, tuple)):
        return [_coords_to_lists(item) for item in value]
    return value


def _geometry_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return str(left.get("type")) == str(right.get("type")) and (
        _coords_to_lists(left.get("coordinates")) == _coords_to_lists(right.get("coordinates"))
    )


def _union_extent(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """两个范围的包围盒（会话内增量 extent 的单调并集）。"""
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _feature_extent(features: Iterable[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    """快照要素范围（V8 M4：走共享 extent 内核；空集保持占位语义）。"""
    geometries = [
        feature.get("geometry")
        for feature in features
        if isinstance(feature, Mapping) and isinstance(feature.get("geometry"), Mapping)
    ]
    try:
        return extent_of_geometries(geometries)
    except ValueError:
        return (0.0, 0.0, 1.0, 1.0)


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


def _geometry_hit(point: tuple[float, float], geometry: Mapping[str, Any], tolerance: float) -> bool:
    """快照记录的粗命中测试：点距 / 线距 / 多边形 even-odd。

    V8 M4：PIP 与线段距离均走共享内核（geometry_planar）——本函数只保留
    命中测试特有的容差语义（顶点邻近回退；内部的第 4 份射线复刻已删）。
    """
    import math as _math

    kind = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        try:
            return _math.dist(point, (float(coordinates[0]), float(coordinates[1]))) <= tolerance
        except (TypeError, ValueError, IndexError):
            return False
    if kind in {"LineString", "MultiLineString"}:
        return any(
            distance_to_segment(point, start, end) <= tolerance
            for start, end in _segments(coordinates)
        )
    if kind == "Polygon":
        # 迁移前精确语义（review-1 P2-6）：外环内 → 命中=不在任何洞（直接
        # 返回，洞内点不做顶点回退）；外环之外 → 顶点邻近回退（容差）。
        rings = list(coordinates or [])

        def _inside(ring: Any) -> bool:
            vertices = [
                (float(node[0]), float(node[1]))
                for node in ring or ()
                if isinstance(node, (list, tuple))
                and len(node) >= 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
            ]
            if len(vertices) < 3:
                return False
            return point_in_ring_scalar(
                float(point[0]), float(point[1]), vertices)

        if rings and _inside(rings[0]):
            return not any(_inside(hole) for hole in rings[1:])
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
    # V8 M3：跨图层复合撤销被拒绝的用户可读原因（不静默——原子性受损时
    # 用户必须知道为什么这次 undo 没有发生）。
    topology_conflict = Signal(str)

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
        # 图层科学角色（LayerRole 值）：阶段动作经 set_layer_role 登记，
        # 快照时写入 metadata["role"] 供桥侧取字段 schema；权威仍是阶段
        # 工作区的成员资格表，此处只是编辑侧的快照携带副本（重开工程时
        # 由 load_from_project 从 mapping_workspace memberships 恢复）。
        self._layer_roles: dict[str, str] = {}
        # 图层管理面板的显示态（可见性 / 不透明度），供持久化还原。
        self._display: dict[str, tuple[bool, float]] = {}
        self._active_layer_id: str | None = None
        self._active_tool_action = "pan"
        self._canvas = None
        # 宿主注入的多图层识别回调（Identify Results 面板）；缺省单图层命中。
        self.identify_delegate: Any = None
        # 修订键控的序列化缓存：数字化点击只重组变化图层，不整层重编码
        # （review #6：100k 要素时每次点击的全量 as_record 是 GUI 线程热点）。
        # (composite revision, session 对象, features 元组, extent, 有序
        # records dict)。session 身份入键：同一 data_revision 下的新会话 /
        # 回滚不会误用旧会话的增量基线。
        self._records_cache: dict[str, tuple[int, Any, tuple, tuple, dict]] = {}
        self._persist_cache: dict[str, tuple[int, list]] = {}
        # RAW/锁定门禁（宿主注入；单点 = CompositeDocument._role_allows_editing）。
        # 所有会话起点（start_editing / ensure_layer_session / 修复）与
        # flush 提交都必须经过它——历史旁路：属性表直接 layer.start_editing()、
        # flush 无角色复查（V6 baseline B-P0-1）。
        self._edit_gate: Any = None
        # V9 W6/W9：角色查询单点注入（宿主 = stage membership 权威）。
        # 快照 metadata.role（镜像 fields_json 的来源）与捕获 spec 的默认
        # 属性/捕捉推荐都从这里读——控制器不持有第二份角色表。
        self._role_lookup: Any = None

    # -- RAW/锁定门禁（V6 单点） -------------------------------------------------

    def set_edit_gate(self, gate) -> None:
        """注入编辑门禁 ``layer_id -> (allowed, reason)``（无注入 = 全放行）。"""
        self._edit_gate = gate

    def can_edit_layer(self, layer_id: str) -> tuple[bool, str]:
        """角色门禁判定；被拒时返回用户可读原因（无门禁 = 允许，测试/独立用）。"""
        if self._edit_gate is None:
            return True, ""
        return self._edit_gate(str(layer_id))

    def set_role_lookup(self, lookup) -> None:
        """注入角色查询 ``layer_id -> LayerRole|value|None``（stage membership 权威）。

        无注入（独立用/测试）= 无角色语义：快照 metadata 不带 role、
        捕获回落模板默认——与 V8 行为一致，不猜。
        """
        self._role_lookup = lookup

    def role_of_layer(self, layer_id: str) -> str:
        """图层角色值（LayerRole.value；未知/无注入 = ""）。"""
        if self._role_lookup is None:
            return ""
        try:
            role = self._role_lookup(str(layer_id))
        except Exception:
            return ""
        if role is None:
            return ""
        return str(getattr(role, "value", role) or "")

    def _capture_defaults_for_role(self, layer_id: str) -> dict[str, object]:
        """角色捕获语义的默认属性（spec.template_key → 模板 field_defaults）。

        与显式 ``create_layer(template=)`` 的区别只在派生方向：这里从角色
        反推模板；两者的字段值同源（同一注册表），不会漂移出第二套默认。
        """
        from paleo_workbench.mapping_workspace.capture_spec import (
            capture_spec_for_role,
        )

        spec = capture_spec_for_role(self.role_of_layer(layer_id))
        if spec is None or not spec.template_key:
            return {}
        template = _TEMPLATE_BY_KEY.get(spec.template_key)
        return template.field_defaults() if template is not None else {}

    def apply_capture_spec(self, layer_id: str) -> str | None:
        """按图层角色应用捕获语义（V9 W9：捕捉推荐 + 拓扑建议）。

        在角色图层创建/角色生效时由宿主调用；返回用户可读的推荐解释
        （状态条呈现），无角色语义时返回 None 且不改动任何配置。
        默认属性与模板不在此处应用——它们经 ``create_layer(template=)``
          /``_capture_defaults`` 在会话捕获时派生。
        """
        from paleo_workbench.mapping_workspace.capture_spec import (
            capture_spec_for_role,
        )

        spec = capture_spec_for_role(self.role_of_layer(layer_id))
        if spec is None:
            return None
        summary = self._snapping.apply_role_profile(layer_id, spec.role)
        self._push_snapping_config()
        hint = "" if summary is None else summary
        if spec.recommend_topological_editing and not self._topology.enabled:
            hint += "；建议开启拓扑编辑（相带拼接共享节点）" if hint else "建议开启拓扑编辑"
        return hint or None

    # -- 画布绑定 -------------------------------------------------------------

    def attach_canvas(self, canvas) -> None:
        """绑定鸭子类型画布（UnifiedMapCanvas / QgisCanvasShim）：工具控制器与 overlay 提供者。"""
        self._canvas = canvas
        canvas.set_map_tool_controller(self.tools)
        canvas.set_overlay_provider(self.overlay_state)
        # V9 W7：digitize commit 的 CRS 守卫钩子（原生画布才有该面）。
        set_crs_provider = getattr(canvas, "set_capture_layer_crs_provider", None)
        if callable(set_crs_provider):
            set_crs_provider(self._capture_layer_crs)
        self._push_snapping_config()

    def _capture_layer_crs(self, tool) -> str:
        """采点工具会话所属图层的存储 CRS（找不到层 = ""，不比对）。"""
        session = getattr(tool, "session", None)
        if session is None:
            return ""
        for layer in self._layers.values():
            if layer.edit_session is session:
                return str(layer.crs or "")
        return ""

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

    def create_layer(self, name: str, kind: str, template: str = "", *, role: object = "") -> VectorLayer:
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
        role_value = _normalize_layer_role(role)
        if role_value:
            self._layer_roles[layer_id] = role_value
        self._active_layer_id = layer_id
        self._push_snapping_config()
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

    def set_layer_role(self, layer_id: str, role: object) -> None:
        """登记图层的科学角色（阶段动作建层后调用；"" 清除）。"""
        layer_id = str(layer_id)
        if layer_id not in self._layers:
            return
        role_value = _normalize_layer_role(role)
        if role_value:
            self._layer_roles[layer_id] = role_value
        else:
            self._layer_roles.pop(layer_id, None)

    def layer_role(self, layer_id: str) -> str:
        """图层的科学角色值（"" = 无角色，走 legacy 无 schema 路径）。"""
        return self._layer_roles.get(str(layer_id), "")

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
        # 副本继承科学角色：内容同源，快照携带同一 schema 语义（桥侧不断链）；
        # 阶段成员资格仍由宿主按需登记，此处不动。
        source_role = self._layer_roles.get(str(layer_id))
        if source_role:
            self._layer_roles[layer_id_new] = source_role
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
        # V8 M3：触及该图层的复合撤销组随层作废（命令身份已无处解析）。
        self._topology.discard_compounds([layer_id])
        # V9 W2：错误计数缓存随层清理（防跨工程泄漏）。
        self._topology.forget_error_count([layer_id])
        self._kinds.pop(layer_id, None)
        self._templates.pop(layer_id, None)
        self._schemas.pop(layer_id, None)
        self._layer_roles.pop(layer_id, None)
        self._display.pop(layer_id, None)
        self._snapping.layer_enabled.pop(layer_id, None)
        self._snapping.layer_modes.pop(layer_id, None)
        self._snapping.layer_tolerance.pop(layer_id, None)
        self._snapping.layer_priority.pop(layer_id, None)
        self._push_snapping_config()
        self._records_cache.pop(layer_id, None)
        self._persist_cache.pop(layer_id, None)
        if self._active_layer_id == layer_id:
            self._active_layer_id = next(iter(self._layers), None)
            self._rebind_active_tool()
        self.layers_changed.emit()
        self.state_changed.emit()

    # -- 工程持久化（人工建数据纳入数据管理） --------------------------------------

    def load_from_project(self, project) -> None:
        """从工程文档恢复人工矢量图层（替换当前全部图层）。

        Review-3 P1-4：切换前先 flush（提交进行中会话；门禁/拓扑阻断的
        会话保持打开并上报，不静默 rollback 丢数据）。flush 后仍有未
        提交会话（被阻断）时拒绝切换并返回 False，调用方必须处理。
        """
        committed, blocked = self.flush_edit_sessions()
        remaining = [layer for layer in self._layers.values() if layer.edit_session is not None]
        if remaining:
            return False
        for layer in self._layers.values():
            if layer.edit_session is not None:
                layer.edit_session.rollback_changes()
        self._layers.clear()
        self._kinds.clear()
        self._templates.clear()
        self._schemas.clear()
        self._layer_roles.clear()
        self._display.clear()
        self._records_cache.clear()
        self._persist_cache.clear()
        # V9（lifecycle 压测发现）：层集全替换时 per-layer 捕捉覆盖与拓扑
        # 计数缓存必须随之清空——旧层 id 的条目跨工程存活会在同名 id 复用
        # 时复活过期配置（remove_layer 单层路径已清，整组替换路径漏清）。
        self._snapping.layer_enabled.clear()
        self._snapping.layer_modes.clear()
        self._snapping.layer_tolerance.clear()
        self._snapping.layer_priority.clear()
        self._topology.forget_all_error_counts()
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
        # 科学角色随层恢复：权威是 mapping_workspace 的成员资格表（阶段控制
        # 器稍后才 load_state，此处直接读工程上的原始 dict，不经过它）。
        workspace = getattr(project, "mapping_workspace", None) or {}
        memberships = (
            workspace.get("memberships") if isinstance(workspace, Mapping) else None
        ) or {}
        for layer_id in self._layers:
            entry = memberships.get(layer_id)
            role_value = _normalize_layer_role(
                entry.get("role") if isinstance(entry, Mapping) else "")
            if role_value:
                self._layer_roles[layer_id] = role_value
        if self._layers:
            self._active_layer_id = next(iter(self._layers))
        self._rebind_active_tool()
        self._push_snapping_config()
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

    def topmost_visible_layer_id(self) -> str | None:
        """最上可见编修图层（无活动层时 identify 的绑定/置 current 目标）。

        顺序权威是组装顺序（自下而上）；``_display`` 缺键的图层视为可见
        （从未被面板改过显隐，与 identify_all 的缺省一致）。
        """
        visible = {
            layer_id
            for layer_id in self._layers
            if self._display.get(layer_id, (True, 1.0))[0]
        }
        return pick_topmost_visible_layer_id(tuple(self._layers), visible)

    @property
    def topology(self):
        """拓扑校验服务（只读公共访问；stage_actions QA 等宿主消费）。"""
        return self._topology

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
        # M3：原生选择/identify 工具的目标图层 = 活动图层（QGIS currentLayer 语义）
        canvas = self._canvas
        if canvas is not None and hasattr(canvas, "set_current_layer"):
            try:
                canvas.set_current_layer(layer_id or "")
            except Exception:
                pass
        self.state_changed.emit()

    def start_editing(self) -> None:
        layer = self.active_layer
        if layer is None or layer.edit_session is not None:
            return
        allowed, _reason = self.can_edit_layer(layer.id)
        if not allowed:
            return  # 原因由调用方（门禁入口）负责呈现
        self._open_session(layer)
        self.state_changed.emit()

    def ensure_layer_session(self, layer_id: str):
        """门禁下的会话获取：返回 ``(session, reason)``。

        允许 → (该图层的会话——无则开启, "")；拒绝 → (None, 原因)。
        属性表 / 阶段动作等一切「拿会话写数据」的路径统一走这里，
        不再各自 ``layer.start_editing()``。
        """
        layer = self._layers.get(str(layer_id))
        if layer is None:
            return None, "图层不存在"
        allowed, reason = self.can_edit_layer(layer.id)
        if not allowed:
            return None, reason
        if layer.edit_session is None:
            self._open_session(layer)
            self.state_changed.emit()
        return layer.edit_session, ""

    def import_layer_features(self, layer_id: str, features: list) -> None:
        """可信导入通道：向（通常是 RAW 角色的）图层写入初始要素。

        语义对齐 DataCatalogService.import_raw——RAW 不可变保护约束的是
        **用户编辑**，不约束数据的初始落盘。只有领域建稿动作
        （stage_actions 的加载/建稿）允许走这条路径；绝不能用于
        用户编辑入口。会话即刻提交，不留打开的编辑会话。
        """
        layer = self._layers.get(str(layer_id))
        if layer is None or not features:
            return
        session = self._open_session(layer)
        # ADV-4：批量导入中途失败（重复 id 等）必须回滚，不得留半脏会话。
        try:
            with session.edit_source("domain_import"):
                for feature in features:
                    session.add_feature(feature)
        except Exception:
            session.rollback_changes()
            self.state_changed.emit()
            raise
        session.commit_changes()
        self.content_changed.emit(str(layer_id))

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
            # V9 W2：保存校验结论进运行时计数缓存（merge 门禁事实源）。
            self._topology.record_validation(layer, len(issues))
            if issues:
                # UX-4：列出前 3 个 offender（图层名/要素 id/判词），用户可
                # 定位修复；不再只报首条 transient 消息。
                shown = issues[:3]
                details = "；".join(
                    f"{issue.get('feature_id', '')}：{issue.get('message', '')}"
                    for issue in shown
                )
                more = f"（另有 {len(issues) - 3} 个问题）" if len(issues) > 3 else ""
                return (
                    f"图层「{layer.name}」{len(issues)} 个要素未通过拓扑检查："
                    f"{details}{more}"
                )
        layer.edit_session.commit_changes()
        # V8 M3：会话终结（提交）——涉及本层的复合撤销组作废（撤销历史
        # 随会话关闭消失，与单层 undo 语义一致）。
        self._topology.discard_compounds([layer.id])
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
        self._topology.discard_compounds([layer.id])
        # 会话终结：计数缓存随会话作废（cached 读以会话身份判定，这里
        # 显式清理防同 id 复用误读）。
        self._topology.forget_error_count([layer.id])
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
            # 角色门禁复查（V6 B-P0-1）：历史旁路开启的 RAW 会话绝不提交；
            # 会话保持打开（可回滚），原因进 blocked。
            allowed, gate_reason = self.can_edit_layer(layer.id)
            if not allowed:
                blocked.append(f"图层「{layer.name}」{gate_reason}（该图层编辑未提交）")
                continue
            if self._topology.enabled:
                issues = self._topology.validate([layer])
                self._topology.record_validation(layer, len(issues))
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
            # V8 M3：被提交会话的复合组作废（撤销历史随会话终结消失）。
            self._topology.discard_compounds(
                [layer.id for layer in self._layers.values() if layer.edit_session is None]
            )
            self._rebind_active_tool()
            self.sessions_committed.emit()
            self.state_changed.emit()
        return committed, blocked

    # -- 会话开启 / 能力溯源 -----------------------------------------------------

    # EditDelta 的引擎溯源 token（capability snapshot 稳定摘要）；宿主在
    # 桥探测后注入，未注入时保持诚实的 "unavailable"。
    qgis_capability_token: str = "unavailable"

    def set_qgis_capability_token(self, token: str) -> None:
        self.qgis_capability_token = str(token or "unavailable")

    def _open_session(self, layer: VectorLayer) -> object:
        """开启（或取既有）会话并注入引擎溯源 token（单点）。"""
        session = layer.edit_session or layer.start_editing()
        session.qgis_capability_token = self.qgis_capability_token
        return session

    def _make_reshape_applier(self, session, feature_id: str):
        """构建 reshape 应用器（桥 geometry.reshape → SetGeometryCommand）。

        桥不可用/无 reshape 算子时返回 None（工具不激活——native-only）。
        """
        if not feature_id:
            return None
        try:
            import qgis_render_bridge as native

            reshape_fn = getattr(native.geometry, "reshape", None)
            if not callable(reshape_fn):
                return None
        except Exception:
            return None
        import json

        def _apply(line_geometry) -> bool:
            try:
                feature = session.feature(feature_id)
                target = json.dumps(feature.as_record()["geometry"], ensure_ascii=False)
                line = json.dumps(dict(line_geometry), ensure_ascii=False)
                reshaped = json.loads(reshape_fn(target, line))
                session.set_geometry(feature_id, reshaped)
                self.content_changed.emit(session.layer.id)
                return True
            except Exception:
                return False

        return _apply

    def _apply_captured_ring(self, session, feature_id: str, ring_geometry) -> bool:
        """V10 捕获环 → session.add_ring（外环坐标，自动闭合守卫在 session）。"""
        try:
            ring: list = []
            gtype = str(ring_geometry.get("type") or "")
            coords = ring_geometry.get("coordinates")
            if gtype == "Polygon" and coords:
                ring = [list(p) for p in coords[0]]
            elif gtype == "MultiPolygon" and coords and coords[0]:
                ring = [list(p) for p in coords[0][0]]
            session.add_ring(feature_id, ring)
            self.content_changed.emit(session.layer.id)
            return True
        except Exception:
            return False

    def _make_part_applier(self, session, feature_id: str):
        """构建部件应用器（桥 geometry.add_part → session.add_part）。"""
        try:
            import qgis_render_bridge as native

            add_part_fn = getattr(native.geometry, "add_part", None)
            if not callable(add_part_fn):
                return None
        except Exception:
            return None
        import json

        def _apply(part_geometry) -> bool:
            try:
                feature = session.feature(feature_id)
                target = json.dumps(feature.as_record()["geometry"], ensure_ascii=False)
                part = json.dumps(dict(part_geometry), ensure_ascii=False)
                merged = json.loads(add_part_fn(target, part))
                session.add_part(feature_id, merged)
                self.content_changed.emit(session.layer.id)
                return True
            except Exception:
                return False

        return _apply

    def _apply_captured_part(self, session, feature_id: str, part_geometry) -> bool:
        applier = self._make_part_applier(session, feature_id)
        return bool(applier and applier(part_geometry))

    def _propagate_shared_vertex(
        self,
        feature_id: str,
        path: tuple[int, ...],
        origin: tuple[float, float],
        replacement: tuple[float, float],
    ) -> None:
        """顶点提交后的 opt-in 拓扑传播（与编图页同语义，V7 工作站接线）。

        只向门禁放行的图层传播：传播会在共享节点图层上开启编辑会话，
        RAW/锁定图层绝不能因此获得脏会话。
        """
        layer = self.active_layer
        if layer is None:
            return
        allowed_layers = [
            candidate
            for candidate in self._layers.values()
            if self.can_edit_layer(candidate.id)[0]
        ]
        self._topology.propagate_shared_vertex(
            allowed_layers,
            origin=origin,
            replacement=replacement,
            skip=(layer.id, str(feature_id), tuple(path)),
        )
        # 传播可能为其它图层新开编辑会话——统一注入引擎溯源 token（P2-6）。
        for candidate in allowed_layers:
            opened = candidate.edit_session
            if opened is not None and (
                not opened.qgis_capability_token
                or opened.qgis_capability_token == "unavailable"
            ):
                opened.qgis_capability_token = self.qgis_capability_token
        if len(allowed_layers) > 1:
            self.content_changed.emit(layer.id)

    def _pending_compound_redo(self, session) -> object | None:
        """该会话最近一个处于已撤销态的复合组（redo 入口，委托拓扑服务）。"""
        return self._topology.pending_compound_redo(session)

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
            tool = MeasureDistanceTool(crs=self.project_crs)
        else:
            layer = self.active_layer
            if layer is None and action_id == "identify":
                # 无活动层时 identify 仍可激活：优先绑最上可见编修层
                # （多图层回调经 identify_delegate 进面板）；连编修层都
                # 没有（仅基础/引用可查询）时走无层 IdentifyTool。
                fallback_id = self.topmost_visible_layer_id()
                if fallback_id is not None:
                    layer = self._layers[fallback_id]
                elif callable(self.identify_delegate):
                    tool = IdentifyTool(identify=self.identify_delegate)
                    self._active_tool_action = action_id
                    self.tools.set_active_tool(tool)
                    if canvas is not None and _cpp_alive(canvas):
                        canvas.setFocus()
                    self.state_changed.emit()
                    return
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
                if not defaults:
                    # V9 W9：模板未指定时按角色捕获语义取默认（角色 → spec →
                    # template_key → field_defaults；无 spec 保持空——不猜）。
                    defaults = self._capture_defaults_for_role(layer.id)
                if action_id == "add_point":
                    tool = AddPointTool(session, snap=self._snap, attributes=defaults)
                elif action_id == "add_line":
                    tool = AddLineTool(session, snap=self._snap, attributes=defaults)
                elif action_id == "add_polygon":
                    tool = AddPolygonTool(session, snap=self._snap, attributes=defaults)
                elif action_id == "move_feature":
                    tool = MoveFeatureTool(session, identify=lambda point: index.identify(point, self._tolerance()))
                elif action_id == "vertex":
                    tool = VertexTool(
                        session,
                        identify_vertex=lambda point: index.identify_vertex(point, self._tolerance()),
                        # 拓扑传播与编图页（mapping_page._on_unified_vertex_committed）
                        # 同语义：顶点提交后按 opt-in 传播共享节点（V7 修复
                        # 工作站断线——两条路径行为不得漂移）。
                        on_vertex_committed=self._propagate_shared_vertex,
                    )
                elif action_id == "reshape":
                    # V7：native-only 工具——非原生画布（ReshapeTool 无鼠标
                    # 输入路径）、无 reshape 算子（旧桥/无桥）或选集非恰一个
                    # 时拒激活并保持当前工具（与 evaluator 禁用语义一致，
                    # P1-3/P2-5 双重防御）。
                    if not hasattr(self._canvas, "canvas_address"):
                        return
                    if len(layer.selection) != 1:
                        return
                    feature_id = next(iter(sorted(layer.selection)), "")
                    applier = self._make_reshape_applier(session, feature_id) if feature_id else None
                    if applier is None:
                        return
                    tool = ReshapeTool(
                        session,
                        feature_id=feature_id,
                        apply_reshape=applier,
                    )
                elif action_id == "add_ring":
                    # V10：native-only 捕获环——addPolygon 数字化器采环，
                    # session.add_ring 落命令（与 reshape 同款双重防御）。
                    if not hasattr(self._canvas, "canvas_address"):
                        return
                    if self._kinds.get(layer.id) != "polygon" or len(layer.selection) != 1:
                        return
                    feature_id = next(iter(sorted(layer.selection)), "")
                    if not feature_id:
                        return
                    tool = RingCaptureTool(
                        session,
                        feature_id=feature_id,
                        apply_ring=lambda ring_geometry, _s=session, _f=feature_id:
                            self._apply_captured_ring(_s, _f, ring_geometry),
                    )
                elif action_id == "add_part":
                    # V10：native-only 捕获部件——digitizer 随图层 kind，
                    # 桥 geometry.add_part 执行，session.add_part 落命令。
                    if not hasattr(self._canvas, "canvas_address"):
                        return
                    if len(layer.selection) != 1:
                        return
                    feature_id = next(iter(sorted(layer.selection)), "")
                    if not feature_id or self._make_part_applier(session, feature_id) is None:
                        return
                    tool = PartCaptureTool(
                        session,
                        feature_id=feature_id,
                        apply_part=lambda part_geometry, _s=session, _f=feature_id:
                            self._apply_captured_part(_s, _f, part_geometry),
                    )
                    tool.native_digitize_kind = {
                        "point": "addPoint", "line": "addLine", "polygon": "addPolygon",
                    }.get(self._kinds.get(layer.id, ""), "pan")
                else:
                    return
        self._active_tool_action = action_id
        self.tools.set_active_tool(tool)
        # teardown 竞态：Qt 子对象析构序可能先删画布，树/面板的队列回调随后
        # 才触发 activate_tool——画布 C++ 体已亡时跳过 setFocus。
        if canvas is not None and _cpp_alive(canvas):
            canvas.setFocus()
        self.state_changed.emit()

    def _rebind_active_tool(self) -> None:
        action = self._active_tool_action
        session_actions = {"add_point", "add_line", "add_polygon", "move_feature",
                           "vertex", "reshape", "add_ring", "add_part"}
        if action in session_actions:
            layer = self.active_layer
            # 会话级工具在会话消失（保存/回滚/flush 提交）后必须回落 pan：
            # 旧工具持有的 session 缓冲已与图层脱钩，继续数字化会静默丢失。
            if layer is None or layer.edit_session is None:
                # 但同步链上选择会瞬时扫过无会话图层（bind/_publish 逐层
                # set_active_layer）：只要工具持有的会话仍属于某个活图层
                # （没被提交/回滚收回），就保留工具不打断数字化；会话真被
                # 收回才回落 pan（review #1 语义不变）。
                session = getattr(self.tools.active_tool, "session", None)
                if session is not None and any(
                    l.edit_session is session for l in self._layers.values()
                ):
                    return
                self.activate_tool("pan")
                return
            if (
                action in _KIND_BOUND_TOOLS
                and _KIND_BOUND_TOOLS[action] != self._kinds.get(layer.id)
            ):
                self.activate_tool("pan")
                return
            # ADV-3：reshape 目标是单选集要素——选集变化（删除/清空）导致
            # 失配时回落 pan 并提示，不得把用户卡在无目标的重塑工具里。
            if action == "reshape" and len(layer.selection) != 1:
                self.activate_tool("pan")
                self.state_changed.emit()
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
        self._push_snapping_config()

    def _push_snapping_config(self) -> None:
        """把 SnappingService 状态投影到 QGIS canvas snappingUtils（M3）。

        QGIS 端 AdvancedConfiguration 只认显式列出的图层，因此为每个图层
        都发条目（未覆盖者落全局值），语义与 SnappingService.snap 对齐；
        layer_priority（等距裁决）与 grid 模式无 QGIS 对应物，不下推。

        V7：endpoint → QGIS LineEndpoint、intersection → 交点捕捉 flag——
        两者都在桥 capability manifest 声明后才下推（旧桥静默丢弃未知
        types 会造成语义漂移；未声明时保持 Python 执行体路径并如实不推）。
        """
        canvas = self._canvas
        if canvas is None or not hasattr(canvas, "set_snapping_config"):
            return
        snapping = self._snapping
        features = self._bridge_snapping_features()
        endpoint_pushable = "snapping_endpoint" in features
        intersection_pushable = "snapping_intersection" in features
        # P2-8：旧桥不识别 endpoint/intersection 时如实告警一次——原生采点
        # 走 QGIS 捕捉引擎（不经 Python snap），用户必须知道这两个模式在
        # 原生路径未生效，而不是静默失效。
        native_canvas = hasattr(canvas, "canvas_address")
        if snapping.enabled and native_canvas:
            degraded_modes = [
                mode
                for mode, pushable in (
                    ("endpoint", endpoint_pushable),
                    ("intersection", intersection_pushable),
                )
                if mode in snapping.modes and not pushable
            ]
            # review-2 P2-3：per-layer 推荐含 intersection 而全局未开时，
            # 原生路径同样不生效（intersection 是整配置 flag）——一并告警。
            per_layer_intersection = any(
                "intersection" in (self._snapping.layer_modes.get(layer_id) or ())
                for layer_id in self._layers
            ) and "intersection" not in snapping.modes
            if per_layer_intersection:
                degraded_modes.append("intersection(per-layer)")
            if degraded_modes:
                _logger.warning(
                    "捕捉模式 %s 在当前 qgis_render_bridge 版本的 QGIS 捕捉引擎"
                    "上不可用（仅 fallback 采点轨生效）；重建桥扩展可恢复",
                    "、".join(degraded_modes),
                )
        types = [
            m
            for m in ("vertex", "segment", "midpoint", "endpoint")
            if m in snapping.modes and (m != "endpoint" or endpoint_pushable)
        ]
        config: dict[str, object] = {
            "enabled": bool(snapping.enabled),
            "mode": "active_layer" if snapping.current_layer_only else "all_layers",
            "tolerance_px": float(snapping.pixel_tolerance),
            "types": types,
            "reference_enabled": "reference" in snapping.modes,
            "intersection_enabled": "intersection" in snapping.modes and intersection_pushable,
        }
        # V9 W2：拓扑编辑状态下推（桥 manifest 声明后才发——旧桥静默忽略
        # 未知键，会让原生数字化器与宿主 TopologyService 语义漂移）。
        # 下推后 QGIS 数字化器在捕获时保持共享边界；宿主侧传播/保存校验
        # 仍是权威（两层同向，无双真源）。
        if "snapping_topological_editing" in features:
            config["topological_editing"] = bool(self._topology.enabled)
        if not snapping.current_layer_only:
            layers: dict[str, dict[str, object]] = {}
            for layer_id in self._layers:
                modes = snapping.layer_modes.get(layer_id)
                layers[layer_id] = {
                    "enabled": bool(snapping.layer_enabled.get(layer_id, True)),
                    "types": (
                        [
                            m
                            for m in ("vertex", "segment", "midpoint", "endpoint")
                            if m in modes and (m != "endpoint" or endpoint_pushable)
                        ]
                        if modes is not None
                        else types
                    ),
                    "tolerance_px": float(
                        snapping.layer_tolerance.get(layer_id, snapping.pixel_tolerance)
                    ),
                }
            config["layers"] = layers
        canvas.set_snapping_config(config)

    @staticmethod
    def _bridge_snapping_features() -> frozenset[str]:
        """桥 capability manifest 声明的 snapping 特性（V7）。

        vertex/segment/midpoint 自 M3 起所有桥版本支持；endpoint 与
        intersection 为 V7 新增——manifest 未声明时不下推（旧桥会静默丢弃
        未知条目，绝不允许静默语义漂移）。无桥时本方法结果不影响 fallback
        执行体（下推路径本身不存在）。
        """
        try:
            from paleo_workbench.mapping.qgis_style import ensure_qgis_bridge_dll_dirs

            ensure_qgis_bridge_dll_dirs()  # Windows V7: vendor DLL path
            import qgis_render_bridge as bridge

            manifest = bridge.capability_manifest()
            return frozenset(str(f) for f in (manifest.get("features") or ()))
        except Exception:
            return frozenset()

    @property
    def snapping(self) -> SnappingService:
        """捕捉配置面（per-layer enable/modes/tolerance/priority，#Phase9）。"""
        return self._snapping

    def set_topology(self, enabled: bool) -> None:
        """拓扑编辑开关：开启后保存编辑执行拓扑校验门禁。

        V9 W2：开启即对全部活跃会话刷新一次错误计数——merge 门禁的
        ``topology_error_count`` 从此有真实生产者（不再是仅测试写入的死事实）。
        """
        self._topology.enabled = bool(enabled)
        if enabled:
            for layer in self._layers.values():
                if layer.edit_session is not None:
                    self._topology.refresh_error_count(layer)
        # V9 W2：拓扑开关随捕捉配置下推（QgsProject topologicalEditing 与
        # 宿主 TopologyService 同向）。
        self._push_snapping_config()
        self.state_changed.emit()

    @property
    def topology_enabled(self) -> bool:
        return self._topology.enabled

    def validate_active_layer_topology(self) -> list[dict[str, object]]:
        """对活动图层（或其编辑工作副本）执行拓扑检查，返回问题清单。

        V9 W2：显式校验结论同步进运行时计数缓存（inspector/修复入口）。"""
        layer = self.active_layer
        if layer is None:
            return []
        issues = self._topology.validate([layer])
        self._topology.record_validation(layer, len(issues))
        return issues

    def repair_layer_geometries(self, layer_id: str) -> int:
        """修复图层无效几何（QGIS make-valid 优先，shapely 兜底）。

        修复结果经 ``SetGeometryCommand`` 写入编辑会话：可撤销、可回滚、
        可审计，与直接改数据无缘。
        """
        from paleo_workbench.mapping.geometry_service import make_geometry_valid

        layer = self._layers.get(str(layer_id))
        if layer is None:
            return 0
        allowed, _reason = self.can_edit_layer(layer.id)
        if not allowed:
            return 0
        opened_session = layer.edit_session is None
        session = self._open_session(layer)
        repaired = 0
        with session.edit_source("repair_geometry"):
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
        mutated_layers: list = [layer]
        try:
            if command_id == "merge":
                if not layer.selection:
                    return False, "请先选择要合并的要素"
                with session.edit_source("merge(command)"):
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
                if polygon_layer is not layer:
                    mutated_layers.append(polygon_layer)
                with polygon_layer.edit_session.edit_source("split(command)"):
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
            if command_id == "explode_multipart":
                return self._explode_selected_multipart(layer, session)
            if command_id == "collect_multipart":
                return self._collect_selected_multipart(layer, session)
        except (KeyError, RuntimeError, ValueError) as exc:
            return False, str(exc)
        finally:
            # V9 W2：几何命令改写会话后刷新涉及层错误计数（merge/split 后
            # 的 merge 门禁立即可见真实拓扑状态）。split 可能改写非活动
            # polygon 层（review-2 P1-3）——按实际触及集合刷新。
            for mutated in mutated_layers:
                if mutated.edit_session is not None:
                    try:
                        self._topology.refresh_error_count(mutated)
                    except Exception:  # noqa: BLE001 — 刷新绝不吞命令结果
                        pass
        return False, f"未知几何命令 {command_id}"

    def _explode_selected_multipart(self, layer, session) -> tuple[bool, str]:
        """V10 拆分多部件：每个选中的 multipart 要素按部件拆为 N 个要素。

        几何走桥 multipart_to_singlepart（shapely 回退 facade）；属性全继承
        （一个地质体被细分）；命令复用 split_feature（delta=split_feature，
        replacements=related ids）。返回 (ok, 消息)。
        """
        from paleo_workbench.mapping.geometry_operations import multipart_to_singlepart

        try:
            exploded_any = False
            new_selection: list[str] = []
            for feature_id in sorted(layer.selection):
                feature = session.feature(feature_id)
                gtype = str(feature.geometry.get("type") or "")
                if not gtype.startswith("Multi"):
                    new_selection.append(feature_id)
                    continue
                parts = _plain_geometry(multipart_to_singlepart(feature.as_record()["geometry"]))
                if len(parts) < 2:
                    new_selection.append(feature_id)
                    continue
                replacements = [
                    VectorFeature(
                        new_feature_id("explode"),
                        part,
                        feature.attributes,
                    )
                    for part in parts
                ]
                with session.edit_source("explode_multipart(command)"):
                    session.split_feature(feature_id, replacements)
                new_selection.extend(r.feature_id for r in replacements)
                exploded_any = True
            if not exploded_any:
                return False, "选中的要素都不是多部件几何"
            layer.set_selection(new_selection)
            self._topology.refresh_error_count(layer)
            self.content_changed.emit(layer.id)
            self.state_changed.emit()
            return True, "已拆分为单部件要素"
        except (KeyError, RuntimeError, ValueError) as exc:
            return False, str(exc)

    def _collect_selected_multipart(self, layer, session) -> tuple[bool, str]:
        """V10 组合多部件：>=2 个同类型单部件选中要素 → 一个多部件要素。

        几何走桥 singlepart_to_multipart（collect 不 dissolve——与 merge 的
        union 语义区分）；属性 = 首个选中要素（选择序，D2 策略）；命令复用
        merge_features。
        """
        from paleo_workbench.mapping.geometry_operations import singlepart_to_multipart

        try:
            selected = sorted(layer.selection)
            if len(selected) < 2:
                return False, "组合多部件需要至少两个要素"
            features = [session.feature(feature_id) for feature_id in selected]
            kinds = {str(f.geometry.get("type") or "") for f in features}
            if len(kinds) != 1 or any(k.startswith("Multi") for k in kinds):
                return False, "组合多部件需要同类型的单部件要素"
            collected = _plain_geometry(singlepart_to_multipart(
                [f.as_record()["geometry"] for f in features]))
            merged = VectorFeature(
                new_feature_id("collect"), collected, features[0].attributes)
            with session.edit_source("collect_multipart(command)"):
                session.merge_features(selected, merged)
            layer.set_selection((merged.feature_id,))
            self._topology.refresh_error_count(layer)
            self.content_changed.emit(layer.id)
            self.state_changed.emit()
            return True, "已组合为多部件要素"
        except (KeyError, RuntimeError, ValueError) as exc:
            return False, str(exc)

    def _ring_and_part_commands(self, command_id: str, pick_point=None) -> tuple[bool, str]:
        """V10 环/部件编辑命令（显式 pick_point 定位目标环/部件）。

        delete_ring：单选面要素，pick 点落在（或最近于）某个内环的边界 →
        删除该内环。delete_part：单选多部件要素，pick 点命中/最近于某部件
        → 桥 delete_part。move_part：同 delete_part 定位 + dx/dy 平移。
        pick_point=None 时返回提示（工具面交互模式后续轮次接线，见
        known-limitations）。
        """
        layer = self.active_layer
        if layer is None:
            return False, "没有活动的矢量图层"
        session = layer.edit_session
        if session is None:
            return False, "请先开始编辑"
        if len(layer.selection) != 1:
            return False, "该操作需要恰好选中一个要素"
        if pick_point is None:
            return False, "需要提供定位点（pick_point）"
        feature_id = next(iter(layer.selection))
        try:
            feature = session.feature(feature_id)
            geometry = feature.as_record()["geometry"]
            if command_id == "delete_ring":
                ring_index = _nearest_interior_ring(geometry, pick_point)
                if ring_index is None:
                    return False, "定位点附近没有内环"
                with session.edit_source("delete_ring(command)"):
                    session.delete_ring(feature_id, ring_index)
                self._topology.refresh_error_count(layer)
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True, "已删除内环"
            if command_id == "delete_part":
                part_index = _nearest_part(geometry, pick_point)
                if part_index is None:
                    return False, "定位点附近没有部件"
                import json as _json

                try:
                    import qgis_render_bridge as native

                    new_geometry = _json.loads(
                        native.geometry.delete_part(_json.dumps(geometry), part_index))
                except Exception as exc:
                    return False, f"删除部件失败：{exc}"
                with session.edit_source("delete_part(command)"):
                    session.delete_part(feature_id, new_geometry)
                self._topology.refresh_error_count(layer)
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True, "已删除部件"
            if command_id == "move_part":
                if "delta" not in (pick_point if isinstance(pick_point, dict) else {}):
                    return False, "move_part 需要 pick_point={'point':(x,y),'delta':(dx,dy)}"
                spec = pick_point
                part_index = _nearest_part(geometry, spec.get("point"))
                if part_index is None:
                    return False, "定位点附近没有部件"
                dx, dy = spec.get("delta", (0.0, 0.0))
                with session.edit_source("move_part(command)"):
                    session.move_part(feature_id, part_index, float(dx), float(dy))
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True, "已平移部件"
        except (KeyError, RuntimeError, ValueError) as exc:
            return False, str(exc)
        return False, f"未知命令 {command_id}"

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
        # M3 Task 5：原生工具占有 Esc（采点中/拖动中）时直接派发画布——
        # 只取消本次捕捉/拖动，工具保持激活；否则走 Python 工具栈取消。
        canvas = self._canvas
        if canvas is not None and hasattr(canvas, "native_tool_busy") and canvas.native_tool_busy():
            canvas.cancel_native_tool()
            self.state_changed.emit()
            return
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
        # 选集变化可能使 reshape 等单选集工具失配（ADV-3）：重绑检查。
        self._rebind_active_tool()
        self.state_changed.emit()

    def _refresh_topology_counts(self, layer_ids: Iterable[str]) -> None:
        """复合撤销/重做触及的层刷新错误计数（V9 W2 刷新点）。"""
        for layer_id in layer_ids:
            layer = self._layers.get(str(layer_id))
            if layer is not None and layer.edit_session is not None:
                self._topology.refresh_error_count(layer)

    def edit_command(self, command_id: str) -> bool:
        """执行编辑命令；返回 True 表示图层内容已变（宿主需重组快照）。"""
        layer = self.active_layer
        session = layer.edit_session if layer is not None else None
        if command_id == "undo" and session is not None:
            # V8 M3：栈顶是复合组 origin（顶点编辑 + 共享节点传播）时，
            # undo 必须整组原子撤销；不可安全撤销则拒绝并给出原因（信号
            # 上报，不静默半组回滚）。
            group = self._topology.pending_compound(session)
            if group is not None:
                result = self._topology.undo_compound(group)
                if result.ok:
                    self._refresh_topology_counts(result.undone_layer_ids)
                    for changed_layer_id in result.undone_layer_ids:
                        self.content_changed.emit(changed_layer_id)
                    self.state_changed.emit()
                    return True
                self.topology_conflict.emit(result.reason)
                return False
            if session.undo():
                self._topology.refresh_error_count(layer)
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True
            return False
        if command_id == "redo" and session is not None:
            # 复合组的重做同样整组：栈顶 redo 不是入口（组命令寄存在组里），
            # 以"最近被整组撤销且无后续编辑"的组为准。
            group = self._pending_compound_redo(session)
            if group is not None:
                result = self._topology.redo_compound(group)
                if result.ok:
                    self._refresh_topology_counts(result.undone_layer_ids)
                    for changed_layer_id in result.undone_layer_ids:
                        self.content_changed.emit(changed_layer_id)
                    self.state_changed.emit()
                    return True
                # 组拒绝（撤销后有新编辑）：线性历史上更晚被单层撤销的
                # 命令仍可 redo——回退单层路径，不吞掉入口（review-1 P1-3）。
                self.topology_conflict.emit(result.reason)
                if session.redo():
                    self._topology.refresh_error_count(layer)
                    self.content_changed.emit(layer.id)
                    self.state_changed.emit()
                    return True
                return False
            if session.redo():
                self._topology.refresh_error_count(layer)
                self.content_changed.emit(layer.id)
                self.state_changed.emit()
                return True
            return False
        if command_id == "delete_selected" and session is not None and layer.selection:
            for feature_id in sorted(layer.selection):
                session.delete_feature(feature_id)
            layer.set_selection(())
            self._topology.refresh_error_count(layer)
            self.content_changed.emit(layer.id)
            self.state_changed.emit()
            return True
        if command_id == "duplicate_selected" and session is not None and layer.selection:
            # V10：全属性 + 几何复制，新 id；一个动作 = 一个 undo 单元/要素。
            duplicates: list[str] = []
            for feature_id in sorted(layer.selection):
                with session.edit_source("duplicate_selected(command)"):
                    duplicate = session.duplicate_feature(feature_id)
                duplicates.append(duplicate.feature_id)
            layer.set_selection(duplicates)
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

        会话内增量快照：settle 只重编码会话日志覆盖到的要素（#932 的
        宿主侧对应物），未触及要素的 record 对象跨快照复用——后端
        feature-entry 复用与 delta 发送因此保持 O(changed)。范围在会话
        内单调并集（缩放语义宁大勿缺）；会话结束（提交 / 回滚）后修订
        键变化，下一次重建回到全量精确路径。
        """
        display = display or {}
        snapshots: list[MapLayerSnapshot] = []
        for layer_id, layer in self._layers.items():
            session = layer.edit_session
            revision = layer.data_revision if session is None else (layer.data_revision << 32) + session.revision
            cached = self._records_cache.get(layer_id)
            if cached is not None and cached[0] == revision and cached[1] is session:
                features, extent = cached[2], cached[3]
            else:
                records: dict[str, dict[str, object]] | None = None
                base_revision: int | None = None
                if session is not None and cached is not None:
                    if cached[1] is session and (cached[0] & ~0xFFFFFFFF) == (
                        layer.data_revision << 32
                    ):
                        base_revision = cached[0] & 0xFFFFFFFF
                    elif cached[1] is None and cached[0] == layer.data_revision:
                        # 会话开始前的无会话缓存：同一 data_revision 下内容
                        # 与会话工作副本初值一致，可作修订 0 的增量基线
                        # （会话首个 settle 也不必全量重建）。
                        base_revision = 0
                if base_revision is not None:
                    entries = session.changes_since(base_revision)
                    if entries is not None:
                        records = cached[4]
                        changed: list[dict[str, object]] = []
                        for ids in entries:
                            for feature_id in ids:
                                try:
                                    record = session.feature(feature_id).as_record()
                                except KeyError:
                                    records.pop(feature_id, None)
                                else:
                                    records[feature_id] = record
                                    changed.append(record)
                        extent = cached[3]
                        if changed:
                            # 会话内范围单调并集：缩放/命中宁大勿缺，精确
                            # 范围由会话结束后的全量重建恢复。
                            extent = _union_extent(extent, _feature_extent(changed))
                if records is None:
                    source = session.features() if session is not None else layer.features()
                    records = {feature.feature_id: feature.as_record() for feature in source}
                    extent = _feature_extent(records.values())
                features = tuple(records.values())
                self._records_cache[layer_id] = (revision, session, features, extent, records)
            previous = display.get(layer_id)
            if previous is not None:
                # 面板显示态回写为图层权威，供持久化还原。
                self._display[layer_id] = (bool(previous.visible), float(previous.opacity))
            visible, opacity = self._display.get(layer_id, (True, 1.0))
            # V9 W6：快照携带 role。图层自带 metadata role 优先（不覆盖既有
            # 工程），否则 stage membership（role_of_layer），再回落本控制器
            # 登记的科学角色。无角色 = 不带键，走 legacy 属性路径。
            pre_metadata = getattr(layer, "metadata", None)
            pre_role = (
                str(pre_metadata.get("role") or "").strip()
                if isinstance(pre_metadata, Mapping) else ""
            )
            role_value = (
                pre_role
                or self.role_of_layer(layer_id)
                or self._layer_roles.get(layer_id, "")
            )
            metadata = {
                "editable": "true",
                "geometry_kind": self._kinds.get(layer_id, ""),
                "template": self._templates.get(layer_id, ""),
                "editing": "true" if session is not None else "false",
            }
            if role_value and role_value not in _SNAPSHOT_ROLELESS:
                metadata["role"] = role_value
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
                    metadata=metadata,
                )
            )
        return tuple(snapshots)

    def apply_display_state(self, display_layers: Iterable[Any], *, include_names: bool = False) -> None:
        """把图层管理面板的显示态（顺序 / 可见性 / 不透明度 / 名称）写回权威。

        面板是显示增量的唯一提交口；顺序变化重建内部图层序（dict 保持
        插入序），使 identify 可见性判定与工程持久化读到同一份状态。

        include_names 只在面板发起的回写（notify_display_changed）为 True：
        重组快照路径（_sync_composition_now 经 layers_changed 同步触发）上
        面板副本可能滞后于控制器权威，此时消费 name 会把刚改的名立即回滚
        （C1 修复的配套约束）。name 经 rename_layer 写回（空名/同名幂等）。
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
                if include_names:
                    name = str(getattr(snapshot, "name", "") or "").strip()
                    if name:
                        self.rename_layer(layer_id, name)
        if order:
            # 面板未覆盖的图层保守保持原序尾部（异常路径）。
            remaining = [lid for lid in self._layers if lid not in seen]
            self._layers = {lid: self._layers[lid] for lid in order + remaining}

    def action_state(self, *, can_previous_extent: bool = False, can_next_extent: bool = False) -> dict:
        """兼容别名（V8 M1 删除 MapActionState）：等价 ``tool_context_inputs``
        的精简字典。生产路径已全部走 ``tool_context_inputs``。"""
        inputs = self.tool_context_inputs()
        inputs["can_previous_extent"] = can_previous_extent
        inputs["can_next_extent"] = can_next_extent
        return inputs

    @staticmethod
    def _selection_multipart_count(layer, session) -> int:
        """选集中多部件几何数（explode 门禁事实，O(selection)）。"""
        if layer is None or session is None or not layer.selection:
            return 0
        count = 0
        for feature_id in layer.selection:
            try:
                if str(session.feature(feature_id).geometry.get("type") or "").startswith("Multi"):
                    count += 1
            except KeyError:
                continue
        return count

    @staticmethod
    def _selection_collect_ready(layer, session) -> bool:
        """collect 门禁：>=2 个同几何类型的单部件选中要素（O(selection)）。"""
        if layer is None or session is None or len(layer.selection) < 2:
            return False
        kinds: set[str] = set()
        for feature_id in layer.selection:
            try:
                kind = str(session.feature(feature_id).geometry.get("type") or "")
            except KeyError:
                return False
            if kind.startswith("Multi") or kind not in {"Point", "LineString", "Polygon"}:
                return False
            kinds.add(kind)
            if len(kinds) > 1:
                return False
        return len(kinds) == 1

    def tool_context_inputs(self) -> dict[str, Any]:
        """ToolContext 的宿主侧采集器（Goal V7 §3）。

        只做派生（不建第二状态源）：图层/会话/选集/捕捉拓扑开关全部读
        既有权威；角色/阶段锁由 CompositeDocument 注入（它拥有
        ``_role_allows_editing`` 的语义细分）。
        """
        layer = self.active_layer
        session = layer.edit_session if layer is not None else None
        # 选集几何类型 O(1) 推导（P1-5）：图层 kind 是权威（一个图层一种
        # 几何），无需遍历要素——本方法挂在帧级触发链（extent_changed）上。
        layer_kind = self._kinds.get(layer.id, "") if layer is not None else ""
        kinds_among_selection: tuple[str, ...] = (
            (layer_kind,) if layer is not None and layer.selection and layer_kind else ()
        )
        # wkb_type O(1)（review-3 P1-1）：图层 kind 的 GeoJSON 名；
        # evaluator 不用它做门禁（下游消费字段），绝不为它全量拷贝
        # features()（next 再短路也已付 O(N) tuple 拷贝，帧级链上不可接受）。
        wkb_type = {"point": "Point", "line": "LineString", "polygon": "Polygon"}.get(layer_kind, "")
        gate_allowed, gate_reason = (
            self.can_edit_layer(layer.id) if layer is not None else (False, "没有活动图层")
        )
        return {
            "project_open": True,
            "active_layer_id": layer.id if layer is not None else "",
            "active_layer_kind": layer_kind,
            "wkb_type": wkb_type,
            "vector_writable": layer is not None,
            "editing": session is not None,
            "dirty": bool(session is not None and session.is_dirty),
            "edit_gate_open": bool(gate_allowed),
            "edit_gate_reason": str(gate_reason or ""),
            "can_undo": bool(
                session and (session.undo_stack or self._topology.pending_compound(session))
            ),
            "can_redo": bool(
                session and (session.redo_stack or self._topology.pending_compound_redo(session))
            ),
            "selection_count": len(layer.selection) if layer is not None else 0,
            "selection_geometry_types": tuple(kinds_among_selection),
            "compatible_polygon_count": (
                len(layer.selection)
                if layer is not None and session is not None and self._kinds.get(layer.id) == "polygon"
                else 0
            ),
            "split_ready": self._split_inputs() is not None,
            "merge_ready": (
                layer is not None
                and session is not None
                and self._kinds.get(layer.id) == "polygon"
                and len(layer.selection) >= 2
            ),
            "reshape_ready": (
                layer is not None
                and session is not None
                and self._kinds.get(layer.id) in {"line", "polygon"}
                and len(layer.selection) == 1
            ),
            # V10 复杂几何事实（contract v4）：O(selection) 的选集形状扫描，
            # 仅选集变化时重算成本，帧级链上无 O(features) 热点。
            "selection_multipart_count": (
                self._selection_multipart_count(layer, session)
            ),
            "collect_ready": self._selection_collect_ready(layer, session),
            "snapping_enabled": self._snapping.enabled,
            "topology_enabled": self._topology.enabled,
            # snapping/topology *可用性*不在此采集（V9 W1）——由
            # build_tool_context 从桥 manifest/引擎探测派生；此前硬编码
            # True 是无权威来源的猜测。
            "crs_valid": _crs_parseable(self.project_crs),
            "project_crs": str(self.project_crs or ""),
            "layer_crs": str(getattr(layer, "crs", "") or "") if layer is not None else "",
            "topology_error_count": self._topology.cached_error_count(
                self._layers.values()),
            "current_tool": getattr(self.tools.active_tool, "tool_id", "") or "pan",
            "blocking_task": str(getattr(self, "blocking_task_label", "") or ""),
        }

    def overlay_state(self) -> dict[str, Any]:
        """画布 overlay：选中要素高亮 / 采点预览 / 捕捉标记。

        PERF-1：只点查选集 id 对应的要素（O(选集)），不全量拷贝
        features()（O(全量)）——fallback 画布每帧 overlay 回调即触发。
        """
        selected = []
        for layer in self._layers.values():
            if not layer.selection:
                continue
            session = layer.edit_session
            for feature_id in layer.selection:
                try:
                    feature = (
                        session.feature(feature_id)
                        if session is not None
                        else layer.feature(feature_id)
                    )
                except KeyError:
                    continue
                selected.append(feature)
        tool = self.tools.active_tool
        capture = list(getattr(tool, "points", ()) or ())
        snap = self._snapping.last_match.point if self._snapping.last_match is not None else None
        from paleo_workbench.mapping.workarea_map_snapshot import WORKAREA_LEGEND_ITEMS

        return {
            "selected_features": selected,
            "capture_points": capture,
            "snap_point": snap,
            "decorations": {
                "elements": ["比例尺", "指北针", "图例"],
                "legend_items": [
                    {"label": label, "color": color}
                    for label, color in WORKAREA_LEGEND_ITEMS
                ],
            },
        }
