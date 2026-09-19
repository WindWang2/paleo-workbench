// UI-12 — Qt-free core semantic tests (headless). Pins the Python
// contracts of mode_state / state_language / ui_context / tool_surface /
// action_help / explorer_spec / inspector_spec / task_projection /
// agent_plan / stage_actions / keybinding_intent / log_buffer.

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_workstation/action_help.hpp>
#include <pwb/ui_workstation/agent_plan.hpp>
#include <pwb/ui_workstation/explorer_spec.hpp>
#include <pwb/ui_workstation/inspector_spec.hpp>
#include <pwb/ui_workstation/keybinding_intent.hpp>
#include <pwb/ui_workstation/log_buffer.hpp>
#include <pwb/ui_workstation/mode_state.hpp>
#include <pwb/ui_workstation/stage_actions.hpp>
#include <pwb/ui_workstation/state_language.hpp>
#include <pwb/ui_workstation/task_projection.hpp>
#include <pwb/ui_workstation/tool_surface.hpp>
#include <pwb/ui_workstation/ui_context.hpp>

#include "ui_workstation_test.hpp"

using namespace pwb::ui_workstation;
namespace tp = pwb::tool_policy;

// ---------------------------------------------------------------- FSM

PWB_TEST(mode_state_tool_activation_and_esc) {
    ModeStateMachine m;
    std::vector<WorkstationMode> seen;
    m.on_mode_changed = [&](WorkstationMode mode) {
        seen.push_back(mode);
    };
    m.dispatch_tool_activated("draw_polygon");
    CHECK(m.mode() == WorkstationMode::Digitizing);
    m.dispatch_tool_activated("vertex");
    CHECK(m.mode() == WorkstationMode::AdjustingBoundary);
    m.dispatch(ModeEvent::Esc);
    CHECK(m.mode() == WorkstationMode::Idle);
    CHECK(seen.size() == 3);  // real transitions only
}

PWB_TEST(mode_state_time_travel_roundtrip) {
    ModeStateMachine m;
    m.dispatch_tool_activated("draw");
    m.dispatch(ModeEvent::ScrubStart);
    CHECK(m.mode() == WorkstationMode::TimeTravelling);
    // Tool activation is REJECTED while travelling (no mode change).
    m.dispatch_tool_activated("vertex");
    CHECK(m.mode() == WorkstationMode::TimeTravelling);
    m.dispatch(ModeEvent::EpochCommit);
    CHECK(m.mode() == WorkstationMode::Digitizing);  // pre-travel mode
}

PWB_TEST(mode_state_pan_held_is_transient) {
    ModeStateMachine m;
    m.dispatch_tool_activated("draw");
    m.dispatch(ModeEvent::PanHeld);
    CHECK(m.pan_held());
    CHECK(m.mode() == WorkstationMode::Digitizing);  // unchanged
    m.dispatch(ModeEvent::PanReleased);
    CHECK(!m.pan_held());
}

PWB_TEST(mode_state_qc_hub) {
    ModeStateMachine m;
    m.dispatch(ModeEvent::QcHubActivated);
    CHECK(m.mode() == WorkstationMode::InspectingQc);
    m.dispatch(ModeEvent::QcHubClosed);
    CHECK(m.mode() == WorkstationMode::Idle);
    CHECK_EQ(std::string(m.hint_text()),
             "浏览：Space 平移 · Z/X 缩放 · Tab 循环要素 · Ctrl+D 吸属性");
}

PWB_TEST(mode_state_no_signal_on_self_loop) {
    ModeStateMachine m;
    int emissions = 0;
    m.on_mode_changed = [&](WorkstationMode) { ++emissions; };
    m.dispatch(ModeEvent::Esc);         // already idle — no signal
    m.dispatch(ModeEvent::PanHeld);     // transient — no signal
    CHECK(emissions == 0);
}

// ------------------------------------------------------- state_language

