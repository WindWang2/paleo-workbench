// UI-16 — Qt-free core smoke: the registries reproduce the Python shot
// tables/vocabulary, the pure check bodies return the Python verdicts on
// synthetic snapshots, and the dual-volume prototype math matches the
// numpy reference (index order, clamp parity, uint8-truncated blending).

#include <cmath>
#include <map>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui_visualqa/dual_volume.hpp>
#include <pwb/ui_visualqa/qa_check.hpp>
#include <pwb/ui_visualqa/qa_checks.hpp>
#include <pwb/ui_visualqa/qa_snapshot.hpp>
#include <pwb/ui_visualqa/qa_states.hpp>

#include "ui_visualqa_test.hpp"

using namespace pwb::ui_visualqa;

namespace {

bool names_of(const std::vector<CheckResult>& results,
              const std::string& name) {
    for (const CheckResult& r : results) {
        if (r.name == name) return r.ok;
    }
    return false;
}

std::size_t count_checks(const std::vector<CheckResult>& results) {
    return results.size();
}

QaToolVerdict tool(bool enabled, std::string reason = "") {
    QaToolVerdict v;
    v.exists = true;
    v.enabled = enabled;
    v.disabled_reason = std::move(reason);
    return v;
}

QaActionState act(bool enabled, bool visible = true) {
    QaActionState a;
    a.exists = true;
    a.enabled = enabled;
    a.visible = visible;
    return a;
}

// A bound workstation baseline — individual tests override the fields
// their state's checks read.
WorkstationSnapshot bound_ws() {
    WorkstationSnapshot s;
    s.bound = true;
    return s;
}

}  // namespace

// ---------------------------------------------------------------------------
// Registries / vocabulary parity
// ---------------------------------------------------------------------------

PWB_TEST(v6_registry_parity) {
    const std::vector<std::string> want = {
        "mapping_stage_phase1", "mapping_stage_phase2",
        "mapping_stage_phase3", "command_palette_context",
        "write_grant_dialog",   "status_workbench_segment",
    };
    CHECK(v6_states() == want);
    CHECK_EQ(palette_context_filter(), std::string("单因素"));
    const std::vector<std::string> want_actions = {"map.add_layer",
                                                   "map.export"};
    CHECK(write_grant_action_ids() == want_actions);
    CHECK_EQ(static_cast<long long>(v6_shot_table().size()), 6);
    for (const QaShotEntry& e : v6_shot_table()) {
        CHECK(e.needs_project);
    }
}

PWB_TEST(v7_v8_registry_parity) {
    CHECK_EQ(static_cast<long long>(v7_states().size()), 8);
    CHECK_EQ(static_cast<long long>(v8_states().size()), 6);
    CHECK_EQ(static_cast<long long>(v7_shot_table().size()), 8);
    // v8_shot_table parity: only empty_project_tool_surface binds the
    // none_factory (needs_project=false).
    int none_count = 0;
    for (const QaShotEntry& e : v8_shot_table()) {
        if (!e.needs_project) {
            ++none_count;
            CHECK_EQ(e.state,
                     std::string("empty_project_tool_surface"));
        }
    }
    CHECK_EQ(none_count, 1);
}

PWB_TEST(v9_v10_registry_parity) {
    CHECK_EQ(static_cast<long long>(v9_states().size()), 6);
    CHECK_EQ(static_cast<long long>(v10_states().size()), 10);
    CHECK_EQ(kCompactSize.width, 1000);
    CHECK_EQ(kCompactSize.height, 700);
    CHECK_EQ(kWideSize.width, 1920);
    CHECK_EQ(kUltrawideSize.width, 2560);
    CHECK_EQ(kUltrawideSize.height, 1440);
    CHECK_EQ(kNarrowSize.width, 960);
    CHECK_EQ(kNarrowSize.height, 600);
    CHECK_EQ(kPrimeSize.width, 1600);
    CHECK_EQ(kPrimeSize.height, 900);
    CHECK_EQ(kCompact1366.width, 1366);
    CHECK_EQ(kCompact1366.height, 768);
}

