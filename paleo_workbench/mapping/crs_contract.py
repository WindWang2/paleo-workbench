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

import logging
from dataclasses import dataclass

__all__ = [
    "CRSResolution",
    "panel_publish_crs",
    "crs_axis_unit_metres",
    "crs_is_geographic",
    "geod_for_crs",
    "normalize_crs",
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


def crs_axis_unit_metres(crs: object) -> bool | None:
    """True when the CRS horizontal axis unit is exactly metres.

    ``None`` = unverifiable (unknown id / no pyproj). Used by the honest
    scale-denominator derivation: a denominator computed from pixel metrics
    is only meaningful for metre axes, everything else reports unknown
    rather than a plausible-looking wrong number.
    """
    text = str(crs or "").strip()
    if not text:
        return None
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
