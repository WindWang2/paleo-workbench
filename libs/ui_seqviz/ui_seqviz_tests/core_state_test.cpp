// UI-10 — Qt-free core state test for libs/ui_seqviz.
//
// Exercises the sequence workflow port (apply_stratigraphy_scheme /
// set_target_from_boundary + the panel view models), the factor state
// helpers (badge tokens, sub labels, common-method seeding, preview
// cards, factor-map params/job), plus a first pass over the viz /
// correlation / composition / curve-op / lithology state surfaces.

#include <any>
#include <cstdio>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_seqviz/factor_state.hpp>
#include <pwb/ui_seqviz/sequence_state.hpp>
#include <pwb/ui_seqviz/state_language.hpp>

#include "ui_seqviz_test.hpp"

using namespace pwb::ui_seqviz;

namespace {

StratigraphyProjectSlice make_project() {
    StratigraphyProjectSlice project;
    project.stratigraphy.interpretation_version = "v2";
    project.stratigraphy.systems_tract_scheme = "LST/TST/HST";
    project.stratigraphy.target_horizon = "Sq2";
    project.stratigraphy.sequence_boundaries = {"Sq1", "Sq2", "Sq3"};
    project.stratigraphy.applicable_wells = {"w1", "w2"};
    project.stratigraphy.applicable_seismic_ranges = {"line-A"};

    CompilationRunSlice run;
    run.target_horizon = "Sq2";
    run.sequence_scheme_ref = "LST/TST/HST";
    project.compilation_runs.push_back(run);

    PaleoMapDocumentSlice map;
    map.linked_target_horizon = "Sq2";
    project.paleomap_documents.push_back(map);

    FactorTaskHorizonSlice task;
    task.name = "Sq2 砂厚";
    task.target_horizon = "Sq2";
    task.factor_type = "砂厚";
    project.factor_map_tasks.push_back(task);

    FactorTaskHorizonSlice other;
    other.name = "Sq1 泥质";
    other.target_horizon = "Sq1";
    other.factor_type = "泥质";
    project.factor_map_tasks.push_back(other);

    return project;
}

}  // namespace

// --- sequence_state: apply + downstream bind -------------------------------

PWB_TEST(apply_stratigraphy_scheme_binds_downstream) {
    auto project = make_project();
    const StratigraphySlice& strat = apply_stratigraphy_scheme(
        project, std::string("Sq3"), std::nullopt, std::nullopt,
        std::nullopt, /*bind_downstream=*/true);
    CHECK_EQ(strat.target_horizon, "Sq3");
    // Compilation run syncs.
    CHECK_EQ(project.compilation_runs.back().target_horizon, "Sq3");
    // Previously-linked map follows the new horizon.
    CHECK_EQ(project.paleomap_documents[0].linked_target_horizon, "Sq3");
    // Factor task sharing the previous horizon is re-bound AND renamed.
    CHECK_EQ(project.factor_map_tasks[0].target_horizon, "Sq3");
    CHECK_EQ(project.factor_map_tasks[0].name, "Sq3 砂厚");
    // Unrelated horizon is preserved untouched.
    CHECK_EQ(project.factor_map_tasks[1].target_horizon, "Sq1");
    CHECK_EQ(project.factor_map_tasks[1].name, "Sq1 泥质");
}

PWB_TEST(apply_stratigraphy_scheme_no_bind_preserves) {
    auto project = make_project();
    apply_stratigraphy_scheme(project, std::string("Sq3"), std::nullopt,
                              std::nullopt, std::nullopt,
                              /*bind_downstream=*/false);
    CHECK_EQ(project.stratigraphy.target_horizon, "Sq3");
    CHECK_EQ(project.compilation_runs.back().target_horizon, "Sq3");
    CHECK_EQ(project.paleomap_documents[0].linked_target_horizon, "Sq2");
    CHECK_EQ(project.factor_map_tasks[0].target_horizon, "Sq2");
}

PWB_TEST(set_target_from_boundary_adds_missing_boundary) {
    auto project = make_project();
    set_target_from_boundary(project, "Sq4", /*bind_downstream=*/true);
    CHECK_EQ(project.stratigraphy.target_horizon, "Sq4");
    CHECK_LL(project.stratigraphy.sequence_boundaries.size(), 4);
    CHECK_EQ(project.stratigraphy.sequence_boundaries.back(), "Sq4");
}

PWB_TEST(set_target_from_boundary_ignores_empty) {
    auto project = make_project();
    set_target_from_boundary(project, "   ", /*bind_downstream=*/true);
    CHECK_EQ(project.stratigraphy.target_horizon, "Sq2");
    CHECK_LL(project.stratigraphy.sequence_boundaries.size(), 3);
}