PWB_TEST(v11_registry_parity) {
    const std::vector<std::string> want = {
        "first_open_empty_shell",       "data_manager_surface",
        "well_task_workflow_panel",     "seismic_context_surface",
        "stage_bar_phase1",             "stage_bar_phase2",
        "stage_bar_phase3",             "inspector_version_payload",
        "inspector_run_payload",        "task_center_operations",
        "command_palette_disabled_reason",
        "error_empty_states_composite", "theme_matrix_smoke",
    };
    CHECK(v11_scenarios() == want);
    CHECK(v11_shot_table() == want);
    const std::vector<std::string> themes = {"light", "dark"};
    CHECK(theme_matrix_themes() == themes);
    CHECK_EQ(static_cast<long long>(theme_matrix_sizes().size()), 2);
    CHECK_EQ(theme_matrix_sizes()[0].width, 1280);
    CHECK_EQ(theme_matrix_sizes()[0].height, 720);
    CHECK_EQ(theme_matrix_sizes()[1].width, 1920);
    CHECK_EQ(theme_matrix_sizes()[1].height, 1080);
    CHECK_EQ(palette_stage_filter(), std::string("单因素"));
    CHECK_EQ(palette_tool_filter(), std::string("开始编辑"));
    // Divergence note (ledger): C++ needs the shell only for the
    // first-open scenario — the palette scenario wires the real
    // CommandRegistry evaluator directly.
    CHECK(scenario_needs_workstation_shell("first_open_empty_shell"));
    CHECK(!scenario_needs_workstation_shell(
        "command_palette_disabled_reason"));
    CHECK_EQ(static_cast<long long>(all_v6_v10_states().size()), 36);
}

// ---------------------------------------------------------------------------
// Check vocabulary
// ---------------------------------------------------------------------------

PWB_TEST(check_vocabulary) {
    const CheckResult a = make_check("a", true);
    const CheckResult b = make_check("b", false, "why");
    CHECK(a.ok);
    CHECK(!b.ok);
    CHECK_EQ(b.detail, std::string("why"));

    const std::vector<CheckResult> empty;
    const pwb::domain::Json empty_payload = checks_payload(empty);
    CHECK(empty_payload["state_ok"].is_null());
    CHECK(empty_payload["checks"].is_array());
    CHECK(!all_ok(empty));

    const std::vector<CheckResult> mixed = {a, b};
    const pwb::domain::Json payload = checks_payload(mixed);
    CHECK(payload["state_ok"] == false);
    CHECK_EQ(payload["checks"].size(), 2u);
    CHECK(payload["checks"][0]["ok"] == true);
    CHECK_EQ(payload["checks"][1]["name"].get<std::string>(),
             std::string("b"));
    CHECK(!all_ok(mixed));
    const std::vector<std::string> failed = failed_names(mixed);
    CHECK_EQ(failed.size(), 1u);
    CHECK_EQ(failed[0], std::string("b"));
    CHECK(all_ok({a}));
}

// ---------------------------------------------------------------------------
// V6..V10 check bodies on synthetic snapshots
// ---------------------------------------------------------------------------

PWB_TEST(fail_closed_unbound_probe) {
    const WorkstationSnapshot s;  // bound=false
    const std::vector<CheckResult> results =
        run_state_checks("mapping_stage_phase1", s);
    CHECK_EQ(count_checks(results), 1u);
    CHECK_EQ(results[0].name,
             std::string("workstation_surface_bound"));
    CHECK(!results[0].ok);
}

PWB_TEST(unknown_state_empty_checks) {
    WorkstationSnapshot s = bound_ws();
    CHECK(run_state_checks("no_such_state", s).empty());
}

