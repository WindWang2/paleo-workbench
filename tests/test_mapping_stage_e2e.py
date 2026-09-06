"""阶段工作流 E2E 测试（fallback 画布路径；覆盖 V5 §82–§85）。

* Stage1：初始相图 → RAW 叠加 → RAW→DERIVED 建稿 → 编辑保存 → RAW 不变。
* Stage2：typed 约束创建（图层 + ConstraintLayers 权威 + 组归属）。
* Stage3：证据选择 → 综合草稿 → 上游版本更新后 downstream STALE（不静默覆盖）。
* 保存/重开一致性（mapping_workspace + 图层内容）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import (
    PaleoMapDocument,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
)

QApplication.instance() or QApplication([])

_FACIES_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 0]]],
}


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def _project_with_initial_facies() -> ProjectDocument:
    project = ProjectDocument.new("E2E 相图")
    project.paleomap_documents.append(PaleoMapDocument(
        name="初始沉积相", linked_target_horizon="D63",
        facies_polygons=[
            {"geometry": dict(_FACIES_GEOMETRY),
             "properties": {"facies": "三角洲前缘"}},
            {"geometry": dict(_FACIES_GEOMETRY),
             "properties": {"facies": "滨浅湖"}},
        ]))
    return project


# ---------------------------------------------------------------------------
# Stage 1（§82）
# ---------------------------------------------------------------------------

def test_stage1_raw_to_derived_raw_never_modified(qtbot, monkeypatch):
    project = _project_with_initial_facies()
    doc = _composite(qtbot, monkeypatch, project)
    actions = doc.stage_actions

    # 1) 加载初始相图（RAW 叠加）。
    actions.load_initial_facies()
    raw_ids = doc.stage_controller.state.layers_with_role(
        LayerRole.INITIAL_FACIES_SOURCE)
    assert len(raw_ids) == 1
    raw = doc.edit_controller.layer(raw_ids[0])
    raw_feature_count = len(list(raw.features()))

    # 2) RAW→DERIVED 建稿。
    actions.create_facies_draft()
    draft_ids = doc.stage_controller.state.layers_with_role(
        LayerRole.INITIAL_FACIES_DRAFT)
    assert len(draft_ids) == 1
    draft = doc.edit_controller.layer(draft_ids[0])
    assert len(list(draft.features())) == raw_feature_count  # 草稿继承 RAW 内容

    # 3) 编辑草稿（新增要素 + 提交）。
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc.edit_controller.set_active_layer(draft.id)
    doc.edit_controller.start_editing()
    session = draft.edit_session
    session.add_feature(VectorFeature(
        feature_id="f-new",
        geometry={"type": "Polygon",
                  "coordinates": [[[10, 10], [12, 10], [12, 12], [10, 10]]]},
        attributes={"facies": "新增相带"}))
    session.commit_changes()

    # 4) RAW 不可变：要素数与几何保持，且编辑被门禁拒绝。
    assert len(list(raw.features())) == raw_feature_count
    messages = []
    doc.status_message.connect(messages.append)
    doc._toggle_layer_editing(raw.id)
    assert not raw.edit_session
    assert any("不可直接编辑" in message for message in messages)

    # 5) 保存 → 工程里 RAW 与 DERIVED 同时存在（多版本不覆盖）。
    doc.flush_edit_sessions()
    doc.edit_controller.sync_to_project(project)
    names = [layer.name for layer in project.user_vector_layers]
    assert any("原始" in name for name in names)
    assert any("校正稿" in name for name in names)


def test_stage1_reopen_restores_roles_and_stage(qtbot, monkeypatch):
    """保存 → 重开：RAW/DERIVED 角色与当前阶段一致（§82 reopen）。"""
    project = _project_with_initial_facies()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.load_initial_facies()
    doc.stage_actions.create_facies_draft()
    doc.flush_edit_sessions()
    doc.stage_controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    doc._sync_workspace_state_to_project()

    doc2 = _composite(qtbot, monkeypatch, project)
    controller = doc2.stage_controller
    assert controller.current_stage == MappingStage.CONSTRAINT_FACTOR
    assert controller.state.layers_with_role(LayerRole.INITIAL_FACIES_SOURCE)
    assert controller.state.layers_with_role(LayerRole.INITIAL_FACIES_DRAFT)


# ---------------------------------------------------------------------------
# Stage 2（§83）
# ---------------------------------------------------------------------------

def test_stage2_typed_constraint_creation(qtbot, monkeypatch):
    project = _project_with_initial_facies()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.create_constraint("fault")

    # 图层 + 角色 + typed kind。
    roles = doc.stage_controller.state.layers_with_role(LayerRole.FAULT_CONSTRAINT)
    assert len(roles) == 1
    record = doc.stage_controller.state.membership(roles[0])
    assert record.constraint_kind == "fault"

    # 工程 ConstraintLayers 权威同步登记（插值引擎语义 role=break）。
    lines = project.constraint_layers[0].lines
    assert any(line.role == "break" and
               line.properties.get("constraint_kind") == "fault"
               for line in lines)

    # 组归属（领域放置）。
    placement = doc.stage_controller.group_controller.placement_of(roles[0])
    assert placement == "phase2.constraints"


# ---------------------------------------------------------------------------
# Stage 3 + backward dependency（§85）
# ---------------------------------------------------------------------------

class _FakeVersion:
    def __init__(self, version_id, asset_id, version_number, run_id=""):
        self.id = version_id
        self.asset_id = asset_id
        self.version_number = version_number
        self.run_id = run_id


class _FakeRun:
    def __init__(self, run_id, input_version_ids):
        self.run_id = run_id
        self.input_version_ids = list(input_version_ids)


class _FakeCatalog:
    def __init__(self):
        self.versions = {}
        self.runs = {}
        self._asset_counters: dict[str, int] = {}

    def add_asset(self, asset_id, *version_ids):
        for version_id in version_ids:
            number = self._asset_counters.get(asset_id, 0) + 1
            self._asset_counters[asset_id] = number
            self.versions[version_id] = _FakeVersion(version_id, asset_id, number)

    def resolve_version(self, version_id):
        return self.versions.get(version_id)

    def resolve_run(self, run_id):
        return self.runs.get(run_id)

    def list_versions(self, *, stage=None, asset_id=None):
        return [v for v in self.versions.values() if v.asset_id == asset_id]


def test_backward_dependency_marks_stale_no_silent_replacement(qtbot, monkeypatch):
    """§85：Phase3 用 Factor v1 → Phase2 出 v2 → Phase3 标 STALE，旧结果保留。"""
    project = _project_with_initial_facies()
    doc = _composite(qtbot, monkeypatch, project)
    controller = doc.stage_controller

    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1")
    controller.attach_document(project, catalog)

    # Phase2/3 流程：draft 钉住 ver_1；综合解释引用 ver_1。
    actions = doc.stage_actions
    actions.load_initial_facies()
    actions.create_facies_draft()
    draft_ids = controller.state.layers_with_role(LayerRole.INITIAL_FACIES_DRAFT)
    record = controller.state.membership(draft_ids[0])
    record.source_version_id = "ver_1"

    controller.state.compilation_input_set["阶段1解释"] = "ver_1"
    actions.create_integrated_draft()
    integrated = controller.state.layers_with_role(LayerRole.INTEGRATED_FACIES)
    assert integrated

    controller.refresh_evaluation()
    assert controller.stale_summary.stale_count == 0

    # 回 Phase2：上游产出 v2（同一资产新版本）。
    catalog.add_asset("raw-asset", "ver_2")
    controller.refresh_evaluation()

    draft_entry = controller.stale_summary.get(f"phase1_draft:{draft_ids[0]}")
    integrated_entry = controller.stale_summary.get(f"integrated:{integrated[0]}")
    assert draft_entry is not None and draft_entry.status.value == "stale"
    assert integrated_entry is not None and integrated_entry.status.value == "stale"

    # 旧成果保留（不删除不覆盖）。
    assert doc.edit_controller.layer(draft_ids[0]) is not None
    assert doc.edit_controller.layer(integrated[0]) is not None
    # 阶段徽标带过期计数。
    assert "↑" in controller.readiness_badge()


# ---------------------------------------------------------------------------
# 保存 / 重开一致性（§49）
# ---------------------------------------------------------------------------

def test_project_manager_roundtrip_keeps_workspace_state(tmp_path, monkeypatch):
    from paleo_workbench.project.manager import ProjectManager

    project = _project_with_initial_facies()
    project.mapping_workspace = {
        "schema_version": 1,
        "current_stage": "integrated_compilation",
        "stage_states": {},
        "memberships": {
            "L1": {"layer_id": "L1", "role": "integrated_facies"}},
        "tree": {},
        "artifact_maturity": {"phase1_draft:L1": "reviewed"},
        "compilation_input_set": {"砂厚": "factor:f1:ver_9"},
    }
    path = tmp_path / "roundtrip.paleo.json"
    manager = ProjectManager(path)
    prepared = manager.prepare_save(project)
    assert prepared is not None
    manager.execute_save(prepared)

    loaded = manager.load()
    assert loaded.mapping_workspace["current_stage"] == "integrated_compilation"
    assert loaded.mapping_workspace["artifact_maturity"] == {
        "phase1_draft:L1": "reviewed"}
    assert loaded.mapping_workspace["compilation_input_set"]["砂厚"] == "factor:f1:ver_9"
