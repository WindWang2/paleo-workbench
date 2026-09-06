"""V6 §2–4 — well scientific contract: depth units, gaps, null provenance.

The primary rule under test: an undeclared/unknown depth unit must never be
silently treated as meters by any operation whose semantics depend on units;
gaps must survive processing; a derived file that introduces a null sentinel
the source never declared must record that policy in provenance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
lasio = pytest.importorskip("lasio")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.curve_interpretation import (
    UnknownDepthUnitError,
    apply_curve_operation,
    depth_shift,
)
from paleo_workbench.workflow.curve_operations import interp_gap_preserving
from paleo_workbench.workflow.well_science import (
    DepthUnitInfo,
    classify_depth_unit,
    depth_unit_of,
    require_depth_unit,
)


# ---------------------------------------------------------------------------
# Depth-unit classification (pure)
# ---------------------------------------------------------------------------


class TestClassifyDepthUnit:
    def test_declared_meter_tokens(self):
        for token in ("M", "m", "METER", "Meters", "MTR"):
            info = classify_depth_unit(token)
            assert info.unit == "m", token
            assert info.declared is True

    def test_declared_foot_tokens(self):
        for token in ("FT", "ft", "F", "FEET", "Foot"):
            info = classify_depth_unit(token)
            assert info.unit == "ft", token
            assert info.declared is True

    def test_absent_token_is_undeclared_unknown(self):
        info = classify_depth_unit("")
        assert info.unit is None
        assert info.declared is False

    def test_unrecognized_token_is_declared_but_unknown(self):
        info = classify_depth_unit("FURLONGS")
        assert info.unit is None
        assert info.declared is True  # the file said *something* we cannot honor
        assert info.raw == "FURLONGS"

    def test_none_token_is_undeclared_unknown(self):
        info = classify_depth_unit(None)
        assert info.unit is None
        assert info.declared is False


class TestRequireDepthUnit:
    def test_known_units_pass_through(self):
        assert require_depth_unit("m", operation="depth_shift") == "m"
        assert require_depth_unit("ft", operation="depth_shift") == "ft"
        assert require_depth_unit(classify_depth_unit("FT"), operation="x") == "ft"

    def test_unknown_raises_typed_error_naming_operation(self):
        with pytest.raises(UnknownDepthUnitError) as exc:
            require_depth_unit(None, operation="depth_shift")
        assert "depth_shift" in str(exc.value)

    def test_unrecognized_declared_unit_also_raises(self):
        with pytest.raises(UnknownDepthUnitError):
            require_depth_unit(classify_depth_unit("FURLONGS"), operation="resample_display")


# ---------------------------------------------------------------------------
# Detection from files + wrapper envelope
# ---------------------------------------------------------------------------


def _las_text(depth_unit: str | None, *, null_line: str | None = None) -> str:
    dept = "DEPT.M" if depth_unit == "m" else (
        "DEPT.FT" if depth_unit == "ft" else "DEPT."
    )
    unit_for_well = {"m": "M", "ft": "FT", None: ""}[depth_unit]
    lines = [
        "~VERSION INFORMATION",
        "VERS. 2.0",
        "WRAP. NO",
        "~WELL",
        f"STRT.{unit_for_well} 1000.0 : Start depth",
        f"STOP.{unit_for_well} 1002.0 : Stop depth",
        f"STEP.{unit_for_well} 0.5 : Step",
    ]
    if null_line:
        lines.append(null_line)
    lines += [
        "~CURVE INFORMATION",
        f"{dept} : Depth",
        "GR.gAPI : Gamma Ray",
        "~ASCII LOG DATA",
        "1000.0   60.0",
        "1000.5   61.0",
        "1001.0   62.0",
        "1001.5   63.0",
        "1002.0   64.0",
    ]
    return "\n".join(lines) + "\n"


class TestDetectDepthUnitFromFile:
    def test_feet_file_detected(self, tmp_path):
        from paleo_workbench.viz.well_log_load import detect_depth_unit

        path = tmp_path / "ft.las"
        path.write_text(_las_text("ft"), encoding="utf-8")
        assert detect_depth_unit(str(path)) == "ft"

    def test_meter_file_detected(self, tmp_path):
        from paleo_workbench.viz.well_log_load import detect_depth_unit

        path = tmp_path / "m.las"
        path.write_text(_las_text("m"), encoding="utf-8")
        assert detect_depth_unit(str(path)) == "m"

    def test_undeclared_unit_is_unknown_not_meters(self, tmp_path):
        """The V6 contract: no `or "m"` fallback — absence is unknown."""
        from paleo_workbench.viz.well_log_load import detect_depth_unit

        path = tmp_path / "nounit.las"
        path.write_text(_las_text(None), encoding="utf-8")
        assert detect_depth_unit(str(path)) is None

    def test_wrapper_carries_unknown_unit_explicitly(self, tmp_path):
        from paleo_workbench.viz.well_log_load import (
            WellLogDataWithDepthUnit,
            load_well_log_from_path,
        )

        path = tmp_path / "nounit2.las"
        path.write_text(_las_text(None), encoding="utf-8")
        data = load_well_log_from_path(str(path))
        assert data is not None
        assert isinstance(data, WellLogDataWithDepthUnit)
        assert data.depth_unit is None
        assert data.depth_unit_declared is False

    def test_declared_ft_wrapper_marks_declared(self, tmp_path):
        from paleo_workbench.viz.well_log_load import (
            WellLogDataWithDepthUnit,
            load_well_log_from_path,
        )

        path = tmp_path / "ft2.las"
        path.write_text(_las_text("ft"), encoding="utf-8")
        data = load_well_log_from_path(str(path))
        assert isinstance(data, WellLogDataWithDepthUnit)
        assert data.depth_unit == "ft"
        assert data.depth_unit_declared is True


class TestDepthUnitOf:
    def test_bare_document_is_unknown(self):
        class Bare:
            pass

        info = depth_unit_of(Bare())
        assert info.unit is None
        assert info.declared is False

    def test_wrapper_ft_is_declared(self):
        from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

        class Bare:
            pass

        info = depth_unit_of(WellLogDataWithDepthUnit(Bare(), "ft"))
        assert info.unit == "ft"
        assert info.declared is True

    def test_wrapper_none_is_unknown(self):
        from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

        class Bare:
            pass

        info = depth_unit_of(WellLogDataWithDepthUnit(Bare(), None))
        assert info.unit is None


# ---------------------------------------------------------------------------
# Gap-preserving resample interpolation
# ---------------------------------------------------------------------------


class TestInterpGapPreserving:
    def test_interior_gap_is_not_bridged(self):
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        y = np.array([1.0, 2.0, np.nan, np.nan, 5.0])
        new_x = np.arange(0.0, 4.01, 0.25)
        out = interp_gap_preserving(new_x, x, y)
        inside_gap = (new_x > 1.0) & (new_x < 4.0)
        assert np.isnan(out[inside_gap]).all(), "gap must survive resampling"
        np.testing.assert_allclose(out[new_x <= 1.0], new_x[new_x <= 1.0] + 1.0)
        np.testing.assert_allclose(out[new_x >= 4.0], 5.0)

    def test_outside_hull_stays_nan(self):
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([10.0, 20.0, 30.0])
        out = interp_gap_preserving(np.array([0.0, 1.5, 3.5]), x, y)
        assert np.isnan(out[0]) and np.isnan(out[2])
        assert out[1] == 15.0

    def test_two_runs_interpolate_within_runs_only(self):
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([0.0, 1.0, np.nan, 3.0, 4.0, 5.0])
        out = interp_gap_preserving(np.array([0.5, 2.5, 4.5]), x, y)
        assert out[0] == 0.5
        assert np.isnan(out[1])
        assert out[2] == 4.5

    def test_all_nan_returns_all_nan(self):
        out = interp_gap_preserving(
            np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([np.nan, np.nan])
        )
        assert np.isnan(out).all()


# ---------------------------------------------------------------------------
# depth_shift unit semantics
# ---------------------------------------------------------------------------


class TestDepthShiftUnits:
    def test_default_axis_meters_unchanged(self):
        depths = np.array([1000.0, 1000.5])
        np.testing.assert_allclose(depth_shift(depths, -1.5), [998.5, 999.0])

    def test_foot_axis_converts_meters_delta(self):
        depths = np.array([3000.0, 3001.0])
        shifted = depth_shift(depths, 3.048, axis_unit="ft")
        np.testing.assert_allclose(shifted, [3010.0, 3011.0])

    def test_unknown_axis_unit_raises_typed(self):
        with pytest.raises(UnknownDepthUnitError):
            depth_shift(np.array([1000.0, 1000.5]), 1.0, axis_unit=None)


# ---------------------------------------------------------------------------
# Operation loop: units, gaps, null provenance (catalog integration)
# ---------------------------------------------------------------------------


def _write_unit_las(path: Path, *, depth_unit: str | None, values=None, null_line: str | None = None) -> None:
    dept = {"m": "DEPT.M", "ft": "DEPT.FT", None: "DEPT"}[depth_unit]
    depths = np.arange(1000.0, 1002.01, 0.5)
    vals = values if values is not None else np.full(depths.size, 60.0)
    lines = _las_text(depth_unit, null_line=null_line).splitlines()
    # rebuild ascii block with provided values
    head: list[str] = []
    for line in lines:
        if line.startswith("~ASCII"):
            break
        head.append(line)
    head.append("~ASCII LOG DATA")
    for d, v in zip(depths, vals):
        head.append(f"{d:10.3f} {v:10.4f}")
    path.write_text("\n".join(head) + "\n", encoding="utf-8")


@pytest.fixture()
def catalog(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    return service, tmp_path


def _derived_path(service: DataCatalogService, result) -> str:
    return str(service.resolve_path(service.get_version(result.output_version_id)))


class TestOperationUnitSemantics:
    def test_depth_shift_on_foot_axis_shifts_in_axis_units(self, catalog):
        service, tmp_path = catalog
        source = tmp_path / "ft.las"
        _write_unit_las(source, depth_unit="ft")
        raw = service.import_raw(source, name="W-ft", type="well_log")

        result = apply_curve_operation(
            service,
            raw.id,
            operation="depth_shift",
            curve="DEPT",
            parameters={"delta_m": 3.048},
        )
        derived = lasio.read(_derived_path(service, result))
        axis = np.asarray(derived.curves[0].data, dtype=float)
        np.testing.assert_allclose(axis[0], 1010.0, atol=1e-6)  # 1000 ft + 10 ft

        run = next(r for r in service.document.runs if r.id == result.run_id)
        assert run.parameters["axis_unit"] == "ft"
        assert run.parameters["delta_m"] == 3.048

    def test_depth_shift_on_undeclared_unit_refuses(self, catalog):
        service, tmp_path = catalog
        source = tmp_path / "nounit.las"
        _write_unit_las(source, depth_unit=None)
        raw = service.import_raw(source, name="W-unknown", type="well_log")

        with pytest.raises(UnknownDepthUnitError):
            apply_curve_operation(
                service,
                raw.id,
                operation="depth_shift",
                curve="DEPT",
                parameters={"delta_m": 1.0},
            )

    def test_depth_unit_normalize_on_undeclared_unit_refuses(self, catalog):
        service, tmp_path = catalog
        source = tmp_path / "nounit2.las"
        _write_unit_las(source, depth_unit=None)
        raw = service.import_raw(source, name="W-unknown2", type="well_log")

        with pytest.raises(UnknownDepthUnitError):
            apply_curve_operation(
                service,
                raw.id,
                operation="depth_unit_normalize",
                curve="DEPT",
                parameters={"target_unit": "m"},
            )

    def test_resample_preserves_null_gaps(self, catalog):
        service, tmp_path = catalog
        vals = np.array([60.0, 61.0, -999.25, -999.25, 62.0])
        source = tmp_path / "gap.las"
        _write_unit_las(
            source,
            depth_unit="m",
            values=vals,
            null_line="NULL. -999.25 : Null value",
        )
        raw = service.import_raw(source, name="W-gap", type="well_log")

        result = apply_curve_operation(
            service,
            raw.id,
            operation="resample",
            curve="GR",
            parameters={"step": 0.25},
        )
        derived = lasio.read(_derived_path(service, result))
        gr = np.asarray(derived.curves["GR"].data, dtype=float)
        axis = np.asarray(derived.curves[0].data, dtype=float)
        # 1001.0 and 1001.5 were null in source; 1001.25 falls inside the gap
        inside = (axis > 1000.99) & (axis < 1001.51)
        assert inside.sum() == 3
        assert np.isnan(gr[inside]).all(), "resample must not bridge null gaps"


class TestNullPolicyProvenance:
    def test_injected_sentinel_is_recorded(self, catalog):
        """A derived LAS whose source declared no NULL must record the
        derivation-introduced sentinel policy in provenance (never silently
        redefine which samples are missing)."""
        service, tmp_path = catalog
        source = tmp_path / "nonull.las"
        _write_unit_las(source, depth_unit="m")  # no NULL line
        raw = service.import_raw(source, name="W-nonull", type="well_log")

        result = apply_curve_operation(
            service,
            raw.id,
            operation="baseline_shift",
            curve="GR",
            parameters={"delta": 1.0},
        )
        run = next(r for r in service.document.runs if r.id == result.run_id)
        policy = run.parameters.get("null_policy")
        assert policy, "derived run must record its null policy"
        assert policy["source"] == "derived_injected"
        assert policy["sentinel"] == -999.25

    def test_declared_sentinel_is_preserved_and_labeled(self, catalog):
        service, tmp_path = catalog
        source = tmp_path / "null9999.las"
        _write_unit_las(
            source,
            depth_unit="m",
            null_line="NULL. -9999.0 : Null value",
        )
        raw = service.import_raw(source, name="W-null9999", type="well_log")

        result = apply_curve_operation(
            service,
            raw.id,
            operation="baseline_shift",
            curve="GR",
            parameters={"delta": 1.0},
        )
        run = next(r for r in service.document.runs if r.id == result.run_id)
        policy = run.parameters.get("null_policy")
        assert policy["source"] == "declared"
        assert policy["sentinel"] == -9999.0
        derived = lasio.read(_derived_path(service, result))
        assert str(derived.well["NULL"].value) == "-9999.0"