PWB_TEST(v6_mapping_stage_phase2_checks) {
    using pwb::tool_policy::MappingStage;
    WorkstationSnapshot s = bound_ws();
    s.stage_marker_checked = {
        {pwb::tool_policy::stage_value(MappingStage::FaciesCalibration),
         false},
        {pwb::tool_policy::stage_value(MappingStage::ConstraintFactor),
         true},
        {pwb::tool_policy::stage_value(
             MappingStage::IntegratedCompilation),
         false},
    };
    s.stage_panel_shows_target = true;
    s.actions["add_line"] = act(true);
    s.actions["add_polygon"] = act(true);
    s.docks["stage"] = QaDockState{false, 300, 700, 120};
    const std::vector<CheckResult> results =
        run_state_checks("mapping_stage_phase2", s);
    // 3 stage markers + panel page + add_line + add_polygon + dock.
    CHECK_EQ(count_checks(results), 7u);
    CHECK(all_ok(results));
    // Phase 1 hides add_line — same fixture minus the line visibility.
    s.actions["add_line"].visible = false;
    s.stage_marker_checked[pwb::tool_policy::stage_value(
        MappingStage::FaciesCalibration)] = true;
    s.stage_marker_checked[pwb::tool_policy::stage_value(
        MappingStage::ConstraintFactor)] = false;
    CHECK(all_ok(run_state_checks("mapping_stage_phase1", s)));
    // A missing marker fails closed instead of pretending unchecked.
    s.stage_marker_checked.erase(pwb::tool_policy::stage_value(
        MappingStage::IntegratedCompilation));
    CHECK(!all_ok(run_state_checks("mapping_stage_phase1", s)));
}

PWB_TEST(v6_write_grant_dialog_checks) {
    WorkstationSnapshot s = bound_ws();
    QaDialogSnapshot& d = s.grab_dialog;
    d.present = true;
    d.object_name = "WriteGrantDialog";
    d.hidden = false;
    d.deny_present = true;
    d.deny_default = true;
    d.deny_text = "拒绝";
    d.grant_present = true;
    d.grant_text = "授权";
    d.granted = false;
    d.label_texts = {"写入动作授权",
                     "map.add_layer — 在画布创建新图层",
                     "map.export — 导出当前编图"};
    const std::vector<CheckResult> results =
        run_state_checks("write_grant_dialog", s);
    CHECK(all_ok(results));
    // Missing dialog -> single honest failure (Python would AttributeError).
    WorkstationSnapshot empty = bound_ws();
    const std::vector<CheckResult> missing =
        run_state_checks("write_grant_dialog", empty);
    CHECK_EQ(missing.size(), 1u);
    CHECK(!missing[0].ok);
}

PWB_TEST(v7_task_cancelling_checks) {
    WorkstationSnapshot s = bound_ws();
    s.task_handles.push_back(
        QaTaskHandle{"job-1", "running", true});
    s.docks["task"] = QaDockState{false, 400, 240, 100};
    CHECK(all_ok(run_state_checks("task_cancelling", s)));
    // No cancel flag -> the pending check fails.
    s.task_handles[0].cancel_requested = false;
    CHECK(!names_of(run_state_checks("task_cancelling", s),
                    "task_cancel_pending"));
}

PWB_TEST(v8_empty_project_checks) {
    WorkstationSnapshot s = bound_ws();
    s.availability["pan"] = tool(true);
    s.availability["layer_new"] = tool(true);
    s.availability["toggle_editing"] =
        tool(false, "请先选择可编辑图层");
    s.availability["cancel"] = tool(true);
    s.empty_hint_visible = true;
    CHECK(all_ok(run_state_checks("empty_project_tool_surface", s)));
}

PWB_TEST(v8_blocking_task_checks) {
    WorkstationSnapshot s = bound_ws();
    s.availability["toggle_editing"] =
        tool(false, "后台任务进行中（正在导入参考图层）");
    s.availability["pan"] =
        tool(false, "后台任务进行中（正在导入参考图层）");
    s.availability["cancel"] = tool(true);
    CHECK(all_ok(run_state_checks("blocking_task_tool_surface", s)));
    // The blocking reason must lead the disabled_reason string.
    s.availability["pan"].disabled_reason = "其他原因";
    CHECK(!names_of(
        run_state_checks("blocking_task_tool_surface", s),
        "blocking_reason"));
}

