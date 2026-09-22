"""V10 capture-spec completion + snapping-authority consistency.

锁定：
- INTEGRATED_BOUNDARY / INTERPRETATION_ANNOTATION 补齐捕获语义（可编辑角色
  不再有 apply_capture_spec=None 的静默跳过）。
- FAULT_CONSTRAINT 三权威（capture_spec / snapping_profiles /
  geological_layer_spec）同向：topological=False + endpoint 参与。
"""

from __future__ import annotations

from paleo_workbench.mapping_workspace.capture_spec import capture_spec_for_role
from paleo_workbench.mapping_workspace.geological_layer_spec import spec_for_role
from paleo_workbench.mapping_workspace.layer_roles import LayerRole, ROLE_EDITABLE
from paleo_workbench.mapping_workspace.snapping_profiles import (
    recommended_profile_for_role,
)


def test_integrated_boundary_has_capture_spec():
    spec = capture_spec_for_role(LayerRole.INTEGRATED_BOUNDARY)
    assert spec is not None
    assert spec.geometry_kind == "line"
    assert spec.snapping_profile is not None
    # 综合相带边界与相带边界同簇（boundary：vertex+segment+intersection）
    assert {"vertex", "segment"} <= set(spec.snapping_profile.modes)
    assert spec.recommend_topological_editing is True


def test_interpretation_annotation_has_capture_spec():
    spec = capture_spec_for_role(LayerRole.INTERPRETATION_ANNOTATION)
    assert spec is not None
    assert spec.geometry_kind == "line"
    # 注记不做拓扑推荐
    assert spec.recommend_topological_editing is False


def test_every_editable_role_has_capture_spec():
    """ROLE_EDITABLE 成员要么有捕获语义，要么显式豁免（记录在案的少数）。"""
    missing = []
    for role_value in ROLE_EDITABLE:
        role = LayerRole(role_value)
        if capture_spec_for_role(role) is None:
            missing.append(role_value)
    # USER_GENERAL 有 spec；目前全部可编辑角色都有捕获语义或本测试失败提示缺口。
    assert missing == [], f"editable roles without capture specs: {missing}"


def test_fault_snapping_three_authorities_aligned():
    capture = capture_spec_for_role(LayerRole.FAULT_CONSTRAINT)
    profile = recommended_profile_for_role(LayerRole.FAULT_CONSTRAINT)
    layer_spec = spec_for_role(LayerRole.FAULT_CONSTRAINT)

    assert capture is not None and profile is not None
    assert capture.recommend_topological_editing is False
    assert profile.topological is False
    assert layer_spec.snapping_policy.topological is False
    # endpoint 参与捕捉（断层次生点语义）且三处 modes 一致声明
    assert "endpoint" in profile.modes
    assert "endpoint" in layer_spec.snapping_policy.modes
    assert {"vertex", "segment"} <= set(profile.modes)
