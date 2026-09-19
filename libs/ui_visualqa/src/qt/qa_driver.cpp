#include <pwb/ui_visualqa/qt/qa_driver.hpp>

#include <chrono>
#include <thread>

#include <QApplication>
#include <QEventLoop>
#include <QTimer>

#include <pwb/tool_policy/layer_roles.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui_visualqa/qa_checks.hpp>
#include <pwb/ui_visualqa/qa_states.hpp>

namespace pwb::ui_visualqa::qt {

namespace {

using pwb::tool_policy::MappingStage;
namespace lr = pwb::tool_policy::layer_role;

const char* stage_val(MappingStage stage) {
    return pwb::tool_policy::stage_value(stage);
}

// The GeoJSON square fixture the Python drivers insert as the dirty
// feature (coordinates differ per state — kept verbatim).
const char* kPolygonDraft1 =
    R"({"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]})";
const char* kPolygonDirty1 =
    R"({"type":"Polygon","coordinates":[[[0,0],[8,0],[8,8],[0,8],[0,0]]]})";

}  // namespace

const char* qa_dock_key(QaDock dock) {
    switch (dock) {
        case QaDock::Stage: return "stage";
        case QaDock::CompositeLayer: return "composite_layer";
        case QaDock::Inspector: return "inspector";
        case QaDock::Task: return "task";
        case QaDock::Agent: return "agent";
        case QaDock::Nav: return "nav";
        case QaDock::Hub: return "hub";
    }
    return "";
}

void settle(int ms) {
    // visual_qa_v6._settle parity: single-shot timer + processEvents.
    QEventLoop loop;
    QTimer::singleShot(ms, &loop, &QEventLoop::quit);
    loop.exec();
    QApplication::processEvents();
}

void cancellable_demo_task(QaTaskContext& ctx) {
    // _long_task parity: 50 uninterruptible 2 s segments, cancel
    // checkpoint between them — the request lands mid-run so the task
    // center shows the "取消中" presentation window.
    for (int i = 0; i < 50; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(2000));
        ctx.check_cancelled();
    }
}

// ==========================================================================
// V6 — visual_qa_v6.py drive functions
// ==========================================================================

void drive_mapping_stage_phase1(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.raise_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    settle(200);
}

void drive_mapping_stage_phase2(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.raise_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::ConstraintFactor));
    settle(200);
}

void drive_mapping_stage_phase3(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.raise_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::IntegratedCompilation));
    settle(200);
}

void drive_command_palette_context(VisualQaProbe& p) {
    // Stage 1 + palette open + filter hits a stage-2-scoped command.
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    settle(150);
    p.popup_palette();
    p.set_palette_filter(palette_context_filter());
    settle(100);
}

void drive_write_grant_dialog(VisualQaProbe& p) {
    // Real registry action cards + deny default; non-modal show (the
    // shot process must not block on exec) — the probe keeps the dialog
    // as the grab widget (_v6_grab_widget parity).
    p.build_write_grant_dialog(write_grant_action_ids());
    settle(150);
}

void drive_status_workbench_segment(VisualQaProbe& p) {
    // Stage 2 + explicit context recompute → workbench segment shows
    // 阶段 · 编辑目标 · 后端 · 任务.
    p.set_mapping_stage(stage_val(MappingStage::ConstraintFactor));
    settle(150);
    p.refresh_ui_context();
    settle(50);
}

// ==========================================================================
// V7 — visual_qa_v7.py drive functions
// ==========================================================================

void drive_phase1_raw_blocked(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesSource),
        "初始沉积相（RAW）", ""});
    p.select_layer(layer_id);
    settle(200);
}

void drive_phase1_editing_session(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "沉积相解释草稿",
        ""});
    p.request_command("toggle_editing");
    // session.add_feature guarded by `session is not None` parity —
    // the follow-up sync only happens inside that guard.
    if (p.add_edit_feature(layer_id, QaFeatureInsert{
                               "draft_1", kPolygonDraft1,
                               {{"name", "相带1"}}, ""})) {
        p.sync_action_state();
    }
    settle(200);
}

void drive_phase2_constraint_line(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::ConstraintFactor));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "line", std::string(lr::kProvenanceLine), "物源线", ""});
    p.request_command("toggle_editing");
    p.select_layer(layer_id);
    settle(200);
}

void drive_phase2_factor_raster(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::ConstraintFactor));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kFactorGrid), "厚度因子栅格",
        "factor-qa-1"});
    p.select_layer(layer_id);
    settle(200);
}