PWB_TEST(v9_compact_and_preset_checks) {
    WorkstationSnapshot s = bound_ws();
    s.docks["inspector"] = QaDockState{true, 0, 0, 0};
    s.responsive_hid_inspector = true;
    s.user_hid_inspector = false;
    s.command_input_min_width = 220;
    s.stage_label_visible = false;
    s.docks["nav"] = QaDockState{false, 320, 700, 80};
    s.composite_width = 520;
    CHECK(all_ok(run_state_checks("compact_viewport", s)));

    s.docks["nav"].width = 430;
    s.session_values["v9_nav_width_before"] = 430;
    s.current_preset_id = "review";
    CHECK(all_ok(run_state_checks("preset_visibility_only", s)));
    // A snapped-back width fails the preservation check.
    s.docks["nav"].width = 180;
    CHECK(!names_of(run_state_checks("preset_visibility_only", s),
                    "preset_kept_user_nav_width"));
}

PWB_TEST(v10_crs_and_frozen_checks) {
    WorkstationSnapshot s = bound_ws();
    s.edit_chip_text = "已冻结";
    s.availability["toggle_editing"] =
        tool(false, "图层已冻结（只读）");
    CHECK(all_ok(run_state_checks("frozen_layer_surface", s)));

    s.crs_text = "⚠ EPSG:32650";
    s.crs_tooltip = "图层 CRS 与工程 CRS 不一致";
    CHECK(all_ok(run_state_checks("crs_mismatch_warning", s)));
    // The scrubbed text must not leak a fake 4326 — parity guard.
    s.crs_text = "⚠ EPSG:32650 / EPSG:4326";
    CHECK(!names_of(run_state_checks("crs_mismatch_warning", s),
                    "crs_mismatch_no_fake_crs"));
}

PWB_TEST(v10_raw_and_dirty_checks) {
    WorkstationSnapshot s = bound_ws();
    s.edit_chip_text = "RAW · 只读";
    s.availability["toggle_editing"] =
        tool(false, "RAW 图层不可编辑");
    s.availability["add_polygon"] = tool(false, "RAW 图层不可编辑");
    s.availability["layer_properties"] = tool(true);
    CHECK(all_ok(run_state_checks("raw_layer_readonly_surface", s)));

    s.edit_chip_text = "编辑中 ● 未保存";
    s.availability["save_edits"] = tool(true);
    CHECK(all_ok(run_state_checks("editing_dirty_chip", s)));
}

// ---------------------------------------------------------------------------
// V11 scenario checks on synthetic snapshots
// ---------------------------------------------------------------------------

PWB_TEST(v11_task_panel_checks) {
    ScenarioSnapshot s;
    QaTaskPanelSnapshot& p = s.task_panel.emplace();
    p.panel_found = true;
    p.row_texts = {"D63 砂地比预测 · 排队中",
                   "T1 岩相预测 · 运行中",
                   "ZJ2 孔隙度预测 · 完成"};
    p.status_badge_text = "运行中";
    p.status_badge_tone = "primary";
    CHECK(all_ok(run_scenario_checks("well_task_workflow_panel", s)));
    // Missing section -> one honest failing check.
    CHECK_EQ(run_scenario_checks("well_task_workflow_panel",
                                 ScenarioSnapshot{})
                 .size(),
             1u);
}

