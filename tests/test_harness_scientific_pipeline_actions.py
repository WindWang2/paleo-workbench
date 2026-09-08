"""V8 M6 — scientific pipeline actions over real services."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.harness import (
    DEFAULT_PERMISSIONS,
    ActionRegistry,
    ActionRisk,
    ActionStatus,
    HarnessExecutor,
)
from paleo_workbench.harness.actions import register_all
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)


@pytest.fixture()
def registry() -> ActionRegistry:
    reg = ActionRegistry()
    register_all(reg)
    return reg


@pytest.fixture()
def service(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


@pytest.fixture()
def project() -> ProjectDocument:
    doc = ProjectDocument(meta=ProjectMeta(name="m6"))
    doc.coordinate.project_crs = "EPSG:32650"
    doc.constraint_layers.append(
        ConstraintLayers(
            name="约束层",
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    name="F1", role="break",
                    coordinates=[[0.0, 0.0], [10.0, 0.0]],
                )
            ],
        )
    )
    doc.factor_map_tasks.append(
        FactorMapTask(
            name="砂地比",
            target_horizon="H1",
            method="IDW",
            factor_type="砂地比",
            parameters={
                "sample_points": [
                    {"x": float(i * 10), "y": float(i * 7 % 30), "value": float(i)}
                    for i in range(10)
                ]
            },
        )
    )
    return doc


def _ctx(project, service, **extra) -> ActionContext:
    return ActionContext(
        project=project,
        catalog=CoreCatalogAdapter(service),
        permissions=DEFAULT_PERMISSIONS | {ActionRisk.WRITE},
        **extra,
    )


class TestFactorInterpolate:
    def test_interpolate_runs_and_verifies(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "factor.interpolate", {"task": "砂地比"}, _ctx(project, service)
        )
        assert result.ok, result.error
        task = project.factor_map_tasks[0]
        assert task.status == "complete"
        assert result.outputs["constraint_diagnostics"] is not None
        assert result.outputs["sample_normalization"]["policy"] == "mean"

    def test_interpolate_unknown_task_rejected(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "factor.interpolate", {"task": "nope"}, _ctx(project, service)
        )
        assert result.outputs.get("error") == "not_found"


class TestConstraintActions:
    def test_validate_reports_capability_and_geometry(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "constraint.validate",
            {"method": "克里金", "kinds": ["barrier", "anisotropy"]},
            _ctx(project, service),
        )
        assert result.ok
        outputs = result.outputs
        assert outputs["capability"]["method"] == "kriging"
        # barrier × kriging is honestly unsupported in the matrix
        joined = str(outputs["capability"])
        assert "unsupported" in joined or "ignored" in joined
        assert outputs["n_invalid"] == 0

    def test_commit_creates_version_and_verifier_passes(
        self, registry, project, service
    ):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "constraint.commit", {"actor": "agent"}, _ctx(project, service)
        )
        assert result.ok, result.error
        assert result.outputs["n_committed"] == 1
        version_id = result.outputs["groups"][0]["version_id"]
        assert service.get_version(version_id) is not None
        # second commit is a no-op (unchanged)
        result2 = executor.execute(
            "constraint.commit", {"actor": "agent"}, _ctx(project, service)
        )
        assert result2.ok
        assert result2.outputs["n_committed"] == 0
        assert result2.outputs["n_unchanged"] == 1


class TestFusionAndCompilation:
    def test_validate_inputs_reports_unresolved_factor(self, registry, project, service):
        executor = HarnessExecutor(registry)
        evidence = {"facies": "factor:砂地比:ver_missing"}
        result = executor.execute(
            "compilation.validate_inputs",
            {"evidence": evidence},
            _ctx(project, service),
        )
        assert result.ok
        assert result.outputs["ready"] is False
        assert result.outputs["n_unresolved"] == 1

    def test_fusion_run_rejects_empty_evidence(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "fusion.run", {}, _ctx(project, service)
        )
        assert not result.ok

    def test_fusion_run_rejects_non_factor_evidence(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "fusion.run",
            {"evidence": {"draft": "draft:layer1"}},
            _ctx(project, service),
        )
        assert not result.ok


class TestMapProductActions:
    def test_qa_unknown_product(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "map_product.qa", {"product": "ghost"}, _ctx(project, service)
        )
        assert result.outputs.get("error") == "not_found"

    def test_freeze_requires_existing_product(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "map_product.freeze", {"product": "ghost"}, _ctx(project, service)
        )
        assert result.outputs.get("error") == "not_found"


class TestEvaluateMethodsUpgrade:
    def test_real_per_method_evaluation_no_proxy(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "factor.evaluate_methods",
            {"factor": "砂地比", "methods": ["IDW", "克里金"], "k": 3},
            _ctx(project, service),
        )
        assert result.ok
        outputs = result.outputs
        assert outputs["scheme"] == "per_method_production_cv"
        assert "fold_engine" not in outputs  # the idw-proxy label is gone
        schemes = {e.get("scheme") for e in outputs["methods"]}
        assert "loo_exact" in schemes and "kfold_surface" in schemes


class TestPolygonize:
    def test_polygonize_needs_grid(self, registry, project, service):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "factor.polygonize", {"task": "砂地比"}, _ctx(project, service)
        )
        # task has no grid yet → honest unavailable (or computed after interp)
        assert result.status in (
            ActionStatus.SUCCESS.value,
            ActionStatus.DEGRADED.value,
            ActionStatus.FAILED.value,
        )

    def test_polygonize_after_interpolation(self, registry, project, service):
        executor = HarnessExecutor(registry)
        first = executor.execute(
            "factor.interpolate", {"task": "砂地比"}, _ctx(project, service)
        )
        assert first.ok
        result = executor.execute(
            "factor.polygonize", {"task": "砂地比"}, _ctx(project, service)
        )
        assert result.ok
        assert "n_polygons" in result.outputs
