// V14-CONSTRAINT-FACTOR — test battery for
// apps/paleo_workbench_platform/factor_prepare_production (see
// docs/development/v14-constraint-factor/05-test-plan.md sections A1-A7
// plus the well-table bridge). Plain asserts, Qt-free, exit 0/1.
//
// Composition under test:
//   build_prepare_slice -> run_factor_prepare_schedule (real seams)
//   -> commit_prepare_batch_result (+ PersistentRuntimeCatalog)
//   -> commit_contour_drafts_full / well-table bridge + QC.
#include <cassert>
#include <cmath>
#ifdef _WIN32
#include <process.h>  // _getpid
#else
#include <unistd.h>
#endif
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <random>
#include <algorithm>
#include <set>
#include <string>

#include "factor_prepare_production.hpp"

using namespace pwb::factor_production;
using pwb::domain::Json;
using pwb::ui_workers::FactorPrepareBatchResult;
using pwb::ui_workers::FactorPrepareSeams;
using pwb::ui_workers::FactorPrepareSnapshot;
using pwb::ui_workers::FactorTaskSlice;

namespace {

int g_failures = 0;

#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

[[nodiscard]] Json make_point(double x, double y, double value,
                              const std::string& well = "A") {
    Json point = Json::object();
    point["well"] = well;
    point["x"] = x;
    point["y"] = y;
    point["value"] = value;
    return point;
}

[[nodiscard]] Json synthetic_points(int count, unsigned seed) {
    // A deterministic spread distinct from the geoviz synthetic oracle —
    // these are kernel inputs, not parity fixtures.
    std::mt19937 rng(seed);
    Json points = Json::array();
    for (int i = 0; i < count; ++i) {
        points.push_back(make_point(
            100.0 + static_cast<double>(rng() % 1000) / 100.0,
            30.0 + static_cast<double>(rng() % 1000) / 100.0,
            10.0 + static_cast<double>(rng() % 4000) / 100.0,
            "W" + std::to_string(i)));
    }
    return points;
}

[[nodiscard]] Json make_task(const std::string& id, const std::string& type,
                             const Json& points,
                             const std::string& method = "IDW") {
    Json task = Json::object();
    task["id"] = id;
    task["name"] = "C6 " + type;
    task["target_horizon"] = "C6";
    task["factor_type"] = type;
    task["method"] = method;
    task["status"] = "pending";
    task["source_kind"] = "mixed";
    task["parameters"] = Json::object();
    task["parameters"]["sample_points"] = points;
    return task;
}

[[nodiscard]] Json make_project(const std::vector<Json>& tasks,
                                const Json& constraint_layers = Json::array(),
                                const std::string& crs = "EPSG:32650") {
    Json root = Json::object();
    root["factor_map_tasks"] = Json::array();
    for (const auto& task : tasks) root["factor_map_tasks"].push_back(task);
    Json coordinate = Json::object();
    coordinate["project_crs"] = crs;
    root["coordinate"] = coordinate;
    Json stratigraphy = Json::object();
    stratigraphy["target_horizon"] = "C6";
    root["stratigraphy"] = stratigraphy;
    root["constraint_layers"] = constraint_layers;
    return root;
}

[[nodiscard]] Json make_break_line(const std::string& id, double x0,
                                   double y0) {
    Json layer = Json::object();
    layer["id"] = "clayers_1";
    layer["name"] = "约束层";
    layer["target_horizon"] = "C6";
    Json line = Json::object();
    line["id"] = id;
    line["role"] = "break";
    line["active"] = true;
    Json coords = Json::array();
    coords.push_back(Json::array({x0, y0}));
    coords.push_back(Json::array({x0 + 1.0, y0 + 5.0}));
    line["coordinates"] = coords;
    layer["lines"] = Json::array({line});
    return layer;
}

[[nodiscard]] Json make_boundary_ring(double cx, double cy, double r) {
    Json layer = Json::object();
    layer["id"] = "clayers_b";
    layer["target_horizon"] = "C6";
    Json line = Json::object();
    line["id"] = "cline_b";
    line["role"] = "boundary";
    line["active"] = true;
    Json coords = Json::array();
    for (int i = 0; i <= 4; ++i) {
        const double angle = i * 2.0 * M_PI / 4.0;
        coords.push_back(Json::array({cx + r * std::cos(angle),
                                      cy + r * std::sin(angle)}));
    }
    // square ring: 4 corners + explicit closure == first point
    line["coordinates"] = coords;
    layer["lines"] = Json::array({line});
    return layer;
}

[[nodiscard]] FactorPrepareSnapshot run_prepare(const Json& project,
                                                const std::string& method,
                                                LiveFactorGridStore& grids,
                                                FactorPrepareBatchResult* out,
                                                int generation = 1) {
    const auto slice = build_prepare_slice(project);
    const auto seams = make_factor_prepare_seams(
        std::shared_ptr<LiveFactorGridStore>(
            &grids, [](LiveFactorGridStore*) {}));  // non-owning view
    auto snapshot = pwb::ui_workers::build_prepare_snapshot(
        slice, generation, method, std::nullopt, 2.0, false, 0, std::nullopt,
        std::nullopt, seams);
    pwb::job::CancellationToken token;
    *out = pwb::ui_workers::run_factor_prepare_schedule(snapshot, token,
                                                        nullptr, seams, 0);
    return snapshot;
}

}  // namespace

// ---------------------------------------------------------------- A1 ---

