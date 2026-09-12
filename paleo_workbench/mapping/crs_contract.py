"""Unified CRS contract — the single CRS predicate/resolution authority (V9 W3).

Before this module the workbench carried four coexisting CRS predicates /
normalizers (``workflow.crs_policy``, ``map_render_backend._normalize_crs_name``,
``reference_layers._normalize_crs_input``, ``qgis_mirror._geographic_auth``)
plus a handful of "quietly EPSG:4326" defaults. This module does NOT
re-implement any axis math — it is the one place that answers:

* **declared?** — ``normalize_crs`` delegates to the render backend's single
  normalizer (auth-id canonicalization);
* **geographic?** — ``crs_is_geographic`` delegates to
  :func:`paleo_workbench.workflow.crs_policy.crs_is_geographic`, the single
  axis-units truth (known-set + pyproj; ``None`` = unverifiable);
* **what happens when a CRS is missing** — :func:`resolve_crs` returns a
  :class:`CRSResolution` that either carries the declared CRS or an explicit
  degraded reason. A silent ``EPSG:4326`` assumption is a contract violation:
  undeclared stays undeclared (``crs=""``) and the degraded state is recorded
  by the caller (mirror diagnostics, tool-context facts, measurement labels).

Leaf module: standard library + optional pyproj only.
"""
from __future__ import annotations

from functools import lru_cache

import logging
from dataclasses import dataclass

__all__ = [
    "CRSInference",
    "CRSResolution",
    "DomainMismatch",
    "coordinate_domain_mismatch",
    "crs_axis_unit_metres",
    "crs_coordinate_domain",
    "crs_is_geographic",
    "geod_for_crs",
    "infer_crs_from_extent",
    "normalize_crs",
    "panel_publish_crs",
    "resolve_crs",
    "scale_denominator_from_pixels",
]

logger = logging.getLogger(__name__)


def normalize_crs(crs: object) -> str:
    """Canonical CRS auth id (``""`` when absent/unparseable).

    Single normalization implementation: delegates to the render backend's
    ``_normalize_crs_name`` (pyproj-backed, historically the most complete
    normalizer in the tree). Every CRS comparison in the mapping stack goes
    through this — raw string compare against "EPSG:4326" style literals is
    the bug class this contract exists to remove.
    """
    text = str(crs or "").strip()
    if not text:
        return ""
    from paleo_workbench.mapping.map_render_backend import _normalize_crs_name

    return _normalize_crs_name(text)


def crs_is_geographic(crs: object) -> bool | None:
    """Axis-units truth (delegate): ``None`` = unverifiable, never a guess."""
    from paleo_workbench.workflow.crs_policy import crs_is_geographic as _axis_truth

    return _axis_truth(str(crs or "").strip() or None)


@dataclass(frozen=True, slots=True)
class CRSResolution:
    """The outcome of resolving a CRS requirement at one consumption site.

    ``crs`` is the resolved auth id (``""`` = none resolved). ``declared``
    is False exactly when the source carried no usable CRS; the
    ``degraded_reason`` then states *what was done instead* — the caller is
    expected to surface it (diagnostics entry, status label, QA annotation),
    never to swallow it.
    """

    crs: str
    declared: bool
    degraded_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.declared and bool(self.crs)


def resolve_crs(
    value: object,
    *,
    purpose: str,
    fallback: object = "",
) -> CRSResolution:
    """Resolve a CRS requirement without silent defaults (V9 contract).

    ``value`` non-empty → declared resolution (normalized). Empty → the
    ``fallback`` **only when it is a real, recorded legacy default** and the
    result is marked degraded with the purpose named in the reason; no
    fallback → undeclared resolution (``crs=""``). Either way the caller can
    explain what happened — the forbidden pattern is
    ``project_crs or "EPSG:4326"`` with no trace.
    """
    normalized = normalize_crs(value)
    if normalized:
        return CRSResolution(crs=normalized, declared=True)
    fallback_text = normalize_crs(fallback)
    if fallback_text:
        return CRSResolution(
            crs=fallback_text,
            declared=False,
            degraded_reason=(
                f"{purpose}: CRS 未声明，按记录在案的默认 {fallback_text} 处理（降级）"
            ),
        )
    return CRSResolution(
        crs="",
        declared=False,
        degraded_reason=f"{purpose}: CRS 未声明且无默认——按未知坐标处理（降级）",
    )


def _axis_unit_metres_uncached(text: str) -> bool | None:
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(text)
        axis = parsed.axis_info[0] if parsed.axis_info else None
        if axis is None:
            return None
        return str(axis.unit_name or "").strip().lower() in {
            "metre", "meter", "m",
        }
    except Exception:
        return None


@lru_cache(maxsize=64)
def _axis_unit_metres_cached(text: str) -> bool | None:
    return _axis_unit_metres_uncached(text)


