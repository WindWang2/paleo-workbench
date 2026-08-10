"""Vectorized grid helpers for single-factor interpolation performance.

Uses NumPy (+ optional multi-thread row blocks / CuPy CUDA when enabled).
PyInstaller stays lean: CUDA is optional at runtime.
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Sequence, Tuple

import numpy as np


def resolve_performance_grid_resolution(
    map_width: float,
    map_height: float,
    requested: int,
    *,
    max_cells: int = 0,
    min_resolution: int = 40,
    max_resolution: int = 2000,
) -> int:
    """Cap grid resolution so interpolation stays within a cell budget.

    Budget scales with the CPU/GPU performance sliders so weak machines stay
    responsive while stronger machines can use finer grids.
    """
    requested = max(min_resolution, min(max_resolution, int(requested)))
    if max_cells <= 0:
        try:
            from drawing.compute.performance import get_compute_settings

            s = get_compute_settings()
            # Base 120k cells @ 0% CPU → up to ~900k @ 100% CPU; GPU adds extra
            base = 120_000
            cpu_boost = 1.0 + 6.5 * (s.cpu_percent / 100.0)
            gpu_boost = 1.0 + 2.0 * s.gpu_fraction()
            max_cells = int(base * cpu_boost * gpu_boost)
        except Exception:
            max_cells = 200_000
    extent = max(float(map_width), float(map_height), 1.0)
    if extent <= 0.0:
        return requested
    # Keep aspect roughly square in cell count.
    ratio = max(map_width, map_height) / max(min(map_width, map_height), 1e-9)
    if ratio >= 1.5:
        # Roughly: rows * cols <= max_cells with rows/cols ~ map aspect
        major = int(math.sqrt(max_cells * ratio))
        minor = max(1, int(max_cells / max(major, 1)))
        cap = max(major, minor)
    else:
        cap = int(math.sqrt(max_cells))
    return max(min_resolution, min(requested, cap))


def resolve_adaptive_gap_fill_iterations(
    well_count: int,
    valid_domain_cells: int,
    requested: int,
) -> int:
    """Fewer BFS iterations when data are sparse to avoid slow diffusion passes."""
    requested = max(0, int(requested))
    if requested <= 0:
        return 0
    if well_count <= 4 or valid_domain_cells < 2500:
        return min(requested, 3)
    if well_count <= 8 or valid_domain_cells < 8000:
        return min(requested, 4)
    return requested


def resolve_adaptive_contour_upsample(grid_resolution: int, requested: int) -> int:
    """Keep denser contour sampling on large grids for smoother isolines.

    Dense trend grids still benefit from mild upsample so marching-squares
    stairs collapse under Chaikin; only cap extreme cases for speed.
    """
    requested = max(1, min(5, int(requested)))
    if grid_resolution >= 320:
        return min(requested, 3)
    if grid_resolution >= 240:
        return min(requested, 4)
    return requested


def rasterize_polygon_mask(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    ring: Sequence[Tuple[float, float]],
) -> np.ndarray:
    """Vectorized ray-cast point-in-polygon for one closed ring."""
    if len(ring) < 3 or len(grid_x) == 0 or len(grid_y) == 0:
        return np.zeros((len(grid_y), len(grid_x)), dtype=bool)

    xs = np.asarray([float(p[0]) for p in ring], dtype=float)
    ys = np.asarray([float(p[1]) for p in ring], dtype=float)
    gx, gy = np.meshgrid(np.asarray(grid_x, dtype=float), np.asarray(grid_y, dtype=float))
    px = gx.ravel()
    py = gy.ravel()
    inside = np.zeros(px.shape[0], dtype=bool)
    count = len(xs)
    j = count - 1
    for i in range(count):
        xi, yi = xs[i], ys[i]
        xj, yj = xs[j], ys[j]
        denom = yj - yi
        cond = (yi > py) != (yj > py)
        if np.any(cond):
            x_intersect = (xj - xi) * (py - yi) / np.where(np.abs(denom) > 1e-30, denom, 1e-30) + xi
            inside ^= cond & (px < x_intersect)
        j = i
    return inside.reshape(gx.shape)


def _direction_perpendicular_scale(ratio: float, strength: float) -> float:
    return 1.0 + max(float(ratio) - 1.0, 0.0) * max(float(strength), 0.0)


def build_boundary_union_mask(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    boundaries: Sequence[object],
) -> np.ndarray:
    """Union of boundary polygons (exterior minus holes)."""
    rows = len(grid_y)
    cols = len(grid_x)
    if not boundaries:
        return np.zeros((rows, cols), dtype=bool)
    mask = np.zeros((rows, cols), dtype=bool)
    for boundary in boundaries:
        if len(boundary.exterior) < 3:
            continue
        poly = rasterize_polygon_mask(grid_x, grid_y, boundary.exterior)
        for hole in boundary.holes:
            if len(hole) >= 3:
                poly &= ~rasterize_polygon_mask(grid_x, grid_y, hole)
        mask |= poly
    return mask


def build_domain_mask_fast(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    boundaries: Sequence[object],
    *,
    blank_mask: Optional[np.ndarray] = None,
    interpolation_area_masks: Optional[Sequence[np.ndarray]] = None,
    well_coverage_mask: Optional[np.ndarray] = None,
    data_hull_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Assemble the interpolation domain mask with rasterized polygon ops."""
    domain = build_boundary_union_mask(grid_x, grid_y, boundaries)
    if blank_mask is not None:
        domain &= ~np.asarray(blank_mask, dtype=bool)
    if interpolation_area_masks:
        area_union = np.zeros_like(domain, dtype=bool)
        for area_mask in interpolation_area_masks:
            area_union |= np.asarray(area_mask, dtype=bool)
        domain &= area_union
    if well_coverage_mask is not None:
        domain &= np.asarray(well_coverage_mask, dtype=bool)
    if data_hull_mask is not None:
        domain &= np.asarray(data_hull_mask, dtype=bool)
    return domain


