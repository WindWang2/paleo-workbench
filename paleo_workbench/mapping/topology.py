"""Map-layer topology validation and opt-in shared-vertex propagation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import math
from typing import Iterable

from paleo_workbench.mapping.vector_layer import VectorLayer, VectorEditSession

__all__ = [
    "CompoundUndoGroup",
    "CompoundUndoResult",
    "SharedVertexEdit",
    "TopologyEditResult",
    "TopologyService",
    "repair_invalid_geometry",
]

_logger = logging.getLogger(__name__)

Point = tuple[float, float]


def _point(value: object) -> Point | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _vertices(value: object, path: tuple[int, ...] = ()):
    point = _point(value)
    if point is not None:
        yield point, path
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            yield from _vertices(child, path + (index,))


@dataclass(frozen=True, slots=True)
class TopologyEditResult:
    changed: tuple[tuple[str, str, tuple[int, ...]], ...] = ()
    issues: tuple[dict[str, object], ...] = ()
    # V8 M3：本次传播是否登记进了复合撤销组（origin 顶命令形状不符——
    # 例如宏打开——时 False，此时保持 V7 非原子行为并如实上报）。
    compound_registered: bool = False


@dataclass(frozen=True, slots=True)
class SharedVertexEdit:
    """复合组中的一个顶点编辑（origin 或传播副本），按命令对象身份追踪。"""

    layer_id: str
    feature_id: str
    path: tuple[int, ...]
    before: Point
    after: Point
    session: VectorEditSession
    command: object


@dataclass
class CompoundUndoGroup:
    """一次用户级地质动作 = origin 顶点编辑 + 其共享节点传播（M3 原子性）。

    组本身持历史（被弹出的命令不进任何单层 redo 栈），redo 以各涉及
    会话的 revision 快照守卫：组撤销后任一层又有新编辑 → 整组拒绝重做，
    绝不错位应用。
    """

    origin: SharedVertexEdit
    propagated: tuple[SharedVertexEdit, ...]
    undone: bool = False
    revision_guard: dict[str, int] = field(default_factory=dict)

    @property
    def involved_layer_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [self.origin.layer_id, *(edit.layer_id for edit in self.propagated)]
            )
        )


@dataclass(frozen=True, slots=True)
class CompoundUndoResult:
    ok: bool
    reason: str = ""
    undone_layer_ids: tuple[str, ...] = ()


class TopologyService:
    """Validate host geometry and update logically shared vertices only when enabled."""

    def __init__(self, *, enabled: bool = False, tolerance: float = 1e-9) -> None:
        self.enabled = bool(enabled)
        self.tolerance = max(0.0, float(tolerance))
        # V8 M3：复合撤销组登记簿 + 最近一次传播见过的图层（origin 层
        # 定位用——服务不持有图层注册表，宿主每次调用传入全集）。
        self._compounds: list[CompoundUndoGroup] = []
        self._last_layers: list[VectorLayer] = []

    # -- 校验引擎选择（V7：QGIS GEOS 优先，Shapely 显式回退） ------------------

    @staticmethod
    def _bridge_validate_fn():
        """桥 geometry.validate（逐错误详情）——不可用时返回 None（回退 Shapely）。

        与 split/merge/repair 的桥优先策略对齐（基线不一致项，V7 收敛）；
        运行失败按不可用处理（不静默吞异常，Shapely 路径会给出自己的报告）。
        """
        try:
            from paleo_workbench.mapping.qgis_style import qgis_bridge_available

            if not qgis_bridge_available():
                return None
            import qgis_render_bridge as native

            fn = getattr(native.geometry, "validate", None)
            return fn if callable(fn) else None
        except Exception:
            return None

    def validate(self, layers: Iterable[VectorLayer]) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        # 探测单次提升（review-2 P2-6）：逐要素重复 import 探测是 O(N) 开销。
        bridge_validate = self._bridge_validate_fn()
        shapely_ok = self._shapely_available()
        if bridge_validate is None and not shapely_ok:
            return [
                {
                    "severity": "error",
                    "layer_id": "",
                    "feature_id": "",
                    "code": "validator_unavailable",
                    "message": "拓扑检查需要 QGIS 桥或 Shapely/GEOS，当前均不可用",
                }
            ]
        bridge_failed = False
        for layer in layers:
            session = layer.edit_session
            features = session.features() if session is not None else layer.features()
            for feature in features:
                geometry = feature.as_record()["geometry"]
                if geometry["type"] in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
                    messages: list[str] | None
                    if bridge_validate is not None and not bridge_failed:
                        try:
                            errors = bridge_validate(geometry)
                            messages = [str(entry.get("message") or "invalid geometry") for entry in errors]
                        except Exception as exc:
                            # 桥路径失败必须可诊断（P2-2）且只报一次（P2-6）。
                            _logger.warning("QGIS 几何校验失败，后续回退 Shapely：%s", exc)
                            bridge_failed = True
                            messages = None
                    else:
                        messages = None
                    if messages is None:
                        messages = self._shapely_messages(geometry)
                    for message in messages:
                        issues.append(
                            {
                                "severity": "error",
                                "layer_id": layer.id,
                                "feature_id": feature.feature_id,
                                "message": message,
                            }
                        )
                if geometry["type"] == "Polygon":
                    for ring_index, ring in enumerate(geometry["coordinates"]):
                        points = [point for point, _path in _vertices(ring)]
                        if len(points) < 4 or points[0] != points[-1]:
                            issues.append(
                                {
                                    "severity": "error",
                                    "layer_id": layer.id,
                                    "feature_id": feature.feature_id,
                                    "message": f"polygon ring {ring_index} is not closed",
                                }
                            )
        return issues

    @staticmethod
    def _shapely_messages(geometry) -> list[str]:
        """Shapely 判词（空列表 = 有效）；不可用时报告单条不可用消息。"""
        try:
            from shapely.geometry import shape
            from shapely.validation import explain_validity
        except ImportError:
            return ["QGIS 校验失败且 Shapely/GEOS 不可用"]
        candidate = shape(geometry)
        if candidate.is_valid:
            return []
        return [explain_validity(candidate) if explain_validity else "invalid geometry"]

    @staticmethod
    def _shapely_available() -> bool:
        try:
            import shapely.geometry  # noqa: F401

            return True
        except ImportError:
            return False

    def propagate_shared_vertex(
        self,
        layers: Iterable[VectorLayer],
        *,
        origin: Point,
        replacement: Point,
        skip: tuple[str, str, tuple[int, ...]] | None = None,
    ) -> TopologyEditResult:
        """Update exact shared nodes in opted-in map layers, never raw sources.

        V8 M3：传播后把 origin 命令 + 传播命令登记为复合撤销组——一次
        用户级地质动作一次 undo/redo。登记条件（不满足则如实返回
        compound_registered=False，保持 V7 行为）：origin 会话此刻的栈顶
        命令恰好是 ``(skip 要素)`` 的 set_vertex 类编辑且宏未打开。
        """
        if not self.enabled:
            return TopologyEditResult()
        changed: list[tuple[str, str, tuple[int, ...]]] = []
        propagated: list[SharedVertexEdit] = []
        layer_list = list(layers)
        self._last_layers = layer_list
        # 宏打开时传播命令不落 undo 栈——无从按身份追踪，登记降级。
        macro_open = False
        for layer in layer_list:
            # Snapshot paths before mutation; it makes duplicate closing nodes and
            # adjacent polygons deterministic even as individual commands change data.
            session = layer.edit_session
            source = session.features() if session is not None else layer.features()
            candidates = [
                (feature.feature_id, path)
                for feature in source
                for point, path in _vertices(feature.geometry["coordinates"])
                if math.dist(point, origin) <= self.tolerance
            ]
            # Do not create dirty edit sessions for unrelated layers merely because
            # topological editing is enabled. A working buffer appears only for a
            # layer that actually owns a logically shared node.
            if not candidates:
                continue
            session = session or layer.start_editing()
            if session._open_command is not None:
                macro_open = True
            for feature_id, path in candidates:
                if skip == (layer.id, feature_id, path):
                    continue
                before_feature = session.feature(feature_id)
                before_point = next(
                    (
                        point
                        for point, vertex_path in _vertices(
                            before_feature.geometry["coordinates"]
                        )
                        if vertex_path == tuple(path)
                    ),
                    None,
                )
                session.set_vertex(feature_id, path, replacement)
                changed.append((layer.id, feature_id, path))
                if before_point is not None and session._open_command is None:
                    command = session.undo_stack[-1] if session.undo_stack else None
                    if command is not None and feature_id in command.feature_ids:
                        propagated.append(
                            SharedVertexEdit(
                                layer_id=layer.id,
                                feature_id=str(feature_id),
                                path=tuple(path),
                                before=before_point,
                                after=(float(replacement[0]), float(replacement[1])),
                                session=session,
                                command=command,
                            )
                        )
        compound_registered = False
        if self.enabled and propagated and not macro_open and skip is not None:
            skip_layer_id, skip_feature_id, _skip_path = skip
            compound_registered = self._register_compound(
                skip_layer_id, str(skip_feature_id), propagated
            )
        return TopologyEditResult(
            changed=tuple(changed), compound_registered=compound_registered
        )

    # -- V8 M3：跨图层复合撤销组 ------------------------------------------------

    def _register_compound(
        self,
        origin_layer_id: str,
        origin_feature_id: str,
        propagated: list[SharedVertexEdit],
    ) -> bool:
        """以 origin 会话栈顶命令为准登记复合组；形状不符 → False（不登记）。"""
        origin_layer = next(
            (layer for layer in self._compound_registry_layers() if layer.id == origin_layer_id),
            None,
        )
        if origin_layer is None:
            return False
        session = origin_layer.edit_session
        if session is None or session._open_command is not None or not session.undo_stack:
            return False
        command = session.undo_stack[-1]
        if origin_feature_id not in command.feature_ids:
            return False
        before_feature = command.before.get(origin_feature_id)
        after_feature = command.after.get(origin_feature_id)
        if before_feature is None or after_feature is None:
            return False
        before_points = {
            path: point
            for point, path in _vertices(before_feature.geometry["coordinates"])
        }
        after_points = {
            path: point
            for point, path in _vertices(after_feature.geometry["coordinates"])
        }
        # 栈顶必须是同一要素的顶点级编辑（set_vertex/insert/delete 皆可——
        # before/after 顶点集给出精确还原值）。
        shared_paths = [path for path in before_points if path in after_points]
        if not shared_paths:
            return False
        moved = [
            path
            for path in shared_paths
            if before_points[path] != after_points[path]
        ]
        if len(moved) != 1:
            return False
        path = moved[0]
        self._compounds.append(
            CompoundUndoGroup(
                origin=SharedVertexEdit(
                    layer_id=origin_layer_id,
                    feature_id=origin_feature_id,
                    path=path,
                    before=before_points[path],
                    after=after_points[path],
                    session=session,
                    command=command,
                ),
                propagated=tuple(propagated),
            )
        )
        if len(self._compounds) > self.COMPOUND_LIMIT:
            del self._compounds[: len(self._compounds) - self.COMPOUND_LIMIT]
        return True

    def _compound_registry_layers(self) -> list[VectorLayer]:
        """最近一次 propagate 调用见过的图层（origin 层必在其中）。"""
        return self._last_layers

    # 复合组保留上限：与 journal 同量级——过旧的组早被会话提交/回滚作废。
    COMPOUND_LIMIT = 256

    def pending_compound(self, session: VectorEditSession) -> CompoundUndoGroup | None:
        """该会话栈顶命令是否是一个未撤销复合组的 origin。

        宿主在单层 undo 前查询：命中则必须走 :meth:`undo_compound`（整组
        原子撤销），否则一次用户动作只回滚一半。
        """
        if session is None or session._open_command is not None or not session.undo_stack:
            return None
        top = session.undo_stack[-1]
        for group in reversed(self._compounds):
            if group.undone:
                continue
            if group.origin.session is session and group.origin.command is top:
                return group
        return None

    def pending_compound_redo(self, session: VectorEditSession) -> CompoundUndoGroup | None:
        """该会话最近一个处于已撤销态的复合组（redo 入口）。

        组命令寄存在组内而非 redo 栈，因此以"最近整组撤销"为准；
        :meth:`redo_compound` 的 revision 守卫会拒绝非线性重做。
        """
        for group in reversed(self._compounds):
            if group.undone and group.origin.session is session:
                return group
        return None

    def undo_compound(self, group: CompoundUndoGroup) -> CompoundUndoResult:
        """整组原子撤销；任何一部分不可安全撤销 → 整组拒绝并给原因。"""
        if group.undone:
            return CompoundUndoResult(False, "compound already undone")
        origin = group.origin
        if origin.session._open_command is not None:
            return CompoundUndoResult(False, "an edit command is still open")
        if not origin.session.undo_stack or origin.session.undo_stack[-1] is not origin.command:
            return CompoundUndoResult(
                False,
                "origin 顶点编辑已不是该图层最近一次编辑——请按编辑顺序逐层撤销",
            )
        # 先全量检查再执行（all-or-nothing）：传播命令必须仍在各自栈上，
        # 且其后同要素不得再有编辑（否则逐条回滚不等价于那一次地质动作；
        # 快照式命令按要素判定——同组其它命令不算冲突，它们一起弹）。
        group_command_ids = {
            id(edit.command) for edit in (*group.propagated, group.origin)
        }
        for edit in group.propagated:
            if edit.session._open_command is not None:
                return CompoundUndoResult(False, "an edit command is still open")
            stack = edit.session.undo_stack
            try:
                index = stack.index(edit.command)
            except ValueError:
                return CompoundUndoResult(
                    False, f"图层 {edit.layer_id} 的传播命令已不在撤销栈上"
                )
            for later in stack[index + 1:]:
                if (
                    edit.feature_id in later.feature_ids
                    and id(later) not in group_command_ids
                ):
                    return CompoundUndoResult(
                        False,
                        f"图层 {edit.layer_id} 要素 {edit.feature_id} 在拓扑传播后又有编辑"
                        "——整组拒绝撤销，请先处理该图层",
                    )
        for edit in reversed(group.propagated):
            if not edit.session.pop_command(edit.command):
                return CompoundUndoResult(False, f"图层 {edit.layer_id} 的传播命令已失效")
        if not origin.session.pop_command(origin.command):
            return CompoundUndoResult(False, "origin command is no longer on the stack")
        group.undone = True
        group.revision_guard = {
            layer_id: self._session_revision(layer_id)
            for layer_id in group.involved_layer_ids
        }
        return CompoundUndoResult(True, undone_layer_ids=group.involved_layer_ids)

    def redo_compound(self, group: CompoundUndoGroup) -> CompoundUndoResult:
        """整组原子重做；组撤销后任一涉及层又有编辑 → 拒绝（线性历史）。"""
        if not group.undone:
            return CompoundUndoResult(False, "compound is not undone")
        for layer_id, revision in group.revision_guard.items():
            if self._session_revision(layer_id) != revision:
                return CompoundUndoResult(
                    False,
                    f"图层 {layer_id} 在复合撤销后已有新的编辑——整组拒绝重做",
                )
        for edit in (group.origin, *group.propagated):
            if edit.session._open_command is not None:
                return CompoundUndoResult(False, "an edit command is still open")
        if not group.origin.session.push_command_back(group.origin.command):
            return CompoundUndoResult(False, "origin re-apply failed")
        for edit in group.propagated:
            if not edit.session.push_command_back(edit.command):
                return CompoundUndoResult(False, f"layer {edit.layer_id} re-apply failed")
        group.undone = False
        group.revision_guard = {}
        return CompoundUndoResult(True, undone_layer_ids=group.involved_layer_ids)

    def discard_compounds(self, layer_ids: Iterable[str]) -> None:
        """丢弃触及这些图层的复合组（会话提交/回滚/图层删除后调用）。"""
        stale = set(layer_ids)
        self._compounds = [
            group for group in self._compounds
            if not stale.intersection(group.involved_layer_ids)
        ]

    def _session_revision(self, layer_id: str) -> int:
        layer = next(
            (layer for layer in self._last_layers if layer.id == layer_id), None
        )
        if layer is None or layer.edit_session is None:
            # 会话已关（提交/回滚）：用哨兵值使 redo 守卫必然拒绝。
            return -1
        return layer.edit_session.revision


def repair_invalid_geometry(geometry: dict[str, object]) -> dict[str, object]:
    """Auto-heal invalid Polygon / MultiPolygon geometries (self-intersection, ring unclosed)."""
    if not isinstance(geometry, dict):
        return geometry
    geom_type = geometry.get("type")
    if geom_type not in {"Polygon", "MultiPolygon"}:
        return geometry

    # First ensure ring closure in coordinates
    coords = geometry.get("coordinates")
    if geom_type == "Polygon" and isinstance(coords, list):
        fixed_coords = []
        for ring in coords:
            if isinstance(ring, (list, tuple)) and len(ring) >= 3:
                r = [list(pt) for pt in ring]
                if r[0] != r[-1]:
                    r.append(list(r[0]))
                fixed_coords.append(r)
            else:
                fixed_coords.append(ring)
        geometry = {"type": "Polygon", "coordinates": fixed_coords}

    try:
        from shapely.geometry import MultiPolygon, Polygon, mapping, shape
        from shapely.geometry.polygon import orient
        from shapely.validation import make_valid

        cand = shape(geometry)
        if not cand.is_valid:
            repaired = make_valid(cand) if make_valid is not None else cand.buffer(0)
        else:
            repaired = cand

        if not repaired.is_empty:
            if repaired.geom_type == "Polygon":
                repaired = orient(repaired, sign=1.0)
            elif repaired.geom_type == "MultiPolygon":
                repaired = MultiPolygon([orient(p, sign=1.0) for p in repaired.geoms if p.geom_type == "Polygon"])
            elif repaired.geom_type == "GeometryCollection":
                polys = [orient(p, sign=1.0) for p in repaired.geoms if p.geom_type == "Polygon"]
                if len(polys) == 1:
                    repaired = polys[0]
                elif len(polys) > 1:
                    repaired = MultiPolygon(polys)
            res = mapping(repaired)
            return dict(res)
    except Exception:
        pass

    return geometry


