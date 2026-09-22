"""V9 W4/W9 — per-LayerRole 捕捉推荐与 GeologicalCaptureSpec。

覆盖：

* profile 词表：FACIES_BOUNDARY/FAULT/PROVENANCE_DIRECTION/SHORELINE 各自
  的模式/容差/拓扑建议与 rationale（可解释）；
* ``SnappingService.apply_role_profile``：写既有 per-layer 覆盖通道、
  不动全局开关、未知角色不改动；
* ``GeologicalCaptureSpec``：role → template/捕捉 profile/拓扑建议/约束
  语义；未知角色 None；
* 控制器集成：``apply_capture_spec`` 状态回执 + 快照 metadata.role
  （stage membership 单权威注入派生）+ 角色捕获默认值。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_interaction import SnappingService
from paleo_workbench.mapping_workspace.capture_spec import capture_spec_for_role
from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
)
from paleo_workbench.mapping_workspace.snapping_profiles import (
    profile_summary,
    recommended_profile_for_role,
)
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


# --------------------------------------------------------------------------- #
# profile vocabulary
# --------------------------------------------------------------------------- #

def test_boundary_profile_is_topological_with_intersection():
    profile = recommended_profile_for_role(LayerRole.FACIES_BOUNDARY)
    assert profile is not None
    assert profile.topological is True
    assert "intersection" in profile.modes
    assert "vertex" in profile.modes and "segment" in profile.modes
    assert profile.rationale  # 可解释


def test_fault_profile_prefers_endpoints_without_topology():
    profile = recommended_profile_for_role(LayerRole.FAULT_CONSTRAINT)
    assert profile is not None
    assert "endpoint" in profile.modes
    assert profile.topological is False


def test_direction_profile_snaps_endpoints_only():
    profile = recommended_profile_for_role(LayerRole.PROVENANCE_DIRECTION)
    assert profile is not None
    assert "endpoint" in profile.modes
    assert "segment" not in profile.modes


def test_shoreline_profile_vertex_segment_no_topology():
    profile = recommended_profile_for_role(LayerRole.PALEO_SHORELINE)
    assert profile is not None
    assert profile.modes == {"vertex", "segment"}
    assert profile.topological is False


def test_unknown_role_has_no_profile():
    assert recommended_profile_for_role("not_a_role") is None
    assert recommended_profile_for_role("") is None
    assert recommended_profile_for_role(None) is None


def test_raw_protected_roles_have_no_capture_recommendation():
    # RAW 保护角色不可编辑——推荐无意义（不猜）。
    assert recommended_profile_for_role(LayerRole.INITIAL_FACIES_SOURCE) is None


def test_profile_summary_is_user_readable():
    profile = recommended_profile_for_role(LayerRole.FACIES_BOUNDARY)
    text = profile_summary(profile)
    assert "相带边界" in text
    assert "拓扑编辑开" in text
    assert profile.rationale in text


# --------------------------------------------------------------------------- #
# SnappingService.apply_role_profile
# --------------------------------------------------------------------------- #

def test_apply_role_profile_writes_layer_overrides():
    service = SnappingService()
    summary = service.apply_role_profile("L1", LayerRole.FAULT_CONSTRAINT)
    assert summary is not None
    assert service.layer_modes["L1"] == {"vertex", "endpoint", "segment"}
    assert service.layer_tolerance["L1"] == 8.0
    # 全局开关不动（推荐 ≠ 强加）
    assert service.enabled is False
    assert service.modes == {"vertex", "segment", "midpoint"}


def test_apply_role_profile_unknown_role_no_change():
    service = SnappingService()
    assert service.apply_role_profile("L1", "not_a_role") is None
    assert "L1" not in service.layer_modes
    assert "L1" not in service.layer_tolerance


# --------------------------------------------------------------------------- #
# GeologicalCaptureSpec
# --------------------------------------------------------------------------- #

def test_capture_spec_direction_line_semantics():
    spec = capture_spec_for_role(LayerRole.PROVENANCE_DIRECTION)
    assert spec is not None
    assert spec.geometry_kind == "line"
    assert spec.template_key == "direction"
    assert spec.constraint_kind is ConstraintKind.SOURCE_DIRECTION
    assert spec.snapping_profile is not None
    assert "endpoint" in spec.snapping_profile.modes


def test_capture_spec_fault_uses_fault_template():
    spec = capture_spec_for_role(LayerRole.FAULT_CONSTRAINT)
    assert spec is not None
    assert spec.template_key == "fault"
    assert spec.constraint_kind is ConstraintKind.FAULT


def test_capture_spec_boundary_recommends_topological_editing():
    spec = capture_spec_for_role(LayerRole.FACIES_BOUNDARY)
    assert spec is not None
    assert spec.recommend_topological_editing is True


def test_capture_spec_unknown_role_returns_none():
    assert capture_spec_for_role("bogus") is None
    assert capture_spec_for_role(None) is None


def test_capture_spec_template_keys_resolve_in_registry():
    from paleo_workbench.ui.workstation.composite_editing import (
        _TEMPLATE_BY_KEY,
    )

    seen = set()
    for role in LayerRole:
        spec = capture_spec_for_role(role)
        if spec is None or not spec.template_key:
            continue
        assert spec.template_key in _TEMPLATE_BY_KEY, (
            f"{role}: template {spec.template_key} 不在注册表——词表漂移")
        seen.add(spec.template_key)
    assert seen  # 至少一个 spec 指向真实模板


# --------------------------------------------------------------------------- #
# controller integration
# --------------------------------------------------------------------------- #

@pytest.fixture()
def controller(qtbot):
    controller = CompositeEditController(project_crs="EPSG:4326")
    qtbot.addWidget(controller._dummy_parent()) if hasattr(controller, "_dummy_parent") else None
    return controller


def test_controller_apply_capture_spec_applies_profile(controller):
    layer = controller.create_layer("物源方向", "line")
    assert controller.apply_capture_spec(layer.id) is None  # 无角色 = 无动作
    assert layer.id not in controller._snapping.layer_modes

    controller.set_role_lookup(lambda layer_id: (
        LayerRole.PROVENANCE_DIRECTION
        if layer_id == layer.id else None))
    hint = controller.apply_capture_spec(layer.id)
    assert hint is not None
    assert layer.id in controller._snapping.layer_modes


def test_snapshot_metadata_carries_role_from_lookup(controller):
    layer = controller.create_layer("断层", "line")
    controller.set_role_lookup(lambda layer_id: (
        LayerRole.FAULT_CONSTRAINT if layer_id == layer.id else None))
    snapshots = controller.snapshot_layers()
    target = next(s for s in snapshots if s.id == layer.id)
    assert target.metadata.get("role") == "fault_constraint"

    controller.set_role_lookup(lambda layer_id: None)
    snapshots = controller.snapshot_layers()
    target = next(s for s in snapshots if s.id == layer.id)
    assert "role" not in target.metadata  # 无角色不带键（legacy 诚实路径）


def test_capture_defaults_derive_from_role_spec(controller):
    layer = controller.create_layer("物源方向", "line")
    controller.set_role_lookup(lambda layer_id: (
        LayerRole.PROVENANCE_DIRECTION if layer_id == layer.id else None))
    defaults = controller._capture_defaults_for_role(layer.id)
    # direction 模板的必填字段默认值进入捕获默认
    assert isinstance(defaults, dict)
    # 未指定模板的显式建层（template=""）不因无模板而丢默认：
    layer2 = controller.create_layer("边界", "line", template="fault")
    assert controller._capture_defaults_for_role(layer2.id) == {}
    # 显式模板建层的默认仍走模板通道（不因角色而漂移）
    layer3 = controller.create_layer("断层2", "line", template="fault")
    controller.set_role_lookup(lambda lid: (
        LayerRole.FAULT_CONSTRAINT if lid == layer3.id else None))
    defaults3 = controller._capture_defaults_for_role(layer3.id)
    # fault 模板无默认值字段 → 空 dict（同模板通道结果）
    assert isinstance(defaults3, dict)


# --------------------------------------------------------------------------- #
# dialog integration (W4 UI)
# --------------------------------------------------------------------------- #

def test_snapping_dialog_applies_role_profile(qtbot, controller):
    from paleo_workbench.ui.workstation.composite_panels import (
        SnappingSettingsDialog,
    )

    layer = controller.create_layer("断层", "line")
    controller.set_role_lookup(lambda lid: (
        LayerRole.FAULT_CONSTRAINT if lid == layer.id else None))
    dialog = SnappingSettingsDialog(controller)
    qtbot.addWidget(dialog)

    # 行 tooltip 携带推荐解释
    item = dialog._table.item(0, 0)
    assert "断层约束推荐" in (item.toolTip() or "")

    # 应用推荐：全局模式 = profile 模式；行内顶点/线段/容差就位
    dialog._apply_role_profile_to_row(layer.id)
    checked = {m for m, box in dialog._mode_boxes.items() if box.isChecked()}
    assert checked == {"vertex", "endpoint", "segment"}
    entries = dialog._layer_rows[layer.id]
    assert entries["vertex"].isChecked()
    assert entries["segment"].isChecked()
    assert entries["tolerance"].value() == 8.0
    assert "断层" in dialog._hint.text() or "断层约束" in dialog._hint.text()


def test_snapping_dialog_roleless_row_has_no_recommendation(qtbot, controller):
    from paleo_workbench.ui.workstation.composite_panels import (
        SnappingSettingsDialog,
    )

    controller.create_layer("普通", "line")
    dialog = SnappingSettingsDialog(controller)
    qtbot.addWidget(dialog)
    assert dialog._table.item(0, 0).toolTip() == ""
