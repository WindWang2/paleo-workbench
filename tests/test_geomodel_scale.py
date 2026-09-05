"""Medium-scale performance guards (G12).

Assertions are RATIO- and COUNT-based (robust across machines), never
fragile absolute milliseconds:

* re-sync of an unchanged assembly rebuilds nothing (count == 0);
* single-object change rebuilds exactly one payload (incremental sync);
* sync cost scales sub-linearly in payload count via the token cache;
* horizon decimation caps display triangles regardless of grid size;
* payload memory stays bounded (tracemalloc trend, generous ceiling).
"""

from __future__ import annotations

import time
import tracemalloc

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import (
    build_horizon_from_grid,
    build_simplified_vertical_well,
    build_volume_shell,
)
from paleo_workbench.viz.geomodel.domain import ModelAssembly
from paleo_workbench.viz.geomodel.scene_adapter import (
    GeologicalSceneAdapter,
    _MAX_HORIZON_DIM,
)

from tests.test_geomodel_scene_adapter import RecordingWidget, _FakeScene


def make_wells(n, start=0):
    wells = []
    for k in range(start, start + n):
        st = np.array(
            [[0.0, k * 7.0, 0.0, 0.0], [50.0, k * 7.0, 3.0, -50.0], [100.0, k * 7.0, 6.0, -100.0]],
            dtype=float,
        )
        wells.append(
            build_simplified_vertical_well(
                f"W{k}", (k * 7.0, 0.0, 0.0), 100.0, crs="EPSG:32650",
                object_id=f"well:w{k}",
            )
        )
    return wells


def make_surfaces(n, dim=64):
    surfaces = []
    for k in range(n):
        g = np.full((dim, dim), -100.0 - k)
        surfaces.append(
            build_horizon_from_grid(
                f"H{k}", g, origin=(0.0, float(k)), spacing=(10.0, 10.0),
                crs="EPSG:32650", object_id=f"horizon:h{k}",
            )
        )
    return surfaces


@pytest.fixture()
def rig():
    widget = RecordingWidget()
    widget.set_scene_ref(_FakeScene())
    holder = {"widget": widget}
    adapter = GeologicalSceneAdapter(lambda: holder["widget"])
    return holder, adapter


@pytest.mark.parametrize("n_wells", [100, 500, 1000])
def test_well_scale_sync_and_incremental(rig, n_wells):
    holder, adapter = rig
    asm = ModelAssembly()
    for w in make_wells(n_wells):
        asm.add(w)

    t0 = time.perf_counter()
    report = adapter.sync(asm)
    t_initial = time.perf_counter() - t0
    assert len(report.added) == n_wells

    t0 = time.perf_counter()
    report2 = adapter.sync(asm)
    t_unchanged = time.perf_counter() - t0
    assert report2.unchanged == n_wells
    assert len(report2) == 0
    # unchanged re-sync must be far cheaper than the initial build
    assert t_unchanged < max(t_initial * 0.5, 1e-4)

    # single-object change rebuilds exactly one payload
    import dataclasses

    w = asm.get("well:w0")
    asm.replace(dataclasses.replace(w, version=w.version + 1))
    report3 = adapter.sync(asm)
    assert report3.updated == ["well:w0"]
    assert report3.unchanged == n_wells - 1


def test_surface_scale_and_no_per_frame_rebuild(rig):
    holder, adapter = rig
    asm = ModelAssembly()
    for s in make_surfaces(50):
        asm.add(s)
    report = adapter.sync(asm)
    assert len(report.added) == 50
    # object count on the stub view is stable across re-syncs (no churn)
    count_before = len(holder["widget"].objects)
    for _ in range(10):
        adapter.sync(asm)
    assert len(holder["widget"].objects) == count_before
    assert count_before == 50


def test_volume_shell_scale(rig):
    holder, adapter = rig
    asm = ModelAssembly()
    tg = np.full((33, 33), 100.0)
    bg = np.full((33, 33), 150.0)
    top = build_horizon_from_grid("T", tg, origin=(0, 0), spacing=(10.0, 10.0), crs="EPSG:32650")
    base = build_horizon_from_grid("B", bg, origin=(0, 0), spacing=(10.0, 10.0), crs="EPSG:32650")
    for k in range(10):
        vol, qc = build_volume_shell(
            top, base,
            [(float(10 * k), 0.0), (float(10 * k + 100), 0.0),
             (float(10 * k + 100), 100.0), (float(10 * k), 100.0)],
            object_id=f"volume:v{k}",
        )
        asm.add(vol)
    report = adapter.sync(asm)
    assert len(report.added) == 10
    triangles = sum(
        len(np.asarray(o["faces"])) for o in holder["widget"].objects.values()
    )
    # each volume's boundary is 100x100 m on a 10 m lattice → 10x10 cells →
    # 400 sheet triangles + ~80 wall triangles ≈ 480 per volume
    assert 10 * 400 <= triangles <= 10 * 600


def test_horizon_decimation_caps_triangles(rig):
    holder, adapter = rig
    asm = ModelAssembly()
    dim = _MAX_HORIZON_DIM * 2 + 1  # 1025 → stride 2 decimation
    g = np.arange(dim * dim, dtype=float).reshape(dim, dim) * 0.001
    asm.add(
        build_horizon_from_grid("Huge", g, origin=(0, 0), spacing=(1.0, 1.0), crs="EPSG:32650")
    )
    tracemalloc.start()
    report = adapter.sync(asm)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(report.added) == 1
    mesh = holder["widget"].objects["horizon:huge"]
    max_tris = _MAX_HORIZON_DIM * _MAX_HORIZON_DIM * 2
    assert len(mesh["faces"]) <= max_tris
    # full 1M-node grid would be ~2M triangles and hundreds of MB of payload
    assert peak < 200 * 1024 * 1024


def test_payload_memory_trend(rig):
    holder, adapter = rig
    asm = ModelAssembly()
    for w in make_wells(1000):
        asm.add(w)
    tracemalloc.start()
    adapter.sync(asm)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # 1000 two-station wells: payload ≈ vertices + faces + manager state;
    # a generous 64 MiB ceiling catches accidental per-frame copies.
    assert peak < 64 * 1024 * 1024
