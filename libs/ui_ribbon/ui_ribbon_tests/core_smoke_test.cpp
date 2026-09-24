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
    // Two-page shell: 数据管理 / 编图 — the three stages are modes
    // inside 编图 (authoring_mode_* below).
    CHECK(kWorkspaceCount == 2);
    CHECK(kWorkspaceOrder.size() == 2);
    const Workspace expected[] = {
        Workspace::DataManagement,
        Workspace::Authoring,
    };
    for (int i = 0; i < kWorkspaceCount; ++i) {
        CHECK(kWorkspaceOrder[static_cast<size_t>(i)] == expected[i]);
    }
    CHECK(std::string(workspace_label(Workspace::DataManagement)) ==
          "数据管理");
    CHECK(std::string(workspace_label(Workspace::Authoring)) == "编图");

    // id round-trip + tolerant lookups.
    for (const auto workspace : kWorkspaceOrder) {
        const auto id = workspace_from_id(workspace_id(workspace));
        CHECK(id.has_value() && *id == workspace);
        const auto label = workspace_from_label(workspace_label(workspace));
        CHECK(label.has_value() && *label == workspace);
    }
    CHECK(!workspace_from_id("nope").has_value());
    CHECK(!workspace_from_label("nope").has_value());
    // Retired five-workspace ids never resurrect.
    CHECK(!workspace_from_id("predict").has_value());
    CHECK(!workspace_from_id("validation").has_value());
}

PWB_TEST(workspace_stage_mapping) {
    // D1 preserved: NEITHER page rewrites the stage — the 编图 modes do
    // it through the mode.* toggle commands.
    CHECK(!workspace_stage(Workspace::DataManagement).has_value());
    CHECK(!workspace_stage(Workspace::Authoring).has_value());
    // Every stage lives inside 编图 as a mode.
    CHECK(workspace_for_stage(MappingStage::FaciesCalibration) ==
          Workspace::Authoring);
    CHECK(workspace_for_stage(MappingStage::ConstraintFactor) ==
          Workspace::Authoring);
    CHECK(workspace_for_stage(MappingStage::IntegratedCompilation) ==
          Workspace::Authoring);
}

PWB_TEST(authoring_mode_vocabulary) {
    // mode.* toggle command ids ⇄ MappingStage (kStageOrder coverage).
    for (const auto stage : pwb::tool_policy::kStageOrder) {
        const char* id = authoring_mode_command_id(stage);
        CHECK(id != nullptr);
        const auto parsed = authoring_mode_for_command(id);
        CHECK(parsed.has_value() && *parsed == stage);
    }
    CHECK(std::string(
              authoring_mode_command_id(MappingStage::FaciesCalibration)) ==
          "mode.predict");
    CHECK(std::string(
              authoring_mode_command_id(MappingStage::ConstraintFactor)) ==
          "mode.factor");
    CHECK(std::string(
              authoring_mode_command_id(
                  MappingStage::IntegratedCompilation)) == "mode.author");
    CHECK(!authoring_mode_for_command("nope").has_value());

    // Every mode projects a non-empty group set; the toggle ids are
    // declared in the 编图 static band (group author_mode).
    for (const auto stage : pwb::tool_policy::kStageOrder) {
        const auto groups = authoring_mode_groups(stage);
        CHECK(!groups.empty());
        for (const auto& group : groups) {
            CHECK(!group.commands.empty());
            CHECK(!group.id.empty());
            CHECK(!group.label.empty());
        }
    }
    CHECK(find_group(Workspace::Authoring, "author_mode") != nullptr);
    CHECK(find_command("mode.predict") != nullptr);
    // The retired stage-workspace commands live in the mode groups —
    // the global lookup still resolves them.
    CHECK(find_command("predict.run") != nullptr);
    CHECK(find_command("factor.compute") != nullptr);
    CHECK(find_command("map.select") != nullptr);
}

// ---------------------------------------------------------------- table

PWB_TEST(command_group_table_structure) {
    const auto& specs = workspace_specs();
    CHECK(specs.size() == 2);
    for (size_t i = 0; i < specs.size(); ++i) {
        CHECK(specs[i].workspace == kWorkspaceOrder[i]);
    }
    // 数据管理 5 组原样保留；编图静态带 = 编图模式 toggle 组 + 常驻
    // 输出组（模式的命令集在 authoring_mode_groups，按模式注入）。
    const size_t expected_groups[] = {5, 2};
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
    CHECK(find_command(Workspace::Authoring, "data.import") == nullptr);
    CHECK(find_command(Workspace::Authoring, "mode.predict") != nullptr);
    CHECK(find_command("no.such") == nullptr);
    CHECK(find_group(Workspace::Authoring, "map_output") != nullptr);
    CHECK(find_workspace_spec("authoring") != nullptr);
    CHECK(find_workspace_spec("nope") == nullptr);
}

PWB_TEST(command_table_integrity) {
    // Healthy table: unique ids (mode groups share the pool), one
    // primary per workspace spec, the declared primary resolves to a
    // Primary-kind command.
    const auto problems = table_integrity_problems();
    for (const auto& problem : problems) {
        std::fprintf(stderr, "  integrity: %s\n", problem.c_str());
    }
    CHECK(problems.empty());

    // The per-workspace default primary actions (R:29).
    const auto& specs = workspace_specs();
    CHECK(specs[0].primary_command_id == "data.import");
    CHECK(specs[1].primary_command_id == "map.export");
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
    // Mode primaries stay distinct: 智能预测/单因素 each declare one in
    // their mode set; 编图 mode's primary is the static map.export.
    const auto count_primaries = [](MappingStage stage) {
        int n = 0;
        for (const auto& group : authoring_mode_groups(stage)) {
            for (const auto& command : group.commands) {
                if (command.kind == CommandKind::Primary) ++n;
            }
        }
        return n;
    };
    CHECK(count_primaries(MappingStage::FaciesCalibration) == 1);
    CHECK(count_primaries(MappingStage::ConstraintFactor) == 1);
    CHECK(count_primaries(MappingStage::IntegratedCompilation) == 0);
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
    // 数据管理带保持原密度；编图静态带刻意轻（模式组 + 输出组）——
    // 命令面的大头在按模式注入的上下文组里。
    CHECK(overflow_count(specs[0]) >= 3);
    CHECK(command_count(specs[0]) >= 8);
    CHECK(command_count(specs[1]) >= 5);
    for (const auto stage : pwb::tool_policy::kStageOrder) {
        int mode_commands = 0;
        for (const auto& group : authoring_mode_groups(stage)) {
            mode_commands += static_cast<int>(group.commands.size());
        }
        CHECK(mode_commands >= 8);
    }
    // M6: every command carries an icon asset (the declared map.opacity
    // gap closed with rb-opacity.svg in the repo set) — mode groups
    // included (the aggregate scan covers them).
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
