// UI-18 — ui_ribbon core smoke (Qt-free): workspace registry order and
// stage mapping, command group table completeness (prototype five-page
// structure, unique ids, exactly one primary per workspace), the
// three-mode state machine (heights + temporary expansion), and the
// host-injected disabled-reason channel.

#include <string>
#include <vector>

#include <pwb/ui_ribbon/ribbon_spec.hpp>
#include <pwb/ui_ribbon/ribbon_state.hpp>

#include "ui_ribbon_test.hpp"

using namespace pwb::ui_ribbon;
using pwb::tool_policy::MappingStage;

namespace {

int command_count(const RibbonWorkspaceSpec& spec) {
    int count = 0;
    for (const auto& group : spec.groups) {
        count += static_cast<int>(group.commands.size());
    }
    return count;
}

int overflow_count(const RibbonWorkspaceSpec& spec) {
    int count = 0;
    for (const auto& group : spec.groups) {
        for (const auto& command : group.commands) {
            if (command.overflow) ++count;
        }
    }
    return count;
}

}  // namespace

// ---------------------------------------------------------------- registry

PWB_TEST(workspace_registry_fixed_order) {
    CHECK(kWorkspaceCount == 5);
    CHECK(kWorkspaceOrder.size() == 5);
    const Workspace expected[] = {
        Workspace::DataManagement,      Workspace::IntelligentPrediction,
        Workspace::ConstraintFactor,    Workspace::IntegratedCompilation,
        Workspace::Validation,
    };
    for (int i = 0; i < kWorkspaceCount; ++i) {
        CHECK(kWorkspaceOrder[static_cast<size_t>(i)] == expected[i]);
    }
    CHECK(std::string(workspace_label(Workspace::DataManagement)) == "数据管理");
    CHECK(std::string(workspace_label(Workspace::IntelligentPrediction)) ==
          "1 智能预测");
    CHECK(std::string(workspace_label(Workspace::ConstraintFactor)) ==
          "2 约束与单因素");
    CHECK(std::string(workspace_label(Workspace::IntegratedCompilation)) ==
          "3 综合编图");
    CHECK(std::string(workspace_label(Workspace::Validation)) == "验证");

    // id round-trip + tolerant lookups.
    for (const auto workspace : kWorkspaceOrder) {
        const auto id = workspace_from_id(workspace_id(workspace));
        CHECK(id.has_value() && *id == workspace);
        const auto label = workspace_from_label(workspace_label(workspace));
        CHECK(label.has_value() && *label == workspace);
    }
    CHECK(!workspace_from_id("nope").has_value());
    CHECK(!workspace_from_label("nope").has_value());
}

PWB_TEST(workspace_stage_mapping) {
    // The middle three workspaces ARE stage views (D1); 数据管理/验证
    // have no stage — entering them must not rewrite the stage.
    CHECK(!workspace_stage(Workspace::DataManagement).has_value());
    CHECK(!workspace_stage(Workspace::Validation).has_value());
    CHECK(workspace_stage(Workspace::IntelligentPrediction) ==
          MappingStage::FaciesCalibration);
    CHECK(workspace_stage(Workspace::ConstraintFactor) ==
          MappingStage::ConstraintFactor);
    CHECK(workspace_stage(Workspace::IntegratedCompilation) ==
          MappingStage::IntegratedCompilation);

    CHECK(workspace_for_stage(MappingStage::FaciesCalibration) ==
          Workspace::IntelligentPrediction);
    CHECK(workspace_for_stage(MappingStage::ConstraintFactor) ==
          Workspace::ConstraintFactor);
    CHECK(workspace_for_stage(MappingStage::IntegratedCompilation) ==
          Workspace::IntegratedCompilation);
}

// ---------------------------------------------------------------- table