void drive_layer_tree_decorations(VisualQaProbe& p) {
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "冻结成果层",
        ""});
    p.set_maturity("phase1_draft:" + layer_id, "frozen");
    p.sync_composition_now();
    p.sync_action_state();
    p.show_dock(QaDock::CompositeLayer);
    p.raise_dock(QaDock::CompositeLayer);
    settle(200);
}

void drive_task_cancelling(VisualQaProbe& p) {
    // Submit an interruptible long task then request cancel → the task
    // center shows "取消中".
    const std::string task_id = p.submit_task(
        "视觉 QA 长任务（取消中演示）",
        [](QaTaskContext& ctx) { cancellable_demo_task(ctx); });
    settle(300);
    if (!task_id.empty()) {
        p.cancel_task(task_id);
    }
    p.show_dock(QaDock::Task);
    p.raise_dock(QaDock::Task);
    settle(150);
}

void drive_toolbar_overflow_narrow(VisualQaProbe& p) {
    // Host-row layout drive: an active layer gets the evaluator's full
    // visibility; the row re-park does not assert sizes (the window is
    // NOT resized — the harness's size guard requires actual == request).
    p.add_layer(QaLayerSpec{"polygon",
                            std::string(lr::kInitialFaciesDraft),
                            "宿主行探针层", ""});
    p.enforce_toolbar_rows();
    settle(120);
}

void drive_inspector_factor(VisualQaProbe& p) {
    p.set_mapping_stage(stage_val(MappingStage::ConstraintFactor));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "line", std::string(lr::kFactorContour), "厚度等值线",
        "factor-qa-2"});
    // The synthetic fixture races role assignment vs the selection
    // signal — settle then drive the inspector slot explicitly.
    settle(400);
    p.inspect_layer_selection(layer_id);
    p.show_dock(QaDock::Inspector);
    p.raise_dock(QaDock::Inspector);
    settle(150);
}

// ==========================================================================
// V8 — visual_qa_v8.py drive functions
// ==========================================================================

void drive_empty_project_tool_surface(VisualQaProbe& p) {
    (void)p;
    // Untitled project is the honest "empty" workstation state (a truly
    // project-less shell is unreachable — evaluator gates are covered
    // by the M2 pure-function matrix).
    settle(200);
}

void drive_derived_polygon_editing_dirty(VisualQaProbe& p) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "沉积相解释草稿",
        ""});
    p.request_command("toggle_editing");
    p.add_edit_feature(layer_id, QaFeatureInsert{"dirty_1", kPolygonDirty1,
                                                 {{"name", "相带A"}}, ""});
    p.sync_action_state();
    settle(200);
}

void drive_frozen_map_product(VisualQaProbe& p) {
    p.set_mapping_stage(stage_val(MappingStage::IntegratedCompilation));
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kIntegratedFacies), "综合相图成果",
        ""});
    p.set_maturity("integrated:" + layer_id, "frozen");
    p.sync_composition_now();
    p.sync_action_state();
    settle(200);
}

void drive_palette_disabled_reason(VisualQaProbe& p) {
    // Stage 1 + palette open: map:* commands' disable reasons visible.
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    settle(150);
    p.popup_palette();
    p.set_palette_filter("编图");
    settle(120);
}

void drive_native_activation_failure_revert(VisualQaProbe& p) {
    // Editing session + capture tool → simulated native activation
    // failure → checked state reverts to pan.
    p.set_mapping_stage(stage_val(MappingStage::FaciesCalibration));
    p.add_layer(QaLayerSpec{"polygon",
                            std::string(lr::kInitialFaciesDraft), "草稿",
                            ""});
    p.request_command("toggle_editing");
    p.request_command("add_polygon");
    settle(120);
    p.begin_status_capture();
    p.emit_native_tool_activation_failed("add_polygon", "模拟桥异常");
    settle(120);
}

void drive_blocking_task_tool_surface(VisualQaProbe& p) {
    p.add_layer(QaLayerSpec{"polygon",
                            std::string(lr::kInitialFaciesDraft), "草稿",
                            ""});
    p.set_blocking_task_label("正在导入参考图层");
    p.sync_action_state();
    settle(150);
}

// ==========================================================================
// V9 — visual_qa_v9.py drive functions
// ==========================================================================

namespace {

void prime_window(VisualQaProbe& p) {
    // show → wait for restoreGeometry's deferred re-apply (the 50 ms
    // post-show restore would clobber an immediate resize).
    p.show_window();
    settle(250);
}

void resize_and_settle(VisualQaProbe& p, int w, int h, int ms = 400) {
    p.resize_window(w, h);
    settle(ms);  // >= 180 ms debounce window + layout settle
}

}  // namespace

