"""Tests for managed factor-grid artifact persistence (npz sidecar)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.catalog.grid_artifact import (
    FACTOR_GRID_ARTIFACT_VERSION,
    read_grid_artifact,
    write_grid_artifact,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _constrained_result() -> FactorGridResult:
    return FactorGridResult.from_constrained_idw_dict(
        {
            "grid_x": [0.0, 1.0, 2.0],
            "grid_y": [10.0, 11.0],
            "grid_z": [[1.0, float("nan"), 3.0], [4.0, 5.0, 6.0]],
            "backend": "约束IDW",
            "method": "约束IDW",
            "grid_n": 3,
            "n_points": 4,
            "n_break_lines": 1,
            "n_direction_lines": 2,
            "min": 1.0,
            "max": 6.0,
            "mean": 3.8,
            "r_squared": 0.91,
            "boundary": [[0.0, 10.0], [2.0, 10.0], [2.0, 11.0], [0.0, 11.0], [0.0, 10.0]],
        },
        factor_name="孔隙度",
        crs="EPSG:32650",
        unit="%",
        source_refs=["asset-1/v-3"],
        run_ref="run-42",
    )


def _kriging_result() -> FactorGridResult:
    return FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[1.0, 2.0], [3.0, 4.0]],
            "backend": "kriging",
            "grid": "2x2",
            "n_points": 4,
            "min": 1.0,
            "max": 4.0,
            "mean": 2.5,
            "r_squared": 0.5,
            "grid_var": [[0.1, 0.2], [0.3, 0.4]],
            "variance_min": 0.1,
            "variance_max": 0.4,
        },
        factor_name="porosity",
    )


def test_round_trip_preserves_grid_and_metadata(tmp_path: Path):
    original = _constrained_result()
    path = write_grid_artifact(original, tmp_path, "pora-孔隙度")
    assert path.name.endswith(".factor_grid.npz")
    assert path.exists()

    loaded = read_grid_artifact(path)
    np.testing.assert_array_equal(loaded.grid_z, original.grid_z)
    np.testing.assert_array_equal(loaded.grid_x, original.grid_x)
    np.testing.assert_array_equal(loaded.grid_y, original.grid_y)
    assert loaded.factor_name == original.factor_name == "孔隙度"
    assert loaded.crs == "EPSG:32650"
    assert loaded.unit == "%"
    assert loaded.algorithm_id == "constrained_idw"
    assert loaded.source_refs == ["asset-1/v-3"]
    assert loaded.run_ref == "run-42"
    assert loaded.boundary is not None and len(loaded.boundary) == 5


def test_round_trip_preserves_nodata_and_stats(tmp_path: Path):
    original = _constrained_result()
    loaded = read_grid_artifact(write_grid_artifact(original, tmp_path, "p"))
    # NaN preserved as nodata.
    assert math.isnan(float(loaded.grid_z[0, 1]))
    assert loaded.statistics.valid_count == original.statistics.valid_count == 5
    assert loaded.statistics.min == original.statistics.min
    assert loaded.statistics.max == original.statistics.max


def test_kriging_variance_grid_round_trips(tmp_path: Path):
    original = _kriging_result()
    loaded = read_grid_artifact(write_grid_artifact(original, tmp_path, "k"))
    assert loaded.variance_grid is not None
    np.testing.assert_array_equal(loaded.variance_grid, original.variance_grid)
    assert loaded.algorithm_parameters.get("variance_min") == 0.1


def test_descriptor_is_embedded_and_versioned(tmp_path: Path):
    original = _constrained_result()
    path = write_grid_artifact(original, tmp_path, "p")
    with np.load(path, allow_pickle=False) as data:
        import json

        descriptor = json.loads(str(data["__descriptor__"]))
    assert descriptor["artifact_version"] == FACTOR_GRID_ARTIFACT_VERSION
    assert descriptor["crs"] == "EPSG:32650"
    assert "grid_z" not in descriptor  # arrays live in the npz, not the descriptor


def test_write_is_atomic_on_existing_file(tmp_path: Path):
    original = _constrained_result()
    path = write_grid_artifact(original, tmp_path, "p")
    first_bytes = path.read_bytes()
    # Rewrite: must replace atomically, not leave a .tmp behind.
    write_grid_artifact(original, tmp_path, "p")
    assert path.exists()
    assert not (tmp_path / "p.factor_grid.npz.tmp").exists()
    assert path.read_bytes() == first_bytes  # deterministic compressed payload


def test_read_missing_artifact_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_grid_artifact(tmp_path / "nope.factor_grid.npz")


def test_all_nodata_artifact_descriptor_stays_strict_json(tmp_path: Path):
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[None, None], [None, None]],
            "backend": "idw",
        },
        factor_name="empty",
    )
    path = write_grid_artifact(result, tmp_path, "empty")
    with np.load(path, allow_pickle=False) as data:
        import json

        descriptor = json.loads(str(data["__descriptor__"]))
    assert descriptor["statistics"]["valid_count"] == 0
    assert descriptor["statistics"]["min"] is None
