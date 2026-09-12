"""Map-layer topology validation (Python shared-vertex propagation retired in M5)."""

from __future__ import annotations

import logging
import math
from typing import Iterable

from paleo_workbench.mapping.vector_layer import VectorLayer, VectorEditSession

__all__ = [
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


class TopologyService:
    """Host geometry validation + M4 checker holder.

    Shared-vertex Python propagation retired in M5
    (native vertex topological editing + gesture manager).
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = bool(enabled)
        # M4 §5：analysis 检查器结果 + 双豁免。旧桥无 run_geometry_checks
        # 时 commit_all 仍走 validate_records。
        from paleo_workbench.mapping.topology_checker import TopologyChecker

        self.checker = TopologyChecker()
        # V9 W2：每图层最近一次校验的错误计数（运行时 topology_error_count
        # 生产者）。键 = layer id，值 = (data_revision, session_revision,
        # count, session)。只在有界刷新点写（保存/flush 校验、拓扑开关、
        # 几何命令、undo/redo、显式校验）；上下文采集只读缓存——帧级链
        # 不做 O(要素) 校验。会话对象身份入键值（review-2 P1-2）：回滚/
        # 提交后新建的会话即使 layer id 相同也不继承旧计数。
        self._error_counts: dict[str, tuple[int, int, int, VectorEditSession | None]] = {}

    # -- V9 W2：运行时拓扑错误计数（merge 门禁的事实生产者） -------------------

    def record_validation(self, layer: VectorLayer, error_count: int) -> None:
        """记录一次校验结论（缓存写；刷新点调用）。"""
        session = layer.edit_session
        self._error_counts[layer.id] = (
            int(getattr(layer, "data_revision", 0) or 0),
            int(session.revision if session is not None else -1),
            max(0, int(error_count)),
            session,
        )

    def refresh_error_count(self, layer: VectorLayer) -> int:
        """校验一层并记录（有界刷新点）；返回错误数。"""
        count = len(self.validate([layer]))
        self.record_validation(layer, count)
        return count

    def cached_error_count(self, layers: Iterable[VectorLayer]) -> int:
        """各**活跃编辑会话**最近一次校验的错误数之和（缓存读，O(层数)）。

        语义与 save 时校验门禁一致：从未校验过 = 0（门不因未知而拦）；
        同一会话内校验后又编辑 → 保持最近已知值直到下一刷新点；会话
        终结（提交/回滚）或**换新会话对象**后不计入（新会话内容未经
        校验，旧计数对它既不可信也不可用——按未知处理，门不拦）。
        """
        total = 0
        for layer in layers:
            session = layer.edit_session
            if session is None:
                continue
            entry = self._error_counts.get(layer.id)
            if entry is not None and entry[3] is session:
                total += entry[2]
        return total

    def forget_error_count(self, layer_ids: Iterable[str]) -> None:
        """丢弃这些图层的计数（图层删除时随生命周期清理）。"""
        stale = set(layer_ids)
        for key in stale.intersection(self._error_counts):
            del self._error_counts[key]

    def forget_all_error_counts(self) -> None:
        """清空全部计数（工程切换层集全替换时；宿主不触私有状态）。"""
        self._error_counts.clear()

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
        for layer in layers:
            session = layer.edit_session
            features = session.features() if session is not None else layer.features()
            issues.extend(self.validate_records(
                layer.id,
                [{"feature_id": feature.feature_id,
                  "geometry": feature.as_record()["geometry"]}
                 for feature in features]))
        return issues

    def validate_records(
        self, layer_id: str, records: Iterable[dict[str, object]],
    ) -> list[dict[str, object]]:
        """校验 (feature_id, geometry) 记录集（拓扑编辑迁移 M1：原生编辑
        会话的几何事实从镜像读回，无 Python 会话/图层对象可用）。"""
        issues: list[dict[str, object]] = []
        # 探测单次提升（review-2 P2-6）：逐要素重复 import 探测是 O(N) 开销。
        bridge_validate = self._bridge_validate_fn()
        shapely_ok = self._shapely_available()
        if bridge_validate is None and not shapely_ok:
            return [
                {
                    "severity": "error",
                    "layer_id": layer_id,
                    "feature_id": "",
                    "code": "validator_unavailable",
                    "message": "拓扑检查需要 QGIS 桥或 Shapely/GEOS，当前均不可用",
                }
            ]
        bridge_failed = False
        for record in records:
            feature_id = str(record.get("feature_id") or "")
            geometry = record.get("geometry") or {}
            if not isinstance(geometry, dict):
                continue
            if geometry.get("type") in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
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
                            "layer_id": layer_id,
                            "feature_id": feature_id,
                            "message": message,
                        }
                    )
            if geometry.get("type") == "Polygon":
                for ring_index, ring in enumerate(geometry.get("coordinates") or []):
                    points = [point for point, _path in _vertices(ring)]
                    if len(points) < 4 or points[0] != points[-1]:
                        issues.append(
                            {
                                "severity": "error",
                                "layer_id": layer_id,
                                "feature_id": feature_id,
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