def _idw_row_block(
    r0: int,
    r1: int,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    wx: np.ndarray,
    wy: np.ndarray,
    wz: np.ndarray,
    domain_mask: np.ndarray,
    *,
    search_radius: float,
    power: float,
    min_points: int,
    max_points: int,
    density_weights: np.ndarray,
    region_labels: Optional[np.ndarray],
    well_labels: Optional[np.ndarray],
    direction_field: Optional[np.ndarray],
    direction_corridor_strength: float,
    direction_perpendicular_strength: float,
    use_extended_search: bool,
    limit_search_radius: bool,
    xp=np,
    use_f32: bool = False,
) -> Tuple[int, int, np.ndarray, np.ndarray]:
    """IDW for rows [r0, r1). Returns (r0, r1, values, exact_mask) as numpy."""
    rows_b = r1 - r0
    cols = len(grid_x)
    n_wells = len(wx)
    is_cupy = xp is not np
    dtype = xp.float32 if use_f32 else xp.float64

    gx = xp.asarray(grid_x, dtype=dtype)
    gy = xp.asarray(grid_y[r0:r1], dtype=dtype)
    wx_a = xp.asarray(wx, dtype=dtype)
    wy_a = xp.asarray(wy, dtype=dtype)
    wz_a = xp.asarray(wz, dtype=dtype)

    # (rows_b, cols, n_wells)
    rel_x = gx[None, :, None] - wx_a[None, None, :]
    rel_y = gy[:, None, None] - wy_a[None, None, :]
    euclidean = xp.hypot(rel_x, rel_y)

    nan_v = xp.asarray(float("nan"), dtype=dtype)
    inf_v = xp.asarray(float("inf"), dtype=dtype)
    result = xp.full((rows_b, cols), nan_v, dtype=dtype)
    exact = euclidean <= 1e-9
    exact_any = xp.any(exact, axis=2)
    if bool(xp.any(exact_any)):
        exact_idx = xp.argmax(exact.astype(xp.int8), axis=2)
        result[exact_any] = wz_a[exact_idx[exact_any]]

    dist = euclidean
    if direction_field is not None and direction_field.shape[0] >= r1:
        dfield = xp.asarray(direction_field[r0:r1], dtype=dtype)
        unit_x = dfield[:, :, 0][:, :, None]
        unit_y = dfield[:, :, 1][:, :, None]
        ratio = xp.maximum(dfield[:, :, 2][:, :, None], 1.0)
        # 逐格垂向惩罚：与本地 stretch 成正比，椭圆更贴方向线
        strength = max(float(direction_perpendicular_strength), 0.0)
        perp_scale = 1.0 + xp.maximum(ratio - 1.0, 0.0) * strength
        u = rel_x * unit_x + rel_y * unit_y
        v = rel_x * (-unit_y) + rel_y * unit_x
        aniso = xp.sqrt((u / ratio) ** 2 + (v * perp_scale) ** 2)
        stretched = ratio > (1.0 + 1e-9)
        dist = xp.where(stretched, aniso, euclidean)

    filter_dist = dist if use_extended_search else euclidean
    radius = max(float(search_radius), 1e-9)
    radius_scales = (1.0,) if limit_search_radius else (1.0, 1.5, 2.25, 3.0)

    if density_weights is not None and getattr(density_weights, "size", 0):
        decluster = xp.asarray(density_weights, dtype=dtype).reshape(1, 1, n_wells)
    else:
        decluster = xp.ones((1, 1, n_wells), dtype=dtype)

    corridor_strength = float(direction_corridor_strength)
    direction_weights = xp.ones_like(dist, dtype=dtype)
    if direction_field is not None and corridor_strength > 0.0:
        dfield = xp.asarray(direction_field[r0:r1], dtype=dtype)
        unit_x = dfield[:, :, 0][:, :, None]
        unit_y = dfield[:, :, 1][:, :, None]
        ratio_plane = xp.maximum(dfield[:, :, 2], 1.0)[:, :, None]
        cross = xp.abs(rel_x * (-unit_y) + rel_y * unit_x)
        corridor_width = xp.maximum(radius / xp.maximum(ratio_plane, 1.0), 1e-9)
        stretch = xp.maximum(ratio_plane - 1.0, 0.0)
        taper = 1.0 / (1.0 + (cross / corridor_width) ** 2)
        direction_weights = 1.0 + stretch * corridor_strength * taper
        direction_weights = xp.where(
            (stretch <= 0.0) | (corridor_strength <= 0.0),
            1.0,
            direction_weights,
        )

    dm = xp.asarray(domain_mask[r0:r1], dtype=bool)
    pending = dm & ~exact_any
    min_pts = max(1, int(min_points))
    max_pts = max(1, int(max_points))
    wz_tile = xp.broadcast_to(wz_a, (rows_b, cols, n_wells))
    decl_tile = xp.broadcast_to(decluster.reshape(1, 1, n_wells), (rows_b, cols, n_wells))

    rl = None
    wl = None
    if region_labels is not None and well_labels is not None:
        rl = xp.asarray(region_labels[r0:r1], dtype=xp.int32)
        wl = xp.asarray(well_labels, dtype=xp.int32)

    for pass_index, scale in enumerate(radius_scales):
        if not bool(xp.any(pending)):
            break
        in_radius = filter_dist <= radius * scale
        work = xp.where(in_radius, dist, inf_v)

        if rl is not None and wl is not None:
            cell_lbl = rl[:, :, None]
            well_lbl = wl[None, None, :]
            region_ok = (well_lbl < 0) | (cell_lbl < 0) | (cell_lbl == well_lbl)
            work = xp.where(region_ok, work, inf_v)

        try:
            order = xp.argsort(work, axis=2, kind="stable")
        except TypeError:
            order = xp.argsort(work, axis=2)
        sorted_dist = xp.take_along_axis(work, order, axis=2)
        sorted_z = xp.take_along_axis(wz_tile, order, axis=2)
        sorted_decl = xp.take_along_axis(decl_tile, order, axis=2)
        sorted_dir_w = xp.take_along_axis(direction_weights, order, axis=2)

        k = min(max_pts, n_wells)
        d_k = sorted_dist[:, :, :k]
        z_k = sorted_z[:, :, :k]
        decl_k = sorted_decl[:, :, :k]
        dir_k = sorted_dir_w[:, :, :k]

        valid = xp.isfinite(d_k)
        count = valid.sum(axis=2)
        need = max(1, min_pts - pass_index)
        eligible = pending & (count >= need)

        d_safe = xp.where(valid, d_k, nan_v)
        w = decl_k * dir_k / xp.power(xp.maximum(d_safe, 1e-9), float(power))
        w = xp.where(valid, w, 0.0)
        wsum = w.sum(axis=2)
        vals = xp.sum(w * z_k, axis=2) / xp.maximum(wsum, 1e-12)
        update = eligible & (wsum > 0.0)
        result[update] = vals[update]
        pending = pending & ~update

    if is_cupy:
        result = xp.asnumpy(result)
        exact_any = xp.asnumpy(exact_any)
    return r0, r1, np.asarray(result, dtype=float), np.asarray(exact_any, dtype=bool)


