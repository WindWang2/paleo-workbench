"""L3 — curve processing toolbox: pure kernels + catalog loop.

Numeric correctness of every new kernel (smoothing, median filter,
normalization, clip, unit conversion, resample, missing-interval
diagnostics, controlled derived-curve expression) and the DERIVED-version
loop through :func:`apply_curve_operation` (provenance, RAW untouched,
metadata preservation). The expression evaluator's security contract is
asserted adversarially: attribute access, subscripts, names outside the
curve set and keyword calls must raise — never evaluate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
lasio = pytest.importorskip("lasio")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.curve_interpretation import (
    CURVE_OPERATIONS,
    OPERATION_SCOPE,
    apply_curve_operation,
)
from paleo_workbench.workflow.curve_operations import (
    clip_outliers,
    conversion_factor,
    convert_values,
    evaluate_curve_expression,
    interp_nan_aware,
    median_filter_curve,
    missing_interval_report,
    moving_average,
    normalize_curve,
    resample_axis,
)


class TestKernels:
    def test_moving_average_is_nan_aware(self):
        values = np.array([1.0, 2.0, 3.0, np.nan, 5.0, 6.0])
        smoothed = moving_average(values, window=3)
        assert np.isfinite(smoothed[1])
        # Gap positions stay NaN — smoothing never fabricates samples.
        assert np.isnan(smoothed[3])
        # position 2 averages only the finite neighbours {2, 3} -> 2.5
        np.testing.assert_allclose(smoothed[2], 2.5)

    def test_median_filter_preserves_nan_positions(self):
        values = np.array([10.0, 10.0, 10.0, 500.0, 10.0, np.nan, 10.0])
        filtered = median_filter_curve(values, window=3)
        assert np.isnan(filtered[5])
        np.testing.assert_allclose(filtered[3], 10.0)  # spike rejected

    def test_normalize_zscore_and_minmax(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, np.nan])
        z = normalize_curve(values, method="zscore")
        np.testing.assert_allclose(np.nanmean(z[finite(z)]), 0.0, atol=1e-12)
        m = normalize_curve(values, method="minmax")
        np.testing.assert_allclose(np.nanmin(m[finite(m)]), 0.0)
        np.testing.assert_allclose(np.nanmax(m[finite(m)]), 1.0)
        with pytest.raises(ValueError, match="unknown normalization"):
            normalize_curve(values, method="magic")

    def test_clip_outliers_percentile_and_bounds(self):
        values = np.arange(100, dtype=float)
        values[50] = 1e6
        clipped = clip_outliers(values, percentile=5.0)
        assert clipped.max() < 1e5
        bounded = clip_outliers(np.array([-5.0, 0.0, 5.0]), lower=0.0, upper=1.0)
        np.testing.assert_allclose(bounded, [0.0, 0.0, 1.0])
        with pytest.raises(ValueError, match="needs lower/upper"):
            clip_outliers(np.array([1.0]))

    def test_unit_conversion_whitelist(self):
        np.testing.assert_allclose(
            convert_values(np.array([1000.0]), "m", "ft"), [1000.0 / 0.3048], rtol=1e-9
        )
        np.testing.assert_allclose(
            convert_values(np.array([2.0]), "g/cm3", "kg/m3"), [2000.0]
        )
        np.testing.assert_allclose(
            convert_values(np.array([100.0]), "us/m", "us/ft"), [30.48]
        )
        # Alias handling: "G/CC" is g/cc; unknown pairs and units refuse.
        assert conversion_factor("G/CC", "KG/M3") == 1000.0
        with pytest.raises(ValueError, match="no whitelisted conversion"):
            convert_values(np.array([1.0]), "api", "m")
        with pytest.raises(ValueError, match="unrecognized unit"):
            convert_values(np.array([1.0]), "blorts", "m")

    def test_resample_axis_regular_and_bounded(self):
        depth = np.array([1000.0, 1000.5, 1001.0, 1001.5])
        axis = resample_axis(depth, 1.0)
        np.testing.assert_allclose(axis, [1000.0, 1001.0])
        with pytest.raises(ValueError, match="positive"):
            resample_axis(depth, 0.0)

    def test_interp_keeps_gaps_and_range_limits(self):
        x = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, np.nan, 2.0, 3.0])
        # Finite samples are (0,0),(2,2),(3,3): linear between them, never
        # bridging with the NaN sample's stale value.
        out = interp_nan_aware(np.array([0.5, 1.5, 2.5]), x, y)
        np.testing.assert_allclose(out, [0.5, 1.5, 2.5])
        outside = interp_nan_aware(np.array([-1.0, 4.0]), x, y)
        assert np.all(np.isnan(outside))

    def test_missing_interval_report(self):
        depth = np.arange(1000.0, 1010.0, 0.5)
        values = np.ones_like(depth)
        values[4:8] = np.nan
        report = missing_interval_report(depth, values)
        assert report.total_samples == 20
        assert report.missing_samples == 4
        assert len(report.intervals) == 1
        np.testing.assert_allclose(report.intervals[0], (1002.0, 1003.5))
        assert report.missing_fraction == pytest.approx(0.2)


finite = np.isfinite


class TestExpressionEvaluator:
    def test_arithmetic_and_functions(self):
        variables = {"GR": np.array([10.0, 50.0]), "RT": np.array([1.0, 4.0])}
        out = evaluate_curve_expression("GR / max(RT, 2.0) + 1", variables)
        np.testing.assert_allclose(out, [10.0 / 2.0 + 1.0, 50.0 / 4.0 + 1.0])

    def test_where_and_clip(self):
        variables = {"GR": np.array([5.0, 200.0])}
        out = evaluate_curve_expression("where(GR > 100, 100, GR)", variables)
        np.testing.assert_allclose(out, [5.0, 100.0])

    def test_unknown_name_refused(self):
        with pytest.raises(ValueError, match="unknown curve name"):
            evaluate_curve_expression("DT + 1", {"GR": np.array([1.0])})

    def test_attribute_access_refused(self):
        with pytest.raises(ValueError, match="not allowed"):
            evaluate_curve_expression("GR.__class__", {"GR": np.array([1.0])})

    def test_subscript_refused(self):
        with pytest.raises(ValueError, match="not allowed"):
            evaluate_curve_expression("GR[0]", {"GR": np.array([1.0])})

    def test_disallowed_function_refused(self):
        with pytest.raises(ValueError, match="not allowed"):
            evaluate_curve_expression("open('x')", {"GR": np.array([1.0])})

    def test_keywords_refused(self):
        with pytest.raises(ValueError, match="keyword"):
            evaluate_curve_expression("clip(GR, a_min=0)", {"GR": np.array([1.0])})


class TestRegistryAndLoop:
    def test_registry_covers_the_toolbox(self):
        expected = {
            "depth_shift", "despike", "baseline_shift", "smooth", "median_filter",
            "normalize", "clip_outliers", "unit_conversion", "resample",
            "depth_unit_normalize", "derive_curve",
        }
        assert expected <= set(CURVE_OPERATIONS)
        assert set(OPERATION_SCOPE) == set(CURVE_OPERATIONS)

    def test_resample_creates_derived_with_metadata(self, tmp_path):
        service, version, _source = _catalog_with_two_curve_las(tmp_path)
        result = apply_curve_operation(
            service, version.id, operation="resample", curve="DEPT",
            parameters={"step": 1.0},
        )
        run = next(r for r in service.document.runs if r.id == result.run_id)
        assert run.operation == "curve_interpretation:resample"
        assert run.parameters["original_sample_count"] == 40
        assert run.parameters["new_step"] == 1.0
        derived = lasio.read(str(service.resolve_path(service.get_version(result.output_version_id))))
        depth = np.asarray(derived.curves["DEPT"].data, dtype=float)
        assert depth.size == 20
        np.testing.assert_allclose(np.diff(depth), 1.0)
        # Curves stay aligned with the new axis (values interpolated, no NaN at nodes).
        gr = np.asarray(derived.curves["GR"].data, dtype=float)
        assert np.all(np.isfinite(gr))

    def test_unit_conversion_records_provenance_and_header(self, tmp_path):
        service, version, _source = _catalog_with_two_curve_las(tmp_path)
        result = apply_curve_operation(
            service, version.id, operation="unit_conversion", curve="DEN",
            parameters={"from_unit": "g/cm3", "to_unit": "kg/m3"},
        )
        run = next(r for r in service.document.runs if r.id == result.run_id)
        assert run.parameters["unit_from"] == "g/cm3"
        assert run.parameters["unit_to"] == "kg/m3"
        derived = lasio.read(str(service.resolve_path(service.get_version(result.output_version_id))))
        den = np.asarray(derived.curves["DEN"].data, dtype=float)
        np.testing.assert_allclose(
            den, 1000.0 * np.linspace(2.4, 2.6, den.size), rtol=1e-6
        )
        assert str(derived.curves["DEN"].unit).lower() in ("kg/m3", "kg/m³")

    def test_depth_unit_normalize_ft_to_m(self, tmp_path):
        service, version, _source = _catalog_with_ft_depth_las(tmp_path)
        result = apply_curve_operation(
            service, version.id, operation="depth_unit_normalize", curve="DEPT",
            parameters={"target_unit": "m"},
        )
        derived = lasio.read(str(service.resolve_path(service.get_version(result.output_version_id))))
        depth = np.asarray(derived.curves["DEPT"].data, dtype=float)
        # ft → m round trip lands on the metre depths within sub-mm precision.
        np.testing.assert_allclose(depth, [1000.0, 1000.5, 1001.0], atol=1e-3)
        run = next(r for r in service.document.runs if r.id == result.run_id)
        # Provenance quotes the source header verbatim ("F" is LAS for feet).
        assert str(run.parameters["unit_from"]).lower() in ("f", "ft")

    def test_depth_unit_normalize_refuses_when_already_target(self, tmp_path):
        service, version, _source = _catalog_with_two_curve_las(tmp_path)
        with pytest.raises(ValueError, match="already in"):
            apply_curve_operation(
                service, version.id, operation="depth_unit_normalize", curve="DEPT",
                parameters={"target_unit": "m"},
            )

    def test_derive_curve_appends_new_curve(self, tmp_path):
        service, version, _source = _catalog_with_two_curve_las(tmp_path)
        result = apply_curve_operation(
            service, version.id, operation="derive_curve", curve="GR",
            parameters={
                "expression": "0.5 * (GR + 10)",
                "result_mnemonic": "GRHALF",
                "result_unit": "API",
            },
        )
        run = next(r for r in service.document.runs if r.id == result.run_id)
        assert run.parameters["expression"] == "0.5 * (GR + 10)"
        derived = lasio.read(str(service.resolve_path(service.get_version(result.output_version_id))))
        half = np.asarray(derived.curves["GRHALF"].data, dtype=float)
        gr = np.asarray(derived.curves["GR"].data, dtype=float)
        # lasio's text writer rounds to ~5 decimals; compare at write precision.
        np.testing.assert_allclose(half, 0.5 * (gr + 10.0), rtol=1e-5)

    def test_derive_curve_refuses_existing_mnemonic(self, tmp_path):
        service, version, _source = _catalog_with_two_curve_las(tmp_path)
        with pytest.raises(ValueError, match="already exists"):
            apply_curve_operation(
                service, version.id, operation="derive_curve", curve="GR",
                parameters={"expression": "GR", "result_mnemonic": "GR"},
            )

    def test_raw_bytes_untouched(self, tmp_path):
        service, version, source = _catalog_with_two_curve_las(tmp_path)
        before = source.read_bytes()
        apply_curve_operation(
            service, version.id, operation="smooth", curve="GR",
            parameters={"window": 5},
        )
        assert source.read_bytes() == before


def _catalog_with_two_curve_las(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    source = tmp_path / "raw.las"
    depths = np.arange(1000.0, 1020.0, 0.5)
    gr = 60.0 + 10.0 * np.sin(depths * 0.7)
    den = np.linspace(2.4, 2.6, depths.size)
    lines = [
        "~VERSION INFORMATION", "VERS. 2.0", "WRAP. NO",
        "~WELL",
        "STRT.M 1000.0 : Start depth", "STOP.M 1019.5 : Stop depth",
        "STEP.M 0.5 : Step", "NULL. -999.25 : Null value",
        "~CURVE INFORMATION",
        "DEPT.M : Depth", "GR.gAPI : Gamma Ray", "DEN.g/cm3 : Density",
        "~PARAMETER INFORMATION", "~OTHER", "~ASCII LOG DATA",
    ]
    for d, g, v in zip(depths, gr, den):
        lines.append(f"{d:12.6f} {g:12.6f} {v:12.6f}")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    version = service.import_raw(source, name="W-1 GR DEN", type="well_log")
    return service, version, source


def _catalog_with_ft_depth_las(tmp_path: Path):
    project = tmp_path / "proj" / "ft.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    source = tmp_path / "ft.las"
    # Exact ft equivalents of 1000.0/1000.5/1001.0 m (written at 6 decimals).
    depths = np.array([1000.0, 1000.5, 1001.0]) / 0.3048
    gr = np.array([80.0, 85.0, 90.0])
    lines = [
        "~VERSION INFORMATION", "VERS. 2.0", "WRAP. NO",
        "~WELL",
        "STRT.F 3280.839895 : Start depth", "STOP.F 3284.122922 : Stop depth",
        "STEP.F 1.640420 : Step", "NULL. -999.25 : Null value",
        "~CURVE INFORMATION",
        "DEPT.F : Depth", "GR.gAPI : Gamma Ray",
        "~PARAMETER INFORMATION", "~OTHER", "~ASCII LOG DATA",
    ]
    for d, g in zip(depths, gr):
        lines.append(f"{d:12.6f} {g:10.4f}")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    version = service.import_raw(source, name="W-FT GR", type="well_log")
    return service, version, source
