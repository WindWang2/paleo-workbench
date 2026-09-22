"""P2 constrained-IDW regressions: curve+barrier point path (#524) and RAM budget (#525)."""

from __future__ import annotations

import time

import numpy as np

from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

_ensure_haiyou_engine()
import drawing.single_factor.direction_corridor as dc  # noqa: E402
from drawing.compute.performance import ComputeSettings  # noqa: E402
from drawing.single_factor.constrained_engine import (  # noqa: E402
    BarrierLine,
    BoundaryPolygon,
    ConstrainedIDWConfig,
    ConstraintWell,
    DirectionLine,
    generate_constrained_idw,
)


def test_pairs_effective_distance_matches_scalar_pair_loop():
    """Vectorized (s,n) distances must match the per-well scalar functions."""
    rng = np.random.default_rng(7)
    n_wells = 80
    well_xy = rng.uniform(0.0, 100.0, (n_wells, 2))
    geoms = dc.build_direction_geometries(
        [
            dc.DirectionLineSpec(
                line_id="d0",
                points=((0.0, 50.0), (100.0, 50.0)),
                active=True,
                ratio=8.0,
                influence_radius=40.0,
                priority=1,
            )
        ],
        search_radius=40.0,
        mean_well_spacing=8.0,
        map_extent=100.0,
    )
    well_coords = dc.precompute_well_curve_coords(well_xy, geoms)
    pt = np.array([42.0, 51.0])
    euclidean = np.hypot(well_xy[:, 0] - pt[0], well_xy[:, 1] - pt[1])
    cell_s, cell_n, *_rest, _dist = dc.project_point_to_polyline((42.0, 51.0), geoms[0])
    cell_g = dc.combined_influence(_dist, cell_s, geoms[0])

    d_vec, g_vec = dc.pairs_effective_distance(
        euclidean=euclidean,
        cell_dir=0,
        cell_s=cell_s,
        cell_n=cell_n,
        cell_g=cell_g,
        cell_ratio=8.0,
        well_coords=well_coords,
        geoms=geoms,
    )
    in_vec = dc.pairs_in_search_neighborhood(
        euclidean=euclidean,
        d_eff=d_vec,
        g_pair=g_vec,
        cell_s=cell_s,
        cell_n=cell_n,
        cell_ratio=8.0,
        cell_dir=0,
        well_coords=well_coords,
        base_radius=40.0,
        use_extended_search=True,
    )

    d_ref = np.empty(n_wells)
    g_ref = np.empty(n_wells)
    in_ref = np.empty(n_wells, dtype=bool)
    for i in range(n_wells):
        d_ref[i], g_ref[i] = dc.pair_effective_distance(
            euclidean=float(euclidean[i]),
            cell_dir=0,
            cell_s=cell_s,
            cell_n=cell_n,
            cell_g=cell_g,
            cell_ratio=8.0,
            well_index=i,
            well_coords=well_coords,
            geoms=geoms,
        )
        in_ref[i] = dc.pair_in_search_neighborhood(
            euclidean=float(euclidean[i]),
            d_eff=float(d_ref[i]),
            g_pair=float(g_ref[i]),
            cell_s=cell_s,
            cell_n=cell_n,
            cell_ratio=8.0,
            well_index=i,
            cell_dir=0,
            well_coords=well_coords,
            base_radius=40.0,
            use_extended_search=True,
        )
    np.testing.assert_allclose(d_vec, d_ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(g_vec, g_ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(in_vec, in_ref)


def test_curve_plus_barrier_point_path_avoids_scalar_pair_loop(monkeypatch):
    """#524: 300 wells + direction + barrier at grid 200 must not call the
    per-well Python pair functions (old path: tens of seconds)."""
    rng = np.random.default_rng(11)
    n_wells = 300
    xs = rng.uniform(0.0, 100.0, n_wells)
    ys = rng.uniform(0.0, 100.0, n_wells)
    zs = rng.uniform(10.0, 90.0, n_wells)
    wells = [
        ConstraintWell(f"w{i}", float(xs[i]), float(ys[i]), float(zs[i]))
        for i in range(n_wells)
    ]
    boundary = BoundaryPolygon(
        exterior=(( -5.0, -5.0), (105.0, -5.0), (105.0, 105.0), (-5.0, 105.0), (-5.0, -5.0))
    )
    barriers = [BarrierLine("b0", points=((50.0, -5.0), (50.0, 105.0)), active=True)]
    directions = [
        DirectionLine(
            "d0",
            points=(( -5.0, 50.0), (105.0, 50.0)),
            active=True,
            ratio=8.0,
            influence_radius=40.0,
        )
    ]
    config = ConstrainedIDWConfig(
        grid_resolution=200,
        search_radius=80.0,
        decluster_radius=15.0,
        value_min=0.0,
        value_max=100.0,
        extract_contours=False,
        well_anchor_enabled=False,
        grid_smoothing_iterations=0,
        gap_fill_iterations=0,
        barrier_buffer_auto=False,
        barrier_buffer_distance=0.0,
        along_track_blend_strength=0.0,
    )

    pair_calls = {"n": 0}
    nbhd_calls = {"n": 0}
    orig_pair = dc.pair_effective_distance
    orig_nbhd = dc.pair_in_search_neighborhood

    def _count_pair(**kwargs):
        pair_calls["n"] += 1
        return orig_pair(**kwargs)

    def _count_nbhd(**kwargs):
        nbhd_calls["n"] += 1
        return orig_nbhd(**kwargs)

    monkeypatch.setattr(dc, "pair_effective_distance", _count_pair)
    monkeypatch.setattr(dc, "pair_in_search_neighborhood", _count_nbhd)

    t0 = time.perf_counter()
    result = generate_constrained_idw(
        wells, [boundary], barriers, directions, levels=(30.0, 50.0, 70.0), config=config
    )
    elapsed = time.perf_counter() - t0

    finite = int(np.count_nonzero(np.isfinite(result.grid_z)))
    assert finite > 1000
    # Old code: one scalar call per (corridor cell × well) ≈ 10^5–10^7.
    # A handful is only acceptable if a test helper called the scalar API.
    assert pair_calls["n"] == 0, pair_calls["n"]
    assert nbhd_calls["n"] == 0, nbhd_calls["n"]
    # Old scalar loop: ~8e6 pair calls / ~50s on this fixture. 20s still
    # fails that path while allowing host variance around the vectorized ~10s.
    assert elapsed < 20.0, f"curve+barrier IDW took {elapsed:.1f}s"


def test_idw_row_block_budget_is_global_not_per_worker():
    """#525: (block × cols × wells × workers) must stay inside the element budget."""
    settings = ComputeSettings()
    settings.cpu_percent = 100
    workers = settings.cpu_workers()
    cols, n_wells = 200, 4000
    block = settings.idw_row_block(cols, n_wells)
    target = 4_000_000 + int(12_000_000 * (settings.cpu_percent / 100.0))
    peak_elements = int(block) * cols * n_wells * max(int(workers), 1)
    assert peak_elements <= target, (
        f"block={block} workers={workers} peak={peak_elements} target={target}"
    )
    assert block >= 1