PWB_TEST(state_language_unknown_is_honest) {
    const StateToken t = state_token("maturity", "bogus-value");
    CHECK_EQ(t.glyph, "·");
    CHECK_EQ(t.label, "未知");
    CHECK_EQ(t.tone, "muted");
}

PWB_TEST(state_language_tone_badge_bridge) {
    CHECK_EQ(tone_to_badge("ok"), "success");
    CHECK_EQ(tone_to_badge("info"), "primary");
    CHECK_EQ(tone_to_badge("warn"), "warning");
    CHECK_EQ(tone_to_badge("error"), "error");
    CHECK_EQ(tone_to_badge("muted"), "neutral");
    CHECK_EQ(tone_to_badge("locked"), "neutral");
}

PWB_TEST(state_language_known_category) {
    const StateToken t = state_token("task", "running");
    CHECK(!t.label.empty());
    CHECK_EQ(t.glyph, std::string(state_token("task", "running").glyph));
}

PWB_TEST(state_language_context_text_fallbacks) {
    // No project → honest closed text.
    UIContextSnapshot snap;
    CHECK_EQ(workbench_context_text(snap), "未打开工程");
    // Stage + blocked edit target + native backend + running tasks.
    snap.project_open = true;
    snap.mapping_stage_label = "相图·L1";
    snap.active_layer_id = "l1";
    snap.active_layer_editable = false;
    snap.active_layer_block_reason = "角色门控";
    snap.qgis_bridge_available = true;
    snap.running_task_count = 2;
    const std::string text = workbench_context_text(
        snap, [](const std::string&) { return std::string("相图层"); });
    CHECK(text.find("相图·L1") != std::string::npos);
    CHECK(text.find("角色门控") != std::string::npos);
    CHECK(text.find("QGIS 原生") != std::string::npos);
    CHECK(text.find("2") != std::string::npos);
}

// ----------------------------------------------------------- ui_context

PWB_TEST(ui_context_defaults_and_providers) {
    UIContextService svc;
    const auto snap = svc.snapshot();
    CHECK(!snap.project_open);
    CHECK(!snap.mapping_stage.has_value());
    CHECK(snap.running_task_count == 0);

    svc.set_provider("project_open", [] { return UIContextFieldValue{true}; });
    svc.set_provider("project_name",
                     [] { return UIContextFieldValue{std::string("测试")}; });
    const auto snap2 = svc.snapshot();
    CHECK(snap2.project_open);
    CHECK(snap2.project_name.value_or("") == "测试");
}

