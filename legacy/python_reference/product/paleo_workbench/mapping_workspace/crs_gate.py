"""V11 M0（#1285）：可编辑层 CRS 契约——进前域校验 + 引导式修复。

已知事故形态：声明 EPSG:4326（±180/±90 地理域）+ 数据坐标 0–16000
（本地坐标）。本模块在**进入编辑前**做声明的有效坐标域 vs 数据实际坐标
范围的失配检测，产出机器可读结果与修复选项；修复（改声明为本地 /
清除声明）由宿主对话框执行，同一检测在打开工程时兜底再跑一次。

纯函数、无 Qt/桥依赖（fallback 画布同样可用）；地理 CRS 识别用已知
authid 集 + ``+proj=longlat`` 前缀（PROJ 字符串声明）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "CrsDomainCheck",
    "GEOGRAPHIC_AUTHIDS",
    "is_geographic_declaration",
    "feature_bounds",
    "validate_crs_domain",
    "crs_mismatch_reason",
    "collect_crs_mismatches",
]

#: 常见地理（经纬度）CRS authid（域 ±180/±90，容差 1° 供球面溢出）。
GEOGRAPHIC_AUTHIDS: frozenset[str] = frozenset({
    "epsg:4326", "epsg:4490", "epsg:4214", "epsg:4610", "epsg:4269",
    "epsg:4267", "epsg:4230", "epsg:4314", "ogc:crs84",
})

_GEOGRAPHIC_LATLON_PREFIXES = ("+proj=longlat", "+proj=latlong")

#: 地理域容差（度）——略超 ±180/±90 的合法球面环绕不算失配。
_DOMAIN_SLACK = 1.0


@dataclass(frozen=True)
class CrsDomainCheck:
    """进前域校验结果（机器可读；宿主据此阻止进入编辑并给出引导）。"""

    ok: bool
    declared_crs: str = ""
    geographic_declared: bool = False
    bounds: tuple[float, float, float, float] | None = None
    reason: str = ""

    @property
    def fix_options(self) -> tuple[str, ...]:
        """修复选项（"declare_local" 推荐 / "clear"）。"""
        if self.ok:
            return ()
        return ("declare_local", "clear")


def is_geographic_declaration(declared_crs: str) -> bool:
    """声明的 CRS 是否地理（经纬度）坐标系。"""
    authid = str(declared_crs or "").strip().lower()
    if not authid:
        return False
    if authid in GEOGRAPHIC_AUTHIDS:
        return True
    return any(authid.startswith(prefix) for prefix in _GEOGRAPHIC_LATLON_PREFIXES)


def feature_bounds(coords: Iterable[Sequence[float]]) -> tuple[float, float, float, float] | None:
    """坐标流（[x, y, ...]）的包围盒；空 → None。"""
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    has = False
    for coord in coords:
        if not coord or len(coord) < 2:
            continue
        x, y = float(coord[0]), float(coord[1])
        if not (finite(x) and finite(y)):
            continue
        has = True
        xmin = min(xmin, x)
        ymin = min(ymin, y)
        xmax = max(xmax, x)
        ymax = max(ymax, y)
    return (xmin, ymin, xmax, ymax) if has else None


def finite(value: float) -> bool:
    import math

    return math.isfinite(value)


def validate_crs_domain(
    declared_crs: str,
    bounds: tuple[float, float, float, float] | None,
) -> CrsDomainCheck:
    """声明的坐标域 vs 数据实际范围（进前段门禁的机器判定）。"""
    declared = str(declared_crs or "").strip()
    geographic = is_geographic_declaration(declared)
    if not geographic:
        return CrsDomainCheck(ok=True, declared_crs=declared,
                              geographic_declared=False, bounds=bounds)
    if bounds is None:
        return CrsDomainCheck(ok=True, declared_crs=declared,
                              geographic_declared=True, bounds=None)
    xmin, ymin, xmax, ymax = bounds
    if (xmin < -180.0 - _DOMAIN_SLACK or xmax > 180.0 + _DOMAIN_SLACK
            or ymin < -90.0 - _DOMAIN_SLACK or ymax > 90.0 + _DOMAIN_SLACK):
        return CrsDomainCheck(
            ok=False, declared_crs=declared, geographic_declared=True,
            bounds=bounds,
            reason=crs_mismatch_reason(declared, bounds))
    return CrsDomainCheck(ok=True, declared_crs=declared,
                          geographic_declared=True, bounds=bounds)


def crs_mismatch_reason(declared: str, bounds: tuple[float, float, float, float]) -> str:
    xmin, ymin, xmax, ymax = bounds
    return (
        f"声明 {declared}（经纬度域 ±180/±90），但数据坐标范围 "
        f"x:[{xmin:g}, {xmax:g}]、y:[{ymin:g}, {ymax:g}] 为本地坐标"
        "——失配声明会污染编辑缓冲几何。")


def collect_crs_mismatches(
    layers: Iterable[tuple[str, str, Iterable[Sequence[float]]]],
) -> dict[str, CrsDomainCheck]:
    """工程打开兜底检测：``(layer_id, declared_crs, coords)`` 流 → 失配表。

    一次修复永久生效（声明更正后进前门禁自然放行）。
    """
    mismatches: dict[str, CrsDomainCheck] = {}
    for layer_id, declared, coords in layers:
        check = validate_crs_domain(declared, feature_bounds(coords))
        if not check.ok:
            mismatches[str(layer_id)] = check
    return mismatches