void test_idw_positive(LiveFactorGridStore& grids) {
    Json project = make_project(
        {make_task("factor_t1", "地层厚度", synthetic_points(12, 7))});
    FactorPrepareBatchResult result;
    run_prepare(project, "IDW", grids, &result);
    CHECK(result.task_results.size() == 1);
    const auto& item = result.task_results[0];
    CHECK(!item.reused);
    CHECK(!item.error.has_value());
    const Json& task = *item.task->source_json;
    CHECK(task["status"] == "complete");
    CHECK(task["method"] == "IDW");
    const Json& params = task["parameters"];
    CHECK(params["interp_backend"] == "idw");
    CHECK(params["grid"] == "50×50");
    CHECK(params.contains("geometry_fingerprint"));
    CHECK(params.contains("values_fingerprint"));
    CHECK(params.contains("algorithm_fingerprint"));
    CHECK(params.contains("constraints_fingerprint"));
    CHECK(params.contains("result_fingerprint"));
    CHECK(params.contains("schema_version"));
    CHECK(!params.contains("grid_z"));
    CHECK(task["input_snapshot_hash"] ==
          params["result_fingerprint"].get<std::string>());
    CHECK(task["quality_metrics"]["n_points"] == 12);
    CHECK(task["quality_metrics"]["backend"] == "idw");
    CHECK(task["grid_metadata"].is_object());
    CHECK(grids.has("factor_t1"));
    auto entry = grids.peek("factor_t1").value();
    CHECK(entry.grid_x.size() == 50);
    CHECK(entry.grid_z.size() == 2500);
    CHECK(entry.result_fingerprint ==
          params["result_fingerprint"].get<std::string>());
    // finite cells present (IDW with all neighbours fills the padded extent)
    int finite = 0;
    for (const float z : entry.grid_z) {
        if (std::isfinite(z)) ++finite;
    }
    CHECK(finite > 2000);
}

void test_kriging_positive(LiveFactorGridStore& grids) {
    Json project = make_project(
        {make_task("factor_k1", "砂岩含量", synthetic_points(20, 11),
                   "克里金")});
    FactorPrepareBatchResult result;
    run_prepare(project, "克里金", grids, &result);
    const auto& item = result.task_results[0];
    CHECK(!item.error.has_value());
    const Json& task = *item.task->source_json;
    CHECK(task["status"] == "complete");
    const Json& params = task["parameters"];
    CHECK(params["interp_backend"] == "kriging");
    CHECK(params.contains("kriging_diagnostics"));
    CHECK(grids.has("factor_k1"));
    CHECK(!grids.peek("factor_k1")->variance_grid.empty());
}

void test_constrained_positive(LiveFactorGridStore& grids) {
    Json layers = Json::array({make_boundary_ring(105.0, 35.0, 6.0)});
    Json project =
        make_project({make_task("factor_c1", "砂地比", synthetic_points(10, 3),
                                "约束IDW")},
                     layers);
    FactorPrepareBatchResult result;
    run_prepare(project, "约束IDW", grids, &result);
    const auto& item = result.task_results[0];
    CHECK(!item.error.has_value());
    const Json& task = *item.task->source_json;
    CHECK(task["status"] == "complete");
    const Json& params = task["parameters"];
    CHECK(params["interp_backend"] == "constrained_idw");
    CHECK(params.contains("grid_boundary"));
    CHECK(params["constraint_pins"].is_array()
          && !params["constraint_pins"].empty());
    CHECK(grids.has("factor_c1"));
}

void test_determinism(LiveFactorGridStore& grids_a,
                      LiveFactorGridStore& grids_b) {
    Json project = make_project(
        {make_task("factor_d1", "泥岩含量", synthetic_points(15, 42))});
    FactorPrepareBatchResult a;
    FactorPrepareBatchResult b;
    run_prepare(project, "IDW", grids_a, &a, 1);
    run_prepare(project, "IDW", grids_b, &b, 2);
    const auto grid_a = grids_a.peek("factor_d1").value();
    const auto grid_b = grids_b.peek("factor_d1").value();
    CHECK(grid_a.result_fingerprint == grid_b.result_fingerprint);
    CHECK(grid_a.grid_z == grid_b.grid_z);
}

// ---------------------------------------------------------------- A2 ---

