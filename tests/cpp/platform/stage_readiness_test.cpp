// platform.stage_readiness — CONV-27 kernel test: the stage readiness
// contract (statuses, per-stage check lists, ordering, wording) against
// the Python source semantics (readiness.py + stage_profiles.py).

#include <cstdio>
#include <string>

#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui/stage_readiness.hpp>

#include "test_framework.hpp"

using pwb::tool_policy::MappingStage;
using pwb::ui::ReadinessInputs;
using pwb::ui::ReadinessItem;
using pwb::ui::ReadinessItemStatus;
using pwb::ui::evaluate_stage_readiness;
using pwb::ui::stage_readiness_checks;

namespace {

const ReadinessItem* find_item(const pwb::ui::StageReadiness& report,
                               const std::string& check_id) {
    for (const auto& item : report.items) {
        if (item.check_id == check_id) return &item;
    }
    return nullptr;
}

}  // namespace

int main() {
    // ---- per-stage check lists (stage_profiles.py order) ----------------
    {
        const auto& s1 = stage_readiness_checks(
            MappingStage::FaciesCalibration);
        PWB_CHECK(s1.size() == 7);
        PWB_CHECK(s1[0] == "target_horizon");
        PWB_CHECK(s1[1] == "initial_facies_present");
        PWB_CHECK(s1[6] == "interpretation_saved");

        const auto& s2 = stage_readiness_checks(
            MappingStage::ConstraintFactor);
        PWB_CHECK(s2.size() == 5);
        PWB_CHECK(s2[1] == "phase1_interpretation");
        PWB_CHECK(s2[2] == "constraints_present");

        const auto& s3 = stage_readiness_checks(
            MappingStage::IntegratedCompilation);
        PWB_CHECK(s3.size() == 5);
        PWB_CHECK(s3[1] == "evidence_available");
        PWB_CHECK(s3[4] == "qa_geometry_errors");
    }

    // ---- empty inputs: honest unconfigured state ------------------------
    {
        const ReadinessInputs empty;
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, empty);
        PWB_CHECK(report.status()
                  == pwb::ui::StageReadinessStatus::NotReady);
        PWB_CHECK(std::string(report.label()) == "未就绪");

        const auto* horizon = find_item(report, "target_horizon");
        PWB_CHECK(horizon != nullptr);
        PWB_CHECK(horizon->status == ReadinessItemStatus::Error);
        PWB_CHECK(horizon->title == "未设定编图层位");

        const auto* crs = find_item(report, "initial_facies_crs");
        PWB_CHECK(crs != nullptr);
        PWB_CHECK(crs->status == ReadinessItemStatus::Error);

        const auto* well = find_item(report, "well_prediction_linked");
        PWB_CHECK(well != nullptr);
        PWB_CHECK(well->status == ReadinessItemStatus::Warning);

        const auto* draft = find_item(report, "interpretation_saved");
        PWB_CHECK(draft != nullptr);
        PWB_CHECK(draft->status == ReadinessItemStatus::Info);

        // No polygons loaded -> geometry check is a pending INFO, not error.
        const auto* geometry = find_item(report, "initial_facies_geometry");
        PWB_CHECK(geometry != nullptr);
        PWB_CHECK(geometry->status == ReadinessItemStatus::Info);
    }

    // ---- workarea default blank facies (>=3 finite vertices) -----------
    {
        ReadinessInputs in;
        in.workarea_boundary_vertices = 4;
        in.target_horizon = "T1";
        in.project_crs = "EPSG:4326";
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, in);
        const auto* present = find_item(report, "initial_facies_present");
        PWB_CHECK(present != nullptr);
        PWB_CHECK(present->status == ReadinessItemStatus::Ok);
        PWB_CHECK(present->title == "初始相图（工区默认空白相）");
        // Polygon geometry check still pending (no polygons loaded).
        const auto* geometry = find_item(report, "initial_facies_geometry");
        PWB_CHECK(geometry != nullptr
                  && geometry->status == ReadinessItemStatus::Info);
        // No prediction tasks -> warning keeps the stage at WITH_WARNINGS.
        PWB_CHECK(report.status()
                  == pwb::ui::StageReadinessStatus::ReadyWithWarnings);
    }

    // ---- fully configured stage 1 reaches READY -------------------------
    {
        ReadinessInputs in;
        in.target_horizon = "T2";
        in.project_crs = "EPSG:4326";
        in.facies_polygon_count = 5;
        in.facies_polygons_loaded = true;
        in.real_prediction_tasks = 2;
        in.any_probability_summary = true;
        in.facies_draft_layers = 1;
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, in);
        for (const auto& item : report.items) {
            PWB_CHECK_MSG(
                item.status == ReadinessItemStatus::Ok,
                item.check_id + " expected ok, got "
                    + pwb::ui::readiness_item_status_value(item.status));
        }
        PWB_CHECK(report.status() == pwb::ui::StageReadinessStatus::Ready);
        PWB_CHECK(std::string(report.label()) == "就绪");
    }

    // ---- mock prediction wording parity ---------------------------------
    {
        ReadinessInputs in;
        in.mock_prediction_tasks = 1;
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, in);
        const auto* well = find_item(report, "well_prediction_linked");
        PWB_CHECK(well != nullptr);
        PWB_CHECK(well->status == ReadinessItemStatus::Ok);
        PWB_CHECK(well->detail.find("mock 演示任务") != std::string::npos);
    }

    // ---- stage 2: constraints + factors ----------------------------------
    {
        ReadinessInputs in;
        in.target_horizon = "T1";
        const auto empty = evaluate_stage_readiness(
            MappingStage::ConstraintFactor, in);
        const auto* constraints = find_item(empty, "constraints_present");
        PWB_CHECK(constraints != nullptr);
        PWB_CHECK(constraints->status == ReadinessItemStatus::Warning);
        PWB_CHECK(constraints->target == "phase2.constraints");
        const auto* factors = find_item(empty, "factors_complete");
        PWB_CHECK(factors != nullptr);
        PWB_CHECK(factors->status == ReadinessItemStatus::Warning);

        in.constraint_lines = 4;
        in.factor_tasks_total = 3;
        in.factor_tasks_complete = 3;
        const auto ready = evaluate_stage_readiness(
            MappingStage::ConstraintFactor, in);
        PWB_CHECK(ready.status() == pwb::ui::StageReadinessStatus::Ready);

        // Partial completion shows the progress ladder.
        in.factor_tasks_complete = 1;
        const auto partial = evaluate_stage_readiness(
            MappingStage::ConstraintFactor, in);
        const auto* ladder = find_item(partial, "factors_complete");
        PWB_CHECK(ladder != nullptr);
        PWB_CHECK(ladder->status == ReadinessItemStatus::Warning);
        PWB_CHECK(ladder->title == "1/3 个单因素完成");
    }

    // ---- stage 3: evidence gate + staleness ------------------------------
    {
        ReadinessInputs in;
        in.target_horizon = "T1";
        const auto none = evaluate_stage_readiness(
            MappingStage::IntegratedCompilation, in);
        const auto* evidence = find_item(none, "evidence_available");
        PWB_CHECK(evidence != nullptr);
        PWB_CHECK(evidence->status == ReadinessItemStatus::Error);
        PWB_CHECK(none.status() == pwb::ui::StageReadinessStatus::NotReady);

        in.factor_tasks_complete = 1;
        in.constraint_lines = 2;
        in.integrated_draft_layers = 1;
        const auto ready = evaluate_stage_readiness(
            MappingStage::IntegratedCompilation, in);
        PWB_CHECK(ready.status()
                  == pwb::ui::StageReadinessStatus::Ready);

        // Stale evidence degrades to warning but stays usable (advisory).
        in.stale_artifacts = 2;
        const auto stale = evaluate_stage_readiness(
            MappingStage::IntegratedCompilation, in);
        PWB_CHECK(stale.status()
                  == pwb::ui::StageReadinessStatus::ReadyWithWarnings);
        const auto* staleness = find_item(stale, "factor_staleness");
        PWB_CHECK(staleness != nullptr);
        PWB_CHECK(staleness->status == ReadinessItemStatus::Warning);
        PWB_CHECK(staleness->title == "2 项成果已过期");
    }

    // ---- sort order: errors before warnings before info/ok ---------------
    {
        ReadinessInputs in;   // errors present (no horizon, no CRS, no facies)
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, in);
        const auto sorted = report.sorted_items();
        PWB_CHECK(sorted.size() == report.items.size());
        int last_weight = -1;
        for (const auto& item : sorted) {
            PWB_CHECK(item.sort_weight() >= last_weight);
            last_weight = item.sort_weight();
        }
        // warnings() carries warning + error only.
        const auto warnings = report.warnings();
        for (const auto& item : warnings) {
            PWB_CHECK(item.status == ReadinessItemStatus::Warning
                      || item.status == ReadinessItemStatus::Error);
        }
        PWB_CHECK(warnings.size() >= 4);   // horizon, crs, facies, well
    }

    // ---- blank-facies boundary below 3 vertices stays an error ----------
    {
        ReadinessInputs in;
        in.workarea_boundary_vertices = 2;
        const auto report = evaluate_stage_readiness(
            MappingStage::FaciesCalibration, in);
        const auto* present = find_item(report, "initial_facies_present");
        PWB_CHECK(present != nullptr);
        PWB_CHECK(present->status == ReadinessItemStatus::Error);
        PWB_CHECK(present->title == "初始相图缺失");
    }

    return ::pwb::test::report("platform.stage_readiness");
}