PWB_TEST(v11_seismic_context_checks) {
    ScenarioSnapshot s;
    QaSeismicContextSnapshot& t = s.seismic.emplace();
    t.toolbar_found = true;
    t.source_text = "HZ26_3D_full.sgy";
    t.attribute_text = "RMS振幅";
    t.horizon_text = "D63";
    t.task_text = "振幅属性提取 · HZ26";
    t.shape_text = "301 × 401 × 1201";
    t.status_text = "运行中 · 第 4/9 属性";
    CHECK(all_ok(run_scenario_checks("seismic_context_surface", s)));
}

PWB_TEST(v11_stage_surface_checks) {
    using pwb::tool_policy::MappingStage;
    ScenarioSnapshot s;
    QaStageSurfaceSnapshot& g = s.stage.emplace();
    g.stage_marker_checked = {
        {pwb::tool_policy::stage_value(MappingStage::FaciesCalibration),
         false},
        {pwb::tool_policy::stage_value(MappingStage::ConstraintFactor),
         true},
        {pwb::tool_policy::stage_value(
             MappingStage::IntegratedCompilation),
         false},
    };
    g.stage_panel_shows_target = true;
    g.current_horizon = "D63";
    g.constraints_row_visible = true;  // phase2 shows the row
    CHECK(all_ok(run_scenario_checks("stage_bar_phase2", s)));
    // Phase 1: the same surface but the row must hide.
    g.stage_marker_checked[pwb::tool_policy::stage_value(
        MappingStage::FaciesCalibration)] = true;
    g.stage_marker_checked[pwb::tool_policy::stage_value(
        MappingStage::ConstraintFactor)] = false;
    g.constraints_row_visible = false;
    CHECK(all_ok(run_scenario_checks("stage_bar_phase1", s)));
}

PWB_TEST(v11_task_center_checks) {
    ScenarioSnapshot s;
    QaTaskCenterSnapshot& c = s.task_center.emplace();
    c.row_ids = {"op:v11qa-verify", "op:v11qa-import"};
    c.running_present = true;
    c.finished_present = true;
    c.running_state_text = "运行中 42%";
    c.running_progress = 0.42;
    c.finished_message = "A12.las · 2 项过期";
    c.cancel_request_result = true;
    CHECK(all_ok(run_scenario_checks("task_center_operations", s)));
}

PWB_TEST(v11_palette_checks) {
    ScenarioSnapshot s;
    QaPaletteScenarioSnapshot& p = s.palette.emplace();
    p.open = true;
    p.enabled_count = 3;
    QaPaletteItem disabled;
    disabled.text = "阶段动作 · 单因素工作台（当前阶段不可用）";
    disabled.enabled = false;
    disabled.stage_scoped = true;
    disabled.spec_id = "stage:constraint_factor:open_factor_workbench";
    QaPaletteItem enabled;
    enabled.text = "编图 · 开始编辑";
    enabled.enabled = true;
    enabled.spec_id = "map:toggle_editing";
    p.stage_items = {enabled, disabled};
    QaPaletteItem tool_row = enabled;
    tool_row.tool_tip = "影响：进入编辑会话\n前置条件：已选择可编辑图层";
    p.tool_items = {tool_row};
    CHECK(all_ok(run_scenario_checks(
        "command_palette_disabled_reason", s)));
}

PWB_TEST(v11_theme_matrix_checks) {
    ScenarioSnapshot s;
    for (const std::string& theme : theme_matrix_themes()) {
        for (const QaSize& size : theme_matrix_sizes()) {
            QaThemeRender r;
            r.theme = theme;
            r.want_width = size.width;
            r.want_height = size.height;
            r.width = size.width;
            r.height = size.height;
            r.distinct_colors = 12;
            r.null_pixmap = false;
            s.theme_renders.push_back(r);
        }
    }
    CHECK(all_ok(run_scenario_checks("theme_matrix_smoke", s)));
    // A monochrome render fails the diversity guard.
    s.theme_renders[0].distinct_colors = 1;
    CHECK(!all_ok(run_scenario_checks("theme_matrix_smoke", s)));
}

PWB_TEST(unknown_scenario_empty_checks) {
    CHECK(run_scenario_checks("no_such_scenario", ScenarioSnapshot{})
              .empty());
}

