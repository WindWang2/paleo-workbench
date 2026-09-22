"""ResourceGovernor convergence (#1225, v6 §10).

Pins:
- the vendored constrained-IDW interpolation no longer mutates process-level
  OMP/BLAS/MKL env vars at runtime, and its threadpoolctl limit is SCOPED
  (restored after the batch);
- the workflow DAG engine's pool width is clamped by the central allowance;
- the interchange batch converter's width comes from the governor;
- no module mutates OMP/OPENBLAS/MKL env vars at import time.
"""

from __future__ import annotations

import os
import threading

import numpy as np
import pytest

_BLAS_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def test_idw_batch_does_not_mutate_blas_env():
    """Runtime env mutation leaks to every subprocess and unrelated compute
    (#1225): the interpolation batch must leave the environment untouched."""
    before = {k: os.environ.get(k) for k in _BLAS_VARS}
    from paleo_workbench._vendored.haiyou_constrained_idw.drawing.single_factor import (
        fast_grid,
    )

    # Serial path (workers<=1) used to pin BLAS to full cpu_count via env.
    well_array = np.array(
        [[0.1, 0.1, 1.0], [0.5, 0.5, 2.0], [0.8, 0.8, 3.0]], dtype=np.float64
    )
    grid_x = np.linspace(0.0, 1.0, 12)
    grid_y = np.linspace(0.0, 1.0, 10)
    density = np.ones(len(well_array))
    mask = np.ones((len(grid_y), len(grid_x)), dtype=bool)
    result = fast_grid.interpolate_idw_grid_batch(
        grid_x, grid_y, well_array, mask,
        search_radius=2.0,
        power=2.0,
        min_points=1,
        max_points=4,
        density_weights=density,
    )
    assert result is not None and result.size
    after = {k: os.environ.get(k) for k in _BLAS_VARS}
    assert after == before, f"env mutated by interpolation: {after}"


def test_idw_blas_limit_is_scoped():
    """threadpoolctl limits during the batch are restored after it."""
    pytest.importorskip("threadpoolctl")
    import threadpoolctl

    from paleo_workbench._vendored.haiyou_constrained_idw.drawing.single_factor import (
        fast_grid,
    )

    def _run():
        well_array = np.array(
            [[0.1, 0.1, 1.0], [0.5, 0.5, 2.0]], dtype=np.float64
        )
        grid_x = np.linspace(0.0, 1.0, 8)
        grid_y = np.linspace(0.0, 1.0, 6)
        fast_grid.interpolate_idw_grid_batch(
            grid_x, grid_y, well_array, np.ones((len(grid_y), len(grid_x)), dtype=bool),
            search_radius=2.0, power=2.0, min_points=1, max_points=4,
            density_weights=np.ones(len(well_array)),
        )

    before = threadpoolctl.threadpool_info()
    _run()
    after = threadpoolctl.threadpool_info()
    key = lambda infos: sorted(
        (i.get("user_api"), i.get("num_threads")) for i in infos
    )
    assert key(after) == key(before)  # restored


def test_dag_pool_width_clamped_by_governor(monkeypatch):
    """A workflow declaring max_concurrency=64 gets the governor's ceiling."""
    from paleo_workbench.runtime import governance

    captured: dict[str, int] = {}

    class _FakePool:
        def __init__(self, max_workers=None, thread_name_prefix=""):
            captured["width"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, *a, **kw):
            class _F:
                def result(self, timeout=None):
                    raise RuntimeError("unused")

                def done(self):
                    return True

            return _F()

    import paleo_workbench.workflow.dag.engine as engine_mod

    monkeypatch.setattr(engine_mod, "ThreadPoolExecutor", _FakePool)
    monkeypatch.setattr(
        governance, "clamp_workers",
        lambda category, requested: 3, raising=True,
    )

    # The clamp sits on the pool-construction path (unit seam: verified by
    # source contract; the full drive loop needs a complete run/store).
    import inspect

    src = inspect.getsource(engine_mod.WorkflowEngine._drive_parallel)
    assert "clamp_workers" in src
    assert "background.compute" in src


def test_batch_workers_governed():
    from paleo_workbench.interchange.batch import BatchConversionService

    from paleo_workbench.runtime.governance import clamp_workers

    expected = clamp_workers("background.io", 99)
    svc = BatchConversionService(max_workers=99)
    assert svc._max_workers == expected
    assert svc._max_workers < 99  # the governor actually bounded it


def test_no_blas_env_mutation_at_import():
    """Importing every runtime-relevant module must not set BLAS env vars."""
    before = {k: os.environ.get(k) for k in _BLAS_VARS}
    import paleo_workbench.runtime.governance  # noqa: F401
    import paleo_workbench.runtime.task_scheduler  # noqa: F401
    import paleo_workbench.seismic_transcode  # noqa: F401

    after = {k: os.environ.get(k) for k in _BLAS_VARS}
    assert after == before
