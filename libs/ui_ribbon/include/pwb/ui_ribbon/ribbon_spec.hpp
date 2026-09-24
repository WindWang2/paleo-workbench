#pragma once

// UI-18 — Ribbon 两页 chrome, Qt-free core: workspace registry +
// data-driven command group table.
//
// Two-page shell (docs/ui-redesign/two-page-shell-2026-09-24/README.md —
// supersedes the five-workspace table):
//   * TWO workspaces in FIXED order: 数据管理 / 编图;
//   * the former three stage workspaces (智能预测 / 约束与单因素 /
//     综合编图) are now MODES inside 编图 — they still map onto the
//     tool_policy stage vocabulary (facies_calibration /
//     constraint_factor / integrated_compilation) but the stage is
//     written by the 编图模式 toggle commands (mode.*), never by page
//     entry (D1: workspace_stage() returns nullopt for both pages);
//   * command ids are SEMANTIC PLACEHOLDERS ("data.import", "mode.predict",
//     ...) — the host rebinds them to the real CommandRegistry ids.

#include <array>
#include <optional>
#include <string>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_ribbon {

// ---------------------------------------------------------------------------
// Workspace registry (fixed order).
// ---------------------------------------------------------------------------

enum class Workspace {
    DataManagement,
    Authoring,
};

// The Ribbon tab order. Never reorder — navigation indices are
// load-bearing once the host wires shortcuts 1..2.
inline constexpr std::array<Workspace, 2> kWorkspaceOrder = {
    Workspace::DataManagement,
    Workspace::Authoring,
};
inline constexpr int kWorkspaceCount = 2;

// Stable ids ("data_management", "authoring") and the Chinese display
// labels ("数据管理", "编图"). Unknown input never fabricates: lookups
// return nullopt.
const char* workspace_id(Workspace workspace);
const char* workspace_label(Workspace workspace);
std::optional<Workspace> workspace_from_id(const std::string& id);
std::optional<Workspace> workspace_from_label(const std::string& label);

// Stage mapping (D1): page entry never rewrites the stage — both
// workspaces return nullopt; the three MappingStages all live INSIDE
// 编图 as modes (workspace_for_stage -> Authoring for every stage).
std::optional<tool_policy::MappingStage> workspace_stage(
    Workspace workspace);
std::optional<Workspace> workspace_for_stage(
    tool_policy::MappingStage stage);

// ---------------------------------------------------------------------------
// Command group table (data-driven; M4 fills the ids with real
// CommandRegistry commands).
// ---------------------------------------------------------------------------

// 主按钮 = 32px 大图标（标准模式图标在上、文字在下，最多两行）；
// 次级动作 = 16–20px 图标 + 文字；可勾选切换项与画布控件同步、不维护
// 第二份状态（R:31）。
enum class CommandKind {
    Primary,
    Secondary,
    Toggle,
};

struct RibbonCommand {
    std::string id;    // semantic placeholder; M4 -> CommandRegistry id
    std::string text;  // Chinese command label (prototype vocabulary)
    // icon_factory name ("folder-open.svg", "map/btn-import.svg"); empty
    // = declared asset gap -> QStyle fallback + gap report (M1 icon
    // inventory, plan §6-5).
    std::string icon;
    CommandKind kind = CommandKind::Secondary;
    // 紧凑模式空间不足时，标记的次级动作进组内溢出菜单（R:22）。
    bool overflow = false;
};

struct RibbonGroup {
    std::string id;
    std::string label;  // 组名（标准模式放命令带底部）
    std::vector<RibbonCommand> commands;
};

struct RibbonWorkspaceSpec {
    Workspace workspace = Workspace::DataManagement;
    // 每区唯一默认主动作（R:29）：导入数据 / 运行预测 / 计算单因素 /
    // 导出图件 / 运行验证。运行中的主动由宿主防重复提交。
    std::string primary_command_id;
    std::vector<RibbonGroup> groups;
};

// The two workspace specs in kWorkspaceOrder.
const std::vector<RibbonWorkspaceSpec>& workspace_specs();

// ---------------------------------------------------------------------------
// 编图 modes (in-page) — the three stage projections.
// ---------------------------------------------------------------------------

// The 编图模式 toggle command ids in the static band group
// ("mode.predict" / "mode.factor" / "mode.author"); the host binds them
// to an exclusive checkable QActionGroup that writes the stage
// authority. Unknown input -> nullptr / nullopt.
const char* authoring_mode_command_id(tool_policy::MappingStage stage);
std::optional<tool_policy::MappingStage> authoring_mode_for_command(
    const std::string& command_id);

// Per-mode command groups the host injects into the 编图 band as
// context groups (RibbonBar::set_context_group) when the mode changes.
// They carry the retired stage-workspace command vocabulary verbatim —
// command ids are unchanged so the M4 registry bindings still resolve.
std::vector<RibbonGroup> authoring_mode_groups(
    tool_policy::MappingStage stage);

const RibbonWorkspaceSpec& workspace_spec(Workspace workspace);
const RibbonWorkspaceSpec* find_workspace_spec(const std::string& id);

// Lookups (nullptr when absent). The id-only overload scans every
// workspace (host command routing + M4 rebind audit).
const RibbonCommand* find_command(Workspace workspace,
                                  const std::string& command_id);
const RibbonCommand* find_command(const std::string& command_id);
const RibbonGroup* find_group(Workspace workspace,
                              const std::string& group_id);

// Table-integrity surface (tests + M4 rebind audit): every command id is
// unique across the whole table, every workspace declares exactly one
// primary, and the declared primary resolves to a Primary-kind command.
// Empty = healthy.
std::vector<std::string> table_integrity_problems();

// Icon-asset gap inventory (M1): commands declared WITHOUT an icon name.
// The Qt layer adds the runtime misses (asset absent behind the resource
// locator) to the same report.
std::vector<std::string> commands_without_icon();

}  // namespace pwb::ui_ribbon
