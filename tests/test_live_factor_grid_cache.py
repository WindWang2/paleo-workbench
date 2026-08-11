"""Live FactorGrid cache: byte budget, immutable sharing, geometry dedup."""

from __future__ import annotations

import os

import numpy as np
import pytest

from paleo_workbench.project import factor_grid_artifacts as fga
from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    factor_grid_result_for_task,
    live_factor_grid_cache_stats,
    store_live_factor_grid,
)
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _result(name: str, n: int = 8, value: float = 1.0) -> FactorGridResult:
    z = np.full((n, n), value, dtype=np.float32)
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    y = np.linspace(0.0, 1.0, n, dtype=np.float64)
    return FactorGridResult(
        grid_z=z,
        grid_x=x,
        grid_y=y,
        factor_name=name,
        algorithm_id="idw",
        algorithm_parameters={"geometry_id": f"shared-geo-{n}"},
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    # Drop every entry so tests are isolated.
    stats = live_factor_grid_cache_stats()
    # Clear by storing then removing known keys is awkward; re-import fresh state
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        fga._LIVE_FACTOR_GRIDS.clear()
        fga._LIVE_FACTOR_GRID_BYTES.clear()
        fga._LIVE_FACTOR_GRIDS_TOTAL_BYTES = 0
        fga._GEOMETRY_POOL.clear()
    yield
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        fga._LIVE_FACTOR_GRIDS.clear()
        fga._LIVE_FACTOR_GRID_BYTES.clear()
        fga._LIVE_FACTOR_GRIDS_TOTAL_BYTES = 0
        fga._GEOMETRY_POOL.clear()


def test_store_get_shares_frozen_arrays_no_defensive_copy():
    r = _result("a", n=16)
    store_live_factor_grid("t1", r)
    task = FactorMapTask(
        id="t1",
        name="t1",
        target_horizon="H",
        factor_type="a",
        method="IDW",
        parameters={},
        status="complete",
    )
    a = factor_grid_result_for_task(task)
    b = factor_grid_result_for_task(task)
    assert a.grid_z is b.grid_z
    assert a.grid_x is b.grid_x
    assert not a.grid_z.flags["WRITEABLE"]
    with pytest.raises(ValueError):
        a.grid_z[0, 0] = 99.0


def test_copied_is_writable_and_isolated():
    r = _result("a", n=8)
    store_live_factor_grid("t1", r)
    task = FactorMapTask(
        id="t1",
        name="t1",
        target_horizon="H",
        factor_type="a",
        method="IDW",
        parameters={},
        status="complete",
    )
    shared = factor_grid_result_for_task(task)
    private = shared.copied()
    assert private.grid_z.flags["WRITEABLE"]
    private.grid_z[0, 0] = 42.0
    assert shared.grid_z[0, 0] != 42.0


def test_geometry_shared_across_factors():
    r1 = _result("f1", n=12, value=1.0)
    r2 = _result("f2", n=12, value=2.0)
    store_live_factor_grid("a", r1)
    store_live_factor_grid("b", r2)
    ta = FactorMapTask(
        id="a", name="a", target_horizon="H", factor_type="f1", method="IDW", parameters={}
    )
    tb = FactorMapTask(
        id="b", name="b", target_horizon="H", factor_type="f2", method="IDW", parameters={}
    )
    ga = factor_grid_result_for_task(ta)
    gb = factor_grid_result_for_task(tb)
    assert ga.grid_x is gb.grid_x
    assert ga.grid_y is gb.grid_y
    assert ga.grid_z is not gb.grid_z
    assert float(gb.grid_z[0, 0]) == pytest.approx(2.0)


def test_byte_budget_evicts_lru(monkeypatch):
    # Tiny byte budget: each 64x64 float32 grid is 16 KiB + axes.
    monkeypatch.setattr(fga, "_LIVE_FACTOR_GRIDS_MAX", 10)
    monkeypatch.setattr(fga, "_LIVE_FACTOR_GRIDS_MAX_BYTES", 40_000)
    for i in range(6):
        store_live_factor_grid(f"t{i}", _result(f"f{i}", n=64, value=float(i)))
    stats = live_factor_grid_cache_stats()
    assert stats["entries"] < 6
    assert stats["total_bytes"] <= stats["max_bytes"] + 64 * 64 * 4  # one insert slack


def test_entry_cap_evicts(monkeypatch):
    monkeypatch.setattr(fga, "_LIVE_FACTOR_GRIDS_MAX", 2)
    monkeypatch.setattr(fga, "_LIVE_FACTOR_GRIDS_MAX_BYTES", 10**9)
    store_live_factor_grid("a", _result("a", n=4))
    store_live_factor_grid("b", _result("b", n=4))
    store_live_factor_grid("c", _result("c", n=4))
    assert live_factor_grid_cache_stats()["entries"] == 2
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        keys = set(fga._LIVE_FACTOR_GRIDS.keys())
    assert "a" not in keys
    assert "c" in keys


def test_clear_and_apply_roundtrip():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
    ]
    task = FactorMapTask(
        name="t",
        target_horizon="H1",
        factor_type="thickness",
        method="IDW",
        parameters={"sample_points": points},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=10)
    live = factor_grid_result_for_task(task)
    assert live.shape == (10, 10)
    assert "grid_z" not in (task.parameters or {})
    clear_live_factor_grid(task.id)
    # Without live cache or artifact / inline payload, legacy path fails.
    with pytest.raises((ValueError, KeyError, TypeError)):
        factor_grid_result_for_task(task)
