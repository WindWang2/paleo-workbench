"""Constrained-IDW engine: vectorized postprocessing / LOS parity tests.

Issue #383: the constrained-IDW engine path paid per-(cell, well, segment)
Python loops for the LOS barrier filter, the barrier blank buffer, and the
smoothing / boundary-refine / well-anchoring postprocessing.  These tests
verify that the vectorized replacements are bit-for-bit identical to the
reference scalar implementations (same float operations, same order).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

_ensure_haiyou_engine()
import drawing.single_factor.constrained_engine as ce  # noqa: E402
from drawing.single_factor.constrained_engine import (  # noqa: E402
    BarrierLine,
    ConstraintWell,
    ConstrainedIDWConfig,
)


def _wavy_breaks(n_polys: int = 2, n_verts: int = 12) -> list[list[tuple[float, float]]]:
    lines = []
    for p in range(n_polys):
        pts = []
        for i in range(n_verts):
            t = i / (n_verts - 1)
            x = 5.0 + t * 90.0
            y = 40.0 + (p * 15.0) + 8.0 * np.sin(t * 6.0 + p)
            pts.append((float(x), float(y)))
        lines.append(pts)
    return lines


def _barriers_from(lines) -> list[BarrierLine]:
    return [
        BarrierLine(line_id=f"b{i}", points=tuple(pts), active=True)
        for i, pts in enumerate(lines)
    ]


# --------------------------------------------------------------------------- #
# Vectorized LOS barrier mask vs the reference per-pair loop
# --------------------------------------------------------------------------- #


def test_barrier_blocked_mask_matches_reference_loop():
    rng = np.random.default_rng(3)
    n_wells = 40
    xs = rng.uniform(0.0, 100.0, n_wells)
    ys = rng.uniform(0.0, 100.0, n_wells)
    barriers = _barriers_from(_wavy_breaks())
    segments = ce._barrier_segments(barriers)

    gx = np.linspace(-5.0, 105.0, 16)
    gy = np.linspace(-5.0, 105.0, 16)
    cell_x = np.tile(gx, 16)
    cell_y = np.repeat(gy, 16)

    got = ce._barrier_blocked_mask(cell_x, cell_y, xs, ys, segments)
    ref = np.zeros((cell_x.size, n_wells), dtype=bool)
    for i, (nx, ny) in enumerate(zip(cell_x, cell_y)):
        for j in range(n_wells):
            if ce.is_blocked_by_barrier(
                (float(nx), float(ny)), (float(xs[j]), float(ys[j])), barriers
            ):
                ref[i, j] = True
    np.testing.assert_array_equal(got, ref)
    assert ref.sum() > 0


def test_barrier_blocked_mask_matches_reference_degenerate():
    """Collinear / on-segment cases must match too."""
    gx = np.arange(0.0, 8.0)
    gy = np.arange(0.0, 8.0)
    cell_x = np.tile(gx, 8)
    cell_y = np.repeat(gy, 8)
    # Wells exactly on a horizontal barrier line.
    barriers = _barriers_from([[(0.0, 25.0), (100.0, 25.0)]])
    segments = ce._barrier_segments(barriers)
    xs = np.array([10.0, 30.0, 50.0, 70.0])
    ys = np.array([25.0, 25.0, 25.0, 25.0])
    got = ce._barrier_blocked_mask(cell_x, cell_y, xs, ys, segments)
    ref = np.zeros((cell_x.size, 4), dtype=bool)
    for i, (nx, ny) in enumerate(zip(cell_x, cell_y)):
        for j in range(4):
            if ce.is_blocked_by_barrier(
                (float(nx), float(ny)), (float(xs[j]), float(ys[j])), barriers
            ):
                ref[i, j] = True
    np.testing.assert_array_equal(got, ref)


# --------------------------------------------------------------------------- #
# Vectorized smooth_valid_grid vs the reference scalar loop
# --------------------------------------------------------------------------- #


def _ref_smooth(
    grid, x_coords, y_coords, barriers, iterations,
    near_barrier_mask=None, region_labels=None,
    direction_field=None, direction_strength=1.0,
):
    result = np.array(grid, dtype=float, copy=True)
    if iterations <= 0 or result.size == 0:
        return result
    valid_mask = np.isfinite(result)
    if not bool(valid_mask.any()):
        return result
    offsets = (
        (0, 0, 4.0), (-1, 0, 2.0), (1, 0, 2.0), (0, -1, 2.0), (0, 1, 2.0),
        (-1, -1, 1.0), (-1, 1, 1.0), (1, -1, 1.0), (1, 1, 1.0),
    )
    rows, cols = result.shape
    aspect = ce._grid_aspect(x_coords, y_coords)
    direction_strength = max(0.0, float(direction_strength))
    for _ in range(max(0, int(iterations))):
        next_grid = result.copy()
        for row in range(rows):
            center_y = float(y_coords[row])
            for col in range(cols):
                if not valid_mask[row, col]:
                    continue
                check_barrier = bool(barriers) and (
                    near_barrier_mask is None or bool(near_barrier_mask[row, col])
                )
                center = (float(x_coords[col]), center_y)
                weighted_sum = 0.0
                weight_sum = 0.0
                for dr, dc, weight in offsets:
                    nr = row + dr
                    nc = col + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    if not valid_mask[nr, nc] or not math.isfinite(float(result[nr, nc])):
                        continue
                    if (dr != 0 or dc != 0) and region_labels is not None \
                            and region_labels[nr, nc] != region_labels[row, col]:
                        continue
                    if (dr != 0 or dc != 0) and check_barrier:
                        neighbor = (float(x_coords[nc]), float(y_coords[nr]))
                        if ce.is_blocked_by_barrier(center, neighbor, barriers, 1e-9):
                            continue
                    if (dr != 0 or dc != 0) and direction_field is not None:
                        field_entry = direction_field[row, col]
                        base_multiplier = ce._anisotropic_fill_multiplier(
                            dr, dc, field_entry, aspect
                        )
                        if base_multiplier > 1.0:
                            weight *= 1.0 + (base_multiplier - 1.0) * direction_strength
                    weighted_sum += float(result[nr, nc]) * weight
                    weight_sum += weight
                if weight_sum > 0.0:
                    next_grid[row, col] = weighted_sum / weight_sum
        next_grid[~valid_mask] = np.nan
        result = next_grid
    return result


def test_smooth_valid_grid_matches_reference():
    rng = np.random.default_rng(9)
    rows, cols = 22, 22
    gx = np.linspace(-5.0, 105.0, cols)
    gy = np.linspace(-5.0, 105.0, rows)
    grid = rng.normal(25.0, 5.0, (rows, cols))
    grid[rng.random((rows, cols)) < 0.15] = np.nan
    barriers = _barriers_from(_wavy_breaks())
    near = np.zeros((rows, cols), dtype=bool)
    near[8:16, 8:16] = True
    labels = np.zeros((rows, cols), dtype=int)
    labels[12:, :] = 1
    dirf = np.zeros((rows, cols, 3))
    dirf[..., 0] = 1.0
    dirf[..., 2] = 3.0

    cases = [
        ("plain", dict(barriers=(), iterations=2)),
        ("barriers+labels", dict(barriers=barriers, iterations=2,
                                 near_barrier_mask=near, region_labels=labels)),
        ("direction", dict(barriers=(), iterations=2, direction_field=dirf,
                           direction_strength=1.5)),
        ("barriers+labels+dir", dict(barriers=barriers, iterations=2,
                                     near_barrier_mask=near, region_labels=labels,
                                     direction_field=dirf, direction_strength=1.2)),
    ]
    for label, kw in cases:
        got = ce.smooth_valid_grid(grid, gx, gy, **kw)
        ref = _ref_smooth(grid, gx, gy, **kw)
        np.testing.assert_array_equal(got, ref, err_msg=f"smooth[{label}]")


# --------------------------------------------------------------------------- #
# Vectorized refine_domain_boundary_transition vs reference
# --------------------------------------------------------------------------- #


def _ref_refine(grid, domain_mask, x_coords, y_coords, barriers, *,
                near_barrier_mask=None, region_labels=None,
                feather_cells=4, iterations=2):
    result = np.array(grid, dtype=float, copy=True)
    if iterations <= 0 or result.size == 0 or not bool(np.any(domain_mask)):
        return result
    from scipy.ndimage import distance_transform_edt

    dist_to_edge = distance_transform_edt(np.asarray(domain_mask, dtype=bool))
    feather = max(float(feather_cells), 1.0)
    edge_band = (
        np.asarray(domain_mask, dtype=bool)
        & (dist_to_edge > 0.0)
        & (dist_to_edge <= feather)
    )
    if not bool(np.any(edge_band)):
        return result
    valid_mask = np.isfinite(result) & np.asarray(domain_mask, dtype=bool)
    offsets = (
        (-1, 0, 2.0), (1, 0, 2.0), (0, -1, 2.0), (0, 1, 2.0),
        (-1, -1, 1.0), (-1, 1, 1.0), (1, -1, 1.0), (1, 1, 1.0),
    )
    rows, cols = result.shape
    for _ in range(max(0, int(iterations))):
        next_grid = result.copy()
        for row, col in zip(*np.nonzero(edge_band)):
            if not valid_mask[row, col]:
                continue
            check_barrier = bool(barriers) and (
                near_barrier_mask is None or bool(near_barrier_mask[row, col])
            )
            center = (float(x_coords[col]), float(y_coords[row]))
            weighted_sum = 0.0
            weight_sum = 0.0
            for dr, dc, weight in offsets:
                nr = row + dr
                nc = col + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                if not valid_mask[nr, nc] or not math.isfinite(float(result[nr, nc])):
                    continue
                if region_labels is not None and region_labels[nr, nc] != region_labels[row, col]:
                    continue
                if check_barrier:
                    neighbor = (float(x_coords[nc]), float(y_coords[nr]))
                    if ce.is_blocked_by_barrier(center, neighbor, barriers, 1e-9):
                        continue
                edge_factor = float(dist_to_edge[nr, nc]) / feather
                weighted_sum += float(result[nr, nc]) * weight * max(edge_factor, 0.35)
                weight_sum += weight * max(edge_factor, 0.35)
            if weight_sum > 0.0:
                interior = weighted_sum / weight_sum
                blend = float(np.clip(dist_to_edge[row, col] / feather, 0.0, 1.0))
                next_grid[row, col] = interior * blend + float(result[row, col]) * (1.0 - blend)
        next_grid[~valid_mask] = np.nan
        result = next_grid
    return result


def test_refine_domain_boundary_transition_matches_reference():
    rng = np.random.default_rng(13)
    rows, cols = 22, 22
    gx = np.linspace(-5.0, 105.0, cols)
    gy = np.linspace(-5.0, 105.0, rows)
    grid = rng.normal(25.0, 5.0, (rows, cols))
    grid[rng.random((rows, cols)) < 0.1] = np.nan
    domain = np.ones((rows, cols), dtype=bool)
    domain[:2, :] = False
    domain[-2:, :] = False
    domain[:, :2] = False
    domain[:, -2:] = False
    barriers = _barriers_from(_wavy_breaks())
    near = np.zeros((rows, cols), dtype=bool)
    near[8:16, 8:16] = True
    labels = np.zeros((rows, cols), dtype=int)
    labels[12:, :] = 1

    for label, kw in (
        ("plain", dict(barriers=())),
        ("barriers", dict(barriers=barriers, near_barrier_mask=near,
                          region_labels=labels)),
    ):
        got = ce.refine_domain_boundary_transition(grid, domain, gx, gy, **kw)
        ref = _ref_refine(grid, domain, gx, gy, **kw)
        np.testing.assert_array_equal(got, ref, err_msg=f"refine[{label}]")


# --------------------------------------------------------------------------- #
# Vectorized apply_well_residual_anchoring vs reference
# --------------------------------------------------------------------------- #


def _ref_anchor(grid, grid_x, grid_y, wells, domain_mask, config,
                region_labels=None, well_labels=None, direction_field=None):
    result = np.array(grid, dtype=float, copy=True)
    if not config.well_anchor_enabled or grid.size == 0 or not wells:
        return result
    grid_step = ce._estimate_grid_step(grid_x, grid_y)
    step = max(float(grid_step), 1e-9)
    has_dir = (
        direction_field is not None
        and direction_field.ndim == 3
        and direction_field.shape[2] >= 3
        and bool(np.any(direction_field[:, :, 2] > 1.0 + 1e-9))
    )
    preserve_aniso = bool(getattr(config, "well_anchor_preserve_anisotropy", True)) or has_dir
    anchor_radius = float(config.well_anchor_radius)
    if anchor_radius <= 0.0:
        anchor_radius = (
            max(step * 4.0, step * 2.5) if preserve_aniso
            else max(step * 10.0, step * 4.0)
        )
    if preserve_aniso:
        core_radius = max(step * 0.9, min(anchor_radius * 0.22, step * 1.6))
    else:
        core_radius = max(step * 1.5, min(anchor_radius * 0.32, step * 3.0))
    max_stretch = 1.0
    if has_dir:
        max_stretch = max(float(np.nanmax(direction_field[:, :, 2])), 1.0)
    search_bbox_radius = anchor_radius * max(max_stretch, 1.0) if has_dir else anchor_radius
    radius_cells = max(3, int(math.ceil(search_bbox_radius / step)) + 1)
    if preserve_aniso:
        blend_radius = max(anchor_radius * 0.55, step * 2.0)
        sigma = max(anchor_radius * 0.28, step * 1.0)
    else:
        blend_radius = max(anchor_radius * 1.15, step * 4.0)
        sigma = max(anchor_radius * 0.45, step * 1.5)
    blend_cells = max(
        radius_cells, int(math.ceil(blend_radius * max(max_stretch, 1.0) / step)) + 1
    )
    rows, cols = result.shape
    well_centers = []
    finite_values = [float(w.value) for w in wells if math.isfinite(float(w.value))]
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
        halo_scale = 1.0
        if residual_cap > 1e-9 and abs(residual) > residual_cap:
            halo_scale = residual_cap / abs(residual)
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
            (row, col, float(well.x), float(well.y), target_value,
             halo_target, unit_x, unit_y, ratio_eff)
        )
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                nr = row + dr
                nc = col + dc
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                if not domain_mask[nr, nc]:
                    continue
                if region_labels is not None and region_labels[nr, nc] != region_labels[row, col]:
                    continue
                gx = float(grid_x[nc])
                gy = float(grid_y[nr])
                if ratio_eff > 1.0 + 1e-9:
                    perp = ce.direction_perpendicular_scale(
                        ratio_eff,
                        float(getattr(config, "direction_perpendicular_strength", 1.0)),
                    )
                    dist = ce.anisotropic_distance(
                        (well.x, well.y), (gx, gy), unit_x, unit_y, ratio_eff,
                        perpendicular_scale=perp,
                    )
                else:
                    dist = math.hypot(gx - well.x, gy - well.y)
                if dist > anchor_radius:
                    continue
                if nr == row and nc == col:
                    result[nr, nc] = target_value
                elif abs(residual) > 1e-9 and math.isfinite(result[nr, nc]):
                    t = max(0.0, dist - core_radius) / max(anchor_radius - core_radius, 1e-9)
                    t = max(0.0, min(1.0, t))
                    weight = 0.5 * (1.0 + math.cos(math.pi * t))
                    corrected = float(result[nr, nc]) + residual * halo_scale * weight
                    if (config.value_min is not None and config.value_max is not None
                            and float(config.value_min) <= target_value <= float(config.value_max)):
                        corrected = max(float(config.value_min), min(float(config.value_max), corrected))
                    result[nr, nc] = corrected
    if well_centers and (not preserve_aniso or blend_radius >= step * 1.5):
        blended = np.array(result, dtype=float, copy=True)
        two_sig2 = 2.0 * sigma * sigma
        core_mix = 0.70 if preserve_aniso else 0.85
        outer_well = 0.35 if preserve_aniso else 0.55
        outer_keep = 0.65 if preserve_aniso else 0.45
        for row, col, wx, wy, target_value, halo_target, unit_x, unit_y, ratio_eff in well_centers:
            for dr in range(-blend_cells, blend_cells + 1):
                for dc in range(-blend_cells, blend_cells + 1):
                    nr, nc = row + dr, col + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    if not domain_mask[nr, nc] or not math.isfinite(result[nr, nc]):
                        continue
                    if region_labels is not None and region_labels[nr, nc] != region_labels[row, col]:
                        continue
                    gx = float(grid_x[nc])
                    gy = float(grid_y[nr])
                    if ratio_eff > 1.0 + 1e-9:
                        perp = ce.direction_perpendicular_scale(
                            ratio_eff,
                            float(getattr(config, "direction_perpendicular_strength", 1.0)),
                        )
                        dist = ce.anisotropic_distance(
                            (wx, wy), (gx, gy), unit_x, unit_y, ratio_eff,
                            perpendicular_scale=perp,
                        )
                    else:
                        dist = math.hypot(gx - wx, gy - wy)
                    if dist > blend_radius:
                        continue
                    if nr == row and nc == col:
                        new_v = target_value
                    elif preserve_aniso:
                        radial = math.exp(-(dist * dist) / max(two_sig2, 1e-12))
                        if dist <= core_radius:
                            new_v = core_mix * halo_target + (1.0 - core_mix) * float(result[nr, nc])
                        else:
                            new_v = (radial * (outer_well * halo_target + outer_keep * float(result[nr, nc]))
                                     + (1.0 - radial) * float(result[nr, nc]))
                    else:
                        acc = 0.0
                        wsum = 0.0
                        sample_r = max(1, int(math.ceil(1.6 * step / step)))
                        for sdr in range(-sample_r, sample_r + 1):
                            for sdc in range(-sample_r, sample_r + 1):
                                sr, sc = nr + sdr, nc + sdc
                                if sr < 0 or sr >= rows or sc < 0 or sc >= cols:
                                    continue
                                if not domain_mask[sr, sc] or not math.isfinite(result[sr, sc]):
                                    continue
                                if region_labels is not None and region_labels[sr, sc] != region_labels[nr, nc]:
                                    continue
                                d2 = float(sdr * sdr + sdc * sdc) * (step * step)
                                sw = math.exp(-d2 / max(two_sig2 * 0.35, 1e-12))
                                acc += float(result[sr, sc]) * sw
                                wsum += sw
                        if wsum <= 1e-12:
                            continue
                        local_mean = acc / wsum
                        radial = math.exp(-(dist * dist) / max(two_sig2, 1e-12))
                        if dist <= core_radius:
                            new_v = core_mix * halo_target + (1.0 - core_mix) * local_mean
                        else:
                            new_v = (radial * (outer_well * halo_target + outer_keep * float(result[nr, nc]))
                                     + (1.0 - radial) * local_mean)
                    if (config.value_min is not None and config.value_max is not None
                            and float(config.value_min) <= target_value <= float(config.value_max)):
                        new_v = max(float(config.value_min), min(float(config.value_max), float(new_v)))
                    blended[nr, nc] = new_v
        result = blended
    return result


def test_apply_well_residual_anchoring_matches_reference():
    rng = np.random.default_rng(11)
    rows, cols = 28, 28
    gx = np.linspace(-5.0, 105.0, cols)
    gy = np.linspace(-5.0, 105.0, rows)
    grid = rng.normal(25.0, 5.0, (rows, cols))
    grid[rng.random((rows, cols)) < 0.1] = np.nan
    domain = np.ones((rows, cols), dtype=bool)
    domain[:2, :] = False
    domain[-2:, :] = False
    domain[:, :2] = False
    domain[:, -2:] = False
    wells = [
        ConstraintWell(str(i), float(x), float(y), float(v))
        for i, (x, y, v) in enumerate(zip(
            rng.uniform(0, 100, 10),
            rng.uniform(0, 100, 10),
            rng.uniform(10, 90, 10),
        ))
    ]
    config = ConstrainedIDWConfig(
        grid_resolution=50, value_min=0.0, value_max=100.0,
        well_anchor_enabled=True, well_anchor_radius=6.0,
        well_anchor_preserve_anisotropy=False,
    )
    labels = np.zeros((rows, cols), dtype=int)
    labels[15:, :] = 1
    well_labels = np.array([0 if w.y < 55.0 else 1 for w in wells], dtype=int)
    dirf = np.zeros((rows, cols, 3))
    dirf[..., 0] = 1.0
    dirf[..., 2] = 4.0

    cases = [
        ("iso", dict()),
        ("iso+labels", dict(region_labels=labels, well_labels=well_labels)),
        ("aniso", dict(direction_field=dirf)),
    ]
    for label, kw in cases:
        got, got_stats = ce.apply_well_residual_anchoring(
            grid, gx, gy, wells, domain, config, **kw
        )
        ref = _ref_anchor(grid, gx, gy, wells, domain, config, **kw)
        # Vectorized distances use np.hypot; the reference uses math.hypot.
        # Both are correctly rounded but can differ by one ulp (~0.6% of
        # values), so parity is asserted within tight float tolerance.
        np.testing.assert_allclose(
            got, ref, rtol=1e-12, atol=1e-12, equal_nan=True,
            err_msg=f"anchor[{label}]",
        )
        # Edge wells exercise the clipped patch windows.
        edge_wells = [
            ConstraintWell("e1", 0.5, 0.5, 50.0),
            ConstraintWell("e2", 104.0, 104.0, 60.0),
        ]
        got_e, _ = ce.apply_well_residual_anchoring(
            grid, gx, gy, edge_wells, domain, config, **kw
        )
        ref_e = _ref_anchor(grid, gx, gy, edge_wells, domain, config, **kw)
        np.testing.assert_allclose(
            got_e, ref_e, rtol=1e-12, atol=1e-12, equal_nan=True,
            err_msg=f"anchor-edge[{label}]",
        )


# --------------------------------------------------------------------------- #
# Vectorized barrier blank buffer vs the reference sampling implementation
# --------------------------------------------------------------------------- #


def test_barrier_blank_mask_matches_reference():
    rng = np.random.default_rng(21)
    lines = []
    for p in range(2):
        pts = []
        for i in range(20):
            t = i / 19
            x = 5.0 + t * 90.0
            y = 40.0 + p * 15.0 + 8.0 * np.sin(t * 6.0 + p)
            pts.append((float(x), float(y)))
        lines.append(pts)
    barriers = _barriers_from(lines)
    gx = np.linspace(-5.0, 105.0, 36)
    gy = np.linspace(-5.0, 105.0, 36)
    R = 4.4

    got = ce.build_barrier_blank_mask(gx, gy, barriers, R, None)

    # Reference: the pre-vectorization sampling + stadium distance version.
    x0 = float(gx[0]); y0 = float(gy[0])
    dx = float(gx[1] - gx[0]); dy = float(gy[1] - gy[0])
    rows, cols = len(gy), len(gx)
    cell = max(min(abs(dx), abs(dy)), 1e-9)
    dilation = int(math.ceil(R / cell)) + 2
    ref = np.zeros((rows, cols), dtype=bool)
    sample_step = cell * 0.5
    for barrier in barriers:
        pts = list(getattr(barrier, "points", ()) or ())
        if len(pts) < 1:
            continue
        sample_pts = []
        for p0, p1 in ce._segments(pts):
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            samples = max(2, int(length / max(sample_step, 1e-9)) + 2)
            for i in range(samples):
                t = i / (samples - 1)
                sample_pts.append(
                    (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
                )
        if len(pts) >= 2:
            for end_idx, inward_idx, sign in ((0, 1, -1.0), (-1, -2, 1.0)):
                ex, ey = float(pts[end_idx][0]), float(pts[end_idx][1])
                ix, iy = float(pts[inward_idx][0]), float(pts[inward_idx][1])
                tx, ty = ex - ix, ey - iy
                tn = math.hypot(tx, ty)
                if tn <= 1e-12:
                    continue
                ux, uy = tx / tn, ty / tn
                n_tip = max(2, int(R / max(sample_step, 1e-9)) + 1)
                for k in range(1, n_tip + 1):
                    d = R * (k / n_tip)
                    sample_pts.append((ex + sign * ux * d, ey + sign * uy * d))
        for px, py in sample_pts:
            col = int(round((px - x0) / dx))
            row = int(round((py - y0) / dy))
            r0 = max(0, row - dilation)
            r1 = min(rows - 1, row + dilation)
            c0 = max(0, col - dilation)
            c1 = min(cols - 1, col + dilation)
            if r1 < r0 or c1 < c0:
                continue
            for rr in range(r0, r1 + 1):
                for cc in range(c0, c1 + 1):
                    if ref[rr, cc]:
                        continue
                    center = (float(gx[cc]), float(gy[rr]))
                    if ce._point_within_polyline_stadium_buffer(center, pts, R):
                        ref[rr, cc] = True
    ref_out = ref if bool(ref.any()) else None
    if got is None:
        assert ref_out is None
    else:
        # The distance threshold sits at R + 1e-12; np.hypot vs math.hypot can
        # differ by one ulp, so allow a few boundary cells to flip.
        mismatch = int(np.count_nonzero(got != ref_out))
        assert mismatch <= 4, f"blank mask differs in {mismatch} cells"


# --------------------------------------------------------------------------- #
# Vectorized euclidean interpolation fast path vs the reference pass loop
# --------------------------------------------------------------------------- #


def test_interpolate_grid_point_euclidean_matches_reference():
    rng = np.random.default_rng(31)
    n_wells = 60
    xs = rng.uniform(0, 100, n_wells)
    ys = rng.uniform(0, 100, n_wells)
    well_array = np.column_stack([xs, ys, rng.uniform(10, 90, n_wells)])
    density = rng.uniform(0.5, 1.5, n_wells)
    barriers = _barriers_from(_wavy_breaks())
    segments = ce._barrier_segments(barriers)
    config = ConstrainedIDWConfig(
        grid_resolution=50, search_radius=200.0, decluster_radius=30.0,
        value_min=0.0, value_max=100.0, min_points=3, max_points=12, power=2.0,
    )
    gx = np.linspace(-5.0, 105.0, 14)
    gy = np.linspace(-5.0, 105.0, 14)
    cell_x = np.tile(gx, 14)
    cell_y = np.repeat(gy, 14)
    mask = ce._barrier_blocked_mask(cell_x, cell_y, xs, ys, segments)

    for i, (nx, ny) in enumerate(zip(cell_x, cell_y)):
        pt = (float(nx), float(ny))
        euclidean = np.sqrt((well_array[:, 0] - nx) ** 2 + (well_array[:, 1] - ny) ** 2)
        fast = ce._interpolate_grid_point(
            pt=pt, well_array=well_array, barriers=barriers, directions=[],
            config=config, density_weights=density,
            blocked_mask=mask, cell_index=i,
        )
        # Reference: re-implement the scalar pass loop via the direction path
        # cannot be used directly; emulate it with a hand-rolled loop.
        ref = _euclidean_scalar_reference(
            pt, well_array, barriers, config, density, euclidean, mask[i]
        )
        assert fast == ref, f"cell {pt}: {fast} != {ref}"


def _euclidean_scalar_reference(pt, well_array, barriers, config, density_weights,
                                euclidean, mask_row):
    n = len(well_array)
    blocked_indices = set()
    required_points = max(1, int(config.min_points))
    base_radius = max(float(config.search_radius), 1e-9)
    radius_scales = (
        (1.0,)
        if bool(config.limit_interpolation_to_search_radius)
        else (1.0, 1.5, 2.25, 3.0)
    )
    weighted_candidates = []
    for pass_index, radius_scale in enumerate(radius_scales):
        r_pass = base_radius * radius_scale
        weighted_candidates = []
        for idx in range(n):
            if barriers:
                if mask_row is not None:
                    blocked_flag = bool(mask_row[idx])
                else:
                    blocked_flag = ce.is_blocked_by_barrier(
                        pt,
                        (float(well_array[idx, 0]), float(well_array[idx, 1])),
                        barriers,
                        config.endpoint_tolerance,
                    )
                if blocked_flag:
                    blocked_indices.add(int(idx))
                    continue
            filter_d = float(euclidean[idx])
            if filter_d > r_pass:
                continue
            dist = float(euclidean[idx])
            if dist <= 1e-9:
                return float(well_array[idx, 2]), len(blocked_indices), False
            density_weight = (
                float(density_weights[int(idx)]) if density_weights.size else 1.0
            )
            weighted_candidates.append((dist, float(well_array[idx, 2]), density_weight))
        required_points = max(1, int(config.min_points) - pass_index)
        if len(weighted_candidates) >= required_points:
            break
    if len(weighted_candidates) < required_points:
        return None, len(blocked_indices), False
    weighted_candidates.sort(key=lambda item: item[0])
    selected = weighted_candidates[: max(1, int(config.max_points))]
    distances = np.asarray([item[0] for item in selected], dtype=float)
    values = np.asarray([item[1] for item in selected], dtype=float)
    decluster = np.asarray([item[2] for item in selected], dtype=float)
    weights = decluster / np.power(np.maximum(distances, 1e-9), float(config.power))
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        return None, len(blocked_indices), False
    return float(np.sum(weights * values) / weight_sum), len(blocked_indices), False