PWB_TEST(active_target_horizon_prefers_last_run) {
    auto project = make_project();
    CHECK_EQ(active_target_horizon(project), "Sq2");
    project.compilation_runs.back().target_horizon = "";
    project.stratigraphy.target_horizon = "Sq1";
    CHECK_EQ(active_target_horizon(project), "Sq1");
}

// --- sequence_state: panel view models -------------------------------------

PWB_TEST(target_view_options_preserve_order_and_promote) {
    StratigraphySlice strat;
    strat.sequence_boundaries = {"Sq1", "Sq2", "Sq3"};
    strat.target_horizon = "Sq2";
    const SequenceTargetView view = sequence_target_view(strat);
    CHECK_LL(view.options.size(), 3);
    CHECK_EQ(view.options[0], "Sq1");
    CHECK_EQ(view.options[1], "Sq2");
    CHECK_EQ(view.options[2], "Sq3");
    CHECK_LL(view.selected_index, 1);

    // Target absent from boundaries → promoted to the front.
    strat.target_horizon = "SqX";
    const SequenceTargetView promoted = sequence_target_view(strat);
    CHECK_LL(promoted.options.size(), 4);
    CHECK_EQ(promoted.options[0], "SqX");
    CHECK_LL(promoted.selected_index, 0);
}

PWB_TEST(target_view_empty_boundaries_single_empty_option) {
    StratigraphySlice strat;
    const SequenceTargetView view = sequence_target_view(strat);
    CHECK_LL(view.options.size(), 1);
    CHECK_EQ(view.options[0], "");
    CHECK_LL(view.selected_index, 0);
    CHECK_EQ(view.version_text, "v1");
    CHECK_EQ(view.scheme_text, "LST/TST/HST");
    CHECK_EQ(view.scope_text, "0 口井 / 0 条测线");
    CHECK(!view.last_committed_target.has_value());
}

PWB_TEST(boundary_rows_flag_current_target) {
    StratigraphySlice strat;
    strat.sequence_boundaries = {"Sq1", "Sq2"};
    strat.target_horizon = "Sq2";
    const auto rows = sequence_boundary_rows(strat);
    CHECK_LL(rows.size(), 2);
    CHECK_EQ(rows[0].name, "Sq1");
    CHECK_EQ(rows[0].target, "Sq2");
    CHECK_EQ(rows[0].note, "第 1 层序界面");
    CHECK_EQ(rows[1].note, "当前目标");

    // Empty target → "未设置" in the target column.
    strat.target_horizon = "";
    const auto unset = sequence_boundary_rows(strat);
    CHECK_EQ(unset[0].target, "未设置");
}

PWB_TEST(target_commit_tracker_dedupes) {
    TargetCommitTracker tracker;
    CHECK(tracker.should_emit("Sq1"));
    // Same text → suppressed.
    CHECK(!tracker.should_emit("Sq1"));
    CHECK(tracker.should_emit("Sq2"));
    tracker.resync(std::string("Sq1"));
    CHECK(!tracker.should_emit("Sq1"));
    tracker.resync(std::nullopt);
    CHECK(tracker.should_emit("Sq1"));
}

PWB_TEST(scheme_summary_view_texts) {
    StratigraphySlice strat;
    strat.sequence_boundaries = {"a", "b", "c"};
    strat.target_horizon = "b";
    strat.systems_tract_scheme = "SQ";
    const auto view = sequence_scheme_summary_view(strat);
    CHECK_EQ(view.scheme_text, "SQ");
    CHECK_EQ(view.boundary_count_text, "3 个");
    CHECK_EQ(view.systems_tract_text, "LST / TST / HST");
    CHECK_EQ(view.status_text, "目标 b");

    strat.target_horizon.clear();
    const auto unset = sequence_scheme_summary_view(strat);
    CHECK_EQ(unset.status_text, "未设置目标层位");
}

// --- factor_state ----------------------------------------------------------

PWB_TEST(factor_badge_token_overrides) {
    // complete→done, pending→queued via the task-map override.
    CHECK_EQ(factor_task_badge_token("complete").label, "完成");
    CHECK_EQ(factor_task_badge_token("complete").tone, "ok");
    CHECK_EQ(factor_task_badge_token("pending").label, "排队中");
    CHECK_EQ(factor_task_badge_token("pending").tone, "muted");
    // running / failed / cancelled pass through unchanged.
    CHECK_EQ(factor_task_badge_token("running").label, "运行中");
    CHECK_EQ(factor_task_badge_token("failed").tone, "error");
}

PWB_TEST(factor_task_sub_label_grid_fallback) {
    FactorTaskRecord task;
    task.method = "IDW";
    CHECK_EQ(factor_task_sub_label(task), "IDW · 50m");
    task.parameters["grid"] = 100;
    CHECK_EQ(factor_task_sub_label(task), "IDW · 100");
}