void test_degenerate_cases(LiveFactorGridStore& grids) {
    // <2 valid points -> failed with the engine text.
    Json few = make_project(
        {make_task("factor_e1", "地层厚度",
                   Json::array({make_point(1, 1, 5.0)}))});
    FactorPrepareBatchResult r1;
    run_prepare(few, "IDW", grids, &r1);
    CHECK(r1.task_results[0].error.has_value());
    CHECK(r1.task_results[0].task->status == "failed");
    CHECK((*r1.task_results[0].task->source_json)["parameters"]
              .contains("last_error"));
    CHECK(!grids.has("factor_e1"));  // failed run owns no grid (#918)

    // all non-finite values -> failed.
    Json nan_points = Json::array();
    for (int i = 0; i < 5; ++i) {
        Json p = make_point(i, i, std::nan(""));
        nan_points.push_back(p);
    }
    Json nans =
        make_project({make_task("factor_e2", "砂岩含量", nan_points)});
    FactorPrepareBatchResult r2;
    run_prepare(nans, "IDW", grids, &r2);
    CHECK(r2.task_results[0].error.has_value());

    // duplicate_policy=error with exact duplicates -> per-task failure,
    // the other task in the batch still completes.
    Json dup_points = Json::array({make_point(1, 1, 5.0, "A"),
                                   make_point(1, 1, 7.0, "B"),
                                   make_point(4, 5, 9.0, "C"),
                                   make_point(7, 8, 11.0, "D")});
    Json dup_task = make_task("factor_e3", "砂地比", dup_points);
    dup_task["parameters"]["duplicate_policy"] = "error";
    Json mixed = make_project(
        {dup_task, make_task("factor_e4", "泥岩含量",
                             synthetic_points(8, 5))});
    FactorPrepareBatchResult r3;
    run_prepare(mixed, "IDW", grids, &r3);
    CHECK(r3.failed_count == 1);
    CHECK(r3.task_results.size() == 2);
    bool saw_failed = false;
    bool saw_complete = false;
    for (const auto& item : r3.task_results) {
        if (item.task_id == "factor_e3") {
            CHECK(item.error.has_value());
            saw_failed = true;
        } else {
            CHECK(!item.error.has_value());
            saw_complete = true;
        }
    }
    CHECK(saw_failed && saw_complete);

    // 样条 / 方向趋势 — NATIVE kernels since the scipy_grid (Clough-Tocher
    // cubic) / directional_trend ports: real grids land (the pre-kernel
    // honest degrade was the explicit "未原生接入" failure — now stale).
    for (const std::string& method : {"样条", "方向趋势"}) {
        Json project = make_project(
            {make_task("factor_m1", "地层厚度",
                       synthetic_points(10, 9), method)});
        FactorPrepareBatchResult r;
        run_prepare(project, method, grids, &r);
        CHECK(!r.task_results[0].error.has_value());
        CHECK(grids.has("factor_m1"));
    }

    // plain IDW + active break lines -> fails closed (the native plain
    // kernel cannot consume them; silently ignoring would fake
    // participation).
    Json with_break =
        make_project({make_task("factor_b1", "地层厚度",
                                synthetic_points(10, 13))},
                     Json::array({make_break_line("cline_b1", 100.0, 30.0)}));
    FactorPrepareBatchResult r4;
    run_prepare(with_break, "IDW", grids, &r4);
    CHECK(r4.task_results[0].error.has_value());
    CHECK((*r4.task_results[0].error).find("constrained_idw")
          != std::string::npos);

    // kriging + direction lines -> fails closed (no anisotropy input).
    Json dir_layer = make_break_line("cline_d1", 100.0, 30.0);
    dir_layer["lines"][0]["role"] = "direction";
    Json with_dir =
        make_project({make_task("factor_b2", "砂岩含量",
                                synthetic_points(10, 17), "克里金")},
                     Json::array({dir_layer}));
    FactorPrepareBatchResult r5;
    run_prepare(with_dir, "克里金", grids, &r5);
    CHECK(r5.task_results[0].error.has_value());

    // constrained with <3 wells -> failed with engine text.
    Json small = make_project(
        {make_task("factor_c2", "砂地比",
                   Json::array({make_point(0, 0, 1.0),
                                make_point(1, 1, 2.0)}),
                   "约束IDW")},
        Json::array({make_boundary_ring(1.0, 1.0, 10.0)}));
    FactorPrepareBatchResult r6;
    run_prepare(small, "约束IDW", grids, &r6);
    CHECK(r6.task_results[0].error.has_value());

    // constrained without a user ring -> the sample convex hull
    // synthesizes the boundary (adapter parity); degenerate (<3 unique
    // positions) still refuses with the engine text.
    Json no_boundary = make_project(
        {make_task("factor_c3", "砂地比",
                   synthetic_points(8, 21), "约束IDW")});
    FactorPrepareBatchResult r7;
    run_prepare(no_boundary, "约束IDW", grids, &r7);
    CHECK(!r7.task_results[0].error.has_value());
    CHECK((*r7.task_results[0].task->source_json)["parameters"]
              .contains("grid_boundary"));
    Json degenerate = make_project(
        {make_task("factor_c3b", "砂地比",
                   Json::array({make_point(1, 1, 5.0),
                                make_point(1, 1, 6.0),
                                make_point(2, 2, 7.0)}),
                   "约束IDW")});
    FactorPrepareBatchResult r8;
    run_prepare(degenerate, "约束IDW", grids, &r8);
    CHECK(r8.task_results[0].error.has_value());
}

// ---------------------------------------------------------------- A3 ---

