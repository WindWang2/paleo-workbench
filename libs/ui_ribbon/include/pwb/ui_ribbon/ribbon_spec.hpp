#pragma once

// UI-18 — Ribbon 五工作区 chrome, Qt-free core: workspace registry +
// data-driven command group table.
//
// M1 of docs/development/ribbon-five-workspaces/00-plan.md (D3): this
// library is pure data + derivation — no Qt, no CommandRegistry link, no
// domain authority. The design contract lives in
// docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/README.md:
//   * five workspaces in FIXED order (R:19/F:24): 数据管理 / 1 智能预测 /
//     2 约束与单因素 / 3 综合编图 / 验证;
//   * the middle three ARE stage views — they map onto the tool_policy
//     stage vocabulary (facies_calibration / constraint_factor /
//     integrated_compilation); 数据管理 and 验证 have no stage, so
//     entering them never rewrites ProjectSession::mapping_stage (D1);
//   * command ids are SEMANTIC PLACEHOLDERS ("data.import", ...) — M4
//     rebinds them to the real CommandRegistry ids. The table SHAPE
//     (icon name, text, primary/toggle/overflow flags) is what M1
//     freezes; the group structure mirrors the prototype's five pages
//     (prototypes/qt_ribbon_native/main.cpp:200-205) — structure only,
//     never its synthetic data, inline QSS or icon heuristics.

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
    IntelligentPrediction,
    ConstraintFactor,
    IntegratedCompilation,
    Validation,
};

// The Ribbon tab order (R:19). Never reorder — navigation indices are
// load-bearing once the host wires shortcuts 1..5 (M2).
inline constexpr std::array<Workspace, 5> kWorkspaceOrder = {
    Workspace::DataManagement,
    Workspace::IntelligentPrediction,
    Workspace::ConstraintFactor,
    Workspace::IntegratedCompilation,
    Workspace::Validation,
};
inline constexpr int kWorkspaceCount = 5;

// Stable ids ("data_management", "intelligent_prediction", ...) and the
// Chinese display labels ("数据管理", "1 智能预测", ...). Unknown input
// never fabricates: lookups return nullopt.
const char* workspace_id(Workspace workspace);
const char* workspace_label(Workspace workspace);
std::optional<Workspace> workspace_from_id(const std::string& id);
std::optional<Workspace> workspace_from_label(const std::string& label);

// Stage mapping (D1): the middle three workspaces are stage views;
// 数据管理/验证 return nullopt (entering them must not rewrite the stage).
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

// The five workspace specs in kWorkspaceOrder.
const std::vector<RibbonWorkspaceSpec>& workspace_specs();

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