// ---------------------------------------------------------------------------
// Dual-volume prototype core
// ---------------------------------------------------------------------------

PWB_TEST(synthetic_volume_math) {
    const SyntheticVolumes v =
        generate_synthetic_seismic_volumes(8, 9, 10);
    CHECK_EQ(v.amplitude.nx, 8);
    CHECK_EQ(v.amplitude.ny, 9);
    CHECK_EQ(v.amplitude.nz, 10);
    CHECK_EQ(static_cast<long long>(v.amplitude.data.size()),
             8LL * 9 * 10);
    // numpy parity spot-check: x = linspace(-3,3,8)[2], y = [3],
    // z = linspace(0,4π,10)[4].
    const double x = -3.0 + 6.0 * (2.0 / 7.0);
    const double y = -3.0 + 6.0 * (3.0 / 8.0);
    const double z = (4.0 * std::acos(-1.0)) * (4.0 / 9.0);
    const double expect_amp =
        std::sin(z + 0.3 * x + 0.2 * y) *
        std::exp(-0.05 * (x * x + y * y));
    CHECK_NEAR(v.amplitude.at(2, 3, 4), expect_amp, 1e-6);
    const double fault_arg =
        (x - 0.5 * y) - 0.2 * z / (4.0 * std::acos(-1.0));
    const double expect_coh = 1.0 - 0.8 * std::exp(-15.0 * fault_arg * fault_arg);
    CHECK_NEAR(v.coherence.at(2, 3, 4), expect_coh, 1e-6);
    // (x*ny + y)*nz + z index order.
    const ScalarVolume& a = v.amplitude;
    CHECK_NEAR(a.at(0, 0, 0), a.data[0], 1e-9);
    CHECK_NEAR(a.at(1, 0, 0), a.data[9 * 10], 1e-9);
}

PWB_TEST(slice_extraction_parity) {
    // Tiny volume: data[x,y,z] = x*100 + y*10 + z (index probe).
    ScalarVolume v{3, 4, 5, std::vector<float>(3 * 4 * 5)};
    for (int x = 0; x < 3; ++x)
        for (int y = 0; y < 4; ++y)
            for (int z = 0; z < 5; ++z)
                v.data[(x * 4 + y) * 5 + z] =
                    static_cast<float>(x * 100 + y * 10 + z);

    // axis 0 (Inline): vol[idx,:,:] -> h=ny w=nz.
    const Slice2D inline_slice = extract_slice(v, kAxisInline, 1);
    CHECK_EQ(inline_slice.h, 4);
    CHECK_EQ(inline_slice.w, 5);
    CHECK_NEAR(inline_slice.at(2, 3), 100 + 20 + 3, 1e-6);
    // axis 1 (Crossline): vol[:,idx,:] -> h=nx w=nz.
    const Slice2D cross = extract_slice(v, kAxisCrossline, 2);
    CHECK_EQ(cross.h, 3);
    CHECK_EQ(cross.w, 5);
    CHECK_NEAR(cross.at(0, 4), 0 + 20 + 4, 1e-6);
    // axis 2 (Time): vol[:,:,idx] -> h=nx w=ny.
    const Slice2D time = extract_slice(v, kAxisTime, 4);
    CHECK_EQ(time.h, 3);
    CHECK_EQ(time.w, 4);
    CHECK_NEAR(time.at(2, 1), 200 + 10 + 4, 1e-6);
    // np.clip parity: out-of-range indices clamp.
    CHECK_NEAR(extract_slice(v, kAxisTime, -3).at(0, 0),
               v.at(0, 0, 0), 1e-6);
    CHECK_NEAR(extract_slice(v, kAxisTime, 99).at(0, 0),
               v.at(0, 0, 4), 1e-6);
}