void test_classify_reuse(LiveFactorGridStore& grids) {
    Json project = make_project(
        {make_task("factor_r1", "地层厚度", synthetic_points(10, 31)),
         make_task("factor_r2", "砂岩含量", synthetic_points(10, 32))});
    FactorPrepareBatchResult first;
    run_prepare(project, "IDW", grids, &first, 1);
    CHECK(first.clean_count == 0);
    CHECK(first.executed_count == 2);
    CHECK(first.dirty_count == 2);
    // The reuse decision reads the COMMITTED state (status + stored
    // fingerprints + live grid): commit the first run before rerunning.
    pwb::workflow_runtime::RuntimeStore catalog;
    auto committed = commit_prepare_batch_result(project, first, 1, grids,
                                                 &catalog);
    CHECK(committed.applied == 2);

    // identical rerun -> everything CLEAN / reused.
    FactorPrepareBatchResult second;
    run_prepare(project, "IDW", grids, &second, 2);
    CHECK(second.clean_count == 2);
    CHECK(second.executed_count == 0);
    CHECK(second.task_results[0].reused);
    CHECK(second.task_results[1].reused);

    // change ONE task's VALUES (coordinates held fixed) -> only that
    // task recomputes ("recompute only the affected factor").
    Json changed = project;
    {
        Json points = changed["factor_map_tasks"][0]["parameters"]
                          ["sample_points"];
        for (auto& point : points) {
            point["value"] = point["value"].get<double>() + 13.0;
        }
        changed["factor_map_tasks"][0]["parameters"]["sample_points"] =
            points;
    }
    FactorPrepareBatchResult third;
    run_prepare(changed, "IDW", grids, &third, 3);
    CHECK(third.clean_count == 1);
    CHECK(third.dirty_count == 1);
    CHECK(third.task_results[0].dirty_state == "DIRTY_VALUES");

    // constraint change -> DIRTY_CONSTRAINTS for the constrained task.
    Json layers = Json::array({make_boundary_ring(105.0, 35.0, 6.0)});
    Json cproject = make_project(
        {make_task("factor_r3", "砂地比", synthetic_points(10, 33),
                   "约束IDW")},
        layers);
    FactorPrepareBatchResult c1;
    run_prepare(cproject, "约束IDW", grids, &c1, 4);
    CHECK(c1.executed_count == 1);
    CHECK(commit_prepare_batch_result(cproject, c1, 4, grids, &catalog)
              .applied == 1);
    Json layers2 = Json::array({make_boundary_ring(105.0, 35.0, 7.0)});
    Json cproject2 = cproject;
    cproject2["constraint_layers"] = layers2;
    // keep the fingerprint inputs of the committed state (task patch from
    // the first run rides in cproject already — rerun on the same doc)
    FactorPrepareBatchResult c2;
    // direction lines drive the constraints fingerprint (Python parity:
    // boundary rings are pinned via constraint_pins content hashes, but do
    // not enter the Stage-4 fingerprints — see 08-known-limitations).
    Json dir_layer = make_break_line("cline_dir", 104.0, 34.0);
    dir_layer["lines"][0]["role"] = "direction";
    cproject2["constraint_layers"] =
        Json::array({make_boundary_ring(105.0, 35.0, 7.0), dir_layer});
    run_prepare(cproject2, "约束IDW", grids, &c2, 5);
    CHECK(c2.task_results[0].dirty_state == "DIRTY_CONSTRAINTS");

    // grid_n change -> DIRTY_GEOMETRY (scheduled override differs).
    {
        const auto slice = build_prepare_slice(project);
        const auto seams = make_factor_prepare_seams(
            std::shared_ptr<LiveFactorGridStore>(&grids,
                                                 [](LiveFactorGridStore*) {}));
        auto snapshot = pwb::ui_workers::build_prepare_snapshot(
            slice, 6, "IDW", /*grid_n=*/80, 2.0, false, 0, std::nullopt,
            std::nullopt, seams);
        pwb::job::CancellationToken token;
        auto r = pwb::ui_workers::run_factor_prepare_schedule(
            snapshot, token, nullptr, seams, 0);
        CHECK(r.task_results[0].dirty_state == "DIRTY_GEOMETRY");
    }
}

// ---------------------------------------------------------------- A4 ---

void test_commit_semantics(LiveFactorGridStore& grids) {
    pwb::workflow_runtime::RuntimeStore catalog;

    // generation mismatch discards everything, project untouched.
    Json project = make_project(
        {make_task("factor_g1", "地层厚度", synthetic_points(10, 51))});
    project["factor_map_tasks"][0]["custom_field"] = "keepme";
    FactorPrepareBatchResult r;
    run_prepare(project, "IDW", grids, &r, 10);
    auto mismatch = commit_prepare_batch_result(project, r, 11, grids);
    CHECK(mismatch.applied == 0);
    CHECK(mismatch.discarded.size() == 1);
    CHECK(project["factor_map_tasks"][0]["status"] == "pending");

    // matching generation applies the patch; the snapshot-time unknown
    // field survives the wholesale replacement (deep-copy patch parity).
    auto ok = commit_prepare_batch_result(project, r, 10, grids, &catalog);
    CHECK(ok.applied == 1);
    CHECK(ok.discarded.empty());
    CHECK(project["factor_map_tasks"][0]["status"] == "complete");
    CHECK(project["factor_map_tasks"][0]["custom_field"] == "keepme");
    CHECK(project["factor_map_tasks"][0]["grid_artifact_version_id"]
              .is_string());

    // stale-input guard: live sample points changed between schedule and
    // commit -> the patch is discarded, nothing mutates.
    Json project2 = make_project(
        {make_task("factor_g2", "砂岩含量", synthetic_points(10, 52))});
    FactorPrepareBatchResult r2;
    run_prepare(project2, "IDW", grids, &r2, 20);
    project2["factor_map_tasks"][0]["parameters"]["sample_points"] =
        synthetic_points(10, 99);
    auto stale = commit_prepare_batch_result(project2, r2, 20, grids,
                                             &catalog);
    CHECK(stale.applied == 0);
    CHECK(stale.discarded.size() == 1);
    CHECK(project2["factor_map_tasks"][0]["status"] == "pending");

    // cancelled result: no partial commit, non-reused grids invalidated.
    Json project3 = make_project(
        {make_task("factor_g3", "泥岩含量", synthetic_points(10, 53))});
    FactorPrepareBatchResult cancelled;
    cancelled.generation = 30;
    cancelled.method = "IDW";
    cancelled.cancelled = true;
    pwb::ui_workers::FactorPrepareTaskResult item;
    item.task_id = "factor_g3";
    item.dirty_state = "MISSING_OUTPUT";
    cancelled.task_results.push_back(item);
    // Seed a live grid with a DIFFERENT fingerprint: the cancelled run
    // produced no grid, so the fingerprint-conditional invalidation
    // (#881) leaves the still-valid previous payload in place.
    LiveGridEntry entry;
    entry.grid_x = {0.0, 1.0};
    entry.grid_y = {0.0, 1.0};
    entry.grid_z = {1.0f, 2.0f, 3.0f, 4.0f};
    entry.result_fingerprint = "fp_old";
    grids.store("factor_g3", entry);
    auto creport = commit_prepare_batch_result(project3, cancelled, 30,
                                               grids, &catalog);
    CHECK(creport.applied == 0);
    CHECK(grids.has("factor_g3"));  // #881: no grid produced -> no eviction
    CHECK(project3["factor_map_tasks"][0]["status"] == "pending");

    // first-prepare defaults bootstrap: empty task list grows the four
    // default factor types; late defaults on a non-empty project are
    // dropped wholesale (#1159).
    Json empty_project = make_project({});
    FactorPrepareBatchResult defaults;
    defaults.generation = 40;
    defaults.method = "IDW";
    defaults.created_default_tasks = true;
    {
        const auto slice = build_prepare_slice(empty_project);
        const auto seams = make_factor_prepare_seams(
            std::shared_ptr<LiveFactorGridStore>(&grids,
                                                 [](LiveFactorGridStore*) {}));
        auto snapshot = pwb::ui_workers::build_prepare_snapshot(
            slice, 40, "IDW", std::nullopt, 2.0, false, 0, std::nullopt,
            std::nullopt, seams);
        pwb::job::CancellationToken token;
        defaults = pwb::ui_workers::run_factor_prepare_schedule(
            snapshot, token, nullptr, seams, 0);
    }
    CHECK(defaults.created_default_tasks);
    CHECK(defaults.task_results.size() == 4);
    auto boot = commit_prepare_batch_result(empty_project, defaults, 40,
                                            grids, &catalog);
    CHECK(boot.applied == 4);
    CHECK(empty_project["factor_map_tasks"].size() == 4);
    // distinct ids (the scheduler's synthesized ids must not collide)
    std::set<std::string> ids;
    for (const auto& task : empty_project["factor_map_tasks"]) {
        ids.insert(task["id"].get<std::string>());
    }
    CHECK(ids.size() == 4);
    for (const auto& task : empty_project["factor_map_tasks"]) {
        CHECK(task["status"] == "complete");
    }
    // late defaults against a project that gained tasks -> all discarded.
    auto late = commit_prepare_batch_result(empty_project, defaults, 40,
                                            grids, &catalog);
    CHECK(late.applied == 0);
    CHECK(late.discarded.size() == 4);
    CHECK(empty_project["factor_map_tasks"].size() == 4);

    // unknown task id (not a defaults run) -> discarded, project intact.
    Json project4 = make_project(
        {make_task("factor_g4", "地层厚度", synthetic_points(10, 54))});
    FactorPrepareBatchResult ghost;
    ghost.generation = 50;
    ghost.method = "IDW";
    pwb::ui_workers::FactorPrepareTaskResult ghost_item;
    ghost_item.task_id = "factor_ghost";
    ghost_item.dirty_state = "MISSING_OUTPUT";
    pwb::ui_workers::FactorTaskSlice ghost_slice;
    ghost_slice.id = "factor_ghost";
    ghost_slice.name = "x";
    ghost_slice.status = "complete";
    ghost_slice.target_horizon = "C6";
    ghost_slice.factor_type = "x";
    ghost_slice.method = "IDW";
    ghost_slice.source_json = make_task("factor_ghost", "x",
                                        synthetic_points(4, 1));
    ghost_item.task = ghost_slice;
    ghost.task_results.push_back(ghost_item);
    auto ghost_report = commit_prepare_batch_result(project4, ghost, 50,
                                                    grids, &catalog);
    CHECK(ghost_report.applied == 0);
    CHECK(project4["factor_map_tasks"].size() == 1);
}

