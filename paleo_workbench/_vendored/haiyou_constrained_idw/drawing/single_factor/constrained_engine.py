"""Constrained single-factor interpolation for contour draft generation.

This module is intentionally independent from the generic drawing contour
engine. It implements the first single-factor prototype only: hard barrier
visibility, local direction-line anisotropy, boundary masking, constrained IDW,
and masked marching-squares contour extraction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np



PointTuple = Tuple[float, float]

# block_mode 中显式表示"不阻断"的取值；缺失或未知取值一律按 full_block 处理（第一版只有硬打断）
_NON_BLOCKING_MODES = {"none", "off", "no_block", "soft", "partial", "0", "false"}


def is_full_block_mode(block_mode: str) -> bool:
    return str(block_mode or "").strip().lower() not in _NON_BLOCKING_MODES


@dataclass(frozen=True)
class ConstraintWell:
    well_id: str
    x: float
    y: float
    value: float
    is_control_point: bool = False


@dataclass(frozen=True)
class BoundaryPolygon:
    exterior: Tuple[PointTuple, ...]
    holes: Tuple[Tuple[PointTuple, ...], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BarrierLine:
    line_id: str
    points: Tuple[PointTuple, ...]
    active: bool = True
    block_mode: str = "full_block"
    priority: int = 3


@dataclass(frozen=True)
class DirectionLine:
    line_id: str
    points: Tuple[PointTuple, ...]
    active: bool = True
    # Surfer-style strong stretch default; legacy data without attrs
    # still works via workflow default_ratio.
    ratio: float = 18.0
    influence_radius: float = 0.0  # <=0 → auto from well spacing / map extent
    priority: int = 1
    # Full stretch inside core; smooth decay only between core and influence.
    core_radius: float = 0.0  # <=0 → use search_radius
    zone_id: str = ""
    extend_mode: str = "auto"  # auto | none | tangent
    transition: float = 0.0  # <=0 → auto (influence - core)


@dataclass(frozen=True)
class ConstrainedIDWConfig:
    grid_resolution: int = 160
    # power=2 keeps long-axis stretch visible (high power collapses to nearest wells)
    power: float = 2.0
    search_radius: float = 10000.0
    interpolation_mask_radius: float = 0.0
    interpolation_mask_use_control_points: bool = False
    grid_smoothing_iterations: int = 2
    # 平滑/补洞默认不跨越打断线，否则硬打断产生的不连续会被邻域平均抹平
    smooth_across_barriers: bool = False
    # 方向线影响范围内使用方向距离筛选候选井（沿线可达 ratio*search_radius）；
    # 关闭后仍按普通欧氏半径筛选，仅用方向距离排序/加权
    use_extended_search: bool = True
    # Optional: leave a blank buffer around barriers. Keep this at 0 for the
    # normal partition-interpolation workflow; barriers should split sampling
    # regions, not cut the final contour geometry.
    barrier_blank_cells: float = 0.0
    # Meter-based barrier buffer. When > 0, this takes precedence over the
    # legacy grid-cell buffer and turns the barrier into a no-interpolation
    # corridor. This removes numerical contour crowding along the partition.
    barrier_buffer_distance: float = 0.0
    # Whether the resolved barrier buffer also blanks the trend surface. Keep
    # this True for explicit/manual buffers; current-layer cartographic mode
    # sets it False for auto buffers so the color surface reaches the barrier
    # smoothly while contours still stop there.
    barrier_buffer_applies_to_surface: bool = True
    # 未手动指定缓冲距离时，按网格步长/搜索半径/图幅自动估算打断线缓冲带宽度。
    barrier_buffer_auto: bool = True
    # 分区构建阶段允许把打断线端点沿切向外延少量网格，修正手工绘制时
    # 未精确贴到成图边界导致区域无法分开的情况。只影响分区标签，不改变
    # 原始线要素显示，也不制造屏蔽空白带。
    # 仅当显式开启 barrier_extend_to_boundary 时，分区阶段才外延打断线端点。
    barrier_partition_extension_cells: float = 0.0
    # 打断线自动延伸到成图边界作为分割线：手绘的半截打断线端点会沿切向
    # 延伸整幅对角线长度（保证穿出边界），泛洪无法绕过 → 强制分区。
    # 默认关闭；缓冲带始终按用户绘制的原始线段长度生成，不做任何延长。
    barrier_extend_to_boundary: bool = False
    # 插值完成后在井点位置做残差回写，保证井所在网格及邻域与观测值一致。
    well_anchor_enabled: bool = True
    # 井点残差扩散半径（米）；<=0 时按网格步长自动估算。
    # 调大以让井值修正向周围扩散，避免孤立闭合等值线（用户反馈局部高低被当孤立区域）。
    well_anchor_radius: float = 0.0
    # Keep the well cell exact, but cap the broad residual halo to avoid sharp
    # isolated bullseyes after interpolation.
    well_anchor_max_residual_fraction: float = 0.16
    # 方向线拉伸的 taper 平台点：距线 <= plateau*R 满拉伸，plateau*R~R 线性降到 1。
    # Kept for backward compatibility; curve-corridor uses core/influence radii.
    direction_taper_plateau: float = 0.85
    # 方向线平滑引导强度：沿切向邻域加权（轻度，避免抹掉多中心）
    direction_smoothing_strength: float = 1.8
    # 方向距离垂向惩罚（与 ratio 形成椭圆搜索）
    direction_perpendicular_strength: float = 1.0
    # 方向走廊候选井加权（轻度引导）
    direction_corridor_strength: float = 1.0
    # 补洞是否沿方向各向异性扩散
    anisotropic_fill: bool = True
    # Use curve-coordinate (s,n) distance + elliptical search (Surfer-style)
    use_curve_direction_distance: bool = True
    gap_fill_iterations: int = 8
    # 为 True 时，未设置插值区 polygon 的情况下，插值/补洞仅限井点搜索半径内。
    limit_interpolation_to_search_radius: bool = True
    contour_extraction_method: str = "partitioned_marching_squares"
    contour_smoothing_iterations: int = 2
    contour_upsample_factor: int = 1
    contour_bridge_gap: float = 0.0
    min_contour_length: float = 0.0
    contour_simplify_tolerance: float = 0.0
    clip_contours_to_barriers: bool = False
    # 等值线线间距（地图单位）。0=自动(~1.5×网格步长)；负数=关闭。
    min_contour_spacing: float = -1.0
    # 等值线不得相交（强约束，默认开启）
    enforce_no_crossing: bool = True
    # False：只生成趋势面栅格，跳过 MS/贴边/消交等重型等值线路径（避免“生成趋势面”卡住）
    extract_contours: bool = True
    # True：缩小井点圆形融合以保留方向拉伸（有方向线时必须开启，避免残差圆斑抵消拉伸）
    well_anchor_preserve_anisotropy: bool = True
    # Red-oval along-track ridge blend (0=off default for unit tests;
    # workflow sets ~1.0 when directions enabled for production red-corridor stretch)
    along_track_blend_strength: float = 0.0
    along_track_min_cell_g: float = 0.05
    # Exponential weight steepness for corridor blend (non-linear, user request)
    along_track_exp_k: float = 6.0
    # 去聚类：半径内邻居越多权越低，避免密井合成单一大高值团
    # 半径/强度偏大 → 密井区降权更狠，孤立高点更突出，趋势更清晰
    decluster_radius: float = 6500.0
    decluster_strength: float = 2.0
    min_points: int = 3
    max_points: int = 12
    value_min: Optional[float] = 0.0
    value_max: Optional[float] = 1.0
    endpoint_tolerance: float = 1e-7
    boundary_margin_ratio: float = 0.02
    data_hull_buffer_meters: float = 0.0


@dataclass
class ConstrainedGridResult:
    grid_z: np.ndarray
    grid_x: np.ndarray
    grid_y: np.ndarray
    contours: Dict[float, List[List[PointTuple]]]
    diagnostics: Dict[str, int]
    # Dense surface actually used for contour extraction (upsampled + barrier stop mask).
    surface_grid: Optional[np.ndarray] = None
    surface_x: Optional[np.ndarray] = None
    surface_y: Optional[np.ndarray] = None


def resolve_interpolation_mask_radius(mask_radius: float, search_radius: float) -> float:
    """Effective well-coverage radius for interpolation domain masking."""
    explicit = float(mask_radius)
    if explicit > 0.0:
        return explicit
    return max(float(search_radius), 1.0)


def build_well_coverage_mask(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    wells: Sequence[ConstraintWell],
    coverage_radius: float,
) -> Optional[np.ndarray]:
    """Mark grid cells that lie within ``coverage_radius`` of at least one well."""
    if not wells or coverage_radius <= 0.0 or len(grid_x) == 0 or len(grid_y) == 0:
        return None
    well_xy = np.asarray([(well.x, well.y) for well in wells], dtype=float)
    radius_sq = float(coverage_radius) * float(coverage_radius)
    cols = np.asarray(grid_x, dtype=float)
    rows = np.asarray(grid_y, dtype=float)
    dx = cols[None, :] - well_xy[:, 0][:, None, None]
    dy = rows[None, :, None] - well_xy[:, 1][:, None, None]
    dist_sq = dx * dx + dy * dy
    return np.any(dist_sq <= radius_sq, axis=0)


def resolve_barrier_buffer_distance(
    requested_distance: float,
    legacy_cell_buffer: float,
    grid_step: float,
    map_width: float,
    map_height: float,
    search_radius: float,
    has_barriers: bool,
    auto_enabled: bool = True,
) -> Tuple[float, bool]:
    """Resolve the effective barrier blank-buffer distance in map units."""
    if requested_distance > 0.0:
        return requested_distance, False
    if legacy_cell_buffer > 0.0:
        return legacy_cell_buffer, False
    if not has_barriers or not auto_enabled:
        return 0.0, False

    map_extent = max(map_width, map_height, grid_step)
    # 偏细缓冲（约 200–400 m 量级）；默认产品取向 300 m 左右
    adaptive = max(
        grid_step * 2.0,
        search_radius * 0.03,  # 搜索 10 km → 约 300 m
        map_extent * 0.012,
    )
    # 避免缓冲过宽把有效插值域吃掉；上限约图幅 4%
    adaptive = min(adaptive, map_extent * 0.04, 400.0)
    return adaptive, True


def apply_well_residual_anchoring(
    grid: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    wells: Sequence[ConstraintWell],
    domain_mask: np.ndarray,
    config: ConstrainedIDWConfig,
    region_labels: Optional[np.ndarray] = None,
    well_labels: Optional[np.ndarray] = None,
    direction_field: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """Re-anchor interpolated grid values to observed well values via residual correction.

    1. 核心：邻域内强制井值
    2. 过渡：环带残差按径向余弦衰减
    3. 可选高斯融合；开启 preserve_anisotropy 或提供 direction_field 时使用
       与插值一致的椭圆/方向距离，避免残差圆斑抵消方向拉伸
    """
    stats: Dict[str, float] = {
        "well_anchor_count": 0.0,
        "well_anchor_residual_cells": 0.0,
        "well_anchor_max_residual": 0.0,
        "well_anchor_core_cells": 0.0,
        "well_anchor_smooth_cells": 0.0,
        "well_anchor_anisotropic": 0.0,
        "well_anchor_limited_count": 0.0,
    }
    if not config.well_anchor_enabled or grid.size == 0 or not wells:
        return grid, stats

    result = np.array(grid, dtype=float, copy=True)
    grid_step = _estimate_grid_step(grid_x, grid_y)
    step = max(float(grid_step), 1e-9)
    has_dir = (
        direction_field is not None
        and direction_field.ndim == 3
        and direction_field.shape[2] >= 3
        and bool(np.any(direction_field[:, :, 2] > 1.0 + 1e-9))
    )
    preserve_aniso = bool(getattr(config, "well_anchor_preserve_anisotropy", True)) or has_dir
    if has_dir:
        stats["well_anchor_anisotropic"] = 1.0
    anchor_radius = float(config.well_anchor_radius)
    if anchor_radius <= 0.0:
        # 保留各向异性时缩小锚定半径，防止井群合成圆形“一坨”
        if preserve_aniso:
            anchor_radius = max(step * 4.0, step * 2.5)
        else:
            # 略放大锚定核，高值井周红斑更醒目
            anchor_radius = max(step * 10.0, step * 4.0)
    # 核心稍小，保证过渡自然
    if preserve_aniso:
        core_radius = max(step * 0.9, min(anchor_radius * 0.22, step * 1.6))
    else:
        core_radius = max(step * 1.5, min(anchor_radius * 0.32, step * 3.0))
    # Elliptical search bbox must cover R_parallel ≈ ratio * anchor when stretched
    max_stretch = 1.0
    if has_dir:
        max_stretch = float(np.nanmax(direction_field[:, :, 2]))
        max_stretch = max(max_stretch, 1.0)
    search_bbox_radius = anchor_radius * max(max_stretch, 1.0) if has_dir else anchor_radius
    radius_cells = max(3, int(math.ceil(search_bbox_radius / step)) + 1)
    # 高斯融合：保留方向时显著缩小，几乎只贴井点
    if preserve_aniso:
        blend_radius = max(anchor_radius * 0.55, step * 2.0)
        sigma = max(anchor_radius * 0.28, step * 1.0)
    else:
        blend_radius = max(anchor_radius * 1.15, step * 4.0)
        sigma = max(anchor_radius * 0.45, step * 1.5)
    blend_cells = max(radius_cells, int(math.ceil(blend_radius * max(max_stretch, 1.0) / step)) + 1)

    rows, cols = result.shape
    # (row, col, x, y, exact target, soft halo target, unit_x, unit_y, ratio)
    well_centers: List[
        Tuple[int, int, float, float, float, float, float, float, float]
    ] = []
    finite_values = [float(well.value) for well in wells if math.isfinite(float(well.value))]
    if config.value_min is not None and config.value_max is not None:
        value_span = max(float(config.value_max) - float(config.value_min), 0.0)
    elif finite_values:
        value_span = max(finite_values) - min(finite_values)
    else:
        value_span = 0.0
    residual_cap = value_span * max(
        0.0, float(getattr(config, "well_anchor_max_residual_fraction", 0.16))
    )

    for well_index, well in enumerate(wells):
        col = int(np.argmin(np.abs(grid_x - well.x)))
        row = int(np.argmin(np.abs(grid_y - well.y)))
        if row < 0 or col < 0 or row >= rows or col >= cols:
            continue
        if not domain_mask[row, col]:
            continue
        if region_labels is not None and well_labels is not None:
            well_label = int(well_labels[well_index])
            cell_label = int(region_labels[row, col])
            if well_label >= 0 and cell_label >= 0 and well_label != cell_label:
                continue

        center_value = result[row, col]
        target_value = float(well.value)
        if not math.isfinite(target_value):
            continue
        if config.value_min is not None:
            target_value = max(float(config.value_min), target_value)
        if config.value_max is not None:
            target_value = min(float(config.value_max), target_value)

        if not math.isfinite(center_value):
            residual = 0.0
        else:
            residual = target_value - float(center_value)
        stats["well_anchor_max_residual"] = max(
            stats["well_anchor_max_residual"],
            abs(residual),
        )
        stats["well_anchor_count"] += 1.0
        halo_scale = 1.0
        if residual_cap > 1e-9 and abs(residual) > residual_cap:
            halo_scale = residual_cap / abs(residual)
            stats["well_anchor_limited_count"] += 1.0
        halo_target = (
            target_value
            if not math.isfinite(center_value)
            else float(center_value) + residual * halo_scale
        )

        unit_x, unit_y, ratio_eff = 1.0, 0.0, 1.0
        if has_dir and direction_field is not None:
            unit_x = float(direction_field[row, col, 0])
            unit_y = float(direction_field[row, col, 1])
            ratio_eff = float(direction_field[row, col, 2])
            if ratio_eff <= 1.0 + 1e-9 or (abs(unit_x) + abs(unit_y)) <= 1e-12:
                unit_x, unit_y, ratio_eff = 1.0, 0.0, 1.0
            else:
                nrm = math.hypot(unit_x, unit_y) or 1.0
                unit_x, unit_y = unit_x / nrm, unit_y / nrm

        well_centers.append(
            (
                row,
                col,
                float(well.x),
                float(well.y),
                target_value,
                halo_target,
                unit_x,
                unit_y,
                ratio_eff,
            )
        )

        # 1) 核心 + 过渡：有方向时用椭圆距离，无方向时用欧氏（向量化窗口）
        pr = row + np.arange(-radius_cells, radius_cells + 1, dtype=int)
        pc = col + np.arange(-radius_cells, radius_cells + 1, dtype=int)
        inb = (pr >= 0) & (pr < rows)
        inb_c = (pc >= 0) & (pc < cols)
        idx_r, idx_c = np.ix_(np.clip(pr, 0, rows - 1), np.clip(pc, 0, cols - 1))
        patch = result[idx_r, idx_c]
        dom = np.asarray(domain_mask, dtype=bool)[idx_r, idx_c]
        ok = inb[:, None] & inb_c[None, :] & dom
        if region_labels is not None:
            ok = ok & (region_labels[idx_r, idx_c] == int(region_labels[row, col]))
        gx_patch = np.asarray(grid_x, dtype=float)[np.clip(pc, 0, cols - 1)][None, :]
        gy_patch = np.asarray(grid_y, dtype=float)[np.clip(pr, 0, rows - 1)][:, None]
        if ratio_eff > 1.0 + 1e-9:
            vx = gx_patch - float(well.x)
            vy = gy_patch - float(well.y)
            u = vx * unit_x + vy * unit_y
            v = vx * (-unit_y) + vy * unit_x
            perp = direction_perpendicular_scale(
                ratio_eff,
                float(getattr(config, "direction_perpendicular_strength", 1.0)),
            )
            cross = max(float(perp), 1.0)
            dist = np.sqrt((u / max(ratio_eff, 1.0)) ** 2 + (v * cross) * (v * cross))
        else:
            dist = np.hypot(gx_patch - float(well.x), gy_patch - float(well.y))
        dist_ok = dist <= anchor_radius
        center_cell = (pr[:, None] == row) & (pc[None, :] == col)
        halo = (
            ok
            & dist_ok
            & ~center_cell
            & (abs(residual) > 1e-9)
            & np.isfinite(patch)
        )
        if np.any(center_cell & dist_ok & ok):
            stats["well_anchor_core_cells"] += 1.0
        if np.any(halo):
            t = np.clip(
                (dist - core_radius) / max(anchor_radius - core_radius, 1e-9),
                0.0,
                1.0,
            )
            weight = 0.5 * (1.0 + np.cos(np.pi * t))
            corrected = patch + residual * halo_scale * weight
            if (
                config.value_min is not None
                and config.value_max is not None
                and float(config.value_min) <= target_value <= float(config.value_max)
            ):
                corrected = np.clip(corrected, float(config.value_min), float(config.value_max))
            stats["well_anchor_residual_cells"] += float(np.count_nonzero(halo))
            new_patch = np.where(halo, corrected, patch)
            new_patch = np.where(center_cell & dist_ok & ok, target_value, new_patch)
            result[idx_r, idx_c] = new_patch
        elif np.any(center_cell & dist_ok & ok):
            result[row, col] = target_value

    # 3) 融合：有方向时只做极轻贴井（椭圆邻域）；无方向时保留圆顶过渡
    if well_centers and (not preserve_aniso or blend_radius >= step * 1.5):
        blended = np.array(result, dtype=float, copy=True)
        two_sig2 = 2.0 * sigma * sigma
        core_mix = 0.70 if preserve_aniso else 0.85
        outer_well = 0.35 if preserve_aniso else 0.55
        outer_keep = 0.65 if preserve_aniso else 0.45
        for row, col, wx, wy, target_value, halo_target, unit_x, unit_y, ratio_eff in well_centers:
            pr = row + np.arange(-blend_cells, blend_cells + 1, dtype=int)
            pc = col + np.arange(-blend_cells, blend_cells + 1, dtype=int)
            inb = (pr >= 0) & (pr < rows)
            inb_c = (pc >= 0) & (pc < cols)
            idx_r, idx_c = np.ix_(np.clip(pr, 0, rows - 1), np.clip(pc, 0, cols - 1))
            patch = result[idx_r, idx_c]
            dom = np.asarray(domain_mask, dtype=bool)[idx_r, idx_c]
            ok = (
                inb[:, None]
                & inb_c[None, :]
                & dom
                & np.isfinite(patch)
            )
            if region_labels is not None:
                ok = ok & (region_labels[idx_r, idx_c] == int(region_labels[row, col]))
            gx_patch = np.asarray(grid_x, dtype=float)[np.clip(pc, 0, cols - 1)][None, :]
            gy_patch = np.asarray(grid_y, dtype=float)[np.clip(pr, 0, rows - 1)][:, None]
            if ratio_eff > 1.0 + 1e-9:
                vx = gx_patch - wx
                vy = gy_patch - wy
                u = vx * unit_x + vy * unit_y
                v = vx * (-unit_y) + vy * unit_x
                perp = direction_perpendicular_scale(
                    ratio_eff,
                    float(getattr(config, "direction_perpendicular_strength", 1.0)),
                )
                cross = max(float(perp), 1.0)
                dist = np.sqrt((u / max(ratio_eff, 1.0)) ** 2 + (v * cross) * (v * cross))
            else:
                dist = np.hypot(gx_patch - wx, gy_patch - wy)
            dist_ok = dist <= blend_radius
            center_cell = (pr[:, None] == row) & (pc[None, :] == col)
            valid = ok & dist_ok
            if preserve_aniso:
                radial = np.exp(-(dist * dist) / max(two_sig2, 1e-12))
                core = dist <= core_radius
                new_v = np.where(
                    core,
                    core_mix * halo_target + (1.0 - core_mix) * patch,
                    radial * (outer_well * halo_target + outer_keep * patch)
                    + (1.0 - radial) * patch,
                )
            else:
                # 局部 3x3 高斯均值（采样半径 2 格）
                sample_r = max(1, int(math.ceil(1.6 * step / step)))
                pr_ext = row + np.arange(
                    -blend_cells - sample_r, blend_cells + sample_r + 1, dtype=int
                )
                pc_ext = col + np.arange(
                    -blend_cells - sample_r, blend_cells + sample_r + 1, dtype=int
                )
                pr_clip = np.clip(pr_ext, 0, rows - 1)
                pc_clip = np.clip(pc_ext, 0, cols - 1)
                idx_re, idx_ce = np.ix_(pr_clip, pc_clip)
                ext = result[idx_re, idx_ce]
                ext_ok = (
                    (pr_ext >= 0)[:, None]
                    & (pr_ext < rows)[:, None]
                    & (pc_ext >= 0)[None, :]
                    & (pc_ext < cols)[None, :]
                    & np.asarray(domain_mask, dtype=bool)[idx_re, idx_ce]
                    & np.isfinite(ext)
                )
                if region_labels is not None:
                    ext_ok = ext_ok & (
                        region_labels[idx_re, idx_ce] == int(region_labels[row, col])
                    )
                acc = np.zeros(ext.shape, dtype=float)
                wsum = np.zeros(ext.shape, dtype=float)
                for sdr in range(-sample_r, sample_r + 1):
                    for sdc in range(-sample_r, sample_r + 1):
                        r_dst, c_dst, r_src, c_src = _offset_slices(
                            ext.shape[0], ext.shape[1], sdr, sdc
                        )
                        sw = math.exp(
                            -(float(sdr * sdr + sdc * sdc) * (step * step))
                            / max(two_sig2 * 0.35, 1e-12)
                        )
                        src_ok = ext_ok[r_src, c_src]
                        acc[r_dst, c_dst] += np.where(
                            src_ok, ext[r_src, c_src] * sw, 0.0
                        )
                        wsum[r_dst, c_dst] += np.where(src_ok, sw, 0.0)
                local_mean = np.zeros(ext.shape, dtype=float)
                filled = wsum > 1e-12
                local_mean[filled] = acc[filled] / wsum[filled]
                local_mean = local_mean[
                    sample_r : ext.shape[0] - sample_r,
                    sample_r : ext.shape[1] - sample_r,
                ]
                radial = np.exp(-(dist * dist) / max(two_sig2, 1e-12))
                core = dist <= core_radius
                new_v = np.where(
                    core,
                    core_mix * halo_target + (1.0 - core_mix) * local_mean,
                    radial * (outer_well * halo_target + outer_keep * patch)
                    + (1.0 - radial) * local_mean,
                )
            new_v = np.where(center_cell, target_value, new_v)
            if (
                config.value_min is not None
                and config.value_max is not None
                and float(config.value_min) <= target_value <= float(config.value_max)
            ):
                new_v = np.clip(new_v, float(config.value_min), float(config.value_max))
            stats["well_anchor_smooth_cells"] += float(np.count_nonzero(valid))
            blended[idx_r, idx_c] = np.where(
                valid, new_v, blended[idx_r, idx_c]
            )
        result = blended

    return result, stats


def generate_constrained_idw(
    wells: Sequence[ConstraintWell],
    boundaries: Sequence[BoundaryPolygon],
    barriers: Sequence[BarrierLine],
    directions: Sequence[DirectionLine],
    levels: Sequence[float],
    config: ConstrainedIDWConfig,
    interpolation_areas: Optional[Sequence[BoundaryPolygon]] = None,
) -> ConstrainedGridResult:
    """Generate a constrained IDW surface and masked contour polylines."""
    if len(wells) < 3:
        raise ValueError(f"有效井点不足，至少需要 3 个，当前 {len(wells)} 个")
    if not boundaries:
        raise ValueError("当前图层模式需要至少 1 个边界面")

    resolution = max(20, min(2000, int(config.grid_resolution)))
    grid_x, grid_y = _build_grid_axes(boundaries, resolution, config.boundary_margin_ratio)
    grid_z = np.full((len(grid_y), len(grid_x)), np.nan, dtype=float)
    domain_mask = np.zeros((len(grid_y), len(grid_x)), dtype=bool)

    active_barriers = [
        line for line in barriers
        if line.active and is_full_block_mode(line.block_mode) and len(line.points) >= 2
    ]
    # influence_radius <= 0 表示"自动半径"，保留交给 _resolve_direction_radii 处理
    active_directions = [
        line for line in directions
        if line.active and len(line.points) >= 2
    ]
    explicit_interpolation_areas = list(interpolation_areas or [])
    mask_source_wells = [
        well for well in wells
        if config.interpolation_mask_use_control_points or not well.is_control_point
    ]
    if not mask_source_wells:
        mask_source_wells = list(wells)
    mask_well_array = np.asarray([(w.x, w.y) for w in mask_source_wells], dtype=float)

    diagnostics = {
        "参与井点数": int(len(wells)),
        "控制点数": int(sum(1 for well in wells if well.is_control_point)),
        "control_point_count": int(sum(1 for well in wells if well.is_control_point)),
        "有效打断线数": int(len(active_barriers)),
        "active_barrier_count": int(len(active_barriers)),
        "有效方向线数": int(len(active_directions)),
        "active_direction_count": int(len(active_directions)),
        "有效网格点数": 0,
        "无效网格点数": 0,
        "显式插值区数": int(len(explicit_interpolation_areas)),
        "explicit_interpolation_area_count": int(len(explicit_interpolation_areas)),
        "插值区外网格点数": 0,
        "outside_interpolation_area_grid_points": 0,
        "生成等值线条数": 0,
        "被打断线过滤的井点-网格关系数量": 0,
        "blocked_well_grid_relations": 0,
        "打断线屏蔽网格点数": 0,
        "barrier_buffer_masked_grid_points": 0,
        "分割区域数": 0,
        "region_count": 0,
        "使用方向距离的网格点数": 0,
        "direction_distance_grid_points": 0,
        "普通距离网格点数": 0,
        "plain_distance_grid_points": 0,
        "方向线覆盖百分比": 0,
        "direction_coverage_percent": 0,
    }

    well_array = np.asarray([(w.x, w.y, w.value) for w in wells], dtype=float)
    density_diagnostics = summarize_point_density(well_array[:, :2], float(config.decluster_radius))
    diagnostics.update(density_diagnostics)
    density_weights = compute_declustering_weights(
        well_array[:, :2],
        float(config.decluster_radius),
        float(config.decluster_strength),
    )

    # ── 第 1 步：成图域掩码（边界 / 可选屏蔽带 / 插值区）──
    grid_step = _estimate_grid_step(grid_x, grid_y)
    map_width = float(grid_x[-1] - grid_x[0]) if len(grid_x) > 1 else grid_step
    map_height = float(grid_y[-1] - grid_y[0]) if len(grid_y) > 1 else grid_step
    map_diagonal = math.hypot(map_width, map_height)
    # 分区用打断线：默认严格使用用户绘制的原始几何，不做任何端点延长。
    # 仅当显式勾选 barrier_extend_to_boundary 时才沿切向延伸至图幅边界。
    if config.barrier_extend_to_boundary:
        partition_barriers = extend_barriers_for_partition(active_barriers, map_diagonal)
    else:
        partition_barriers = list(active_barriers)
    buffer_barriers = active_barriers
    buffer_distance, buffer_auto_applied = resolve_barrier_buffer_distance(
        requested_distance=max(0.0, float(config.barrier_buffer_distance)),
        legacy_cell_buffer=max(0.0, float(config.barrier_blank_cells)) * grid_step,
        grid_step=grid_step,
        map_width=map_width,
        map_height=map_height,
        search_radius=float(config.search_radius),
        has_barriers=bool(active_barriers),
        auto_enabled=bool(config.barrier_buffer_auto),
    )
    # 显示：全缓冲归 0；提取：仅窄核停线，后处理再禁入全缓冲并绕端头
    surface_blank_distance = buffer_distance
    contour_buffer_distance = buffer_distance
    blank_distance = buffer_distance
    from drawing.single_factor.fast_grid import build_boundary_union_mask, build_domain_mask_fast, rasterize_polygon_mask
    from drawing.single_factor.masks import (
        apply_mask_to_grid,
        build_bfs_reach_mask,
        build_contour_component_mask,
        build_contour_support_mask,
        build_data_hull_mask,
        resolve_bfs_reach_cells,
        resolve_contour_component_dilation_cells,
        resolve_contour_support_dilation_cells,
        resolve_data_hull_buffer_meters,
    )

    # 先成图边界，再生成缓冲掩膜并裁到边界内（缓冲不得出成图范围）
    boundary_mask = build_boundary_union_mask(grid_x, grid_y, boundaries)
    blank_mask = build_barrier_blank_mask(
        grid_x,
        grid_y,
        buffer_barriers,
        surface_blank_distance,
        domain_mask=boundary_mask,
    )
    # MS 只停窄核，避免整带挖洞；全缓冲禁入在 route 里做
    core_stop_distance = max(float(grid_step) * 0.85, 1e-9)
    contour_stop_mask = build_barrier_blank_mask(
        grid_x,
        grid_y,
        buffer_barriers,
        core_stop_distance,
        domain_mask=boundary_mask,
    )
    diagnostics["打断线缓冲距离"] = int(round(blank_distance))
    diagnostics["barrier_buffer_distance"] = float(contour_buffer_distance)
    diagnostics["barrier_buffer_auto_applied"] = int(buffer_auto_applied)
    diagnostics["barrier_surface_blank_distance"] = float(surface_blank_distance)
    diagnostics["barrier_buffer_applies_to_surface"] = 1
    diagnostics["barrier_contour_core_stop_distance"] = float(core_stop_distance)
    diagnostics["barrier_contour_stop_grid_points"] = int(np.count_nonzero(contour_stop_mask)) if contour_stop_mask is not None else 0

    # 方向线影响半径 auto：要素半径 <=0 时取半个图幅（大邻域，覆盖全图拉伸）
    auto_direction_radius = max(map_width, map_height) * 0.5
    resolved_directions = _resolve_direction_radii(active_directions, auto_direction_radius)
    effective_mask_radius = resolve_interpolation_mask_radius(
        float(config.interpolation_mask_radius),
        float(config.search_radius),
    )
    apply_well_coverage_mask = (
        float(config.interpolation_mask_radius) > 0.0
        or bool(config.limit_interpolation_to_search_radius)
    )
    diagnostics["interpolation_mask_radius_effective"] = float(effective_mask_radius if apply_well_coverage_mask else 0.0)
    diagnostics["well_coverage_limited"] = int(apply_well_coverage_mask)
    diagnostics["data_hull_limited"] = 0
    diagnostics["data_hull_buffer_meters"] = 0.0
    interpolation_area_masks = None
    if explicit_interpolation_areas:
        interpolation_area_masks = [
            rasterize_polygon_mask(grid_x, grid_y, area.exterior)
            for area in explicit_interpolation_areas
        ]
    well_coverage_mask = None
    if apply_well_coverage_mask:
        well_coverage_mask = build_well_coverage_mask(
            grid_x,
            grid_y,
            [
                ConstraintWell(str(index), float(x), float(y), 0.0)
                for index, (x, y) in enumerate(mask_well_array)
            ],
            effective_mask_radius,
        )
    data_hull_mask = None
    hull_buffer = resolve_data_hull_buffer_meters(
        float(config.data_hull_buffer_meters),
        float(config.search_radius),
        map_diagonal,
        limit_to_well_coverage=apply_well_coverage_mask,
    )
    limit_well_coverage = bool(config.limit_interpolation_to_search_radius)
    if hull_buffer > 0.0 or float(config.data_hull_buffer_meters) > 0.0:
        data_hull_mask = build_data_hull_mask(
            grid_x,
            grid_y,
            well_array[:, :2],
            buffer_meters=hull_buffer,
        )
        if data_hull_mask is not None:
            diagnostics["data_hull_limited"] = 1
            diagnostics["data_hull_buffer_meters"] = float(hull_buffer)
    # 限制外推时不用凸包扩域：井点沿边界分布时凸包会把内部无井区包进来。
    domain_hull_mask = None if limit_well_coverage else data_hull_mask
    if limit_well_coverage and data_hull_mask is not None:
        diagnostics["data_hull_domain_skipped"] = 1
    else:
        diagnostics["data_hull_domain_skipped"] = 0
    domain_mask = build_domain_mask_fast(
        grid_x,
        grid_y,
        boundaries,
        blank_mask=blank_mask,
        interpolation_area_masks=interpolation_area_masks,
        well_coverage_mask=well_coverage_mask,
        data_hull_mask=domain_hull_mask,
    )
    total_cells = int(domain_mask.size)
    valid_cells = int(np.count_nonzero(domain_mask))
    outside_cells = max(total_cells - valid_cells, 0)
    diagnostics["插值区外网格点数"] = outside_cells
    diagnostics["outside_interpolation_area_grid_points"] = outside_cells
    if blank_mask is not None:
        blank_count = int(np.count_nonzero(blank_mask & boundary_mask))
        diagnostics["打断线屏蔽网格点数"] = blank_count
        diagnostics["barrier_buffer_masked_grid_points"] = blank_count
    diagnostics["无效网格点数"] = int(np.count_nonzero(boundary_mask) - valid_cells)

    # ── 第 2 步：打断线分割区域，井点归属各自区域 ──
    # 贯穿成图区的打断线把区域一分为二，各区域用自己的井独立插值；
    # 未贯穿的打断线不改变连通性，靠视线阻断起局部作用。
    near_active_mask = build_barrier_proximity_mask(grid_x, grid_y, active_barriers)
    near_partition_mask = build_barrier_proximity_mask(grid_x, grid_y, partition_barriers)
    region_labels = None
    well_labels = None
    if active_barriers:
        region_labels = build_region_labels(
            grid_x,
            grid_y,
            domain_mask,
            partition_barriers,
            near_partition_mask,
        )
        region_count = int(region_labels.max()) + 1 if region_labels.size and region_labels.max() >= 0 else 0
        diagnostics["分割区域数"] = region_count
        diagnostics["region_count"] = region_count
        well_labels = assign_well_regions(well_array[:, :2], grid_x, grid_y, region_labels)
    else:
        diagnostics["分割区域数"] = 1 if bool(domain_mask.any()) else 0
        diagnostics["region_count"] = diagnostics["分割区域数"]

    # ── 第 3 步：区域内约束 IDW 插值趋势面（曲线坐标走廊 + 椭圆搜索）──
    from drawing.single_factor.fast_grid import interpolate_idw_grid_batch
    from drawing.single_factor.direction_corridor import (
        DirectionLineSpec,
        blend_corridor_along_track,
        build_along_track_well_profiles,
        build_direction_geometries,
        build_grid_direction_cache,
        build_legacy_direction_field,
        estimate_mean_well_spacing,
        precompute_well_curve_coords,
    )

    direction_field_for_idw = None
    direction_cache = None
    direction_geoms = []
    well_curve_coords: Dict[int, Dict[str, np.ndarray]] = {}
    use_curve = bool(getattr(config, "use_curve_direction_distance", True)) and bool(resolved_directions)

    if resolved_directions:
        mean_spacing = estimate_mean_well_spacing(well_array[:, :2])
        specs = [
            DirectionLineSpec(
                line_id=d.line_id,
                points=d.points,
                active=d.active,
                ratio=float(d.ratio),
                influence_radius=float(d.influence_radius),
                priority=int(d.priority),
                core_radius=float(getattr(d, "core_radius", 0.0) or 0.0),
                zone_id=str(getattr(d, "zone_id", "") or ""),
                extend_mode=str(getattr(d, "extend_mode", "auto") or "auto"),
                transition=float(getattr(d, "transition", 0.0) or 0.0),
            )
            for d in resolved_directions
        ]
        direction_geoms = build_direction_geometries(
            specs,
            search_radius=float(config.search_radius),
            mean_well_spacing=mean_spacing,
            map_extent=max(map_width, map_height),
        )
        if direction_geoms:
            direction_cache = build_grid_direction_cache(
                grid_x, grid_y, domain_mask, direction_geoms
            )
            direction_field_for_idw = build_legacy_direction_field(direction_cache)
            well_curve_coords = precompute_well_curve_coords(well_array[:, :2], direction_geoms)
            diagnostics["direction_curve_corridor"] = 1
            diagnostics["mean_well_spacing"] = float(mean_spacing)
            diagnostics["direction_geom_count"] = int(len(direction_geoms))
        else:
            diagnostics["direction_curve_corridor"] = 0
    if direction_field_for_idw is None and config.anisotropic_fill and resolved_directions:
        # Fallback: legacy fixed-angle field
        direction_field_for_idw = build_direction_field(
            grid_x, grid_y, domain_mask, resolved_directions, float(config.direction_taper_plateau)
        )
        diagnostics["direction_curve_corridor"] = 0

    diagnostics["vectorized_idw"] = 0
    # Performance-critical: NEVER run pure-Python per-cell IDW for direction-only
    # cases (600² domain freezes the UI). Use vectorized batch + direction_field.
    # Barriers are a hard LOS constraint: only the per-cell point path honours
    # it everywhere. Upstream switched to a vectorized batch + narrow
    # near-barrier LOS refine above 4096 domain cells, which leaked values
    # past dead-end barriers on larger grids. The host (the only caller of
    # this vendored copy) caps grid_resolution at 200, so the point path
    # stays responsive (~2 s worst case with barriers).
    domain_cell_count = int(np.count_nonzero(domain_mask))
    use_full_point_path = bool(active_barriers) or bool(
        getattr(config, "force_point_path", False)
    )

    if use_full_point_path:
        grid_z = np.full((len(grid_y), len(grid_x)), np.nan, dtype=float)
        point_rows, point_cols = np.nonzero(domain_mask)
        # Precompute the LOS barrier mask for the whole domain once (vectorized)
        # instead of re-testing every (cell, well) pair against every barrier
        # segment per point-path pass.
        point_path_blocked = _barrier_blocked_mask(
            grid_x[point_cols],
            grid_y[point_rows],
            well_array[:, 0],
            well_array[:, 1],
            _barrier_segments(active_barriers),
            endpoint_tolerance=config.endpoint_tolerance,
        )
        for cell_index, (row, col) in enumerate(zip(point_rows, point_cols)):
            pt = (float(grid_x[col]), float(grid_y[row]))
            cell_label = int(region_labels[row, col]) if region_labels is not None else -2
            c_dir = -1
            c_s = c_n = c_g = 0.0
            c_ratio = 1.0
            c_tx, c_ty = 1.0, 0.0
            if direction_cache is not None:
                c_dir = int(direction_cache["dir_index"][row, col])
                c_s = float(direction_cache["s"][row, col])
                c_n = float(direction_cache["n"][row, col])
                c_g = float(direction_cache["g"][row, col])
                c_ratio = float(direction_cache["ratio"][row, col])
                c_tx = float(direction_cache["tx"][row, col])
                c_ty = float(direction_cache["ty"][row, col])
            value, blocked_count, used_direction = _interpolate_grid_point(
                pt=pt,
                well_array=well_array,
                barriers=active_barriers,
                directions=resolved_directions,
                config=config,
                density_weights=density_weights,
                cell_label=cell_label,
                well_labels=well_labels,
                cell_dir_index=c_dir,
                cell_s=c_s,
                cell_n=c_n,
                cell_g=c_g,
                cell_ratio=c_ratio,
                cell_tx=c_tx,
                cell_ty=c_ty,
                well_curve_coords=well_curve_coords if well_curve_coords else None,
                direction_geoms=direction_geoms,
                blocked_mask=point_path_blocked,
                cell_index=cell_index,
            )
            diagnostics["被打断线过滤的井点-网格关系数量"] += blocked_count
            diagnostics["blocked_well_grid_relations"] += blocked_count
            if value is None or not math.isfinite(value):
                continue
            if config.value_min is not None:
                value = max(float(config.value_min), value)
            if config.value_max is not None:
                value = min(float(config.value_max), value)
            grid_z[row, col] = value
            if used_direction:
                diagnostics["使用方向距离的网格点数"] += 1
                diagnostics["direction_distance_grid_points"] += 1
            else:
                diagnostics["普通距离网格点数"] += 1
                diagnostics["plain_distance_grid_points"] += 1
    else:
        diagnostics["vectorized_idw"] = 1
        grid_z = interpolate_idw_grid_batch(
            grid_x,
            grid_y,
            well_array,
            domain_mask,
            search_radius=float(config.search_radius),
            power=float(config.power),
            min_points=int(config.min_points),
            max_points=int(config.max_points),
            density_weights=density_weights,
            value_min=config.value_min,
            value_max=config.value_max,
            region_labels=region_labels,
            well_labels=well_labels,
            direction_field=direction_field_for_idw,
            direction_corridor_strength=float(config.direction_corridor_strength),
            direction_perpendicular_strength=float(config.direction_perpendicular_strength),
            use_extended_search=bool(config.use_extended_search),
            limit_search_radius=bool(config.limit_interpolation_to_search_radius),
        )
        # Optional LOS refine only near barriers (small band — keeps UI responsive)
        if active_barriers and near_active_mask is not None:
            refine = domain_mask & np.asarray(near_active_mask, dtype=bool)
            refine_n = int(np.count_nonzero(refine))
            diagnostics["barrier_los_refine_cells"] = refine_n
            if 0 < refine_n < 120000:
                refine_rows, refine_cols = np.nonzero(refine)
                # Precompute the LOS barrier mask for the refine band once
                # (vectorized), instead of re-testing every (cell, well) pair
                # against every barrier segment per refine pass.
                los_blocked = _barrier_blocked_mask(
                    grid_x[refine_cols],
                    grid_y[refine_rows],
                    well_array[:, 0],
                    well_array[:, 1],
                    _barrier_segments(active_barriers),
                    endpoint_tolerance=config.endpoint_tolerance,
                )
                for cell_index, (row, col) in enumerate(zip(refine_rows, refine_cols)):
                    pt = (float(grid_x[col]), float(grid_y[row]))
                    cell_label = int(region_labels[row, col]) if region_labels is not None else -2
                    c_dir = int(direction_cache["dir_index"][row, col]) if direction_cache is not None else -1
                    c_s = float(direction_cache["s"][row, col]) if direction_cache is not None else 0.0
                    c_n = float(direction_cache["n"][row, col]) if direction_cache is not None else 0.0
                    c_g = float(direction_cache["g"][row, col]) if direction_cache is not None else 0.0
                    c_ratio = float(direction_cache["ratio"][row, col]) if direction_cache is not None else 1.0
                    value, blocked_count, _used = _interpolate_grid_point(
                        pt=pt,
                        well_array=well_array,
                        barriers=active_barriers,
                        directions=resolved_directions,
                        config=config,
                        density_weights=density_weights,
                        cell_label=cell_label,
                        well_labels=well_labels,
                        cell_dir_index=c_dir,
                        cell_s=c_s,
                        cell_n=c_n,
                        cell_g=c_g,
                        cell_ratio=c_ratio,
                        well_curve_coords=well_curve_coords if well_curve_coords else None,
                        direction_geoms=direction_geoms,
                        blocked_mask=los_blocked,
                        cell_index=cell_index,
                    )
                    diagnostics["blocked_well_grid_relations"] += blocked_count
                    if value is None or not math.isfinite(value):
                        grid_z[row, col] = np.nan
                        continue
                    if config.value_min is not None:
                        value = max(float(config.value_min), value)
                    if config.value_max is not None:
                        value = min(float(config.value_max), value)
                    grid_z[row, col] = value
            else:
                diagnostics["barrier_los_refine_skipped"] = 1

    # Along-track red-oval stretch: 1D ridge over full polyline start→end.
    # Only when stretch ratio is meaningful (ratio≥2.0); skip near-isotropic ratio≈1.
    max_dir_ratio = 1.0
    along_profiles = None
    if direction_geoms:
        max_dir_ratio = max(float(g.ratio) for g in direction_geoms)
    apply_along_track = (
        direction_cache is not None
        and direction_geoms
        and well_curve_coords
        and use_curve
        and max_dir_ratio >= 2.0
        and bool(config.use_extended_search)
        and float(getattr(config, "along_track_blend_strength", 0.0) or 0.0) > 0.05
    )
    if apply_along_track:
        along_profiles = build_along_track_well_profiles(
            well_array[:, :2],
            well_array[:, 2],
            well_curve_coords,
            direction_geoms,
            min_g=0.10,
        )
        grid_z, at_stats = blend_corridor_along_track(
            grid_z,
            direction_cache,
            direction_geoms,
            along_profiles,
            domain_mask,
            blend_strength=float(getattr(config, "along_track_blend_strength", 0.99)),
            min_cell_g=float(getattr(config, "along_track_min_cell_g", 0.05)),
            exp_k=float(getattr(config, "along_track_exp_k", 6.0)),
        )
        diagnostics["along_track_stretch"] = 1
        diagnostics["along_track_cells"] = int(at_stats.get("along_track_cells", 0))
        diagnostics["along_track_profiles"] = int(at_stats.get("along_track_profiles", 0))
        if config.value_min is not None or config.value_max is not None:
            finite = np.isfinite(grid_z)
            if config.value_min is not None:
                grid_z[finite] = np.maximum(grid_z[finite], float(config.value_min))
            if config.value_max is not None:
                grid_z[finite] = np.minimum(grid_z[finite], float(config.value_max))
    else:
        diagnostics["along_track_stretch"] = 0

    finite_mask = domain_mask & np.isfinite(grid_z)
    diagnostics["有效网格点数"] = int(np.count_nonzero(finite_mask))
    if direction_field_for_idw is not None:
        stretched = direction_field_for_idw[:, :, 2] > (1.0 + 1e-9)
        direction_used = finite_mask & stretched
        diagnostics["使用方向距离的网格点数"] = int(np.count_nonzero(direction_used))
        diagnostics["direction_distance_grid_points"] = diagnostics["使用方向距离的网格点数"]
        diagnostics["普通距离网格点数"] = int(diagnostics["有效网格点数"] - diagnostics["使用方向距离的网格点数"])
        diagnostics["plain_distance_grid_points"] = diagnostics["普通距离网格点数"]

    # 方向线覆盖率诊断（有效网格中受方向拉伸影响的比例）
    valid_grid_points = int(diagnostics["有效网格点数"])
    direction_points = int(diagnostics["使用方向距离的网格点数"])
    coverage_pct = int(round(100.0 * direction_points / valid_grid_points)) if valid_grid_points else 0
    diagnostics["方向线覆盖百分比"] = coverage_pct
    diagnostics["direction_coverage_percent"] = coverage_pct

    # ── 第 4 步：区域内补洞 + 平滑（不跨区域、不跨打断线）──
    # 区域标签负责把域切成独立区，补洞/平滑不跨区；同时恢复不跨打断线的
    # 线段级隔离（配合近线预过滤保性能），未贯穿打断线产生的局部跳变也留痕。
    smoothing_barriers = () if config.smooth_across_barriers else active_barriers
    smoothing_labels = None if config.smooth_across_barriers else region_labels
    smoothing_near_mask = near_active_mask if smoothing_barriers else None

    # 方向场：补洞/BFS 扩散沿方向线切向加权，稀疏区扩散也沿方向拉长
    direction_field = direction_field_for_idw
    if direction_field is None and config.anisotropic_fill and resolved_directions:
        direction_field = build_direction_field(
            grid_x, grid_y, domain_mask, resolved_directions, float(config.direction_taper_plateau)
        )

    gap_iterations = max(0, int(config.gap_fill_iterations))
    data_hull_active = data_hull_mask is not None and bool(np.any(data_hull_mask))
    idw_support_mask = domain_mask & np.isfinite(grid_z)
    bfs_reach_cells = resolve_bfs_reach_cells(
        float(config.search_radius),
        grid_step,
        len(grid_x),
        limit_to_well_coverage=bool(config.limit_interpolation_to_search_radius),
        data_hull_active=data_hull_active,
    )
    gap_fill_domain = build_bfs_reach_mask(idw_support_mask, domain_mask, bfs_reach_cells)
    diagnostics["bfs_reach_cells"] = float(bfs_reach_cells)
    if bool(config.limit_interpolation_to_search_radius):
        gap_iterations = min(gap_iterations, 3 if data_hull_active else 0)
    filled_grid, filled_count = fill_internal_gaps(
        grid_z,
        grid_x,
        grid_y,
        gap_fill_domain,
        gap_iterations,
        config.value_min,
        config.value_max,
        barriers=smoothing_barriers,
        near_barrier_mask=smoothing_near_mask,
        region_labels=smoothing_labels,
        direction_field=direction_field,
    )
    diagnostics["补值网格点数"] = int(filled_count)

    # 限制外推时禁止大范围 BFS，避免从井点边缘向内部无井区扩散。
    skip_bfs_gap_fill = bool(config.limit_interpolation_to_search_radius)
    if skip_bfs_gap_fill:
        extended_count = 0
        diagnostics["bfs_gap_fill_skipped"] = 1
    else:
        filled_grid, extended_count = complete_gap_fill(
            filled_grid,
            gap_fill_domain,
            smoothing_labels,
            config.value_min,
            config.value_max,
            direction_field=direction_field,
            cell_aspect=_grid_aspect(grid_x, grid_y),
            barriers=active_barriers,
            x_coords=grid_x,
            y_coords=grid_y,
            near_barrier_mask=near_active_mask,
            exclusion_mask=blank_mask,
        )
        diagnostics["bfs_gap_fill_skipped"] = 0
    diagnostics["扩展补值网格点数"] = int(extended_count)

    contour_grid = smooth_valid_grid(
        filled_grid,
        grid_x,
        grid_y,
        smoothing_barriers,
        max(0, int(config.grid_smoothing_iterations)),
        near_barrier_mask=smoothing_near_mask,
        region_labels=smoothing_labels,
        direction_field=direction_field,
        direction_strength=float(config.direction_smoothing_strength),
    )
    if bool(config.limit_interpolation_to_search_radius):
        contour_support_mask = build_contour_support_mask(
            idw_support_mask,
            domain_mask,
            dilation_cells=resolve_contour_support_dilation_cells(
                len(grid_x),
                limit_to_well_coverage=True,
            ),
        )
    else:
        contour_support_mask = np.asarray(domain_mask, dtype=bool).copy()
    contour_grid = refine_domain_boundary_transition(
        contour_grid,
        contour_support_mask,
        grid_x,
        grid_y,
        smoothing_barriers,
        near_barrier_mask=smoothing_near_mask,
        region_labels=smoothing_labels,
        feather_cells=4,
        iterations=2,
    )

    contour_grid, anchor_stats = apply_well_residual_anchoring(
        contour_grid,
        grid_x,
        grid_y,
        wells,
        contour_support_mask,
        config,
        region_labels=region_labels,
        well_labels=well_labels,
        direction_field=direction_field,
    )
    diagnostics.update(anchor_stats)

    # Re-apply ridge blend after residual so circular well anchors cannot erase
    # the red-oval full-length corridor.
    if (
        apply_along_track
        and along_profiles
        and direction_cache is not None
        and direction_geoms
    ):
        contour_grid, at2 = blend_corridor_along_track(
            contour_grid,
            direction_cache,
            direction_geoms,
            along_profiles,
            domain_mask,
            # Keep full ridge strength after well anchors so stretch is not washed out
            blend_strength=min(
                1.0,
                float(getattr(config, "along_track_blend_strength", 0.99)),
            ),
            min_cell_g=float(getattr(config, "along_track_min_cell_g", 0.05)),
            exp_k=float(getattr(config, "along_track_exp_k", 6.0)),
        )
        diagnostics["along_track_post_anchor_cells"] = int(at2.get("along_track_cells", 0))
        if config.value_min is not None or config.value_max is not None:
            finite = np.isfinite(contour_grid)
            if config.value_min is not None:
                contour_grid[finite] = np.maximum(contour_grid[finite], float(config.value_min))
            if config.value_max is not None:
                contour_grid[finite] = np.minimum(contour_grid[finite], float(config.value_max))

    # Display support stays tight (finite cells only). Extraction support is a
    # separate dilated component mask that *includes* small interior NaN holes so
    # prepare_contour_extraction_surface can bridge them for closed isolines.
    display_support_mask = np.asarray(contour_support_mask, dtype=bool) & np.isfinite(contour_grid)

    # Display trend surface uses the strict finite support only.
    working_surface = np.array(contour_grid, dtype=float, copy=True)
    working_surface[~np.asarray(domain_mask, dtype=bool)] = np.nan
    contour_support_mask = display_support_mask
    contour_grid = np.array(working_surface, dtype=float, copy=True)
    contour_grid[~contour_support_mask] = np.nan

    # 提取用归 0 前连续面；显示：屏障走廊保持 nodata（本 vendored 副本的唯一
    # 使用方是 paleo-workbench，它以真实因子单位调用并基于本网格自行重导等值线；
    # 上游"绿带 = 0"的归一化显示约定会沿每条断层伪造观测最小值带）。
    extract_base_surface = np.array(contour_grid, dtype=float, copy=True)
    if blank_mask is not None and bool(np.any(blank_mask)) and active_barriers:
        bm = np.asarray(blank_mask, dtype=bool)
        in_boundary = bm & np.asarray(boundary_mask, dtype=bool)
        contour_grid[in_boundary] = np.nan
        diagnostics["barrier_buffer_forced_zero_cells"] = int(np.count_nonzero(in_boundary))
        diagnostics["barrier_buffer_filled_cells"] = int(np.count_nonzero(in_boundary))
        diagnostics["barrier_buffer_fill_value"] = float("nan")
    else:
        diagnostics["barrier_buffer_forced_zero_cells"] = 0
        diagnostics["barrier_buffer_filled_cells"] = 0

    # 仅趋势面：跳过等值线提取/贴边/消交（此前即使 generate_contours=False 也会全做，易卡死）
    if not bool(getattr(config, "extract_contours", True)):
        diagnostics["contour_extraction_skipped"] = 1
        diagnostics["生成等值线条数"] = 0
        return ConstrainedGridResult(
            grid_z=contour_grid,
            grid_x=grid_x,
            grid_y=grid_y,
            contours={},
            diagnostics=diagnostics,
            surface_grid=None,
            surface_x=None,
            surface_y=None,
        )

    component_dilation = resolve_contour_component_dilation_cells(
        len(grid_x),
        limit_to_well_coverage=bool(config.limit_interpolation_to_search_radius),
    )
    contour_component_mask = build_contour_component_mask(
        idw_support_mask,
        domain_mask,
        component_dilation,
    )
    # Cartographic contours should stay in well-controlled components even when
    # the *display* trend surface extends to the formation boundary. Extracting
    # from the full domain produces long messy open isolines in empty north /
    # far-field areas (unlike the Enping reference maps).
    extraction_support_mask = np.asarray(contour_component_mask, dtype=bool)
    extraction_support_mask &= np.asarray(domain_mask, dtype=bool)
    # 仅排除窄核，缓冲带参与提取以便端头外侧连续
    if contour_stop_mask is not None:
        extraction_support_mask = extraction_support_mask & ~np.asarray(
            contour_stop_mask, dtype=bool
        )

    working_surface = np.array(extract_base_surface, dtype=float, copy=True)
    working_surface[~np.asarray(domain_mask, dtype=bool)] = np.nan

    contour_extraction_grid, contour_fill_count = prepare_contour_extraction_surface(
        working_surface,
        extraction_support_mask,
        smoothing_labels,
        config.value_min,
        config.value_max,
        direction_field=direction_field,
        cell_aspect=_grid_aspect(grid_x, grid_y),
        barriers=active_barriers,
        x_coords=grid_x,
        y_coords=grid_y,
        near_barrier_mask=near_active_mask,
        exclusion_mask=contour_stop_mask,
    )
    # Mild directional smooth on extraction surface — continuous isolines without
    # isotropic rounding that undoes long-axis stretch.
    _extract_smooth_iters = max(2, min(4, int(config.grid_smoothing_iterations) + 1))
    contour_extraction_grid = smooth_valid_grid(
        contour_extraction_grid,
        grid_x,
        grid_y,
        () if config.smooth_across_barriers else active_barriers,
        iterations=_extract_smooth_iters,
        near_barrier_mask=None if config.smooth_across_barriers else near_active_mask,
        region_labels=None if config.smooth_across_barriers else smoothing_labels,
        direction_field=direction_field if direction_field is not None else None,
        direction_strength=float(config.direction_smoothing_strength) if direction_field is not None else 0.0,
    )
    diagnostics["contour_component_fill_points"] = int(contour_fill_count)
    diagnostics["contour_extraction_support_cells"] = int(np.count_nonzero(extraction_support_mask))
    diagnostics["contour_component_dilation_cells"] = float(component_dilation)
    diagnostics["contour_extraction_isotropic_smooth"] = 0
    diagnostics["contour_extraction_directional_smooth"] = 1 if direction_field is not None else 0
    diagnostics["contour_extraction_skipped"] = 0

    # ── 第 5 步：混合等值线 ──
    # 1) 传统分区 MS：恢复区域梯度、贴成图边界的开放弧、打断线附近连续线
    # 2) 高值连通域闭合环：井区高峰的嵌套套圈（绿线目标）
    # 二者合并；绝不使用 closed-only 过滤把开放等值线整批删掉。
    contour_region_labels = region_labels if active_barriers else None
    postprocess_barriers = active_barriers if active_barriers else ()
    approx_step = max(
        abs(float(grid_x[-1] - grid_x[0])) / max(len(grid_x) - 1, 1),
        abs(float(grid_y[-1] - grid_y[0])) / max(len(grid_y) - 1, 1),
        1e-9,
    )
    upsample_factor = int(config.contour_upsample_factor)
    if upsample_factor <= 0:
        upsample_factor = 3
    smoothing_iterations = int(config.contour_smoothing_iterations)
    if smoothing_iterations < 0:
        smoothing_iterations = 2

    # Prefer the hole-filled extraction surface for continuous MS isolines;
    # fall back to the display surface if extraction prep was skipped.
    line_source = np.array(contour_extraction_grid, dtype=float, copy=True)
    # 等值线提取：仅窄核 nan；全缓冲禁入/绕端头在 route 后处理
    if contour_stop_mask is not None and bool(np.any(contour_stop_mask)):
        line_source[np.asarray(contour_stop_mask, dtype=bool)] = np.nan
    # Pre-MS surface smooth: more continuous isolines, less MS stair-steps.
    # Keep direction field when present so long-axis morphology is preserved.
    _line_smooth_iters = max(2, min(4, int(config.grid_smoothing_iterations) + 1))
    line_source = smooth_valid_grid(
        line_source,
        grid_x,
        grid_y,
        () if config.smooth_across_barriers else active_barriers,
        iterations=_line_smooth_iters,
        near_barrier_mask=None if config.smooth_across_barriers else near_active_mask,
        region_labels=None if config.smooth_across_barriers else smoothing_labels,
        direction_field=direction_field if direction_field is not None else None,
        direction_strength=(
            float(config.direction_smoothing_strength) if direction_field is not None else 0.0
        ),
    )
    # 平滑后再次清空窄核
    if contour_stop_mask is not None and bool(np.any(contour_stop_mask)):
        line_source[np.asarray(contour_stop_mask, dtype=bool)] = np.nan
    contour_grid_for_lines, contour_x, contour_y, surface_labels = _upsample_contour_surface(
        line_source,
        grid_x,
        grid_y,
        contour_region_labels,
        max(1, upsample_factor),
    )
    line_support = np.isfinite(np.asarray(line_source, dtype=float)) & np.asarray(
        domain_mask, dtype=bool
    )
    if contour_stop_mask is not None:
        line_support = line_support & ~np.asarray(contour_stop_mask, dtype=bool)
    if upsample_factor > 1:
        from drawing.single_factor.fast_grid import upsample_mask_nearest

        up_support = upsample_mask_nearest(line_support, upsample_factor)
        contour_grid_for_lines = np.array(contour_grid_for_lines, dtype=float, copy=True)
        contour_grid_for_lines[~np.asarray(up_support, dtype=bool)] = np.nan
    else:
        contour_grid_for_lines = np.array(contour_grid_for_lines, dtype=float, copy=True)
        contour_grid_for_lines[~line_support] = np.nan

    partition_labels = surface_labels if contour_region_labels is not None else None

    # A) Traditional partition-aware marching squares (open + closed).
    # 传入打断线：等值线强制止于打断线，不得穿越
    # 缓冲带已在 line_source 上 nan；MS 不再做每格几何相交（极慢）
    ms_barriers = ()
    ms_contours = masked_marching_squares(
        contour_grid_for_lines,
        contour_x,
        contour_y,
        levels,
        barriers=ms_barriers,
        region_labels=partition_labels,
    )
    # B) Peak-seeded closed high rings (nested bullseyes MS often leaves open).
    ring_contours = extract_closed_high_rings(
        contour_grid_for_lines,
        contour_x,
        contour_y,
        levels,
        region_labels=partition_labels,
        min_cells=max(6, int(upsample_factor) * 3),
    )
    contours, merge_stats = _merge_hybrid_contours(
        ms_contours,
        ring_contours,
        approx_step,
    )

    # Strictly drop segments outside the finite extraction surface.
    # min_segment_points=2 keeps valid straight isolines (RDP may leave 2 verts).
    contours, _clip_stats = clip_contours_to_finite_surface(
        contours,
        contour_grid_for_lines,
        contour_x,
        contour_y,
        levels=levels,
        min_segment_points=2,
    )
    # Re-close nicked near-closed loops after clip. Pass barrier buffer width so
    # ends sitting just outside the blank corridor still count as "near barrier".
    early_barrier_proximity = (
        max(float(contour_buffer_distance), approx_step * 4.0) if postprocess_barriers else 0.0
    )
    contours, _ = finalize_contour_loop_closure(
        contours,
        contour_grid_for_lines,
        contour_x,
        contour_y,
        approx_step,
        barriers=postprocess_barriers,
        barrier_proximity=early_barrier_proximity,
    )
    # Cartographic smooth / simplify / same-level bridge. Bridge is in map units;
    # plausibility + barrier checks prevent long false diagonals.
    bridge_gap = max(0.0, float(config.contour_bridge_gap))
    if bridge_gap <= 0.0:
        bridge_gap = approx_step * 1.5
    post_cfg = ConstrainedIDWConfig(
        contour_smoothing_iterations=max(1, min(3, int(smoothing_iterations))),
        contour_simplify_tolerance=max(
            0.0,
            float(config.contour_simplify_tolerance)
            if float(config.contour_simplify_tolerance) >= 0
            else approx_step * 0.08,
        ),
        contour_bridge_gap=min(max(bridge_gap, approx_step * 1.25), approx_step * 2.25),
        min_contour_length=max(0.0, float(config.min_contour_length)),
    )
    contours, post_stats = postprocess_contours(
        contours,
        contour_x,
        contour_y,
        post_cfg,
        barriers=postprocess_barriers,
        surface_grid=contour_grid_for_lines,
        directions=(),  # 内部生成路径主要靠插值阶段的 direction_field 实现对齐；独立提取会传方向快照
    )
    diagnostics["contour_extraction_method"] = "hybrid_ms_plus_closed_rings"
    diagnostics["contour_upsample_factor"] = int(max(1, upsample_factor))
    diagnostics["contour_extraction_surface_continuous"] = 1
    diagnostics["contour_extraction_region_masked"] = 1 if contour_region_labels is not None else 0
    diagnostics["ms_contour_polylines"] = int(merge_stats.get("ms_count", 0))
    diagnostics["closed_high_ring_polylines"] = int(merge_stats.get("ring_kept", 0))
    diagnostics["hybrid_ring_skipped_duplicate"] = int(merge_stats.get("ring_skipped", 0))
    diagnostics["closed_only_filter"] = 0
    diagnostics["生成等值线条数"] = int(sum(len(v) for v in contours.values()))
    for key, value in post_stats.items():
        diagnostics[key] = int(value)
    diagnostics["barrier_extend_applied"] = int(bool(config.barrier_extend_to_boundary))

    # 禁入缓冲 + 外缘/端头绕过（用户标注：绕过，缓冲区也不能进去）
    raw_buf = float(contour_buffer_distance) if postprocess_barriers else 0.0
    barrier_proximity = max(raw_buf * 1.1, approx_step * 3.0) if postprocess_barriers else 0.0
    if active_barriers and postprocess_barriers:
        contours, trimmed = trim_contours_at_barrier_buffers(
            contours,
            postprocess_barriers,
            max(raw_buf, approx_step * 2.0),
            approx_step,
        )
        contours, cut = enforce_no_barrier_crossing(
            contours, postprocess_barriers, approx_step
        )
        diagnostics["trimmed_barrier_contour_segments"] = int(trimmed)
        diagnostics["cut_barrier_crossings"] = int(cut)
        diagnostics["barrier_edge_stitched"] = 0
        diagnostics["barrier_edge_hugged_ends"] = 0
        diagnostics["edge_joined_contours"] = 0
        diagnostics["removed_barrier_artifact_contours"] = 0
        diagnostics["finalized_closed_contours"] = 0
        diagnostics["barrier_seal_proximity"] = float(barrier_proximity)
        diagnostics["barrier_hard_stop"] = 1
        diagnostics["barrier_detour_mode"] = 0
    else:
        # 无打断线时，仍允许沿域边缘续接断裂等值线
        contours, edge_joined = connect_open_contours_along_surface_edge(
            contours,
            contour_grid_for_lines,
            contour_x,
            contour_y,
            barriers=(),
            grid_step=approx_step,
            buffer_distance=0.0,
        )
        diagnostics["edge_joined_contours"] = int(edge_joined)
        diagnostics["barrier_edge_hugged_ends"] = 0
        diagnostics["trimmed_barrier_contour_segments"] = 0
        diagnostics["finalized_closed_contours"] = 0
        diagnostics["barrier_seal_proximity"] = 0.0
        diagnostics["removed_barrier_artifact_contours"] = 0
        diagnostics["barrier_hard_stop"] = 0

    # Drop tiny scraps only — never wipe all open regional isolines.
    # 贴打断线的开放段放宽保留，避免区域等值线（如 80）被误删成碎断
    contours, prune_stats = prune_messy_contour_fragments(
        contours,
        approx_step,
        min_open_length=max(float(config.min_contour_length) * 1.0, approx_step * 8.0),
        min_closed_length=max(float(config.min_contour_length) * 0.4, approx_step * 3.0),
        barriers=postprocess_barriers if postprocess_barriers else (),
        barrier_keep_proximity=(
            max(float(contour_buffer_distance) * 1.4, approx_step * 3.0)
            if postprocess_barriers
            else 0.0
        ),
    )
    diagnostics["pruned_short_open_contours"] = int(prune_stats.get("pruned_open", 0))
    diagnostics["pruned_short_closed_contours"] = int(prune_stats.get("pruned_closed", 0))

    # 贴边/桥接/延伸后：最小间距 + 不得相交 + 不得穿打断线（硬约束）
    min_spacing = float(getattr(config, "min_contour_spacing", 0.0) or 0.0)
    contours, topo_stats = apply_contour_topology_constraints(
        contours,
        approx_step,
        min_spacing=min_spacing,
        enforce_no_crossing=bool(getattr(config, "enforce_no_crossing", True)),
        fast=True,
        barriers=postprocess_barriers if postprocess_barriers else (),
    )
    diagnostics["fixed_contour_crossings"] = int(
        int(diagnostics.get("fixed_contour_crossings", 0) or 0)
        + int(topo_stats.get("fixed_contour_crossings", 0))
    )
    diagnostics["removed_dense_contours"] = int(topo_stats.get("removed_dense_contours", 0))
    diagnostics["min_contour_spacing_m"] = int(topo_stats.get("min_contour_spacing_m", 0))
    # 绝对终态：再平滑 + 禁入缓冲 + 写死不相交（之后不得再改几何）
    contours, hard_stats = finalize_contours_hard_no_cross(
        contours,
        approx_step,
        barriers=postprocess_barriers if postprocess_barriers else (),
        buffer_distance=max(float(contour_buffer_distance), approx_step * 2.0)
        if postprocess_barriers
        else 0.0,
        smooth_iterations=3,
        enforce_no_crossing=bool(getattr(config, "enforce_no_crossing", True)),
        surface_grid=contour_grid_for_lines,
        surface_x=contour_x,
        surface_y=contour_y,
    )
    diagnostics["fixed_contour_crossings"] = int(
        int(diagnostics.get("fixed_contour_crossings", 0) or 0)
        + int(hard_stats.get("fixed_contour_crossings", 0))
    )
    # When well-coverage is limited, re-clip isolines to the *display* trend
    # surface so dilated extraction support cannot leak into empty far-field.
    if bool(config.limit_interpolation_to_search_radius):
        contours, disp_clip = clip_contours_to_finite_surface(
            contours,
            contour_grid,
            grid_x,
            grid_y,
            levels=levels,
            min_segment_points=2,
        )
        diagnostics["display_support_clipped_segments"] = int(
            disp_clip.get("clipped_contour_segments", 0) if isinstance(disp_clip, dict) else 0
        )
    # Cropping/crossing repair can leave new interior scraps. Clean them once at
    # the true end of the pipeline while preserving arcs that terminate at a
    # barrier buffer.
    contours, final_prune = prune_messy_contour_fragments(
        contours,
        approx_step,
        min_open_length=max(float(config.min_contour_length), approx_step * 10.0),
        min_closed_length=max(float(config.min_contour_length) * 0.4, approx_step * 3.5),
        barriers=postprocess_barriers if postprocess_barriers else (),
        barrier_keep_proximity=(
            max(float(contour_buffer_distance) * 1.4, approx_step * 3.0)
            if postprocess_barriers
            else 0.0
        ),
    )
    diagnostics["final_pruned_open_contours"] = int(final_prune.get("pruned_open", 0))
    diagnostics["final_pruned_closed_contours"] = int(final_prune.get("pruned_closed", 0))
    diagnostics["kept_contour_polylines"] = int(sum(len(v) for v in contours.values()))
    diagnostics["生成等值线条数"] = int(sum(len(v) for v in contours.values()))
    return ConstrainedGridResult(
        grid_z=contour_grid,
        grid_x=grid_x,
        grid_y=grid_y,
        contours=contours,
        diagnostics=diagnostics,
        surface_grid=contour_grid_for_lines,
        surface_x=contour_x,
        surface_y=contour_y,
    )


def _point_in_interpolation_mask(
    pt: PointTuple,
    mask_well_array: np.ndarray,
    directions: Sequence[DirectionLine],
    mask_radius: float,
) -> bool:
    if mask_radius is None or float(mask_radius) <= 0:
        return True
    if mask_well_array.size == 0:
        return True
    direction = nearest_direction_context(pt, directions)
    if direction is None:
        dx = mask_well_array[:, 0] - pt[0]
        dy = mask_well_array[:, 1] - pt[1]
        return bool(np.any(dx * dx + dy * dy <= float(mask_radius) * float(mask_radius)))

    unit_x, unit_y, ratio = direction
    for well_x, well_y in mask_well_array:
        if anisotropic_distance(pt, (float(well_x), float(well_y)), unit_x, unit_y, ratio) <= float(mask_radius):
            return True
    return False


def _build_grid_axes(
    boundaries: Sequence[BoundaryPolygon],
    resolution: int,
    margin_ratio: float,
) -> Tuple[np.ndarray, np.ndarray]:
    points = [pt for boundary in boundaries for pt in boundary.exterior]
    if not points:
        raise ValueError("边界面缺少有效顶点")
    xs = np.asarray([p[0] for p in points], dtype=float)
    ys = np.asarray([p[1] for p in points], dtype=float)
    span = max(float(xs.max() - xs.min()), float(ys.max() - ys.min()), 1.0)
    margin = span * max(0.0, float(margin_ratio))
    return (
        np.linspace(float(xs.min() - margin), float(xs.max() + margin), resolution),
        np.linspace(float(ys.min() - margin), float(ys.max() + margin), resolution),
    )


def compute_declustering_weights(
    points: np.ndarray,
    radius: float,
    strength: float,
) -> np.ndarray:
    """Down-weight dense well clusters so they do not dominate the interpolated surface."""
    if points.size == 0:
        return np.asarray([], dtype=float)
    if radius <= 0.0 or strength <= 0.0 or len(points) <= 1:
        return np.ones(len(points), dtype=float)

    xy = np.asarray(points, dtype=float)
    dx = xy[:, 0][:, None] - xy[:, 0][None, :]
    dy = xy[:, 1][:, None] - xy[:, 1][None, :]
    dist_sq = dx * dx + dy * dy
    radius_sq = float(radius) * float(radius)
    local_counts = np.count_nonzero(dist_sq <= radius_sq, axis=1).astype(float)
    local_counts = np.maximum(local_counts, 1.0)
    weights = 1.0 / np.power(local_counts, float(strength))
    mean_weight = float(np.mean(weights))
    if mean_weight > 0:
        weights = weights / mean_weight
    return weights


def summarize_point_density(points: np.ndarray, radius: float) -> Dict[str, int]:
    if points.size == 0 or radius <= 0.0:
        return {"孤立井点数": 0, "密集井点数": 0}
    xy = np.asarray(points, dtype=float)
    dx = xy[:, 0][:, None] - xy[:, 0][None, :]
    dy = xy[:, 1][:, None] - xy[:, 1][None, :]
    local_counts = np.count_nonzero(dx * dx + dy * dy <= float(radius) * float(radius), axis=1)
    return {
        "孤立井点数": int(np.count_nonzero(local_counts <= 1)),
        "密集井点数": int(np.count_nonzero(local_counts >= 5)),
    }


def _interpolate_grid_point_euclidean(
    pt: PointTuple,
    well_array: np.ndarray,
    barriers: Sequence[BarrierLine],
    config: ConstrainedIDWConfig,
    density_weights: np.ndarray,
    euclidean: np.ndarray,
    *,
    cell_label: int = -2,
    well_labels: Optional[np.ndarray] = None,
    blocked_mask: Optional[np.ndarray] = None,
    cell_index: int = -1,
) -> Tuple[Optional[float], int, bool]:
    """Vectorized well-candidate selection for the pure-Euclidean IDW case.

    Bit-for-bit equivalent to the scalar pass loop in :func:`_interpolate_grid_point`
    when no direction context applies (``use_curve`` and legacy fixed-angle
    distances both off): same label / barrier LOS filters, same radius-pass
    candidate accumulation, same stable sort by distance, same top-k weighting.
    Returns ``(value, blocked_well_count, used_direction=False)``.
    """
    n_wells = len(well_array)
    blocked_wells = np.zeros(n_wells, dtype=bool)
    if well_labels is not None and cell_label >= 0:
        wl = np.asarray(well_labels, dtype=int)
        blocked_wells |= (wl >= 0) & (wl != int(cell_label))
    if barriers:
        if blocked_mask is not None and cell_index >= 0:
            blocked_wells |= np.asarray(blocked_mask[cell_index, :], dtype=bool)
        else:
            for idx in range(n_wells):
                if is_blocked_by_barrier(
                    pt,
                    (float(well_array[idx, 0]), float(well_array[idx, 1])),
                    barriers,
                    config.endpoint_tolerance,
                ):
                    blocked_wells[idx] = True
    n_blocked = int(blocked_wells.sum())

    base_radius = max(float(config.search_radius), 1e-9)
    radius_scales = (
        (1.0,)
        if bool(config.limit_interpolation_to_search_radius)
        else (1.0, 1.5, 2.25, 3.0)
    )
    candidate_mask = np.zeros(n_wells, dtype=bool)
    required_points = max(1, int(config.min_points))
    for pass_index, radius_scale in enumerate(radius_scales):
        r_pass = base_radius * radius_scale
        candidate_mask |= (~blocked_wells) & (euclidean <= r_pass)
        required_points = max(1, int(config.min_points) - pass_index)
        if int(candidate_mask.sum()) >= required_points:
            break
    if int(candidate_mask.sum()) < required_points:
        return None, n_blocked, False

    cand_idx = np.nonzero(candidate_mask)[0]
    # Stable sort by distance — matches the scalar list.sort(key=item[0]).
    order = np.argsort(euclidean[cand_idx], kind="stable")
    selected = cand_idx[order[: max(1, int(config.max_points))]]
    dists = euclidean[selected]
    values = np.asarray(well_array[selected, 2], dtype=float)
    if density_weights.size:
        decluster = np.asarray(density_weights[selected], dtype=float)
    else:
        decluster = np.ones_like(dists)
    weights = decluster / np.power(np.maximum(dists, 1e-9), float(config.power))
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        return None, n_blocked, False
    return float(np.sum(weights * values) / weight_sum), n_blocked, False


def _interpolate_grid_point_curve(
    pt: PointTuple,
    well_array: np.ndarray,
    barriers: Sequence[BarrierLine],
    config: ConstrainedIDWConfig,
    density_weights: np.ndarray,
    euclidean: np.ndarray,
    candidate_distances: np.ndarray,
    direction_weight_factors: np.ndarray,
    g_pair: np.ndarray,
    *,
    cell_label: int = -2,
    well_labels: Optional[np.ndarray] = None,
    cell_dir_index: int = -1,
    cell_s: float = 0.0,
    cell_n: float = 0.0,
    cell_ratio: float = 1.0,
    well_curve_coords: Dict[int, Dict[str, np.ndarray]],
    blocked_mask: Optional[np.ndarray] = None,
    cell_index: int = -1,
) -> Tuple[Optional[float], int, bool]:
    """Vectorized curve-corridor candidate selection (same semantics as the scalar loop)."""
    from drawing.single_factor.direction_corridor import pairs_in_search_neighborhood

    n_wells = len(well_array)
    blocked_wells = np.zeros(n_wells, dtype=bool)
    if well_labels is not None and cell_label >= 0:
        wl = np.asarray(well_labels, dtype=int)
        blocked_wells |= (wl >= 0) & (wl != int(cell_label))
    if barriers:
        if blocked_mask is not None and cell_index >= 0:
            blocked_wells |= np.asarray(blocked_mask[cell_index, :], dtype=bool)
        else:
            for idx in range(n_wells):
                if is_blocked_by_barrier(
                    pt,
                    (float(well_array[idx, 0]), float(well_array[idx, 1])),
                    barriers,
                    config.endpoint_tolerance,
                ):
                    blocked_wells[idx] = True
    n_blocked = int(blocked_wells.sum())

    base_radius = max(float(config.search_radius), 1e-9)
    radius_scales = (
        (1.0,)
        if bool(config.limit_interpolation_to_search_radius)
        else (1.0, 1.5, 2.25, 3.0)
    )
    candidate_mask = np.zeros(n_wells, dtype=bool)
    required_points = max(1, int(config.min_points))
    for pass_index, radius_scale in enumerate(radius_scales):
        r_pass = base_radius * radius_scale
        in_nbhd = pairs_in_search_neighborhood(
            euclidean=euclidean,
            d_eff=candidate_distances,
            g_pair=g_pair,
            cell_s=float(cell_s),
            cell_n=float(cell_n),
            cell_ratio=float(cell_ratio),
            cell_dir=int(cell_dir_index),
            well_coords=well_curve_coords,
            base_radius=r_pass,
            use_extended_search=bool(config.use_extended_search),
        )
        candidate_mask = (~blocked_wells) & np.asarray(in_nbhd, dtype=bool)
        required_points = max(1, int(config.min_points) - pass_index)
        if int(candidate_mask.sum()) >= required_points:
            break

    exact = candidate_mask & (candidate_distances <= 1e-9)
    if bool(exact.any()):
        idx = int(np.flatnonzero(exact)[0])
        return float(well_array[idx, 2]), n_blocked, True
    if int(candidate_mask.sum()) < required_points:
        return None, n_blocked, True

    cand_idx = np.nonzero(candidate_mask)[0]
    order = np.argsort(candidate_distances[cand_idx], kind="stable")
    selected = cand_idx[order[: max(1, int(config.max_points))]]
    dists = np.asarray(candidate_distances[selected], dtype=float)
    values = np.asarray(well_array[selected, 2], dtype=float)
    if density_weights.size:
        decluster = np.asarray(density_weights[selected], dtype=float)
    else:
        decluster = np.ones_like(dists)
    decluster = decluster * np.asarray(direction_weight_factors[selected], dtype=float)
    weights = decluster / np.power(np.maximum(dists, 1e-9), float(config.power))
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        return None, n_blocked, True
    return float(np.sum(weights * values) / weight_sum), n_blocked, True


def _interpolate_grid_point(
    pt: PointTuple,
    well_array: np.ndarray,
    barriers: Sequence[BarrierLine],
    directions: Sequence[DirectionLine],
    config: ConstrainedIDWConfig,
    density_weights: np.ndarray,
    cell_label: int = -2,
    well_labels: Optional[np.ndarray] = None,
    *,
    cell_dir_index: int = -1,
    cell_s: float = 0.0,
    cell_n: float = 0.0,
    cell_g: float = 0.0,
    cell_ratio: float = 1.0,
    cell_tx: float = 1.0,
    cell_ty: float = 0.0,
    well_curve_coords: Optional[Dict[int, Dict[str, np.ndarray]]] = None,
    direction_geoms: Optional[Sequence[object]] = None,
    blocked_mask: Optional[np.ndarray] = None,
    cell_index: int = -1,
) -> Tuple[Optional[float], int, bool]:
    """返回 (插值结果, 被打断线过滤的井点数量, 是否使用了方向距离)。

    cell_label / well_labels 用于分区插值：只有与网格点同区域
    （或标号 -2 = 全局参与）的井才作为候选。

    When curve-corridor caches are provided (cell_dir_index / well_curve_coords),
    distances use blended curve coordinates so stretch follows bent direction
    polylines and search neighborhoods elongate along-axis.
    """
    from drawing.single_factor.direction_corridor import pairs_effective_distance

    dx = well_array[:, 0] - pt[0]
    dy = well_array[:, 1] - pt[1]
    euclidean = np.sqrt(dx * dx + dy * dy)

    exact = np.where(euclidean <= 1e-9)[0]
    if exact.size:
        return float(well_array[int(exact[0]), 2]), 0, False

    use_curve = (
        bool(getattr(config, "use_curve_direction_distance", True))
        and well_curve_coords is not None
        and int(cell_dir_index) >= 0
        and float(cell_g) > 1e-9
    )

    direction_weight_factors = np.ones(len(well_array), dtype=float)
    candidate_distances = euclidean.copy()
    used_direction = False
    curve_g_pair: Optional[np.ndarray] = None

    if use_curve:
        used_direction = True
        geoms = direction_geoms or ()
        d_eff, curve_g_pair = pairs_effective_distance(
            euclidean=euclidean,
            cell_dir=int(cell_dir_index),
            cell_s=float(cell_s),
            cell_n=float(cell_n),
            cell_g=float(cell_g),
            cell_ratio=float(cell_ratio),
            well_coords=well_curve_coords,
            geoms=geoms,
        )
        candidate_distances = d_eff
        boost = curve_g_pair > 1e-9
        direction_weight_factors[boost] = 1.0 + float(
            config.direction_corridor_strength
        ) * 0.35 * curve_g_pair[boost]
    else:
        # Legacy fixed-angle anisotropic distance (compatibility path)
        direction = nearest_direction_context(pt, directions, float(config.direction_taper_plateau))
        used_direction = direction is not None
        if direction is not None:
            unit_x, unit_y, ratio = direction
            perpendicular_scale = direction_perpendicular_scale(
                ratio,
                float(config.direction_perpendicular_strength),
            )
            candidate_distances = np.asarray(
                [
                    anisotropic_distance(
                        pt,
                        (float(x), float(y)),
                        unit_x,
                        unit_y,
                        ratio,
                        perpendicular_scale=perpendicular_scale,
                    )
                    for x, y in well_array[:, :2]
                ],
                dtype=float,
            )
            direction_weight_factors = np.asarray(
                [
                    direction_corridor_weight(
                        float(x) - pt[0],
                        float(y) - pt[1],
                        unit_x,
                        unit_y,
                        ratio,
                        base_radius=max(float(config.search_radius), 1e-9),
                        strength=float(config.direction_corridor_strength),
                    )
                    for x, y in well_array[:, :2]
                ],
                dtype=float,
            )

    weighted_candidates: List[Tuple[float, float, float]] = []
    blocked_indices = set()
    required_points = max(1, int(config.min_points))
    base_radius = max(float(config.search_radius), 1e-9)
    radius_scales = (1.0,) if bool(config.limit_interpolation_to_search_radius) else (1.0, 1.5, 2.25, 3.0)
    # Fast path: no direction context — pure Euclidean candidates with the
    # whole well loop vectorized (identical semantics to the scalar loop).
    if not use_curve and not used_direction:
        return _interpolate_grid_point_euclidean(
            pt,
            well_array,
            barriers,
            config,
            density_weights,
            euclidean,
            cell_label=cell_label,
            well_labels=well_labels,
            blocked_mask=blocked_mask,
            cell_index=cell_index,
        )
    if use_curve:
        return _interpolate_grid_point_curve(
            pt,
            well_array,
            barriers,
            config,
            density_weights,
            euclidean,
            candidate_distances,
            direction_weight_factors,
            curve_g_pair if curve_g_pair is not None else np.zeros(len(well_array)),
            cell_label=cell_label,
            well_labels=well_labels,
            cell_dir_index=int(cell_dir_index),
            cell_s=float(cell_s),
            cell_n=float(cell_n),
            cell_ratio=float(cell_ratio),
            well_curve_coords=well_curve_coords or {},
            blocked_mask=blocked_mask,
            cell_index=cell_index,
        )
    for pass_index, radius_scale in enumerate(radius_scales):
        r_pass = base_radius * radius_scale
        weighted_candidates = []
        for idx in range(len(well_array)):
            # 分区插值：跨区域的井不参与（计入打断线过滤诊断）
            if well_labels is not None and cell_label >= 0:
                well_label = int(well_labels[int(idx)])
                if well_label >= 0 and well_label != cell_label:
                    blocked_indices.add(int(idx))
                    continue
            well_pt = (float(well_array[idx, 0]), float(well_array[idx, 1]))
            # Hard barrier LOS filter at trend-surface stage.  A precomputed
            # vectorized mask (see _barrier_blocked_mask) replaces the
            # per-(cell, well) segment loop on the hot LOS refine path.
            if barriers:
                if blocked_mask is not None and cell_index >= 0:
                    blocked_flag = bool(blocked_mask[cell_index, idx])
                else:
                    blocked_flag = is_blocked_by_barrier(
                        pt, well_pt, barriers, config.endpoint_tolerance
                    )
                if blocked_flag:
                    blocked_indices.add(int(idx))
                    continue

            filter_d = float(candidate_distances[idx]) if config.use_extended_search else float(euclidean[idx])
            if filter_d > r_pass:
                continue
            dist = float(candidate_distances[idx]) if used_direction else float(euclidean[idx])

            if dist <= 1e-9:
                return float(well_array[idx, 2]), len(blocked_indices), used_direction
            density_weight = float(density_weights[int(idx)]) if density_weights.size else 1.0
            direction_weight = float(direction_weight_factors[int(idx)])
            weighted_candidates.append((dist, float(well_array[idx, 2]), density_weight * direction_weight))

        required_points = max(1, int(config.min_points) - pass_index)
        if len(weighted_candidates) >= required_points:
            break

    if len(weighted_candidates) < required_points:
        return None, len(blocked_indices), used_direction

    weighted_candidates.sort(key=lambda item: item[0])
    selected = weighted_candidates[: max(1, int(config.max_points))]
    distances = np.asarray([item[0] for item in selected], dtype=float)
    values = np.asarray([item[1] for item in selected], dtype=float)
    decluster = np.asarray([item[2] for item in selected], dtype=float)
    weights = decluster / np.power(np.maximum(distances, 1e-9), float(config.power))
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        return None, len(blocked_indices), used_direction
    return float(np.sum(weights * values) / weight_sum), len(blocked_indices), used_direction


def point_in_boundary(pt: PointTuple, boundary: BoundaryPolygon) -> bool:
    if not point_in_ring(pt, boundary.exterior):
        return False
    return not any(point_in_ring(pt, hole) for hole in boundary.holes)


def point_in_ring(pt: PointTuple, ring: Sequence[PointTuple]) -> bool:
    if len(ring) < 3:
        return False
    if any(point_on_segment(pt, ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))):
        return True

    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            denom = yj - yi
            if abs(denom) > 1e-30:
                x_intersect = (xj - xi) * (y - yi) / denom + xi
                if x < x_intersect:
                    inside = not inside
        j = i
    return inside


def point_on_segment(pt: PointTuple, a: PointTuple, b: PointTuple, tol: float = 1e-9) -> bool:
    px, py = pt
    ax, ay = a
    bx, by = b
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > tol:
        return False
    dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
    return dot <= tol


def is_blocked_by_barrier(
    a: PointTuple,
    b: PointTuple,
    barriers: Sequence[BarrierLine],
    endpoint_tolerance: float = 1e-7,
) -> bool:
    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            if strict_segments_intersect(a, b, p0, p1, endpoint_tolerance):
                return True
    return False


def _barrier_segments(
    barriers: Sequence[BarrierLine],
) -> List[Tuple[PointTuple, PointTuple]]:
    """Flatten all active barrier polylines into segment pairs."""
    out: List[Tuple[PointTuple, PointTuple]] = []
    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            out.append((p0, p1))
    return out


def _barrier_blocked_mask(
    cell_x: np.ndarray,
    cell_y: np.ndarray,
    well_x: np.ndarray,
    well_y: np.ndarray,
    barrier_segments: Sequence[Tuple[PointTuple, PointTuple]],
    endpoint_tolerance: float = 1e-7,
) -> np.ndarray:
    """Vectorized LOS barrier mask: ``blocked[c, w]`` == segment c→w crosses a barrier.

    Bit-for-bit equivalent to the reference ``is_blocked_by_barrier`` /
    ``strict_segments_intersect`` loop (same per-element float operations, same
    parallel / collinear branch semantics), evaluated with NumPy per segment.
    Cells are processed in chunks bounded by an element budget so peak memory
    stays flat as the well count grows.
    """
    n_cells = int(np.size(cell_x))
    n_wells = int(np.size(well_x))
    blocked = np.zeros((n_cells, n_wells), dtype=bool)
    if n_cells == 0 or n_wells == 0 or not barrier_segments:
        return blocked
    cell_x = np.asarray(cell_x, dtype=float)
    cell_y = np.asarray(cell_y, dtype=float)
    well_x = np.asarray(well_x, dtype=float)
    well_y = np.asarray(well_y, dtype=float)
    tol = float(endpoint_tolerance)
    # Element budget (cells x wells) per chunk.
    chunk = max(1, 4_000_000 // max(1, n_wells))
    for start in range(0, n_cells, chunk):
        stop = min(start + chunk, n_cells)
        ax = cell_x[start:stop, None]
        ay = cell_y[start:stop, None]
        bx = well_x[None, :]
        by = well_y[None, :]
        # (cell → well) offsets — identical for every segment.
        rx = bx - ax
        ry = by - ay
        chunk_blocked = np.zeros((stop - start, n_wells), dtype=bool)
        for (c, d) in barrier_segments:
            cx, cy = c
            dx, dy = d
            sx = dx - cx
            sy = dy - cy
            denom = rx * sy - ry * sx
            qpx = cx - ax
            qpy = cy - ay
            # General crossing case: segment (c, d) pierces the (cell → well)
            # segment iff the intersection parameters fall inside both spans.
            # Parallel pairs divide by zero here; their crossing condition is
            # False and the collinear branch below handles them exactly.
            with np.errstate(divide="ignore", invalid="ignore"):
                num_t = qpx * sy - qpy * sx
                t = num_t / denom
                u = (qpx * ry - qpy * rx) / denom
            crossing = (
                (tol < t) & (t < 1.0 - tol)
                & (-tol <= u) & (u <= 1.0 + tol)
            )
            # Collinear segment-on-segment case (measure-zero for real data;
            # only evaluated when some pair is exactly parallel).
            if (np.abs(denom) <= 1e-12).any():
                rr = rx * rx + ry * ry
                with np.errstate(divide="ignore", invalid="ignore"):
                    t0 = (qpx * rx + qpy * ry) / rr
                    t1 = ((dx - ax) * rx + (dy - ay) * ry) / rr
                lo = np.minimum(t0, t1)
                hi = np.maximum(t0, t1)
                collinear = (
                    (np.abs(denom) <= 1e-12)
                    & (rr > 1e-24)
                    & (np.abs(qpx * ry - qpy * rx) <= 1e-12)
                    & (hi > tol)
                    & (lo < 1.0 - tol)
                )
                crossing |= collinear
            chunk_blocked |= crossing
        blocked[start:stop] = chunk_blocked
    return blocked


def strict_segments_intersect(
    a: PointTuple,
    b: PointTuple,
    c: PointTuple,
    d: PointTuple,
    endpoint_tolerance: float = 1e-7,
) -> bool:
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denom = _cross(rx, ry, sx, sy)
    qpx, qpy = cx - ax, cy - ay

    if abs(denom) <= 1e-12:
        if abs(_cross(qpx, qpy, rx, ry)) > 1e-12:
            return False
        rr = rx * rx + ry * ry
        if rr <= 1e-24:
            return False
        t0 = ((cx - ax) * rx + (cy - ay) * ry) / rr
        t1 = ((dx - ax) * rx + (dy - ay) * ry) / rr
        lo, hi = sorted((t0, t1))
        return hi > endpoint_tolerance and lo < 1.0 - endpoint_tolerance

    t = _cross(qpx, qpy, sx, sy) / denom
    u = _cross(qpx, qpy, rx, ry) / denom
    return endpoint_tolerance < t < 1.0 - endpoint_tolerance and -endpoint_tolerance <= u <= 1.0 + endpoint_tolerance


def _segment_intersection_point(
    a: PointTuple,
    b: PointTuple,
    c: PointTuple,
    d: PointTuple,
    endpoint_tolerance: float = 1e-7,
) -> Optional[PointTuple]:
    """Proper (non-endpoint) transverse intersection of ab and cd.

    Collinear overlap returns None (not a single point to rewire).
    """
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cx, cy = float(c[0]), float(c[1])
    dx, dy = float(d[0]), float(d[1])
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denom = _cross(rx, ry, sx, sy)
    qpx, qpy = cx - ax, cy - ay

    if abs(denom) <= 1e-12:
        return None

    t = _cross(qpx, qpy, sx, sy) / denom
    u = _cross(qpx, qpy, rx, ry) / denom
    if not (
        endpoint_tolerance < t < 1.0 - endpoint_tolerance
        and endpoint_tolerance < u < 1.0 - endpoint_tolerance
    ):
        return None
    return (ax + t * rx, ay + t * ry)


def _decimate_polyline_for_topology(
    pts: Sequence[PointTuple],
    grid_step: float,
    *,
    max_points: int = 160,
) -> List[PointTuple]:
    """拓扑前抽稀折线，显著降低消交复杂度（点数²）。"""
    step = max(float(grid_step), 1e-9)
    tol = max(step * 1e-5, 1e-9)
    pts = _dedupe_consecutive_points(pts, tolerance=tol)
    if len(pts) <= max(4, int(max_points)):
        return pts
    # 先按步长抽，再上限截断
    min_seg = max(step * 0.55, 1e-9)
    out: List[PointTuple] = [pts[0]]
    for p in pts[1:-1]:
        if _point_distance(out[-1], p) >= min_seg:
            out.append(p)
    if _point_distance(out[-1], pts[-1]) > tol:
        out.append(pts[-1])
    else:
        out[-1] = pts[-1]
    if len(out) > max_points:
        stride = max(1, (len(out) - 1) // max(1, max_points - 1))
        core = out[::stride]
        if core[-1] != out[-1]:
            core = core + [out[-1]]
        out = core
    return out if len(out) >= 2 else list(pts[:2])


def sanitize_contour_crossings(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    max_passes: int = 120,
    time_budget_s: float = 3.5,
    *,
    max_points_per_line: int = 200,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """消除等值线不当交点（硬约束：等值线不得相交）。

    - 同级别 X 交叉：优先重连；失败则截断
    - 不同级别交叉：截断留缝
    - 自相交：拆段
    有时间与轮次上限，避免大数据卡死。
    """
    import time as _time

    step = max(float(grid_step), 1e-9)
    tol = max(step * 1e-5, 1e-9)
    t0 = _time.perf_counter()
    # working: list of (level, points)
    working: List[Tuple[float, List[PointTuple]]] = []
    total_pts = 0
    for level, lines in contours.items():
        for raw in lines:
            pts = _decimate_polyline_for_topology(
                raw, step, max_points=int(max_points_per_line)
            )
            if len(pts) >= 2:
                working.append((float(level), pts))
                total_pts += len(pts)

    # 点太多时收紧预算，避免交互式生成卡死
    if total_pts > 8000:
        max_passes = min(int(max_passes), 40)
        time_budget_s = min(float(time_budget_s), 1.5)
    elif total_pts > 4000:
        max_passes = min(int(max_passes), 60)
        time_budget_s = min(float(time_budget_s), 2.0)

    fixed = 0
    stagnant = 0
    last_sig: Optional[Tuple[int, int, int, int]] = None
    for _pass in range(max(1, int(max_passes))):
        if (_time.perf_counter() - t0) > float(time_budget_s):
            break
        hit = _find_first_contour_crossing(working, step)
        if hit is None:
            break
        kind, i, si, j, sj, P = hit
        sig = (i, si, j, sj)
        if sig == last_sig:
            stagnant += 1
            if stagnant >= 2:
                # 同一交叉反复出现 → 强制截断并换策略
                level_i, line_i = working[i]
                if i == j:
                    left, right = _split_and_gap_at(line_i, si, P, step)
                    working.pop(i)
                    for p in (left, right):
                        if len(p) >= 2 and _polyline_length(p) >= step * 0.5:
                            working.append((level_i, p))
                else:
                    level_j, line_j = working[j]
                    n1, n2 = _truncate_pair_at_crossing(line_i, si, line_j, sj, P, step)
                    hi, lo = (i, j) if i > j else (j, i)
                    working.pop(hi)
                    working.pop(lo)
                    if len(n1) >= 2:
                        working.append((level_i, n1))
                    if len(n2) >= 2:
                        working.append((level_j, n2))
                fixed += 1
                last_sig = None
                stagnant = 0
                continue
        else:
            stagnant = 0
            last_sig = sig

        if i == j:
            level = working[i][0]
            line = working[i][1]
            left = _dedupe_consecutive_points(line[: si + 1] + [P], tolerance=tol)
            mid_right = [P] + line[si + 1 :]
            local_sj = sj - (si + 1)
            parts: List[List[PointTuple]] = []
            if 0 <= local_sj < len(mid_right) - 1:
                mid = _dedupe_consecutive_points(mid_right[: local_sj + 1] + [P], tolerance=tol)
                right = _dedupe_consecutive_points([P] + mid_right[local_sj + 1 :], tolerance=tol)
                parts = [left, mid, right]
            else:
                parts = [left, _dedupe_consecutive_points(mid_right, tolerance=tol)]
            working.pop(i)
            for p in parts:
                if len(p) >= 2 and _polyline_length(p) >= step * 0.5:
                    working.append((level, p))
            fixed += 1
            continue

        # 任意两线交叉（含同级）：一律四向断开留缝，禁止重连成可能仍交叉的折线
        level_i, line_i = working[i]
        level_j, line_j = working[j]
        left_i, right_i = _split_and_gap_at(line_i, si, P, step)
        left_j, right_j = _split_and_gap_at(line_j, sj, P, step)
        hi, lo = (i, j) if i > j else (j, i)
        working.pop(hi)
        working.pop(lo)
        for lv, parts in (
            (level_i, (left_i, right_i)),
            (level_j, (left_j, right_j)),
        ):
            for p in parts:
                if len(p) >= 2 and _polyline_length(p) >= step * 0.35:
                    working.append((lv, p))
        fixed += 1

    cleaned: Dict[float, List[List[PointTuple]]] = {}
    for level, pts in working:
        if len(pts) < 2:
            continue
        cleaned.setdefault(float(level), []).append(pts)
    return cleaned, fixed


def guarantee_no_contour_crossings(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    max_rounds: int = 80,
    fast: bool = True,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """硬保证：输出中不存在 proper 相交（含自交）。

    交互路径必须有总时间上限：冲突优先丢短线，禁止无限拆缝碎化。
    """
    import time as _time

    step = max(float(grid_step), 1e-9)
    t0 = _time.perf_counter()
    # 统一紧预算：避免生成等值线卡死
    if fast:
        sanitize_passes = 20
        sanitize_budget = 0.8
        max_pts = 100
        fix_rounds = min(50, max(20, int(max_rounds)))
        total_budget = 2.0
        drop_first = True
    else:
        sanitize_passes = 36
        sanitize_budget = 1.5
        max_pts = 140
        fix_rounds = min(70, max(30, int(max_rounds)))
        total_budget = 3.5
        drop_first = True  # 即便 non-fast 也优先丢短线，防止拆缝爆炸

    cleaned, fixed = sanitize_contour_crossings(
        contours,
        step,
        max_passes=sanitize_passes,
        time_budget_s=sanitize_budget,
        max_points_per_line=max_pts,
    )
    working: List[Tuple[float, List[PointTuple]]] = []
    for level, lines in cleaned.items():
        for raw in lines:
            pts = _decimate_polyline_for_topology(raw, step, max_points=max_pts)
            if len(pts) >= 2:
                working.append((float(level), pts))

    dropped = 0
    last_sig: Optional[Tuple[int, int, int, int]] = None
    stagnant = 0
    # 线数爆炸保护
    max_lines = max(400, len(working) * 3)
    for round_i in range(max(1, int(fix_rounds))):
        if (_time.perf_counter() - t0) > total_budget:
            break
        if len(working) > max_lines:
            # 线太多：只保留较长的一半，快速收敛
            working.sort(key=lambda it: _polyline_length(it[1]), reverse=True)
            working = working[: max(80, max_lines // 2)]
            dropped += 1
            continue
        # 前几轮 thorough，之后只做段-段（更快）
        thorough = round_i < 8
        hit = _find_first_contour_crossing(working, step, thorough=thorough)
        if hit is None:
            break
        _kind, i, si, j, sj, P = hit
        sig = (i, si, j, sj)
        if sig == last_sig:
            stagnant += 1
        else:
            stagnant = 0
            last_sig = sig

        # 默认策略：丢较短线（秒级收敛，避免拆缝产生更多交叉）
        force_drop = drop_first or stagnant >= 1 or i == j
        if force_drop:
            if i == j:
                working.pop(i)
            else:
                len_i = _polyline_length(working[i][1])
                len_j = _polyline_length(working[j][1])
                working.pop(i if len_i <= len_j else j)
            dropped += 1
            fixed += 1
            last_sig = None
            stagnant = 0
            continue

        # 非 drop 路径：拆缝一次（保留接口，实际 fast 已走 drop）
        level_i, line_i = working[i]
        level_j, line_j = working[j]
        left_i, right_i = _split_and_gap_at(line_i, si, P, step)
        left_j, right_j = _split_and_gap_at(line_j, sj, P, step)
        hi, lo = (i, j) if i > j else (j, i)
        working.pop(hi)
        working.pop(lo)
        min_keep = step * 3.0
        for lv, parts in (
            (level_i, (left_i, right_i)),
            (level_j, (left_j, right_j)),
        ):
            for p in parts:
                if len(p) >= 2 and _polyline_length(p) >= min_keep:
                    working.append((lv, p))
        fixed += 1

    out: Dict[float, List[List[PointTuple]]] = {}
    for level, pts in working:
        if len(pts) >= 2:
            out.setdefault(float(level), []).append(pts)
    return out, fixed + dropped


def heal_contour_breaks(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    bridge_gap_ratio: float = 8.0,
    close_gap_ratio: float = 6.0,
    barriers: Sequence[BarrierLine] = (),
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """同级断口桥接 + 近端点闭合，减少等值线断点。

    在消交/疏线之后调用：只连同级开放端，不跨级别。
    若传入 barriers：桥接/闭合路径不得穿越打断线（与“不得相交”同级硬约束）。
    """
    step = max(float(grid_step), 1e-9)
    bridge_gap = max(step * float(bridge_gap_ratio), step * 2.0)
    close_gap = max(step * float(close_gap_ratio), step * 2.0)
    active_barriers = tuple(b for b in barriers if getattr(b, "active", True))
    healed: Dict[float, List[List[PointTuple]]] = {}
    bridged_total = 0
    closed_total = 0
    for level, lines in contours.items():
        raw = [list(ln) for ln in lines if len(ln) >= 2]
        if not raw:
            continue
        joined, bcount = _bridge_contour_gaps(
            raw, bridge_gap, step, barriers=active_barriers
        )
        bridged_total += int(bcount)
        sealed, ccount = _close_near_contour_loops(
            joined,
            close_gap,
            step,
            barriers=active_barriers,
            surface_grid=None,
            surface_x=None,
            surface_y=None,
            barrier_proximity=(
                max(step * 3.0, 1e-9) if active_barriers else 0.0
            ),
        )
        closed_total += int(ccount)
        # 去掉过短碎段
        keep: List[List[PointTuple]] = []
        for ln in sealed:
            if len(ln) < 2:
                continue
            if _polyline_length(ln) < step * 2.0 and not _is_closed_polyline(ln, step):
                continue
            keep.append(ln)
        if keep:
            healed[float(level)] = keep
    return healed, {
        "healed_bridged_gaps": int(bridged_total),
        "healed_closed_loops": int(closed_total),
    }


def prepare_surface_for_barrier_interrupt(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
) -> Tuple[np.ndarray, Dict[str, int]]:
    """把「绿缓冲归 0」的显示面改成真正打断用的提取面。

    - 缓冲带内 0/nan 用同侧邻域回填，消除贴外缘的掩膜等值线
    - 仅沿打断线保留 ~1 格宽 nan 窄核作为停线
    不修改调用方持有的显示网格（返回副本）。
    """
    result = np.array(grid, dtype=float, copy=True)
    stats = {"filled_cells": 0, "core_cells": 0}
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active or result.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return result, stats

    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)
    core_r = max(step * 0.85, 1e-9)
    blank = build_barrier_blank_mask(x_coords, y_coords, active, buf)
    core = build_barrier_blank_mask(x_coords, y_coords, active, core_r)
    if blank is None:
        return result, stats

    blank_m = np.asarray(blank, dtype=bool)
    core_m = np.asarray(core, dtype=bool) if core is not None else np.zeros_like(blank_m)
    # 缓冲内被强制为 0 或空的格需要回填（显示绿带造成的掩膜源）
    need = blank_m & ~core_m & (
        ~np.isfinite(result) | (np.abs(result) <= 1e-12)
    )
    # 也回填缓冲内极低伪值（归 0 后平滑残留）
    finite = np.isfinite(result)
    if bool(finite.any()):
        med = float(np.nanmedian(np.abs(result[finite])))
        low_cut = max(1e-12, med * 1e-6)
        need |= blank_m & ~core_m & finite & (np.abs(result) <= low_cut)

    rows, cols = result.shape
    xs = np.asarray(x_coords, dtype=float)
    ys = np.asarray(y_coords, dtype=float)
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))

    filled = 0
    max_passes = min(max(rows, cols) + 8, 80)
    for _pass in range(max_passes):
        changed = 0
        nxt = result.copy()
        candidates = np.where(need)
        for r, c in zip(candidates[0], candidates[1]):
            r = int(r)
            c = int(c)
            if core_m[r, c]:
                continue
            wsum = 0.0
            vsum = 0.0
            cx, cy = float(xs[c]), float(ys[r])
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                if core_m[nr, nc]:
                    continue
                val = float(result[nr, nc])
                if not math.isfinite(val) or abs(val) <= 1e-12:
                    continue
                # 邻格连线不得跨打断线
                nx, ny = float(xs[nc]), float(ys[nr])
                if is_blocked_by_barrier((cx, cy), (nx, ny), active, endpoint_tolerance=1e-7):
                    continue
                w = 1.0 / max(math.hypot(float(dr), float(dc)), 0.5)
                wsum += w
                vsum += val * w
            if wsum > 0:
                nxt[r, c] = vsum / wsum
                need[r, c] = False
                changed += 1
                filled += 1
        result = nxt
        if changed == 0:
            break

    if bool(core_m.any()):
        result[core_m] = np.nan
        stats["core_cells"] = int(np.count_nonzero(core_m))
    stats["filled_cells"] = int(filled)
    return result, stats


def interrupt_contours_at_barriers(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    grid_step: float,
    *,
    snap_distance: float = 0.0,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """真正打断：在红线处切断，端点吸附到打断线；不沿绿缓冲外缘贴边。

    与掩膜式「整带剔除 + 外缘绕行」相对：等值线可进入显示绿带区域，
    但不得穿越打断线本身。
    """
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    stats = {"cut_crossings": 0, "snapped_ends": 0, "removed_scraps": 0}
    if not active:
        return (
            {float(lv): [list(ln) for ln in lines] for lv, lines in contours.items()},
            stats,
        )
    step = max(float(grid_step), 1e-9)
    snap_d = float(snap_distance) if snap_distance > 0 else step * 3.0
    snap_d = max(snap_d, step * 1.5)

    result, cut = enforce_no_barrier_crossing(contours, active, step)
    stats["cut_crossings"] = int(cut)

    # 开放端靠近打断线 → 吸附到线（略偏同侧，避免重新压线）
    out: Dict[float, List[List[PointTuple]]] = {}
    snapped = 0
    scraps = 0
    min_keep = step * 2.5
    for level, lines in result.items():
        kept: List[List[PointTuple]] = []
        for raw in lines:
            if len(raw) < 2:
                scraps += 1
                continue
            pts = [(float(p[0]), float(p[1])) for p in raw]
            if not _is_closed_polyline(pts, step):
                for which in ("start", "end"):
                    end_i = 0 if which == "start" else -1
                    inner_i = 1 if which == "start" else -2
                    end_pt = pts[end_i]
                    inner_pt = pts[inner_i] if len(pts) >= 2 else end_pt
                    proj_info = _nearest_barrier_projection(end_pt, active)
                    if proj_info is None:
                        continue
                    proj, seg_a, seg_b, dist = proj_info
                    if dist > snap_d:
                        continue
                    # 同侧微偏置，端点落在打断线旁而不是跨侧
                    sx = float(seg_b[0]) - float(seg_a[0])
                    sy = float(seg_b[1]) - float(seg_a[1])
                    sl = math.hypot(sx, sy)
                    if sl <= 1e-12:
                        nx, ny = 0.0, 0.0
                    else:
                        nx, ny = -sy / sl, sx / sl  # 左法向
                    side = _side_sign_of_point(inner_pt, seg_a, seg_b)
                    if side < 0:
                        nx, ny = -nx, -ny
                    offset = step * 0.20
                    new_end = (float(proj[0]) + nx * offset, float(proj[1]) + ny * offset)
                    # 吸附边不得跨线
                    if is_blocked_by_barrier(inner_pt, new_end, active, endpoint_tolerance=1e-7):
                        new_end = (float(proj[0]), float(proj[1]))
                    if which == "start":
                        pts[0] = new_end
                    else:
                        pts[-1] = new_end
                    snapped += 1
            pts = _dedupe_consecutive_points(pts, tolerance=max(step * 1e-6, 1e-9))
            if len(pts) < 2 or _polyline_length(pts) < min_keep:
                scraps += 1
                continue
            kept.append(pts)
        if kept:
            out[float(level)] = kept
    stats["snapped_ends"] = int(snapped)
    stats["removed_scraps"] = int(scraps)
    return out, stats


def enforce_no_barrier_crossing(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """硬约束：等值线任意线段不得与打断线严格相交。

    与「等值线不得相交」同级：发现穿越则在交点拆开并留缝，禁止跨侧连通。
    """
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active:
        return (
            {float(lv): [list(ln) for ln in lines] for lv, lines in contours.items()},
            0,
        )
    step = max(float(grid_step), 1e-9)
    cut = 0
    out: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for raw in lines:
            if len(raw) < 2:
                continue
            current: List[PointTuple] = [(float(raw[0][0]), float(raw[0][1]))]
            for idx in range(1, len(raw)):
                a = current[-1]
                b = (float(raw[idx][0]), float(raw[idx][1]))
                if is_blocked_by_barrier(a, b, active, endpoint_tolerance=1e-7):
                    hit = _first_barrier_intersection(a, b, active)
                    if hit is not None:
                        left, right = _split_and_gap_at([a, b], 0, hit, step)
                        if len(left) >= 2:
                            # 把 left 接到 current（left[0]≈a）
                            for p in left[1:]:
                                current.append(p)
                        if len(current) >= 2:
                            kept.append(current)
                            cut += 1
                        current = list(right) if len(right) >= 1 else []
                        if len(current) == 1:
                            # 单点：下一段再延伸
                            pass
                        elif not current:
                            current = [b]
                    else:
                        if len(current) >= 2:
                            kept.append(current)
                            cut += 1
                        current = [b]
                else:
                    current.append(b)
            if len(current) >= 2:
                kept.append(current)
        out[float(level)] = kept
    return out, cut


def _first_barrier_intersection(
    a: PointTuple,
    b: PointTuple,
    barriers: Sequence[BarrierLine],
) -> Optional[PointTuple]:
    """返回 ab 与打断线的第一个严格交点（沿 a→b 最近）。"""
    best = None
    best_t = math.inf
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    for barrier in barriers:
        for c, d in _segments(barrier.points):
            P = _segment_intersection_point(a, b, c, d, endpoint_tolerance=1e-9)
            if P is None:
                # 退回 strict 判定但取中点近似
                if not strict_segments_intersect(a, b, c, d, 1e-9):
                    continue
                # 用参数求交（与 _segment_intersection_point 同公式，放宽端点）
                cx, cy = float(c[0]), float(c[1])
                dx, dy = float(d[0]), float(d[1])
                rx, ry = bx - ax, by - ay
                sx, sy = dx - cx, dy - cy
                denom = _cross(rx, ry, sx, sy)
                if abs(denom) <= 1e-12:
                    continue
                qpx, qpy = cx - ax, cy - ay
                t = _cross(qpx, qpy, sx, sy) / denom
                if t <= 0.0 or t >= 1.0:
                    continue
                P = (ax + t * rx, ay + t * ry)
            # 参数 t
            vx, vy = bx - ax, by - ay
            ll = vx * vx + vy * vy
            if ll <= 1e-24:
                t = 0.0
            else:
                t = ((float(P[0]) - ax) * vx + (float(P[1]) - ay) * vy) / ll
            if 0.0 < t < 1.0 and t < best_t:
                best_t = t
                best = (float(P[0]), float(P[1]))
    return best


def enforce_min_contour_spacing(
    contours: Dict[float, List[List[PointTuple]]],
    min_spacing: float,
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """线间距约束：去掉过密短环，但保护长开放脊线等值线。

    - 优先保留**长线**（含沿方向的开放脊线），避免井点小环「抢走廊」把脊线删光
    - 闭合小环过密时只整环去留，不裁断弧
    - 长开放线仅当几乎全程贴靠更长主线时才整条丢弃
    """
    step = max(float(grid_step), 1e-9)
    spacing = float(min_spacing)
    if spacing <= 0.0:
        return (
            {float(lv): [list(ln) for ln in lines] for lv, lines in contours.items()},
            0,
        )

    # (priority_score, length, level, points) — 长线优先，开放脊线不因「非闭合」被压后
    candidates: List[Tuple[float, float, float, List[PointTuple]]] = []
    for level, lines in contours.items():
        for raw in lines:
            pts = _dedupe_consecutive_points(raw, tolerance=max(step * 1e-6, 1e-9))
            if len(pts) < 2:
                continue
            length = _polyline_length(pts)
            if length < step * 0.5:
                continue
            closed = 1.0 if _is_closed_polyline(pts, step) else 0.0
            chord = _point_distance(pts[0], pts[-1])
            if closed > 0.0:
                straightness = 1.0
            else:
                # 开放线：沿脊线往往端点很远，chord≈length；弯折线略降权
                straightness = max(0.35, min(1.0, chord / max(length, 1e-9)))
            # 长度主导；闭合仅轻微加分（同长度时优先环）
            score = length * (0.9 + 0.1 * straightness) + closed * length * 0.05
            candidates.append((score, length, float(level), pts))
    candidates.sort(key=lambda item: item[0], reverse=True)

    # 独占走廊半径：用 spacing 作为半宽（两条趋势线至少隔开约 1×spacing）
    corridor = max(spacing, step)
    cell = max(corridor, step)
    # bins[(ix,iy)] -> list of (ax,ay,bx,by, level)
    bins: Dict[Tuple[int, int], List[Tuple[float, float, float, float, float]]] = {}

    def _cell_key(x: float, y: float) -> Tuple[int, int]:
        return (int(math.floor(x / cell)), int(math.floor(y / cell)))

    def _add_polyline(level: float, pts: Sequence[PointTuple]) -> None:
        for a, b in zip(pts, pts[1:]):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            if math.hypot(bx - ax, by - ay) < 1e-12:
                continue
            min_x, max_x = (ax, bx) if ax <= bx else (bx, ax)
            min_y, max_y = (ay, by) if ay <= by else (by, ay)
            # 走廊膨胀：登记时把线段邻域 cell 也写入，加速密区判定
            pad = corridor
            i0 = int(math.floor((min_x - pad) / cell))
            i1 = int(math.floor((max_x + pad) / cell))
            j0 = int(math.floor((min_y - pad) / cell))
            j1 = int(math.floor((max_y + pad) / cell))
            seg = (ax, ay, bx, by, float(level))
            for ix in range(i0, i1 + 1):
                for iy in range(j0, j1 + 1):
                    bins.setdefault((ix, iy), []).append(seg)

    def _min_dist(pt: PointTuple, self_level: float) -> float:
        """到已保留线的最小垂距；同级不参与（避免同级碎段互杀）。"""
        if not bins:
            return math.inf
        px, py = float(pt[0]), float(pt[1])
        cx, cy = _cell_key(px, py)
        best = math.inf
        neighbor_r = 2
        lv_self = float(self_level)
        for dx in range(-neighbor_r, neighbor_r + 1):
            for dy in range(-neighbor_r, neighbor_r + 1):
                for ax, ay, bx, by, lv in bins.get((cx + dx, cy + dy), ()):
                    if abs(float(lv) - lv_self) <= 1e-12:
                        continue
                    d = _point_to_segment_distance((px, py), (ax, ay), (bx, by))
                    if d < best:
                        best = d
                        if best <= corridor * 0.2:
                            return best
        return best

    def _vertex_flags(pts: Sequence[PointTuple], level: float) -> List[bool]:
        """True=离开已占走廊（可留）；False=落在密集成束走廊内。"""
        if not bins:
            return [True] * len(pts)
        thr = corridor * 0.95
        flags: List[bool] = []
        for p in pts:
            flags.append(_min_dist(p, level) >= thr)
        for i in range(len(pts) - 1):
            if not flags[i] and not flags[i + 1]:
                continue
            a, b = pts[i], pts[i + 1]
            mx = 0.5 * (float(a[0]) + float(b[0]))
            my = 0.5 * (float(a[1]) + float(b[1]))
            if _min_dist((mx, my), level) < thr:
                flags[i] = False
                flags[i + 1] = False
        return flags

    def _split_by_flags(
        pts: Sequence[PointTuple], flags: Sequence[bool]
    ) -> List[List[PointTuple]]:
        # 保留可分离的远段；阈值放宽，减少短断弧
        min_keep = max(corridor * 1.5, step * 3.0)
        parts: List[List[PointTuple]] = []
        cur: List[PointTuple] = []
        for p, ok in zip(pts, flags):
            if ok:
                cur.append((float(p[0]), float(p[1])))
            else:
                if len(cur) >= 2 and _polyline_length(cur) >= min_keep:
                    parts.append(cur)
                cur = []
        if len(cur) >= 2 and _polyline_length(cur) >= min_keep:
            parts.append(cur)
        return parts

    kept: List[Tuple[float, List[PointTuple]]] = []
    removed_parts = 0
    for _score, length, level, pts in candidates:
        if not bins:
            kept.append((level, pts))
            _add_polyline(level, pts)
            continue

        is_closed = _is_closed_polyline(pts, step)
        flags = _vertex_flags(pts, level)
        good_count = sum(1 for f in flags if f)
        good_ratio = good_count / max(len(flags), 1)

        # 闭合环：只整环保留/整环删除，绝不裁成断弧
        if is_closed:
            # 小环过密才删；大环放宽
            thr = 0.25 if length < corridor * 25 else 0.12
            if good_ratio < thr:
                removed_parts += 1
                continue
            kept.append((level, pts))
            _add_polyline(level, pts)
            continue

        # —— 开放脊线 ——
        # 保护：不被井点小环抹掉；但若与更长主线大段贴靠/近平行，仍要疏掉，
        # 否则会出现图上多条近平行线缠绕相交。
        long_open = length >= max(corridor * 20.0, step * 25.0)
        if long_open:
            if good_ratio < 0.22:
                removed_parts += 1
                continue
            if good_ratio < 0.55:
                # 部分贴靠：只留安全段，避免与主线缠绕
                parts = _split_by_flags(pts, flags)
                if not parts:
                    removed_parts += 1
                    continue
                kept_len = sum(_polyline_length(p) for p in parts)
                if kept_len < max(length * 0.45, corridor * 8.0, step * 10.0):
                    removed_parts += 1
                    continue
                for part in parts:
                    kept.append((level, part))
                    _add_polyline(level, part)
                removed_parts += 1
                continue
            kept.append((level, pts))
            _add_polyline(level, pts)
            continue

        # 短开放线：大半贴靠 → 丢弃
        if good_ratio < 0.35:
            removed_parts += 1
            continue

        if good_ratio > 0.88 and all(flags):
            kept.append((level, pts))
            _add_polyline(level, pts)
            continue

        parts = _split_by_flags(pts, flags)
        if not parts:
            removed_parts += 1
            continue
        kept_len = sum(_polyline_length(p) for p in parts)
        if kept_len < max(length * 0.35, corridor * 2.5, step * 4.0):
            removed_parts += 1
            continue
        for part in parts:
            kept.append((level, part))
            _add_polyline(level, part)
        removed_parts += 1

    out: Dict[float, List[List[PointTuple]]] = {}
    for level, pts in kept:
        out.setdefault(float(level), []).append(pts)
    return out, removed_parts


def _estimate_auto_contour_spacing(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
) -> float:
    """自动间距：约 1.2×网格步长，避免过大把脊线等值线疏没。"""
    step = max(float(grid_step), 1e-9)
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    n_pts = 0
    for lines in contours.values():
        for ln in lines:
            for p in ln:
                x, y = float(p[0]), float(p[1])
                if not (math.isfinite(x) and math.isfinite(y)):
                    continue
                n_pts += 1
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if n_pts < 2 or not math.isfinite(min_x):
        return max(step * 1.2, step)
    diag = math.hypot(max_x - min_x, max_y - min_y)
    # 偏保守：只疏过密小环，不伤区域脊线
    extent_based = diag * 0.002
    spacing = max(step * 1.2, min(step * 3.5, max(extent_based, step * 1.2)))
    return float(spacing)


def apply_contour_topology_constraints(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    min_spacing: float = 0.0,
    enforce_no_crossing: bool = True,
    fast: bool = True,
    barriers: Sequence[BarrierLine] = (),
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """等值线拓扑硬约束统一入口。

    - enforce_no_crossing=True：保证线不相交（硬约束）
    - barriers：等值线不得穿越打断线（硬约束，与不相交同级）
    - min_spacing>0：线间距疏化
    - min_spacing==0：自动间距；<0 关闭
    - fast=True：交互生成默认快速路径
    """
    step = max(float(grid_step), 1e-9)
    active_barriers = tuple(b for b in barriers if getattr(b, "active", True))
    stats: Dict[str, int] = {
        "fixed_contour_crossings": 0,
        "removed_dense_contours": 0,
        "min_contour_spacing_m": 0,
        "cut_barrier_crossings": 0,
        "enforce_no_crossing": int(bool(enforce_no_crossing)),
        "enforce_no_barrier_crossing": int(1 if active_barriers else 0),
    }
    result = {float(lv): [list(ln) for ln in lines] for lv, lines in contours.items()}

    spacing = float(min_spacing)
    if spacing == 0.0:
        spacing = _estimate_auto_contour_spacing(result, step)
    if spacing < 0.0:
        spacing = 0.0
    stats["min_contour_spacing_m"] = int(round(spacing)) if spacing > 0 else 0

    # 单轮流水：疏线 → 消交 → 轻愈合 → 再消交/断打断（总预算约数秒）
    if active_barriers:
        result, cut0 = enforce_no_barrier_crossing(result, active_barriers, step)
        stats["cut_barrier_crossings"] = int(cut0)

    if spacing > 0.0:
        result, removed = enforce_min_contour_spacing(result, spacing, step)
        stats["removed_dense_contours"] = int(removed)

    if enforce_no_crossing:
        result, fixed = guarantee_no_contour_crossings(
            result, step, max_rounds=50, fast=True
        )
        stats["fixed_contour_crossings"] = int(fixed)

    # Gap repair and curve smoothing already happened against the scalar surface.
    # Do not reconnect here: a topology-only pass has no level-surface evidence
    # and used to create long false joins (especially beside barrier buffers).
    stats["healed_bridged_gaps"] = 0
    stats["healed_closed_loops"] = 0

    if active_barriers:
        result, cut1 = enforce_no_barrier_crossing(result, active_barriers, step)
        stats["cut_barrier_crossings"] = int(
            stats["cut_barrier_crossings"] + cut1
        )

    # ★ 最后一步：严格不相交（含近距缠绕），之后不再做会改几何的操作
    if enforce_no_crossing:
        result, fixed2 = enforce_strict_no_crossing(
            result,
            step,
            near_tol_ratio=0.20,
            time_budget_s=5.0,
            max_rounds=250,
        )
        stats["fixed_contour_crossings"] = int(
            stats["fixed_contour_crossings"] + fixed2
        )

    return result, stats


def enforce_strict_no_crossing(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    near_tol_ratio: float = 0.45,
    time_budget_s: float = 4.0,
    max_rounds: int = 200,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """最终严格消交：proper 相交 或 中段过近缠绕 → 丢较短线。

    写死硬约束：只要还有交叉/缠绕就继续丢短线，直到干净或预算耗尽。
    专治图上「几乎平行又蹭在一起/交叉」的残留。
    """
    import time as _time

    step = max(float(grid_step), 1e-9)
    near_tol = max(step * float(near_tol_ratio), 1e-6)
    t0 = _time.perf_counter()

    working: List[Tuple[float, List[PointTuple]]] = []
    for level, lines in contours.items():
        for raw in lines:
            # 最终消交保留更多点，避免抽稀漏检交叉
            pts = _decimate_polyline_for_topology(raw, step, max_points=360)
            if len(pts) >= 2:
                working.append((float(level), pts))

    fixed = 0
    rounds = max(1, int(max_rounds))
    for round_i in range(rounds):
        # 预算只限制「近距缠绕」扫描；真正的 proper 相交必须尽量清完
        over_budget = (_time.perf_counter() - t0) > float(time_budget_s)
        hit = _find_first_contour_crossing(working, step, thorough=True)
        if hit is None:
            if over_budget and round_i > 0:
                break
            pair = _find_first_near_touch(working, near_tol, step)
            if pair is None:
                break
            i, j = pair
            li = _polyline_length(working[i][1])
            lj = _polyline_length(working[j][1])
            working.pop(i if li <= lj else j)
            fixed += 1
            continue
        _kind, i, _si, j, _sj, _P = hit
        if i == j:
            working.pop(i)
            fixed += 1
            continue
        li = _polyline_length(working[i][1])
        lj = _polyline_length(working[j][1])
        working.pop(i if li <= lj else j)
        fixed += 1

    # 终极兜底：再扫一轮 proper 相交（不计近距，防止预算提前跳出）
    for _ in range(max(20, rounds // 4)):
        hit = _find_first_contour_crossing(working, step, thorough=True)
        if hit is None:
            break
        _kind, i, _si, j, _sj, _P = hit
        if i == j:
            working.pop(i)
        else:
            li = _polyline_length(working[i][1])
            lj = _polyline_length(working[j][1])
            working.pop(i if li <= lj else j)
        fixed += 1

    out: Dict[float, List[List[PointTuple]]] = {}
    for level, pts in working:
        if len(pts) >= 2:
            out.setdefault(float(level), []).append(pts)
    return out, fixed


def _find_first_near_touch(
    working: Sequence[Tuple[float, List[PointTuple]]],
    near_tol: float,
    grid_step: float,
) -> Optional[Tuple[int, int]]:
    """若两条不同折线中段距离 < near_tol（非端点轻触），返回 (i,j)。"""
    n = len(working)
    if n < 2:
        return None
    step = max(float(grid_step), 1e-9)
    tol2 = float(near_tol) * float(near_tol)
    # 轻量：对每条线采样点，查与其他线的最近段
    for i in range(n):
        pi = working[i][1]
        if len(pi) < 2:
            continue
        # 跳过两端点，只看中段
        idxs = range(1, len(pi) - 1) if len(pi) > 3 else range(len(pi))
        stride = 1 if len(pi) <= 60 else max(1, len(pi) // 40)
        for vi in list(idxs)[::stride]:
            px, py = float(pi[vi][0]), float(pi[vi][1])
            for j in range(n):
                if j == i:
                    continue
                pj = working[j][1]
                for s in range(len(pj) - 1):
                    # 跳过对方端点邻域段可减少误判，但真正缠绕需检出
                    d = _point_to_segment_distance((px, py), pj[s], pj[s + 1])
                    if d * d > tol2:
                        continue
                    # 若只是端点靠近（断口相邻）则忽略
                    if (
                        _point_distance((px, py), pj[0]) < near_tol * 1.5
                        or _point_distance((px, py), pj[-1]) < near_tol * 1.5
                    ) and (
                        _point_distance((px, py), pi[0]) < step * 2
                        or _point_distance((px, py), pi[-1]) < step * 2
                    ):
                        continue
                    return (i, j)
    return None


def cartographic_smooth_contours(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    iterations: int = 3,
) -> Dict[float, List[List[PointTuple]]]:
    """对全部等值线做制图平滑（压阶梯 + 去尖刺 + Chaikin）。"""
    step = max(float(grid_step), 1e-9)
    out: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for ln in lines:
            if len(ln) < 2:
                continue
            sm = _cartographic_smooth_polyline(ln, step, iterations=iterations)
            if len(sm) >= 2:
                kept.append(sm)
        if kept:
            out[float(level)] = kept
    return out


def project_contours_to_surface_levels(
    contours: Dict[float, List[List[PointTuple]]],
    surface_grid: Optional[np.ndarray],
    surface_x: Optional[np.ndarray],
    surface_y: Optional[np.ndarray],
    grid_step: float,
    *,
    iterations: int = 2,
) -> Dict[float, List[List[PointTuple]]]:
    """Move smoothed vertices back onto their source surface level.

    Pure geometry smoothing can drift a contour away from the scalar field and
    make adjacent levels crowd or cross. A short, capped Newton projection keeps
    Surfer-like smooth curves while preserving the numerical isoline meaning.
    Open-line endpoints remain fixed because they usually encode a map, support,
    or barrier boundary.
    """
    if surface_grid is None or surface_x is None or surface_y is None:
        return {float(level): [list(line) for line in lines] for level, lines in contours.items()}
    grid = np.asarray(surface_grid, dtype=float)
    xs = np.asarray(surface_x, dtype=float)
    ys = np.asarray(surface_y, dtype=float)
    if grid.ndim != 2 or grid.size == 0 or len(xs) < 2 or len(ys) < 2:
        return {float(level): [list(line) for line in lines] for level, lines in contours.items()}

    step = max(float(grid_step), 1e-9)
    eps_x = max(float(np.median(np.abs(np.diff(xs)))), step * 0.5, 1e-9)
    eps_y = max(float(np.median(np.abs(np.diff(ys)))), step * 0.5, 1e-9)
    max_shift = step * 1.15

    def _gradient(x: float, y: float) -> Optional[Tuple[float, float]]:
        left = sample_bilinear_grid(grid, xs, ys, x - eps_x, y)
        right = sample_bilinear_grid(grid, xs, ys, x + eps_x, y)
        down = sample_bilinear_grid(grid, xs, ys, x, y - eps_y)
        up = sample_bilinear_grid(grid, xs, ys, x, y + eps_y)
        if left is None or right is None or down is None or up is None:
            return None
        return ((right - left) / (2.0 * eps_x), (up - down) / (2.0 * eps_y))

    projected: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        out_lines: List[List[PointTuple]] = []
        target = float(level)
        for raw in lines:
            line = list(raw)
            if len(line) < 3:
                out_lines.append(line)
                continue
            closed = _is_closed_polyline(line, step)
            core = line[:-1] if closed else line
            moved: List[PointTuple] = []
            for index, point in enumerate(core):
                if not closed and index in (0, len(core) - 1):
                    moved.append((float(point[0]), float(point[1])))
                    continue
                x, y = float(point[0]), float(point[1])
                for _ in range(max(1, min(3, int(iterations)))):
                    value = sample_bilinear_grid(grid, xs, ys, x, y)
                    grad = _gradient(x, y)
                    if value is None or grad is None:
                        break
                    gx, gy = grad
                    norm_sq = gx * gx + gy * gy
                    if norm_sq <= 1e-18:
                        break
                    scale = (target - float(value)) / norm_sq
                    dx, dy = scale * gx, scale * gy
                    distance = math.hypot(dx, dy)
                    if distance > max_shift:
                        ratio = max_shift / distance
                        dx *= ratio
                        dy *= ratio
                    nx, ny = x + dx, y + dy
                    if sample_bilinear_grid(grid, xs, ys, nx, ny) is None:
                        break
                    x, y = nx, ny
                moved.append((x, y))
            if closed and len(moved) >= 3:
                moved.append(moved[0])
            if len(moved) >= 2 and not _polyline_self_intersects(moved, step):
                out_lines.append(moved)
            else:
                out_lines.append(line)
        if out_lines:
            projected[float(level)] = out_lines
    return projected


def finalize_contours_hard_no_cross(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    barriers: Sequence[BarrierLine] = (),
    buffer_distance: float = 0.0,
    smooth_iterations: int = 3,
    enforce_no_crossing: bool = True,
    surface_grid: Optional[np.ndarray] = None,
    surface_x: Optional[np.ndarray] = None,
    surface_y: Optional[np.ndarray] = None,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """流水线终态：平滑 → 禁入缓冲/断打断 → 写死不相交。

    之后不得再改几何（禁止再绕缓冲/贴边/桥接）。
    """
    step = max(float(grid_step), 1e-9)
    stats = {"final_smooth": 0, "fixed_contour_crossings": 0, "cut_barrier_crossings": 0}
    result = {float(level): [list(line) for line in lines] for level, lines in contours.items()}
    if int(smooth_iterations) > 0:
        result = cartographic_smooth_contours(
            result, step, iterations=min(3, int(smooth_iterations))
        )
        if surface_grid is not None and surface_x is not None and surface_y is not None:
            result = project_contours_to_surface_levels(
                result,
                surface_grid,
                surface_x,
                surface_y,
                step,
                iterations=2,
            )
        stats["final_smooth"] = 1

    active = tuple(b for b in barriers if getattr(b, "active", True))
    buf = float(buffer_distance)
    if active and buf > 0.0:
        # Hard-stop contours at the buffer. Point-by-point radial pushing can
        # create a new kink where the pushed section rejoins the untouched arc.
        result, pre_trim = trim_contours_at_barrier_buffers(
            result, active, buf, step
        )
        stats["initial_buffer_trimmed"] = int(pre_trim)
        result, cut = enforce_no_barrier_crossing(result, active, step)
        stats["cut_barrier_crossings"] = int(cut)
        result = cartographic_smooth_contours(result, step, iterations=1)
        if surface_grid is not None and surface_x is not None and surface_y is not None:
            result = project_contours_to_surface_levels(
                result,
                surface_grid,
                surface_x,
                surface_y,
                step,
                iterations=1,
            )
        result, post_trim = trim_contours_at_barrier_buffers(
            result, active, buf, step
        )
        stats["post_smooth_buffer_trimmed"] = int(post_trim)
    elif active:
        result, cut = enforce_no_barrier_crossing(result, active, step)
        stats["cut_barrier_crossings"] = int(cut)
        result = cartographic_smooth_contours(result, step, iterations=1)
        if surface_grid is not None and surface_x is not None and surface_y is not None:
            result = project_contours_to_surface_levels(
                result,
                surface_grid,
                surface_x,
                surface_y,
                step,
                iterations=1,
            )

    if enforce_no_crossing:
        result, fixed = enforce_strict_no_crossing(
            result,
            step,
            near_tol_ratio=0.20,
            time_budget_s=5.0,
            max_rounds=250,
        )
        stats["fixed_contour_crossings"] = int(fixed)

    # Numeric projection and topology edits can leave a few visible angular
    # vertices. One geometry-only polish pass restores curve continuity; a
    # second strict check below keeps the hard no-cross guarantee.
    if int(smooth_iterations) > 0:
        result = cartographic_smooth_contours(result, step, iterations=1)
        stats["final_curve_polish"] = 1
        if enforce_no_crossing:
            result, polished_fixed = enforce_strict_no_crossing(
                result,
                step,
                near_tol_ratio=0.20,
                time_budget_s=5.0,
                max_rounds=250,
            )
            stats["fixed_contour_crossings"] = int(
                stats.get("fixed_contour_crossings", 0) + polished_fixed
            )

    # This must be the final geometry operation. Crossing cleanup can create a
    # new long chord after earlier barrier checks, so trim against the full
    # buffer and recheck the centerline without smoothing afterward.
    if active and buf > 0.0:
        result, final_trim = trim_contours_at_barrier_buffers(
            result,
            active,
            buf,
            step,
        )
        result, final_cut = enforce_no_barrier_crossing(result, active, step)
        stats["final_buffer_trimmed"] = int(
            stats.get("initial_buffer_trimmed", 0)
            + stats.get("post_smooth_buffer_trimmed", 0)
            + final_trim
        )
        stats["cut_barrier_crossings"] = int(
            stats.get("cut_barrier_crossings", 0) + final_cut
        )
    return result, stats


def resolve_min_contour_spacing(min_spacing: Optional[float], grid_step: float) -> float:
    """归一化最小间距：None/0→自动；负数→关闭。"""
    step = max(float(grid_step), 1e-9)
    if min_spacing is None:
        return max(step * 2.0, step)
    val = float(min_spacing)
    if val < 0.0:
        return -1.0
    if val == 0.0:
        return max(step * 2.0, step)
    return val


def _point_on_segment_interior(
    pt: PointTuple,
    a: PointTuple,
    b: PointTuple,
    *,
    end_tol: float,
    line_tol: float,
) -> Optional[float]:
    """若 pt 落在 ab 内部（非端点），返回沿 ab 的参数 t∈(0,1)；否则 None。"""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    px, py = float(pt[0]), float(pt[1])
    vx, vy = bx - ax, by - ay
    ll = vx * vx + vy * vy
    if ll <= 1e-24:
        return None
    t = ((px - ax) * vx + (py - ay) * vy) / ll
    if t <= end_tol or t >= 1.0 - end_tol:
        return None
    qx, qy = ax + t * vx, ay + t * vy
    if math.hypot(px - qx, py - qy) > line_tol:
        return None
    return t


def _find_first_contour_crossing(
    working: Sequence[Tuple[float, List[PointTuple]]],
    grid_step: float,
    *,
    thorough: bool = True,
) -> Optional[Tuple[str, int, int, int, int, PointTuple]]:
    """Return (kind, line_i, seg_i, line_j, seg_j, P) for first improper crossing.

    使用空间哈希加速段-段检测。thorough=True 时额外检查顶点压段/共享内点。
    """
    n = len(working)
    if n == 0:
        return None
    step = max(float(grid_step), 1e-9)
    line_tol = max(step * 0.08, 1e-6)
    end_tol = 1e-6
    cell = max(step * 4.0, 1e-6)

    def _ck(x: float, y: float) -> Tuple[int, int]:
        return (int(math.floor(x / cell)), int(math.floor(y / cell)))

    # 段索引：(line_idx, seg_idx, a0, a1) — 自交与互交都走空间哈希，禁止 O(m²) 全扫
    segs: List[Tuple[int, int, PointTuple, PointTuple]] = []
    bins: Dict[Tuple[int, int], List[int]] = {}
    for i in range(n):
        pts = working[i][1]
        m = len(pts) - 1
        if m < 1:
            continue
        for si in range(m):
            a0, a1 = pts[si], pts[si + 1]
            segs.append((i, si, a0, a1))
            sx0, sy0 = float(a0[0]), float(a0[1])
            sx1, sy1 = float(a1[0]), float(a1[1])
            i0, i1 = sorted((_ck(sx0, sy0)[0], _ck(sx1, sy1)[0]))
            j0, j1 = sorted((_ck(sx0, sy0)[1], _ck(sx1, sy1)[1]))
            # 限制单段覆盖 cell 数，避免超长段填爆哈希
            if (i1 - i0 + 1) * (j1 - j0 + 1) > 64:
                # 只登记两端附近
                for cx, cy in (_ck(sx0, sy0), _ck(sx1, sy1)):
                    bins.setdefault((cx, cy), []).append(len(segs) - 1)
            else:
                sid = len(segs) - 1
                for ix in range(i0, i1 + 1):
                    for iy in range(j0, j1 + 1):
                        bins.setdefault((ix, iy), []).append(sid)

    # 自交 + 互交：同 cell 段对
    checked: set = set()
    for cell_ids in bins.values():
        mm = len(cell_ids)
        if mm < 2:
            continue
        # cell 内段过多时抽样，防止单格爆炸
        ids = cell_ids if mm <= 80 else cell_ids[:: max(1, mm // 60)]
        mm2 = len(ids)
        for a in range(mm2):
            ia, sa, a0, a1 = segs[ids[a]]
            amin_x = min(a0[0], a1[0]) - line_tol
            amax_x = max(a0[0], a1[0]) + line_tol
            amin_y = min(a0[1], a1[1]) - line_tol
            amax_y = max(a0[1], a1[1]) + line_tol
            for b in range(a + 1, mm2):
                ib, sb, b0, b1 = segs[ids[b]]
                if ia == ib:
                    # 同线：跳过相邻段与闭合首尾
                    if abs(sa - sb) <= 1:
                        continue
                    pts = working[ia][1]
                    mseg = len(pts) - 1
                    if (
                        _is_closed_polyline(pts, grid_step)
                        and min(sa, sb) == 0
                        and max(sa, sb) == mseg - 1
                    ):
                        continue
                key = (ia, sa, ib, sb) if (ia, sa) <= (ib, sb) else (ib, sb, ia, sa)
                if key in checked:
                    continue
                checked.add(key)
                if max(b0[0], b1[0]) < amin_x or min(b0[0], b1[0]) > amax_x:
                    continue
                if max(b0[1], b1[1]) < amin_y or min(b0[1], b1[1]) > amax_y:
                    continue
                P = _segment_intersection_point(a0, a1, b0, b1, end_tol)
                if P is not None:
                    kind = "self" if ia == ib else "pair"
                    return (kind, ia, sa, ib, sb, P)

    if not thorough:
        return None

    # 顶点压在他线内部（限点数，避免卡死）
    max_vertex_checks = 800
    checked_v = 0
    for i in range(n):
        pi = working[i][1]
        stride = 1 if len(pi) <= 80 else max(1, len(pi) // 60)
        for vi in range(0, len(pi), stride):
            checked_v += 1
            if checked_v > max_vertex_checks:
                break
            v = pi[vi]
            vx, vy = float(v[0]), float(v[1])
            cx, cy = _ck(vx, vy)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for sid in bins.get((cx + dx, cy + dy), ()):
                        j, sj, b0, b1 = segs[sid]
                        if j == i:
                            continue
                        t = _point_on_segment_interior(
                            v, b0, b1, end_tol=0.02, line_tol=line_tol
                        )
                        if t is None:
                            continue
                        ax, ay = float(b0[0]), float(b0[1])
                        bx, by = float(b1[0]), float(b1[1])
                        P = (ax + t * (bx - ax), ay + t * (by - ay))
                        si = 0 if vi <= 0 else (
                            max(0, len(pi) - 2) if vi >= len(pi) - 1 else max(0, vi - 1)
                        )
                        return ("pair", i, si, j, sj, P)

    # 共享内点（X 交点落在双方顶点上，段-段严格相交会漏）
    share_tol = max(step * 0.12, line_tol * 1.5)
    vcell = max(share_tol, step * 0.5)
    vbins: Dict[Tuple[int, int], List[Tuple[int, int, float, float]]] = {}
    for i in range(n):
        pi = working[i][1]
        for vi in range(1, len(pi) - 1):
            x, y = float(pi[vi][0]), float(pi[vi][1])
            key = (int(math.floor(x / vcell)), int(math.floor(y / vcell)))
            vbins.setdefault(key, []).append((i, vi, x, y))
    for items in vbins.values():
        if len(items) < 2:
            continue
        for a in range(min(len(items), 24)):
            ia, via, xa, ya = items[a]
            for b in range(a + 1, min(len(items), a + 12)):
                ib, vib, xb, yb = items[b]
                if ia == ib:
                    continue
                if math.hypot(xa - xb, ya - yb) > share_tol:
                    continue
                P = (0.5 * (xa + xb), 0.5 * (ya + yb))
                return ("pair", ia, max(0, via - 1), ib, max(0, vib - 1), P)
    return None


def _polylines_properly_cross(
    a: Sequence[PointTuple], b: Sequence[PointTuple], grid_step: float
) -> bool:
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            if _segment_intersection_point(a[i], a[i + 1], b[j], b[j + 1]) is not None:
                return True
    return False


def _truncate_pair_at_crossing(
    line_i: Sequence[PointTuple],
    si: int,
    line_j: Sequence[PointTuple],
    sj: int,
    P: PointTuple,
    grid_step: float,
) -> Tuple[List[PointTuple], List[PointTuple]]:
    left_i, right_i = _split_and_gap_at(line_i, si, P, grid_step)
    left_j, right_j = _split_and_gap_at(line_j, sj, P, grid_step)
    # 返回各自最长一侧，尽量保留主体
    cand_i = max((left_i, right_i), key=lambda p: _polyline_length(p) if len(p) >= 2 else 0.0)
    cand_j = max((left_j, right_j), key=lambda p: _polyline_length(p) if len(p) >= 2 else 0.0)
    return cand_i, cand_j


def _split_and_gap_at(
    line: Sequence[PointTuple],
    seg_index: int,
    P: PointTuple,
    grid_step: float,
) -> Tuple[List[PointTuple], List[PointTuple]]:
    """在交点处拆开，并沿线段各退回一小段，避免不同级等值线共点。"""
    step = max(float(grid_step), 1e-9)
    gap = max(step * 0.12, 1e-6)
    pts = [(float(p[0]), float(p[1])) for p in line]
    if seg_index < 0 or seg_index >= len(pts) - 1:
        return list(pts), []
    a = pts[seg_index]
    b = pts[seg_index + 1]
    ax, ay = a
    bx, by = b
    px, py = float(P[0]), float(P[1])
    # 从 a→P、P→b 各缩短 gap
    d_ap = math.hypot(px - ax, py - ay)
    d_pb = math.hypot(bx - px, by - py)

    def _pull(from_pt, to_pt, dist_avail):
        if dist_avail <= gap * 1.01:
            return from_pt  # 段太短，退到 from
        t = max(0.0, 1.0 - gap / max(dist_avail, 1e-12))
        return (from_pt[0] + t * (to_pt[0] - from_pt[0]), from_pt[1] + t * (to_pt[1] - from_pt[1]))

    left_end = _pull(a, (px, py), d_ap)
    right_start = _pull(b, (px, py), d_pb)
    left = pts[: seg_index + 1] + [left_end]
    right = [right_start] + pts[seg_index + 1 :]
    left = _dedupe_consecutive_points(left, tolerance=max(step * 1e-6, 1e-9))
    right = _dedupe_consecutive_points(right, tolerance=max(step * 1e-6, 1e-9))
    return left, right


def nearest_direction_context(
    pt: PointTuple,
    directions: Sequence[DirectionLine],
    plateau: float = 0.75,
) -> Optional[Tuple[float, float, float]]:
    """返回最近方向矢量的 (切向单位向量x, y, 有效拉伸比)。

    方向线是**有向矢量**（用户要求）：
    - 方向 = 线段起点 → 终点
    - 大小 = 线段长度（控制拉伸作用的沿程范围）
    - 拉伸从起点开始，沿方向到终点最强；起点前/终点后衰减
    - 垂向距离用 influence_radius 控制走廊宽度
    - ratio 为拉伸强度权重（可调大更夸张）
    """
    best = None
    for direction in directions:
        radius = max(float(direction.influence_radius), 1e-9)
        ratio = max(float(direction.ratio), 1.0)
        priority = int(direction.priority)
        for p0, p1 in _segments(direction.points):
            vx = float(p1[0] - p0[0])
            vy = float(p1[1] - p0[1])
            length = math.hypot(vx, vy)
            if length < 1e-12:
                continue
            unit_x = vx / length
            unit_y = vy / length
            # 相对起点的沿程 / 垂距
            dx = float(pt[0] - p0[0])
            dy = float(pt[1] - p0[1])
            along = dx * unit_x + dy * unit_y  # 0=起点, length=终点
            perp = abs(dx * (-unit_y) + dy * unit_x)
            # 到有向线段的最近距离（垂足夹在 [0,L]）
            along_c = max(0.0, min(length, along))
            cx = float(p0[0]) + along_c * unit_x
            cy = float(p0[1]) + along_c * unit_y
            distance = math.hypot(float(pt[0]) - cx, float(pt[1]) - cy)
            # 走廊：垂向超出半径则无影响；沿程允许略超出终点半径
            if perp > radius and distance > radius:
                continue
            if distance > radius * 1.25:
                continue

            # 沿程包络：起点→终点满幅，起点前弱，终点后按半径衰减
            if along < 0.0:
                # 起点之前：很快衰减（拉伸从起点开始）
                along_env = max(0.0, 1.0 + along / max(radius * 0.25, length * 0.15, 1e-9))
            elif along <= length:
                along_env = 1.0
            else:
                beyond = along - length
                along_env = max(0.0, 1.0 - beyond / max(radius, length * 0.5, 1e-9))

            # 垂向包络（走廊宽度）
            perp_env = _direction_taper(perp if perp > 1e-12 else distance, radius, plateau)
            if along_env <= 1e-6 or perp_env <= 1e-6:
                continue

            # 有效拉伸 = 用户 ratio × 沿程/垂向包络；线段长度通过走廊半径影响范围，不虚抬 ratio
            env = along_env * perp_env
            effective_ratio = 1.0 + (ratio - 1.0) * env

            # 优选：更近、更高优先级、沿程更在线段内
            on_seg_bonus = 0.0 if 0.0 <= along <= length else 0.15 * radius
            rank_dist = distance + on_seg_bonus
            candidate = (rank_dist, priority, unit_x, unit_y, effective_ratio, -env)
            if best is None or candidate[0] < best[0] - 1e-9 or (
                abs(candidate[0] - best[0]) <= 1e-9 and candidate[1] < best[1]
            ) or (
                abs(candidate[0] - best[0]) <= 1e-9
                and candidate[1] == best[1]
                and candidate[5] < best[5]
            ):
                best = candidate
    if best is None:
        return None
    _d, _p, unit_x, unit_y, effective_ratio, _env = best
    if effective_ratio <= 1.0 + 1e-9:
        return None
    return float(unit_x), float(unit_y), float(effective_ratio)


def _direction_taper(distance: float, radius: float, plateau: float) -> float:
    """平台+边缘滑落：距线 <= plateau*R 返回 1，plateau*R~R 线性降到 0。"""
    if radius <= 1e-12:
        return 0.0
    plateau = min(max(float(plateau), 0.0), 0.999)
    ratio_d = float(distance) / radius
    if ratio_d <= plateau:
        return 1.0
    if ratio_d >= 1.0:
        return 0.0
    return (1.0 - ratio_d) / (1.0 - plateau)


def _resolve_direction_radii(
    directions: Sequence[DirectionLine],
    auto_radius: float,
) -> List[DirectionLine]:
    """Preserve direction lines; leave influence_radius<=0 for corridor auto-resolve.

    Legacy callers expected a half-map auto radius here. Curve-corridor mode
    resolves core/influence from well spacing inside ``direction_corridor``;
    we therefore keep <=0 as a sentinel rather than forcing half-map stretch
    everywhere (which made ratio taper away too quickly off-axis).
    """
    if not directions:
        return list(directions)
    resolved: List[DirectionLine] = []
    for direction in directions:
        # Always preserve new optional fields for corridor mode.
        resolved.append(
            DirectionLine(
                line_id=direction.line_id,
                points=direction.points,
                active=direction.active,
                ratio=float(direction.ratio),
                influence_radius=float(direction.influence_radius),
                priority=int(direction.priority),
                core_radius=float(getattr(direction, "core_radius", 0.0) or 0.0),
                zone_id=str(getattr(direction, "zone_id", "") or ""),
                extend_mode=str(getattr(direction, "extend_mode", "auto") or "auto"),
                transition=float(getattr(direction, "transition", 0.0) or 0.0),
            )
        )
    return resolved


def build_direction_field(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    domain_mask: np.ndarray,
    directions: Sequence[DirectionLine],
    plateau: float,
) -> Optional[np.ndarray]:
    """预计算每个网格单元的方向场：(tangent_x, tangent_y, stretch) 三通道。

    stretch = 有效拉伸比 ratio_eff（1.0 表示无拉伸）。补洞/BFS 扩散用它给沿切向
    的邻居加权，使稀疏区扩散也沿方向拉长。域外/无方向影响的单元 stretch=1。
    """
    if not directions or len(x_coords) < 2 or len(y_coords) < 2:
        return None
    rows = len(y_coords)
    cols = len(x_coords)
    field = np.zeros((rows, cols, 3), dtype=float)
    field[:, :, 2] = 1.0
    has_any = False
    for row in range(rows):
        y = float(y_coords[row])
        for col in range(cols):
            if not domain_mask[row, col]:
                continue
            context = nearest_direction_context((float(x_coords[col]), y), directions, plateau)
            if context is None:
                continue
            unit_x, unit_y, ratio_eff = context
            if ratio_eff <= 1.0 + 1e-9:
                continue
            field[row, col, 0] = unit_x
            field[row, col, 1] = unit_y
            field[row, col, 2] = ratio_eff
            has_any = True
    return field if has_any else None


def anisotropic_distance(
    origin: PointTuple,
    target: PointTuple,
    unit_x: float,
    unit_y: float,
    ratio: float,
    perpendicular_scale: float = 1.0,
) -> float:
    vx = target[0] - origin[0]
    vy = target[1] - origin[1]
    u = vx * unit_x + vy * unit_y
    v = vx * (-unit_y) + vy * unit_x
    cross = max(float(perpendicular_scale), 1.0)
    return math.sqrt((u / max(ratio, 1.0)) ** 2 + (v * cross) * (v * cross))


def direction_perpendicular_scale(ratio: float, strength: float) -> float:
    """Return cross-axis scale for directional IDW.

    ``ratio`` shortens along-axis distance. This companion scale increases
    cross-axis distance, making the trend surface visibly elongated along the
    direction line instead of merely giving a weak preference to along-line
    wells.
    """
    return 1.0 + max(float(ratio) - 1.0, 0.0) * max(float(strength), 0.0)


def direction_corridor_weight(
    offset_x: float,
    offset_y: float,
    unit_x: float,
    unit_y: float,
    ratio: float,
    base_radius: float,
    strength: float,
) -> float:
    """Boost wells that lie in the local direction-line fairway.

    Direction lines are geological corridors for sandbody continuity. The IDW
    distance already shortens along-axis distance; this weight makes same-axis
    candidate wells more competitive and prevents nearby cross-axis wells from
    washing out the elongation.
    """
    stretch = max(float(ratio) - 1.0, 0.0)
    strength = max(float(strength), 0.0)
    if stretch <= 0.0 or strength <= 0.0:
        return 1.0

    cross = abs(float(offset_x) * (-float(unit_y)) + float(offset_y) * float(unit_x))
    corridor_width = max(float(base_radius) / max(float(ratio), 1.0), 1e-9)
    taper = 1.0 / (1.0 + (cross / corridor_width) ** 2)
    # 轻度走廊加权；过大 strength 会在趋势面上拉出斜向“水波纹”
    boost = stretch * strength * taper
    return 1.0 + boost


def closest_point_on_segment(
    pt: PointTuple,
    a: PointTuple,
    b: PointTuple,
) -> Tuple[PointTuple, float, PointTuple]:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-24:
        return a, math.hypot(px - ax, py - ay), (1.0, 0.0)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    closest = (ax + t * dx, ay + t * dy)
    length = math.sqrt(length_sq)
    return closest, math.hypot(px - closest[0], py - closest[1]), (dx / length, dy / length)


def extend_barriers_for_partition(
    barriers: Sequence[BarrierLine],
    extension_distance: float,
) -> List[BarrierLine]:
    """Return barrier copies with endpoints extended for raster partitioning.

    Hand-drawn partition lines often stop a little short of the map boundary.
    Extending only the computational wall by ``extension_distance`` makes the
    region split robust without changing the stored/displayed barrier geometry.
    Pass the map diagonal length to force every barrier to reach (and cross)
    the boundary, turning a half-drawn barrier into a full partition line.
    """
    if not barriers or extension_distance <= 0:
        return list(barriers)

    extended: List[BarrierLine] = []
    distance = float(extension_distance)
    for barrier in barriers:
        points = list(barrier.points)
        if len(points) < 2:
            extended.append(barrier)
            continue

        start = points[0]
        next_pt = points[1]
        start_dx = start[0] - next_pt[0]
        start_dy = start[1] - next_pt[1]
        start_len = math.hypot(start_dx, start_dy)
        if start_len > 1e-12:
            points[0] = (
                start[0] + start_dx / start_len * distance,
                start[1] + start_dy / start_len * distance,
            )

        end = points[-1]
        prev = points[-2]
        end_dx = end[0] - prev[0]
        end_dy = end[1] - prev[1]
        end_len = math.hypot(end_dx, end_dy)
        if end_len > 1e-12:
            points[-1] = (
                end[0] + end_dx / end_len * distance,
                end[1] + end_dy / end_len * distance,
            )

        extended.append(
            BarrierLine(
                line_id=barrier.line_id,
                points=tuple(points),
                active=barrier.active,
                block_mode=barrier.block_mode,
                priority=barrier.priority,
            )
        )
    return extended


def build_barrier_proximity_mask(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    dilation_cells: int = 2,
) -> Optional[np.ndarray]:
    """标记打断线附近的网格单元，供邻域平滑/补洞做相交检测预过滤。

    只有与打断线相距 dilation_cells 个网格步长以内的单元才需要逐邻居判交，
    其余单元可跳过昂贵的线段求交，保证大网格下平滑仍然够快。
    """
    if not barriers or len(x_coords) < 2 or len(y_coords) < 2:
        return None

    x0 = float(x_coords[0])
    y0 = float(y_coords[0])
    dx = float(x_coords[1] - x_coords[0]) or 1.0
    dy = float(y_coords[1] - y_coords[0]) or 1.0
    rows = len(y_coords)
    cols = len(x_coords)
    mask = np.zeros((rows, cols), dtype=bool)
    sample_step = min(abs(dx), abs(dy)) * 0.5

    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            samples = max(2, int(length / max(sample_step, 1e-9)) + 2)
            for i in range(samples):
                t = i / (samples - 1)
                px = p0[0] + t * (p1[0] - p0[0])
                py = p0[1] + t * (p1[1] - p0[1])
                col = int(round((px - x0) / dx))
                row = int(round((py - y0) / dy))
                r0 = max(0, row - dilation_cells)
                r1 = min(rows - 1, row + dilation_cells)
                c0 = max(0, col - dilation_cells)
                c1 = min(cols - 1, col + dilation_cells)
                if r1 < r0 or c1 < c0:
                    continue
                mask[r0:r1 + 1, c0:c1 + 1] = True
    return mask


def build_region_labels(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    domain_mask: np.ndarray,
    barriers: Sequence[BarrierLine],
    near_barrier_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """按打断线把成图域分割为连通子区域，返回每个网格单元的区域标号（域外 = -1）。

    4 邻接泛洪填充；相邻单元中心连线与打断线相交则视为不连通。
    贯穿成图区的打断线把区域一分为二，未贯穿的不改变连通性。
    """
    from collections import deque

    rows, cols = domain_mask.shape
    labels = np.full((rows, cols), -1, dtype=int)
    if not bool(domain_mask.any()):
        return labels

    current = 0
    for seed_row in range(rows):
        for seed_col in range(cols):
            if not domain_mask[seed_row, seed_col] or labels[seed_row, seed_col] >= 0:
                continue
            labels[seed_row, seed_col] = current
            queue = deque([(seed_row, seed_col)])
            while queue:
                row, col = queue.popleft()
                center = (float(x_coords[col]), float(y_coords[row]))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr = row + dr
                    nc = col + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    if not domain_mask[nr, nc] or labels[nr, nc] >= 0:
                        continue
                    if barriers and (
                        near_barrier_mask is None
                        or near_barrier_mask[row, col]
                        or near_barrier_mask[nr, nc]
                    ):
                        neighbor = (float(x_coords[nc]), float(y_coords[nr]))
                        if is_blocked_by_barrier(center, neighbor, barriers, 1e-9):
                            continue
                    labels[nr, nc] = current
                    queue.append((nr, nc))
            current += 1
    return labels


def assign_well_regions(
    well_xy: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    region_labels: np.ndarray,
) -> np.ndarray:
    """井点 → 所在网格单元的区域号；附近找不到已标号单元时返回 -2（参与所有区域）。"""
    count = len(well_xy)
    out = np.full(count, -2, dtype=int)
    if region_labels.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return out

    x0 = float(x_coords[0])
    y0 = float(y_coords[0])
    dx = float(x_coords[1] - x_coords[0]) or 1.0
    dy = float(y_coords[1] - y_coords[0]) or 1.0
    rows, cols = region_labels.shape

    for index in range(count):
        wx = float(well_xy[index, 0])
        wy = float(well_xy[index, 1])
        col = int(round((wx - x0) / dx))
        row = int(round((wy - y0) / dy))
        found = -2
        for radius in range(0, 4):
            best_label = None
            best_dist = None
            r0 = max(0, row - radius)
            r1 = min(rows - 1, row + radius)
            c0 = max(0, col - radius)
            c1 = min(cols - 1, col + radius)
            if r1 < r0 or c1 < c0:
                continue
            for rr in range(r0, r1 + 1):
                for cc in range(c0, c1 + 1):
                    label = int(region_labels[rr, cc])
                    if label < 0:
                        continue
                    dist = (float(x_coords[cc]) - wx) ** 2 + (float(y_coords[rr]) - wy) ** 2
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_label = label
            if best_label is not None:
                found = best_label
                break
        out[index] = found
    return out


def apply_barrier_gradient_fade(
    grid_z: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    blank_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """在缓冲区内对趋势面值进行从打断线(0)到缓冲边界的平滑渐变。

    使缓冲区显示渐变打断效果，而不是硬0/空。
    """
    if buffer_distance <= 0 or not barriers or grid_z.size == 0:
        return grid_z
    result = grid_z.copy()
    rows, cols = result.shape
    dx = float(x_coords[1] - x_coords[0]) if len(x_coords) > 1 else 1.0
    dy = float(y_coords[1] - y_coords[0]) if len(y_coords) > 1 else 1.0
    sample_step = min(abs(dx), abs(dy)) * 0.3
    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if length < 1e-9:
                continue
            samples = max(3, int(length / max(sample_step, 1e-9)) + 2)
            for i in range(samples):
                t = i / (samples - 1)
                px = p0[0] + t * (p1[0] - p0[0])
                py = p0[1] + t * (p1[1] - p0[1])
                col = int(round((px - x_coords[0]) / dx))
                row = int(round((py - y_coords[0]) / dy))
                r0 = max(0, row - 2)
                r1 = min(rows - 1, row + 2)
                c0 = max(0, col - 2)
                c1 = min(cols - 1, col + 2)
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        if blank_mask is not None and not blank_mask[rr, cc]:
                            continue
                        if not math.isfinite(result[rr, cc]):
                            continue
                        center = (float(x_coords[cc]), float(y_coords[rr]))
                        dist = _point_to_segment_distance(center, p0, p1)
                        if dist > buffer_distance:
                            continue
                        fade = max(0.0, min(1.0, dist / buffer_distance))
                        result[rr, cc] *= fade
    return result


def _point_to_segment_distance(pt: PointTuple, a: PointTuple, b: PointTuple) -> float:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    projx = ax + t * dx
    projy = ay + t * dy
    return math.hypot(px - projx, py - projy)


def build_barrier_blank_mask(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    blank_distance: float,
    domain_mask: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """标记打断线屏蔽缓冲内的网格单元（胶囊/体育场形）。

    这些单元不参与插值也不被补洞，等值线在打断线附近自然断开。
    形状：中段恒宽矩形缓冲 + 两端椭圆（圆）端帽，合为一体；
    可选 domain_mask（通常为成图边界）裁切，缓冲不得出边界外。
    """
    if not barriers or blank_distance <= 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return None

    rows = len(y_coords)
    cols = len(x_coords)
    R = float(blank_distance)
    mask = np.zeros((rows, cols), dtype=bool)
    domain = None
    if domain_mask is not None:
        domain = np.asarray(domain_mask, dtype=bool)
        if domain.shape != (rows, cols):
            domain = None

    for barrier in barriers:
        pts = list(getattr(barrier, "points", ()) or ())
        # The reference implementation only blanks for polylines with >= 2
        # points (its sampling loop emits no cells for single points).
        if len(pts) < 2:
            continue
        # Vectorized stadium distance: for every grid cell, the distance to the
        # nearest point of the polyline (min over segments of the clamped
        # point-to-segment distance).  This replicates the per-cell
        # _point_within_polyline_stadium_buffer semantics exactly.
        arr_pts = np.asarray(pts, dtype=float)
        seg_ax = arr_pts[:-1, 0]
        seg_ay = arr_pts[:-1, 1]
        seg_bx = arr_pts[1:, 0]
        seg_by = arr_pts[1:, 1]
        seg_len = np.hypot(seg_bx - seg_ax, seg_by - seg_ay)
        cell_xx = np.asarray(x_coords, dtype=float)[None, :]  # (1, cols)
        cell_yy = np.asarray(y_coords, dtype=float)[:, None]  # (rows, 1)
        # (rows, cols, segments) would be too big on fine grids; iterate
        # segments and keep a running per-cell minimum.
        best_d = np.full((rows, cols), np.inf, dtype=float)
        for i in range(len(seg_len)):
            ax, ay = seg_ax[i], seg_ay[i]
            bx, by = seg_bx[i], seg_by[i]
            length = float(seg_len[i])
            if length <= 1e-12:
                d = np.hypot(cell_xx - ax, cell_yy - ay)
            else:
                ux, uy = (bx - ax) / length, (by - ay) / length
                along = (cell_xx - ax) * ux + (cell_yy - ay) * uy
                t = np.clip(along / length, 0.0, 1.0)
                cxp = ax + t * (bx - ax)
                cyp = ay + t * (by - ay)
                d = np.hypot(cell_xx - cxp, cell_yy - cyp)
            np.minimum(best_d, d, out=best_d)
        cell_hit = best_d <= R + 1e-12
        if domain is not None:
            cell_hit &= domain
        mask |= cell_hit
    return mask if bool(mask.any()) else None


def _anisotropic_fill_multiplier(dr: int, dc: int, field_entry, aspect: float) -> float:
    """沿方向线切向的邻居权重放大系数（各向异性扩散）。

    field_entry = (tangent_x, tangent_y, stretch)。offset 在地图方向上越贴近切向，
    放大越强（最强 = stretch），使补洞扩散沿方向拉长而非各向同性变圆。
    """
    stretch = float(field_entry[2])
    if stretch <= 1.0 + 1e-9:
        return 1.0
    ox = float(dc)
    oy = float(dr) * aspect
    norm = math.hypot(ox, oy)
    if norm <= 1e-12:
        return 1.0
    align = abs(ox * float(field_entry[0]) + oy * float(field_entry[1])) / norm
    return 1.0 + (stretch - 1.0) * align


def fill_internal_gaps(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    domain_mask: np.ndarray,
    iterations: int,
    value_min: Optional[float],
    value_max: Optional[float],
    barriers: Sequence[BarrierLine] = (),
    near_barrier_mask: Optional[np.ndarray] = None,
    region_labels: Optional[np.ndarray] = None,
    direction_field: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, int]:
    """Fill small invalid holes inside the interpolation domain before contouring.

    传入 barriers / region_labels 时补洞只在同区域内取邻居值，
    不会引用打断线另一侧的值，避免硬打断被补值抹平。
    传入 direction_field 时沿方向线切向的邻居权重放大，扩散沿方向拉长。
    """
    result = np.array(grid, dtype=float, copy=True)
    if result.size == 0 or iterations <= 0:
        return result, 0

    fillable_mask = np.asarray(domain_mask, dtype=bool) & ~np.isfinite(result)
    if not bool(fillable_mask.any()):
        return result, 0

    step_x = abs(float(x_coords[1] - x_coords[0])) if len(x_coords) > 1 else 1.0
    step_y = abs(float(y_coords[1] - y_coords[0])) if len(y_coords) > 1 else step_x
    aspect = step_y / step_x if step_x > 1e-12 else 1.0

    original_nan = fillable_mask.copy()
    offsets = (
        (-1, 0, 2.0),
        (1, 0, 2.0),
        (0, -1, 2.0),
        (0, 1, 2.0),
        (-1, -1, 1.0),
        (-1, 1, 1.0),
        (1, -1, 1.0),
        (1, 1, 1.0),
    )
    rows, cols = result.shape
    for pass_index in range(max(0, int(iterations))):
        next_grid = result.copy()
        changed = 0
        min_neighbors = 2 if pass_index < max(0, int(iterations)) - 1 else 1
        for row in range(rows):
            for col in range(cols):
                if not fillable_mask[row, col] or math.isfinite(float(result[row, col])):
                    continue
                check_barrier = bool(barriers) and (
                    near_barrier_mask is None or bool(near_barrier_mask[row, col])
                )
                center = (float(x_coords[col]), float(y_coords[row])) if check_barrier else None
                field_entry = direction_field[row, col] if direction_field is not None else None
                weighted_sum = 0.0
                weight_sum = 0.0
                neighbor_count = 0
                for dr, dc, weight in offsets:
                    nr = row + dr
                    nc = col + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    value = float(result[nr, nc])
                    if not math.isfinite(value):
                        continue
                    if region_labels is not None and region_labels[nr, nc] != region_labels[row, col]:
                        continue
                    if check_barrier:
                        neighbor = (float(x_coords[nc]), float(y_coords[nr]))
                        if is_blocked_by_barrier(center, neighbor, barriers, 1e-9):
                            continue
                    eff_weight = weight
                    if field_entry is not None:
                        eff_weight *= _anisotropic_fill_multiplier(dr, dc, field_entry, aspect)
                    weighted_sum += value * eff_weight
                    weight_sum += eff_weight
                    neighbor_count += 1
                if neighbor_count >= min_neighbors and weight_sum > 0:
                    value = weighted_sum / weight_sum
                    if value_min is not None:
                        value = max(float(value_min), value)
                    if value_max is not None:
                        value = min(float(value_max), value)
                    next_grid[row, col] = value
                    changed += 1
        result = next_grid
        if changed == 0:
            break

    filled_count = int(np.count_nonzero(original_nan & np.isfinite(result)))
    outside_domain = ~np.asarray(domain_mask, dtype=bool)
    result[outside_domain] = np.nan
    return result, filled_count


def complete_gap_fill(
    grid: np.ndarray,
    domain_mask: np.ndarray,
    region_labels: Optional[np.ndarray],
    value_min: Optional[float],
    value_max: Optional[float],
    direction_field: Optional[np.ndarray] = None,
    cell_aspect: float = 1.0,
    barriers: Sequence[BarrierLine] = (),
    x_coords: Optional[np.ndarray] = None,
    y_coords: Optional[np.ndarray] = None,
    near_barrier_mask: Optional[np.ndarray] = None,
    exclusion_mask: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, int]:
    """BFS 扩散补全：把成图域内所有仍为 NaN 的单元从有值边界向外逐层填满。

    保证每个区域内趋势面完整（等值线只在打断线和图幅边界处终止）。
    区域内没有任何有值单元时（无井区域）保持 NaN。
    传入 direction_field 时沿方向线切向的邻居权重放大，扩散沿方向拉长。
    """
    from collections import deque

    result = np.array(grid, dtype=float, copy=True)
    if result.size == 0:
        return result, 0
    domain = np.asarray(domain_mask, dtype=bool)
    if exclusion_mask is not None:
        domain = domain & ~np.asarray(exclusion_mask, dtype=bool)
    remaining = domain & ~np.isfinite(result)
    if not bool(remaining.any()):
        return result, 0

    rows, cols = result.shape
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    aspect = float(cell_aspect) if cell_aspect > 1e-12 else 1.0

    def same_region(r0, c0, r1, c1) -> bool:
        if region_labels is None:
            return True
        return bool(region_labels[r0, c0] == region_labels[r1, c1])

    # 种子：与有值单元相邻的 NaN 域内单元
    queue = deque()
    queued = np.zeros((rows, cols), dtype=bool)
    for row in range(rows):
        for col in range(cols):
            if not remaining[row, col]:
                continue
            for dr, dc in offsets:
                nr, nc = row + dr, col + dc
                if 0 <= nr < rows and 0 <= nc < cols \
                        and math.isfinite(float(result[nr, nc])) \
                        and same_region(row, col, nr, nc):
                    queue.append((row, col))
                    queued[row, col] = True
                    break

    check_barrier = bool(barriers) and x_coords is not None and y_coords is not None
    filled = 0
    while queue:
        row, col = queue.popleft()
        if math.isfinite(float(result[row, col])):
            continue
        field_entry = direction_field[row, col] if direction_field is not None else None
        center = (
            (float(x_coords[col]), float(y_coords[row]))
            if check_barrier and (near_barrier_mask is None or bool(near_barrier_mask[row, col]))
            else None
        )
        weighted_sum = 0.0
        weight_sum = 0.0
        for dr, dc in offsets:
            nr, nc = row + dr, col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            if exclusion_mask is not None and bool(exclusion_mask[nr, nc]):
                continue
            value = float(result[nr, nc])
            if not math.isfinite(value) or not same_region(row, col, nr, nc):
                continue
            if center is not None:
                neighbor = (float(x_coords[nc]), float(y_coords[nr]))
                if is_blocked_by_barrier(center, neighbor, barriers, 1e-9):
                    continue
            weight = 2.0 if dr == 0 or dc == 0 else 1.0
            if field_entry is not None:
                weight *= _anisotropic_fill_multiplier(dr, dc, field_entry, aspect)
            weighted_sum += value * weight
            weight_sum += weight
        if weight_sum <= 0:
            continue
        value = weighted_sum / weight_sum
        if value_min is not None:
            value = max(float(value_min), value)
        if value_max is not None:
            value = min(float(value_max), value)
        result[row, col] = value
        filled += 1
        for dr, dc in offsets:
            nr, nc = row + dr, col + dc
            if 0 <= nr < rows and 0 <= nc < cols and domain[nr, nc] \
                    and not queued[nr, nc] and not math.isfinite(float(result[nr, nc])) \
                    and same_region(row, col, nr, nc):
                queue.append((nr, nc))
                queued[nr, nc] = True
    return result, filled


def prepare_contour_extraction_surface(
    contour_grid: np.ndarray,
    support_mask: np.ndarray,
    region_labels: Optional[np.ndarray],
    value_min: Optional[float],
    value_max: Optional[float],
    *,
    direction_field: Optional[np.ndarray] = None,
    cell_aspect: float = 1.0,
    barriers: Sequence[BarrierLine] = (),
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    near_barrier_mask: Optional[np.ndarray] = None,
    exclusion_mask: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, int]:
    """Build a support-local continuous surface used only for contour extraction.

    Display still uses the strict ``contour_grid`` mask. Values propagate only
    inside the extraction support mask (component-dilated domain including small
    NaN holes) so marching squares can close loops near wells without flooding
    large no-well void pockets outside the support.
    """
    from drawing.single_factor.masks import (
        build_bfs_reach_mask,
        build_contour_hole_fill_mask,
        resolve_contour_hole_fill_max_cells,
    )

    working = np.array(contour_grid, dtype=float, copy=True)
    support = np.asarray(support_mask, dtype=bool)
    if not bool(support.any()):
        return working, 0

    grid_resolution = max(len(x_coords), len(y_coords))
    # Larger reach so well clusters form continuous extraction surfaces for
    # nested closed isolines (green-sketch / Enping style).
    fill_reach_cells = min(48.0, max(16.0, float(grid_resolution) * 0.16))
    seeds = support & np.isfinite(working)
    fill_domain = build_bfs_reach_mask(seeds, support, fill_reach_cells)
    # Explicitly re-admit small enclosed holes even if BFS reach is conservative.
    max_hole_cells = resolve_contour_hole_fill_max_cells(grid_resolution, fill_reach_cells)
    small_holes = build_contour_hole_fill_mask(support, working, max_hole_cells)
    fill_domain = fill_domain | small_holes
    if exclusion_mask is not None:
        fill_domain &= ~np.asarray(exclusion_mask, dtype=bool)
    fillable = fill_domain & ~np.isfinite(working)
    if not bool(fillable.any()):
        working[~support] = np.nan
        return working, 0

    fill_iterations = max(16, int(math.ceil(fill_reach_cells * 1.5)))
    working, fill1 = fill_internal_gaps(
        working,
        x_coords,
        y_coords,
        fill_domain,
        fill_iterations,
        value_min,
        value_max,
        barriers=barriers,
        near_barrier_mask=near_barrier_mask,
        region_labels=region_labels,
        direction_field=direction_field,
    )
    working, fill2 = complete_gap_fill(
        working,
        fill_domain,
        region_labels,
        value_min,
        value_max,
        direction_field=direction_field,
        cell_aspect=cell_aspect,
        barriers=barriers,
        x_coords=x_coords,
        y_coords=y_coords,
        near_barrier_mask=near_barrier_mask,
        exclusion_mask=exclusion_mask,
    )
    working[~support] = np.nan
    return working, int(fill1 + fill2)


def finalize_contour_loop_closure(
    contours: Dict[float, List[List[PointTuple]]],
    surface_grid: np.ndarray,
    surface_x: np.ndarray,
    surface_y: np.ndarray,
    grid_step: float,
    *,
    barriers: Sequence[BarrierLine] = (),
    barrier_proximity: float = 0.0,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """Force-close drafting gaps left by masking, barrier trimming, or smoothing.

    Uses path/chord geometry to close *ring-like* open arcs (nested highs) while
    rejecting long false diagonals and outer-rim self-joins.

    老师要求：两端贴在打断线附近的等值线禁止自闭合（保持开放止于缓冲外缘）。
    """
    closed_total = 0
    step = max(float(grid_step), 1e-9)
    proximity = max(float(barrier_proximity), 0.0)
    # Bridge only small fragment seams; ring closure uses smarter path/chord rules.
    bridge_gap = max(step * 3.0, 1e-9)
    close_gap = max(step * 8.0, 1e-9)
    finalized: Dict[float, List[List[PointTuple]]] = {}

    barrier_margin = max(step * 12.0, proximity * 1.5, 1e-9)

    for level, lines in contours.items():
        relaxed: List[List[PointTuple]] = []
        for raw_line in lines:
            line = _dedupe_consecutive_points(raw_line, tolerance=max(step * 1e-6, 1e-9))
            # 打开错误封口：长弦、外缘假闭合，以及贴打断线的 U 形封口
            if len(line) >= 4 and _is_closed_polyline(line, step):
                if (
                    _closed_ring_should_reopen_near_barrier(line, barriers, barrier_margin)
                    or _has_suspicious_closing_chord(line, step)
                    or _is_false_outer_rim_close(
                        line[0],
                        line[-2],
                        surface_grid,
                        surface_x,
                        surface_y,
                        step,
                        barriers=barriers,
                    )
                ):
                    line = line[:-1]
            if len(line) >= 3 and not _is_closed_polyline(line, step):
                if _should_force_close_contour(
                    line,
                    close_gap,
                    step,
                    barriers=barriers,
                    surface_grid=surface_grid,
                    surface_x=surface_x,
                    surface_y=surface_y,
                    barrier_proximity=proximity,
                ):
                    line = _seal_open_contour(line, barriers, step)
                    closed_total += 1
            relaxed.append(line)

        bridged, _bridge_count = _bridge_contour_gaps(
            relaxed,
            bridge_gap,
            step,
            barriers=barriers,
        )
        # Second pass after bridge — assemble multi-fragment rings then close.
        closed_lines, close_count = _close_near_contour_loops(
            bridged,
            close_gap,
            step,
            barriers=barriers,
            surface_grid=surface_grid,
            surface_x=surface_x,
            surface_y=surface_y,
            barrier_proximity=proximity,
        )
        closed_total += int(close_count)
        # Extra ring-formation pass for nested highs (path/chord based).
        closed_lines, ring_count = _form_nested_isoline_rings(
            closed_lines,
            step,
            barriers=barriers,
            surface_grid=surface_grid,
            surface_x=surface_x,
            surface_y=surface_y,
            barrier_proximity=proximity,
        )
        closed_total += int(ring_count)

        # 最终保险：凡贴打断线的假闭合一律拆开
        cleaned: List[List[PointTuple]] = []
        for line in closed_lines:
            if len(line) >= 4 and _is_closed_polyline(line, step):
                if _closed_ring_should_reopen_near_barrier(line, barriers, barrier_margin):
                    line = line[:-1]
                    closed_total = max(0, closed_total - 1)
            cleaned.append(line)
        finalized[float(level)] = cleaned

    return finalized, int(closed_total)


def _form_nested_isoline_rings(
    lines: Sequence[List[PointTuple]],
    grid_step: float,
    *,
    barriers: Sequence[BarrierLine] = (),
    surface_grid: Optional[np.ndarray] = None,
    surface_x: Optional[np.ndarray] = None,
    surface_y: Optional[np.ndarray] = None,
    barrier_proximity: float = 0.0,
) -> Tuple[List[List[PointTuple]], int]:
    """Close open polylines that are geometrically ring-like (nested high cores).

    Criterion: long curved path with a relatively short endpoint chord — nested
    bullseye pattern — without long false diagonals.

    两端贴打断线时禁止封口（交由 _should_force_close_contour 硬拒绝）。
    """
    step = max(float(grid_step), 1e-9)
    proximity = max(float(barrier_proximity), 0.0)
    closed_count = 0
    output: List[List[PointTuple]] = []
    for raw in lines:
        line = list(raw)
        if len(line) < 4 or _is_closed_polyline(line, step):
            output.append(line)
            continue
        gap = _point_distance(line[0], line[-1])
        path = _polyline_length(line)
        if path < step * 8.0 or gap < 1e-12:
            output.append(line)
            continue
        path_chord = path / max(gap, 1e-12)
        # Ring-like: walks a long curve but ends nearly meet.
        if path_chord < 3.5:
            output.append(line)
            continue
        xs = [float(p[0]) for p in line]
        ys = [float(p[1]) for p in line]
        bbox_diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        if gap > max(step * 4.0, bbox_diag * 0.22):
            output.append(line)
            continue
        chord_cap = min(step * 12.0, path * 0.18, max(step * 4.0, bbox_diag * 0.22))
        if gap > chord_cap:
            output.append(line)
            continue
        if _should_force_close_contour(
            line,
            max_gap=chord_cap,
            grid_step=step,
            barriers=barriers,
            surface_grid=surface_grid,
            surface_x=surface_x,
            surface_y=surface_y,
            max_gap_ratio=0.28,
            max_gap_vs_length=0.20,
            barrier_proximity=proximity,
        ):
            line = _seal_open_contour(line, barriers, step)
            closed_count += 1
        output.append(line)
    return output, closed_count


def _contour_ends_on_data_boundary(
    start: PointTuple,
    end: PointTuple,
    surface_grid: Optional[np.ndarray],
    surface_x: Optional[np.ndarray],
    surface_y: Optional[np.ndarray],
    grid_step: float,
    *,
    margin_cells: float = 2.5,
) -> bool:
    """True when both endpoints lie on / next to the finite surface edge."""
    if surface_grid is None or surface_x is None or surface_y is None:
        return False
    return _point_near_finite_surface_edge(
        start, surface_grid, surface_x, surface_y, grid_step, margin_cells=margin_cells
    ) and _point_near_finite_surface_edge(
        end, surface_grid, surface_x, surface_y, grid_step, margin_cells=margin_cells
    )


def _point_near_finite_surface_edge(
    pt: PointTuple,
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    grid_step: float,
    *,
    margin_cells: float = 2.5,
) -> bool:
    """True if ``pt`` is outside the finite surface or within ``margin_cells`` of a NaN."""
    if grid.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return False
    x = float(pt[0])
    y = float(pt[1])
    # Outside / non-finite sample counts as boundary termination.
    if sample_bilinear_grid(grid, x_coords, y_coords, x, y) is None:
        return True

    col = int(np.argmin(np.abs(np.asarray(x_coords, dtype=float) - x)))
    row = int(np.argmin(np.abs(np.asarray(y_coords, dtype=float) - y)))
    radius = max(1, int(math.ceil(float(margin_cells))))
    rows, cols = grid.shape
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            nr, nc = row + dr, col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                return True
            if not math.isfinite(float(grid[nr, nc])):
                return True
    return False


def _absolute_close_gap_cap(max_gap: float, grid_step: float) -> float:
    """Hard cap on endpoint gap for force-close / micro-bridge (map units)."""
    step = max(float(grid_step), 1e-9)
    # Prefer caller max_gap when provided (ring-formation passes a path-aware cap).
    return min(max(float(max_gap), 0.0), step * 14.0)


def _both_endpoints_near_barriers(
    start: PointTuple,
    end: PointTuple,
    barriers: Sequence[BarrierLine],
    max_distance: float,
) -> bool:
    if not barriers or max_distance <= 0.0:
        return False
    return (
        _point_distance_to_barriers(start, barriers) <= max_distance
        and _point_distance_to_barriers(end, barriers) <= max_distance
    )


def _either_endpoint_near_barriers(
    start: PointTuple,
    end: PointTuple,
    barriers: Sequence[BarrierLine],
    max_distance: float,
) -> bool:
    """任一端点靠近打断线即视为贴线（防单端贴线仍被强行闭合）。"""
    if not barriers or max_distance <= 0.0:
        return False
    return (
        _point_distance_to_barriers(start, barriers) <= max_distance
        or _point_distance_to_barriers(end, barriers) <= max_distance
    )


def _closed_ring_should_reopen_near_barrier(
    line: Sequence[PointTuple],
    barriers: Sequence[BarrierLine],
    margin: float,
) -> bool:
    """已闭合环若因贴打断线形成假封口，应拆开。"""
    if not barriers or len(line) < 4 or margin <= 0.0:
        return False
    # 闭合环：line[0]≈line[-1]，检查开口两端（首点与倒数第二点）
    a = line[0]
    b = line[-2]
    if _either_endpoint_near_barriers(a, b, barriers, margin):
        return True
    # 封口弦本身穿过/贴近打断线
    if is_blocked_by_barrier(a, b, barriers, endpoint_tolerance=1e-7):
        return True
    # 中点靠近打断线且弦较长 → 典型 U 形假闭合
    step_like = max(margin / 8.0, 1e-9)
    chord = _point_distance(a, b)
    if chord >= step_like * 3.0:
        mid = ((float(a[0]) + float(b[0])) * 0.5, (float(a[1]) + float(b[1])) * 0.5)
        if _point_distance_to_barriers(mid, barriers) <= margin * 0.85:
            return True
    return False


def _is_false_outer_rim_close(
    start: PointTuple,
    end: PointTuple,
    surface_grid: Optional[np.ndarray],
    surface_x: Optional[np.ndarray],
    surface_y: Optional[np.ndarray],
    grid_step: float,
    *,
    barriers: Sequence[BarrierLine] = (),
) -> bool:
    """Ends on finite surface/formation edge → treat as false outer-rim join.

    老师要求：贴打断线的封口同样视为应打开的假闭合（不要因硬约束而自闭合）。
    """
    del barriers  # 保留参数兼容调用方；外缘一律视为假闭合
    if not _contour_ends_on_data_boundary(
        start, end, surface_grid, surface_x, surface_y, grid_step
    ):
        return False
    return True


def _has_suspicious_closing_chord(line: Sequence[PointTuple], grid_step: float) -> bool:
    """True if the last edge of a closed ring is much longer than typical edges.

    Catches false first↔last joins that insert a long straight diagonal.
    """
    if len(line) < 5 or not _is_closed_polyline(line, grid_step):
        return False
    # Closed ring: ... -> p[-2] -> p[-1]==p[0]
    close_len = _point_distance(line[-2], line[0])
    edge_lens = [
        _point_distance(line[i], line[i + 1])
        for i in range(len(line) - 2)
        if _point_distance(line[i], line[i + 1]) > 1e-12
    ]
    if not edge_lens:
        return False
    edge_lens_sorted = sorted(edge_lens)
    median = edge_lens_sorted[len(edge_lens_sorted) // 2]
    mean = sum(edge_lens) / len(edge_lens)
    step = max(float(grid_step), 1e-9)
    return close_len > max(step * 5.0, median * 5.0, mean * 4.0)


def _nearest_point_on_barriers(
    pt: PointTuple,
    barriers: Sequence[BarrierLine],
) -> Tuple[Optional[PointTuple], Optional[str], float]:
    """Return (projected_point, barrier_id, distance) for the nearest barrier segment."""
    best_pt: Optional[PointTuple] = None
    best_id: Optional[str] = None
    best_d = math.inf
    for barrier in barriers:
        bid = str(getattr(barrier, "line_id", "") or id(barrier))
        for a, b in _segments(barrier.points):
            projection = _project_point_to_segment(pt, a, b)
            if projection is None:
                continue
            _t, closest = projection
            dist = math.hypot(float(pt[0]) - float(closest[0]), float(pt[1]) - float(closest[1]))
            if dist < best_d:
                best_d = dist
                best_pt = (float(closest[0]), float(closest[1]))
                best_id = bid
    if best_pt is None:
        return None, None, math.inf
    return best_pt, best_id, float(best_d)


def _barrier_seal_midpoints(
    start: PointTuple,
    end: PointTuple,
    barriers: Sequence[BarrierLine],
    grid_step: float,
) -> List[PointTuple]:
    """Sample a short path along the shared barrier between two endpoint projections.

    Avoids a long diagonal chord cutting through a nested high when the open nick
    sits against 打断线.
    """
    if not barriers:
        return []
    step = max(float(grid_step), 1e-9)
    p0, id0, d0 = _nearest_point_on_barriers(start, barriers)
    p1, id1, d1 = _nearest_point_on_barriers(end, barriers)
    if p0 is None or p1 is None or id0 is None or id1 is None:
        return []
    if id0 != id1:
        return []
    # Only walk the barrier when projections are meaningfully apart.
    along = _point_distance(p0, p1)
    if along < step * 0.75:
        return []
    # Keep seal path short — this is a nick, not a map-crossing join.
    if along > step * 28.0:
        return []
    n = max(1, min(12, int(math.ceil(along / max(step * 1.5, 1e-9)))))
    mids: List[PointTuple] = []
    for i in range(1, n + 1):
        t = i / (n + 1)
        mids.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))
    # Pull midpoints slightly off the barrier toward the contour interior so the
    # seal sits just outside the blank buffer rather than exactly on the line.
    # Use average of start/end as interior hint.
    cx = (float(start[0]) + float(end[0])) * 0.5
    cy = (float(start[1]) + float(end[1])) * 0.5
    # Offset each mid a tiny step toward the open arc centroid-ish (start/end mean
    # is on the barrier side; use a sample point from mid-polyline via start-end).
    # Safer: offset from barrier projection toward the midpoint of start-end chord
    # which already lies inside the partition for U-arcs.
    pulled: List[PointTuple] = []
    for mx, my in mids:
        vx, vy = cx - mx, cy - my
        norm = math.hypot(vx, vy)
        if norm > 1e-12:
            # Small inward offset (~0.35 cell) so seal is cartographically clean.
            s = min(step * 0.35, norm * 0.5)
            pulled.append((mx + vx / norm * s, my + vy / norm * s))
        else:
            pulled.append((mx, my))
    return pulled


def _seal_open_contour(
    line: Sequence[PointTuple],
    barriers: Sequence[BarrierLine],
    grid_step: float,
) -> List[PointTuple]:
    """Close an open polyline into a simple ring (no barrier-following U-seal).

    老师要求：禁止沿打断线走中点把开放等值线封成环。
    """
    del barriers, grid_step
    pts = list(line)
    if len(pts) < 3:
        return pts
    return pts + [pts[0]]


def _should_force_close_contour(
    line: Sequence[PointTuple],
    max_gap: float,
    grid_step: float,
    *,
    barriers: Sequence[BarrierLine] = (),
    surface_grid: Optional[np.ndarray] = None,
    surface_x: Optional[np.ndarray] = None,
    surface_y: Optional[np.ndarray] = None,
    max_gap_ratio: float = 0.28,
    max_gap_vs_length: float = 0.22,
    min_gap_cells: float = 4.0,
    barrier_proximity: float = 0.0,
) -> bool:
    """Whether an open polyline should be closed into a ring.

    - Interior: micro-gaps always; ring-like arcs (high path/chord) more freely.
    - Outer formation rim: leave open (ends meet the map boundary).
    - Near 打断线: **never** force-close (老师硬性约束 → 开放止于缓冲外缘).
    - Reject long straight chords (false diagonals) via path/chord + absolute caps.
    """
    del min_gap_cells
    if len(line) < 3 or _is_closed_polyline(line, grid_step):
        return False
    gap = _point_distance(line[0], line[-1])
    length = _polyline_length(line)
    if length < 1e-12:
        return False
    ratio = gap / length
    step = max(float(grid_step), 1e-9)
    path_chord = length / max(gap, 1e-12)
    proximity = max(float(barrier_proximity), 0.0)

    ends_on_edge = _contour_ends_on_data_boundary(
        line[0],
        line[-1],
        surface_grid,
        surface_x,
        surface_y,
        grid_step,
    )
    # 覆盖缓冲带宽：裁剪/贴边后端点常落在缓冲外缘
    barrier_margin = max(step * 12.0, proximity * 1.5, 1e-9)
    either_near = bool(barriers) and _either_endpoint_near_barriers(
        line[0], line[-1], barriers, barrier_margin
    )
    both_near = bool(barriers) and _both_endpoints_near_barriers(
        line[0], line[-1], barriers, barrier_margin
    )

    # 跨打断线封口一律禁止
    if barriers and is_blocked_by_barrier(line[0], line[-1], barriers, endpoint_tolerance=1e-7):
        return False

    # 老师要求：贴打断线（任一端或两端）禁止强制自闭合，开放止于缓冲外缘
    if either_near or both_near:
        return False

    # 封口弦中点靠近打断线 → 也禁止（防弦贴线假闭合）
    if barriers and gap > step * 0.5:
        mid = (
            (float(line[0][0]) + float(line[-1][0])) * 0.5,
            (float(line[0][1]) + float(line[-1][1])) * 0.5,
        )
        if _point_distance_to_barriers(mid, barriers) <= barrier_margin * 0.9:
            return False

    if ends_on_edge:
        # Outer formation rim: keep open so lines meet the map boundary.
        return False

    # Interior: true micro-gaps only when clearly away from barriers
    if gap <= step * 3.0 and ratio <= 0.28:
        return True

    # Interior ring-like close (nested high cores) — 更严格，减少误闭合
    absolute_cap = _absolute_close_gap_cap(max_gap, grid_step)
    if gap > absolute_cap:
        return False
    if path_chord < 4.0:
        return False
    xs = [float(p[0]) for p in line]
    ys = [float(p[1]) for p in line]
    bbox_diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if gap > max(step * 3.5, bbox_diag * 0.18):
        return False
    if ratio > min(max_gap_ratio, 0.25) or gap > max(length * min(max_gap_vs_length, 0.18), step * 3.5):
        return False
    return True


def _polyline_bbox_center(line: Sequence[PointTuple]) -> PointTuple:
    xs = [float(p[0]) for p in line]
    ys = [float(p[1]) for p in line]
    return ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5)


def _closed_polylines_similar(
    a: Sequence[PointTuple],
    b: Sequence[PointTuple],
    grid_step: float,
) -> bool:
    """True when two closed rings are essentially the same cartographic feature."""
    step = max(float(grid_step), 1e-9)
    if len(a) < 4 or len(b) < 4:
        return False
    la = _polyline_length(a)
    lb = _polyline_length(b)
    if la < step * 4.0 or lb < step * 4.0:
        return False
    ratio = min(la, lb) / max(la, lb)
    if ratio < 0.72:
        return False
    ca = _polyline_bbox_center(a)
    cb = _polyline_bbox_center(b)
    # Similar length + nearby centers → treat as duplicate nested ring.
    center_tol = max(step * 6.0, min(la, lb) * 0.12)
    return _point_distance(ca, cb) <= center_tol


def _merge_hybrid_contours(
    ms_contours: Dict[float, List[List[PointTuple]]],
    ring_contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """Merge traditional MS polylines with peak closed rings (no open-line wipe).

    MS provides regional open arcs and many closed loops; rings fill nested
    bullseyes that MS leaves incomplete. Duplicate closed rings are skipped.
    """
    step = max(float(grid_step), 1e-9)
    levels = set(float(lv) for lv in ms_contours.keys()) | set(float(lv) for lv in ring_contours.keys())
    merged: Dict[float, List[List[PointTuple]]] = {}
    ms_count = 0
    ring_kept = 0
    ring_skipped = 0

    for level in sorted(levels):
        base: List[List[PointTuple]] = []
        for raw in ms_contours.get(level, []) or ms_contours.get(float(level), []):
            line = _dedupe_consecutive_points(raw, tolerance=max(step * 1e-6, 1e-9))
            if len(line) >= 2:
                base.append(line)
                ms_count += 1

        closed_base = [ln for ln in base if len(ln) >= 4 and _is_closed_polyline(ln, step)]
        for raw in ring_contours.get(level, []) or ring_contours.get(float(level), []):
            ring = _dedupe_consecutive_points(raw, tolerance=max(step * 1e-6, 1e-9))
            if len(ring) < 4:
                continue
            if not _is_closed_polyline(ring, step):
                gap = _point_distance(ring[0], ring[-1])
                path = _polyline_length(ring)
                if path > step * 6.0 and gap > 1e-12 and (path / max(gap, 1e-12)) >= 2.5:
                    if gap <= min(step * 16.0, path * 0.35):
                        ring = ring + [ring[0]]
                    else:
                        continue
                else:
                    continue
            if not _is_closed_polyline(ring, step):
                continue
            if any(_closed_polylines_similar(ring, existing, step) for existing in closed_base):
                ring_skipped += 1
                continue
            base.append(ring)
            closed_base.append(ring)
            ring_kept += 1
        merged[float(level)] = base

    return merged, {
        "ms_count": int(ms_count),
        "ring_kept": int(ring_kept),
        "ring_skipped": int(ring_skipped),
    }


def _keep_closed_contours_only(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """Legacy helper: drop open polylines. Prefer hybrid merge; do not use in pipeline."""
    step = max(float(grid_step), 1e-9)
    dropped = 0
    cleaned: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for raw in lines:
            line = _dedupe_consecutive_points(raw, tolerance=max(step * 1e-6, 1e-9))
            if len(line) >= 4 and _is_closed_polyline(line, step):
                kept.append(line)
            else:
                # Last chance: ring-like open → seal.
                if len(line) >= 4:
                    gap = _point_distance(line[0], line[-1])
                    path = _polyline_length(line)
                    if path > step * 8.0 and gap > 1e-12 and (path / gap) >= 2.8:
                        if gap <= min(step * 16.0, path * 0.35):
                            kept.append(line + [line[0]])
                            continue
                dropped += 1
        cleaned[float(level)] = kept
    return cleaned, int(dropped)


def prune_messy_contour_fragments(
    contours: Dict[float, List[List[PointTuple]]],
    grid_step: float,
    *,
    min_open_length: float,
    min_closed_length: float,
    barriers: Sequence[BarrierLine] = (),
    barrier_keep_proximity: float = 0.0,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """Remove short/noisy polylines that make isolines look chaotic.

    Closed loops are kept with a lower length threshold (nested bullseyes can be
    small). Open arcs must be longer — short open scraps are the main source of
    visual mess in drafting output.
    例外：两端靠近打断线的中等长度开放弧放宽阈值，避免贴边续接前被误删。
    """
    pruned_open = 0
    pruned_closed = 0
    kept = 0
    cleaned: Dict[float, List[List[PointTuple]]] = {}
    step = max(float(grid_step), 1e-9)
    open_min = max(float(min_open_length), step * 10.0)
    closed_min = max(float(min_closed_length), step * 4.0)
    near_lim = max(float(barrier_keep_proximity), 0.0)

    for level, lines in contours.items():
        kept_lines: List[List[PointTuple]] = []
        for raw in lines:
            line = _dedupe_consecutive_points(raw, tolerance=max(step * 1e-6, 1e-9))
            if len(line) < 2:
                pruned_open += 1
                continue
            length = _polyline_length(line)
            closed = _is_closed_polyline(line, step)
            if closed:
                if length < closed_min or len(line) < 4:
                    pruned_closed += 1
                    continue
            else:
                need = open_min
                # 贴打断的开放弧：放宽长度门槛，留给贴边拼接
                if barriers and near_lim > 0 and len(line) >= 2:
                    d0 = _point_distance_to_barriers(
                        (float(line[0][0]), float(line[0][1])), barriers
                    )
                    d1 = _point_distance_to_barriers(
                        (float(line[-1][0]), float(line[-1][1])), barriers
                    )
                    if d0 <= near_lim or d1 <= near_lim:
                        need = max(step * 4.0, open_min * 0.45)
                if length < need or len(line) < 3:
                    pruned_open += 1
                    continue
            kept_lines.append(line)
            kept += 1
        cleaned[float(level)] = kept_lines
    return cleaned, {
        "pruned_open": int(pruned_open),
        "pruned_closed": int(pruned_closed),
        "kept": int(kept),
    }


def _offset_barrier_blocked_mask(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    dr: int,
    dc: int,
    barrier_segments: Sequence[Tuple[PointTuple, PointTuple]],
    endpoint_tolerance: float = 1e-9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Grid-wide mask of cells whose neighbor at offset (dr, dc) is barrier-blocked.

    Returns ``(blocked, rows_dst, cols_dst)`` where ``blocked`` is the
    (len(rows_dst), len(cols_dst)) mask over the destination slice and
    ``rows_dst``/``cols_dst`` are the destination row/col index arrays
    (``blocked[i, j]`` corresponds to grid cell ``(rows_dst[i], cols_dst[j])``).

    The neighbor of cell (r, c) is (r + dr, c + dc); the (cell → neighbor)
    segment is tested against every barrier segment with the same
    ``strict_segments_intersect`` arithmetic as the reference implementation.
    """
    H = len(y_coords)
    W = len(x_coords)
    x_coords = np.asarray(x_coords, dtype=float)
    y_coords = np.asarray(y_coords, dtype=float)
    if dr >= 0:
        rows_dst = np.arange(0, H - dr, dtype=int)
        rows_src = rows_dst + dr
    else:
        rows_dst = np.arange(-dr, H, dtype=int)
        rows_src = rows_dst + dr
    if dc >= 0:
        cols_dst = np.arange(0, W - dc, dtype=int)
        cols_src = cols_dst + dc
    else:
        cols_dst = np.arange(-dc, W, dtype=int)
        cols_src = cols_dst + dc
    dst_x = x_coords[cols_dst][None, :]
    dst_y = y_coords[rows_dst][:, None]
    rx = (x_coords[cols_src] - x_coords[cols_dst])[None, :]
    ry = (y_coords[rows_src] - y_coords[rows_dst])[:, None]
    tol = float(endpoint_tolerance)
    blocked = np.zeros((len(rows_dst), len(cols_dst)), dtype=bool)
    for (c, d) in barrier_segments:
        cx, cy = c
        dx, dy = d
        sx = dx - cx
        sy = dy - cy
        denom = rx * sy - ry * sx
        qpx = (cx - dst_x)
        qpy = (cy - dst_y)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (qpx * sy - qpy * sx) / denom
            u = (qpx * ry - qpy * rx) / denom
        crossing = (
            (tol < t) & (t < 1.0 - tol)
            & (-tol <= u) & (u <= 1.0 + tol)
        )
        if (np.abs(denom) <= 1e-12).any():
            rr = rx * rx + ry * ry
            with np.errstate(divide="ignore", invalid="ignore"):
                t0 = (qpx * rx + qpy * ry) / rr
                t1 = ((dx - dst_x) * rx + (dy - dst_y) * ry) / rr
            lo = np.minimum(t0, t1)
            hi = np.maximum(t0, t1)
            crossing |= (
                (np.abs(denom) <= 1e-12)
                & (rr > 1e-24)
                & (np.abs(qpx * ry - qpy * rx) <= 1e-12)
                & (hi > tol)
                & (lo < 1.0 - tol)
            )
        blocked |= crossing
    return blocked, rows_dst, cols_dst


def _anisotropic_fill_multiplier_vec(
    dr: int, dc: int, field: np.ndarray, aspect: float
) -> np.ndarray:
    """Vectorized ``_anisotropic_fill_multiplier`` over a (rows, cols, 3) field."""
    stretch = np.asarray(field[..., 2], dtype=float)
    base = np.ones(stretch.shape, dtype=float)
    active = stretch > 1.0 + 1e-9
    ox = float(dc)
    oy = float(dr) * aspect
    norm = math.hypot(ox, oy)
    if norm > 1e-12:
        align = np.abs(ox * field[..., 0] + oy * field[..., 1]) / norm
        base = np.where(active, 1.0 + (stretch - 1.0) * align, base)
    return base


def _offset_slices(rows: int, cols: int, dr: int, dc: int):
    """Destination / source row-col slices for a neighbor offset (dr, dc)."""
    if dr >= 0:
        r_dst = slice(0, rows - dr)
        r_src = slice(dr, rows)
    else:
        r_dst = slice(-dr, rows)
        r_src = slice(0, rows + dr)
    if dc >= 0:
        c_dst = slice(0, cols - dc)
        c_src = slice(dc, cols)
    else:
        c_dst = slice(-dc, cols)
        c_src = slice(0, cols + dc)
    return r_dst, c_dst, r_src, c_src


def smooth_valid_grid(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    iterations: int,
    near_barrier_mask: Optional[np.ndarray] = None,
    region_labels: Optional[np.ndarray] = None,
    direction_field: Optional[np.ndarray] = None,
    direction_strength: float = 1.0,
) -> np.ndarray:
    """Smooth finite cells without filling the mask or blending across barriers/regions.

    When ``direction_field`` is provided, neighbor weights are increased for
    offsets aligned with the local direction-line tangent. This keeps the
    final trend surface elongated along direction lines instead of letting
    ordinary isotropic smoothing pull it back toward circular blobs.
    """
    result = np.array(grid, dtype=float, copy=True)
    if iterations <= 0 or result.size == 0:
        return result

    valid_mask = np.isfinite(result)
    if not bool(valid_mask.any()):
        return result

    offsets = (
        (0, 0, 4.0),
        (-1, 0, 2.0),
        (1, 0, 2.0),
        (0, -1, 2.0),
        (0, 1, 2.0),
        (-1, -1, 1.0),
        (-1, 1, 1.0),
        (1, -1, 1.0),
        (1, 1, 1.0),
    )
    rows, cols = result.shape
    aspect = _grid_aspect(x_coords, y_coords)
    direction_strength = max(0.0, float(direction_strength))
    barrier_segments = _barrier_segments(barriers) if barriers else []
    near = (
        None
        if near_barrier_mask is None
        else np.asarray(near_barrier_mask, dtype=bool)
    )
    # Neighbor-blocked masks depend only on geometry — compute once per call
    # and reuse across iterations.
    offset_blocked: Dict[Tuple[int, int], np.ndarray] = {}
    if barrier_segments:
        for (dr, dc, _weight) in offsets:
            if dr != 0 or dc != 0:
                offset_blocked[(dr, dc)], _, _ = _offset_barrier_blocked_mask(
                    x_coords, y_coords, dr, dc, barrier_segments, 1e-9
                )
    for _ in range(max(0, int(iterations))):
        next_grid = result.copy()
        weighted_sum = np.zeros_like(result)
        weight_sum = np.zeros_like(result)
        for (dr, dc, weight) in offsets:
            r_dst, c_dst, r_src, c_src = _offset_slices(rows, cols, dr, dc)
            ok = valid_mask[r_src, c_src]
            eff = weight
            if dr != 0 or dc != 0:
                if region_labels is not None:
                    ok = ok & (
                        region_labels[r_src, c_src]
                        == region_labels[r_dst, c_dst]
                    )
                if barrier_segments:
                    blocked = offset_blocked[(dr, dc)]
                    if near is not None:
                        blocked = blocked & near[r_dst, c_dst]
                    ok = ok & ~blocked
                if direction_field is not None:
                    base = _anisotropic_fill_multiplier_vec(
                        dr, dc, direction_field[r_dst, c_dst], aspect
                    )
                    eff = np.where(
                        base > 1.0,
                        weight * (1.0 + (base - 1.0) * direction_strength),
                        weight,
                    )
            weighted_sum[r_dst, c_dst] += np.where(
                ok, result[r_src, c_src] * eff, 0.0
            )
            weight_sum[r_dst, c_dst] += np.where(ok, eff, 0.0)
        populated = weight_sum > 0.0
        next_grid[populated] = weighted_sum[populated] / weight_sum[populated]
        next_grid[~valid_mask] = np.nan
        result = next_grid
    return result



def refine_domain_boundary_transition(
    grid: np.ndarray,
    domain_mask: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    barriers: Sequence[BarrierLine],
    *,
    near_barrier_mask: Optional[np.ndarray] = None,
    region_labels: Optional[np.ndarray] = None,
    feather_cells: int = 4,
    iterations: int = 2,
) -> np.ndarray:
    """Smooth values in a band near domain edges for gradual fade toward boundaries/barriers."""
    result = np.array(grid, dtype=float, copy=True)
    if iterations <= 0 or result.size == 0 or not bool(np.any(domain_mask)):
        return result
    try:
        from scipy.ndimage import distance_transform_edt
    except ImportError:
        return result

    dist_to_edge = distance_transform_edt(np.asarray(domain_mask, dtype=bool))
    feather = max(float(feather_cells), 1.0)
    edge_band = np.asarray(domain_mask, dtype=bool) & (dist_to_edge > 0.0) & (dist_to_edge <= feather)
    if not bool(np.any(edge_band)):
        return result

    valid_mask = np.isfinite(result) & np.asarray(domain_mask, dtype=bool)
    offsets = (
        (-1, 0, 2.0), (1, 0, 2.0), (0, -1, 2.0), (0, 1, 2.0),
        (-1, -1, 1.0), (-1, 1, 1.0), (1, -1, 1.0), (1, 1, 1.0),
    )
    rows, cols = result.shape
    barrier_segments = _barrier_segments(barriers) if barriers else []
    near = (
        None
        if near_barrier_mask is None
        else np.asarray(near_barrier_mask, dtype=bool)
    )
    # Neighbor-blocked masks depend only on geometry — compute once per call
    # and reuse across iterations.
    offset_blocked: Dict[Tuple[int, int], np.ndarray] = {}
    if barrier_segments:
        for (dr, dc, _weight) in offsets:
            offset_blocked[(dr, dc)], _, _ = _offset_barrier_blocked_mask(
                x_coords, y_coords, dr, dc, barrier_segments, 1e-9
            )
    for _ in range(max(0, int(iterations))):
        next_grid = result.copy()
        weighted_sum = np.zeros_like(result)
        weight_sum = np.zeros_like(result)
        for (dr, dc, weight) in offsets:
            r_dst, c_dst, r_src, c_src = _offset_slices(rows, cols, dr, dc)
            ok = valid_mask[r_src, c_src] & edge_band[r_dst, c_dst]
            if region_labels is not None:
                ok = ok & (
                    region_labels[r_src, c_src] == region_labels[r_dst, c_dst]
                )
            if barrier_segments:
                blocked = offset_blocked[(dr, dc)]
                if near is not None:
                    blocked = blocked & near[r_dst, c_dst]
                ok = ok & ~blocked
            edge_factor = dist_to_edge[r_src, c_src] / feather
            eff_w = weight * np.maximum(edge_factor, 0.35)
            weighted_sum[r_dst, c_dst] += np.where(
                ok, result[r_src, c_src] * eff_w, 0.0
            )
            weight_sum[r_dst, c_dst] += np.where(ok, eff_w, 0.0)
        interior = np.zeros_like(result)
        populated = weight_sum > 0.0
        interior[populated] = weighted_sum[populated] / weight_sum[populated]
        blend = np.clip(dist_to_edge / feather, 0.0, 1.0)
        band = edge_band & valid_mask
        next_grid[band] = interior[band] * blend[band] + result[band] * (1.0 - blend[band])
        next_grid[~valid_mask] = np.nan
        result = next_grid
    return result


def clip_contours_to_finite_surface(
    contours: Dict[float, List[List[PointTuple]]],
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    levels: Sequence[float] = (),
    min_segment_points: int = 2,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """Remove contour segments that fall outside the finite interpolation surface."""
    if grid.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return contours, {"clipped_contour_segments": 0, "clipped_contour_points": 0}

    grid_step = _estimate_grid_step(x_coords, y_coords)
    finite_values = grid[np.isfinite(grid)]
    value_span = float(np.nanmax(finite_values) - np.nanmin(finite_values)) if finite_values.size else 1.0
    level_tolerance = max(grid_step * 2.5, value_span * 0.12, 0.02)
    clipped_segments = 0
    clipped_points = 0
    cleaned: Dict[float, List[List[PointTuple]]] = {}

    for raw_level, lines in contours.items():
        level = float(raw_level)
        kept: List[List[PointTuple]] = []
        for line in lines:
            if len(line) < 2:
                clipped_segments += 1
                continue

            # Smoothing and simplification can leave one long segment whose
            # endpoints are both valid while its interior crosses a NaN stop
            # corridor. Sample more finely than a grid cell so clipping uses
            # the complete geometry rather than contour vertices alone.
            sampled_line = _densify_polyline_segments(
                line,
                max_seg=max(grid_step * 0.35, 1e-9),
            )
            support_flags = [
                _contour_point_supported_by_surface(
                    pt, level, grid, x_coords, y_coords, level_tolerance
                )
                for pt in sampled_line
            ]
            if all(support_flags):
                kept.append([(float(pt[0]), float(pt[1])) for pt in line])
                continue

            current: List[PointTuple] = []
            for pt, on_surface in zip(sampled_line, support_flags):
                if on_surface:
                    current.append((float(pt[0]), float(pt[1])))
                else:
                    clipped_points += 1
                    if len(current) >= min_segment_points:
                        kept.append(current)
                    elif current:
                        clipped_segments += 1
                    current = []
            if len(current) >= min_segment_points:
                kept.append(current)
            elif current:
                clipped_segments += 1
        cleaned[level] = kept
    return cleaned, {
        "clipped_contour_segments": int(clipped_segments),
        "clipped_contour_points": int(clipped_points),
    }


def _contour_point_supported_by_surface(
    pt: PointTuple,
    level: float,
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    level_tolerance: float,
) -> bool:
    del level, level_tolerance
    return sample_bilinear_grid(grid, x_coords, y_coords, float(pt[0]), float(pt[1])) is not None


def postprocess_contours(
    contours: Dict[float, List[List[PointTuple]]],
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    config: ConstrainedIDWConfig,
    barriers: Sequence[BarrierLine] = (),
    surface_grid: Optional[np.ndarray] = None,
    directions: Sequence[DirectionLine] = (),
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """Apply cartographic cleanup to raw marching-squares polylines.

    directions: if provided, after smoothing we do light direction-guided alignment
    so that contour strike tends to follow the direction lines (user request for
    "等值线走向和方向线趋同").
    """
    grid_step = _estimate_grid_step(x_coords, y_coords)
    configured_min = float(config.min_contour_length)
    if configured_min <= 0.0:
        # Production defaults: drop short open scraps that look "messy".
        min_open_length = max(grid_step * 12.0, 1e-9)
        min_closed_length = max(grid_step * 5.0, 1e-9)
    else:
        # Honor explicit config (unit tests and specialized runs).
        min_open_length = configured_min
        min_closed_length = max(configured_min * 0.5, configured_min * 0.5)
    simplify_tolerance = max(0.0, float(config.contour_simplify_tolerance))
    # Two to three controlled passes are enough after surface upsampling. More
    # passes round off local geology and force later topology repairs.
    smooth_iterations = max(0, min(3, int(config.contour_smoothing_iterations)))
    bridge_gap = max(0.0, float(config.contour_bridge_gap))

    filtered_short = 0
    smoothed = 0
    bridged = 0
    closed = 0
    cleaned: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        candidate_lines: List[List[PointTuple]] = []
        for raw_points in lines:
            points = _dedupe_consecutive_points(raw_points, tolerance=max(grid_step * 1e-5, 1e-9))
            if len(points) < 2:
                filtered_short += 1
                continue

            # 先去尖角，再轻度简化（保留足够顶点供后续平滑成弧）
            points = _remove_polyline_spikes(points, grid_step)
            if simplify_tolerance > 0.0 and len(points) > 3:
                was_closed = _is_closed_polyline(points, grid_step)
                core = points[:-1] if was_closed else points
                # 简化不宜过狠，否则只剩折角
                core = _rdp_simplify(core, min(simplify_tolerance, grid_step * 0.22))
                points = core + [core[0]] if was_closed and len(core) >= 3 else core

            points = _dedupe_consecutive_points(points, tolerance=max(grid_step * 1e-6, 1e-9))
            if len(points) >= 2:
                candidate_lines.append(points)
            else:
                filtered_short += 1

        # Only heal sub-cell MS nicks. Long endpoint joins are the main source of
        # false diagonals and of fragments created when those joins are cut again.
        safe_bridge = min(max(bridge_gap, grid_step * 2.0), grid_step * 6.0)
        safe_close = min(max(safe_bridge * 1.35, grid_step * 3.0), grid_step * 9.0)
        output_lines, bridge_count = _bridge_contour_gaps(
            candidate_lines,
            safe_bridge,
            grid_step,
            barriers=barriers,
        )
        bridged += bridge_count
        active_surface = surface_grid if surface_grid is not None else None
        output_lines, close_count = _close_near_contour_loops(
            output_lines,
            safe_close,
            grid_step,
            barriers=barriers,
            surface_grid=active_surface,
            surface_x=x_coords,
            surface_y=y_coords,
        )
        closed += close_count

        final_lines: List[List[PointTuple]] = []
        for points in output_lines:
            if len(points) > 2 and smooth_iterations > 0:
                points = _cartographic_smooth_polyline(
                    points, grid_step, iterations=smooth_iterations
                )
                smoothed += 1
            # 方向线对齐力度降低：过强会把不同级等值线拉出交叉
            if directions and len(points) > 2:
                aligned = _direction_align_polyline(points, directions, grid_step, strength=0.10)
                if not _polyline_self_intersects(aligned, grid_step):
                    points = aligned
            if active_surface is not None and len(points) > 2:
                projected = project_contours_to_surface_levels(
                    {float(level): [points]},
                    active_surface,
                    x_coords,
                    y_coords,
                    grid_step,
                    iterations=2,
                )
                points = projected.get(float(level), [points])[0]
            points = _dedupe_consecutive_points(points, tolerance=max(grid_step * 1e-6, 1e-9))
            barrier_margin = max(grid_step * 12.0, 1e-9)
            if len(points) >= 4 and _is_closed_polyline(points, grid_step):
                # 打开贴打断线假闭合 + 长弦 / 外缘假闭合
                if (
                    _closed_ring_should_reopen_near_barrier(points, barriers, barrier_margin)
                    or _has_suspicious_closing_chord(points, grid_step)
                    or _is_false_outer_rim_close(
                        points[0],
                        points[-2],
                        active_surface,
                        x_coords,
                        y_coords,
                        grid_step,
                        barriers=barriers,
                    )
                ):
                    points = points[:-1]
            if len(points) >= 3 and not _is_closed_polyline(points, grid_step):
                if _should_force_close_contour(
                    points,
                    safe_close,
                    grid_step,
                    barriers=barriers,
                    surface_grid=active_surface,
                    surface_x=x_coords,
                    surface_y=y_coords,
                    barrier_proximity=barrier_margin,
                ):
                    points = _seal_open_contour(points, barriers, grid_step)
                    closed += 1
            length = _polyline_length(points)
            is_closed = _is_closed_polyline(points, grid_step)
            need = min_closed_length if is_closed else min_open_length
            if len(points) >= 2 and length >= need:
                final_lines.append(points)
            else:
                filtered_short += 1
        cleaned[float(level)] = final_lines

    # 轻量消交：完整硬保证留给最终 apply_contour_topology_constraints（避免重复重算）
    cleaned, cross_fixed = sanitize_contour_crossings(
        cleaned,
        grid_step,
        max_passes=24,
        time_budget_s=0.8,
        max_points_per_line=220,
    )
    return cleaned, {
        "filtered_short_contours": int(filtered_short),
        "smoothed_contours": int(smoothed),
        "bridged_contour_gaps": int(bridged),
        "closed_contour_gaps": int(closed),
        "fixed_contour_crossings": int(cross_fixed),
    }


def _snap_point_to_barrier_buffer_rim(
    pt: PointTuple,
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
) -> PointTuple:
    """把点投影到缓冲带外缘（距打断线 = buffer_distance 的同侧位置）。"""
    buf = max(float(buffer_distance), 1e-9)
    proj = _nearest_barrier_projection(pt, barriers)
    if proj is None:
        return (float(pt[0]), float(pt[1]))
    foot, a, b, d = proj
    px, py = float(pt[0]), float(pt[1])
    fx, fy = float(foot[0]), float(foot[1])
    rx, ry = px - fx, py - fy
    rn = math.hypot(rx, ry)
    if rn < 1e-12:
        # 点几乎在打断线上：用法向推到外缘
        tx, ty = float(b[0] - a[0]), float(b[1] - a[1])
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl
        return (fx + nx * buf, fy + ny * buf)
    s = buf / rn
    return (fx + rx * s, fy + ry * s)


def push_contours_out_of_buffer(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """把落入缓冲内部的顶点径向推到外缘，尽量保持绕行折线不断开。"""
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.2)
    inside = buf * 0.98
    pushed = 0
    out: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for ln in lines:
            if len(ln) < 2:
                continue
            pts: List[PointTuple] = []
            for p in ln:
                pt = (float(p[0]), float(p[1]))
                d = _point_distance_to_barriers(pt, active)
                if d < inside:
                    pt = _snap_point_to_barrier_buffer_rim(pt, active, buf)
                    pushed += 1
                pts.append(pt)
            pts = _dedupe_consecutive_points(pts, tolerance=max(step * 1e-5, 1e-9))
            if len(pts) >= 2:
                kept.append(pts)
        out[float(level)] = kept
    return out, pushed


def trim_contours_at_barrier_buffers(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """等值线让出整个缓冲区（不是被掩膜盖住）。

    - 缓冲带内部（距打断线 < buffer）的顶点全部剔除
    - 穿越打断线/进入缓冲的线段切断，端点贴到缓冲外缘
    - 之后由 route/stitch 沿外缘绕行续接
    """
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active:
        return {float(level): [list(line) for line in lines] for level, lines in contours.items()}, 0

    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.2)
    # 整带剔除：略小于 buf，外缘留给绕行折线
    inside_tol = max(buf * 0.995, step * 0.5)
    sample_step = max(min(step * 0.45, buf * 0.25), step * 0.10)
    trimmed = 0
    cleaned: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for line in lines:
            if len(line) < 2:
                continue
            # A sparse/smoothed contour can cross the whole buffer without a
            # vertex inside it. Densify before testing the corridor.
            sampled_line = _densify_polyline_segments(line, max_seg=sample_step)
            touches_buffer = any(
                _point_distance_to_barriers(
                    (float(pt[0]), float(pt[1])), active
                ) < inside_tol
                for pt in sampled_line
            )
            crosses_barrier = any(
                is_blocked_by_barrier(
                    (float(line[i - 1][0]), float(line[i - 1][1])),
                    (float(line[i][0]), float(line[i][1])),
                    active,
                    endpoint_tolerance=1e-7,
                )
                for i in range(1, len(line))
            )
            if not touches_buffer and not crosses_barrier:
                kept.append([(float(pt[0]), float(pt[1])) for pt in line])
                continue
            current: List[PointTuple] = []
            was_inside = False
            for index in range(len(sampled_line)):
                pt = (float(sampled_line[index][0]), float(sampled_line[index][1]))
                d_bar = _point_distance_to_barriers(pt, active)
                in_buffer = d_bar < inside_tol
                if in_buffer:
                    if current:
                        rim = _snap_point_to_barrier_buffer_rim(current[-1], active, buf)
                        if _point_distance(current[-1], rim) > step * 1e-6:
                            current.append(rim)
                        if len(current) >= 2:
                            kept.append(current)
                            trimmed += 1
                        current = []
                    was_inside = True
                    continue
                # 从缓冲内走出：用外缘点启动新段，保证两侧都有可贴边的端点
                if was_inside:
                    rim = _snap_point_to_barrier_buffer_rim(pt, active, buf)
                    current = [rim]
                    if _point_distance(rim, pt) > step * 1e-6:
                        current.append(pt)
                    was_inside = False
                    continue
                if index > 0 and current:
                    prev = current[-1]
                    crosses = is_blocked_by_barrier(prev, pt, active, endpoint_tolerance=1e-7)
                    if crosses:
                        rim = _snap_point_to_barrier_buffer_rim(prev, active, buf)
                        if _point_distance(prev, rim) > step * 1e-6:
                            current.append(rim)
                        if len(current) >= 2:
                            kept.append(current)
                            trimmed += 1
                        rim2 = _snap_point_to_barrier_buffer_rim(pt, active, buf)
                        current = [rim2]
                        if _point_distance(rim2, pt) > step * 1e-6:
                            current.append(pt)
                        continue
                current.append(pt)
                was_inside = False
            if len(current) >= 2:
                kept.append(current)
            elif current:
                trimmed += 1
        cleaned[float(level)] = kept
    cleaned, cut2 = enforce_no_barrier_crossing(cleaned, active, step)
    return cleaned, int(trimmed + cut2)


def route_contours_around_barrier_buffers(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
    *,
    surface_grid: Optional[np.ndarray] = None,
    surface_x: Optional[np.ndarray] = None,
    surface_y: Optional[np.ndarray] = None,
    max_rounds: int = 20,
) -> Tuple[Dict[float, List[List[PointTuple]]], Dict[str, int]]:
    """等值线绕开缓冲区：禁止进入绿缓冲，沿外缘/端头半圆绕过。

    1) 整带剔除内部点并贴到缓冲外缘
    2) 同级开放端沿外缘桥接（含对侧绕端头）
    3) 强制把仍悬空端绕最近端头到对侧并尝试接上
    4) 平滑后推缘，保证不进缓冲
    """
    del surface_grid, surface_x, surface_y  # 几何绕行，不再依赖栅格贴边
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    stats = {"trimmed": 0, "stitched": 0, "hugged": 0, "wrapped": 0, "pruned_scraps": 0}
    if not active:
        return (
            {float(k): [list(ln) for ln in v] for k, v in contours.items()},
            stats,
        )
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)

    result, trimmed = trim_contours_at_barrier_buffers(contours, active, buf, step)
    stats["trimmed"] = int(trimmed)
    result, _ = remove_barrier_artifact_contours(result, active, step)

    # 多轮：外缘拼接 → 强制绕端头 → 再拼接
    for _round in range(3):
        result, stitched = stitch_open_contours_along_barrier_edge(
            result,
            active,
            buf,
            step,
            max_rounds=max(16, int(max_rounds)),
            allow_long_detour=True,
        )
        stats["stitched"] = int(stats["stitched"] + stitched)
        result, wrapped = force_wrap_open_ends_around_barrier_tips(
            result, active, buf, step
        )
        stats["wrapped"] = int(stats["wrapped"] + wrapped)
        if stitched == 0 and wrapped == 0:
            break

    result, hugged = extend_open_ends_along_buffer_rim(
        result, active, buf, step, max_extend=max(buf * 6.0, step * 24.0)
    )
    stats["hugged"] = int(hugged)
    result, stitched2 = stitch_open_contours_along_barrier_edge(
        result,
        active,
        buf,
        step,
        max_rounds=max(12, int(max_rounds)),
        allow_long_detour=True,
    )
    stats["stitched"] = int(stats["stitched"] + stitched2)

    # 去掉贴缓冲的短碎段（如图上 0.4 残桩）— 绕行前后各清一次
    result, n_scrap = _prune_short_buffer_scraps(result, active, buf, step)
    stats["pruned_scraps"] = int(n_scrap)

    # 最终保证不进缓冲、不穿打断线（推缘优先，避免把绕行线裁碎）
    result, _ = push_contours_out_of_buffer(result, active, buf, step)
    result, _ = enforce_no_barrier_crossing(result, active, step)
    result = cartographic_smooth_contours(result, step, iterations=3)
    result, _ = push_contours_out_of_buffer(result, active, buf, step)
    result, _ = enforce_no_barrier_crossing(result, active, step)
    result, n_scrap2 = _prune_short_buffer_scraps(result, active, buf, step)
    stats["pruned_scraps"] = int(stats["pruned_scraps"] + n_scrap2)
    return result, stats


def _prune_short_buffer_scraps(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """删除贴缓冲的过短开放碎段。"""
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)
    min_len = max(buf * 2.5, step * 10.0)
    near = buf * 1.6
    removed = 0
    out: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for ln in lines:
            if len(ln) < 2:
                removed += 1
                continue
            length = _polyline_length(ln)
            if _is_closed_polyline(ln, step):
                if length >= min_len * 0.6:
                    kept.append(list(ln))
                else:
                    removed += 1
                continue
            d0 = _point_distance_to_barriers(ln[0], barriers)
            d1 = _point_distance_to_barriers(ln[-1], barriers)
            # 两端都贴缓冲且很短 → 碎桩
            if d0 <= near and d1 <= near and length < min_len:
                removed += 1
                continue
            # 单端贴缓冲的极短残段
            if length < min_len * 0.55 and (d0 <= near or d1 <= near):
                removed += 1
                continue
            kept.append(list(ln))
        if kept:
            out[float(level)] = kept
    return out, removed


def force_wrap_open_ends_around_barrier_tips(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """强制：贴缓冲的开放端沿外缘绕最近端头到对侧，并尽量接到同级另一端。

    对应用户示意的 U 形绕端头，而不是停在缓冲侧壁上。
    """
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)
    offset = max(buf * 1.08, step * 1.3)
    sample = max(step * 0.7, buf * 0.10)
    chains = _barrier_chains(active)
    if not chains:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0

    wrapped = 0
    # 先复制为可改列表
    working: Dict[float, List[List[PointTuple]]] = {
        float(lv): [list(ln) for ln in lines if len(ln) >= 2]
        for lv, lines in contours.items()
    }

    for level in list(working.keys()):
        lines = working[level]
        # 收集开放端
        changed = True
        guard = 0
        while changed and guard < 12:
            guard += 1
            changed = False
            ends: List[Tuple[int, str, PointTuple]] = []
            for i, ln in enumerate(lines):
                if _is_closed_polyline(ln, step):
                    continue
                ends.append((i, "start", (float(ln[0][0]), float(ln[0][1]))))
                ends.append((i, "end", (float(ln[-1][0]), float(ln[-1][1]))))

            # 优先尝试：两端对绕端头拼接
            best_join = None  # score, i, wi, j, wj, path
            for a_idx in range(len(ends)):
                i, wi, pi = ends[a_idx]
                if _point_distance_to_barriers(pi, active) > buf * 2.2:
                    continue
                for b_idx in range(a_idx + 1, len(ends)):
                    j, wj, pj = ends[b_idx]
                    if i == j:
                        continue
                    if _point_distance_to_barriers(pj, active) > buf * 2.2:
                        continue
                    path = _buffer_rim_detour_path(
                        pi,
                        pj,
                        active,
                        offset,
                        sample,
                        allow_tip=True,
                    )
                    if path is None or len(path) < 3:
                        continue
                    plen = sum(
                        math.hypot(path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
                        for k in range(len(path) - 1)
                    )
                    chord = math.hypot(pj[0] - pi[0], pj[1] - pi[1])
                    if plen > max(chord * 10.0, buf * 40.0, step * 120.0):
                        continue
                    others = [ln for k, ln in enumerate(lines) if k not in (i, j)]
                    if _path_crosses_any(path, others, step):
                        continue
                    # 构造合并
                    li, lj = list(lines[i]), list(lines[j])
                    if wi == "start":
                        li = list(reversed(li))
                    if wj == "end":
                        lj = list(reversed(lj))
                    merged = li + path[1:-1] + lj
                    merged = _dedupe_consecutive_points(
                        merged, tolerance=max(step * 1e-5, 1e-9)
                    )
                    if len(merged) < 3:
                        continue
                    if _polyline_self_intersects(merged, step):
                        continue
                    if any(_polylines_properly_cross(merged, o, step) for o in others):
                        continue
                    score = plen
                    if best_join is None or score < best_join[0]:
                        best_join = (score, i, wi, j, wj, merged)

            if best_join is not None:
                _, i, _wi, j, _wj, merged = best_join
                hi, lo = (i, j) if i > j else (j, i)
                lines[lo] = merged
                del lines[hi]
                wrapped += 1
                changed = True
                continue

            # 无配对：把单个贴壁端强制绕到最近端头对侧
            best_ext = None  # score, i, which, new_pts
            for i, ln in enumerate(lines):
                if _is_closed_polyline(ln, step) or len(ln) < 2:
                    continue
                # 短碎段不硬绕（避免 0.4 残桩被拉成假绕行）
                if _polyline_length(ln) < max(buf * 2.2, step * 9.0):
                    continue
                for which in ("start", "end"):
                    end_pt = (
                        (float(ln[0][0]), float(ln[0][1]))
                        if which == "start"
                        else (float(ln[-1][0]), float(ln[-1][1]))
                    )
                    d_bar = _point_distance_to_barriers(end_pt, active)
                    if d_bar > buf * 1.85:
                        continue
                    # 已靠近某端头则不再硬绕
                    near_tip = False
                    for chain in chains:
                        if min(
                            math.hypot(end_pt[0] - chain[0][0], end_pt[1] - chain[0][1]),
                            math.hypot(end_pt[0] - chain[-1][0], end_pt[1] - chain[-1][1]),
                        ) <= buf * 1.35:
                            near_tip = True
                            break
                    if near_tip:
                        continue
                    # 选最近端头
                    tip_choice = None
                    tip_d = math.inf
                    for chain in chains:
                        for tip_flag in (0, -1):
                            tip = chain[0] if tip_flag == 0 else chain[-1]
                            d = math.hypot(end_pt[0] - tip[0], end_pt[1] - tip[1])
                            if d < tip_d:
                                tip_d = d
                                tip_choice = (chain, tip_flag, tip)
                    if tip_choice is None or tip_d > max(buf * 12.0, step * 40.0):
                        continue
                    chain, tip_flag, tip = tip_choice
                    if tip_flag == 0:
                        nxt = chain[1]
                        inward = (float(nxt[0] - tip[0]), float(nxt[1] - tip[1]))
                    else:
                        prv = chain[-2]
                        inward = (float(prv[0] - tip[0]), float(prv[1] - tip[1]))
                    il = math.hypot(inward[0], inward[1]) or 1.0
                    inward = (inward[0] / il, inward[1] / il)
                    left = (-inward[1], inward[0])
                    left_rim = (tip[0] + left[0] * offset, tip[1] + left[1] * offset)
                    right_rim = (tip[0] - left[0] * offset, tip[1] - left[1] * offset)
                    # 当前侧角 → 半圆 → 对侧角
                    dL = math.hypot(end_pt[0] - left_rim[0], end_pt[1] - left_rim[1])
                    dR = math.hypot(end_pt[0] - right_rim[0], end_pt[1] - right_rim[1])
                    if dL <= dR:
                        a_rim, b_rim, side_a = left_rim, right_rim, 1.0
                    else:
                        a_rim, b_rim, side_a = right_rim, left_rim, -1.0
                    leg = _same_side_rim_path(
                        end_pt, a_rim, chain, offset, side_a, sample, active
                    )
                    if leg is None:
                        if not is_blocked_by_barrier(
                            end_pt, a_rim, active, endpoint_tolerance=1e-7
                        ):
                            leg = [end_pt, a_rim]
                        else:
                            continue
                    arc = _tip_endcap_arc(tip, inward, a_rim, b_rim, offset, sample)
                    ext = list(leg[1:])
                    if arc:
                        if ext and _point_distance(ext[-1], arc[0]) < sample * 0.5:
                            ext.extend(arc[1:])
                        else:
                            ext.extend(arc)
                    if not ext:
                        continue
                    # 路径不得与其它线交叉
                    others = [x for k, x in enumerate(lines) if k != i]
                    trial_path = [end_pt] + ext
                    if _path_crosses_any(trial_path, others, step):
                        continue
                    pts = list(ln)
                    if which == "start":
                        new_pts = list(reversed(ext)) + pts
                    else:
                        new_pts = pts + ext
                    new_pts = _dedupe_consecutive_points(
                        new_pts, tolerance=max(step * 1e-5, 1e-9)
                    )
                    if _polyline_self_intersects(new_pts, step):
                        continue
                    if any(_polylines_properly_cross(new_pts, o, step) for o in others):
                        continue
                    score = tip_d
                    if best_ext is None or score < best_ext[0]:
                        best_ext = (score, i, which, new_pts)

            if best_ext is not None:
                _, i, _which, new_pts = best_ext
                lines[i] = new_pts
                wrapped += 1
                changed = True

        working[level] = lines

    return working, wrapped


def extend_open_ends_along_buffer_rim(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
    *,
    max_extend: float = 0.0,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """开放端在缓冲外缘时，沿外缘向最近端头延伸一截（几何路径，非贴格）。"""
    active = [b for b in barriers if getattr(b, "active", True) and len(b.points) >= 2]
    if not active:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)
    offset = max(buf * 1.05, step * 1.2)
    extend_lim = max(float(max_extend), buf * 3.0, step * 12.0)
    sample = max(step * 0.75, buf * 0.12)
    chains = _barrier_chains(active)
    extended = 0
    out: Dict[float, List[List[PointTuple]]] = {}

    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for ln in lines:
            if len(ln) < 2 or _is_closed_polyline(ln, step):
                kept.append(list(ln))
                continue
            pts = list(ln)
            for which in ("start", "end"):
                end_pt = pts[0] if which == "start" else pts[-1]
                end_pt = (float(end_pt[0]), float(end_pt[1]))
                d_bar = _point_distance_to_barriers(end_pt, active)
                if d_bar > buf * 1.9 and d_bar > step * 4.0:
                    continue
                # 找最近端头
                best_tip = None
                best_d = math.inf
                best_chain = None
                best_tip_flag = 0
                for chain in chains:
                    for tip_flag, tip in ((0, chain[0]), (-1, chain[-1])):
                        d = math.hypot(end_pt[0] - tip[0], end_pt[1] - tip[1])
                        if d < best_d:
                            best_d = d
                            best_tip = tip
                            best_chain = chain
                            best_tip_flag = tip_flag
                if best_tip is None or best_chain is None or best_d > extend_lim * 1.5:
                    continue
                # 端头角点（同侧）
                tip = best_tip
                if best_tip_flag == 0:
                    nxt = best_chain[1]
                    inward = (float(nxt[0] - tip[0]), float(nxt[1] - tip[1]))
                else:
                    prv = best_chain[-2]
                    inward = (float(prv[0] - tip[0]), float(prv[1] - tip[1]))
                il = math.hypot(inward[0], inward[1]) or 1.0
                inward = (inward[0] / il, inward[1] / il)
                left = (-inward[1], inward[0])
                # 用端点相对侧决定目标角
                side = _side_sign_of_point(end_pt, tip, (tip[0] + inward[0], tip[1] + inward[1]))
                if side >= 0:
                    target = (tip[0] + left[0] * offset, tip[1] + left[1] * offset)
                    side_h = 1.0
                else:
                    target = (tip[0] - left[0] * offset, tip[1] - left[1] * offset)
                    side_h = -1.0
                path = _same_side_rim_path(
                    end_pt, target, best_chain, offset, side_h, sample, active
                )
                if path is None or len(path) < 2:
                    if not is_blocked_by_barrier(end_pt, target, active, endpoint_tolerance=1e-7):
                        path = [end_pt, target]
                    else:
                        continue
                # 只延伸到端头角点，端帽跨侧交给 stitch 的 tip detour 完成
                ext = path[1:]
                if not ext:
                    continue
                if which == "start":
                    pts = list(reversed(ext)) + pts
                else:
                    pts = pts + ext
                extended += 1
            pts = _dedupe_consecutive_points(pts, tolerance=max(step * 1e-5, 1e-9))
            if len(pts) >= 3:
                pts = _cartographic_smooth_polyline(pts, step, iterations=2)
            # 延伸后不得进缓冲
            if any(_point_distance_to_barriers(p, active) < buf * 0.90 for p in pts):
                # 轻裁：丢弃过近点
                cleaned: List[PointTuple] = []
                for p in pts:
                    if _point_distance_to_barriers(p, active) < buf * 0.90:
                        if cleaned:
                            rim = _snap_point_to_barrier_buffer_rim(cleaned[-1], active, buf)
                            if _point_distance(cleaned[-1], rim) > step * 1e-6:
                                cleaned.append(rim)
                        continue
                    cleaned.append((float(p[0]), float(p[1])))
                pts = cleaned if len(cleaned) >= 2 else pts
            if len(pts) >= 2:
                kept.append(pts)
        out[float(level)] = kept
    return out, extended


def connect_open_contours_along_surface_edge(
    contours: Dict[float, List[List[PointTuple]]],
    surface_grid: np.ndarray,
    surface_x: np.ndarray,
    surface_y: np.ndarray,
    barriers: Sequence[BarrierLine] = (),
    grid_step: float = 1.0,
    max_walk_cells: int = 0,
    buffer_distance: float = 0.0,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """把同一级别、同侧开放端点沿趋势面有效域 / 打断缓冲外缘续接。

    用户要求：靠近打断线缓冲区时，等值线应沿缓冲区边缘下来/贴边走，
    不要悬空断开；仍禁止穿越打断线。
    """
    if surface_grid is None or surface_grid.size == 0 or len(surface_x) < 2 or len(surface_y) < 2:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0

    rows, cols = surface_grid.shape
    grid = np.asarray(surface_grid, dtype=float)
    finite = np.isfinite(grid)
    # 缓冲带常被写成 0 值（有限），贴边需要把“低值缓冲带”也视为障碍侧
    # 判定：邻格为 nan，或邻格值接近 0 且自身明显更高 → 边缘
    zero_like = finite & (np.abs(grid) <= 1e-9)
    walkable = finite & ~zero_like  # 真正参与贴边行走的有效趋势面单元
    if not bool(walkable.any()):
        walkable = finite

    edge = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            if not walkable[r, c]:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    edge[r, c] = True
                    break
                if not walkable[nr, nc]:
                    edge[r, c] = True
                    break
            # 靠近打断线的 walkable 单元也强制视为可贴边边缘
            if barriers and not edge[r, c]:
                pt = (float(surface_x[c]), float(surface_y[r]))
                d_bar = _point_distance_to_barriers(pt, barriers)
                hug_band = max(float(buffer_distance) * 1.15, float(grid_step) * 2.0) if buffer_distance > 0 else float(grid_step) * 2.5
                if d_bar <= hug_band:
                    edge[r, c] = True

    xs = np.asarray(surface_x, dtype=float)
    ys = np.asarray(surface_y, dtype=float)
    step = max(float(grid_step), 1e-9)
    near_edge_tol = step * 4.0  # 放宽：靠近缓冲也能抓到边缘
    if max_walk_cells <= 0:
        max_walk_cells = max(rows, cols) * 3

    def _nearest_edge_cell(pt: PointTuple) -> Optional[Tuple[int, int]]:
        # 粗定位最近格
        c0 = int(np.argmin(np.abs(xs - pt[0])))
        r0 = int(np.argmin(np.abs(ys - pt[1])))
        best = None
        best_d = math.inf
        r_lo = max(0, r0 - 3)
        r_hi = min(rows - 1, r0 + 3)
        c_lo = max(0, c0 - 3)
        c_hi = min(cols - 1, c0 + 3)
        for r in range(r_lo, r_hi + 1):
            for c in range(c_lo, c_hi + 1):
                if not edge[r, c]:
                    continue
                d = math.hypot(float(xs[c]) - pt[0], float(ys[r]) - pt[1])
                if d < best_d:
                    best_d = d
                    best = (r, c)
        if best is None or best_d > near_edge_tol * 1.5:
            return None
        return best

    def _cell_center(rc: Tuple[int, int]) -> PointTuple:
        r, c = rc
        return (float(xs[c]), float(ys[r]))

    def _edge_path(a: Tuple[int, int], b: Tuple[int, int]) -> Optional[List[PointTuple]]:
        """BFS 仅沿 edge 单元，且边不跨打断线。"""
        if a == b:
            return [_cell_center(a)]
        from collections import deque
        q = deque([a])
        prev: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {a: None}
        steps = 0
        while q and steps < max_walk_cells:
            steps += 1
            cur = q.popleft()
            if cur == b:
                break
            cr, cc = cur
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = cr + dr, cc + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                nxt = (nr, nc)
                if nxt in prev or not edge[nr, nc]:
                    continue
                p0 = _cell_center(cur)
                p1 = _cell_center(nxt)
                if barriers and is_blocked_by_barrier(p0, p1, barriers, endpoint_tolerance=1e-7):
                    continue
                prev[nxt] = cur
                q.append(nxt)
        if b not in prev:
            return None
        # 回溯
        chain: List[PointTuple] = []
        node: Optional[Tuple[int, int]] = b
        while node is not None:
            chain.append(_cell_center(node))
            node = prev[node]
        chain.reverse()
        if len(chain) < 2:
            return None
        # 路径过长则放弃（避免绕大半圈）
        path_len = sum(
            math.hypot(chain[i + 1][0] - chain[i][0], chain[i + 1][1] - chain[i][1])
            for i in range(len(chain) - 1)
        )
        chord = math.hypot(chain[-1][0] - chain[0][0], chain[-1][1] - chain[0][1])
        if path_len > max(chord * 4.0, step * 40.0):
            return None
        return chain

    joined = 0
    out: Dict[float, List[List[PointTuple]]] = {}
    max_join_rounds = 40  # 防止死循环导致内存暴涨/闪退
    for level, lines in contours.items():
        working = [list(ln) for ln in lines if len(ln) >= 2]
        skipped_pairs: set = set()
        # 反复尝试沿边拼接
        rounds = 0
        while len(working) >= 2 and rounds < max_join_rounds:
            rounds += 1
            # 收集开放端点
            ends: List[Tuple[int, str, PointTuple, Tuple[int, int]]] = []
            for i, ln in enumerate(working):
                if _is_closed_polyline(ln, grid_step):
                    continue
                for which, pt in (("start", ln[0]), ("end", ln[-1])):
                    p = (float(pt[0]), float(pt[1]))
                    cell = _nearest_edge_cell(p)
                    if cell is None:
                        continue
                    ends.append((i, which, p, cell))
            if len(ends) > 80:
                ends = ends[:80]
            best = None  # (path_len, i, which_i, j, which_j, path)
            for a_idx in range(len(ends)):
                i, wi, pi, ci = ends[a_idx]
                for b_idx in range(a_idx + 1, len(ends)):
                    j, wj, pj, cj = ends[b_idx]
                    if i == j:
                        continue
                    pair_key = (min(i, j), max(i, j), wi, wj)
                    if pair_key in skipped_pairs:
                        continue
                    path = _edge_path(ci, cj)
                    if path is None:
                        continue
                    plen = sum(
                        math.hypot(path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
                        for k in range(len(path) - 1)
                    )
                    if best is None or plen < best[0]:
                        best = (plen, i, wi, j, wj, path)
            if best is None:
                break
            _, i, wi, j, wj, path = best
            li = list(working[i])
            lj = list(working[j])
            if wi == "start":
                li = list(reversed(li))
            if wj == "end":
                lj = list(reversed(lj))
            merged = li + path[1:-1] + lj
            merged = _dedupe_consecutive_points(merged, tolerance=max(step * 1e-5, 1e-9))
            if len(merged) < 2:
                skipped_pairs.add((min(i, j), max(i, j), wi, wj))
                continue
            others = [ln for k, ln in enumerate(working) if k not in (i, j)]
            if any(_polylines_properly_cross(merged, other, step) for other in others):
                skipped_pairs.add((min(i, j), max(i, j), wi, wj))
                continue
            hi, lo = (i, j) if i > j else (j, i)
            working[lo] = merged
            del working[hi]
            skipped_pairs.clear()  # 索引已变，清空
            joined += 1
        out[float(level)] = working
    return out, joined


def hug_open_ends_along_barrier_buffer(
    contours: Dict[float, List[List[PointTuple]]],
    surface_grid: np.ndarray,
    surface_x: np.ndarray,
    surface_y: np.ndarray,
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
    max_extend_cells: int = 48,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """把靠近打断缓冲、仍悬空的开放端点，沿缓冲带外缘单向延伸。

    解决“有的区域靠近缓冲区没有沿着缓冲区下来”的问题：
    不跨线，只在缓冲外缘（有效趋势面一侧）贴着走。
    """
    if not barriers or surface_grid is None or surface_grid.size == 0:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0

    rows, cols = surface_grid.shape
    grid = np.asarray(surface_grid, dtype=float)
    xs = np.asarray(surface_x, dtype=float)
    ys = np.asarray(surface_y, dtype=float)
    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.5)
    finite = np.isfinite(grid)
    zero_like = finite & (np.abs(grid) <= 1e-9)
    walkable = finite & ~zero_like
    if not bool(walkable.any()):
        walkable = finite

    # 缓冲外缘：walkable 且到打断线距离在 (buf*0.55, buf*1.35)
    edge_cells: List[Tuple[int, int]] = []
    for r in range(rows):
        for c in range(cols):
            if not walkable[r, c]:
                continue
            pt = (float(xs[c]), float(ys[r]))
            d = _point_distance_to_barriers(pt, barriers)
            if buf * 0.45 <= d <= buf * 1.45:
                edge_cells.append((r, c))
            else:
                # 也接受与 0/nan 邻接的 walkable
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols or not walkable[nr, nc]:
                        if d <= buf * 1.6:
                            edge_cells.append((r, c))
                        break
    if not edge_cells:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0

    edge_set = set(edge_cells)

    def _center(rc: Tuple[int, int]) -> PointTuple:
        return (float(xs[rc[1]]), float(ys[rc[0]]))

    def _nearest_edge(pt: PointTuple) -> Optional[Tuple[int, int]]:
        best = None
        best_d = math.inf
        c0 = int(np.argmin(np.abs(xs - pt[0])))
        r0 = int(np.argmin(np.abs(ys - pt[1])))
        for r in range(max(0, r0 - 5), min(rows, r0 + 6)):
            for c in range(max(0, c0 - 5), min(cols, c0 + 6)):
                if (r, c) not in edge_set:
                    continue
                d = math.hypot(float(xs[c]) - pt[0], float(ys[r]) - pt[1])
                if d < best_d:
                    best_d = d
                    best = (r, c)
        if best is None or best_d > step * 5.0:
            return None
        return best

    def _extend_from(start: Tuple[int, int], away_from: PointTuple) -> List[PointTuple]:
        """从边缘格出发，沿边缘尽量远离 away_from，贴缓冲走。"""
        path: List[PointTuple] = [_center(start)]
        visited = {start}
        cur = start
        for _ in range(max_extend_cells):
            cr, cc = cur
            candidates: List[Tuple[float, Tuple[int, int]]] = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = cr + dr, cc + dc
                nxt = (nr, nc)
                if nxt in visited or nxt not in edge_set:
                    continue
                p1 = _center(nxt)
                # 不跨打断线
                if is_blocked_by_barrier(path[-1], p1, barriers, endpoint_tolerance=1e-7):
                    continue
                # 优先：仍靠近缓冲 + 沿缓冲方向推进（远离起点）
                d_bar = _point_distance_to_barriers(p1, barriers)
                if d_bar > buf * 1.6:
                    continue
                progress = math.hypot(p1[0] - away_from[0], p1[1] - away_from[1])
                # 略偏好沿缓冲（d_bar 接近 buf）
                score = progress - abs(d_bar - buf) * 0.35
                candidates.append((score, nxt))
            if not candidates:
                break
            candidates.sort(key=lambda t: t[0], reverse=True)
            cur = candidates[0][1]
            visited.add(cur)
            path.append(_center(cur))
        return path

    hugged = 0
    out: Dict[float, List[List[PointTuple]]] = {}
    for level, lines in contours.items():
        new_lines: List[List[PointTuple]] = []
        for ln in lines:
            if len(ln) < 2 or _is_closed_polyline(ln, grid_step):
                new_lines.append(list(ln))
                continue
            pts = list(ln)
            # 两端各尝试贴边延伸
            for which in ("start", "end"):
                end_pt = (float(pts[0][0]), float(pts[0][1])) if which == "start" else (float(pts[-1][0]), float(pts[-1][1]))
                d_bar = _point_distance_to_barriers(end_pt, barriers)
                if d_bar > buf * 1.8 and d_bar > step * 3.5:
                    continue
                cell = _nearest_edge(end_pt)
                if cell is None:
                    continue
                # away_from：端点内侧一点，用于决定延伸方向
                if which == "start" and len(pts) >= 2:
                    inner = (float(pts[1][0]), float(pts[1][1]))
                elif which == "end" and len(pts) >= 2:
                    inner = (float(pts[-2][0]), float(pts[-2][1]))
                else:
                    inner = end_pt
                ext = _extend_from(cell, inner)
                if len(ext) < 3:
                    continue
                # 贴格路径先压阶梯+平滑，避免阶梯锯齿互相交叉
                ext = _cartographic_smooth_polyline(ext, step, iterations=3)
                if len(ext) < 2:
                    continue
                if which == "start":
                    pts = list(reversed(ext)) + pts
                else:
                    pts = pts + ext
                hugged += 1
            pts = _dedupe_consecutive_points(pts, tolerance=max(step * 1e-5, 1e-9))
            if len(pts) >= 3:
                pts = _cartographic_smooth_polyline(pts, step, iterations=2)
            if len(pts) >= 2:
                new_lines.append(pts)
        out[float(level)] = new_lines
    return out, hugged


def remove_barrier_artifact_contours(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    grid_step: float,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """Remove seam artifacts caused by merging independently interpolated regions.

    The barrier's job is to decide which wells are used during interpolation.
    When two independently interpolated regions are merged into one raster, a
    level can appear exactly on the barrier because values jump across the
    partition. That line is a numerical seam, not a geological contour. Remove
    only contours whose vertices mostly lie directly on a barrier; ordinary
    contours that merely approach or cross the partition are kept.
    """
    if not barriers:
        return {float(level): [list(line) for line in lines] for level, lines in contours.items()}, 0

    tolerance = max(float(grid_step) * 0.35, 1e-9)
    cleaned: Dict[float, List[List[PointTuple]]] = {}
    removed = 0
    for level, lines in contours.items():
        kept: List[List[PointTuple]] = []
        for line in lines:
            if len(line) < 2:
                continue
            near_count = sum(
                1 for pt in line
                if _point_distance_to_barriers(pt, barriers) <= tolerance
            )
            near_ratio = near_count / max(len(line), 1)
            if near_ratio >= 0.85:
                removed += 1
                continue
            kept.append(list(line))
        cleaned[float(level)] = kept
    return cleaned, removed


def _point_distance_to_barriers(pt: PointTuple, barriers: Sequence[BarrierLine]) -> float:
    best = math.inf
    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            best = min(best, _point_to_segment_distance(pt, p0, p1))
    return best


def _nearest_barrier_projection(
    pt: PointTuple, barriers: Sequence[BarrierLine]
) -> Optional[Tuple[PointTuple, PointTuple, PointTuple, float]]:
    """最近打断线段上的投影：(proj, seg_a, seg_b, dist)。"""
    best = None
    best_d = math.inf
    px, py = float(pt[0]), float(pt[1])
    for barrier in barriers:
        for a, b in _segments(barrier.points):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            vx, vy = bx - ax, by - ay
            ll = vx * vx + vy * vy
            if ll <= 1e-24:
                qx, qy = ax, ay
            else:
                t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / ll))
                qx, qy = ax + t * vx, ay + t * vy
            d = math.hypot(px - qx, py - qy)
            if d < best_d:
                best_d = d
                best = ((qx, qy), (ax, ay), (bx, by), d)
    return best


def _side_sign_of_point(pt: PointTuple, a: PointTuple, b: PointTuple) -> float:
    """点相对有向线段 ab 的左右侧符号（叉积）。"""
    return (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])


def _barrier_chains(barriers: Sequence[BarrierLine]) -> List[List[PointTuple]]:
    chains: List[List[PointTuple]] = []
    for barrier in barriers:
        pts = [(float(p[0]), float(p[1])) for p in (barrier.points or ())]
        if len(pts) >= 2:
            chains.append(pts)
    return chains


def _project_on_chain(
    pt: PointTuple, chain: Sequence[PointTuple]
) -> Tuple[Optional[PointTuple], int, float, float]:
    best = None
    best_d = math.inf
    best_i = 0
    best_t = 0.0
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        vx, vy = bx - ax, by - ay
        ll = vx * vx + vy * vy
        if ll <= 1e-24:
            t, qx, qy = 0.0, ax, ay
        else:
            t = max(0.0, min(1.0, ((pt[0] - ax) * vx + (pt[1] - ay) * vy) / ll))
            qx, qy = ax + t * vx, ay + t * vy
        d = math.hypot(pt[0] - qx, pt[1] - qy)
        if d < best_d:
            best_d = d
            best = (qx, qy)
            best_i = i
            best_t = t
    return best, best_i, best_t, best_d


def _offset_point_on_chain(
    chain: Sequence[PointTuple],
    seg_i: int,
    t: float,
    offset: float,
    side_sign: float,
) -> PointTuple:
    """链上参数位置的外侧偏移点（距链 = offset）。"""
    a = chain[max(0, min(seg_i, len(chain) - 2))]
    b = chain[max(1, min(seg_i + 1, len(chain) - 1))]
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    px = ax + (bx - ax) * float(t)
    py = ay + (by - ay) * float(t)
    tx, ty = bx - ax, by - ay
    tl = math.hypot(tx, ty) or 1.0
    tx, ty = tx / tl, ty / tl
    nx, ny = -ty, tx
    if side_sign < 0:
        nx, ny = -nx, -ny
    return (px + nx * offset, py + ny * offset)


def _tip_endcap_arc(
    tip: PointTuple,
    inward: PointTuple,
    from_pt: PointTuple,
    to_pt: PointTuple,
    radius: float,
    sample_step: float,
) -> List[PointTuple]:
    """缓冲端帽半圆弧：from_pt → to_pt，走端头外侧（不穿进链体）。"""
    tx, ty = float(tip[0]), float(tip[1])
    ix, iy = float(inward[0]), float(inward[1])
    il = math.hypot(ix, iy) or 1.0
    ix, iy = ix / il, iy / il
    mid_ang = math.atan2(-iy, -ix)
    a0 = math.atan2(from_pt[1] - ty, from_pt[0] - tx)
    a1 = math.atan2(to_pt[1] - ty, to_pt[0] - tx)

    def _covers(a_from: float, delta: float, prefer: float) -> bool:
        if delta >= 0:
            t = (prefer - a_from) % (2.0 * math.pi)
            return t <= delta + 1e-9
        t = (a_from - prefer) % (2.0 * math.pi)
        return t <= (-delta) + 1e-9

    d_ccw = (a1 - a0) % (2.0 * math.pi)
    if d_ccw <= 1e-12:
        d_ccw = 2.0 * math.pi
    d_cw = -((a0 - a1) % (2.0 * math.pi))
    if abs(d_cw) <= 1e-12:
        d_cw = -2.0 * math.pi

    c_ccw = _covers(a0, d_ccw, mid_ang)
    c_cw = _covers(a0, d_cw, mid_ang)
    if c_ccw and not c_cw:
        start, delta = a0, d_ccw
    elif c_cw and not c_ccw:
        start, delta = a0, d_cw
    else:
        start, delta = (a0, d_ccw) if abs(d_ccw) <= abs(d_cw) else (a0, d_cw)

    arc_len = abs(delta) * max(radius, 1e-9)
    n = max(4, int(math.ceil(arc_len / max(sample_step, 1e-9))))
    pts: List[PointTuple] = []
    for k in range(n + 1):
        ang = start + delta * (k / n)
        pts.append((tx + math.cos(ang) * radius, ty + math.sin(ang) * radius))
    return pts


def _same_side_rim_path(
    p0: PointTuple,
    p1: PointTuple,
    chain: Sequence[PointTuple],
    offset: float,
    side_hint: float,
    sample_step: float,
    barriers: Sequence[BarrierLine],
) -> Optional[List[PointTuple]]:
    """同侧沿缓冲外缘连接 p0→p1。"""
    a_proj, ai, at, ad = _project_on_chain(p0, chain)
    b_proj, bi, bt, bd = _project_on_chain(p1, chain)
    if a_proj is None or b_proj is None:
        return None
    if ad > offset * 2.5 and bd > offset * 2.5:
        return None

    samples: List[Tuple[PointTuple, int, float]] = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(seg_len / max(sample_step, 1e-9)))
        for k in range(n):
            t = k / n
            samples.append(
                (
                    (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])),
                    i,
                    t,
                )
            )
    samples.append((chain[-1], max(0, len(chain) - 2), 1.0))
    if len(samples) < 2:
        return None

    def _nearest_idx(pt: PointTuple) -> int:
        bi2, bd2 = 0, math.inf
        for i, (s, _, _) in enumerate(samples):
            d = math.hypot(s[0] - pt[0], s[1] - pt[1])
            if d < bd2:
                bd2 = d
                bi2 = i
        return bi2

    i0 = _nearest_idx(a_proj)
    i1 = _nearest_idx(b_proj)
    if i0 == i1:
        return [p0, p1]
    lo, hi = (i0, i1) if i0 < i1 else (i1, i0)
    mid = samples[lo : hi + 1]
    if i0 > i1:
        mid = list(reversed(mid))

    side = 1.0 if side_hint >= 0 else -1.0
    path: List[PointTuple] = [p0]
    for s, si, st in mid:
        op = _offset_point_on_chain(chain, si, st, offset, side)
        if is_blocked_by_barrier(path[-1], op, barriers, endpoint_tolerance=1e-7):
            op2 = _offset_point_on_chain(chain, si, st, offset * 1.08, side)
            if is_blocked_by_barrier(path[-1], op2, barriers, endpoint_tolerance=1e-7):
                continue
            op = op2
        path.append(op)
    if is_blocked_by_barrier(path[-1], p1, barriers, endpoint_tolerance=1e-7):
        return None
    path.append(p1)
    if len(path) < 2:
        return None
    return path


def _tip_detour_path(
    p0: PointTuple,
    p1: PointTuple,
    chain: Sequence[PointTuple],
    tip_idx: int,
    offset: float,
    sample_step: float,
    barriers: Sequence[BarrierLine],
) -> Optional[List[PointTuple]]:
    """绕缓冲端头连接 p0→p1（可跨侧）：侧缘 → 端帽半圆 → 另一侧缘。"""
    if len(chain) < 2:
        return None
    tip = chain[0] if tip_idx == 0 else chain[-1]
    if tip_idx == 0:
        nxt = chain[1]
        inward = (float(nxt[0] - tip[0]), float(nxt[1] - tip[1]))
    else:
        prv = chain[-2]
        inward = (float(prv[0] - tip[0]), float(prv[1] - tip[1]))
    il = math.hypot(inward[0], inward[1]) or 1.0
    inward = (inward[0] / il, inward[1] / il)
    left = (-inward[1], inward[0])
    left_rim = (tip[0] + left[0] * offset, tip[1] + left[1] * offset)
    right_rim = (tip[0] - left[0] * offset, tip[1] - left[1] * offset)

    d0l = math.hypot(p0[0] - left_rim[0], p0[1] - left_rim[1])
    d0r = math.hypot(p0[0] - right_rim[0], p0[1] - right_rim[1])
    if d0l <= d0r:
        a_rim, b_rim = left_rim, right_rim
        side_a, side_b = 1.0, -1.0
    else:
        a_rim, b_rim = right_rim, left_rim
        side_a, side_b = -1.0, 1.0

    leg0 = _same_side_rim_path(p0, a_rim, chain, offset, side_a, sample_step, barriers)
    if leg0 is None:
        if _point_distance(p0, a_rim) <= offset * 3.5 and not is_blocked_by_barrier(
            p0, a_rim, barriers, endpoint_tolerance=1e-7
        ):
            leg0 = [p0, a_rim]
        else:
            return None
    leg1 = _same_side_rim_path(b_rim, p1, chain, offset, side_b, sample_step, barriers)
    if leg1 is None:
        if _point_distance(b_rim, p1) <= offset * 3.5 and not is_blocked_by_barrier(
            b_rim, p1, barriers, endpoint_tolerance=1e-7
        ):
            leg1 = [b_rim, p1]
        else:
            return None

    arc = _tip_endcap_arc(tip, inward, a_rim, b_rim, offset, sample_step)
    path = list(leg0)
    if arc:
        if _point_distance(path[-1], arc[0]) < sample_step * 0.5:
            path.extend(arc[1:])
        else:
            path.extend(arc)
    if leg1:
        if _point_distance(path[-1], leg1[0]) < sample_step * 0.5:
            path.extend(leg1[1:])
        else:
            path.extend(leg1)
    if len(path) < 3:
        return None
    for pt in path[1:-1]:
        if _point_distance_to_barriers(pt, barriers) < offset * 0.82:
            return None
    return path


def _buffer_rim_detour_path(
    p0: PointTuple,
    p1: PointTuple,
    barriers: Sequence[BarrierLine],
    offset: float,
    sample_step: float,
    *,
    allow_tip: bool = True,
    side_hint: float = 0.0,
) -> Optional[List[PointTuple]]:
    """缓冲外缘绕行路径：同侧贴缘，或跨侧绕端头半圆。绝不穿入缓冲内部。"""
    if not barriers or offset <= 0:
        return None
    chains = _barrier_chains(barriers)
    if not chains:
        return None

    best: Optional[List[PointTuple]] = None
    best_len = math.inf
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])

    def _plen(path: Sequence[PointTuple]) -> float:
        return sum(
            math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
            for i in range(len(path) - 1)
        )

    for chain in chains:
        a_proj, ai, at, ad = _project_on_chain(p0, chain)
        b_proj, bi, bt, bd = _project_on_chain(p1, chain)
        if a_proj is None or b_proj is None:
            continue
        if ad > offset * 3.0 and bd > offset * 3.0:
            continue
        sa = _side_sign_of_point(p0, chain[ai], chain[min(ai + 1, len(chain) - 1)])
        sb = _side_sign_of_point(p1, chain[bi], chain[min(bi + 1, len(chain) - 1)])
        same_side = sa * sb >= -1e-9

        candidates: List[List[PointTuple]] = []
        if same_side:
            sh = side_hint if abs(side_hint) > 1e-12 else (sa if abs(sa) >= abs(sb) else sb)
            if abs(sh) < 1e-12:
                sh = 1.0
            path = _same_side_rim_path(p0, p1, chain, offset, sh, sample_step, barriers)
            if path is not None:
                candidates.append(path)
        if allow_tip:
            for tip_flag in (0, -1):
                path = _tip_detour_path(
                    p0, p1, chain, tip_flag, offset, sample_step, barriers
                )
                if path is not None:
                    candidates.append(path)

        for path in candidates:
            plen = _plen(path)
            lim = max(chord * 12.0, offset * 48.0, sample_step * 160.0)
            if plen > lim:
                continue
            if plen < best_len:
                best_len = plen
                best = path
    return best


def _barrier_offset_path(
    p0: PointTuple,
    p1: PointTuple,
    barriers: Sequence[BarrierLine],
    offset: float,
    side_hint: float,
    sample_step: float,
) -> Optional[List[PointTuple]]:
    """沿最近打断折线，在同侧外缘生成连接 p0→p1 的贴边折线（不跨线）。"""
    return _buffer_rim_detour_path(
        p0,
        p1,
        barriers,
        offset,
        sample_step,
        allow_tip=False,
        side_hint=side_hint,
    )


def _polyline_self_intersects(pts: Sequence[PointTuple], grid_step: float) -> bool:
    """折线是否存在非相邻段的严格自交（闭合首尾邻接除外）。"""
    n = len(pts)
    if n < 4:
        return False
    closed = _is_closed_polyline(pts, grid_step)
    for i in range(n - 1):
        for j in range(i + 2, n - 1):
            if closed and i == 0 and j == n - 2:
                continue
            if abs(i - j) <= 1:
                continue
            if _segment_intersection_point(pts[i], pts[i + 1], pts[j], pts[j + 1]) is not None:
                return True
    return False


def _path_crosses_any(
    path: Sequence[PointTuple],
    others: Sequence[Sequence[PointTuple]],
    grid_step: float,
) -> bool:
    """path 是否与 others 中任一条折线严格相交（共享端点不算）。"""
    if len(path) < 2:
        return False
    for o in others:
        if len(o) < 2:
            continue
        if _polylines_properly_cross(path, o, grid_step):
            return True
    return False


def stitch_open_contours_along_barrier_edge(
    contours: Dict[float, List[List[PointTuple]]],
    barriers: Sequence[BarrierLine],
    buffer_distance: float,
    grid_step: float,
    max_rounds: int = 24,
    *,
    allow_long_detour: bool = False,
) -> Tuple[Dict[float, List[List[PointTuple]]], int]:
    """同级、同侧、贴打断缓冲的开放端点沿缓冲外缘续接。

    硬约束：拼接路径/合并结果不得与其它等值线相交，也不得自交、不得穿打断线。
    allow_long_detour=True：允许沿缓冲外缘绕得更远（实现“绕开缓冲区”）。
    """
    if not barriers or buffer_distance <= 0:
        return {float(k): [list(ln) for ln in v] for k, v in contours.items()}, 0

    step = max(float(grid_step), 1e-9)
    buf = max(float(buffer_distance), step * 1.2)
    # 端点在缓冲外缘附近即可参与绕行（放宽，避免侧壁端点漏接）
    near_lim = buf * (2.6 if allow_long_detour else 1.35) + step * 4.0
    # 外缘路径：略大于 buf，走在绿色缓冲带外侧
    offset = max(buf * (1.08 if allow_long_detour else 0.95), step * 1.2)
    max_chord = (
        max(buf * 48.0, step * 160.0)
        if allow_long_detour
        else max(buf * 6.0, step * 28.0)
    )
    joined = 0
    out: Dict[float, List[List[PointTuple]]] = {}

    for level, lines in contours.items():
        working = [list(ln) for ln in lines if len(ln) >= 2]
        failed_pairs: set = set()
        rounds = 0
        while rounds < max_rounds and len(working) >= 2:
            rounds += 1
            ends: List[Tuple[int, str, PointTuple, float, float]] = []
            for i, ln in enumerate(working):
                if _is_closed_polyline(ln, step):
                    continue
                for which, pt in (("start", ln[0]), ("end", ln[-1])):
                    p = (float(pt[0]), float(pt[1]))
                    proj = _nearest_barrier_projection(p, barriers)
                    if proj is None:
                        continue
                    _, a, b, d = proj
                    if d > near_lim:
                        continue
                    side = _side_sign_of_point(p, a, b)
                    ends.append((i, which, p, side, d))
            if len(ends) < 2:
                break

            best = None  # (score, i, wi, j, wj, path)
            for a_idx in range(len(ends)):
                i, wi, pi, si, di = ends[a_idx]
                for b_idx in range(a_idx + 1, len(ends)):
                    j, wj, pj, sj, dj = ends[b_idx]
                    if i == j:
                        continue
                    pair_key = (min(i, j), max(i, j), wi, wj)
                    if pair_key in failed_pairs:
                        continue
                    opposite = si * sj < -1e-6 and abs(si) > 1e-8 and abs(sj) > 1e-8
                    # 对侧仅允许长绕行（绕缓冲端头），禁止直线穿缓冲
                    if opposite and not allow_long_detour:
                        continue
                    chord = math.hypot(pj[0] - pi[0], pj[1] - pi[1])
                    if chord < step * 0.35 or chord > max_chord:
                        continue

                    # 优先：短直线（同侧、不跨打断、不进缓冲）
                    path: Optional[List[PointTuple]] = None
                    if (
                        not opposite
                        and not is_blocked_by_barrier(pi, pj, barriers, endpoint_tolerance=1e-7)
                    ):
                        mid = (0.5 * (pi[0] + pj[0]), 0.5 * (pi[1] + pj[1]))
                        if _point_distance_to_barriers(mid, barriers) >= buf * 0.85:
                            if chord <= max(buf * (4.5 if allow_long_detour else 3.5), step * 12.0):
                                path = [pi, pj]

                    # 其次：缓冲外缘绕行（同侧贴缘 / 对侧绕端头半圆）
                    if path is None:
                        side_hint = si if abs(si) >= abs(sj) else sj
                        if abs(side_hint) < 1e-12:
                            side_hint = 1.0
                        cand = _buffer_rim_detour_path(
                            pi,
                            pj,
                            barriers,
                            offset,
                            max(step * 0.75, buf * 0.12),
                            allow_tip=bool(allow_long_detour or opposite),
                            side_hint=side_hint,
                        )
                        if cand is not None and len(cand) >= 2:
                            plen = sum(
                                math.hypot(
                                    cand[k + 1][0] - cand[k][0],
                                    cand[k + 1][1] - cand[k][1],
                                )
                                for k in range(len(cand) - 1)
                            )
                            lim = (
                                max(chord * 12.0, buf * 48.0, step * 160.0)
                                if allow_long_detour
                                else max(chord * 2.8, buf * 5.0, step * 20.0)
                            )
                            if plen <= lim:
                                path = cand
                    if path is None:
                        continue

                    # 路径不得与「其它线」及「i/j 本体（去掉端点邻接）」交叉
                    others_for_path: List[Sequence[PointTuple]] = []
                    for k, ln in enumerate(working):
                        if k == i or k == j:
                            # 本体：去掉靠近连接端的首/尾一段，避免端点误判
                            body = list(ln)
                            if k == i:
                                if wi == "start" and len(body) > 2:
                                    body = body[1:]
                                elif wi == "end" and len(body) > 2:
                                    body = body[:-1]
                            if k == j:
                                if wj == "start" and len(body) > 2:
                                    body = body[1:]
                                elif wj == "end" and len(body) > 2:
                                    body = body[:-1]
                            if len(body) >= 2:
                                others_for_path.append(body)
                        else:
                            others_for_path.append(ln)
                    if _path_crosses_any(path, others_for_path, step):
                        continue
                    if _polyline_self_intersects(path, step):
                        continue

                    plen = sum(
                        math.hypot(path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
                        for k in range(len(path) - 1)
                    )
                    score = plen + 0.1 * (di + dj)
                    if best is None or score < best[0]:
                        best = (score, i, wi, j, wj, path)

            if best is None:
                break
            _, i, wi, j, wj, path = best
            pair_key = (min(i, j), max(i, j), wi, wj)
            li = list(working[i])
            lj = list(working[j])
            if wi == "start":
                li = list(reversed(li))
            if wj == "end":
                lj = list(reversed(lj))
            merged = li + path[1:-1] + lj
            merged = _dedupe_consecutive_points(merged, tolerance=max(step * 1e-5, 1e-9))
            if len(merged) < 2:
                failed_pairs.add(pair_key)
                continue
            others = [ln for k, ln in enumerate(working) if k not in (i, j)]
            if _polyline_self_intersects(merged, step):
                failed_pairs.add(pair_key)
                continue
            if any(_polylines_properly_cross(merged, o, step) for o in others):
                failed_pairs.add(pair_key)
                continue
            hi, lo = (i, j) if i > j else (j, i)
            working[lo] = merged
            del working[hi]
            failed_pairs.clear()
            joined += 1
        out[float(level)] = working
    return out, joined


def sample_bilinear_grid(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    x: float,
    y: float,
) -> Optional[float]:
    """Sample a rectilinear grid with bilinear interpolation (NaN outside finite cells)."""
    if grid.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return None
    x0_axis = float(x_coords[0])
    x1_axis = float(x_coords[-1])
    y0_axis = float(y_coords[0])
    y1_axis = float(y_coords[-1])
    if x < min(x0_axis, x1_axis) or x > max(x0_axis, x1_axis):
        return None
    if y < min(y0_axis, y1_axis) or y > max(y0_axis, y1_axis):
        return None

    dx = float(x_coords[1] - x_coords[0]) if len(x_coords) > 1 else 1.0
    dy = float(y_coords[1] - y_coords[0]) if len(y_coords) > 1 else dx
    if abs(dx) <= 1e-24 or abs(dy) <= 1e-24:
        return None

    col_f = (float(x) - float(x_coords[0])) / dx
    row_f = (float(y) - float(y_coords[0])) / dy
    col0 = int(math.floor(col_f))
    row0 = int(math.floor(row_f))
    if col0 < 0 or row0 < 0 or col0 >= len(x_coords) - 1 or row0 >= len(y_coords) - 1:
        return None

    fx = col_f - col0
    fy = row_f - row0
    v00 = float(grid[row0, col0])
    v10 = float(grid[row0, col0 + 1])
    v01 = float(grid[row0 + 1, col0])
    v11 = float(grid[row0 + 1, col0 + 1])
    if not all(math.isfinite(value) for value in (v00, v10, v01, v11)):
        return None
    top = v00 * (1.0 - fx) + v10 * fx
    bottom = v01 * (1.0 - fx) + v11 * fx
    return top * (1.0 - fy) + bottom * fy


def _estimate_grid_step(x_coords: np.ndarray, y_coords: np.ndarray) -> float:
    dx = float(np.nanmedian(np.diff(x_coords))) if len(x_coords) > 1 else 1.0
    dy = float(np.nanmedian(np.diff(y_coords))) if len(y_coords) > 1 else dx
    return max(abs(dx), abs(dy), 1e-9)


def _grid_aspect(x_coords: np.ndarray, y_coords: np.ndarray) -> float:
    """网格单元的 step_y/step_x，用于各向异性扩散把网格 offset 换算到地图方向。"""
    step_x = abs(float(x_coords[1] - x_coords[0])) if len(x_coords) > 1 else 1.0
    step_y = abs(float(y_coords[1] - y_coords[0])) if len(y_coords) > 1 else step_x
    return step_y / step_x if step_x > 1e-12 else 1.0


def _dedupe_consecutive_points(points: Sequence[PointTuple], tolerance: float) -> List[PointTuple]:
    deduped: List[PointTuple] = []
    for pt in points:
        current = (float(pt[0]), float(pt[1]))
        if not deduped or _point_distance(deduped[-1], current) > tolerance:
            deduped.append(current)
    return deduped


def _polyline_length(points: Sequence[PointTuple]) -> float:
    return sum(_point_distance(a, b) for a, b in zip(points, points[1:]))


def _point_distance(a: PointTuple, b: PointTuple) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _contour_close_tolerance(grid_step: float) -> float:
    return max(float(grid_step) * 0.35, 1e-6)


def _is_closed_polyline(points: Sequence[PointTuple], grid_step: float) -> bool:
    return len(points) > 2 and _point_distance(points[0], points[-1]) <= _contour_close_tolerance(grid_step)


def _rdp_simplify(points: Sequence[PointTuple], tolerance: float) -> List[PointTuple]:
    if len(points) <= 2:
        return list(points)
    start = points[0]
    end = points[-1]
    max_distance = -1.0
    split_index = 0
    for index in range(1, len(points) - 1):
        distance = _point_to_segment_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance > tolerance:
        left = _rdp_simplify(points[: split_index + 1], tolerance)
        right = _rdp_simplify(points[split_index:], tolerance)
        return left[:-1] + right
    return [start, end]


def _point_to_segment_distance(pt: PointTuple, a: PointTuple, b: PointTuple) -> float:
    projection = _project_point_to_segment(pt, a, b)
    if projection is None:
        return math.inf
    _t, closest = projection
    return math.hypot(float(pt[0]) - closest[0], float(pt[1]) - closest[1])


def _project_point_to_segment(
    pt: PointTuple,
    a: PointTuple,
    b: PointTuple,
) -> Optional[Tuple[float, Tuple[float, float]]]:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-24:
        return 0.0, (float(ax), float(ay))
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t_clamped = max(0.0, min(1.0, t))
    closest = (ax + t_clamped * dx, ay + t_clamped * dy)
    return float(t_clamped), closest


def _point_within_segment_buffer(
    pt: PointTuple,
    a: PointTuple,
    b: PointTuple,
    buffer_distance: float,
) -> bool:
    """单段打断线缓冲（胶囊形）：中段矩形 + 两端椭圆端帽。

    兼容旧调用；多段折线请用 _point_within_polyline_stadium_buffer。
    """
    return _point_within_polyline_stadium_buffer(pt, (a, b), buffer_distance)


def _point_within_polyline_olive_buffer(
    pt: PointTuple,
    points: Sequence[PointTuple],
    buffer_distance: float,
) -> bool:
    """兼容旧名：现为胶囊/体育场缓冲。"""
    return _point_within_polyline_stadium_buffer(pt, points, buffer_distance)


def _point_within_polyline_stadium_buffer(
    pt: PointTuple,
    points: Sequence[PointTuple],
    buffer_distance: float,
) -> bool:
    """整条打断折线的胶囊缓冲（一个整体）。

    - 中段：到折线的最短距离 ≤ R → 恒宽矩形缓冲带
    - 自由端：圆/椭圆端帽（到端点距离 ≤ R），与中段在端点处半宽均为 R，无缝衔接
    等价于「折线 Minkowski 圆盘」/ stadium，两端为椭圆（圆是椭圆特例）。
    """
    R = float(buffer_distance)
    if R <= 0.0:
        return False
    pts = [(float(p[0]), float(p[1])) for p in points]
    if not pts:
        return False
    px, py = float(pt[0]), float(pt[1])
    if len(pts) == 1:
        return math.hypot(px - pts[0][0], py - pts[0][1]) <= R + 1e-12

    best_d = math.inf
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len <= 1e-12:
            d = math.hypot(px - ax, py - ay)
        else:
            ux, uy = (bx - ax) / seg_len, (by - ay) / seg_len
            along = (px - ax) * ux + (py - ay) * uy
            t = max(0.0, min(1.0, along / seg_len))
            cx = ax + t * (bx - ax)
            cy = ay + t * (by - ay)
            d = math.hypot(px - cx, py - cy)
        if d < best_d:
            best_d = d
    return best_d <= R + 1e-12


def _segment_projection_parameter(
    pt: PointTuple,
    a: PointTuple,
    b: PointTuple,
) -> Optional[float]:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-24:
        return 0.0
    return ((px - ax) * dx + (py - ay) * dy) / length_sq


def _remove_polyline_spikes(
    points: Sequence[PointTuple],
    grid_step: float,
    *,
    min_turn_cos: float = -0.25,
) -> List[PointTuple]:
    """去掉 MS 阶梯形成的尖锐折角（内角过尖的中间顶点）。

    min_turn_cos：相邻方向夹角 cos；过小（接近 -1）表示急转/尖刺。
    """
    if len(points) < 4:
        return list(points)
    step = max(float(grid_step), 1e-9)
    closed = _is_closed_polyline(points, step)
    core = list(points[:-1] if closed else points)
    if len(core) < 3:
        return list(points)

    def _keep_vertex(prev, cur, nxt) -> bool:
        v1x, v1y = cur[0] - prev[0], cur[1] - prev[1]
        v2x, v2y = nxt[0] - cur[0], nxt[1] - cur[1]
        n1 = math.hypot(v1x, v1y)
        n2 = math.hypot(v2x, v2y)
        if n1 < step * 0.15 or n2 < step * 0.15:
            return False  # 极短边尖刺
        cos_a = (v1x * v2x + v1y * v2y) / (n1 * n2)
        # 急折（转角很大）且两边都不长 → 尖刺，删除
        if cos_a < min_turn_cos and n1 < step * 4.0 and n2 < step * 4.0:
            return False
        return True

    changed = True
    guard = 0
    while changed and guard < 4:
        guard += 1
        changed = False
        new_core: List[PointTuple] = []
        m = len(core)
        for i in range(m):
            if not closed and (i == 0 or i == m - 1):
                new_core.append(core[i])
                continue
            prev = core[i - 1]
            cur = core[i]
            nxt = core[(i + 1) % m]
            if _keep_vertex(prev, cur, nxt):
                new_core.append(cur)
            else:
                changed = True
        if len(new_core) < (3 if closed else 2):
            break
        core = new_core
    if closed:
        if core and core[0] != core[-1]:
            core.append(core[0])
        return core
    return core


def _chaikin_smooth_polyline(
    points: Sequence[PointTuple],
    iterations: int,
    grid_step: float,
) -> List[PointTuple]:
    if len(points) <= 2 or iterations <= 0:
        return list(points)
    closed = _is_closed_polyline(points, grid_step)
    current = list(points[:-1] if closed else points)
    if closed and len(current) < 3:
        return list(points)

    for _ in range(iterations):
        if closed:
            smoothed: List[PointTuple] = []
            for index, p0 in enumerate(current):
                p1 = current[(index + 1) % len(current)]
                smoothed.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
                smoothed.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
            current = smoothed
        else:
            smoothed = [current[0]]
            for p0, p1 in zip(current, current[1:]):
                smoothed.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
                smoothed.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
            smoothed.append(current[-1])
            current = smoothed
    if closed:
        current.append(current[0])
    return current


def _collapse_grid_stairs(
    points: Sequence[PointTuple],
    grid_step: float,
) -> List[PointTuple]:
    """压掉贴格阶梯（HVH/VHV 锯齿），把直角短折换成更直的折线。"""
    if len(points) < 4:
        return list(points)
    step = max(float(grid_step), 1e-9)
    closed = _is_closed_polyline(points, step)
    core = list(points[:-1] if closed else points)
    if len(core) < 3:
        return list(points)

    out: List[PointTuple] = [core[0]]
    i = 1
    n = len(core)
    while i < n - 1:
        p0 = out[-1]
        p1 = core[i]
        p2 = core[i + 1]
        d01 = _point_distance(p0, p1)
        d12 = _point_distance(p1, p2)
        # 仅折叠短直角阶梯
        if d01 <= step * 2.8 and d12 <= step * 2.8:
            v1x, v1y = p1[0] - p0[0], p1[1] - p0[1]
            v2x, v2y = p2[0] - p1[0], p2[1] - p1[1]
            n1 = math.hypot(v1x, v1y)
            n2 = math.hypot(v2x, v2y)
            if n1 > 1e-12 and n2 > 1e-12:
                cos_a = (v1x * v2x + v1y * v2y) / (n1 * n2)
                # 接近 90°：跳过中间拐点
                if abs(cos_a) < 0.35:
                    i += 1
                    continue
        out.append(p1)
        i += 1
    out.append(core[-1])
    if closed and out and out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 2 else list(points)


def _moving_average_polyline(
    points: Sequence[PointTuple],
    grid_step: float,
    *,
    passes: int = 2,
) -> List[PointTuple]:
    """轻量三点滑动平均，专治贴格锯齿；端点固定。"""
    if len(points) < 4 or passes <= 0:
        return list(points)
    step = max(float(grid_step), 1e-9)
    closed = _is_closed_polyline(points, step)
    cur = list(points[:-1] if closed else points)
    if len(cur) < 3:
        return list(points)
    for _ in range(max(1, int(passes))):
        nxt: List[PointTuple] = []
        m = len(cur)
        for i in range(m):
            if not closed and (i == 0 or i == m - 1):
                nxt.append(cur[i])
                continue
            p0 = cur[i - 1]
            p1 = cur[i]
            p2 = cur[(i + 1) % m]
            nxt.append(
                (
                    (p0[0] + 2.0 * p1[0] + p2[0]) * 0.25,
                    (p0[1] + 2.0 * p1[1] + p2[1]) * 0.25,
                )
            )
        cur = nxt
    if closed and cur:
        cur.append(cur[0])
    return cur


def _densify_polyline_segments(
    points: Sequence[PointTuple],
    max_seg: float,
) -> List[PointTuple]:
    """Insert vertices on long segments so Chaikin/MA can round curves (not 2-pt stubs)."""
    if len(points) < 2:
        return list(points)
    max_s = max(float(max_seg), 1e-9)
    out: List[PointTuple] = [(float(points[0][0]), float(points[0][1]))]
    for i in range(1, len(points)):
        x0, y0 = float(out[-1][0]), float(out[-1][1])
        x1, y1 = float(points[i][0]), float(points[i][1])
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist > max_s * 1.05:
            n = max(1, int(math.ceil(dist / max_s)))
            for k in range(1, n):
                t = k / float(n)
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


def _cartographic_smooth_polyline(
    points: Sequence[PointTuple],
    grid_step: float,
    *,
    iterations: int = 4,
) -> List[PointTuple]:
    """制图平滑：压阶梯 → 滑动平均 → 去尖刺 → Chaikin；若自交则降迭代回退。"""
    step = max(float(grid_step), 1e-9)
    base = _collapse_grid_stairs(points, step)
    base = _moving_average_polyline(base, step, passes=3)
    base = _remove_polyline_spikes(base, step, min_turn_cos=-0.05)
    # Only remove numerical jitter here. Strong RDP after smoothing recreates
    # long straight chords and visible corners in otherwise smooth isolines.
    if len(base) > 4:
        was_closed = _is_closed_polyline(base, step)
        core = base[:-1] if was_closed else base
        core = _rdp_simplify(core, step * 0.04)
        if was_closed and len(core) >= 3:
            base = core + [core[0]]
        else:
            base = core
    # 长边补点：避免直线被压成 2 点后被 clip/拓扑丢掉，也利于 Chaikin 出弧
    base = _densify_polyline_segments(base, max_seg=step * 1.35)
    base = _dedupe_consecutive_points(base, tolerance=max(step * 1e-6, 1e-9))
    if len(base) < 2:
        return base
    it = max(0, min(8, int(iterations)))
    if it <= 0:
        return base
    if len(base) < 3:
        return base
    # 从强到弱尝试，避免平滑引入自交
    for try_it in range(it, 0, -1):
        cand = _chaikin_smooth_polyline(base, try_it, step)
        cand = _moving_average_polyline(cand, step, passes=2)
        # Chaikin intentionally creates short consecutive segments around a
        # bend. Running the spike remover here mistakes those curve samples for
        # noise and can collapse a rounded arc back into two long chords.
        # 再压一轮细锯齿，随后补密以保持弧线感
        if len(cand) > 6:
            was_closed = _is_closed_polyline(cand, step)
            core = cand[:-1] if was_closed else cand
            core = _rdp_simplify(core, step * 0.025)
            if was_closed and len(core) >= 3:
                cand = core + [core[0]]
            else:
                cand = core
            cand = _densify_polyline_segments(cand, max_seg=step * 1.25)
            cand = _moving_average_polyline(cand, step, passes=1)
        cand = _dedupe_consecutive_points(cand, tolerance=max(step * 1e-6, 1e-9))
        if len(cand) >= 2 and not _polyline_self_intersects(cand, step):
            return cand
    return base


def _bridge_contour_gaps(
    lines: Sequence[List[PointTuple]],
    max_gap: float,
    grid_step: float,
    barriers: Sequence[BarrierLine] = (),
) -> Tuple[List[List[PointTuple]], int]:
    """Greedily join nearby open contour endpoints of the same level."""
    working = [list(line) for line in lines if len(line) >= 2]
    if len(working) < 2 or max_gap <= 0:
        return working, 0

    bridged = 0
    closed_tolerance = _contour_close_tolerance(grid_step)
    while True:
        best: Optional[Tuple[float, int, int, str]] = None
        for i in range(len(working)):
            if _is_closed_polyline(working[i], grid_step):
                continue
            for j in range(i + 1, len(working)):
                if _is_closed_polyline(working[j], grid_step):
                    continue
                candidates = (
                    (_point_distance(working[i][-1], working[j][0]), "end_start"),
                    (_point_distance(working[i][0], working[j][-1]), "start_end"),
                    (_point_distance(working[i][0], working[j][0]), "start_start"),
                    (_point_distance(working[i][-1], working[j][-1]), "end_end"),
                )
                for distance, mode in candidates:
                    if distance > max_gap:
                        continue
                    start_pt, end_pt = _bridge_endpoints_for_mode(working[i], working[j], mode)
                    if barriers and is_blocked_by_barrier(start_pt, end_pt, barriers, endpoint_tolerance=1e-7):
                        continue
                    if not _bridge_connection_is_plausible(working[i], working[j], mode, distance, grid_step):
                        continue
                    # 桥接边不得与其它同级折线交叉
                    if _bridge_would_cross_others(working, i, j, mode, start_pt, end_pt, grid_step):
                        continue
                    if distance <= closed_tolerance:
                        distance = 0.0
                    if best is None or distance < best[0]:
                        best = (distance, i, j, mode)
        if best is None:
            break

        _, i, j, mode = best
        first = working[i]
        second = working[j]
        if mode == "end_start":
            merged = first + second
        elif mode == "start_end":
            merged = second + first
        elif mode == "start_start":
            merged = list(reversed(first)) + second
        else:
            merged = first + list(reversed(second))
        merged = _dedupe_consecutive_points(merged, tolerance=max(grid_step * 1e-6, 1e-9))
        working[i] = merged
        del working[j]
        bridged += 1
    return working, bridged


def _close_near_contour_loops(
    lines: Sequence[List[PointTuple]],
    max_gap: float,
    grid_step: float,
    barriers: Sequence[BarrierLine] = (),
    surface_grid: Optional[np.ndarray] = None,
    surface_x: Optional[np.ndarray] = None,
    surface_y: Optional[np.ndarray] = None,
    barrier_proximity: float = 0.0,
) -> Tuple[List[List[PointTuple]], int]:
    """Close a contour when its own endpoints leave only a small drafting gap.

    Skips closure when ends lie on the formation edge or both ends sit near
    打断线（硬约束处禁止自闭合）。
    """
    if max_gap <= 0:
        return [list(line) for line in lines], 0

    closed_count = 0
    output: List[List[PointTuple]] = []
    step = max(float(grid_step), 1e-9)
    tolerance = max(step * 1e-6, 1e-9)
    proximity = max(float(barrier_proximity), 0.0)
    for raw_line in lines:
        line = _dedupe_consecutive_points(raw_line, tolerance=tolerance)
        if len(line) < 3 or _is_closed_polyline(line, step):
            output.append(line)
            continue

        if _should_force_close_contour(
            line,
            max_gap,
            step,
            barriers=barriers,
            surface_grid=surface_grid,
            surface_x=surface_x,
            surface_y=surface_y,
            max_gap_ratio=0.22,
            max_gap_vs_length=0.16,
            min_gap_cells=4.0,
            barrier_proximity=proximity,
        ):
            line = _seal_open_contour(line, barriers, step)
            closed_count += 1
        output.append(line)
    return output, closed_count


def _bridge_endpoints_for_mode(
    first: Sequence[PointTuple],
    second: Sequence[PointTuple],
    mode: str,
) -> Tuple[PointTuple, PointTuple]:
    if mode == "end_start":
        return first[-1], second[0]
    if mode == "start_end":
        return first[0], second[-1]
    if mode == "start_start":
        return first[0], second[0]
    return first[-1], second[-1]


def _bridge_would_cross_others(
    working: Sequence[Sequence[PointTuple]],
    i: int,
    j: int,
    mode: str,
    start_pt: PointTuple,
    end_pt: PointTuple,
    grid_step: float,
) -> bool:
    """若拟桥接边与任意其它（或自身非端点）线段严格相交，则禁止桥接。"""
    for k, line in enumerate(working):
        if len(line) < 2:
            continue
        nseg = len(line) - 1
        for s in range(nseg):
            # 跳过与端点相连的邻接段（共享端点不算交叉）
            if k == i:
                if mode in ("end_start", "end_end") and s == nseg - 1:
                    continue
                if mode in ("start_end", "start_start") and s == 0:
                    continue
            if k == j:
                if mode in ("end_start", "start_start") and s == 0:
                    continue
                if mode in ("start_end", "end_end") and s == nseg - 1:
                    continue
            if _segment_intersection_point(start_pt, end_pt, line[s], line[s + 1]) is not None:
                return True
    return False


def _bridge_connection_is_plausible(
    first: Sequence[PointTuple],
    second: Sequence[PointTuple],
    mode: str,
    distance: float,
    grid_step: float,
) -> bool:
    """Avoid connecting unrelated contour fragments during cleanup."""
    # Tiny nicks always join — main cause of ugly broken isolines on MS grids.
    if distance <= max(grid_step * 1.5, 1e-9):
        return True

    first_at_start, second_at_start = _bridge_endpoint_sides(mode)
    start_pt, end_pt = _bridge_endpoints_for_mode(first, second, mode)
    connector = _unit_vector((end_pt[0] - start_pt[0], end_pt[1] - start_pt[1]))
    if connector is None:
        return True

    first_tangent = _endpoint_outward_tangent(first, first_at_start)
    second_tangent = _endpoint_outward_tangent(second, second_at_start)
    if first_tangent is None or second_tangent is None:
        return True

    # Both endpoints should face the proposed bridge, and their tangent trends
    # should be broadly compatible. Looser for short/medium gaps so cartographic
    # isolines stay continuous; still reject clear reverse/cross links.
    min_facing = -0.35 if distance <= grid_step * 6.0 else -0.18
    if _dot(connector, first_tangent) < min_facing:
        return False
    if _dot((-connector[0], -connector[1]), second_tangent) < min_facing:
        return False
    opp_tol = -0.55 if distance <= grid_step * 6.0 else -0.35
    if _dot(first_tangent, (-second_tangent[0], -second_tangent[1])) < opp_tol:
        return False
    return True


def _bridge_endpoint_sides(mode: str) -> Tuple[bool, bool]:
    if mode == "end_start":
        return False, True
    if mode == "start_end":
        return True, False
    if mode == "start_start":
        return True, True
    return False, False


def _endpoint_outward_tangent(points: Sequence[PointTuple], at_start: bool) -> Optional[PointTuple]:
    if len(points) < 2:
        return None
    if at_start:
        raw = (points[0][0] - points[1][0], points[0][1] - points[1][1])
    else:
        raw = (points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
    return _unit_vector(raw)


def _unit_vector(vector: PointTuple) -> Optional[PointTuple]:
    length = math.hypot(float(vector[0]), float(vector[1]))
    if length <= 1e-12:
        return None
    return (float(vector[0]) / length, float(vector[1]) / length)


def _dot(a: PointTuple, b: PointTuple) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def _cell_intersects_barrier(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    barriers: Sequence[BarrierLine],
) -> bool:
    left, right = sorted((float(x0), float(x1)))
    bottom, top = sorted((float(y0), float(y1)))
    corners = ((left, bottom), (right, bottom), (right, top), (left, top))
    edges = tuple(zip(corners, corners[1:] + corners[:1]))

    for barrier in barriers:
        for p0, p1 in _segments(barrier.points):
            if _point_in_box(p0, left, bottom, right, top) or _point_in_box(p1, left, bottom, right, top):
                return True
            if any(strict_segments_intersect(p0, p1, edge_start, edge_end, 1e-9) for edge_start, edge_end in edges):
                return True
    return False


def _point_in_box(pt: PointTuple, left: float, bottom: float, right: float, top: float) -> bool:
    return left <= float(pt[0]) <= right and bottom <= float(pt[1]) <= top


def _upsample_contour_surface(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    region_labels: Optional[np.ndarray],
    factor: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Densify the final trend surface for smoother contour extraction."""
    from drawing.single_factor.fast_grid import upsample_bilinear_grid

    return upsample_bilinear_grid(grid, x_coords, y_coords, region_labels, factor)


def extract_closed_high_rings(
    grid_z: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    levels: Sequence[float],
    *,
    region_labels: Optional[np.ndarray] = None,
    min_cells: int = 8,
) -> Dict[float, List[List[PointTuple]]]:
    """Extract nested closed isolines around local peaks.

    For each level L, grow the connected component of ``z >= L`` that contains
    each local maximum (if the peak exceeds L). Component boundaries become
    **closed** rings. Lower L → larger rings around the same peak (bullseye).

    Open arcs that only graze the map rim are discarded — cartographic nested
    highs use closed rings only.
    """
    result: Dict[float, List[List[PointTuple]]] = {float(lv): [] for lv in levels}
    if grid_z.size == 0 or len(grid_x) < 2 or len(grid_y) < 2:
        return result

    try:
        from scipy.ndimage import binary_erosion, label as nd_label, maximum_filter
    except ImportError:
        return masked_marching_squares(grid_z, grid_x, grid_y, levels)

    finite = np.isfinite(np.asarray(grid_z, dtype=float))
    grid = np.asarray(grid_z, dtype=float)
    min_cells = max(3, int(min_cells))
    step = _estimate_grid_step(grid_x, grid_y)

    # Local maxima (peak seeds for nested rings).
    filled = np.where(finite, grid, -np.inf)
    footprint = max(3, min(7, int(round(min(grid.shape) * 0.04)) | 1))
    peaks = finite & (filled >= maximum_filter(filled, size=footprint) - 1e-12)
    # Keep only peaks that are strict local max vs neighborhood mean-ish
    peak_idx = list(zip(*np.where(peaks)))

    def _component_ring(comp: np.ndarray) -> Optional[List[PointTuple]]:
        if int(comp.sum()) < min_cells:
            return None
        field = np.full(grid.shape, np.nan, dtype=float)
        field[finite] = 0.0
        field[comp] = 1.0
        raw = masked_marching_squares(field, grid_x, grid_y, [0.5], barriers=(), region_labels=None)
        best: Optional[List[PointTuple]] = None
        best_len = 0.0
        for poly in raw.get(0.5, []):
            line = _dedupe_consecutive_points(poly, tolerance=max(step * 1e-6, 1e-9))
            if len(line) < 4:
                continue
            if not _is_closed_polyline(line, step):
                gap = _point_distance(line[0], line[-1])
                path = _polyline_length(line)
                if path < step * 6.0 or gap < 1e-12:
                    continue
                # Seal if ring-like; otherwise skip open scraps.
                if (path / gap) >= 2.5 and gap <= min(step * 20.0, path * 0.4):
                    line = line + [line[0]]
                else:
                    continue
            if not _is_closed_polyline(line, step):
                continue
            plen = _polyline_length(line)
            if plen >= step * 6.0 and plen > best_len:
                best = line
                best_len = plen
        return best

    def _rings_for_domain(domain_mask: np.ndarray) -> Dict[float, List[List[PointTuple]]]:
        local: Dict[float, List[List[PointTuple]]] = {float(lv): [] for lv in levels}
        domain = np.asarray(domain_mask, dtype=bool) & finite
        if not bool(domain.any()):
            return local
        # Shrink slightly so components avoid the outer NaN rim → more closed rings.
        core = binary_erosion(domain, iterations=1) if int(domain.sum()) > 20 else domain
        for raw_level in levels:
            level = float(raw_level)
            high = core & (grid >= level)
            if not bool(high.any()):
                continue
            labeled, count = nd_label(high)
            used: set[int] = set()
            # Prefer peak-seeded components (nested around true highs).
            domain_cells = max(int(domain.sum()), 1)
            for pr, pc in peak_idx:
                if not domain[pr, pc] or not high[pr, pc]:
                    continue
                cid = int(labeled[pr, pc])
                if cid <= 0 or cid in used:
                    continue
                comp = labeled == cid
                # Skip plateaus that fill most of a partition (step-function walls).
                if int(comp.sum()) > domain_cells * 0.50:
                    used.add(cid)
                    continue
                used.add(cid)
                ring = _component_ring(comp)
                if ring is not None:
                    local[level].append(ring)
            # Also keep sizable interior components without a peak seed.
            domain_cells = max(int(domain.sum()), 1)
            for cid in range(1, int(count) + 1):
                if cid in used:
                    continue
                comp = labeled == cid
                n_comp = int(comp.sum())
                if n_comp < min_cells:
                    continue
                # Skip partition-filling plateaus (false wall contours on step jumps).
                if n_comp > domain_cells * 0.50:
                    continue
                # Skip components glued to the outer domain edge (open map-rim arcs).
                edge = domain & ~binary_erosion(domain, iterations=1) if domain_cells > 20 else np.zeros_like(domain)
                if bool((comp & edge).any()) and n_comp > min_cells * 8:
                    continue
                ring = _component_ring(comp)
                if ring is not None:
                    local[level].append(ring)
                    used.add(cid)
        return local

    if region_labels is None:
        merged = _rings_for_domain(finite)
        for lv, rings in merged.items():
            result[float(lv)].extend(rings)
    else:
        labels = np.asarray(region_labels)
        for rid in np.unique(labels):
            if int(rid) < 0:
                continue
            merged = _rings_for_domain(finite & (labels == int(rid)))
            for lv, rings in merged.items():
                result[float(lv)].extend(rings)
    return result


def masked_marching_squares(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    levels: Sequence[float],
    barriers: Sequence[BarrierLine] = (),
    region_labels: Optional[np.ndarray] = None,
) -> Dict[float, List[List[PointTuple]]]:
    """按区域提取等值线：跨区域的网格块直接跳过，等值线止于打断线处。

    性能：若 barriers 非空，先一次性栅格化打断线邻近格（粗掩膜），
    禁止对每个单元反复做几何相交（曾导致 800²×级数 卡死数十分钟）。
    推荐调用方在网格上先 nan 缓冲带，并将 barriers 置空。
    """
    result: Dict[float, List[List[PointTuple]]] = {}
    if grid.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return {float(level): [] for level in levels}

    # 预计算打断格掩膜（仅当确实传入 barriers 时）
    barrier_cell_block: Optional[np.ndarray] = None
    if barriers:
        rows_m, cols_m = int(grid.shape[0]), int(grid.shape[1])
        barrier_cell_block = np.zeros((rows_m, cols_m), dtype=bool)
        x0g = float(x_coords[0])
        y0g = float(y_coords[0])
        dxg = float(x_coords[1] - x_coords[0]) if cols_m > 1 else 1.0
        dyg = float(y_coords[1] - y_coords[0]) if rows_m > 1 else 1.0
        cell = max(min(abs(dxg), abs(dyg)), 1e-9)
        # 约 1 个网格宽的“墙”，阻止 MS 跨打断线连段
        pad = 1
        for barrier in barriers:
            pts = list(getattr(barrier, "points", ()) or ())
            if len(pts) < 2:
                continue
            for p0, p1 in _segments(pts):
                length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                n = max(2, int(length / cell) + 2)
                for i in range(n):
                    t = i / (n - 1)
                    px = p0[0] + t * (p1[0] - p0[0])
                    py = p0[1] + t * (p1[1] - p0[1])
                    cc = int(round((px - x0g) / dxg)) if abs(dxg) > 1e-30 else 0
                    rr = int(round((py - y0g) / dyg)) if abs(dyg) > 1e-30 else 0
                    for dr in range(-pad, pad + 1):
                        for dc in range(-pad, pad + 1):
                            r2, c2 = rr + dr, cc + dc
                            if 0 <= r2 < rows_m and 0 <= c2 < cols_m:
                                barrier_cell_block[r2, c2] = True

    for raw_level in levels:
        level = float(raw_level)
        segments: List[Tuple[PointTuple, PointTuple]] = []
        for row in range(grid.shape[0] - 1):
            y0, y1 = float(y_coords[row]), float(y_coords[row + 1])
            for col in range(grid.shape[1] - 1):
                x0, x1 = float(x_coords[col]), float(x_coords[col + 1])
                if region_labels is not None:
                    label = region_labels[row, col]
                    if not (
                        region_labels[row, col + 1] == label
                        and region_labels[row + 1, col] == label
                        and region_labels[row + 1, col + 1] == label
                    ):
                        continue
                if barrier_cell_block is not None:
                    # 任一角/中心落在打断墙 → 跳过该单元（O(1)）
                    if (
                        barrier_cell_block[row, col]
                        or barrier_cell_block[row, col + 1]
                        or barrier_cell_block[row + 1, col]
                        or barrier_cell_block[row + 1, col + 1]
                    ):
                        continue
                v00 = float(grid[row, col])
                v10 = float(grid[row, col + 1])
                v11 = float(grid[row + 1, col + 1])
                v01 = float(grid[row + 1, col])
                values = (v00, v10, v11, v01)
                if not all(math.isfinite(v) for v in values):
                    continue

                corners = (
                    ((x0, y0), v00),
                    ((x1, y0), v10),
                    ((x1, y1), v11),
                    ((x0, y1), v01),
                )
                edge_points: List[Tuple[int, PointTuple]] = []
                for edge_index, (i, j) in enumerate(((0, 1), (1, 2), (2, 3), (3, 0))):
                    pa, va = corners[i]
                    pb, vb = corners[j]
                    crossed = (va < level <= vb) or (vb < level <= va)
                    if not crossed or math.isclose(va, vb):
                        continue
                    t = (level - va) / (vb - va)
                    edge_points.append((edge_index, (pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1]))))
                if len(edge_points) == 2:
                    segments.append((edge_points[0][1], edge_points[1][1]))
                elif len(edge_points) == 4:
                    segments.extend(_ambiguous_marching_segments(edge_points, values, level))
        result[level] = connect_segments(segments)
    return result


def _ambiguous_marching_segments(
    edge_points: Sequence[Tuple[int, PointTuple]],
    values: Sequence[float],
    level: float,
) -> List[Tuple[PointTuple, PointTuple]]:
    """Resolve 4-edge marching-squares cells with a center-value decider."""
    point_by_edge = {int(edge): point for edge, point in edge_points}
    if any(edge not in point_by_edge for edge in (0, 1, 2, 3)) or len(values) != 4:
        ordered = [point for _, point in edge_points]
        return [(ordered[0], ordered[1]), (ordered[2], ordered[3])]

    v00, v10, v11, v01 = (float(value) for value in values)
    high = (v00 >= level, v10 >= level, v11 >= level, v01 >= level)
    center_high = ((v00 + v10 + v11 + v01) * 0.25) >= level

    if high[0] and high[2] and not high[1] and not high[3]:
        pairs = ((0, 1), (2, 3)) if center_high else ((0, 3), (1, 2))
    elif high[1] and high[3] and not high[0] and not high[2]:
        pairs = ((0, 3), (1, 2)) if center_high else ((0, 1), (2, 3))
    else:
        pairs = ((0, 1), (2, 3))

    return [(point_by_edge[a], point_by_edge[b]) for a, b in pairs]


def connect_segments(segments: Sequence[Tuple[PointTuple, PointTuple]]) -> List[List[PointTuple]]:
    if not segments:
        return []

    coords: Dict[Tuple[int, int], PointTuple] = {}
    adjacency: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    scale = 1_000_000.0

    def key(pt: PointTuple) -> Tuple[int, int]:
        return (int(round(pt[0] * scale)), int(round(pt[1] * scale)))

    for a, b in segments:
        ka, kb = key(a), key(b)
        if ka == kb:
            continue
        coords.setdefault(ka, a)
        coords.setdefault(kb, b)
        adjacency.setdefault(ka, []).append(kb)
        adjacency.setdefault(kb, []).append(ka)

    unused = {tuple(sorted((ka, kb))) for ka, links in adjacency.items() for kb in links}
    polylines: List[List[PointTuple]] = []
    start_keys = [node for node, links in adjacency.items() if len(links) == 1]
    start_keys.extend(node for node in adjacency if node not in start_keys)

    for start in start_keys:
        while True:
            next_nodes = [n for n in adjacency.get(start, []) if tuple(sorted((start, n))) in unused]
            if not next_nodes:
                break
            chain = [start]
            prev = None
            cur = start
            while True:
                candidates = [
                    n for n in adjacency.get(cur, [])
                    if n != prev and tuple(sorted((cur, n))) in unused
                ]
                if not candidates:
                    if prev is None:
                        candidates = [n for n in adjacency.get(cur, []) if tuple(sorted((cur, n))) in unused]
                    if not candidates:
                        break
                nxt = candidates[0]
                unused.discard(tuple(sorted((cur, nxt))))
                chain.append(nxt)
                prev, cur = cur, nxt
                if cur == start:
                    break
            if len(chain) >= 2:
                polylines.append([coords[k] for k in chain])
    return polylines


def _segments(points: Sequence[PointTuple]) -> Iterable[Tuple[PointTuple, PointTuple]]:
    for i in range(len(points) - 1):
        yield points[i], points[i + 1]


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


# ----------------------------- 方向线对齐等值线走向的辅助函数 -----------------------------
# 目标：让提取出的等值线“走向和方向线趋同”，参考专业图的效果（长轴沿方向线拉伸、少小圈）。
# 轻量实现：在 postprocess 阶段对 polyline 做小步切向偏置，力度可控（不会大幅改变 level 值）。

def _query_local_direction(
    x: float, y: float, directions: Sequence[DirectionLine], search_radius: float = 8000.0
) -> Optional[Tuple[float, float]]:
    """返回距离点 (x,y) 最近的方向线段的单位切向向量 (dx, dy)。"""
    if not directions:
        return None
    best_d = None
    min_d2 = float("inf")
    r2 = float(search_radius) * float(search_radius)
    for dline in directions:
        if not getattr(dline, "active", True) or len(getattr(dline, "points", ())) < 2:
            continue
        pts = dline.points
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            vx, vy = bx - ax, by - ay
            len2 = vx * vx + vy * vy
            if len2 < 1e-12:
                continue
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / len2))
            cx = ax + t * vx
            cy = ay + t * vy
            dx_, dy_ = x - cx, y - cy
            dd = dx_ * dx_ + dy_ * dy_
            if dd < min_d2 and dd <= r2:
                min_d2 = dd
                l = math.sqrt(max(len2, 1e-12))
                best_d = (vx / l, vy / l)
    return best_d


def _direction_align_polyline(
    points: List[PointTuple], directions: Sequence[DirectionLine], grid_step: float, strength: float = 0.28
) -> List[PointTuple]:
    """轻量方向对齐：把 polyline 的局部切向向最近方向线偏置，使整体走向更趋同。
    仅对内部点做很小的位置微调（沿混合切向的投影分量），对 level set 影响很小。
    """
    if len(points) < 3 or not directions or strength <= 0:
        return points
    new_pts: List[PointTuple] = list(points)
    s = max(0.0, min(0.55, float(strength)))
    search_r = max(grid_step * 5.0, 1500.0)
    for _it in range(1):  # 单次迭代，轻量
        for i in range(1, len(new_pts) - 1):
            px, py = new_pts[i]
            d = _query_local_direction(px, py, directions, search_r)
            if d is None:
                continue
            dx, dy = d
            # 前后邻平均切向
            tx = new_pts[i + 1][0] - new_pts[i - 1][0]
            ty = new_pts[i + 1][1] - new_pts[i - 1][1]
            tlen = math.hypot(tx, ty)
            if tlen < 1e-9:
                continue
            tx /= tlen
            ty /= tlen
            # 混合
            bx = (1.0 - s) * tx + s * dx
            by = (1.0 - s) * ty + s * dy
            bl = math.hypot(bx, by)
            if bl < 1e-9:
                continue
            bx /= bl
            by /= bl
            # 向混合方向小步移动（用中点在该方向的投影）
            pm = np.array(new_pts[i - 1], dtype=float)
            pp = np.array(new_pts[i + 1], dtype=float)
            p = np.array(new_pts[i], dtype=float)
            mid = (pm + pp) * 0.5
            delta = mid - p
            along = float(np.dot(delta, [bx, by]))
            move = along * np.array([bx, by]) * 0.32 * s
            np_ = p + move
            new_pts[i] = (float(np_[0]), float(np_[1]))
    return new_pts