PWB_TEST(command_group_table_structure) {
    const auto& specs = workspace_specs();
    CHECK(specs.size() == 5);
    for (size_t i = 0; i < specs.size(); ++i) {
        CHECK(specs[i].workspace == kWorkspaceOrder[i]);
    }
    // Group counts mirror the mockup's five pages:
    // 5 / 4 / 5 / 5 / 5 groups, every group non-empty with a label.
    const size_t expected_groups[] = {5, 4, 5, 5, 5};
    for (size_t i = 0; i < specs.size(); ++i) {
        CHECK(specs[i].groups.size() == expected_groups[i]);
        for (const auto& group : specs[i].groups) {
            CHECK(!group.commands.empty());
            CHECK(!group.label.empty());
            CHECK(!group.id.empty());
        }
    }
    // Lookup by workspace + id, and global by id.
    CHECK(find_command(Workspace::DataManagement, "data.import") != nullptr);
    CHECK(find_command(Workspace::Validation, "data.import") == nullptr);
    CHECK(find_command("verify.run") != nullptr);
    CHECK(find_command("no.such") == nullptr);
    CHECK(find_group(Workspace::ConstraintFactor, "factor_contour") !=
          nullptr);
    CHECK(find_workspace_spec("validation") != nullptr);
    CHECK(find_workspace_spec("nope") == nullptr);
}

PWB_TEST(command_table_integrity) {
    // Healthy table: unique ids, one primary per workspace, the declared
    // primary resolves to a Primary-kind command.
    const auto problems = table_integrity_problems();
    for (const auto& problem : problems) {
        std::fprintf(stderr, "  integrity: %s\n", problem.c_str());
    }
    CHECK(problems.empty());

    // The per-workspace default primary actions (R:29).
    const auto& specs = workspace_specs();
    CHECK(specs[0].primary_command_id == "data.import");
    CHECK(specs[1].primary_command_id == "predict.run");
    CHECK(specs[2].primary_command_id == "factor.compute");
    CHECK(specs[3].primary_command_id == "map.export");
    CHECK(specs[4].primary_command_id == "verify.run");
    for (const auto& spec : specs) {
        const auto* primary = find_command(spec.primary_command_id);
        CHECK(primary != nullptr);
        CHECK(primary->kind == CommandKind::Primary);
        int primaries = 0;
        for (const auto& group : spec.groups) {
            for (const auto& command : group.commands) {
                if (command.kind == CommandKind::Primary) ++primaries;
            }
        }
        CHECK(primaries == 1);
    }
}

PWB_TEST(command_table_flags) {
    // Toggle commands exist (联动/捕捉 — checkable, synced with the
    // canvas, never a second state) and overflow flags mark the compact
    // menu candidates.
    const auto* link = find_command("predict.link");
    CHECK(link != nullptr);
    CHECK(link->kind == CommandKind::Toggle);
    const auto* snap = find_command("factor.snap");
    CHECK(snap != nullptr);
    CHECK(snap->kind == CommandKind::Toggle);

    const auto& specs = workspace_specs();
    for (const auto& spec : specs) {
        // 设计稿五页 Ribbon 全直显 —— 无声明溢出；紧凑模式由
        // ribbon_bar 的按宽度自动降级兜底（非 primary 的末位命令
        // 在宽度不足时收进「更多」）。
        CHECK(overflow_count(spec) == 0);
        CHECK(command_count(spec) >= 8);   // 每区命令面足够覆盖旧菜单
    }
    // M6: every command carries an icon asset (the declared map.opacity
    // gap closed with rb-opacity.svg in the repo set).
    const auto gaps = commands_without_icon();
    CHECK(gaps.empty());
}

// ---------------------------------------------------------------- state

