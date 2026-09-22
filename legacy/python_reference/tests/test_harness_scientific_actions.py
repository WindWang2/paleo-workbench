"""V6 §19 — scientific harness actions over real services."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.harness.actions.scientific import register
from paleo_workbench.harness.registry import ActionRegistry


@pytest.fixture()
def registry():
    reg = ActionRegistry()
    register(reg)
    return reg


class TestRegistration:
    def test_five_scientific_actions_registered(self, registry):
        ids = {spec.action_id for spec in registry.specs()}
        assert {
            "well.describe_units",
            "seismic.describe_calibration",
            "factor.evaluate_methods",
            "map.describe_product",
            "map.publish",
        } <= ids

    def test_publish_is_write_risk(self, registry):
        spec = next(s for s in registry.specs() if s.action_id == "map.publish")
        assert spec.risk.value == "write" or str(spec.risk).upper() == "WRITE"


class TestUnitTruthAction:
    def test_unknown_unit_reported_as_null_not_meters(self, registry):
        from types import SimpleNamespace

        from paleo_workbench.harness.context import ActionContext

        context = ActionContext(project=SimpleNamespace(wells=[]))
        bare = SimpleNamespace(well_name="W-?")
        context.well_logs["well-x"] = bare
        spec = next(s for s in registry.specs() if s.action_id == "well.describe_units")
        out = spec.handler(context, {})
        assert out["wells"][0]["depth_unit"] is None
        assert out["wells"][0]["declared"] is False


class TestEvaluationAction:
    def test_insufficient_samples_returns_unavailable(self, registry):
        from types import SimpleNamespace

        from paleo_workbench.harness.context import ActionContext
        from paleo_workbench.project.models import FactorMapTask, ProjectDocument

        project = ProjectDocument.new("p")
        project.factor_map_tasks.append(
            FactorMapTask(
                name="厚度",
                target_horizon="H1",
                factor_type="地层厚度",
                method="IDW",
                parameters={"sample_points": [{"x": 0.0, "y": 0.0, "value": 1.0}]},
                status="pending",
                source_kind="mock",
            )
        )
        context = ActionContext(project=project)
        spec = next(
            s for s in registry.specs() if s.action_id == "factor.evaluate_methods"
        )
        out = spec.handler(context, {"factor": "厚度"})
        assert out["error"] == "unavailable"

    def test_unknown_factor_not_found(self, registry):
        from types import SimpleNamespace

        from paleo_workbench.harness.context import ActionContext
        from paleo_workbench.project.models import ProjectDocument

        context = ActionContext(project=ProjectDocument.new("p"))
        spec = next(
            s for s in registry.specs() if s.action_id == "factor.evaluate_methods"
        )
        out = spec.handler(context, {"factor": "nope"})
        assert out["error"] == "not_found"


class TestProductActions:
    def test_describe_unknown_product(self, registry):
        from types import SimpleNamespace

        from paleo_workbench.harness.context import ActionContext
        from paleo_workbench.project.models import ProjectDocument

        context = ActionContext(project=ProjectDocument.new("p"))
        spec = next(s for s in registry.specs() if s.action_id == "map.describe_product")
        out = spec.handler(context, {"product": "nope"})
        assert out["error"] == "not_found"

    def test_publish_unknown_product(self, registry):
        from types import SimpleNamespace

        from paleo_workbench.harness.context import ActionContext
        from paleo_workbench.project.models import ProjectDocument

        context = ActionContext(project=ProjectDocument.new("p"))
        spec = next(s for s in registry.specs() if s.action_id == "map.publish")
        out = spec.handler(context, {"product": "nope"})
        assert out["error"] == "not_found"
