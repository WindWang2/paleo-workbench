"""Headless tests for pure-geometry builders (G3-G7 core)."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import (
    build_columnar_hex_mesh,
    build_fault_curtain_from_trace,
    build_fault_from_mesh,
    build_horizon_from_grid,
    build_simplified_vertical_well,
    build_volume_shell,
    build_well_trajectory,
    dedupe_stations,
    triangulate_heightfield,
)
from paleo_workbench.viz.geomodel.domain import DomainError


def grid(nI=6, nX=6, top=100.0, thick=50.0, dtype="flat"):
    x = np.arange(nX, dtype=float) * 10.0
    y = np.arange(nI, dtype=float) * 10.0
    xx, yy = np.meshgrid(x, y)
    if dtype == "flat":
        tg = np.full((nI, nX), top)
        bg = np.full((nI, nX), top + thick)
    elif dtype == "dipping":
        tg = top + 0.2 * xx + 0.1 * yy
        bg = tg + thick
    return tg, bg


def make_horizons(**kw):
    tg, bg = grid(**kw)
    top = build_horizon_from_grid("Top", tg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
    base = build_horizon_from_grid("Base", bg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
    return top, base


class TestWellBuilders:
    def test_dedupe_stations(self):
        st = np.array(
            [
                [100.0, 0, 0, 100],
                [0.0, 0, 0, 0],
                [100.0, 0, 0, 100],  # duplicate MD
                [200.0, 0, 0, 200],
            ]
        )
        out, dropped = dedupe_stations(st)
        assert np.all(np.diff(out[:, 0]) > 0)
        assert dropped == 1

    def test_trajectory_qc_inputs(self):
        with pytest.raises(DomainError):
            build_well_trajectory("w", np.array([[0, 0, 0, 0], [10, 1, 1, 1], [10, 2, 2, 2]]))
        with pytest.raises(DomainError):
            build_simplified_vertical_well("w", (0, 0, 0), -5.0)


class TestHeightfieldTriangulation:
    def test_full_grid_triangle_count(self):
        tg, _ = grid()
        verts, faces = triangulate_heightfield(tg)
        # 6x6 nodes -> 5x5 quads -> 50 triangles
        assert len(verts) == 36
        assert len(faces) == 50

    def test_nan_hole_produces_no_fabricated_triangles(self):
        tg, _ = grid()
        tg[2:4, 2:4] = np.nan  # 2x2 hole
        verts, faces = triangulate_heightfield(tg)
        # every triangle must only reference finite nodes
        used = np.unique(faces)
        assert len(used) == int(np.isfinite(tg).sum())
        # quads touching the hole are dropped: (5-2)^2 cells * 2 remaining
        assert len(faces) == 32
        # no triangle spans the hole: bounding boxes stay within halves
        tri = verts[faces]
        for t in tri:
            xs = t[:, 0]
            if xs.min() < 20.0 and xs.max() > 30.0:
                pytest.fail("triangle spans the NaN hole in x")

    def test_winding_is_consistent(self):
        tg, _ = grid()
        tg = tg + 0.01 * np.arange(tg.size).reshape(tg.shape)  # slight relief
        verts, faces = triangulate_heightfield(tg)
        tri = verts[faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        # uniform orientation (renderer shading + export need consistency)
        assert np.all(n[:, 2] > 0) or np.all(n[:, 2] < 0)


class TestFaultBuilders:
    def test_curtain_shape_and_label(self):
        trace = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)]
        fault = build_fault_curtain_from_trace("F1", trace, 100.0, 300.0)
        assert fault.representation == "curtain_2p5d"
        assert fault.verts.shape == (6, 3)  # 3 trace points x 2 levels
        assert len(fault.faces) == 2 * (3 - 1)
        assert fault.z_extent == (100.0, 300.0)

    def test_curtain_requires_descreasing_z(self):
        with pytest.raises(DomainError, match="below"):
            build_fault_curtain_from_trace("F", [(0, 0), (1, 1)], 300.0, 100.0)

    def test_mesh_fault(self):
        v = np.array([[0, 0, 0], [10, 0, 5], [0, 10, 3]])
        f = np.array([[0, 1, 2]])
        fault = build_fault_from_mesh("F2", v, f, strike_dip=(45.0, 60.0))
        assert fault.representation == "triangulated_3d"
        assert fault.strike_dip == (45.0, 60.0)


class TestVolumeShell:
    def test_flat_shell_is_closed_with_walls(self):
        top, base = make_horizons()
        # 5x5 cells of 10 m; a 0..40 box cleanly contains the 4x4 cells whose
        # centres are at 5..35.
        boundary = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
        vol, qc = build_volume_shell(
            top, base, boundary, object_id="volume:sand", name="Sand"
        )
        assert qc["closed"] is True, qc
        assert qc["column_count"] == 16
        assert qc["dropped_crossed"] == 0
        assert qc["min_thickness"] == pytest.approx(50.0)
        tri = vol.verts[vol.faces]
        areas = 0.5 * np.linalg.norm(
            np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1
        )
        assert areas.sum() > 0

    def test_crossed_columns_dropped_and_counted(self):
        tg, bg = grid()
        bg[1:3, 1:3] = tg[1:3, 1:3] - 10.0  # base ABOVE top in depth semantics
        top = build_horizon_from_grid("Top", tg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        base = build_horizon_from_grid("Base", bg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        boundary = [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)]
        vol, qc = build_volume_shell(top, base, boundary, object_id="volume:v")
        # 4 crossed NODES invalidate the 3x3 = 9 cells touching any of them
        assert qc["dropped_crossed"] == 9
        assert qc["column_count"] == 25 - 9
        assert qc["closed"] is True

    def test_nan_area_dropped(self):
        tg, bg = grid()
        tg[3:, 3:] = np.nan
        bg[3:, 3:] = np.nan
        top = build_horizon_from_grid("Top", tg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        base = build_horizon_from_grid("Base", bg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        boundary = [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)]
        vol, qc = build_volume_shell(top, base, boundary, object_id="volume:v")
        assert qc["dropped_nan"] == 9
        assert qc["closed"] is True

    def test_mismatched_grids_rejected(self):
        top, base = make_horizons()
        tg2, _ = grid(nI=5, nX=5)
        other = build_horizon_from_grid("T2", tg2, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        with pytest.raises(DomainError, match="share"):
            build_volume_shell(other, base, [(0, 0), (10, 0), (10, 10), (0, 10)], object_id="volume:x")

    def test_provenance_carries_source_versions(self):
        tg, bg = grid()
        prov = __import__(
            "paleo_workbench.viz.geomodel.domain", fromlist=["Provenance"]
        ).Provenance(source_version_ids=("hv1",))
        top = build_horizon_from_grid(
            "Top", tg, origin=(0.0, 0.0), spacing=(10.0, 10.0), provenance=prov
        )
        base = build_horizon_from_grid(
            "Base", bg, origin=(0.0, 0.0), spacing=(10.0, 10.0), provenance=prov
        )
        vol, _ = build_volume_shell(
            top, base, [(0, 0), (60, 0), (60, 60), (0, 60)], object_id="volume:v"
        )
        assert set(vol.provenance.source_version_ids) == {"hv1"}
        assert vol.top_id == top.object_id and vol.base_id == base.object_id


class TestColumnarHexMesh:
    def test_hex_counts_and_bounds(self):
        top, base = make_horizons()
        boundary = [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)]
        nodes, hexes, info = build_columnar_hex_mesh(
            top, base, boundary, n_layers=4
        )
        assert info["n_cells"] == 25  # 5x5 lattice cells
        assert info["n_hexes"] == 25 * 4
        assert len(hexes) == info["n_hexes"]
        assert len(nodes) == 25 * 5 * 4
        # every hex references valid nodes, positive volume-ish ordering
        assert hexes.min() >= 0
        assert hexes.max() < len(nodes)
        assert info["skipped_crossed"] == 0

    def test_crossed_skipped(self):
        tg, bg = grid()
        bg[2, 2] = tg[2, 2] - 5.0  # crosses cell (1,1) and neighbours
        top = build_horizon_from_grid("Top", tg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        base = build_horizon_from_grid("Base", bg, origin=(0.0, 0.0), spacing=(10.0, 10.0))
        boundary = [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)]
        _, _, info = build_columnar_hex_mesh(top, base, boundary)
        assert info["skipped_crossed"] == 4

    def test_hex_geometry_convex_column(self):
        top, base = make_horizons(dtype="dipping")
        boundary = [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)]
        nodes, hexes, _ = build_columnar_hex_mesh(top, base, boundary, n_layers=2)
        h = hexes[0]
        # bottom loop z <= top loop z (depth grows downward)
        z_lo = nodes[h[0:4], 2].mean()
        z_hi = nodes[h[4:8], 2].mean()
        assert z_hi >= z_lo
        # each loop interpolates the SAME four corners top→base: the layer
        # fraction scales (base - top) per corner, so per-corner offset from
        # the top surface is proportional across loops.
        lo, hi = nodes[h[0:4]], nodes[h[4:8]]
        assert np.allclose(lo[:, :2], hi[:, :2])
        assert np.all(hi[:, 2] >= lo[:, 2] - 1e-9)