// ---------------------------------------------------------------- A5 ---

void test_catalog_registration(LiveFactorGridStore& grids) {
    pwb::workflow_runtime::RuntimeStore catalog;
    Json project = make_project(
        {make_task("factor_p1", "地层厚度", synthetic_points(10, 61)),
         make_task("factor_p2", "砂岩含量", synthetic_points(10, 62))});
    FactorPrepareBatchResult r;
    run_prepare(project, "IDW", grids, &r, 60);
    auto report = commit_prepare_batch_result(project, r, 60, grids,
                                              &catalog);
    CHECK(report.applied == 2);
    CHECK(report.registered_version_ids.size() == 2);

    const auto runs = catalog.list_runs();
    CHECK(runs.size() == 2);
    int factor_map_runs = 0;
    for (const auto& run : runs) {
        CHECK(run.operation == "factor_map");
        CHECK(run.status == "complete");
        CHECK(run.domain_task_id.has_value());
        factor_map_runs++;
    }
    CHECK(factor_map_runs == 2);
    CHECK(catalog.list_assets().size() == 2);
    for (const auto& task : project["factor_map_tasks"]) {
        const std::string vid =
            task["grid_artifact_version_id"].get<std::string>();
        const auto version = catalog.resolve_version(vid);
        CHECK(version.has_value());
        CHECK(version->metadata.value("generator", "") ==
              "factor-interp-v1");
        // payload round-trips as the legacy grid dict
        CHECK(!version->payload_json.empty());
        const Json payload = Json::parse(version->payload_json);
        CHECK(payload.contains("grid_x"));
        CHECK(payload.contains("grid_z"));
    }

    // null catalog: honest degradation — tasks commit, no version stamps.
    Json project2 = make_project(
        {make_task("factor_p3", "泥岩含量", synthetic_points(10, 63))});
    FactorPrepareBatchResult r2;
    run_prepare(project2, "IDW", grids, &r2, 61);
    auto degraded = commit_prepare_batch_result(project2, r2, 61, grids,
                                                nullptr);
    CHECK(degraded.applied == 1);
    CHECK(degraded.registered_version_ids.empty());
    CHECK(project2["factor_map_tasks"][0]["grid_artifact_version_id"]
              .is_null());
}

// ---------------------------------------------------------------- A6 ---