def interpolate_idw_grid_batch(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    well_array: np.ndarray,
    domain_mask: np.ndarray,
    *,
    search_radius: float,
    power: float,
    min_points: int,
    max_points: int,
    density_weights: np.ndarray,
    value_min: Optional[float] = None,
    value_max: Optional[float] = None,
    region_labels: Optional[np.ndarray] = None,
    well_labels: Optional[np.ndarray] = None,
    direction_field: Optional[np.ndarray] = None,
    direction_corridor_strength: float = 0.85,
    direction_perpendicular_strength: float = 0.25,
    use_extended_search: bool = True,
    limit_search_radius: bool = True,
) -> np.ndarray:
    """Batch constrained IDW on a regular grid (chunked + multi-thread / optional CUDA).

    Avoids allocating a full (rows, cols, n_wells) tensor for the entire map —
    that used to freeze the UI on fine grids. Rows are processed in blocks;
    CPU workers come from the performance slider; CUDA (CuPy) is used when
    the GPU slider is >0 and a device is available.
    """
    rows, cols = domain_mask.shape
    result = np.full((rows, cols), np.nan, dtype=float)
    if well_array.size == 0 or not bool(domain_mask.any()):
        return result

    wx = np.asarray(well_array[:, 0], dtype=float)
    wy = np.asarray(well_array[:, 1], dtype=float)
    wz = np.asarray(well_array[:, 2], dtype=float)
    n_wells = len(wx)
    grid_x = np.asarray(grid_x, dtype=float)
    grid_y = np.asarray(grid_y, dtype=float)

    try:
        from drawing.compute.performance import get_compute_settings

        settings = get_compute_settings()
        workers = settings.cpu_workers()
        block = settings.idw_row_block(cols, n_wells)
        use_gpu = settings.use_gpu()  # CuPy device path when switch+strength+device
        use_f32 = settings.use_float32()  # GPU path prefers float32
        xp = settings.cupy() if use_gpu else np
        if xp is None:
            xp = np
            use_gpu = False
    except Exception:
        workers = 1
        block = max(1, min(64, rows))
        use_gpu = False
        use_f32 = False
        xp = np

    # 多线程时必须压低 BLAS/OpenMP 内层线程，否则 20 个 worker × MKL 内线
    # 程会严重超订，资源管理器里“看起来没用满核”、实际更慢。
    def _pin_blas_threads(n: int) -> None:
        n = max(1, int(n))
        for key in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            os.environ[key] = str(n)
        try:
            import threadpoolctl

            threadpoolctl.threadpool_limits(limits=n)
        except Exception:
            pass
        try:
            import numpy as _np

            # some builds expose this
            if hasattr(_np, "__config__"):
                pass
        except Exception:
            pass

    # CPU 多线程：块要足够多，否则 ranges 很少，线程池几乎空转
    if not use_gpu and workers > 1:
        # 目标：至少 2×workers 个任务，且单块不要过大占满内存
        min_tasks = max(workers * 2, 8)
        max_block = max(1, int(math.ceil(rows / min_tasks)))
        block = max(1, min(block, max_block, 24))
    elif use_gpu:
        # GPU：尽量大块，减少 host↔device 往返与 kernel 启动开销
        # 粗估显存：block*cols*n_wells*4*8 ≈ 中间张量；留 1.5GB 余量
        bytes_per_row = max(1, cols * n_wells * 4 * 10)
        max_rows = max(32, min(rows, int(1_500_000_000 / bytes_per_row)))
        block = max(block, max_rows)

    # GPU path: large row blocks on device
    # CPU multi-thread: several small row blocks in parallel
    ranges = [(r0, min(rows, r0 + block)) for r0 in range(0, rows, block)]

    common = dict(
        grid_x=grid_x,
        grid_y=grid_y,
        wx=wx,
        wy=wy,
        wz=wz,
        domain_mask=domain_mask,
        search_radius=search_radius,
        power=power,
        min_points=min_points,
        max_points=max_points,
        density_weights=density_weights,
        region_labels=region_labels,
        well_labels=well_labels,
        direction_field=direction_field,
        direction_corridor_strength=direction_corridor_strength,
        direction_perpendicular_strength=direction_perpendicular_strength,
        use_extended_search=use_extended_search,
        limit_search_radius=limit_search_radius,
        xp=xp if use_gpu else np,
        use_f32=use_f32,
    )

    def _run_one(rr):
        r0, r1 = rr
        return _idw_row_block(r0, r1, **common)

    def _run_all_cpu():
        common_cpu = dict(common)
        common_cpu["xp"] = np
        # 单线程路径可让 BLAS 用多核；多线程路径每 worker 内 BLAS=1
        if workers <= 1 or len(ranges) <= 1:
            _pin_blas_threads(max(1, workers if workers > 1 else (os.cpu_count() or 4)))
            for rr in ranges:
                r0, r1, block_vals, _ = _idw_row_block(r0=rr[0], r1=rr[1], **common_cpu)
                result[r0:r1] = block_vals
            return

        _pin_blas_threads(1)

        def _run_cpu(rr):
            r0, r1 = rr
            return _idw_row_block(r0, r1, **common_cpu)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_cpu, rr) for rr in ranges]
            for fut in as_completed(futures):
                r0, r1, block_vals, _ = fut.result()
                result[r0:r1] = block_vals

    if use_gpu:
        try:
            # GPU：内层 BLAS 不重要；整块上设备
            _pin_blas_threads(1)
            # 首次运行会 JIT 编译若干 kernel（可能数秒）；缓存后明显加速
            for rr in ranges:
                r0, r1, block_vals, _ = _run_one(rr)
                result[r0:r1] = block_vals
        except Exception:
            # device OOM / unsupported ops → fall back to multi-core CPU
            _run_all_cpu()
    else:
        _run_all_cpu()

    if value_min is not None:
        result = np.where(np.isfinite(result), np.maximum(float(value_min), result), result)
    if value_max is not None:
        result = np.where(np.isfinite(result), np.minimum(float(value_max), result), result)
    result[~domain_mask] = np.nan
    return result


