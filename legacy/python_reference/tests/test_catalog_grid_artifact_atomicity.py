"""Issue #1149 — concurrent factor-grid artifact writes to the same target.

``write_grid_artifact`` used a FIXED temp name (``<target>.tmp``) with no
fsync, so two threads writing the same factor grid concurrently fought over
one temp file: one writer's bytes were silently discarded (or interleaved)
by the other's rename. The fix: a unique per-writer temp name, fsync before
``os.replace``, and a directory fsync after.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.catalog.grid_artifact import (
    GRID_ARTIFACT_SUFFIX,
    read_grid_artifact,
    write_grid_artifact,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _grid_result(value: float) -> FactorGridResult:
    return FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[value, value], [value, value]],
            "backend": "kriging",
            "grid": "2x2",
            "n_points": 4,
            "min": value,
            "max": value,
            "mean": value,
            "r_squared": 0.5,
        },
        factor_name=f"factor-{value}",
    )


def test_concurrent_writes_same_target_stay_intact(tmp_path: Path):
    """Two threads writing DIFFERENT grids to one target: the file afterwards
    holds exactly one of them, fully readable — never a torn hybrid."""
    results = [_grid_result(1.0), _grid_result(9.0)]
    errors: list[Exception] = []
    barrier = threading.Barrier(len(results))

    def writer(result: FactorGridResult) -> None:
        try:
            barrier.wait()
            for _ in range(20):
                write_grid_artifact(result, tmp_path, "shared")
        except Exception as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(result,)) for result in results
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    target = tmp_path / f"shared{GRID_ARTIFACT_SUFFIX}"
    loaded = read_grid_artifact(target)
    # The winner is one of the two writers, byte-consistent with its input.
    winners = [r for r in results if float(loaded.grid_z[0, 0]) == float(r.grid_z[0, 0])]
    assert len(winners) == 1
    np.testing.assert_array_equal(loaded.grid_z, winners[0].grid_z)
    # No temp leftovers.
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_write_grid_artifact_uses_unique_temp_names(tmp_path: Path, monkeypatch):
    """The temp path is unique per call (uuid suffix), not a fixed name."""
    import paleo_workbench.catalog.grid_artifact as grid_module

    seen: list[str] = []
    real_replace = grid_module.os.replace

    def tracking_replace(src, dst):
        seen.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(grid_module.os, "replace", tracking_replace)

    write_grid_artifact(_grid_result(2.0), tmp_path, "g")
    write_grid_artifact(_grid_result(3.0), tmp_path, "g")

    tmp_names = set(seen)
    assert len(tmp_names) == 2, f"temp names not unique: {tmp_names}"
    assert all(name.endswith(".tmp") for name in tmp_names)
    assert "g.factor_grid.npz.tmp" not in tmp_names


def test_failed_write_leaves_previous_artifact_intact(tmp_path: Path, monkeypatch):
    """An exception mid-write cleans its own temp file and never damages the
    existing artifact."""
    good = _grid_result(5.0)
    target = write_grid_artifact(good, tmp_path, "keep")
    before = target.read_bytes()

    import paleo_workbench.catalog.grid_artifact as grid_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("savez failed")

    monkeypatch.setattr(grid_module.np, "savez", _boom)
    with pytest.raises(RuntimeError):
        write_grid_artifact(_grid_result(6.0), tmp_path, "keep")

    assert target.read_bytes() == before
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_writes_are_fsynced_before_replace(tmp_path: Path, monkeypatch):
    """The payload file is fsynced (and the directory after the rename)."""
    import paleo_workbench.catalog.grid_artifact as grid_module

    fsynced: list[int] = []
    real_fsync = grid_module.os.fsync

    def tracking_fsync(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(grid_module.os, "fsync", tracking_fsync)

    write_grid_artifact(_grid_result(7.0), tmp_path, "synced")

    assert fsynced, "write_grid_artifact did not fsync the payload"
