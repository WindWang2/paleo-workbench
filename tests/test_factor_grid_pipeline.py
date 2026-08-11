"""Stage-3: artifact-first payload + warm artifact cache + no eager legacy lists."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.catalog.grid_artifact import (
    FACTOR_GRID_ARTIFACT_VERSION,
    read_grid_artifact,
    write_grid_artifact,
)
from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    factor_grid_result_for_task,
    live_factor_grid_cache_stats,
    persist_factor_grid_artifacts,
    reset_artifact_load_counter,
    store_live_factor_grid,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _points() -> list[dict]:
    return [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
        {"x": 0.5, "y": 0.5, "value": 2.5},
    ]


def test_interp_does_not_eager_materialize_legacy_lists():
    task = FactorMapTask(
        name="t",
        target_horizon="H",
        factor_type="thickness",
        method="IDW",
        parameters={"sample_points": _points()},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=16)
    assert "grid_z" not in task.parameters
    assert "grid_x" not in task.parameters
    assert "grid_y" not in task.parameters
    live = factor_grid_result_for_task(task)
    assert live.shape == (16, 16)
    assert live.grid_z.dtype == np.float32


def test_artifact_repeated_reads_do_not_re_decompress(tmp_path: Path):
    result = FactorGridResult(
        grid_z=np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64),
        grid_x=np.linspace(0, 1, 64),
        grid_y=np.linspace(0, 1, 64),
        factor_name="t",
        algorithm_id="idw",
    )
    path = write_grid_artifact(result, tmp_path, "factor_a")
    task = FactorMapTask(
        id="factor_a",
        name="t",
        target_horizon="H",
        factor_type="t",
        method="IDW",
        parameters={},
        status="complete",
        grid_artifact_path=path.as_posix(),
    )
    clear_live_factor_grid(task.id)
    reset_artifact_load_counter()
    first = factor_grid_result_for_task(task)
    for _ in range(19):
        again = factor_grid_result_for_task(task)
        assert again.grid_z is first.grid_z or np.shares_memory(again.grid_z, first.grid_z) or (
            again.grid_z.base is first.grid_z or first.grid_z.base is again.grid_z
        ) or np.array_equal(again.grid_z, first.grid_z)
    stats = live_factor_grid_cache_stats()
    assert stats["artifact_physical_loads"] == 1


def test_project_save_writes_v2_artifact_without_inline_grid(tmp_path: Path):
    project = ProjectDocument.new("Pipe")
    task = FactorMapTask(
        name="t",
        target_horizon="H1",
        factor_type="thickness",
        method="IDW",
        parameters={"sample_points": _points()},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=12)
    project.factor_map_tasks.append(task)
    project_path = tmp_path / "demo.paleo.json"
    ProjectManager(project_path).save(project)
    assert "grid_z" not in (task.parameters or {})
    assert task.grid_artifact_path
    art = Path(task.grid_artifact_path)
    assert art.is_file()
    with np.load(art, allow_pickle=False) as data:
        assert "mask" not in data.files  # V2 drops redundant mask
        desc = str(data["__descriptor__"])
        assert f'"artifact_version": {FACTOR_GRID_ARTIFACT_VERSION}' in desc or (
            f'"artifact_version":{FACTOR_GRID_ARTIFACT_VERSION}' in desc
        )
    # Reopen without live cache should still load once then warm.
    clear_live_factor_grid(task.id)
    reset_artifact_load_counter()
    loaded = ProjectManager(project_path).load()
    t2 = loaded.factor_map_tasks[0]
    r1 = factor_grid_result_for_task(t2)
    r2 = factor_grid_result_for_task(t2)
    assert live_factor_grid_cache_stats()["artifact_physical_loads"] == 1
    np.testing.assert_array_equal(r1.grid_z, r2.grid_z)


def test_legacy_inline_still_reads_and_migrates_on_save(tmp_path: Path):
    project = ProjectDocument.new("Legacy")
    task = FactorMapTask(
        id="legacy1",
        name="legacy",
        target_horizon="H",
        factor_type="t",
        method="IDW",
        status="complete",
        parameters={
            "sample_points": _points(),
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[1.0, None], [3.0, 4.0]],
            "interp_backend": "idw",
        },
    )
    project.factor_map_tasks.append(task)
    # Readable via legacy path
    r = factor_grid_result_for_task(task)
    assert r.shape == (2, 2)
    assert np.isnan(r.grid_z[0, 1])
    project_path = tmp_path / "legacy.paleo.json"
    ProjectManager(project_path).save(project)
    assert "grid_z" not in task.parameters
    assert task.grid_artifact_path
    clear_live_factor_grid(task.id)
    reopened = factor_grid_result_for_task(task)
    assert reopened.shape == (2, 2)


def test_v1_artifact_still_readable(tmp_path: Path):
    """Write a V1-shaped compressed npz and ensure the reader accepts it."""
    import json

    z = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
    x = np.array([0.0, 1.0], dtype=np.float64)
    y = np.array([0.0, 1.0], dtype=np.float64)
    desc = {
        "factor_name": "old",
        "algorithm_id": "idw",
        "algorithm_parameters": {},
        "artifact_version": 1,
        "statistics": {
            "min": 1.0,
            "max": 3.0,
            "mean": 2.0,
            "std": 1.0,
            "valid_count": 3,
            "total_count": 4,
        },
    }
    target = tmp_path / "old.factor_grid.npz"
    with open(target, "wb") as fh:
        np.savez_compressed(
            fh,
            grid_z=z,
            grid_x=x,
            grid_y=y,
            mask=np.isfinite(z),
            __descriptor__=np.array(json.dumps(desc)),
        )
    loaded = read_grid_artifact(target)
    assert loaded.shape == (2, 2)
    assert np.isnan(loaded.grid_z[1, 1])
