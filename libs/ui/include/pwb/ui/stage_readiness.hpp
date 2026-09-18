#pragma once

// CONV-27 — port of paleo_workbench/mapping_workspace/readiness.py +
// stage_profiles.py (readiness check lists). Stage readiness is advisory
// only: it hints, never blocks stage switching (V5 §18).
//
// The Python evaluator reads a duck-typed ProjectDocument; the C++ platform
// has no such document object yet, so the inputs are an explicit struct the
// host assembles from its live authorities (ProjectSession layers/facts,
// factor tasks, catalog snapshot). Check ids, statuses, wording, per-stage
// check lists and the status derivation are the Python contract verbatim.

#include <string>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui {

enum class ReadinessItemStatus { Ok, Warning, Error, Info };

const char* readiness_item_status_value(ReadinessItemStatus status);

struct ReadinessItem {
    std::string check_id;
    ReadinessItemStatus status = ReadinessItemStatus::Info;
    std::string title;
    std::string detail;
    // Navigation reference (UI click-through): layer_id / group_id / ...
    std::string target;

    int sort_weight() const;   // error 0, warning 1, info 2, ok 3
};

enum class StageReadinessStatus {
    Ready,
    ReadyWithWarnings,
    NotReady,
};

struct StageReadiness {
    pwb::tool_policy::MappingStage stage =
        pwb::tool_policy::MappingStage::FaciesCalibration;
    std::vector<ReadinessItem> items;

    StageReadinessStatus status() const;
    // "就绪" / "就绪（有提醒）" / "未就绪" (Python label wording).
    const char* label() const;
    std::vector<ReadinessItem> warnings() const;   // warning + error items
    std::vector<ReadinessItem> sorted_items() const;
};

// Everything the checks may read. All fields default to the "unconfigured"
// state; the evaluator treats missing input as warnings, never crashes
// (Python: default document=None semantics).
struct ReadinessInputs {
    // --- stage 1 (facies calibration) ---
    std::string target_horizon;              // stratigraphy/workflow horizon
    std::string project_crs;                 // coordinate.project_crs
    int facies_polygon_count = 0;            // paleomap facies polygons
    int facies_polygon_geometry_issues = 0;  // invalid/missing geometries
    bool facies_polygons_loaded = false;     // any polygon-bearing document
    int workarea_boundary_vertices = 0;      // finite vertices (>=3: blank facies)
    int real_prediction_tasks = 0;           // adapter_kind != "mock"
    int mock_prediction_tasks = 0;
    bool any_probability_summary = false;    // any task with probability data
    int low_confidence_regions = 0;          // summed over probability summaries
    int facies_draft_layers = 0;             // committed INITIAL_FACIES_DRAFT layers

    // --- stage 2 (constraint + factor) ---
    int constraint_lines = 0;                // constraint lines with >= 2 vertices
    int factor_tasks_total = 0;
    int factor_tasks_complete = 0;
    int stale_artifacts = 0;                 // freshness summary stale count

    // --- stage 3 (integrated compilation) ---
    int integrated_draft_layers = 0;         // INTEGRATED_FACIES/BOUNDARY layers
    int qa_geometry_issues = 0;              // latest QA report geometry issues
};

// The per-stage check lists (stage_profiles.py readiness_checks).
const std::vector<std::string>& stage_readiness_checks(
    pwb::tool_policy::MappingStage stage);

StageReadiness evaluate_stage_readiness(
    pwb::tool_policy::MappingStage stage, const ReadinessInputs& inputs);

// One check by id (unknown id -> std::nullopt-like empty item with Ok status
// is NOT used: unknown ids are skipped by the evaluator, mirroring Python).
ReadinessItem evaluate_readiness_check(const std::string& check_id,
                                       const ReadinessInputs& inputs);

}  // namespace pwb::ui
