"""Harness 2.0 context snapshot tests (H5): immutability, snapshot field
coverage, derived per-node contexts, and $context binding whitelist."""
from __future__ import annotations

import dataclasses

import pytest

from paleo_workbench.harness.context import ActionContext, SelectionSnapshot
from paleo_workbench.workflow.dag.validation import CONTEXT_BINDING_WHITELIST


class TestSelectionSnapshot:
    def test_frozen(self):
        snap = SelectionSnapshot(active_well_id="W1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.active_well_id = "W2"  # type: ignore[misc]

    def test_covers_harness2_fields(self):
        snap = SelectionSnapshot(
            active_well_id="W1",
            selected_well_ids=("W1", "W2"),
            seismic_cursor=(3, 4, 1200.0),
            depth_range=(1000.0, 2000.0),
            target_horizon="H2",
            active_layer_id="layer-7",
            map_extent=(500000.0, 4400000.0, 510000.0, 4410000.0),
            map_crs="EPSG:32650",
            selected_feature_refs=("feature:12",),
            active_version_id="ver-1",
        )
        d = snap.to_dict()
        for key in (
            "target_horizon",
            "active_layer_id",
            "map_extent",
            "map_crs",
            "selected_feature_refs",
            "active_version_id",
        ):
            assert key in d, key
        assert d["map_extent"] == [500000.0, 4400000.0, 510000.0, 4410000.0]

    def test_default_snapshot_has_no_fields(self):
        assert SelectionSnapshot().to_dict()["target_horizon"] is None


class TestActionContext:
    def test_derived_shares_services_not_lease_slot(self):
        ctx = ActionContext(project_path="/wks/a.paleo.json")
        ctx.extras["workflow_run_id"] = "run-1"
        ctx.extras["admission_lease"] = object()
        marker = ctx.map_documents
        derived = ctx.derived()
        assert derived.project_path == ctx.project_path
        assert derived.extras["workflow_run_id"] == "run-1"
        assert "admission_lease" not in derived.extras
        # Stashes are shared (cooperative workflow state).
        assert derived.map_documents is marker
        # New writes do not leak back into the parent's extras identity.
        derived.extras["node_local"] = True
        assert "node_local" not in ctx.extras

    def test_snapshot_description_reports_workflow_ref(self):
        ctx = ActionContext()
        ctx.extras["workflow_run_id"] = "run-42"
        assert ctx.snapshot_description()["current_workflow_run_id"] == "run-42"

    def test_permissions_minimal_by_default(self):
        ctx = ActionContext()
        assert not ctx.permits(__import__(
            "paleo_workbench.harness.spec", fromlist=["ActionRisk"]
        ).ActionRisk.WRITE)
        assert not ctx.permits(__import__(
            "paleo_workbench.harness.spec", fromlist=["ActionRisk"]
        ).ActionRisk.DESTRUCTIVE)


class TestContextBindingWhitelist:
    def test_whitelist_is_readonly_facts(self):
        for key in CONTEXT_BINDING_WHITELIST:
            assert "." not in key or key.split(".")[0] == "selection"
        # Destructive/identity-bypassing keys never appear.
        for banned in ("project", "catalog", "extras", "permissions"):
            assert banned not in CONTEXT_BINDING_WHITELIST
