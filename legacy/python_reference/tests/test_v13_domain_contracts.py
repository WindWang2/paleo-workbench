"""V13 domain contracts: manual-edit provenance, layer source binding,
version→map usage reverse query, stage-state preservation, intermediate
policy, and order-key persistence roundtrip.

These pin the *contracts* added by V13 (docs/development/geodata-qgis-
control-v13/). UI-level behavior is covered by the workspace tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.edit_session import open_edit_session
from paleo_workbench.catalog.intermediate_policy import (
    CLASS_CACHE,
    CLASS_EPHEMERAL,
    CLASS_INTERMEDIATE,
    KNOWN_ARTIFACT_POLICIES,
    policy_for,
)
from paleo_workbench.catalog.lifecycle import (
    MANUAL_EDIT_GENERATOR,
    MANUAL_EDIT_OPERATION,
    complete_manual_edit_run,
    port_role_for_business_role,
    register_manual_edit_run,
)
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.source_usage import (
    USAGE_COMPILATION_INPUT,
    USAGE_FACTOR_GRID,
    USAGE_LAYER,
    USAGE_MAP_PRODUCT_OUTPUT,
    USAGE_RUN_INPUT,
    usage_counts,
    usages_of_asset,
    usages_of_version,
)
from paleo_workbench.mapping_workspace.stage_state import (
    BINDING_CATALOG_VERSION,
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.project.domain import WellEntity, upsert_entity_asset_link
from paleo_workbench.project.models import ProjectDocument


# ---------------------------------------------------------------------------
# fixtures


@pytest.fixture()
def catalog_env(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("demo")
    well = WellEntity(name="Well-A", uwi="UWI-001")
    doc.wells.append(well)
    yield service, doc, well, tmp_path
    service.close()


def _import_raw(service, tmp_path, name, type_):
    src = tmp_path / name
    src.write_text(f"content-{name}", encoding="utf-8")
    return service.import_raw(src, name=name, type=type_)


def _bind(doc, well, asset_id, role):
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset_id, role=role)


# ---------------------------------------------------------------------------
# P1-a: manual edit provenance


class TestManualEditProvenance:
    def test_edit_session_commit_books_manual_edit_run(self, catalog_env):
        service, doc, well, tmp_path = catalog_env
        version = _import_raw(service, tmp_path, "tops.xlsx", "tops")
        _bind(doc, well, version.asset_id, "tops")
        session = open_edit_session(service, doc, "well", well.id, "tops")
        session.primary_path().write_text("edited", encoding="utf-8")

        report = session.commit(new_name="tops edited", actor="tester")

        assert report.committed_version_ids, report.issues
        runs = [r for r in service.list_runs()
                if r.operation == MANUAL_EDIT_OPERATION]
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "complete"
        assert run.generator == MANUAL_EDIT_GENERATOR
        assert run.input_version_ids == [version.id]
        assert run.parameters["entity_type"] == "well"
        assert run.parameters["actor"] == "tester"
        assert run.output_version_ids == list(report.committed_version_ids)
        # typed ports: business role tops → input port "tops"; output manual_edit
        assert [p.role for p in run.input_ports] == ["tops"]
        assert [p.role for p in run.output_ports] == ["manual_edit"]
        # committed version links back to the run → explain reports regenerable
        committed = service.get_version(report.committed_version_ids[0])
        assert committed.run_id == run.id
        assert committed.parent_version_ids == [version.id]

    def test_business_role_port_mapping(self):
        assert port_role_for_business_role("tops") == "tops"
        assert port_role_for_business_role("well_log") == "well_logs"
        assert port_role_for_business_role("trajectory") == "trajectory"
        assert port_role_for_business_role("time_depth") == "time_depth"
        # open vocabulary: unmapped roles pass through verbatim, empty → ""
        assert port_role_for_business_role("core") == "core"
        assert port_role_for_business_role("") == ""

    def test_booking_failure_still_commits_without_run(self, catalog_env, monkeypatch):
        service, doc, well, tmp_path = catalog_env
        version = _import_raw(service, tmp_path, "a.las", "well_log")
        _bind(doc, well, version.asset_id, "well_log")
        session = open_edit_session(service, doc, "well", well.id, "well_log")
        session.primary_path().write_text("edited", encoding="utf-8")

        def boom(*args, **kwargs):
            raise RuntimeError("booking failed")

        monkeypatch.setattr(service, "register_run", boom)
        report = session.commit()

        assert report.committed_version_ids
        assert any("provenance" in issue for issue in report.issues)
        assert [r for r in service.list_runs()
                if r.operation == MANUAL_EDIT_OPERATION] == []

    def test_zero_commit_marks_run_failed(self, catalog_env, monkeypatch):
        service, doc, well, tmp_path = catalog_env
        version = _import_raw(service, tmp_path, "b.las", "well_log")
        run = register_manual_edit_run(
            service, source_version_ids=[version.id],
            entity_type="well", entity_id=well.id, business_role="well_log",
        )
        complete_manual_edit_run(service, run.id, committed_version_ids=[])
        stored = service.get_run(run.id)
        assert stored.status == "failed"

    def test_partial_commit_completes_with_failed_count(self, catalog_env):
        service, *_ = catalog_env
        run = register_manual_edit_run(service, source_version_ids=["ver_x"])
        # committed id 不存在 → set_run_ports 校验失败被吞；run 仍 complete
        # 且失败数如实入参数（宏不是事务）。
        complete_manual_edit_run(
            service, run.id, committed_version_ids=["ver_missing"],
            failed_count=1,
        )
        stored = service.get_run(run.id)
        assert stored.status == "complete"
        assert stored.parameters["failed_checkouts"] == 1


# ---------------------------------------------------------------------------
# P1-b: membership binding fields


class TestMembershipBindingFields:
    def test_register_layer_defaults_binding_kind(self):
        state = MappingWorkspaceState()
        controller = LayerGroupController(state)
        controller.register_layer(
            "layer-1", LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id="ver_1", source_asset_id="asset_1",
        )
        record = state.membership("layer-1")
        assert record.source_version_id == "ver_1"
        assert record.source_asset_id == "asset_1"
        assert record.binding_kind == BINDING_CATALOG_VERSION

    def test_explicit_fingerprint_binding_kind(self):
        state = MappingWorkspaceState()
        controller = LayerGroupController(state)
        controller.register_layer(
            "layer-2", LayerRole.FACIES_BOUNDARY,
            binding_kind="content_fingerprint",
        )
        assert state.membership("layer-2").binding_kind == "content_fingerprint"

    def test_roundtrip_preserves_binding_fields(self):
        state = MappingWorkspaceState()
        state.set_membership(LayerMembershipRecord(
            layer_id="layer-3", role=LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id="ver_9", source_asset_id="asset_9",
            binding_kind=BINDING_CATALOG_VERSION, bound_at="2026-09-15T00:00:00",
        ))
        reloaded = MappingWorkspaceState.from_dict(state.to_dict())
        record = reloaded.membership("layer-3")
        assert record.source_version_id == "ver_9"
        assert record.source_asset_id == "asset_9"
        assert record.binding_kind == BINDING_CATALOG_VERSION
        assert record.bound_at == "2026-09-15T00:00:00"

    def test_legacy_dict_loads_with_unknown_binding(self):
        legacy = {
            "layer_id": "layer-old",
            "role": "legacy_unclassified",
            "created_stage": "facies_calibration",
        }
        record = LayerMembershipRecord.from_dict(legacy)
        assert record.source_asset_id == ""
        assert record.binding_kind == ""
        assert record.bound_at == ""


# ---------------------------------------------------------------------------
# P1-c: version → mapping usage reverse query


class TestSourceUsage:
    def _workspace_with_binding(self):
        state = MappingWorkspaceState()
        state.set_membership(LayerMembershipRecord(
            layer_id="layer-facies", role=LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id="ver_pin", source_asset_id="asset_pin",
            binding_kind=BINDING_CATALOG_VERSION,
        ))
        return state

    def test_usages_of_version_aggregates_all_kinds(self):
        workspace = self._workspace_with_binding()
        project = ProjectDocument.new("demo")
        project.factor_map_tasks.append(_factor_task("task-1", "ver_grid"))
        project.compilation_input_sets.append({
            "id": "cis-1", "name": "综合编图输入", "frozen": True,
            "entries": [{"selector": "s", "pinned_version_id": "ver_pin",
                         "resolved_asset_id": "asset_pin"}],
        })
        project.map_products.append(_map_product("prod-1", "ver_out"))

        report = usages_of_version(
            "ver_pin", workspace=workspace, project=project)
        kinds = {(u.kind, u.ref_id) for u in report.usages}
        assert (USAGE_LAYER, "layer-facies") in kinds
        assert (USAGE_COMPILATION_INPUT, "cis-1") in kinds
        assert not report.truncated

        grid_report = usages_of_version(
            "ver_grid", workspace=workspace, project=project)
        assert {(u.kind, u.ref_id) for u in grid_report.usages} == {
            (USAGE_FACTOR_GRID, "task-1")}

        out_report = usages_of_version(
            "ver_out", workspace=workspace, project=project)
        assert {(u.kind, u.ref_id) for u in out_report.usages} == {
            (USAGE_MAP_PRODUCT_OUTPUT, "prod-1")}

    def test_usages_of_version_with_catalog_runs(self, catalog_env):
        service, doc, well, tmp_path = catalog_env
        raw = _import_raw(service, tmp_path, "u.las", "well_log")
        mid = tmp_path / "mid.out"
        mid.write_text("mid", encoding="utf-8")
        run = service.register_run(
            "prediction", input_version_ids=[raw.id])
        derived = service.register_result_asset(
            name="pred", type="prediction", format="txt", asset_metadata=None,
            source_path=mid, stage="derived", run_id=run.id,
        )
        report = usages_of_version(
            raw.id, workspace=None, project=None, catalog=service)
        run_usages = [u for u in report.usages if u.kind == USAGE_RUN_INPUT]
        assert any(u.ref_id == run.id for u in run_usages)
        assert usage_counts(report).get(USAGE_RUN_INPUT, 0) >= 1
        # derived version 不误报为 raw 的用途
        other = usages_of_version(
            derived.id, workspace=None, project=None, catalog=service)
        assert other.usages == []

    def test_usages_of_asset_via_catalog_versions(self, catalog_env):
        service, doc, well, tmp_path = catalog_env
        version = _import_raw(service, tmp_path, "v.las", "tops")
        _bind(doc, well, version.asset_id, "tops")
        workspace = MappingWorkspaceState()
        workspace.set_membership(LayerMembershipRecord(
            layer_id="layer-tops", role=LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id=version.id, source_asset_id=version.asset_id,
            binding_kind=BINDING_CATALOG_VERSION,
        ))
        report = usages_of_asset(
            version.asset_id, workspace=workspace, project=None, catalog=service)
        assert {(u.kind, u.ref_id) for u in report.usages} == {
            (USAGE_LAYER, "layer-tops")}


def _factor_task(task_id: str, grid_version_id: str):
    from paleo_workbench.project.models import FactorMapTask

    return FactorMapTask(
        id=task_id, name=f"task {task_id}", target_horizon="H1",
        factor_type="sand", method="kriging",
        grid_artifact_version_id=grid_version_id,
    )


def _map_product(product_id: str, output_version_id: str):
    from paleo_workbench.project.models import MapProductRecord

    return MapProductRecord(
        id=product_id, product_name=f"product {product_id}",
        output_version_id=output_version_id,
    )


# ---------------------------------------------------------------------------
# P1-e: stage state preservation


class TestStageStatePreservation:
    def _controller(self, qtbot):
        from paleo_workbench.mapping_workspace.controller import (
            MappingStageController,
        )

        controller = MappingStageController()
        controller.set_target_resolver(
            lambda role: "layer-a" if role == LayerRole.INITIAL_FACIES_DRAFT else None)
        controller.set_target_validator(lambda lid: lid in {"layer-a", "layer-b"})
        return controller

    def test_set_stage_away_and_back_restores_explicit_target(self, qtbot):
        controller = self._controller(qtbot)
        from paleo_workbench.mapping_workspace.stages import MappingStage

        controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
        controller.state.set_current_stage(MappingStage.FACIES_CALIBRATION)
        # 用户在阶段 1 显式选择了 layer-b
        controller.set_active_target("layer-b")
        assert controller.active_target_layer_id == "layer-b"

        controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
        assert controller.active_target_layer_id != "layer-b"  # 跨阶段不继承
        controller.set_stage(MappingStage.FACIES_CALIBRATION)
        # V13：回到阶段 1 恢复用户显式选择，而非 profile 重算
        assert controller.active_target_layer_id == "layer-b"

    def test_stored_target_dead_layer_recomputes(self, qtbot):
        controller = self._controller(qtbot)
        from paleo_workbench.mapping_workspace.stages import MappingStage

        controller.state.view_state(
            MappingStage.FACIES_CALIBRATION).active_layer_id = "layer-gone"
        controller._reassign_active_target()
        assert controller.active_target_layer_id == "layer-a"

    def test_layer_visibility_and_opacity_overlay_roundtrip(self, qtbot):
        state = MappingWorkspaceState()
        controller = LayerGroupController(state)
        controller.record_layer_visibility_event("layer-1", False)
        controller.record_layer_opacity_event("layer-1", 0.4)
        reloaded = MappingWorkspaceState.from_dict(state.to_dict())
        view = reloaded.view_state(state.current_stage)
        assert view.layer_visibility == {"layer-1": False}
        assert view.layer_opacity == {"layer-1": 0.4}
        assert view.customized is True


# ---------------------------------------------------------------------------
# P1-f: intermediate policy


class TestIntermediatePolicy:
    def test_known_policies_registration_flags(self):
        assert policy_for("factor_map_grid").must_register is True
        assert policy_for("factor_map_grid").data_stage is DataStage.INTERMEDIATE
        assert policy_for("factor_map_grid").retention_class == "recomputable"
        assert policy_for("map_product").data_stage is DataStage.OUTPUT
        # EPHEMERAL/CACHE 绝不入库
        for kind in ("render_temp_svg", "workflow_checkpoint",
                     "seismic_attribute_temp", "atomic_write_tmp"):
            assert policy_for(kind).must_register is False
            assert policy_for(kind).data_stage is None
        assert policy_for("north_arrow_cache").artifact_class == CLASS_CACHE
        assert policy_for("render_temp_svg").artifact_class == CLASS_EPHEMERAL

    def test_unknown_kind_falls_back_to_intermediate(self):
        policy = policy_for("brand_new_kind")
        assert policy.must_register is True
        assert policy.data_stage is DataStage.INTERMEDIATE
        assert "brand_new_kind" in policy.rationale

    def test_ephemeral_never_a_data_stage(self):
        # DataStage 词汇只有四值；EPHEMERAL 只活在 policy 层
        from paleo_workbench.catalog.intermediate_policy import (
            CLASS_DERIVED,
            CLASS_OUTPUT,
        )

        assert CLASS_EPHEMERAL not in {s.value for s in DataStage}
        assert {CLASS_EPHEMERAL, CLASS_CACHE, CLASS_INTERMEDIATE,
                CLASS_DERIVED, CLASS_OUTPUT} >= set(
            {p.artifact_class for p in KNOWN_ARTIFACT_POLICIES.values()})


# ---------------------------------------------------------------------------
# P1-d: order key persistence roundtrip (pure)


class TestOrderKeyRoundtrip:
    def test_keys_survive_state_tree_roundtrip(self):
        """用户重排 → 期望树 → 持久化 → 重载 → 重建同一顺序（V13 W-K）。"""
        from types import SimpleNamespace

        state = MappingWorkspaceState()
        controller = LayerGroupController(state)
        controller.register_layer("a", LayerRole.INITIAL_FACIES_DRAFT)
        controller.register_layer("b", LayerRole.INITIAL_FACIES_DRAFT)
        snapshots = [
            SimpleNamespace(id="a", name="A"),
            SimpleNamespace(id="b", name="B"),
        ]
        # 用户把 b 拖到 a 上方（桥观察 payload：root 平铺序）
        accepted = controller.observe_tree_nodes([
            {"type": "layer", "id": "b"},
            {"type": "layer", "id": "a"},
        ])
        assert accepted
        desired = controller.build_desired_tree(snapshots)
        assert list(desired.iter_layers()) == ["b", "a"]
        # 键已分配（观察序 → 稳定键）
        assert controller._order_keys.get("a") and controller._order_keys.get("b")
        assert controller._order_keys["b"] < controller._order_keys["a"]
        # 持久化 → 重载 → 键保真 → 重建同一顺序
        state.tree = desired.to_dict()
        reloaded_state = MappingWorkspaceState.from_dict(state.to_dict())
        controller2 = LayerGroupController(reloaded_state)
        controller2.register_layer("a", LayerRole.INITIAL_FACIES_DRAFT)
        controller2.register_layer("b", LayerRole.INITIAL_FACIES_DRAFT)
        controller2.reload_from_state()
        # 用户层键保真（重载树还带系统组模板键，断言子集）
        assert controller2._order_keys["a"] == controller._order_keys["a"]
        assert controller2._order_keys["b"] == controller._order_keys["b"]
        desired2 = controller2.build_desired_tree(snapshots)
        assert list(desired2.iter_layers()) == ["b", "a"]
