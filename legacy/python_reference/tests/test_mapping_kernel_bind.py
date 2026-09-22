"""Optional pwb_mapping_kernel C++ extension (CONV-20) — parity tests.

Skipped entirely when the pybind11 module is not importable (then the facade
is HAS_CPP=False and everything runs pure Python — the pre-extension state).
When built, the facade functions must be numeric drop-ins for the
pure-Python implementations on the same datasets (grid max-abs within the
mapping_kernel oracle tolerances), and the pure-Python path must remain
reachable (fallback dispatch).
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

import paleo_workbench.mapping.geological_pipeline as gp
from paleo_workbench.mapping.geological_pipeline import native_bind
from paleo_workbench.mapping.geological_pipeline.interpolator import (
    interpolate_factor as py_interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.well_prediction_surface import (
    WellFaciesPoint,
    nearest_neighbor_class_grid as py_nearest_neighbor_class_grid,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
)

pytestmark = pytest.mark.skipif(
    not native_bind.HAS_CPP,
    reason="pwb_mapping_kernel C++ extension not installed",
)

IDW_TOL = 1e-6
KRIGE_TOL = 1e-4
AXIS_TOL = 1e-12


@pytest.fixture
def no_geoviz(monkeypatch):
    """Pin the geoviz-absent state so both paths share the grid-OLS estimator.

    ``sys.modules["geoviz"] = None`` makes every ``from geoviz import ...``
    raise ImportError — the golden-baseline convention
    (docs/development/geopipeline-v12). The facade probe's cache is reset so
    it re-evaluates under the pin (the pure path probes fresh per call);
    both sides therefore see the same absent state and kriging parity is
    kernel (C++) vs numpy-grid-OLS (Python) — exactly the pair the frozen
    oracle pins. Without the pin (geoviz importable) plain kriging stays on
    the pure engine path by design (see the estimator-gate test).
    """
    monkeypatch.setitem(sys.modules, "geoviz", None)
    monkeypatch.setattr(native_bind, "_GEOVIZ_AVAILABLE", None)


def _wells8() -> GeologicalFactorDataset:
    pts = [
        (114.10, 22.50, 18.5), (114.25, 22.52, 22.3), (114.38, 22.48, 15.2),
        (114.15, 22.65, 24.1), (114.30, 22.68, 19.8), (114.42, 22.62, 12.4),
        (114.20, 22.80, 26.5), (114.35, 22.82, 21.0),
    ]
    ds = GeologicalFactorDataset(factor_name="porosity", unit="%")
    for i, (x, y, z) in enumerate(pts):
        ds.add_point(GeologicalFactor(
            name="porosity", value=z, x=x, y=y, unit="%",
            well_id=f"W{i}", well_name=f"W{i}",
        ))
    return ds


def _unit() -> GeologicalFactorDataset:
    pts = [
        (0.0, 0.0, 1.0), (10.0, 0.0, 3.0), (0.0, 8.0, 2.0),
        (10.0, 8.0, 4.0), (4.0, 3.0, 2.5), (7.0, 6.0, 3.5),
    ]
    ds = GeologicalFactorDataset(factor_name="porosity", unit="%")
    for i, (x, y, z) in enumerate(pts):
        ds.add_point(GeologicalFactor(
            name="porosity", value=z, x=x, y=y, unit="%",
            well_id=f"W{i}", well_name=f"W{i}",
        ))
    return ds


def _assert_grids_match(facade, pure, *, tol, with_variance):
    np.testing.assert_allclose(facade.grid_x, pure.grid_x, atol=AXIS_TOL, rtol=0)
    np.testing.assert_allclose(facade.grid_y, pure.grid_y, atol=AXIS_TOL, rtol=0)
    np.testing.assert_allclose(
        facade.grid_z, pure.grid_z, atol=tol, rtol=0, equal_nan=True)
    assert facade.algorithm_id == pure.algorithm_id
    assert facade.shape == pure.shape
    # Statistics are float64 reductions of the (max-abs-compared) float32
    # grids, so their tolerance matches the grid tolerance band.
    np.testing.assert_allclose(
        facade.statistics.min, pure.statistics.min,
        atol=tol, rtol=tol, equal_nan=True)
    np.testing.assert_allclose(
        facade.statistics.mean, pure.statistics.mean,
        atol=tol, rtol=tol)
    assert facade.statistics.valid_count == pure.statistics.valid_count
    if with_variance:
        assert (facade.variance_grid is None) == (pure.variance_grid is None)
        if pure.variance_grid is not None:
            np.testing.assert_allclose(
                facade.variance_grid, pure.variance_grid,
                atol=tol, rtol=0, equal_nan=True)


def test_has_cpp_true():
    assert native_bind.HAS_CPP is True
    assert gp.HAS_CPP is True
    import pwb_mapping_kernel  # noqa: F401


def test_kriging_estimator_gate_routes_engine_to_python():
    """With geoviz importable, plain kriging stays on the pure path (WLS
    engine estimator) — the facade must not substitute the kernel's
    grid-OLS estimator. Neighbourhood kriging still dispatches to C++."""
    ds = _wells8()
    plain = InterpolationOptions(method="kriging", grid_n=12)
    facade = native_bind.interpolate_factor(ds, plain)
    pure = py_interpolate_factor(ds, plain)
    assert facade.algorithm_parameters["variogram_fit"] == \
        pure.algorithm_parameters["variogram_fit"]
    nb = InterpolationOptions(method="kriging", grid_n=12, max_neighbors=3)
    nb_facade = native_bind.interpolate_factor(ds, nb)
    nb_pure = py_interpolate_factor(ds, nb)
    assert nb_facade.algorithm_parameters["variogram_fit"] == \
        nb_pure.algorithm_parameters["variogram_fit"] == "numpy-grid-ols"


def test_interpolate_idw_matches_python():
    ds = _wells8()
    opts = InterpolationOptions(method="idw", grid_n=16)
    _assert_grids_match(
        native_bind.interpolate_factor(ds, opts),
        py_interpolate_factor(ds, opts),
        tol=IDW_TOL, with_variance=False)


def test_interpolate_idw_knn_and_radius_match_python():
    ds = _unit()
    for opts in (
        InterpolationOptions(method="idw", grid_n=12, max_neighbors=3),
        InterpolationOptions(method="idw", grid_n=12, search_radius=2.0),
        InterpolationOptions(method="idw", grid_n=12, search_radius=2.0,
                             min_neighbors=3),
    ):
        _assert_grids_match(
            native_bind.interpolate_factor(ds, opts),
            py_interpolate_factor(ds, opts),
            tol=IDW_TOL, with_variance=False)


def test_interpolate_kriging_matches_python(no_geoviz):
    ds = _wells8()
    for model in ("spherical", "exponential", "gaussian"):
        opts = InterpolationOptions(method="kriging", grid_n=12,
                                    variogram_model=model)
        _assert_grids_match(
            native_bind.interpolate_factor(ds, opts),
            py_interpolate_factor(ds, opts),
            tol=KRIGE_TOL, with_variance=True)


def test_interpolate_kriging_neighborhood_matches_python(no_geoviz):
    ds = _unit()
    opts = InterpolationOptions(method="kriging", grid_n=12, max_neighbors=3)
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    _assert_grids_match(facade, pure, tol=KRIGE_TOL, with_variance=True)
    # The neighbourhood disclosure block is part of the numpy-path contract.
    assert facade.algorithm_parameters["neighborhood"]["max_neighbors"] == 3
    assert facade.algorithm_parameters["sample_points"] == \
        pure.algorithm_parameters["sample_points"]
    # Provenance disclosure: the kernel surface is the grid-OLS estimator,
    # never the geoviz WLS engine.
    assert facade.algorithm_parameters["degraded"] is True
    assert facade.algorithm_parameters["r_squared"] is None
    assert "numpy-grid-OLS" in facade.algorithm_parameters["degraded_reason"]


def _constant() -> GeologicalFactorDataset:
    pts = [(0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0), (1.0, 1.0, 5.0)]
    ds = GeologicalFactorDataset(factor_name="porosity", unit="%")
    for i, (x, y, z) in enumerate(pts):
        ds.add_point(GeologicalFactor(
            name="porosity", value=z, x=x, y=y, unit="%",
            well_id=f"W{i}", well_name=f"W{i}",
        ))
    return ds


def test_interpolate_kriging_special_datasets_match_python(no_geoviz):
    """Constant field, duplicate merge, unknown model, qc/nan filter."""
    dups = _unit()
    dups.add_point(GeologicalFactor(
        name="porosity", value=3.0, x=0.0, y=0.0, unit="%", well_id="D",
        well_name="D"))
    qc = _unit()
    qc.add_point(GeologicalFactor(
        name="porosity", value=float("nan"), x=3.0, y=3.0, unit="%",
        well_id="N", well_name="N"))
    qc.points[0] = GeologicalFactor(
        name=qc.points[0].name, value=qc.points[0].value,
        x=qc.points[0].x, y=qc.points[0].y, unit="%",
        well_id="W0", well_name="W0", qc_flag="bad")
    constant_global = _constant()
    constant_nb = _constant()
    cases = [
        (constant_global, InterpolationOptions(method="kriging", grid_n=10)),
        (constant_nb, InterpolationOptions(method="kriging", grid_n=10,
                                           max_neighbors=3)),
        (dups, InterpolationOptions(method="kriging", grid_n=10)),
        (qc, InterpolationOptions(method="idw", grid_n=10)),
        (_unit(), InterpolationOptions(method="kriging", grid_n=10,
                                       variogram_model="not-a-model")),
    ]
    constant_nb_facade = None
    for ds, opts in cases:
        facade = native_bind.interpolate_factor(ds, opts)
        pure = py_interpolate_factor(ds, opts)
        _assert_grids_match(
            facade, pure,
            tol=KRIGE_TOL if opts.method == "kriging" else IDW_TOL,
            with_variance=opts.method == "kriging")
        if ds is dups:
            assert facade.algorithm_parameters["duplicates_merged"] == \
                pure.algorithm_parameters["duplicates_merged"] == 1
        if ds is constant_nb:
            constant_nb_facade = facade
    # Constant field + neighbourhood: the disclosure carries the same
    # "every estimate is the sample mean" note the numpy path records.
    assert "constant field" in \
        constant_nb_facade.algorithm_parameters["neighborhood"]["note"]


def test_interpolate_knn_exact_hit_matches_python():
    """Exact sample hits inside the kNN (max_neighbors) path: a sample is
    placed exactly on a grid node of the extent, so the k-th-neighbour
    branch must apply the exact-hit override (the frozen oracle's
    idw_exact_hit covers the all-neighbours path; this covers kNN)."""
    ds = _unit()
    opts = InterpolationOptions(method="idw", grid_n=12, max_neighbors=3)
    probe = py_interpolate_factor(ds, opts)
    ds.add_point(GeologicalFactor(
        name="porosity", value=99.0, unit="%",
        x=float(probe.grid_x[4]), y=float(probe.grid_y[7]),
        well_id="HIT", well_name="HIT"))
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    _assert_grids_match(facade, pure, tol=IDW_TOL, with_variance=False)
    assert facade.grid_z[7, 4] == pytest.approx(99.0, abs=1e-5)
    assert pure.grid_z[7, 4] == pytest.approx(99.0, abs=1e-5)


def test_interpolate_idw_power_one_matches_python():
    ds = _wells8()
    opts = InterpolationOptions(method="idw", grid_n=12, power=1.0)
    _assert_grids_match(
        native_bind.interpolate_factor(ds, opts),
        py_interpolate_factor(ds, opts),
        tol=IDW_TOL, with_variance=False)


def test_interpolate_grid_n_clamp_matches_python():
    ds = _unit()
    opts = InterpolationOptions(method="idw", grid_n=3)
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    assert facade.shape == pure.shape == (10, 10)


def test_interpolate_domain_masked_zero_matches_python(no_geoviz):
    """A ring covering the whole extent masks nothing but still records."""
    ds = _unit()
    ring = [(-5.0, -5.0), (15.0, -5.0), (15.0, 15.0), (-5.0, 15.0),
            (-5.0, -5.0)]
    opts = InterpolationOptions(method="idw", grid_n=10, boundary=ring)
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    _assert_grids_match(facade, pure, tol=IDW_TOL, with_variance=False)
    assert facade.boundary == pure.boundary == [tuple(v) for v in ring]
    assert facade.algorithm_parameters["domain_masked_cells"] == \
        pure.algorithm_parameters["domain_masked_cells"] == 0


def test_interpolate_domain_boundary_matches_python(no_geoviz):
    ds = _unit()
    ring = [(1.0, 1.0), (9.0, 1.0), (9.0, 7.0), (1.0, 7.0), (1.0, 1.0)]
    for opts in (
        InterpolationOptions(method="idw", grid_n=14, boundary=ring),
        InterpolationOptions(method="kriging", grid_n=12, boundary=ring),
    ):
        facade = native_bind.interpolate_factor(ds, opts)
        pure = py_interpolate_factor(ds, opts)
        _assert_grids_match(
            facade, pure,
            tol=KRIGE_TOL if opts.method == "kriging" else IDW_TOL,
            with_variance=opts.method == "kriging")
        assert facade.boundary == pure.boundary
        assert facade.algorithm_parameters["domain_mask"] == "user_boundary"
        assert facade.algorithm_parameters["domain_masked_cells"] == \
            pure.algorithm_parameters["domain_masked_cells"]
        outside = ~np.isfinite(facade.grid_z)
        assert outside.any()


def test_interpolate_distance_policy_annotation_matches_python():
    ds = _unit()
    ds.crs = "EPSG:4326"
    opts = InterpolationOptions(method="idw", grid_n=10)
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    assert facade.algorithm_parameters["distance_policy"] == \
        pure.algorithm_parameters["distance_policy"] == "planar_degrees"
    assert facade.algorithm_parameters["distance_policy_annotation"] == \
        pure.algorithm_parameters["distance_policy_annotation"]


def test_interpolate_error_messages_match_python():
    empty = GeologicalFactorDataset(factor_name="porosity")
    collocated = GeologicalFactorDataset(factor_name="porosity")
    collocated.add_point(GeologicalFactor(
        name="porosity", value=1.0, x=1.0, y=1.0))
    collocated.add_point(GeologicalFactor(
        name="porosity", value=2.0, x=1.0, y=1.0))
    for ds in (empty, collocated):
        opts = InterpolationOptions(method="idw", grid_n=10)
        with pytest.raises(ValueError) as facade_exc:
            native_bind.interpolate_factor(ds, opts)
        with pytest.raises(ValueError) as pure_exc:
            py_interpolate_factor(ds, opts)
        assert str(facade_exc.value) == str(pure_exc.value)
    ds = _unit()
    opts = InterpolationOptions(
        method="idw", grid_n=10, boundary=[(0.0, 0.0), (1.0, 1.0)])
    with pytest.raises(ValueError) as facade_exc:
        native_bind.interpolate_factor(ds, opts)
    assert "boundary ring needs at least 3 vertices" in str(facade_exc.value)
    opts = InterpolationOptions(method="idw", grid_n=10,
                                distance_policy="furlongs")
    with pytest.raises(ValueError) as facade_exc:
        native_bind.interpolate_factor(ds, opts)
    with pytest.raises(ValueError) as pure_exc:
        py_interpolate_factor(ds, opts)
    assert str(facade_exc.value) == str(pure_exc.value)
    assert "distance_policy must be one of" in str(facade_exc.value)


def test_extract_factors_matches_python():
    records = [
        {"well_id": "W1", "x": 1.0, "y": 2.0, "POR": 18.5},
        {"well_id": "W2", "x": 2.0, "y": 3.0, "porosity": 22.1},
        {"well_id": "W3", "x": 3.0, "y": 4.0, "孔隙度": 15.3},
        {"well_id": "W4", "x": 0.0, "y": 0.0, "value": 9.0},
        {"well_id": "W5", "x": "N/A", "y": 1.0, "value": 1.0},
        {"well_id": "W6", "H_s": 4.0, "H_t": 8.0,
         "project_x": 5.0, "project_y": 6.0},
        {"id": "W7", "lng": 114.0, "lat": 22.5, "value": 3.0},
    ]
    facade = native_bind.extract_factors(records, "porosity")
    pure = GeologicalMappingPipeline().extract_factors(records, "porosity")
    assert facade.factor_name == pure.factor_name
    assert facade.unit == pure.unit
    assert [p.value for p in facade.points] == [p.value for p in pure.points]
    assert [(p.x, p.y) for p in facade.points] == \
        [(p.x, p.y) for p in pure.points]
    assert [p.well_id for p in facade.points] == \
        [p.well_id for p in pure.points]
    assert [p.unit for p in facade.points] == [p.unit for p in pure.points]
    assert facade.metadata == pure.metadata
    assert [p.metadata for p in facade.points] == \
        [p.metadata for p in pure.points]
    assert facade.metadata["skipped_invalid_coordinates"] == 1
    assert facade.metadata["coordinate_key_family_mixing"] is True


def test_extract_factor_branches_match_python():
    """Sub-dict factor_name key, nested alias, val-None skip, derived guards."""
    batches = [
        # sub-dict carries the factor name itself (not "value")
        ([{"well_id": "W1", "x": 1.0, "y": 2.0,
           "attributes": {"porosity": 11.5}}], "porosity", {}),
        # nested alias lookup inside attributes
        ([{"well_id": "W1", "x": 1.0, "y": 2.0,
           "attributes": {"POR": 12.5}}], "porosity", {}),
        # coordinates present but no value anywhere -> skipped silently
        ([{"well_id": "W1", "x": 1.0, "y": 2.0, "unrelated": "x"}],
         "porosity", {}),
        # non-numeric value -> skipped, invalid counter untouched
        ([{"well_id": "W1", "x": 1.0, "y": 2.0, "value": "junk"}],
         "porosity", {}),
        # derived guards: H_t<=0 and inverted base/top both drop
        ([{"well_id": "W1", "x": 1.0, "y": 2.0, "H_s": 4.0, "H_t": 0.0},
          {"well_id": "W2", "x": 3.0, "y": 4.0, "base_depth": 50.0,
           "top_depth": 90.0}], "formation_thickness", {}),
        # empty records and non-dict records
        ([], "porosity", {}),
        (["not-a-record"], "porosity", {}),
        # target_horizon parameter and formation fallback
        ([{"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0,
           "formation": "Es3"},
          {"well_id": "W2", "x": 2.0, "y": 3.0, "value": 6.0}],
         "porosity", {"target_horizon": "Es3"}),
    ]
    for records, factor_name, kwargs in batches:
        facade = native_bind.extract_factors(records, factor_name, **kwargs)
        pure = GeologicalMappingPipeline().extract_factors(
            records, factor_name, **kwargs)
        assert [(p.x, p.y, p.value) for p in facade.points] == \
            [(p.x, p.y, p.value) for p in pure.points]
        assert [p.metadata for p in facade.points] == \
            [p.metadata for p in pure.points]
        assert facade.metadata == pure.metadata
        assert facade.unit == pure.unit
        assert facade.target_horizon == pure.target_horizon


def test_extract_factors_derived_matches_python():
    records = [{"well_id": "W1", "x": 1.0, "y": 2.0, "H_s": 4.0, "H_t": 8.0}]
    facade = native_bind.extract_factors(records, "砂地比")
    pure = GeologicalMappingPipeline().extract_factors(records, "砂地比")
    assert len(facade.points) == len(pure.points) == 1
    assert facade.points[0].value == pure.points[0].value == pytest.approx(50.0)
    assert facade.points[0].metadata == pure.points[0].metadata
    assert facade.metadata["derived_points"] == \
        pure.metadata["derived_points"] == 1


def test_extract_factors_mixed_family_warning(caplog):
    records = [
        {"well_id": "W1", "project_x": 1.0, "project_y": 2.0, "value": 5.0},
        {"well_id": "W2", "lng": 114.0, "lat": 22.5, "value": 6.0},
    ]
    with caplog.at_level("WARNING"):
        native_bind.extract_factors(records, "porosity")
    assert any(
        "mixed coordinate key families" in rec.message
        for rec in caplog.records)


def test_extract_factors_unit_authority_matches_python():
    records = [{"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0}]
    for kwargs in ({}, {"unit": ""}, {"unit": "m"}):
        facade = native_bind.extract_factors(records, "porosity", **kwargs)
        pure = GeologicalMappingPipeline().extract_factors(
            records, "porosity", **kwargs)
        assert facade.unit == pure.unit
    facade = native_bind.extract_factors(records, "sand_ratio")
    pure = GeologicalMappingPipeline().extract_factors(records, "sand_ratio")
    assert facade.unit == pure.unit == "%"


def test_nearest_neighbor_class_grid_matches_python():
    points = [
        WellFaciesPoint(x=1.0, y=1.0, facies="三角洲"),
        WellFaciesPoint(x=9.0, y=1.0, facies="滨浅湖"),
        WellFaciesPoint(x=5.0, y=8.0, facies="三角洲"),
    ]
    ring = [(2.0, 2.0), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0), (2.0, 2.0)]
    for grid_n, clip in ((5, None), (4, ring)):
        facade = native_bind.nearest_neighbor_class_grid(
            points, extent=(0.0, 0.0, 10.0, 9.0), grid_n=grid_n,
            clip_ring=clip)
        pure = py_nearest_neighbor_class_grid(
            points, extent=(0.0, 0.0, 10.0, 9.0), grid_n=grid_n,
            clip_ring=clip)
        np.testing.assert_allclose(
            facade[0], pure[0], rtol=0, atol=0.0, equal_nan=True)
        np.testing.assert_allclose(facade[1], pure[1], atol=AXIS_TOL, rtol=0)
        np.testing.assert_allclose(facade[2], pure[2], atol=AXIS_TOL, rtol=0)
        assert facade[3] == pure[3]


def test_nearest_neighbor_class_grid_tie_and_error():
    # Equidistant row must take the first-seen class (numpy argmin tie rule).
    points = [
        WellFaciesPoint(x=0.0, y=0.0, facies="A"),
        WellFaciesPoint(x=0.0, y=10.0, facies="B"),
    ]
    facade = native_bind.nearest_neighbor_class_grid(
        points, extent=(-5.0, -5.0, 5.0, 15.0), grid_n=3)
    pure = py_nearest_neighbor_class_grid(
        points, extent=(-5.0, -5.0, 5.0, 15.0), grid_n=3)
    np.testing.assert_array_equal(facade[0], pure[0])
    assert facade[3] == pure[3] == ("A", "B")
    with pytest.raises(ValueError) as facade_exc:
        native_bind.nearest_neighbor_class_grid(
            [], extent=(0.0, 0.0, 1.0, 1.0))
    assert str(facade_exc.value) == \
        "point-to-surface needs at least one well facies point"


def test_fallback_dispatch_pure_python(monkeypatch):
    """With the seam disabled the facade returns the pure-Python results."""
    monkeypatch.setattr(native_bind, "_kernel", None)
    ds = _wells8()
    opts = InterpolationOptions(method="idw", grid_n=12)
    facade = native_bind.interpolate_factor(ds, opts)
    pure = py_interpolate_factor(ds, opts)
    np.testing.assert_array_equal(facade.grid_z, pure.grid_z)
    assert native_bind.extract_factors(
        [{"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0}],
        "porosity",
    ).unit == GeologicalMappingPipeline().extract_factors(
        [{"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0}],
        "porosity",
    ).unit
    grid = native_bind.nearest_neighbor_class_grid(
        [WellFaciesPoint(x=1.0, y=1.0, facies="A")],
        extent=(0.0, 0.0, 2.0, 2.0), grid_n=4)
    assert grid[3] == ("A",)
