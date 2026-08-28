"""P3 session-8 regressions: IDW masks/corridor, coherence fallback, table cap."""

from __future__ import annotations

import time

import numpy as np
import pytest

from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

_ensure_haiyou_engine()
import drawing.single_factor.constrained_engine as ce  # noqa: E402
import drawing.single_factor.direction_corridor as dc  # noqa: E402
import drawing.single_factor.masks as masks  # noqa: E402
from drawing.single_factor.constrained_engine import (  # noqa: E402
    BoundaryPolygon,
    ConstrainedIDWConfig,
    ConstraintWell,
    generate_constrained_idw,
)
from drawing.single_factor.fast_grid import rasterize_polygon_mask  # noqa: E402


def _naive_well_coverage_mask(grid_x, grid_y, wells, coverage_radius):
    well_xy = np.asarray([(well.x, well.y) for well in wells], dtype=float)
    radius_sq = float(coverage_radius) * float(coverage_radius)
    cols = np.asarray(grid_x, dtype=float)
    rows = np.asarray(grid_y, dtype=float)
    dx = cols[None, :] - well_xy[:, 0][:, None, None]
    dy = rows[None, :, None] - well_xy[:, 1][:, None, None]
    return np.any(dx * dx + dy * dy <= radius_sq, axis=0)


def test_well_coverage_mask_matches_broadcast_and_chunks_allocation():
    """#633: coverage must match the (W,R,C) broadcast without allocating it."""
    rng = np.random.default_rng(3)
    wells = [
        ConstraintWell(f"w{i}", float(x), float(y), 0.0)
        for i, (x, y) in enumerate(rng.uniform(0.0, 100.0, (40, 2)))
    ]
    grid_x = np.linspace(0.0, 100.0, 32)
    grid_y = np.linspace(0.0, 100.0, 28)
    got = ce.build_well_coverage_mask(grid_x, grid_y, wells, 18.0)
    ref = _naive_well_coverage_mask(grid_x, grid_y, wells, 18.0)
    np.testing.assert_array_equal(got, ref)

    shapes: list[tuple[int, ...]] = []
    real_any = np.any

    def spy_any(a, *args, **kwargs):
        shapes.append(tuple(np.shape(a)))
        return real_any(a, *args, **kwargs)

    n_wells = 800
    big = [
        ConstraintWell(f"w{i}", float(x), float(y), 0.0)
        for i, (x, y) in enumerate(rng.uniform(0.0, 100.0, (n_wells, 2)))
    ]
    gx = np.linspace(0.0, 100.0, 80)
    gy = np.linspace(0.0, 100.0, 80)
    np_mod = getattr(ce, "np")
    orig = np_mod.any
    np_mod.any = spy_any
    try:
        ce.build_well_coverage_mask(gx, gy, big, 12.0)
    finally:
        np_mod.any = orig
    budget = 4_000_000
    assert shapes, "coverage mask never reduced an array"
    assert all(int(np.prod(s)) <= budget for s in shapes), shapes
    assert all(s[0] != n_wells or len(s) < 3 for s in shapes), shapes


def test_default_limit_path_skips_per_cell_hull_mask(monkeypatch):
    """#634: default well-coverage path must not pay for a discarded hull raster."""
    calls = {"n": 0}
    real = masks.build_data_hull_mask

    def spy(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(masks, "build_data_hull_mask", spy)

    wells = [
        ConstraintWell("a", 0.0, 0.0, 1.0),
        ConstraintWell("b", 10.0, 0.0, 2.0),
        ConstraintWell("c", 0.0, 10.0, 3.0),
        ConstraintWell("d", 10.0, 10.0, 4.0),
    ]
    boundary = BoundaryPolygon(
        exterior=(( -1.0, -1.0), (11.0, -1.0), (11.0, 11.0), (-1.0, 11.0), (-1.0, -1.0))
    )
    config = ConstrainedIDWConfig(
        grid_resolution=20,
        search_radius=8.0,
        extract_contours=False,
        well_anchor_enabled=False,
        grid_smoothing_iterations=0,
        gap_fill_iterations=0,
        limit_interpolation_to_search_radius=True,
    )
    result = generate_constrained_idw(
        wells, [boundary], [], [], levels=(2.0,), config=config
    )
    assert calls["n"] == 0
    assert int(result.diagnostics["data_hull_limited"]) == 1
    assert int(result.diagnostics["data_hull_domain_skipped"]) == 1
    assert float(result.diagnostics["data_hull_buffer_meters"]) > 0.0


def test_data_hull_mask_matches_vectorized_raster():
    """#634: when a hull mask is required it must match rasterize_polygon_mask."""
    wells = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [4.0, 4.0]])
    grid_x = np.linspace(-2.0, 12.0, 29)
    grid_y = np.linspace(-2.0, 12.0, 31)
    got = masks.build_data_hull_mask(grid_x, grid_y, wells, buffer_meters=0.0)
    hull = masks._convex_hull(wells)
    ref = rasterize_polygon_mask(grid_x, grid_y, hull)
    assert isinstance(got, np.ndarray)
    assert got.shape == ref.shape
    np.testing.assert_array_equal(got, ref)