def apply_min_decay_to_empty_areas(
    grid: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    wells: Sequence,
    max_influence_radius: float,
    min_value: float,
) -> np.ndarray:
    """在远离井点的区域将值衰减到最小值；井点邻域必须保留插值结果。

    低/中/高井值都应按全图 min~max 映射出可见颜色，不能被空区衰减抹成同一片底色。
    """
    if grid.size == 0 or len(wells) == 0 or max_influence_radius <= 0:
        return grid
    result = np.array(grid, dtype=float, copy=True)
    well_xy = np.array([[float(w.x), float(w.y)] for w in wells], dtype=float)
    gx, gy = np.meshgrid(np.asarray(grid_x, dtype=float), np.asarray(grid_y, dtype=float))

    # 最近井距离
    min_d = np.full(gx.shape, np.inf, dtype=float)
    for wx, wy in well_xy:
        d = np.hypot(gx - wx, gy - wy)
        min_d = np.minimum(min_d, d)

    # 软点密度（高斯核）
    density_r = max_influence_radius * 0.5
    density = np.zeros_like(gx, dtype=float)
    for wx, wy in well_xy:
        d = np.hypot(gx - wx, gy - wy)
        density += np.exp(-(d / density_r) ** 2)

    density_norm = np.clip(density / max(1e-9, np.max(density)), 0.0, 1.0)

    # 软距离衰减
    scale = max_influence_radius * 0.8
    dist_influence = np.exp(-min_d / scale)
    influence = dist_influence * density_norm

    # ★ 井点保护：邻域内 influence→1，禁止把 56 这类低值井抹成与空区同色
    # 保护半径约影响半径的 18%，且至少覆盖数个网格
    xs = np.asarray(grid_x, dtype=float)
    ys = np.asarray(grid_y, dtype=float)
    step = 1.0
    if len(xs) >= 2:
        step = max(abs(float(xs[1] - xs[0])), step)
    if len(ys) >= 2:
        step = max(abs(float(ys[1] - ys[0])), step)
    protect_r = max(float(max_influence_radius) * 0.18, step * 6.0)
    protect = np.exp(-((min_d / max(protect_r, 1e-9)) ** 2))
    # 近井：至少保留 0.92~1.0 的原值权重
    influence = np.maximum(influence, 0.92 * protect + 0.08 * influence)
    influence = np.clip(influence, 0.0, 1.0)

    finite = np.isfinite(result)
    result[finite] = result[finite] * influence[finite] + float(min_value) * (
        1.0 - influence[finite]
    )
    return result