PWB_TEST(factor_common_method_first_seen_tiebreak) {
    std::vector<FactorTaskRecord> tasks(3);
    tasks[0].method = "IDW";
    tasks[1].method = "kriging";
    tasks[2].method = "IDW";
    CHECK_EQ(factor_common_method(tasks).value_or(""), "IDW");
    tasks[0].method = "";
    tasks[2].method = "kriging";
    // Tie 1:1 — first-seen order wins (dict insertion order parity).
    CHECK_EQ(factor_common_method(tasks).value_or(""), "kriging");
    tasks[1].method = "";
    tasks[2].method = "";
    CHECK(!factor_common_method(tasks).has_value());
}

PWB_TEST(factor_prepared_summary_and_horizon) {
    std::vector<FactorTaskRecord> tasks(3);
    tasks[0].status = "complete";
    tasks[0].target_horizon = "Sq2";
    tasks[1].status = "pending";
    tasks[2].status = "complete";
    CHECK_EQ(factor_prepared_summary(tasks), "已制备 2 / 3 个单因素图");
    CHECK_EQ(factor_panel_horizon_text(tasks), "层位: Sq2");
    CHECK_EQ(factor_panel_horizon_text({}), "层位: —");
}

PWB_TEST(factor_completed_and_preview_header) {
    std::vector<FactorTaskRecord> tasks(2);
    tasks[0].status = "pending";
    tasks[1].status = "complete";
    tasks[1].target_horizon = "Sq2";
    tasks[1].method = "IDW";
    tasks[1].quality_metrics["grid"] = "50×50";
    const auto completed = factor_completed_tasks(tasks);
    CHECK_LL(completed.size(), 1);
    CHECK_EQ(factor_preview_header(completed),
             "Sq2 单因素图集（IDW插值 · 网格 50×50 m）");
    CHECK_EQ(factor_preview_header({}), "单因素图集");
}

PWB_TEST(factor_card_view_honest_fallbacks) {
    FactorTaskRecord task;
    task.factor_type = "砂厚";
    task.quality_metrics["range"] = "0.1 - 12.5";
    const auto view = factor_card_view(task);
    CHECK_EQ(view.title, "砂厚");
    CHECK_EQ(view.range_text, "0.1 - 12.5");
    // #939-5 parity: metrics present but R² omitted → reason shown, not
    // hidden.
    CHECK_EQ(view.rsquared_text, "R² 本轮未计算");
    CHECK(view.rsquared_visible);
    CHECK(!view.dup_visible);
}

PWB_TEST(factor_map_dialog_vocab_and_horizons) {
    CHECK(!factor_map_factor_items().empty());
    CHECK(!factor_map_method_items().empty());
    CHECK(!factor_map_ramp_items().empty());
    const auto horizons = factor_map_horizon_items("Sq2");
    CHECK_EQ(horizons.front(), "Sq2");
    // Dedupe: a default equal to the stratigraphy target appears once.
    const auto deduped = factor_map_horizon_items(horizons.back());
    int count = 0;
    for (const auto& h : deduped) {
        if (h == horizons.back()) {
            ++count;
        }
    }
    CHECK_LL(count, 1);
}

PWB_TEST(factor_map_job_cancel_and_service) {
    FactorMapParams params;
    params.factor_name = "砂厚";
    params.target_horizon = "Sq2";
    bool called = false;
    const FactorMapServiceFn service =
        [&called](const FactorMapParams& p) -> FactorMapOutcome {
        called = true;
        FactorMapOutcome outcome;
        outcome.map_title = "Sq2 砂厚";
        outcome.layer_count = 3;
        return outcome;
    };
    // Cooperative cancel BEFORE the service call → silent empty outcome,
    // service never invoked (isInterruptionRequested → return parity).
    pwb::job::CancellationToken cancelled_token;
    cancelled_token.cancel();
    pwb::job::JobContext cancelled_ctx("job-cancel", cancelled_token);
    const auto cancelled_outcome =
        run_factor_map_job(params, service, cancelled_ctx);
    CHECK(cancelled_outcome.map_title.empty());
    CHECK(!called);

    pwb::job::CancellationToken token;
    pwb::job::JobContext ctx("job-ok", token);
    const auto outcome = run_factor_map_job(params, service, ctx);
    CHECK(called);
    CHECK_EQ(outcome.map_title, "Sq2 砂厚");
    CHECK_LL(outcome.layer_count, 3);
    CHECK_EQ(factor_map_success_text(outcome.map_title, outcome.layer_count),
             "成功生成地质图件：Sq2 砂厚\n包含 3 个 GIS 图层。");
    CHECK_EQ(factor_map_failure_text("boom"), "地质编图失败：boom");
}

PWB_TEST(factor_selected_method_fallback) {
    CHECK_EQ(factor_selected_method("IDW"), "IDW");
    CHECK_EQ(factor_selected_method(""), "IDW");
}

int main() { return pwb_test::run_all(); }