def crs_axis_unit_metres(crs: object) -> bool | None:
    """True when the CRS horizontal axis unit is exactly metres.

    ``None`` = unverifiable (unknown id / no pyproj). Used by the honest
    scale-denominator derivation: a denominator computed from pixel metrics
    is only meaningful for metre axes, everything else reports unknown
    rather than a plausible-looking wrong number.

    V10 R5：按归一化字符串 lru_cache（pyproj 解析在 extent 高频链上，
    同一 CRS 反复解析是纯浪费；未知串也缓存——失败路径同样昂贵）。
    """
    text = str(crs or "").strip()
    if not text:
        return None
    return _axis_unit_metres_cached(text)


def panel_publish_crs(value: object, *, purpose: str = "图层面板发布") -> str:
    """面板/发布路径的 CRS：未声明返回 ""（按原坐标呈现）。

    V9 W3（review-1 P1-1 存量清理）：面板发布快照的 ``or "EPSG:4326"``
    在未声明时伪造坐标系。诚实语义 = 未声明就不设 CRS（渲染按原坐标、
    降级可查），工程模型的默认值照常声明 4326——本函数只消灭伪造路径。
    """
    resolution = resolve_crs(value, purpose=purpose)
    if not resolution.declared:
        logger.warning("%s（按原坐标呈现）", resolution.degraded_reason)
        return ""
    return resolution.crs


def scale_denominator_from_pixels(
    map_units_per_pixel: float,
    pixels_per_inch: float,
    crs: object,
) -> float:
    """Honest scale denominator from pixel geometry (metre axes only).

    Same formula QGIS uses for pixel canvases (``mupp × inches-per-metre ×
    dpi``). Returns ``0.0`` — unknown — whenever the CRS axis unit is not
    *verifiably* metres (degrees, US survey feet, unverifiable ids): a
    denominator derived under any other unit silently misstates the scale,
    which is exactly the failure mode this contract exists to prevent. The
    native path never uses this helper (``QgsMapCanvas::scale()`` is the
    authority there); it serves the fallback canvas only.
    """
    if crs_axis_unit_metres(crs) is not True:
        return 0.0
    if map_units_per_pixel <= 0.0 or pixels_per_inch <= 0.0:
        return 0.0
    return map_units_per_pixel * 39.370078740157481 * pixels_per_inch


def geod_for_crs(crs: object):
    """``pyproj.Geod`` for a geographic CRS, else ``None``.

    Consumers (measurement fallback, W8) use this to replace planar
    raw-map-unit distances with geodesic ones when — and only when — the
    axis truth says geographic. A ``None`` return keeps the honest planar
    label instead of guessing an ellipsoid.
    """
    if crs_is_geographic(crs) is not True:
        return None
    try:
        from pyproj import CRS, Geod

        ellipsoid = CRS.from_user_input(str(crs)).ellipsoid
        return Geod(
            a=ellipsoid.semi_major_metre, b=ellipsoid.semi_minor_metre)
    except Exception as exc:
        try:
            # WGS84 remains the geodesic default for unknown ellipsoids —
            # an explicit, reviewed fallback (V9 W8, review-1 P2-2)：降级
            # 记入日志而非静默替换。
            from pyproj import Geod

            logger.warning(
                "geod_for_crs: %r 椭球不可解析（%s）——测地计算回退 WGS84",
                crs, exc)
            return Geod("WGS84")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 坐标域契约（拓扑编辑迁移 M0 §6：进前域校验 + 推断锁定）
# ---------------------------------------------------------------------------

# 地理 CRS 的轴域是解析定义（经纬度全域），不是经验值。
_GEOGRAPHIC_DEGREE_DOMAIN = (-180.0, -90.0, 180.0, 90.0)
# 变换/面积比较的容差：投影域边界按面积适用范围给出，贴边数据不算失配。
_DOMAIN_EPSILON = 1e-9
# 投影 CRS 的 area_of_use 角点变换是近似框——域外扩比例（贴边真实数据
# 不误拦；明显域外数据仍失配）。
_PROJECTED_DOMAIN_SLACK = 0.02