PWB_TEST(render_variant_blending) {
    // 1x2 slice so each channel formula is exercised on known floats.
    Slice2D amp{1, 2, {0.0f, 0.5f}};
    Slice2D coh{1, 2, {0.9f, 0.2f}};

    const RgbaImage a = render_overlay_rgba(
        amp, coh, OverlayVariant::AlphaBlending, 0.5, 0.6);
    CHECK_EQ(a.h, 1);
    CHECK_EQ(a.w, 2);
    CHECK_EQ(a.rgba.size(), 8u);
    // px0: amp_norm = trunc(127.5)=127, coh_red = trunc((1-0.9)*255*2)=51.
    // r = trunc(0.5*127 + 0.5*51) = trunc(89.0) = 89.
    CHECK_EQ(static_cast<int>(a.rgba[0]), 89);
    CHECK_EQ(static_cast<int>(a.rgba[1]), 63);   // trunc(0.5*127)
    CHECK_EQ(static_cast<int>(a.rgba[2]), 63);
    CHECK_EQ(static_cast<int>(a.rgba[3]), 255);
    // px1: amp_norm = trunc((0.5+1)*127.5)=trunc(191.25)=191,
    //      coh_red = trunc(0.8*255*2)=trunc(408)->255 clamp.
    // r = trunc(0.5*191 + 0.5*255) = trunc(223.0) = 223.
    CHECK_EQ(static_cast<int>(a.rgba[4]), 223);

    const RgbaImage b = render_overlay_rgba(
        amp, coh, OverlayVariant::RgbFusion, 0.5, 0.6);
    CHECK_EQ(static_cast<int>(b.rgba[0]), 0);    // trunc(0.0*255)
    CHECK_EQ(static_cast<int>(b.rgba[1]), 0);    // trunc(-0.0*255)
    CHECK_EQ(static_cast<int>(b.rgba[2]), 25);   // trunc(0.1*255)=25
    CHECK_EQ(static_cast<int>(b.rgba[4]), 127);  // trunc(0.5*255)=127
    CHECK_EQ(static_cast<int>(b.rgba[5]), 0);    // trunc(-0.5*255)->0
    CHECK_EQ(static_cast<int>(b.rgba[6]), 204);  // trunc(0.8*255)=204

    const RgbaImage c = render_overlay_rgba(
        amp, coh, OverlayVariant::ThresholdMask, 0.5, 0.6);
    // px0 coh=0.9 >= 0.6 -> grey amp_norm=127.
    CHECK_EQ(static_cast<int>(c.rgba[0]), 127);
    CHECK_EQ(static_cast<int>(c.rgba[1]), 127);
    CHECK_EQ(static_cast<int>(c.rgba[2]), 127);
    // px1 coh=0.2 < 0.6 -> cyan highlight.
    CHECK_EQ(static_cast<int>(c.rgba[4]), 0);
    CHECK_EQ(static_cast<int>(c.rgba[5]), 240);
    CHECK_EQ(static_cast<int>(c.rgba[6]), 255);
    CHECK_EQ(static_cast<int>(c.rgba[7]), 255);
}

PWB_TEST(variant_and_axis_vocabulary) {
    CHECK_EQ(std::string(axis_display_name(kAxisInline)),
             std::string("Inline (0)"));
    CHECK_EQ(std::string(axis_display_name(kAxisCrossline)),
             std::string("Crossline (1)"));
    CHECK_EQ(std::string(axis_display_name(kAxisTime)),
             std::string("Time (2)"));
    CHECK(variant_from_label("Variant A: Alpha Blending") ==
          OverlayVariant::AlphaBlending);
    CHECK(variant_from_label("Variant B: RGB Multi-Channel Fusion") ==
          OverlayVariant::RgbFusion);
    CHECK(variant_from_label("Variant C: Coherence Masking Overlay") ==
          OverlayVariant::ThresholdMask);
    CHECK(variant_from_label("anything else") ==
          OverlayVariant::ThresholdMask);  // Python else-fallback
}

int main() { return pwb_test::run_all(); }
