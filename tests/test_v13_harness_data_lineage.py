"""V13 harness data-lineage actions（W-S）：agent 与 UI 同一实现的契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.harness.actions import data_lineage
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.registry import ActionRegistry
from paleo_workbench.mapping_workspace.stage_state import (
    BINDING_CATALOG_VERSION,
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.project.models import ProjectDocument


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture()
def registry():
    reg = ActionRegistry()
    reg.register = reg.register  # noqa: PLW0127 - clarity
    data_lineage.register(reg)
    return reg


@pytest.fixture()
def env(tmp_path: Path):
    from paleo_workbench.harness.spec import ActionRisk

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    doc = ProjectDocument.new("demo")
    doc.meta.project_root = str(project_path.parent)
    context = ActionContext(
        project=doc, project_path=str(project_path),
        permissions=frozenset(
            {ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}),
    )
    yield service, doc, context, tmp_path
    reset_catalog()
    service.close()


def _import_root(tmp_path: Path) -> Path:
    root = tmp_path / "import_root" / "Well-A"
    root.mkdir(parents=True)
    (root / "A.las").write_text("~W\nWELL: Well-A\n~C\nDT 1 1\n", encoding="utf-8")
    (root / "tops.csv").write_text("fm,md\nF1,100\n", encoding="utf-8")
    return root.parent


class TestIngestActions:
    def test_plan_is_readonly_and_reports_items(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        root = _import_root(tmp_path)
        result = HarnessExecutor(registry).execute(
            "data.ingest_plan", {"root": str(root)}, context)
        assert result.status == "success", result.error
        payload = result.outputs
        assert payload["summary"]["total"] == 2
        kinds = {item["role"] for item in payload["items"]}
        assert "well_log" in kinds and "tops" in kinds
        # 零副作用：目录为空
        assert service.count_assets() == 0

    def test_ingest_registers_binds_and_is_idempotent(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        root = _import_root(tmp_path)
        result = HarnessExecutor(registry).execute(
            "data.ingest", {"root": str(root)}, context)
        assert result.status == "success", result.error
        first = result.outputs
        assert len(first["imported_version_ids"]) == 2
        assert first["bound_links"] >= 1
        assert first["created_entities"] >= 1
        # 幂等重跑：全部跳过
        result2 = HarnessExecutor(registry).execute(
            "data.ingest", {"root": str(root)}, context)
        assert result2.outputs["imported_version_ids"] == []
        assert len(result2.outputs["skipped"]) == 2

    def test_ingest_decisions_override(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        root = _import_root(tmp_path)
        skip_csv = str(root / "Well-A" / "tops.csv")
        result = HarnessExecutor(registry).execute(
            "data.ingest",
            {"root": str(root), "decisions": {skip_csv: "skip"}}, context)
        assert result.status == "success", result.error
        assert len(result.outputs["imported_version_ids"]) == 1
        assert skip_csv in result.outputs["skipped"]


class TestWorkingCopyActions:
    def test_create_and_commit_with_manual_edit_run(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        src = tmp_path / "w.las"
        src.write_text("~W\nWELL: X\n", encoding="utf-8")
        raw = service.import_raw(src, name="w.las", type="well_log")

        created = HarnessExecutor(registry).execute(
            "data.create_working_copy", {"version_id": raw.id}, context)
        assert created.status == "success", created.error
        working_path = Path(created.outputs["working_path"])
        assert working_path.exists()
        working_path.write_text("~W\nWELL: X\n~C\nEDITED\n", encoding="utf-8")

        committed = HarnessExecutor(registry).execute(
            "data.commit_working_copy",
            {"working_path": str(working_path), "actor": "agent",
             "note": "agent edit"}, context)
        assert committed.status == "success", committed.error
        payload = committed.outputs
        assert payload["stage"] == "derived"
        assert payload["run_id"]
        run = service.get_run(payload["run_id"])
        assert run.operation == "manual_edit"
        assert run.status == "complete"
        assert run.parameters["actor"] == "agent"
        assert payload["version_id"] in run.output_version_ids


class TestMapUsageAction:
    def test_usage_of_version_lists_layers(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        src = tmp_path / "u.las"
        src.write_text("x", encoding="utf-8")
        raw = service.import_raw(src, name="u.las", type="well_log")
        workspace = MappingWorkspaceState()
        workspace.set_membership(LayerMembershipRecord(
            layer_id="layer-q", source_version_id=raw.id,
            source_asset_id=raw.asset_id,
            binding_kind=BINDING_CATALOG_VERSION,
        ))
        doc.mapping_workspace = workspace.to_dict()

        result = HarnessExecutor(registry).execute(
            "data.map_usage", {"version_id": raw.id}, context)
        assert result.status == "success", result.error
        payload = result.outputs
        assert payload["counts"].get("layer") == 1
        assert payload["usages"][0]["ref_id"] == "layer-q"


class TestRecomputeStaleAction:
    def test_dry_run_returns_plan_without_compute(self, registry, env):
        from paleo_workbench.harness.executor import HarnessExecutor

        service, doc, context, tmp_path = env
        result = HarnessExecutor(registry).execute(
            "data.recompute_stale", {"dry_run": True}, context)
        assert result.status == "success", result.error
        assert result.outputs["dry_run"] is True
        assert isinstance(result.outputs["steps"], list)
