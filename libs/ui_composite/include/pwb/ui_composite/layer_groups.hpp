#pragma once

// Port of paleo_workbench/mapping_workspace/layer_groups.py (UI-13):
// system-group registry with stable group ids, stage routing, role →
// home-group resolution and conservative legacy-project classification.
//
// Group identity is machine-readable (group_id), never display-name
// inference. The union tree holds all-stage system groups + user groups +
// factor groups; a layer appears exactly once (its home group) and stage
// switches are group-visibility deltas.
//
// Stage values reuse pwb::tool_policy::MappingStage (same vocabulary).
// Qt-free.

#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_composite {

using tool_policy::MappingStage;

// Shared base group (wells / workarea boundary / seismic area / reference
// geography) — visible in every stage.
inline constexpr const char* kBaseReferenceGroupId = "base.reference";
// Conservative fallback for legacy projects.
inline constexpr const char* kLegacyGroupId = "legacy.unclassified";
// Parent of per-task factor subgroups.
inline constexpr const char* kFactorRootGroupId = "phase2.factors";

// Known base-workarea layer id prefix (workarea_map_snapshot).
inline constexpr const char* kBaseLayerIdPrefix = "home_workarea:";

// 系统组模板（纯数据；实例化为 QGIS 组由 LayerGroupController 执行）。
struct GroupTemplate {
    std::string group_id;
    std::string title;
    // 联合树中的排序位置（小者在上；相邻间隔 10 便于插入）。
    int order = 0;
    // 该组在哪些阶段默认可见（阶段显隐 profile 的默认值来源）。
    std::set<MappingStage> stages;
    // 该组在哪些阶段默认锁定（禁止修改 child geometry；不影响显示）。
    std::set<MappingStage> locked_stages;
    std::string kind = "system";  // "system" | "user"
    // 父组 id（"" = 根）；factor 子组挂在 FACTOR_ROOT_GROUP_ID 下。
    std::string parent_id;
    std::string description;

    bool stage_visible(MappingStage stage) const {
        return stages.count(stage) != 0;
    }
    bool stage_locked(MappingStage stage) const {
        return locked_stages.count(stage) != 0;
    }

    bool operator==(const GroupTemplate&) const = default;
};

// 系统组注册表（联合树排序；order 小者在上 = 渲染在上）。
const std::vector<GroupTemplate>& system_group_templates();

const GroupTemplate* system_group_template(const std::string& group_id);

// 该阶段默认可见的系统组（含共享组），按联合树顺序。
std::vector<const GroupTemplate*> system_group_templates_for_stage(
    MappingStage stage);

// factor 任务 → 稳定组 id（绑定 factor_task_id，与显示名解耦）。
std::string factor_group_id(const std::string& factor_task_id);
std::string factor_group_title(const std::string& factor_name,
                               const std::string& factor_type = "");
bool is_factor_group(const std::string& group_id);
// factor.<task_id> → task_id（非 factor 组返回 nullopt）。
std::optional<std::string> factor_task_of_group(const std::string& group_id);

// 期次组前缀（时间轴差分切换的树侧投影）。
inline constexpr const char* kEpochGroupPrefix = "epoch.";
std::string epoch_group_id(const std::string& epoch_key);
bool is_epoch_group(const std::string& group_id);
// 期次组 id → 期次 key（非期次组返回 nullopt）。
std::optional<std::string> epoch_key_of_group(const std::string& group_id);

// factor 组内子层顺序（输入→栅格→等值线→分级→不确定性→QC）。
const std::vector<std::string>& factor_child_order();

// 角色 → home group id。
//
// factor 系角色在带 factor_task_id 时返回该任务的 factor 子组；
// QC/辅助角色带 stage 时按创建阶段路由；未知角色 → legacy 兜底组。
std::string home_group_for_role(const std::string& role_value,
                                std::optional<MappingStage> stage =
                                    std::nullopt,
                                const std::string& factor_task_id = "");

// 角色的阶段 membership（= 其 home 组的阶段集合；共享组=全阶段）。
// membership ≠ visibility。未知角色 → 全阶段。
std::set<MappingStage> stages_for_role(const std::string& role_value);

// 拖放校验：角色的图层能否移入目标系统组（V5 §51）。用户组/未知组
// 始终允许（只改变视觉组织）；语义不相容的系统组拒绝。
bool movable_into_system_group(const std::string& role_value,
                               const std::string& group_id);

// classify_layer_for_migration parity — duck-typed layer inputs passed
// explicitly so the classifier stays a pure domain function:
//   layer_id:       layer.id
//   metadata:       layer.metadata map (may be empty)
//   template_key:   metadata["template"] OR UserVectorLayer.template
//   geometry_type:  snapshot geometry type ("facies_polygon" …) or ""
// Returns (role_value, home_group_id, constraint_kind_value-or-"").
struct LayerClassification {
    std::string role;
    std::string home_group_id;
    std::string constraint_kind;
};
LayerClassification classify_layer_for_migration(
    const std::string& layer_id,
    const std::map<std::string, std::string>& metadata,
    const std::string& template_key,
    const std::string& geometry_type = "");

// 阶段默认组显隐 profile（组 id → 可见；首次进入阶段应用）。
std::map<std::string, bool> default_group_visibility(MappingStage stage);

}  // namespace pwb::ui_composite