PWB_TEST(mode_state_transitions) {
    RibbonModeState state;
    CHECK(state.mode() == RibbonMode::Standard);
    CHECK(!state.compact());
    CHECK(!state.collapsed());
    CHECK(state.band_visible());

    CHECK(state.set_compact(true));
    CHECK(state.mode() == RibbonMode::Compact);
    CHECK(!state.set_compact(true));  // true-change contract
    CHECK(state.band_visible());

    CHECK(state.set_collapsed(true));
    CHECK(state.mode() == RibbonMode::Collapsed);
    CHECK(!state.band_visible());
    CHECK(state.effective_mode() == RibbonMode::Collapsed);
    // The compact preference survives the collapse.
    CHECK(state.compact());
    CHECK(state.toggle_collapsed());
    CHECK(state.mode() == RibbonMode::Compact);

    CHECK(state.set_collapsed(true));
    CHECK(state.toggle_compact());
    CHECK(state.mode() == RibbonMode::Collapsed);  // collapsed wins
    CHECK(state.toggle_collapsed());
    CHECK(state.mode() == RibbonMode::Standard);
}

PWB_TEST(mode_state_temporary_expansion) {
    RibbonModeState state;
    // Only meaningful while collapsed.
    state.set_temporarily_expanded(true);
    CHECK(!state.temporarily_expanded());
    CHECK(state.mode() == RibbonMode::Standard);

    CHECK(state.set_collapsed(true));
    state.set_temporarily_expanded(true);
    CHECK(state.temporarily_expanded());
    CHECK(state.band_visible());  // 点击标签临时展开
    CHECK(state.effective_mode() == RibbonMode::Standard);

    // Esc / command selection retracts.
    state.set_temporarily_expanded(false);
    CHECK(!state.temporarily_expanded());
    CHECK(!state.band_visible());

    // Any collapse-state change ends a temporary expansion.
    state.set_temporarily_expanded(true);
    CHECK(state.temporarily_expanded());
    CHECK(state.toggle_collapsed());  // uncollapse
    CHECK(!state.temporarily_expanded());
    CHECK(state.band_visible());  // fixed-open band now
    CHECK(state.effective_mode() == RibbonMode::Standard);

    // Collapsing again starts from a clean state.
    CHECK(state.set_collapsed(true));
    CHECK(!state.temporarily_expanded());
    CHECK(!state.band_visible());

    // A collapsed+compact ribbon temporarily expands into compact.
    CHECK(state.set_compact(true));
    state.set_temporarily_expanded(true);
    CHECK(state.effective_mode() == RibbonMode::Compact);
}

PWB_TEST(mode_metrics_ranges) {
    // R:21-23: 标准 76–96 / 紧凑 40–48 / 折叠不带命令带。
    const auto standard = metrics_for(RibbonMode::Standard);
    CHECK(standard.min_height == 76);
    CHECK(standard.max_height == 96);
    const auto compact = metrics_for(RibbonMode::Compact);
    CHECK(compact.min_height == 40);
    CHECK(compact.max_height == 48);
    const auto collapsed = metrics_for(RibbonMode::Collapsed);
    CHECK(collapsed.min_height == 0);
    CHECK(collapsed.max_height == 0);
}

// ---------------------------------------------------------------- gate

PWB_TEST(disabled_reason_channel) {
    CommandEvaluator evaluator =
        [](const std::string& id) -> CommandState {
        if (id == "predict.run") return CommandState{false, "任务正在进行"};
        if (id == "data.import") return CommandState{true, ""};
        return CommandState{};
    };
    const auto running = evaluate_command(evaluator, "predict.run");
    CHECK(!running.enabled);
    CHECK(running.reason == "任务正在进行");
    const auto ready = evaluate_command(evaluator, "data.import");
    CHECK(ready.enabled);
    CHECK(ready.reason.empty());
    // Unknown id -> default (enabled, no reason).
    const auto unknown = evaluate_command(evaluator, "map.export");
    CHECK(unknown.enabled);

    // No evaluator -> enabled: the channel is additive and never
    // fabricates a gate (the host QAction stays authoritative, D4).
    const CommandEvaluator none;
    const auto unwired = evaluate_command(none, "predict.run");
    CHECK(unwired.enabled);
    CHECK(unwired.reason.empty());
}

int main() {
    return ::pwb_test::run_all("ui_ribbon.core_smoke");
}