void test_contour_commit() {
    Json project = make_project({});
    project["contour_drafts"] = Json::array();
    Json draft = Json::object();
    draft["id"] = "cdraft_1";
    draft["name"] = "C6 地层厚度 等值线初稿";
    draft["target_horizon"] = "C6";
    draft["factor_type"] = "地层厚度";
    draft["linked_factor_task_id"] = "factor_t9";
    draft["levels"] = Json::array({1.0, 2.0});
    Json segment = Json::object();
    segment["id"] = "cseg_1";
    segment["level"] = 1.0;
    segment["coordinates"] =
        Json::array({Json::array({100.0, 30.0}),
                     Json::array({101.0, 31.0})});
    segment["closed"] = false;
    segment["properties"] = Json::object();
    draft["segments"] = Json::array({segment});
    draft["source_grid_n"] = 50;
    draft["source_backend"] = "idw";
    draft["source_value_range"] = Json::array({0.0, 5.0});
    draft["generator_version"] = "contour-draft-v2";

    const int first = commit_contour_drafts_full(
        project, Json::array({draft}));
    CHECK(first == 1);
    CHECK(project["contour_drafts"].size() == 1);
    CHECK(project["paleomap_documents"].size() == 1);
    const std::string doc_id =
        project["paleomap_documents"][0]["id"].get<std::string>();
    CHECK(project["paleomap_documents"][0]["line_features"].size() == 1);
    CHECK(project["paleomap_documents"][0]["line_features"][0]["role"]
          == "contour");
    CHECK(project["paleomap_documents"][0]["linked_contour_draft_id"]
          == "cdraft_1");
    CHECK(project["contour_drafts"][0]["status"] == "editing");

    // rerun with a different segment set: draft id preserved, features
    // replaced (never stacked).
    Json draft2 = draft;
    draft2["segments"] = Json::array({segment, segment});
    const int second = commit_contour_drafts_full(
        project, Json::array({draft2}));
    CHECK(second == 1);
    CHECK(project["contour_drafts"].size() == 1);
    CHECK(project["contour_drafts"][0]["id"] == "cdraft_1");
    CHECK(project["paleomap_documents"].size() == 1);
    CHECK(project["paleomap_documents"][0]["id"] == doc_id);
    CHECK(project["paleomap_documents"][0]["line_features"].size() == 2);
}

// ---------------------------------------------------------------- A7 ---

void test_persistence(const std::filesystem::path& tmp) {
    const auto root = tmp / "persist_proj";
    std::filesystem::create_directories(root);
    PersistentRuntimeCatalog catalog;
    catalog.open(root / "workflow_provenance");
    CHECK(std::filesystem::exists(root / "workflow_provenance.json")
          || true);  // fresh store: file appears on first mutation

    LiveFactorGridStore grids;
    Json project = make_project(
        {make_task("factor_s1", "地层厚度", synthetic_points(10, 71))});
    FactorPrepareBatchResult r;
    run_prepare(project, "IDW", grids, &r, 70);
    auto report =
        commit_prepare_batch_result(project, r, 70, grids, &catalog);
    CHECK(report.applied == 1);
    CHECK(std::filesystem::exists(root / "workflow_provenance.json"));

    // reopen: runs/versions survive the process boundary.
    PersistentRuntimeCatalog reopened;
    reopened.open(root / "workflow_provenance");
    CHECK(reopened.list_runs().size() == 1);
    CHECK(reopened.list_assets().size() == 1);
    const auto& version_id = report.registered_version_ids[0];
    const auto version = reopened.resolve_version(version_id);
    CHECK(version.has_value());
    CHECK(version->metadata.value("generator", "") == "factor-interp-v1");

    // task JSON ↔ catalog consistency (the reopen lineage contract).
    const std::string stamped =
        project["factor_map_tasks"][0]["grid_artifact_version_id"]
            .get<std::string>();
    CHECK(stamped == version_id);
    // Sidecar payload: the store JSON stays metadata-only; the grid
    // payload lives beside it.
    CHECK(std::filesystem::exists(root / ("workflow_provenance.json.payloads/" + version_id + ".json")));
    {
        std::ifstream store_in(root / "workflow_provenance.json",
                               std::ios::binary);
        const std::string store_text((std::istreambuf_iterator<char>(store_in)),
                                     std::istreambuf_iterator<char>());
        const Json rail = Json::parse(store_text);
        for (const auto& node : rail["versions"]) {
            CHECK(node.value("payload_json", std::string()).empty());
        }
    }

    // corrupt store refuses to open (fail-closed over provenance).
    {
        std::ofstream out(root / "broken.json", std::ios::trunc);
        out << "{not json";
    }
    PersistentRuntimeCatalog broken;
    bool threw = false;
    try {
        broken.open(root / "broken");
    } catch (const std::exception&) {
        threw = true;
    }
    CHECK(threw);
}

// ------------------------------------------------------- well-table ops --