PWB_TEST(ui_context_unknown_provider_name_throws) {
    UIContextService svc;
    bool threw = false;
    try {
        svc.set_provider("no_such_field", [] { return UIContextFieldValue{}; });
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(ui_context_exception_degrades_to_unknown) {
    UIContextService svc;
    svc.set_provider("project_name", []() -> UIContextFieldValue {
        throw std::runtime_error("provider down");
    });
    const auto snap = svc.snapshot();
    CHECK(!snap.project_name.has_value());  // fail-closed
}

PWB_TEST(ui_context_refresh_emits_only_on_change) {
    UIContextService svc;
    int emissions = 0;
    svc.set_change_listener(
        [&](const UIContextSnapshot&) { ++emissions; });
    bool open = false;
    svc.set_provider("project_open",
                     [&] { return UIContextFieldValue{open}; });
    svc.refresh();
    // Python parity: _last starts None → first refresh always emits.
    CHECK(emissions == 1);
    svc.refresh();
    CHECK(emissions == 1);  // identical snapshots → silent
    open = true;
    svc.refresh();
    CHECK(emissions == 2);
}

// ---------------------------------------------------------- tool_surface

PWB_TEST(tool_surface_delegates_to_tool_policy) {
    UIContextSnapshot snap;
    snap.project_open = true;
    const auto ctx = tool_context_from_ui_snapshot(snap);
    const auto availability = availability_for_context(ctx);
    // Canonical evaluator output — the adapter adds nothing.
    const auto canonical = tp::evaluate_all(ctx);
    CHECK(availability.size() == canonical.size());
}

PWB_TEST(tool_surface_layer_facts_write_back) {
    tp::ToolContextSnapshot ctx;
    LayerCapabilitySnapshot layer;
    layer.layer_id = "uv1";
    layer.kind = "polygon";
    layer.name = "编修";
    layer.frozen = true;
    apply_layer_facts(layer, ctx);
    CHECK_EQ(ctx.active_layer_id, "uv1");
    CHECK_EQ(ctx.active_layer_kind, "polygon");
    CHECK_EQ(ctx.layer_name, "编修");
    CHECK(ctx.layer_frozen);
}

// ------------------------------------------------------------ action_help

PWB_TEST(action_help_explain_uses_evaluator) {
    tp::ToolContextSnapshot ctx;
    const auto help = explain("identify", ctx, "L1");
    CHECK(help.tool_id == "identify");
    CHECK_EQ(help.current_layer, "L1");
    // No stage → legacy caption.
    CHECK_EQ(help.current_stage, "无阶段语义（legacy 表面）");
    const std::string tip = format_tooltip(help);
    CHECK(!tip.empty());
}

PWB_TEST(action_help_unknown_tool_is_honest) {
    tp::ToolContextSnapshot ctx;
    const auto help = explain("no_such_tool", ctx);
    CHECK_EQ(help.label, "no_such_tool");
    CHECK_EQ(help.requirements, "未知工具");
    const std::string details = format_details(help);
    CHECK(details.find("前置条件") != std::string::npos);
}

// ---------------------------------------------------------- explorer_spec

PWB_TEST(explorer_spec_project_mode_groups) {
    ExplorerFacts facts;
    facts.project_open = true;
    facts.project_name = "Demo";
    facts.workarea_name = "工区A";
    facts.target_horizon = "D63";
    facts.wells = {{"w1", "井1"}, {"w2", "井2"}};
    facts.resources = {{"r1", "s1.segy", "seismic", "data/s1.segy",
                        "segy", "ok", nullptr},
                       {"r2", "meta.json", "document", "meta.json",
                        "json", "ok", nullptr}};  // hidden
    const auto spec = build_explorer_spec("project", facts);
    CHECK(spec.roots.size() == 1);
    CHECK(spec.roots[0].key == "project");
    CHECK(spec.footer.find("2 口井") != std::string::npos);
    CHECK(spec.footer.find("1 个地震体") != std::string::npos);
    // area → group/wells with 2 children.
    const auto& area = spec.roots[0].children[1];
    bool found_wells = false;
    for (const auto& g : area.children) {
        if (g.key == "group/wells") {
            found_wells = true;
            CHECK(g.children.size() == 2);
            CHECK_EQ(g.children[0].label, "井1");
        }
    }
    CHECK(found_wells);
}

PWB_TEST(explorer_spec_no_project_footer) {
    ExplorerFacts facts;
    const auto spec = build_explorer_spec("project", facts);
    CHECK_EQ(spec.footer, "未打开工程");
}

PWB_TEST(explorer_spec_workspaces_navigation) {
    ExplorerFacts facts;
    const auto spec = build_explorer_spec("workspaces", facts);
    CHECK(spec.roots.size() == 2);
    bool has_nav = false;
    for (const auto& g : spec.roots[1].children) {
        if (g.navigation.has_value()) has_nav = true;
    }
    CHECK(has_nav);
}

PWB_TEST(explorer_spec_row_cap) {
    ExplorerFacts facts;
    facts.project_open = true;
    for (int i = 0; i < 6000; ++i) {
        facts.wells.push_back({std::to_string(i), "W" + std::to_string(i)});
    }
    const auto spec = build_explorer_spec("project", facts);
    const auto& area = spec.roots[0].children[1];
    for (const auto& g : area.children) {
        if (g.key == "group/wells") {
            CHECK(g.children.size() == 5001);  // cap + truncation tail
            CHECK_EQ(g.children.back().key, "group/wells/truncated");
        }
    }
}

PWB_TEST(explorer_mode_normalization) {
    CHECK_EQ(normalize_explorer_mode("bogus"), "project");
    CHECK_EQ(normalize_explorer_mode("data"), "data");
}

// --------------------------------------------------------- inspector_spec

PWB_TEST(inspector_document_empty_state) {
    const auto doc = empty_inspector_document();
    CHECK_EQ(doc.header, "检查器");
    CHECK(doc.properties_rows.size() == 1);
    CHECK_EQ(doc.properties_rows[0].second, "未选择对象");
}

PWB_TEST(inspector_document_feature) {
    InspectorPayload p;
    p.kind = "feature";
    p.fields = {{"feature_id", "f42"}, {"layer_name", "相图"},
                {"geometry_type", "Polygon"}, {"editable", "1"},
                {"source", "identify"}};
    const auto doc = build_inspector_document(p);
    CHECK(doc.header.find("要素") != std::string::npos);
    CHECK(doc.feature_assign_button);
    bool saw_geom = false;
    for (const auto& [label, value] : doc.properties_rows) {
        if (label == "几何" && value == "面") saw_geom = true;
    }
    CHECK(saw_geom);
    // Style page: feature kind → honest no-style text.
    CHECK(!doc.style_edit_visible);
}

PWB_TEST(inspector_document_layer_style_edit) {
    InspectorPayload p;
    p.kind = "layer";
    p.fields = {{"layer_type", "编修图层"}, {"layer_id", "uv1"},
                {"name", "编修"}, {"visible", "1"}};
    p.list_counts["feature_count"] = 12;
    const auto doc = build_inspector_document(p);
    CHECK(doc.style_edit_visible);
    CHECK_EQ(doc.style_edit_layer_id, "uv1");
    CHECK(doc.style_summary.find("12 个要素") != std::string::npos);
}

PWB_TEST(inspector_document_unknown_kind_generic) {
    InspectorPayload p;
    p.kind = "mystery";
    p.fields = {{"alpha", "1"}, {"beta", "2"}};
    const auto doc = build_inspector_document(p);
    CHECK(doc.properties_rows.size() == 2);  // sorted scalar table
}

PWB_TEST(inspector_yes_no_and_missing) {
    CHECK(inspector_value_missing(""));
    CHECK(inspector_value_missing("—"));
    CHECK(!inspector_value_missing("v"));
    CHECK_EQ(inspector_yes_no("1"), "是");
    CHECK_EQ(inspector_yes_no("0"), "否");
    CHECK_EQ(inspector_yes_no(""), "");
}

// --------------------------------------------------------- task_projection

PWB_TEST(task_projection_op_adapter) {
    pwb::ui_shell::OperationRegistry reg;
    reg.begin("op1", "导入任务", "文件A", true, 100);
    reg.update("op1", 50, 100, "阶段二");
    const auto row = task_row_from_operation(*reg.record("op1"));
    CHECK_EQ(row.task_id, "op:op1");
    CHECK(row.registry_op);
    CHECK(row.state == pwb::job::JobState::running);
    CHECK(row.progress > 0.4 && row.progress < 0.6);
    CHECK(row.message->find("文件A") != std::string::npos);
    CHECK(row.message->find("阶段二") != std::string::npos);
}

PWB_TEST(task_projection_state_text) {
    TaskRow row;
    row.state = pwb::job::JobState::running;
    row.progress = 0.5;
    CHECK_EQ(task_state_text(row), "运行中 50%");
    row.cancel_requested = true;
    CHECK_EQ(task_state_text(row), "取消中");  // cancel wins
    row.state = pwb::job::JobState::degraded;
    row.cancel_requested = false;
    CHECK_EQ(task_state_text(row), "降级完成");
}

PWB_TEST(task_projection_menu_items) {
    TaskRow row;
    row.state = pwb::job::JobState::failed;
    row.task_id = "t1";
    const auto items = task_menu_items(row);
    bool retry = false, copy = false, details = false;
    for (const auto& i : items) {
        if (i.action == TaskMenuAction::Retry) retry = i.enabled;
        if (i.action == TaskMenuAction::CopyTaskId) copy = true;
        if (i.action == TaskMenuAction::Details) details = true;
    }
    CHECK(retry && copy && details);
    // Registry ops cannot retry (no spec).
    row.registry_op = true;
    for (const auto& i : task_menu_items(row)) {
        if (i.action == TaskMenuAction::Retry) CHECK(!i.enabled);
    }
}

PWB_TEST(task_projection_elapsed_format) {
    CHECK_EQ(format_task_elapsed(42.0), "42 s");
    CHECK_EQ(format_task_elapsed(125.0), "02:05");
}

PWB_TEST(task_projection_merge_orders_desc) {
    std::vector<pwb::job::JobSnapshot> jobs(2);
    jobs[0].job_id = "a";
    jobs[0].submitted_at = 10;
    jobs[1].job_id = "b";
    jobs[1].submitted_at = 20;
    const auto rows = build_task_rows(jobs, {});
    CHECK_EQ(rows[0].task_id, "b");
    CHECK_EQ(rows[1].task_id, "a");
    CHECK(active_task_count(rows) == 2);
}

// -------------------------------------------------------------- agent_plan

PWB_TEST(agent_plan_static_risks) {
    AgentPlanSpec plan;
    plan.action_id = "recipe.save";
    const auto risks = agent_plan_risks(plan);
    CHECK(risks.count(AgentRisk::Write));
    CHECK_EQ(agent_plan_risk_label(plan), "写入");
}

PWB_TEST(agent_plan_write_actions_fail_closed) {
    AgentPlanSpec plan;
    plan.action_id = "unregistered.mystery";
    // No resolver → every action treated as WRITE.
    const auto write = agent_plan_write_actions(plan);
    CHECK(write.size() == 1);
    // Registry that knows the action as READ → not a write action.
    const auto write2 = agent_plan_write_actions(
        plan, [](const std::string&) { return std::optional{AgentRisk::Read}; });
    CHECK(write2.empty());
}

PWB_TEST(agent_plan_grants_exact_set) {
    std::set<std::string> grants = {"a", "b"};
    CHECK(agent_write_granted_for(grants, {"a", "b"}));
    CHECK(agent_write_granted_for(grants, {"a"}));   // subset covered
    CHECK(!agent_write_granted_for(grants, {"a", "c"}));
}

PWB_TEST(agent_plan_allowed_risks) {
    CHECK(agent_allowed_risks(false).size() == 2);
    CHECK(agent_allowed_risks(true).count(AgentRisk::Write));
}

// ----------------------------------------------------------- stage_actions

PWB_TEST(stage_action_dispatch_vocabulary) {
    CHECK(is_known_stage_action("run_factor"));
    CHECK_EQ(stage_action_dispatch_key("run_factor"),
             "open_factor_workbench");
    CHECK_EQ(stage_action_dispatch_key("stage_qc"), "run_qa");
    CHECK(!is_known_stage_action("bogus"));
    CHECK(stage_action_requires_horizon("run_factor"));
    CHECK(!stage_action_requires_horizon("stage_save"));
}

PWB_TEST(stage_action_dispatch_gating) {
    // Horizon missing → refusal message, handler never runs.
    bool ran = false;
    const auto msg = dispatch_stage_action(
        "run_factor", false, {{"open_factor_workbench", [&] { ran = true; }}});
    CHECK_EQ(msg, kStageActionHorizonMessage);
    CHECK(!ran);
    // Unknown action → honest unknown message.
    CHECK_EQ(dispatch_stage_action("bogus", true, {}),
             "未知阶段动作：bogus");
    // Handler failure surfaces (never silent).
    const auto fail = dispatch_stage_action(
        "stage_save", true,
        {{"stage_save", [] { throw std::runtime_error("io"); }}});
    CHECK(fail.find("阶段动作失败（stage_save）") != std::string::npos);
}

PWB_TEST(facies_color_deterministic) {
    const auto c1 = facies_category_color("河道砂");
    const auto c2 = facies_category_color("河道砂");
    CHECK_EQ(c1, c2);
    CHECK_EQ(facies_category_color("河道砂", "#fff"), "#fff");
    std::map<std::string, std::string> known = {{"河道砂", "#123456"}};
    CHECK_EQ(facies_category_color("河道砂", "", known), "#123456");
}

// ------------------------------------------------------- keybinding_intent

PWB_TEST(keybinding_space_temporary_pan) {
    KeyEventFacts f;
    f.key = KeyCode::Space;
    f.active_tool_id = "draw_polygon";
    const auto d = interpret_key(f);
    CHECK(d.consumed);
    CHECK(d.intent == KeyIntent::BeginTemporaryPan);
    // Release restores.
    KeyEventFacts r;
    r.key = KeyCode::Space;
    r.type = KeyEventType::Release;
    r.pan_restore_pending = true;
    const auto rd = interpret_key(r);
    CHECK(rd.intent == KeyIntent::ReleaseTemporaryPan);
}

PWB_TEST(keybinding_text_input_first_refusal) {
    KeyEventFacts f;
    f.key = KeyCode::Space;
    f.text_input_focused = true;
    CHECK(!interpret_key(f).consumed);
}

PWB_TEST(keybinding_tab_scope) {
    CHECK(tab_cycle_scope_active("digitizing"));
    CHECK(tab_cycle_scope_active("adjusting"));
    CHECK(!tab_cycle_scope_active("idle"));
    KeyEventFacts f;
    f.key = KeyCode::Tab;
    f.mode_value = "idle";
    CHECK(!interpret_key(f).consumed);  // no focus-chain theft
    f.mode_value = "digitizing";
    const auto d = interpret_key(f);
    CHECK(d.consumed && d.intent == KeyIntent::CycleSelection);
}

PWB_TEST(keybinding_zoom_requires_no_modifiers) {
    KeyEventFacts f;
    f.key = KeyCode::KeyZ;
    CHECK(interpret_key(f).intent == KeyIntent::ZoomCenterIn);
    f.control = true;  // Ctrl+Z must NOT be swallowed
    CHECK(!interpret_key(f).consumed);
}

PWB_TEST(keybinding_escape_chain) {
    KeyEventFacts f;
    f.key = KeyCode::Escape;
    f.active_tool_id = "draw";
    f.active_tool_has_points = true;
    CHECK(interpret_key(f).intent == KeyIntent::EscapeCancelGesture);
    f.active_tool_has_points = false;
    f.onion_active = true;
    CHECK(interpret_key(f).intent == KeyIntent::EscapeEndOnion);
    f.onion_active = false;
    CHECK(interpret_key(f).intent == KeyIntent::EscapeDeactivateTool);
    f.active_tool_id = "";
    f.qc_hub_visible = true;
    CHECK(interpret_key(f).intent == KeyIntent::EscapeCloseQcHub);
    f.qc_hub_visible = false;
    CHECK(interpret_key(f).intent == KeyIntent::EscapeDispatchFsm);
}

// --------------------------------------------------------------- log_buffer

PWB_TEST(log_buffer_bounded_and_drains) {
    LogBuffer buffer(3);
    buffer.push("l1");
    buffer.push("l2");
    buffer.push("l3");
    buffer.push("l4");  // drops l1
    CHECK(buffer.pending_count() == 3);
    const auto lines = buffer.take_pending();
    CHECK(lines.size() == 3);
    CHECK_EQ(lines[0], "l2");
    CHECK(buffer.pending_count() == 0);
}

PWB_TEST(log_line_format) {
    CHECK_EQ(format_log_line("01:02:03", "INFO", "pwb", "hello"),
             "01:02:03 INFO    pwb: hello");
}

int main() { return pwb_test::run_all(); }
