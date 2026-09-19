#pragma once

// Port of paleo_workbench/mapping_workspace/stage_vocabulary.py (UI-13):
// 阶段上下文动作单一词表（V10 Milestone B：消除 profile/panel/
// dispatcher 三表漂移）。
//
// 内容仍是纯数据：(action_id, label) 按阶段。可用性不在此处（执行前经
// STAGE_ACTION_TOOLS 映射到 canonical evaluator re-gate）。
//
// Qt-free.

#include <string>
#include <utility>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_composite {

using tool_policy::MappingStage;

// 阶段动作 → 工具面 tool id（有映射的阶段动作在执行前经 canonical
// evaluator re-gate；palette 注册与执行分派共用这一份——阶段面板按钮
// 不绕过 blocking/project 门禁）。无映射 → ""。
std::string stage_action_tool_id(const std::string& action_id);

// 某阶段的上下文动作表 (action_id, label)（未知阶段 → 空表，
// fail-closed）。
const std::vector<std::pair<std::string, std::string>>&
stage_context_actions(MappingStage stage);
std::vector<std::pair<std::string, std::string>> stage_context_actions(
    const std::string& stage_value);

// 某阶段的上下文动作 id 序列（profile 派生用；未知阶段 → 空表）。
std::vector<std::string> stage_context_action_ids(MappingStage stage);
std::vector<std::string> stage_context_action_ids(
    const std::string& stage_value);

}  // namespace pwb::ui_composite
