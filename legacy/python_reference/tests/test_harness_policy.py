"""Policy sweep (H9/H10): risk/side-effect consistency and resource
estimation across the WHOLE registry — new actions fail these gates at
test time, not in production."""
from __future__ import annotations

import pytest

from paleo_workbench.harness import (
    DEFAULT_PERMISSIONS,
    ActionRegistry,
    ActionRisk,
)
from paleo_workbench.harness.actions import register_all
from paleo_workbench.runtime.task_categories import TaskCategory


@pytest.fixture(scope="module")
def registry() -> ActionRegistry:
    reg = ActionRegistry()
    register_all(reg)
    return reg


class TestRiskPolicy:
    def test_destructive_never_installable(self, registry):
        assert all(spec.risk is not ActionRisk.DESTRUCTIVE for spec in registry.specs())

    def test_write_actions_declare_side_effects(self, registry):
        naked = [
            spec.action_id
            for spec in registry.specs()
            if spec.risk is ActionRisk.WRITE and not spec.side_effect_notes.strip()
        ]
        assert naked == [], f"WRITE actions without side_effect_notes: {naked}"

    def test_read_actions_on_heavy_lanes_declare_io(self, registry):
        # Risk and lane are orthogonal, but a READ that lands on a heavy
        # background lane must declare its (large) IO appetite — a quiet
        # heavy read is a misdeclared side effect.
        offenders = [
            spec.action_id
            for spec in registry.specs()
            if spec.risk is ActionRisk.READ
            and spec.category not in ("interactive.query", "preview")
            and float(spec.resource_profile.get("io_weight", 0)) < 1.0
        ]
        assert offenders == [], f"heavy READs without declared IO: {offenders}"

    def test_default_permissions_are_minimal(self, registry):
        assert ActionRisk.READ in DEFAULT_PERMISSIONS
        assert ActionRisk.COMPUTE in DEFAULT_PERMISSIONS
        assert ActionRisk.WRITE not in DEFAULT_PERMISSIONS
        assert ActionRisk.DESTRUCTIVE not in DEFAULT_PERMISSIONS

    def test_categories_are_real(self, registry):
        for spec in registry.specs():
            TaskCategory(spec.category)  # raises on unknown category

    def test_cancellable_actions_are_heavy(self, registry):
        # supports_cancel makes sense only where a run can be long enough
        # to need stopping; interactive reads never declare it.
        offenders = [
            spec.action_id
            for spec in registry.specs()
            if spec.supports_cancel
            and spec.category in ("interactive.query",)
        ]
        assert offenders == []

    def test_compute_and_write_declare_typed_outputs(self, registry):
        missing = [
            spec.action_id
            for spec in registry.specs()
            if spec.risk in (ActionRisk.COMPUTE, ActionRisk.WRITE)
            and not spec.output_schema
        ]
        # Every producing action declares its output shape (the executor
        # enforces it; declaring nothing means unverified output).
        assert missing == [], f"producing actions without output_schema: {missing}"


class TestResourcePolicy:
    def test_estimates_positive_and_sane(self, registry):
        for spec in registry.specs():
            profile = spec.resource_profile
            assert float(profile.get("estimated_cpu_cores", 0)) > 0, spec.action_id
            assert float(profile.get("io_weight", 0)) >= 0, spec.action_id
            ram = int(profile.get("estimated_ram_bytes", 0))
            assert ram >= 0, spec.action_id

    def test_heavy_actions_declare_real_estimates(self, registry):
        heavy = {
            "seismic.compute_attribute": 4 * 1024**3,
            "map.create_factor_map": 256 * 1024**2,
            "map.export": 256 * 1024**2,
        }
        for action_id, floor in heavy.items():
            spec = registry.get(action_id)
            assert int(spec.resource_profile.get("estimated_ram_bytes", 0)) >= floor, (
                f"{action_id} understates RAM ({spec.resource_profile})"
            )
            assert float(spec.resource_profile["estimated_cpu_cores"]) >= 1.0

    def test_light_reads_declare_light_estimates(self, registry):
        for spec in registry.specs():
            if spec.category == "interactive.query" and spec.risk is ActionRisk.READ:
                assert float(spec.resource_profile["estimated_cpu_cores"]) <= 1.0, (
                    f"{spec.action_id} overstates a read"
                )

    def test_seismic_roi_declared_not_full_volume(self, registry):
        schema = registry.get("seismic.compute_attribute").input_schema
        assert "roi" in schema["properties"], "ROI window must stay part of the contract"

    def test_cancel_flags_match_known_cancellable_set(self, registry):
        cancellable = {
            spec.action_id for spec in registry.specs() if spec.supports_cancel
        }
        assert {
            "seismic.compute_attribute",
            "map.create_factor_map",
            "map.contour",
            "workflow.run",
            "workflow.resume",
        } <= cancellable