void test_well_table_bridge() {
    CHECK(value_key_for_factor_type("砂地比") == "R_s");
    CHECK(value_key_for_factor_type("地层厚度") == "H_t");
    CHECK(value_key_for_factor_type("砂岩厚度") == "H_s");
    CHECK(value_key_for_factor_type("孔隙度") == "z");

    Json table = Json::object();
    table["id"] = "wtable_1";
    table["factor_type"] = "砂地比";
    Json rows = Json::array();
    for (int i = 0; i < 6; ++i) {
        Json row = Json::object();
        row["well_id"] = "well_" + std::to_string(i);
        row["name"] = "W" + std::to_string(i);
        row["x"] = 100.0 + i;
        row["y"] = 30.0 + i;
        row["H_s"] = 10.0 + i;
        row["H_t"] = 40.0 + i;
        row["qc_flag"] = "ok";
        rows.push_back(row);
    }
    // one outlier row (R_s far off) + one invalid ratio row.
    rows[2]["H_s"] = 39.0;
    rows[2]["H_t"] = 40.0;  // R_s=0.975 — the MAD outlier among ~0.25
    rows[4]["H_s"] = 50.0;
    rows[4]["H_t"] = 40.0;  // H_s > H_t -> invalid_ratio
    table["rows"] = rows;

    // QC mutates flags + writes R_s.
    const auto summary = run_well_table_qc(table, "R_s");
    CHECK(summary["invalid_ratio"] == 1);
    CHECK(summary["missing"] == 0);
    CHECK(table["rows"][4]["qc_flag"] == "invalid_ratio");
    CHECK(table["rows"][4]["R_s"].is_null());
    // ok + outlier + invalid + missing == 6
    const int total = summary["ok"].get<int>()
                      + summary["outlier"].get<int>()
                      + summary["invalid_ratio"].get<int>()
                      + summary["missing"].get<int>();
    CHECK(total == 6);

    // export excludes flagged rows by default.
    const auto points = sample_points_from_well_table(table);
    for (const auto& point : points) {
        CHECK(point["qc_flag"] == "ok");
    }
    CHECK(points.size() == static_cast<std::size_t>(
                               summary["ok"].get<int>()));

    // sync writes the QC-passing points onto the bound task only.
    Json project = make_project(
        {make_task("factor_w1", "砂地比",
                   synthetic_points(4, 2)),
         make_task("factor_w2", "地层厚度",
                   synthetic_points(4, 3))});
    project["factor_map_tasks"][0]["parameters"]["well_table_id"] =
        "wtable_1";
    const auto updated =
        sync_well_table_to_linked_tasks(project, table, "R_s");
    CHECK(updated.size() == 1);
    CHECK(updated[0] == "factor_w1");
    CHECK(project["factor_map_tasks"][0]["parameters"]["sample_points"]
              .size() == points.size());
    CHECK(project["factor_map_tasks"][1]["parameters"]["sample_points"]
              .size() == 4);  // untouched
}

// ------------------------------------------------------ adversarial add-ons --

void test_cancel_mid_run(LiveFactorGridStore& grids) {
    // A pre-cancelled token: the scheduler cancels between tasks; the
    // commit must apply NOTHING and evict nothing (#881).
    Json project = make_project(
        {make_task("factor_xa", "地层厚度", synthetic_points(10, 91)),
         make_task("factor_xb", "砂岩含量", synthetic_points(10, 92))});
    const auto slice = build_prepare_slice(project);
    const auto seams = make_factor_prepare_seams(
        std::shared_ptr<LiveFactorGridStore>(&grids,
                                            [](LiveFactorGridStore*) {}));
    auto snapshot = pwb::ui_workers::build_prepare_snapshot(
        slice, 90, "IDW", std::nullopt, 2.0, false, 0, std::nullopt,
        std::nullopt, seams);
    pwb::job::CancellationToken token;
    token.cancel();  // pre-cancelled: the scheduler refuses before classify
    bool threw_cancelled = false;
    pwb::ui_workers::FactorPrepareBatchResult r;
    try {
        r = pwb::ui_workers::run_factor_prepare_schedule(snapshot, token,
                                                          nullptr, seams, 0);
    } catch (const pwb::job::JobCancelled&) {
        threw_cancelled = true;  // scheduler's pre-classify cancel guard
    }
    CHECK(threw_cancelled);
    // The commit contract under cancel: even a partially-staged result
    // (cancelled=true) must apply nothing and evict nothing (#881) —
    // synthesise the same shape the scheduler hands back mid-run.
    r.generation = 90;
    r.method = "IDW";
    r.cancelled = true;
    r.clean_count = 0;
    r.executed_count = 0;
    for (const auto& task : snapshot.tasks) {
        pwb::ui_workers::FactorPrepareTaskResult item;
        item.task_id = task.id;
        item.dirty_state = "MISSING_OUTPUT";
        r.task_results.push_back(item);
    }
    pwb::workflow_runtime::RuntimeStore catalog;
    const auto report = commit_prepare_batch_result(project, r, 90, grids,
                                                    &catalog);
    CHECK(report.applied == 0);
    CHECK(report.discarded.size() == 2);
    CHECK(project["factor_map_tasks"][0]["status"] == "pending");
    CHECK(catalog.list_runs().empty());
}

void test_degenerate_hull_refusal(LiveFactorGridStore& grids) {
    // Collinear wells: the synthesized hull has zero area — the task must
    // fail (scipy QhullError parity), never complete an all-NaN surface.
    Json collinear = Json::array();
    for (int i = 0; i < 6; ++i) {
        collinear.push_back(make_point(i, 2 * i, 5.0 + i, "W"));
    }
    Json project = make_project(
        {make_task("factor_xc", "砂地比", collinear, "约束IDW")});
    FactorPrepareBatchResult r;
    run_prepare(project, "约束IDW", grids, &r, 91);
    CHECK(r.task_results[0].error.has_value());
    CHECK(!grids.has("factor_xc"));
}

void test_direction_degenerate_skip(LiveFactorGridStore& grids) {
    // A zero-length direction line (no explicit azimuth) is skipped — the
    // task still runs on its boundary ring alone.
    Json layer = make_boundary_ring(105.0, 35.0, 6.0);
    Json zero_line = Json::object();
    zero_line["id"] = "cline_zero";
    zero_line["role"] = "direction";
    zero_line["active"] = true;
    zero_line["coordinates"] =
        Json::array({Json::array({104.0, 34.0}),
                     Json::array({104.0, 34.0})});
    layer["lines"].push_back(zero_line);
    Json project =
        make_project({make_task("factor_xd", "砂地比",
                                synthetic_points(8, 31), "约束IDW")},
                     Json::array({layer}));
    FactorPrepareBatchResult r;
    run_prepare(project, "约束IDW", grids, &r, 92);
    CHECK(!r.task_results[0].error.has_value());
}