void drive_compact_viewport(VisualQaProbe& p) {
    prime_window(p);
    resize_and_settle(p, kPrimeSize.width, kPrimeSize.height);
    resize_and_settle(p, kCompactSize.width, kCompactSize.height);
}

void drive_wide_viewport(VisualQaProbe& p) {
    prime_window(p);
    resize_and_settle(p, kWideSize.width, kWideSize.height);
}

void drive_ultrawide_viewport(VisualQaProbe& p) {
    prime_window(p);
    resize_and_settle(p, kUltrawideSize.width, kUltrawideSize.height);
}

void drive_narrow_hub_page(VisualQaProbe& p) {
    prime_window(p);
    resize_and_settle(p, kPrimeSize.width, kPrimeSize.height);
    p.show_hub_page("数据管理");
    resize_and_settle(p, kNarrowSize.width, kNarrowSize.height);
}

void drive_preset_visibility_only(VisualQaProbe& p) {
    // User-sized nav width then a named preset: dock geometry must
    // survive (B-3).
    prime_window(p);
    resize_and_settle(p, kWideSize.width, kWideSize.height);
    p.resize_dock_horizontal(QaDock::Nav, 430);
    settle(300);
    const WorkstationSnapshot before = p.collect();
    const auto it = before.docks.find("nav");
    p.set_session_value("v9_nav_width_before",
                        it != before.docks.end() ? it->second.width : 0);
    p.apply_layout_preset("review");
    settle(300);
}

void drive_agent_grow_only(VisualQaProbe& p) {
    // User-raised agent bottom row then open Agent: the height must not
    // snap back to 245 (B-3).
    prime_window(p);
    resize_and_settle(p, kWideSize.width, kWideSize.height);
    p.show_dock(QaDock::Agent);
    p.resize_dock_height(QaDock::Agent, 420);
    settle(200);
    const WorkstationSnapshot before = p.collect();
    const auto it = before.docks.find("agent");
    p.set_session_value("v9_agent_height_before",
                        it != before.docks.end() ? it->second.height : 0);
    p.show_agent();
    settle(200);
}

// ==========================================================================
// V10 — visual_qa_v10.py drive functions
// ==========================================================================

namespace {

void enter_stage(VisualQaProbe& p, MappingStage stage) {
    p.show_dock(QaDock::Stage);
    p.set_mapping_stage(stage_val(stage));
}

}  // namespace

void drive_raw_layer_readonly_surface(VisualQaProbe& p) {
    enter_stage(p, MappingStage::FaciesCalibration);
    p.add_layer(QaLayerSpec{"polygon",
                            std::string(lr::kInitialFaciesSource),
                            "初始沉积相（RAW）", ""});
    settle(150);
}

void drive_capture_preferred_line_role(VisualQaProbe& p) {
    enter_stage(p, MappingStage::ConstraintFactor);
    p.add_layer(QaLayerSpec{"line", std::string(lr::kFaciesBoundary),
                            "相带边界", ""});
    p.request_command("toggle_editing");
    settle(150);
}

void drive_editing_dirty_chip(VisualQaProbe& p) {
    enter_stage(p, MappingStage::FaciesCalibration);
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "解释草稿", ""});
    p.request_command("toggle_editing");
    p.add_edit_feature(layer_id,
                       QaFeatureInsert{"dirty_1", kPolygonDirty1,
                                       {{"name", "相带A"}}, "visual_qa"});
    p.sync_action_state();
    settle(150);
}

void drive_snapping_detail_surface(VisualQaProbe& p) {
    enter_stage(p, MappingStage::ConstraintFactor);
    p.add_layer(QaLayerSpec{"line", std::string(lr::kFaciesBoundary),
                            "相带边界", ""});
    p.request_command("snapping");
    p.sync_action_state();
    settle(150);
}

void drive_topology_error_chip(VisualQaProbe& p) {
    enter_stage(p, MappingStage::FaciesCalibration);
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "草稿", ""});
    p.request_command("toggle_editing");
    p.request_command("topology");  // counting needs topology on
    p.record_topology_validation(layer_id, 3);
    p.sync_action_state();
    settle(150);
}

void drive_crs_undeclared_surface(VisualQaProbe& p) {
    enter_stage(p, MappingStage::FaciesCalibration);
    p.set_project_crs("");
    p.sync_action_state();
    settle(150);
}

void drive_crs_mismatch_warning(VisualQaProbe& p) {
    enter_stage(p, MappingStage::FaciesCalibration);
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kInitialFaciesDraft), "草稿", ""});
    p.set_project_crs("EPSG:4490");
    p.set_layer_crs(layer_id, "EPSG:32650");
    p.sync_action_state();
    settle(150);
}

