"""Harness 2.0 action library tests (H8): every new action maps a real
production service; missing capabilities return honest unavailability;
workflow.* actions drive the real DAG engine."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from paleo_workbench.harness import (
    DEFAULT_PERMISSIONS,
    ActionRegistry,
    ActionRisk,
    ActionStatus,
    HarnessExecutor,
)
from paleo_workbench.harness.actions import register_all
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.workflow.dag import (
    NodeSpec,
    SlotSpec,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.store import WorkflowRunStore

sys.path.insert(0, str(Path(__file__).parent / "fakes"))
from inmemory_catalog import InMemoryCatalog  # noqa: E402


@pytest.fixture()
def registry() -> ActionRegistry:
    reg = ActionRegistry()
    register_all(reg)
    return reg


@pytest.fixture()
def catalog() -> InMemoryCatalog:
    return InMemoryCatalog()


def _project_document(tmp_path: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import HorizonInterpretationRef, ProjectDocument

    document = ProjectDocument.new(name="H8-Project", region="测试区")
    document.meta.project_root = str(tmp_path)
    document.wells.append(
        WellEntity(
            name="W1",
            surface_x=500000.0,
            surface_y=4400000.0,
            source_crs="EPSG:32650",
        )
    )
    document.wells.append(
        WellEntity(
            name="W2",
            surface_x=501000.0,
            surface_y=4400500.0,
            source_crs="EPSG:32650",
        )
    )
    document.horizon_interpretations.append(
        HorizonInterpretationRef(name="H2 解释", horizon_key="H2")
    )
    return document


class TestProjectActions:
    def test_inspect_counts(self, registry, tmp_path):
        executor = HarnessExecutor(registry)
        ctx = ActionContext(project=_project_document(tmp_path), workspace_id="H8-Project")
        result = executor.execute("project.inspect", {}, ctx)
        assert result.ok
        assert result.outputs["counts"]["wells"] == 2
        assert result.outputs["project_name"] == "H8-Project"

    def test_health_reports_checks(self, registry, tmp_path):
        executor = HarnessExecutor(registry)
        ctx = ActionContext(
            project=_project_document(tmp_path), catalog=InMemoryCatalog()
        )
        result = executor.execute("project.health", {}, ctx)
        assert result.ok
        checks = {c["check"]: c["ok"] for c in result.outputs["checks"]}
        assert "resource_backing" in checks
        assert "catalog_available" in checks

    def test_health_requires_project(self, registry):
        executor = HarnessExecutor(registry)
        result = executor.execute("project.health", {}, ActionContext())
        assert result.status == ActionStatus.REJECTED.value


class TestDataActions:
    def test_search_with_filters_and_degrade_report(self, registry, catalog):
        catalog.register_input(name="gr_grid", path="/d/a", checksum="k1", kind="factor_grid")
        catalog.register_input(name="density_grid", path="/d/b", checksum="k2", kind="factor_grid")
        executor = HarnessExecutor(registry)
        ctx = ActionContext(catalog=catalog)
        result = executor.execute("data.search", {"text": "grid"}, ctx)
        assert result.ok
        assert result.outputs["count"] == 2
        assert result.outputs["filters_applied"]["text"] is True

    def test_describe_version_includes_producing_run(self, registry, catalog):
        version = catalog.register_input(name="f", path="/d/f", checksum="k", kind="factor")
        run = catalog.begin_run(operation="op", input_version_ids=[], generator_version="1")
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "data.describe_version", {"version_id": version.version_id}, ActionContext(catalog=catalog)
        )
        assert result.ok
        assert result.outputs["name"] == "f"

    def test_describe_unknown_version_fails(self, registry, catalog):
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "data.describe_version", {"version_id": "ghost"}, ActionContext(catalog=catalog)
        )
        assert result.status == ActionStatus.FAILED.value

    def test_lineage_directions(self, registry, catalog):
        v1 = catalog.register_input(name="a", path="/d/a", checksum="k1")
        run = catalog.begin_run(operation="op", input_version_ids=[v1.version_id], generator_version="1")
        catalog.complete_run(run.run_id, status="complete")
        executor = HarnessExecutor(registry)
        ctx = ActionContext(catalog=catalog)
        up = executor.execute(
            "data.lineage", {"version_id": v1.version_id, "direction": "descendants"}, ctx
        )
        assert up.ok

    def test_verify_reports_integrity(self, registry, catalog, tmp_path):
        f = tmp_path / "f.dat"
        f.write_bytes(b"payload")
        from inmemory_catalog import sha256_of_file

        version = catalog.register_input(name="f", path=str(f), checksum=sha256_of_file(f))
        executor = HarnessExecutor(registry)
        result = executor.execute(
            "data.verify", {"version_id": version.version_id}, ActionContext(catalog=catalog)
        )
        assert result.ok
        assert result.outputs["integrity"] == "verified"


class TestWorkflowActions:
    def _spec(self) -> WorkflowSpec:
        return WorkflowSpec(
            workflow_id="wf.h8",
            name="H8 工作流",
            slots=(SlotSpec(name="factor", schema={"type": "string"}),),
            nodes=(
                NodeSpec(
                    node_id="n1",
                    action_id="data.search",
                    parameters={"text": {"$slot": "factor"}},
                ),
            ),
        )

    def test_validate_then_run_then_describe(self, registry, catalog, tmp_path, monkeypatch):
        from paleo_workbench.harness.actions import workflow as wf_actions

        store_root = tmp_path / "runs"
        store_root.mkdir()
        monkeypatch.setattr(
            wf_actions, "set_workflow_engine", lambda engine: None, raising=False
        )
        engine = wf_actions.get_workflow_engine()
        engine.set_store(WorkflowRunStore(str(store_root)))
        catalog.register_input(name="gr_grid", path="/d/a", checksum="k1", kind="factor_grid")

        executor = HarnessExecutor(registry)
        ctx = ActionContext(catalog=catalog)
        spec_dict = self._spec().to_dict()

        validated = executor.execute(
            "workflow.validate", {"workflow": spec_dict}, ctx
        )
        assert validated.ok and validated.outputs["valid"] is True

        ran = executor.execute(
            "workflow.run",
            {"workflow": spec_dict, "slot_values": {"factor": "grid"}},
            ctx,
        )
        assert ran.ok, ran.error
        assert ran.outputs["state"] == "completed"
        run_id = ran.outputs["run_id"]

        described = executor.execute("workflow.describe", {"run_id": run_id}, ctx)
        assert described.ok
        assert described.outputs["progress"] == 1.0
        n1 = described.outputs["nodes"]["n1"]
        assert n1["state"] == "succeeded"

    def test_recipe_save_load_clone_roundtrip(self, registry, catalog, tmp_path):
        from paleo_workbench.harness.actions import workflow as wf_actions

        engine = wf_actions.get_workflow_engine()
        store_root = tmp_path / "runs"
        store_root.mkdir()
        engine.set_store(WorkflowRunStore(str(store_root)))
        executor = HarnessExecutor(registry)
        ctx = ActionContext(
            catalog=catalog, permissions=DEFAULT_PERMISSIONS | {ActionRisk.WRITE}
        )
        ran = executor.execute(
            "workflow.run",
            {"workflow": self._spec().to_dict(), "slot_values": {"factor": "x"}},
            ctx,
        )
        run_id = ran.outputs["run_id"]

        saved = executor.execute("recipe.save", {"run_id": run_id}, ctx)
        assert saved.ok, saved.error
        path = saved.outputs["path"]
        assert path.endswith(".paleo-workflow.json")

        loaded = executor.execute("recipe.load", {"path": path}, ctx)
        assert loaded.ok
        assert loaded.outputs["workflow_id"] == "wf.h8"

        cloned = executor.execute("recipe.clone", {"path": path}, ctx)
        assert cloned.ok
        assert cloned.outputs["recipe_id"] != saved.outputs["recipe_id"]

    def test_describe_reproduction_reports_nodes(self, registry, catalog, tmp_path):
        from paleo_workbench.harness.actions import workflow as wf_actions

        engine = wf_actions.get_workflow_engine()
        store_root = tmp_path / "runs"
        store_root.mkdir()
        engine.set_store(WorkflowRunStore(str(store_root)))
        executor = HarnessExecutor(registry)
        ctx = ActionContext(catalog=catalog)
        ran = executor.execute(
            "workflow.run",
            {"workflow": self._spec().to_dict(), "slot_values": {"factor": "x"}},
            ctx,
        )
        repro = executor.execute(
            "workflow.describe_reproduction", {"run_id": ran.outputs["run_id"]}, ctx
        )
        assert repro.ok
        nodes = repro.outputs["nodes"]
        assert nodes[0]["action_id"] == "data.search"
        assert nodes[0]["executed"] is True
        assert repro.outputs["spec_hash"]


class TestWellActions:
    def test_correlate_is_honestly_unavailable(self, registry, tmp_path):
        executor = HarnessExecutor(registry)
        ctx = ActionContext(project=_project_document(tmp_path))
        result = executor.execute(
            "well.correlate", {"wells": ["W1", "W2"]}, ctx
        )
        assert result.status == ActionStatus.UNAVAILABLE.value
        assert "no headless" in (result.error or "")

    def test_describe_interpretation_lists_refs(self, registry, tmp_path):
        executor = HarnessExecutor(registry)
        ctx = ActionContext(project=_project_document(tmp_path))
        result = executor.execute("well.describe_interpretation", {}, ctx)
        assert result.ok
        assert result.outputs["horizons"][0]["horizon_key"] == "H2"
