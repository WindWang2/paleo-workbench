#pragma once

// Port of paleo_workbench/mapping_workspace/stage_profiles.py (UI-13):
// StageProfile — 阶段的编排配置（纯数据注册表，便于单元测试）。
//
// Stage 与 WorkstationLayoutPreset 严格解耦（V5 §6）：
// * StageProfile 描述工作上下文（默认组显隐、默认编辑对象、工具集合、
//   推荐 dock 配置）；
// * WorkstationLayoutPreset 仍是用户窗口布局偏好；
// * 实际 dock 布局 = recommended_docks + 用户阶段布局 override
//   (QSettings)；阶段只「建议」首次 dock 组合，绝不锁死用户布局。
//
// Qt-free.

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_composite {

using tool_policy::MappingStage;

// 阶段工具集合（基础 pan/zoom/select/identify 永远保留，不在此列）。
struct StageToolProfile {
    // 本阶段可用的数字化/编辑动作 id（existing MapActionController
    // ids）。空集合 = 不做阶段过滤。
    std::vector<std::string> edit_actions;
    // 阶段专属上下文动作 id（V10 起从 stage_vocabulary 派生）。
    std::vector<std::string> context_actions;

    // 该编辑/数字化动作在本阶段是否可用（空集合 = 不做阶段过滤）。
    bool allows_edit_action(const std::string& action_id) const;

    bool operator==(const StageToolProfile&) const = default;
};

// 一个编图阶段的完整编排配置。
struct StageProfile {
    MappingStage stage = MappingStage::FaciesCalibration;
    // 阶段标题/说明（来自 MappingStage；冗余存储便于 profile 自足）。
    std::string label;
    std::string description;
    // 首次进入该阶段的组显隐默认（组 id → bool）。
    std::map<std::string, bool> group_visibility;
    // 默认激活的编辑目标角色（按优先级；首个已有图层的角色胜出）。
    std::vector<std::string> active_editing_roles;
    StageToolProfile tools;
    // 推荐 dock 配置（dock key → bool；只建议，不锁死）。
    std::map<std::string, bool> recommended_docks;
    // 就绪度检查项 id（readiness 中按 id 实现）。
    std::vector<std::string> readiness_checks;
    // 阶段切换时需要保护/锁定的组（证据锁定；显示不受影响）。
    std::vector<std::string> locked_groups;

    std::map<std::string, bool> default_visible_groups() const {
        return group_visibility;
    }
    std::vector<std::string> default_locked_groups() const {
        return locked_groups;
    }

    bool operator==(const StageProfile&) const = default;
};

// 取阶段 profile（调用方应已校验；未知阶段值在枚举层不可能出现——
// Python dict[key] KeyError 等价物是 std::out_of_range，但枚举穷举
// 全覆盖）。
const StageProfile& stage_profile(MappingStage stage);

// 全部阶段 profile，按工作流顺序。
const std::vector<const StageProfile*>& stage_profiles();

// 受阶段过滤治理的编辑动作全集 = 各阶段 edit_actions 并集。不在并集
// 内的动作（如 add_point）与基础导航/识别/选择动作一样不做阶段隐藏。
const std::set<std::string>& governed_edit_actions();

// 联合树中系统组的稳定排序（order 升序）。
std::vector<std::string> profile_group_order();

}  // namespace pwb::ui_composite
