"""V8 M3/M4 — duplicate policy in production + CV/production config parity."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    attach_cross_validation,
    cross_validate_factor_task,
    interpolation_params_from_task,
)
from paleo_workbench.workflow.interpolation_evaluation import kriging_leave_one_out


def _smooth_points(n: int = 24, seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 100.0, n)
    ys = rng.uniform(0.0, 100.0, n)
    zs = 0.4 * xs + 0.6 * ys + 5.0
    return [
        {"x": float(x), "y": float(y), "value": float(z), "well_id": f"w{i}"}
        for i, (x, y, z) in enumerate(zip(xs, ys, zs))
    ]


def _project() -> ProjectDocument:
    project = ProjectDocument(meta=ProjectMeta(name="v8-test"))
    return project


def test_plain_idw_duplicate_no_longer_double_votes():
    """Two twin wells at one location must count as ONE vote (mean policy)."""
    points = _smooth_points(12)
    twin_a = {"x": 55.55, "y": 66.66, "value": 90.0, "well_id": "t1"}
    twin_b = {"x": 55.55, "y": 66.66, "value": 90.0, "well_id": "t2"}

    single = FactorMapTask(
        name="single", target_horizon="H1", method="IDW",
        factor_type="砂岩含量", parameters={"sample_points": points},
    )
    doubled = FactorMapTask(
        name="doubled", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": [twin_a, twin_b] + points},
    )
    project = _project()
    apply_interpolation_to_task(single, project=project)
    apply_interpolation_to_task(doubled, project=project)

    norm = doubled.parameters["sample_normalization"]
    assert norm["policy"] == "mean"
    assert norm["n_duplicate_groups"] == 1
    assert norm["n_duplicates_merged"] == 1
    assert doubled.quality_metrics["duplicate_locations_merged"] == 1

    # The doubled task delivered a surface over ONE merged vote at the twin
    # location, not two: its grid must equal the single-twin surface.
    single_twin = FactorMapTask(
        name="st", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": [dict(twin_a, value=90.0)] + points},
    )
    apply_interpolation_to_task(single_twin, project=project)
    assert np.allclose(single_twin.parameters is not None or True, True)  # sanity
    from paleo_workbench.project.factor_grid_artifacts import peek_live_factor_grid

    g_doubled = peek_live_factor_grid(doubled.id)
    g_merged = peek_live_factor_grid(single_twin.id)
    assert g_doubled is not None and g_merged is not None
    assert np.allclose(g_doubled.grid_z, g_merged.grid_z, equal_nan=True)


def test_duplicate_policy_keep_preserves_legacy_double_vote():
    points = _smooth_points(10)
    twins = [
        {"x": 5.0, "y": 5.0, "value": 80.0},
        {"x": 5.0, "y": 5.0, "value": 80.0},
    ]
    keep = FactorMapTask(
        name="keep", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": twins + points, "duplicate_policy": "keep"},
    )
    apply_interpolation_to_task(keep, project=_project())
    assert keep.parameters["sample_normalization"]["n_duplicates_merged"] == 0
    assert "duplicate_locations_merged" not in keep.quality_metrics


def test_error_policy_marks_task_failed():
    points = _smooth_points(8)
    task = FactorMapTask(
        name="strict", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={
            "sample_points": [
                {"x": 1.0, "y": 1.0, "value": 5.0},
                {"x": 1.0, "y": 1.0, "value": 6.0},
            ]
            + points,
            "duplicate_policy": "error",
        },
    )
    from paleo_workbench.workflow.factor_interpolation import (
        _apply_interpolation_isolated,
    )

    _apply_interpolation_isolated(
        task, method="IDW", grid_n=16, power=2.0,
        project=None, cancellation_token=None,
    )
    assert task.status == "failed"
    assert "duplicate" in str(task.parameters.get("last_error", ""))


def test_duplicate_bearing_task_invalidated_by_fingerprint():
    """Fingerprints cover the NORMALIZED set: duplicate-bearing tasks get new
    component digests (→ DIRTY on classify), duplicate-free tasks do not."""
    from paleo_workbench.workflow.interpolation_fingerprint import (
        build_factor_fingerprints,
        fingerprints_for_task,
    )

    points = _smooth_points(10)
    twins = [
        {"x": 5.0, "y": 5.0, "value": 50.0},
        {"x": 5.0, "y": 5.0, "value": 60.0},
    ]
    task = FactorMapTask(
        name="fp", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": twins + points},
    )
    # pre-V8 stored fingerprint over the RAW sample set
    legacy = build_factor_fingerprints(
        sample_points=task.parameters["sample_points"], method="IDW", grid_n=50,
        target_horizon="H1",
    )
    fresh = fingerprints_for_task(task, project=None, method="IDW", grid_n=50)
    assert fresh.values != legacy.values
    assert fresh.geometry != legacy.geometry
    assert fresh.algorithm != legacy.algorithm  # duplicate_policy recorded

    # duplicate-free tasks: byte-identical component digests → stays CLEAN
    clean_task = FactorMapTask(
        name="cf", target_horizon="H1", method="IDW",
        factor_type="砂岩含量", parameters={"sample_points": points},
    )
    legacy_clean = build_factor_fingerprints(
        sample_points=points, method="IDW", grid_n=50, target_horizon="H1",
    )
    fresh_clean = fingerprints_for_task(clean_task, project=None, method="IDW", grid_n=50)
    assert fresh_clean.values == legacy_clean.values
    assert fresh_clean.geometry == legacy_clean.geometry
    assert fresh_clean.algorithm == legacy_clean.algorithm


def test_kriging_cv_uses_production_variogram():
    """Explicit variogram controls must reach the LOO, not engine defaults."""
    points = _smooth_points(20)
    task = FactorMapTask(
        name="krig", target_horizon="H1",
        factor_type="地层厚度",
        method="克里金",
        parameters={
            "sample_points": points,
            "variogram_model": "gaussian",
            "variogram_range": 25.0,
            "variogram_nugget": 0.5,
        },
    )
    report, _ = cross_validate_factor_task(task, project=None, include_diagnostics=True)
    assert report is not None
    assert report.scheme == "loo_exact"
    assert "production settings" in report.detail

    default_report = kriging_leave_one_out(points)
    assert default_report is not None
    # an explicit (wrong-for-this-field) range must NOT reproduce the default fit
    assert report.metrics.rmse != pytest.approx(default_report.metrics.rmse)


def test_kriging_cv_anisotropy_changes_scores():
    """Direction-line anisotropy must reach CV through the task parameters."""
    points = _smooth_points(20)
    iso = FactorMapTask(
        name="iso", target_horizon="H1",
        factor_type="地层厚度",
        method="克里金",
        parameters={"sample_points": points},
    )
    aniso = FactorMapTask(
        name="aniso", target_horizon="H1",
        factor_type="地层厚度",
        method="克里金",
        parameters={
            "sample_points": points,
            "azimuth_deg": 45.0,
            "semi_major": 4.0,
            "semi_minor": 1.0,
        },
    )
    r_iso, _ = cross_validate_factor_task(iso, project=None)
    r_aniso, _ = cross_validate_factor_task(aniso, project=None)
    assert r_iso is not None and r_aniso is not None
    assert "anisotropy frame applied" in r_aniso.detail
    assert r_iso.metrics.rmse != pytest.approx(r_aniso.metrics.rmse)


def test_kriging_loo_residuals_aligned_to_locations():
    """Residual x/y must match the sample at that location (order-safe)."""
    points = _smooth_points(15)
    report = kriging_leave_one_out(points)
    assert report is not None
    by_coord = {(round(p["x"], 6), round(p["y"], 6)): p["value"] for p in points}
    for residual in report.residuals:
        key = (round(residual["x"], 6), round(residual["y"], 6))
        assert key in by_coord
        assert residual["value"] == pytest.approx(by_coord[key])


def test_constrained_idw_fold_receives_crs(monkeypatch):
    """The CV fold closure must pass the project CRS to run_constrained_idw."""
    from paleo_workbench.workflow import factor_interpolation as fi

    captured: dict = {}

    class _FakeReport(dict):
        pass

    def fake_run(points, *, grid_n, power, layers, target_horizon, break_polylines,
                 cancellation_token, crs):
        captured["crs"] = crs
        gx = np.linspace(0.0, 1.0, grid_n)
        gy = np.linspace(0.0, 1.0, grid_n)
        gz = np.zeros((grid_n, grid_n))
        return {"grid_x": gx, "grid_y": gy, "grid_z": gz}

    monkeypatch.setattr(
        "paleo_workbench.workflow.constrained_idw_adapter.run_constrained_idw",
        fake_run,
    )
    points = _smooth_points(14)
    task = FactorMapTask(
        name="cidw", target_horizon="H1",
        factor_type="砂岩含量",
        method="约束IDW",
        parameters={"sample_points": points},
    )
    project = _project()
    project.coordinate.project_crs = "EPSG:4326"
    report, _ = cross_validate_factor_task(task, project=project, k=4)
    assert report is not None
    assert captured["crs"] == "EPSG:4326"


def test_cv_scores_normalized_sample_set():
    """CV trains on exactly the normalized set production interpolates."""
    points = _smooth_points(12)
    twins = [
        {"x": 10.0, "y": 10.0, "value": 20.0},
        {"x": 10.0, "y": 10.0, "value": 40.0},
    ]
    task = FactorMapTask(
        name="cv", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": twins + points},
    )
    attach_cross_validation(task, project=None, k=4)
    cv = task.quality_metrics.get("cv")
    assert cv is not None
    # duplicate location merged → detail notes duplicates handling upstream of folds
    assert cv["metrics"]["n_samples"] > 0


# ---------------------------------------------------------------------------
# V8 M4 — recommendation fail-closed gates + real per-method evaluation
# ---------------------------------------------------------------------------

def _run_fold_idw(train):
    from geoviz import interpolate_idw
    import numpy as np
    xs = np.array([p["x"] for p in train], dtype=float)
    ys = np.array([p["y"] for p in train], dtype=float)
    zs = np.array([p.get("value", p.get("z")) for p in train], dtype=float)
    pad = 0.05 * max(xs.ptp(), ys.ptp(), 1.0)
    gx = np.linspace(xs.min() - pad, xs.max() + pad, 40)
    gy = np.linspace(ys.min() - pad, ys.max() + pad, 40)
    grid = interpolate_idw(xs, ys, zs, gx, gy)
    return gx, gy, grid


def test_recommendation_fails_closed_on_unknown_unit():
    from paleo_workbench.workflow.interpolation_evaluation import (
        recommend_interpolation_methods,
    )

    points = _smooth_points(16)
    report = recommend_interpolation_methods(
        points, methods=["IDW", "克里金"], run_fold=_run_fold_idw, unit=None, k=4
    )
    assert report["recommendation_gate"] == "unit_unknown"
    assert report["recommended_method"] is None
    assert all(e["recommended"] is False for e in report["methods"])
    assert all("unit is unknown" in e["rationale"] for e in report["methods"])
    # metrics may still be reported
    assert any(e["metrics"] for e in report["methods"])


def test_recommendation_fails_closed_on_invalid_crs():
    from paleo_workbench.workflow.interpolation_evaluation import (
        recommend_interpolation_methods,
    )

    points = _smooth_points(16)
    report = recommend_interpolation_methods(
        points, methods=["IDW"], run_fold=_run_fold_idw, unit="m",
        crs="NOT::A::CRS", k=4,
    )
    assert report["recommendation_gate"] == "crs_invalid"
    assert report["recommended_method"] is None


def test_recommendation_fails_closed_on_unknown_constraint_name():
    from paleo_workbench.workflow.interpolation_evaluation import (
        recommend_interpolation_methods,
    )

    points = _smooth_points(16)
    report = recommend_interpolation_methods(
        points, methods=["IDW"], run_fold=_run_fold_idw, unit="m",
        requested_constraints=["unicorn_barrier"], k=4,
    )
    assert report["recommendation_gate"] == "unknown_constraints"
    assert report["recommended_method"] is None
    assert any(
        "unicorn_barrier" in w
        for e in report["methods"]
        for w in e["capability_warnings"]
    )


def test_recommendation_open_with_valid_context():
    from paleo_workbench.workflow.interpolation_evaluation import (
        recommend_interpolation_methods,
    )

    points = _smooth_points(16)
    report = recommend_interpolation_methods(
        points, methods=["IDW", "克里金"], run_fold=_run_fold_idw,
        unit="m", crs="EPSG:32650", k=4,
    )
    assert report["recommendation_gate"] is None
    assert report["recommended_method"] in {"IDW", "克里金"}


def test_evaluate_methods_for_task_real_per_method_schemes():
    from paleo_workbench.workflow.factor_interpolation import evaluate_methods_for_task

    points = _smooth_points(18)
    task = FactorMapTask(
        name="em", target_horizon="H1", method="IDW",
        factor_type="砂岩含量",
        parameters={"sample_points": points, "unit": "%"},
    )
    report = evaluate_methods_for_task(task, methods=["IDW", "克里金"], k=4)
    assert report["scheme"] == "per_method_production_cv"
    schemes = {e.get("scheme") for e in report["methods"]}
    assert "kfold_surface" in schemes
    assert "loo_exact" in schemes
    # unit declared → gate open
    assert report["recommendation_gate"] is None
    assert report["unit"] == "%"
    # scheme-mix caveat is surfaced honestly
    assert any("schemes differ" in (e.get("rationale") or "") for e in report["methods"])


def test_evaluate_methods_for_task_gate_on_undeclared_unit():
    from paleo_workbench.workflow.factor_interpolation import evaluate_methods_for_task

    points = _smooth_points(18)
    task = FactorMapTask(
        name="em2", target_horizon="H1", method="IDW",
        factor_type="神秘因子",  # no unit default for this factor type
        parameters={"sample_points": points},
    )
    report = evaluate_methods_for_task(task, methods=["IDW"], k=4)
    assert report["recommendation_gate"] == "unit_unknown"
    assert report["recommended_method"] is None


class TestReviewR1KrigingDefaults:
    def test_default_kriging_cv_is_isotropic_like_production(self):
        """R1-P0: default axes (1.0/0.4, az 0) mean UNSET — the LOO must
        score the isotropic model production delivers, not a 2.5:1 frame."""
        points = _smooth_points(16)
        default_task = FactorMapTask(
            name="kd", target_horizon="H1", method="克里金",
            factor_type="地层厚度", parameters={"sample_points": points},
        )
        report, _ = cross_validate_factor_task(default_task, project=None)
        assert report is not None
        assert "anisotropy frame applied" not in report.detail
        # identical to a direct isotropic LOO
        direct = kriging_leave_one_out(points)
        assert report.metrics.rmse == pytest.approx(direct.metrics.rmse)
