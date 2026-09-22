"""阶段上下文动作单一词表（V10 Milestone B：消除 profile/panel/dispatcher 三表漂移）。

V7 R2-F1 曾把面板/分派器收敛到 ``STAGE_CONTEXT_ACTIONS``，但
``StageToolProfile.context_actions`` 仍是平行手维护表（P1 的 mock 动作、
P2 的 create_constraint、P3 的 stage_qc 各自漂移）。V10 起词表落位领域层
（mapping_workspace），panel（ui.workstation.stage_actions）与 profile
（stage_profiles）都从这一份**派生**——结构上不再可能漂移。

内容仍是纯数据：``(action_id, label)`` 按阶段。可用性不在此处（执行前经
``STAGE_ACTION_TOOLS`` 映射到 canonical evaluator re-gate）。
"""
from __future__ import annotations

__all__ = [
    "STAGE_ACTION_TOOLS",
    "STAGE_CONTEXT_ACTIONS",
    "stage_context_action_ids",
    "stage_context_actions",
]


#: 阶段动作 → 工具面 tool id（有映射的阶段动作在执行前经 canonical
#: evaluator re-gate；palette 注册与执行分派共用这一份——阶段面板按钮
#: 不绕过 blocking/project 门禁）。
STAGE_ACTION_TOOLS: dict[str, str] = {
    "open_factor_workbench": "factor_workbench",
    "run_factor": "factor_workbench",
    "overlay_factor_results": "factor_overlay",
    "run_qa": "qa_run",
    "stage_qc": "qa_run",
    "assemble_map_product": "map_product_assemble",
}


#: 阶段上下文动作单一词表：``(action_id, label)`` 按阶段。
STAGE_CONTEXT_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "facies_calibration": (
        ("add_seismic_prediction_overlay", "叠加地震相预测"),
        ("add_well_prediction_overlay", "叠加测井相预测"),
        ("well_prediction_point_to_surface", "测井点到面"),
        ("run_well_facies_mock", "运行测井相预测（mock）"),
        ("run_seismic_facies_mock", "运行地震相面预测（mock）"),
        ("load_initial_facies", "加载初始相图"),
        ("create_facies_draft", "创建解释草稿"),
        ("stage_save", "保存阶段成果"),
    ),
    "constraint_factor": (
        ("open_factor_workbench", "单因素工作台"),
        ("overlay_factor_results", "叠加单因素结果"),
        ("commit_constraints", "提交约束版本"),
        ("stage_save", "保存阶段成果"),
    ),
    "integrated_compilation": (
        ("select_evidence", "选择证据版本"),
        ("freeze_input_set", "冻结证据版本"),
        ("run_fusion", "运行融合"),
        ("create_integrated_draft", "创建综合草稿"),
        ("run_qa", "运行 QA"),
        ("commit_interpretation", "提交综合解释"),
        ("assemble_map_product", "生成 MapProduct"),
    ),
}


def stage_context_actions(stage_value: str) -> tuple[tuple[str, str], ...]:
    """某阶段的上下文动作表（未知阶段 → 空表，fail-closed）。"""
    from paleo_workbench.mapping_workspace.stages import stage_from_value

    stage = stage_from_value(str(stage_value or ""))
    if stage is None:
        return ()
    return STAGE_CONTEXT_ACTIONS.get(stage.value, ())


def stage_context_action_ids(stage_value: str) -> tuple[str, ...]:
    """某阶段的上下文动作 id 序列（profile 派生用；未知阶段 → 空表）。"""
    return tuple(action_id for action_id, _label in stage_context_actions(stage_value))