def dilate_mask(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Expand a boolean mask by ``radius`` grid cells (8-neighbor dilation)."""
    source = np.asarray(mask, dtype=bool)
    if source.size == 0 or radius <= 0:
        return source
    rows, cols = source.shape
    result = source.copy()
    offsets = (
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    )
    for _ in range(int(radius)):
        grown = result.copy()
        active = np.argwhere(result)
        for row, col in active:
            for dr, dc in offsets:
                nr = int(row) + dr
                nc = int(col) + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    grown[nr, nc] = True
        result = grown
    return result


def upsample_mask_nearest(mask: np.ndarray, factor: int) -> np.ndarray:
    """Nearest-neighbor upsample for invalid/stop masks used before contouring."""
    source = np.asarray(mask, dtype=bool)
    factor = max(1, int(factor))
    if factor <= 1 or source.size == 0:
        return source
    rows, cols = source.shape
    new_rows = (rows - 1) * factor + 1
    new_cols = (cols - 1) * factor + 1
    rr = np.arange(new_rows, dtype=int)
    cc = np.arange(new_cols, dtype=int)
    src_r = np.minimum(rows - 1, np.rint(rr / float(factor)).astype(int))
    src_c = np.minimum(cols - 1, np.rint(cc / float(factor)).astype(int))
    return source[src_r[:, None], src_c[None, :]]


def upsample_bilinear_grid(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    region_labels: Optional[np.ndarray],
    factor: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Bilinear upsample with the same finite/region guards as the legacy loop."""
    factor = max(1, min(4, int(factor)))
    if factor <= 1 or grid.size == 0 or len(x_coords) < 2 or len(y_coords) < 2:
        return grid, x_coords, y_coords, region_labels

    rows, cols = grid.shape
    new_rows = (rows - 1) * factor + 1
    new_cols = (cols - 1) * factor + 1
    new_grid = np.full((new_rows, new_cols), np.nan, dtype=float)
    new_labels = np.full((new_rows, new_cols), -1, dtype=int) if region_labels is not None else None
    new_x = np.linspace(float(x_coords[0]), float(x_coords[-1]), new_cols)
    new_y = np.linspace(float(y_coords[0]), float(y_coords[-1]), new_rows)

    rr, cc = np.meshgrid(np.arange(new_rows), np.arange(new_cols), indexing="ij")
    src_r = rr / float(factor)
    src_c = cc / float(factor)
    r0 = np.minimum(np.floor(src_r).astype(int), rows - 2)
    c0 = np.minimum(np.floor(src_c).astype(int), cols - 2)
    r0 = np.where(rr == new_rows - 1, rows - 2, r0)
    c0 = np.where(cc == new_cols - 1, cols - 2, c0)
    fy = src_r - r0
    fx = src_c - c0
    fy = np.where(rr == new_rows - 1, 1.0, fy)
    fx = np.where(cc == new_cols - 1, 1.0, fx)

    v00 = grid[r0, c0]
    v10 = grid[r0, c0 + 1]
    v01 = grid[r0 + 1, c0]
    v11 = grid[r0 + 1, c0 + 1]
    finite = np.isfinite(v00) & np.isfinite(v10) & np.isfinite(v01) & np.isfinite(v11)

    if region_labels is not None:
        l00 = region_labels[r0, c0]
        l10 = region_labels[r0, c0 + 1]
        l01 = region_labels[r0 + 1, c0]
        l11 = region_labels[r0 + 1, c0 + 1]
        same = (l00 >= 0) & (l00 == l10) & (l00 == l01) & (l00 == l11)
        finite &= same
        label_val = np.where(finite, l00, -1)
    else:
        label_val = None

    top = v00 * (1.0 - fx) + v10 * fx
    bottom = v01 * (1.0 - fx) + v11 * fx
    new_grid = top * (1.0 - fy) + bottom * fy
    new_grid = np.where(finite, new_grid, np.nan)
    if new_labels is not None and label_val is not None:
        new_labels = np.where(finite, label_val, -1)

    return new_grid, new_x, new_y, new_labels