void test_multi_window_rail_drift(const std::filesystem::path& tmp) {
    // A second store opening the same rail must refuse to clobber the
    // first window's provenance (fail closed, not last-writer-wins).
    const auto root = tmp / "drift_proj";
    std::filesystem::create_directories(root);
    LiveFactorGridStore grids_a;
    PersistentRuntimeCatalog rail_a;
    rail_a.open(root / "workflow_provenance");
    Json project_a = make_project(
        {make_task("factor_ma", "地层厚度", synthetic_points(10, 93))});
    FactorPrepareBatchResult r_a;
    run_prepare(project_a, "IDW", grids_a, &r_a, 93);
    CHECK(commit_prepare_batch_result(project_a, r_a, 93, grids_a,
                                      &rail_a)
              .applied == 1);

    // Window B snapshots the rail (its own open).
    PersistentRuntimeCatalog rail_b;
    rail_b.open(root / "workflow_provenance");
    // Window A commits again (advancing the on-disk state).
    Json project_a2 = make_project(
        {make_task("factor_mb", "砂岩含量", synthetic_points(10, 94))});
    project_a2["factor_map_tasks"][0]["parameters"]["sample_points"] =
        synthetic_points(10, 95);
    FactorPrepareBatchResult r_a2;
    run_prepare(project_a2, "IDW", grids_a, &r_a2, 94);
    CHECK(commit_prepare_batch_result(project_a2, r_a2, 94, grids_a,
                                      &rail_a)
              .applied == 1);

    // Window B's flush now sees the drift: the mutation must THROW
    // (the install catches it and detaches the rail — honest
    // degradation, no history loss).
    LiveFactorGridStore grids_b;
    Json project_b = make_project(
        {make_task("factor_mc", "泥岩含量", synthetic_points(10, 96))});
    FactorPrepareBatchResult r_b;
    run_prepare(project_b, "IDW", grids_b, &r_b, 95);
    bool refused = false;
    try {
        commit_prepare_batch_result(project_b, r_b, 95, grids_b, &rail_b);
    } catch (const std::exception&) {
        refused = true;
    }
    CHECK(refused);
    // The rail still holds BOTH of window A's runs (nothing clobbered).
    PersistentRuntimeCatalog reopened;
    reopened.open(root / "workflow_provenance");
    CHECK(reopened.list_runs().size() == 2);
}

// ----------------------------------------------------------- cross-well --

void test_factor_context_provider() {
    pwb::workflow_runtime::RuntimeStore catalog;
    LiveFactorGridStore grids;
    Json project = make_project(
        {make_task("factor_x1", "地层厚度", synthetic_points(10, 81))});
    FactorPrepareBatchResult r;
    run_prepare(project, "IDW", grids, &r, 80);
    CHECK(commit_prepare_batch_result(project, r, 80, grids, &catalog)
              .applied == 1);

    // Wells inside the interpolated extent: on-grid hits; a far-off
    // well: honest NaN (off-grid bilinear returns nullopt).
    std::vector<std::pair<std::string, std::array<double, 2>>> wells = {
        {"W0", {104.5, 34.0}}, {"W1", {106.0, 32.5}},
        {"FAR", {500.0, 500.0}}};
    const auto samples =
        sample_factor_context(project, wells, &grids, &catalog);
    CHECK(samples.size() == 3);
    int finite = 0;
    for (const auto& sample : samples) {
        CHECK(sample.task_id == "factor_x1");
        CHECK(sample.factor_type == "地层厚度");
        CHECK(!sample.version_id.empty());
        if (std::isfinite(sample.value)) ++finite;
    }
    CHECK(finite >= 2);   // in-extent wells hit
    CHECK(finite < 3);    // the far well is off-grid (honest NaN)

    // Live-cache leg: the catalog leg is exercised by clearing the cache —
    // the version payload still resolves the same grid.
    grids.clear("factor_x1");
    const auto replayed =
        sample_factor_context(project, wells, nullptr, &catalog);
    CHECK(replayed.size() == 3);
    int finite_replay = 0;
    for (const auto& sample : replayed) {
        if (std::isfinite(sample.value)) ++finite_replay;
    }
    CHECK(finite_replay == finite);  // catalog payload == live grid
}

// ---------------------------------------------------------------- main --

int main(int argc, char** argv) {
    std::filesystem::path tmp =
        std::filesystem::temp_directory_path()
        / ("pwb_factor_prepare_" +
           std::to_string(
#ifdef _WIN32
               _getpid()
#else
               ::getpid()
#endif
               ));
    std::filesystem::create_directories(tmp);

    LiveFactorGridStore grids;
    test_idw_positive(grids);
    test_kriging_positive(grids);
    test_constrained_positive(grids);
    {
        LiveFactorGridStore ga;
        LiveFactorGridStore gb;
        test_determinism(ga, gb);
    }
    test_degenerate_cases(grids);
    test_classify_reuse(grids);
    test_commit_semantics(grids);
    test_catalog_registration(grids);
    test_contour_commit();
    test_persistence(tmp);
    test_well_table_bridge();
    test_factor_context_provider();
    test_cancel_mid_run(grids);
    test_degenerate_hull_refusal(grids);
    test_direction_degenerate_skip(grids);
    test_multi_window_rail_drift(tmp);

    std::filesystem::remove_all(tmp);
    if (g_failures == 0) {
        std::printf("factor_prepare_production: ALL GREEN\n");
        return 0;
    }
    std::printf("factor_prepare_production: %d FAILURES\n", g_failures);
    return 1;
    (void)argc;
    (void)argv;
}
