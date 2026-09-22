"""V13 cross-workspace E2E（goal §24 的完整闭环）。

```
RAW×2 (ingest plan) → prediction INTERMEDIATE → DERIVED 解释
  → 上图（factor 任务 + 图层绑定 + 重排）
  → 图层内容编辑 → manual_edit 提交新版本
  → 血缘回溯到 RAW
  → 上游 LAS 升版 → stale 传播（catalog impact + mapping freshness）
  → 重算（新结果版本）→ 重绑图层 → CURRENT
  → 保存/重开 → 绑定/顺序/成熟度不变
```

全部走生产实现：execute_ingest_plan（与 UI/Agent 同一服务）、
catalog/lifecycle 注册助手、LayerGroupController 排序、
MappingDependencyService 新鲜度。无 mock 业务逻辑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.impact import ImpactService
from paleo_workbench.catalog.lifecycle import (
    complete_manual_edit_run,
    register_manual_edit_run,
)
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.dependencies import (
    FreshnessStatus,
    MappingDependencyService,
)
from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import (
    BINDING_CATALOG_VERSION,
    MappingWorkspaceState,
)
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.resources.ingest_plan import (
    build_ingest_plan,
    execute_ingest_plan,
)


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture()
def env(tmp_path: Path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    project = ProjectDocument.new("e2e")
    project.meta.project_root = str(project_path.parent)
    yield service, project, tmp_path
    reset_catalog()
    service.close()


def _ingest_dir(tmp_path: Path) -> Path:
    root = tmp_path / "import" / "Well-A"
    root.mkdir(parents=True)
    (root / "A.las").write_text(
        "~W\nWELL: Well-A\n~C\nDT 1 1\n", encoding="utf-8")
    (root / "B.las").write_text(
        "~W\nWELL: Well-A\n~C\nRHOB 1 1\n", encoding="utf-8")
    return root.parent


class TestCrossWorkspaceLineageLoop:
    def test_raw_to_map_to_stale_to_recompute_to_reopen(self, env):
        service, project, tmp_path = env

        # -- 1-3. 规划导入两份 LAS → Well A（绑定 + primary）--------------
        root = _ingest_dir(tmp_path)
        plan = build_ingest_plan(root, project, service=service)
        for item in plan.items:
            item.decision = "accept"
        report = execute_ingest_plan(plan, service, project, bind=True)
        assert len(report.imported_version_ids) == 2
        assert report.created_entities == 1  # Well-A 自动建井
        assert report.bound_links >= 1
        well = project.wells[0]
        assert well.name == "Well-A"
        raw_versions = [
            service.get_version(vid) for vid in report.imported_version_ids]
        raw_a, raw_b = sorted(raw_versions, key=lambda v: v.source_uri or "")

        # -- 4-5. 处理：prediction run（A+B → INTERMEDIATE 归一化）--------
        normalized = tmp_path / "normalized.npz"
        normalized.write_bytes(b"normalized-grid")
        from paleo_workbench.catalog.lifecycle import register_factor_map_run

        task = FactorMapTask(
            name="砂岩厚度", target_horizon="D63", factor_type="sand",
            method="idw", source_kind="mock",
            input_resource_ids=[],
        )
        run1, grid_version = register_factor_map_run(
            task, catalog=CoreCatalogAdapter(service),
            intermediate_path=str(normalized),
            extra_input_version_ids=[raw_a.id, raw_b.id],
        )
        assert run1 is not None and grid_version is not None
        task.grid_artifact_version_id = grid_version.version_id
        from paleo_workbench.project.models import FACTOR_TASK_STATUS_COMPLETE

        task.status = FACTOR_TASK_STATUS_COMPLETE
        project.factor_map_tasks.append(task)

        # -- 6. 衍生解释：INTERMEDIATE → DERIVED --------------------------
        interp = tmp_path / "interpretation.json"
        interp.write_text('{"facies": "delta"}', encoding="utf-8")
        run2 = service.register_run(
            "prediction",
            input_version_ids=[grid_version.version_id])
        derived = service.register_result_asset(
            name="相解释 v1", type="prediction", format="json",
            asset_metadata=None, source_path=interp, stage="derived",
            run_id=run2.id,
        )

        # -- 7. 上图：factor 格网 + 相带草稿两层，钉版本 -------------------
        workspace = MappingWorkspaceState()
        controller = LayerGroupController(workspace)
        controller.register_layer(
            "layer-grid", LayerRole.FACTOR_GRID,
            factor_task_id=task.id,
            source_version_id=grid_version.version_id,
        )
        controller.register_layer(
            "layer-draft", LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id=derived.id,
        )
        grid_record = workspace.membership("layer-grid")
        assert grid_record.source_version_id == grid_version.version_id
        assert grid_record.binding_kind == BINDING_CATALOG_VERSION

        # -- 8. 重排：draft 提到最上（观察序 → 稳定键）--------------------
        accepted = controller.observe_tree_nodes([
            {"type": "layer", "id": "layer-draft"},
            {"type": "layer", "id": "layer-grid"},
        ])
        assert accepted
        from types import SimpleNamespace

        snapshots = [
            SimpleNamespace(id="layer-grid"),
            SimpleNamespace(id="layer-draft"),
        ]
        desired = controller.build_desired_tree(snapshots)
        assert list(desired.iter_layers()) == ["layer-draft", "layer-grid"]
        workspace.tree = desired.to_dict()

        # -- 9-10. 图层内容编辑 → manual_edit 提交新版本 -------------------
        working = service.create_working_copy(derived.id)
        Path(working).write_text(
            '{"facies": "delta", "edited": true}', encoding="utf-8")
        edit_run = register_manual_edit_run(
            service, source_version_ids=[derived.id],
            note="图层编辑（相带边界修订）", actor="interpreter",
        )
        derived_v2 = service.commit_working_copy(
            working, run_id=edit_run.id)
        complete_manual_edit_run(
            service, edit_run.id, committed_version_ids=[derived_v2.id])
        stored_run = service.get_run(edit_run.id)
        assert stored_run.operation == "manual_edit"
        assert stored_run.status == "complete"
        assert derived_v2.parent_version_ids == [derived.id]

        # -- 11. 血缘回溯：编辑版 → run 输入 → INTERMEDIATE → RAW ---------
        def _walk_ids(node):
            yield node.version_id
            for child in node.children:
                yield from _walk_ids(child)

        chain = service.get_lineage_chain(
            derived_v2.id, direction="ancestors")
        walked = set(_walk_ids(chain.root))
        assert derived.id in walked
        assert grid_version.version_id in walked
        ancestors_of_grid = service.get_lineage_chain(
            grid_version.version_id, direction="ancestors")
        raw_ids = {raw_a.id, raw_b.id}
        assert raw_ids <= set(_walk_ids(ancestors_of_grid.root))

        # -- 12. 上游变更：LAS A 同资产升 v2（多版本资产 = stale 触发口径）--
        working_a = service.create_working_copy(raw_a.id)
        Path(working_a).write_text(
            "~W\nWELL: Well-A\n~C\nDT 1 2\n", encoding="utf-8")
        raw_a_v2 = service.commit_working_copy(
            working_a, asset_id=raw_a.asset_id)
        assert raw_a_v2.asset_id == raw_a.asset_id

        # -- 13. stale 传播：catalog impact 命中中间成果与解释 -------------
        impact = ImpactService(service)
        stale_ids = {item.version_id for item in impact.downstream_stale()}
        assert grid_version.version_id in stale_ids
        assert derived.id in stale_ids

        # -- 14. 地图显示 stale：mapping freshness（factor 路径=run 输入）--
        adapter = CoreCatalogAdapter(service)
        dependency = MappingDependencyService()
        summary = dependency.evaluate(project, workspace, adapter)
        factor_entry = next(
            e for e in summary.artifacts
            if e.artifact_key == f"factor:{task.id}")
        assert factor_entry.status == FreshnessStatus.STALE
        assert raw_a.id in list(factor_entry.upstream_culprits) or (
            factor_entry.detail)

        # -- 15. 重算：同一算法重跑 → 新 INTERMEDIATE，任务指针前移 ---------
        normalized_v2 = tmp_path / "normalized_v2.npz"
        normalized_v2.write_bytes(b"normalized-grid-v2")
        run3, grid_v2 = register_factor_map_run(
            task, catalog=CoreCatalogAdapter(service),
            intermediate_path=str(normalized_v2),
            extra_input_version_ids=[raw_a_v2.id, raw_b.id],
        )
        assert grid_v2 is not None
        task.grid_artifact_version_id = grid_v2.version_id

        # 重算后 factor 新鲜度恢复 CURRENT（新 run 的输入全为 current）。
        summary2 = dependency.evaluate(project, workspace, adapter)
        factor_entry2 = next(
            e for e in summary2.artifacts
            if e.artifact_key == f"factor:{task.id}")
        assert factor_entry2.status == FreshnessStatus.CURRENT

        # -- 16. 替换绑定：图层重钉到新格网版本 ----------------------------
        controller.register_layer(
            "layer-grid", LayerRole.FACTOR_GRID,
            factor_task_id=task.id,
            source_version_id=grid_v2.version_id,
        )
        assert workspace.membership(
            "layer-grid").source_version_id == grid_v2.version_id

        # 反查：新版本被图层引用；旧版本不再被引用 --------------------------
        from paleo_workbench.mapping_workspace.source_usage import (
            usages_of_version,
        )

        usage_new = usages_of_version(
            grid_v2.version_id, workspace=workspace, project=project,
            catalog=service)
        assert any(u.kind == "layer" and u.ref_id == "layer-grid"
                   for u in usage_new.usages)
        usage_old = usages_of_version(
            grid_version.version_id, workspace=workspace, project=project,
            catalog=service)
        assert not any(u.ref_id == "layer-grid" for u in usage_old.usages)

        # -- 17-18. 保存/重开：绑定/顺序/成熟度不变 ------------------------
        project.mapping_workspace = workspace.to_dict()
        reloaded_project = ProjectDocument.model_validate(
            project.model_dump())
        reloaded = MappingWorkspaceState.from_dict(
            reloaded_project.mapping_workspace)
        controller2 = LayerGroupController(reloaded)
        controller2.reload_from_state()
        record2 = reloaded.membership("layer-grid")
        assert record2.source_version_id == grid_v2.version_id
        assert record2.binding_kind == BINDING_CATALOG_VERSION
        assert reloaded.membership("layer-draft").source_version_id == (
            derived_v2.id if workspace.membership(
                "layer-draft").source_version_id == derived_v2.id
            else derived.id)
        desired2 = controller2.build_desired_tree(snapshots)
        assert list(desired2.iter_layers()) == ["layer-draft", "layer-grid"]