def test_grid_direction_cache_matches_scalar_and_stays_fast():
    """#632: corridor cache must match per-cell projection and stay under 1s."""
    geoms = dc.build_direction_geometries(
        [
            dc.DirectionLineSpec(
                line_id=f"d{i}",
                points=tuple(
                    (float(s), 20.0 + 20.0 * i + 2.0 * ((s // 10) % 2))
                    for s in range(0, 201, 10)
                ),
                active=True,
                ratio=8.0,
                influence_radius=40.0,
                priority=1,
            )
            for i in range(3)
        ],
        search_radius=40.0,
        mean_well_spacing=8.0,
        map_extent=200.0,
    )
    assert all(len(g.points) >= 20 for g in geoms)
    grid_x = np.linspace(0.0, 200.0, 40)
    grid_y = np.linspace(0.0, 80.0, 24)
    domain = np.ones((len(grid_y), len(grid_x)), dtype=bool)
    got = dc.build_grid_direction_cache(grid_x, grid_y, domain, geoms)

    rr, cc = np.nonzero(domain)
    for r, c in zip(rr[::17], cc[::17]):
        p = (float(grid_x[c]), float(grid_y[r]))
        best = None
        best_score = -1.0
        for geom in geoms:
            s, n_signed, txx, tyy, dist = dc.project_point_to_polyline(p, geom)
            g = dc.combined_influence(dist, s, geom)
            if g <= 1e-9:
                continue
            prio_boost = 1.0 / max(float(geom.priority), 1.0)
            score = g * (1.0 + 0.15 * prio_boost) / (
                1.0 + dist / max(geom.influence_radius, 1.0)
            )
            if score > best_score:
                best_score = score
                best = (geom.index, s, n_signed, txx, tyy, g, geom.ratio)
        if best is None:
            assert int(got["dir_index"][r, c]) == -1
            continue
        assert int(got["dir_index"][r, c]) == int(best[0])
        np.testing.assert_allclose(got["s"][r, c], best[1], atol=1e-9)
        np.testing.assert_allclose(got["n"][r, c], best[2], atol=1e-9)
        np.testing.assert_allclose(got["g"][r, c], best[5], atol=1e-9)

    gx = np.linspace(0.0, 200.0, 200)
    gy = np.linspace(0.0, 200.0, 200)
    big_domain = np.ones((200, 200), dtype=bool)
    t0 = time.perf_counter()
    dc.build_grid_direction_cache(gx, gy, big_domain, geoms)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"direction cache took {elapsed:.2f}s"


def test_table_preview_serves_full_grid_with_lazy_model(qtbot, monkeypatch):
    """#658 → #1039: the model serves the whole grid lazily; the only cap
    left is the cell-count safety valve, not per-cell materialization."""
    from paleo_workbench.ui.pages import table_preview_widget as tpw
    from paleo_workbench.ui.pages.table_preview_widget import TablePreviewWidget

    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    headers = tuple(f"c{i}" for i in range(200))
    rows = tuple(tuple(str(c) for c in range(200)) for _ in range(400))
    widget.load_table(headers, rows)
    # 80k cells sit far under the valve: every row/column stays reachable.
    assert widget.rowCount() == 400
    assert widget.columnCount() == 200
    assert widget.truncated is False
    assert not widget.truncation_message
    model = widget.model()
    assert model.data(model.index(399, 199)) == "199"
    # The valve itself still guards pathological inputs.
    monkeypatch.setattr(tpw, "MAX_PREVIEW_CELLS", 2_000)
    widget.load_table(headers, rows)
    assert widget.truncated is True
    assert widget.rowCount() == 10  # 2_000 // 200 columns
    assert "截断" in widget.truncation_message
