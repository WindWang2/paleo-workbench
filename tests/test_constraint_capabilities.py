"""V6 §10 — method × constraint capability matrix + honest evaluation."""

from __future__ import annotations

import pytest

from paleo_workbench.workflow.constraint_capabilities import (
    ConstraintKind,
    ConstraintViolationError,
    capability_matrix,
    capabilities_for_method,
    evaluate_request,
)


ALL_KINDS = set(ConstraintKind)


class TestMatrix:
    def test_matrix_covers_every_method_and_kind(self):
        matrix = capability_matrix()
        assert set(matrix) >= {
            "idw", "constrained_idw", "kriging", "spline", "linear",
            "nearest", "rbf", "directional",
        }
        for row in matrix.values():
            assert set(row["constraints"]) == {k.value for k in ALL_KINDS}

    def test_constrained_idw_supports_all_four_core_kinds(self):
        caps = capabilities_for_method("constrained_idw")
        for kind in (ConstraintKind.BOUNDARY_MASK, ConstraintKind.BARRIER):
            support, _ = caps.for_kind(kind)
            assert support.value == "supported"

    def test_kriging_supports_no_constraints(self):
        caps = capabilities_for_method("克里金")  # UI label alias
        for kind in ALL_KINDS:
            support, _ = caps.for_kind(kind)
            assert support.value == "unsupported", kind

    def test_idw_supports_barriers_only(self):
        caps = capabilities_for_method("IDW")
        assert caps.for_kind(ConstraintKind.BARRIER)[0].value == "supported"
        for kind in ALL_KINDS - {ConstraintKind.BARRIER}:
            assert caps.for_kind(kind)[0].value == "unsupported", kind

    def test_unknown_method_raises(self):
        with pytest.raises(KeyError):
            capabilities_for_method("polynomial_chaos")


class TestEvaluateRequest:
    def test_kriging_with_faults_reports_unsupported_never_silent(self):
        app = evaluate_request("kriging", [ConstraintKind.BARRIER, ConstraintKind.DIRECTION])
        assert app.unsupported == ["barrier", "direction"]
        assert app.applied == []
        assert app.diagnostics, "every dropped constraint carries a diagnostic"

    def test_constrained_idw_applies_boundary_and_barrier(self):
        app = evaluate_request(
            "constrained_idw",
            [ConstraintKind.BOUNDARY_MASK, ConstraintKind.BARRIER],
        )
        assert app.applied == ["boundary_mask", "barrier"]
        assert app.unsupported == []
        assert app.as_dict()["applied_constraints"] == ["boundary_mask", "barrier"]

    def test_partial_support_is_labelled_partial_with_notes(self):
        app = evaluate_request("spline", [ConstraintKind.BOUNDARY_MASK])
        assert app.partial == ["boundary_mask"]
        assert any("hull" in d for d in app.diagnostics)

    def test_strict_mode_raises_on_unsupported(self):
        with pytest.raises(ConstraintViolationError, match="barrier"):
            evaluate_request("kriging", [ConstraintKind.BARRIER], strict=True)

    def test_strict_mode_passes_when_all_supported(self):
        app = evaluate_request(
            "constrained_idw",
            [ConstraintKind.BOUNDARY_MASK, ConstraintKind.BARRIER],
            strict=True,
        )
        assert app.applied

    def test_empty_request_is_clean(self):
        app = evaluate_request("kriging", [])
        assert app.as_dict() == {
            "method": "kriging",
            "requested_constraints": [],
            "applied_constraints": [],
            "partial_constraints": [],
            "ignored_constraints": [],
            "unsupported_constraints": [],
            "constraint_diagnostics": [],
        }
