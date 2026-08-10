"""Unit tests for the unified :class:`FactorGridResult` contract.

These tests import only NumPy + the module under test, so they exercise the data layer
without requiring PySide6. They verify the two nodata encodings are normalised, the
shape contracts are enforced, statistics are correct, the legacy round-trip is
lossless, and the descriptor carries no inline grid arrays.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from paleo_workbench.workflow.factor_grid_result import (
    FactorGridResult,
    GridStatistics,
)


def _engine_dict() -> dict:
    """A 2x2 engine-style result with a None (non-finite) cell."""
    return {
        "grid_x": [0.0, 1.0],
        "grid_y": [10.0, 11.0],
        "grid_z": [[1.0, 2.0], [None, 4.0]],
        "backend": "idw",
        "grid": "2x2",
        "n_points": 3,
        "min": 1.0,
        "max": 4.0,
        "mean": 2.33,
        "r_squared": 0.9876,
    }


def _kriging_engine_dict() -> dict:
    return {
        "grid_x": [0.0, 1.0],
        "grid_y": [10.0, 11.0],
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
    }


def _constrained_dict() -> dict:
    """A 2x2 constrained-IDW adapter-style result with a NaN (non-finite) cell."""
    return {
        "grid_x": [0.0, 1.0],
        "grid_y": [10.0, 11.0],
        "grid_z": [[1.0, float("nan")], [3.0, 4.0]],
        "backend": "约束IDW",
        "method": "约束IDW",
        "grid_n": 2,
        "n_points": 3,
        "n_break_lines": 1,
        "min": 1.0,
        "max": 4.0,
        "mean": 2.66,
        "r_squared": 0.9,
        "boundary": [[0.0, 10.0], [1.0, 10.0], [1.0, 11.0], [0.0, 10.0]],
        "n_direction_lines": 2,
    }


# --- construction & nodata normalisation --------------------------------------


def test_engine_dict_normalises_none_to_nan():
    r = FactorGridResult.from_engine_dict(_engine_dict(), factor_name="porosity")
    assert r.shape == (2, 2)
    assert r.grid_z.dtype == np.float32
    # The None cell is now NaN (canonical nodata).
    assert math.isnan(float(r.grid_z[1, 0]))
    assert r.mask[1, 0] is np.False_  # type: ignore[comparison-overlap]
    assert bool(r.mask[0, 0]) is True


def test_constrained_dict_normalises_nan_passthrough():
    r = FactorGridResult.from_constrained_idw_dict(
        _constrained_dict(), factor_name="porosity"
    )
    assert math.isnan(float(r.grid_z[0, 1]))
    assert r.algorithm_id == "constrained_idw"
    assert r.boundary is not None and len(r.boundary) == 4
    assert r.algorithm_parameters["n_direction_lines"] == 2
    assert r.algorithm_parameters["n_break_lines"] == 1


def test_both_encodings_produce_identical_grid():
    """None (engine) and NaN (adapter) for the same logical cell must converge."""
    eng = FactorGridResult.from_engine_dict(
        {"grid_x": [0.0], "grid_y": [0.0], "grid_z": [[None]], "backend": "idw"},
        factor_name="f",
    )
    adr = FactorGridResult.from_constrained_idw_dict(
        {"grid_x": [0.0], "grid_y": [0.0], "grid_z": [[float("nan")]]},
        factor_name="f",
    )
    assert math.isnan(float(eng.grid_z[0, 0]))
    assert math.isnan(float(adr.grid_z[0, 0]))
    assert eng.mask.tolist() == adr.mask.tolist()


# --- statistics ---------------------------------------------------------------


def test_statistics_skip_nodata():
    r = FactorGridResult.from_engine_dict(_engine_dict(), factor_name="porosity")
    assert r.statistics.valid_count == 3
    assert r.statistics.total_count == 4
    assert r.statistics.min == 1.0
    assert r.statistics.max == 4.0
    assert pytest.approx(r.statistics.mean, rel=1e-5) == (1.0 + 2.0 + 4.0) / 3


def test_statistics_all_nodata_grid():
    r = FactorGridResult.from_constrained_idw_dict(
        {"grid_x": [0.0, 1.0], "grid_y": [0.0, 1.0],
         "grid_z": [[float("nan"), float("nan")], [float("nan"), float("nan")]]},
        factor_name="empty",
    )
    assert r.statistics.valid_count == 0
    assert r.statistics.total_count == 4
    assert math.isnan(r.statistics.min)


def test_kriging_variance_grid_preserved():
    r = FactorGridResult.from_engine_dict(
        _kriging_engine_dict(), factor_name="porosity"
    )
    assert r.variance_grid is not None
    assert r.variance_grid.shape == (2, 2)
    assert r.algorithm_parameters["variance_min"] == 0.1
    assert r.algorithm_parameters["variance_max"] == 0.4
    assert r.algorithm_id == "kriging"


# --- geometry / extent / crs --------------------------------------------------


def test_extent_and_axes():
    r = FactorGridResult.from_engine_dict(_engine_dict(), factor_name="f")
    assert r.width == 2 and r.height == 2
    assert r.extent == (0.0, 10.0, 1.0, 11.0)
    assert r.grid_x.tolist() == [0.0, 1.0]
    assert r.grid_y.tolist() == [10.0, 11.0]


def test_crs_is_explicit_and_never_guessed():
    r = FactorGridResult.from_engine_dict(_engine_dict(), factor_name="f")
    assert r.crs is None and r.crs_is_known is False
    r2 = FactorGridResult.from_engine_dict(
        _engine_dict(), factor_name="f", crs="EPSG:32650"
    )
    assert r2.crs_is_known is True


# --- validation ---------------------------------------------------------------


def test_shape_mismatch_grid_x_raises():
    bad = {"grid_x": [0.0, 1.0, 2.0], "grid_y": [0.0, 1.0],
           "grid_z": [[1.0, 2.0], [3.0, 4.0]], "backend": "idw"}
    with pytest.raises(ValueError):
        FactorGridResult.from_engine_dict(bad, factor_name="f")


def test_shape_mismatch_grid_y_raises():
    bad = {"grid_x": [0.0, 1.0], "grid_y": [0.0],
           "grid_z": [[1.0, 2.0], [3.0, 4.0]], "backend": "idw"}
    with pytest.raises(ValueError):
        FactorGridResult.from_engine_dict(bad, factor_name="f")


# --- serialisation ------------------------------------------------------------


def test_descriptor_has_no_grid_arrays_and_is_json_serialisable():
    r = FactorGridResult.from_engine_dict(_engine_dict(), factor_name="porosity")
    d = r.to_descriptor()
    assert "grid_z" not in d and "grid_x" not in d and "grid_y" not in d
    assert d["width"] == 2 and d["height"] == 2
    assert d["extent"] == [0.0, 10.0, 1.0, 11.0]
    assert d["statistics"]["valid_count"] == 3
    # Must round-trip through JSON (proves project/catalog persistence safety).
    json.loads(json.dumps(d))


def test_legacy_round_trip_is_lossless_for_finite_values():
    original = _engine_dict()
    r = FactorGridResult.from_engine_dict(original, factor_name="porosity")
    legacy = r.to_legacy_dict()
    # legacy grid_z uses None for the nodata cell.
    assert legacy["grid_z"][1][0] is None
    r2 = FactorGridResult.from_engine_dict(legacy, factor_name="porosity")
    # Finite values match exactly.
    np.testing.assert_array_equal(
        np.where(r2.mask, r2.grid_z, 0.0),
        np.where(r.mask, r.grid_z, 0.0),
    )
    assert r2.statistics.valid_count == r.statistics.valid_count


def test_legacy_task_parameters_adapter():
    params = {
        "grid_x": [0.0, 1.0],
        "grid_y": [10.0, 11.0],
        "grid_z": [[1.0, 2.0], [None, 4.0]],
        "interp_backend": "idw",
        "grid": "2x2",
        "power": 2.0,
        "sample_points": [[0.0, 10.0, 1.0], [1.0, 11.0, 4.0]],
    }
    r = FactorGridResult.from_legacy_task_parameters(
        params, factor_name="porosity", crs="EPSG:4326"
    )
    assert r.algorithm_id == "idw"
    assert r.crs == "EPSG:4326"
    assert r.algorithm_parameters["n_points"] == 2
    assert r.algorithm_parameters["power"] == 2.0
    assert math.isnan(float(r.grid_z[1, 0]))


def test_grid_statistics_to_dict_round_trip():
    s = GridStatistics.from_grid(np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))
    d = s.to_dict()
    assert d["valid_count"] == 4
    assert d["min"] == 1.0 and d["max"] == 4.0
    json.loads(json.dumps(d))