void drive_frozen_layer_surface(VisualQaProbe& p) {
    enter_stage(p, MappingStage::IntegratedCompilation);
    const std::string layer_id = p.add_layer(QaLayerSpec{
        "polygon", std::string(lr::kIntegratedFacies), "综合相图", ""});
    p.set_maturity("integrated:" + layer_id, "frozen");
    p.sync_composition_now();
    p.sync_action_state();
    settle(150);
}

void drive_canvas_context_menu_surface(VisualQaProbe& p) {
    enter_stage(p, MappingStage::ConstraintFactor);
    p.add_layer(QaLayerSpec{"line", std::string(lr::kFaciesBoundary),
                            "相带边界", ""});
    p.build_canvas_menu();
    settle(120);
}

void drive_compact_1366_toolbar_identity(VisualQaProbe& p) {
    p.show_window();
    settle(250);
    p.resize_window(kCompact1366.width, kCompact1366.height);
    settle(400);
    enter_stage(p, MappingStage::ConstraintFactor);
    p.add_layer(QaLayerSpec{"line", std::string(lr::kFaciesBoundary),
                            "相带边界", ""});
    settle(200);
}

// ==========================================================================
// dispatch
// ==========================================================================

namespace {

using DriveFn = void (*)(VisualQaProbe&);

const std::map<std::string, DriveFn>& drive_table() {
    static const std::map<std::string, DriveFn> table = {
        {"mapping_stage_phase1", &drive_mapping_stage_phase1},
        {"mapping_stage_phase2", &drive_mapping_stage_phase2},
        {"mapping_stage_phase3", &drive_mapping_stage_phase3},
        {"command_palette_context", &drive_command_palette_context},
        {"write_grant_dialog", &drive_write_grant_dialog},
        {"status_workbench_segment", &drive_status_workbench_segment},
        {"phase1_raw_blocked", &drive_phase1_raw_blocked},
        {"phase1_editing_session", &drive_phase1_editing_session},
        {"phase2_constraint_line", &drive_phase2_constraint_line},
        {"phase2_factor_raster", &drive_phase2_factor_raster},
        {"layer_tree_decorations", &drive_layer_tree_decorations},
        {"task_cancelling", &drive_task_cancelling},
        {"toolbar_overflow_narrow", &drive_toolbar_overflow_narrow},
        {"inspector_factor", &drive_inspector_factor},
        {"empty_project_tool_surface", &drive_empty_project_tool_surface},
        {"derived_polygon_editing_dirty",
         &drive_derived_polygon_editing_dirty},
        {"frozen_map_product", &drive_frozen_map_product},
        {"palette_disabled_reason", &drive_palette_disabled_reason},
        {"native_activation_failure_revert",
         &drive_native_activation_failure_revert},
        {"blocking_task_tool_surface", &drive_blocking_task_tool_surface},
        {"compact_viewport", &drive_compact_viewport},
        {"wide_viewport", &drive_wide_viewport},
        {"ultrawide_viewport", &drive_ultrawide_viewport},
        {"narrow_hub_page", &drive_narrow_hub_page},
        {"preset_visibility_only", &drive_preset_visibility_only},
        {"agent_grow_only", &drive_agent_grow_only},
        {"raw_layer_readonly_surface", &drive_raw_layer_readonly_surface},
        {"capture_preferred_line_role", &drive_capture_preferred_line_role},
        {"editing_dirty_chip", &drive_editing_dirty_chip},
        {"snapping_detail_surface", &drive_snapping_detail_surface},
        {"topology_error_chip", &drive_topology_error_chip},
        {"crs_undeclared_surface", &drive_crs_undeclared_surface},
        {"crs_mismatch_warning", &drive_crs_mismatch_warning},
        {"frozen_layer_surface", &drive_frozen_layer_surface},
        {"canvas_context_menu_surface", &drive_canvas_context_menu_surface},
        {"compact_1366_toolbar_identity",
         &drive_compact_1366_toolbar_identity},
    };
    return table;
}

}  // namespace

bool drive_state(const std::string& state, VisualQaProbe& probe) {
    const auto it = drive_table().find(state);
    if (it == drive_table().end()) {
        return false;
    }
    it->second(probe);
    return true;
}

std::vector<CheckResult> run_state_checks(const std::string& state,
                                          VisualQaProbe& probe) {
    const WorkstationSnapshot snapshot = probe.collect();
    return pwb::ui_visualqa::run_state_checks(state, snapshot);
}

}  // namespace pwb::ui_visualqa::qt