def crs_coordinate_domain(crs: object) -> tuple[float, float, float, float] | None:
    """声明 CRS 的有效坐标域（CRS 自身坐标单位）；不可推导 → None。

    - 地理 CRS → 经纬度全域（轴定义，精确）。
    - 投影 CRS → pyproj ``area_of_use``（适用范围的经纬度框）变换回该 CRS
      的坐标单位；无 area_of_use / 无 pyproj / 变换失败 → None（诚实：
      无法验证 ≠ 通过）。
    - 未声明 → None（没有可校验的域）。
    """
    text = normalize_crs(crs)
    if not text:
        return None
    if crs_is_geographic(text) is True:
        return _GEOGRAPHIC_DEGREE_DOMAIN
    try:
        from pyproj import CRS, Transformer

        parsed = CRS.from_user_input(text)
        usage = parsed.area_of_use
        if usage is None or usage.west is None or usage.south is None \
                or usage.east is None or usage.north is None:
            return None
        forward = Transformer.from_crs(
            CRS.from_epsg(4326), parsed, always_xy=True)
        corners = [
            (usage.west, usage.south), (usage.east, usage.south),
            (usage.east, usage.north), (usage.west, usage.north),
        ]
        xs: list[float] = []
        ys: list[float] = []
        for lon, lat in corners:
            x, y = forward.transform(lon, lat)
            # 采样点落在变换定义域外（反常的 area_of_use）→ 无法给出
            # 可信域，而不是拿 inf 当边界。
            if not (abs(x) < 1e12 and abs(y) < 1e12):
                return None
            xs.append(x)
            ys.append(y)
        # 投影域是 area_of_use 角点变换的近似框：外扩 2% 容差，贴着适用
        # 范围边缘的真实数据（跨带边界/赤道边）不算失配；地理域是轴
        # 定义，不外扩。
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        slack_x = (maxx - minx) * _PROJECTED_DOMAIN_SLACK
        slack_y = (maxy - miny) * _PROJECTED_DOMAIN_SLACK
        return (minx - slack_x, miny - slack_y, maxx + slack_x, maxy + slack_y)
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class DomainMismatch:
    """一次「声明 CRS 坐标域 vs 数据实际坐标范围」失配的事实。"""

    crs: str
    extent: tuple[float, float, float, float]
    domain: tuple[float, float, float, float]

    def describe(self) -> str:
        return (
            f"声明 CRS {self.crs} 的有效坐标域为 "
            f"x[{self.domain[0]:g}, {self.domain[2]:g}] / "
            f"y[{self.domain[1]:g}, {self.domain[3]:g}]，"
            f"数据实际坐标范围为 x[{self.extent[0]:g}, {self.extent[2]:g}] / "
            f"y[{self.extent[1]:g}, {self.extent[3]:g}]"
        )


def coordinate_domain_mismatch(
    crs: object,
    extent: object,
) -> DomainMismatch | None:
    """数据范围未完全落在声明 CRS 的有效坐标域内 → 失配事实；否则 None。

    无法推导坐标域（未声明/投影无 area_of_use/pyproj 缺席）→ None：
    域校验只拦截**可证明**的失配（fail-open 与镜像层 extent 检查同约定）。
    """
    if extent is None:
        return None
    try:
        xmin, ymin, xmax, ymax = (float(v) for v in tuple(extent)[:4])
    except (TypeError, ValueError):
        return None
    if not (xmin <= xmax and ymin <= ymax):
        return None
    domain = crs_coordinate_domain(crs)
    if domain is None:
        return None
    dminx, dminy, dmaxx, dmaxy = domain
    eps = _DOMAIN_EPSILON * max(1.0, abs(dmaxx - dminx), abs(dmaxy - dminy))
    fits = (
        xmin >= dminx - eps and xmax <= dmaxx + eps
        and ymin >= dminy - eps and ymax <= dmaxy + eps
    )
    if fits:
        return None
    return DomainMismatch(
        crs=normalize_crs(crs) or str(crs or ""),
        extent=(xmin, ymin, xmax, ymax),
        domain=domain,
    )


@dataclass(frozen=True, slots=True)
class CRSInference:
    """按数据坐标范围对工程 CRS 声明的推断结论（§6 推断锁定）。

    ``suggested_crs`` 为空 = 保持本地（不声明）；非空 = 可识别的 CRS，
    由用户确认后写入声明并锁定。``basis`` 是推断依据（诊断/对话文案用）。
    """

    suggested_crs: str
    basis: str

    @property
    def suggests_declaration(self) -> bool:
        return bool(self.suggested_crs)


def infer_crs_from_extent(extent: object) -> CRSInference:
    """首次导入数据的坐标范围推断（§6）。

    - 完全落在经纬度域内 → 数据本身是地理坐标，建议声明 EPSG:4326。
    - 超出经纬度域 → 本地/投影坐标，从范围无法识别具体投影 → 保持本地
      （未声明）；声明留待用户手动指定。
    - 范围不可用（空层/无效）→ 不推断，保持本地。
    """
    if extent is None:
        return CRSInference("", "数据坐标范围不可用——不推断")
    try:
        bounds = tuple(float(v) for v in tuple(extent)[:4])
        if not (bounds[0] <= bounds[2] and bounds[1] <= bounds[3]):
            return CRSInference("", "数据坐标范围不可用——不推断")
    except (TypeError, ValueError, IndexError):
        return CRSInference("", "数据坐标范围不可用——不推断")
    mismatch = coordinate_domain_mismatch("EPSG:4326", extent)
    if mismatch is None:
        return CRSInference(
            "EPSG:4326", "数据坐标完全落在经纬度域内（地理坐标）")
    return CRSInference("", "数据坐标超出经纬度域（本地/投影坐标）——保持本地")
