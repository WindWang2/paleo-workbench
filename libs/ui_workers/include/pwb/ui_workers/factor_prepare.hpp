#pragma once

// UI-04 — FactorPrepareWorker core.
// Port of paleo_workbench/ui/pages/factor_prepare_worker.py +
// workflow/factor_prepare_scheduler.py.
//
// Signal/progress contract (Python parity):
//   run(): token check -> run_factor_prepare_schedule(snapshot, token,
//          progress) -> progress(FactorPrepareProgress) per _emit ->
//          token check -> result.cancelled -> cancelled, else
//          completed(result) + finished(result.count) |
//          failed("Class: msg").
// The scheduler never mutates the live project — results are staged DTOs;
// commit_prepare_batch_result stays host-side.

#include <any>
#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// ---------------------------------------------------------------------------
// DTOs — field-exact ports of the scheduler dataclasses.
// ---------------------------------------------------------------------------

struct FactorPrepareProgress {
    int generation = 0;
    int total_tasks = 0;
    int clean = 0;
    int dirty = 0;
    int completed = 0;
    int failed = 0;
    int cancelled = 0;
    std::string phase;
    std::optional<std::string> current_task_id;
    std::optional<std::string> current_group;
    std::string message;
};

struct FactorPrepareTaskResult {
    std::string task_id;
    std::string dirty_state;
    bool reused = false;
    std::optional<FactorTaskSlice> task;  // None for failed/cancelled rows
    std::optional<std::string> scheduled_result_fingerprint;
    std::optional<std::string> error;
    double elapsed_ms = 0.0;
    // The grid this run computed (#834 contract): only successful runs own
    // one — failed runs carry none so the commit invalidation can't evict
    // a still-valid previous payload. Type-erased (host's grid type).
    std::any grid;
};

struct FactorPrepareBatchResult {
    int generation = 0;
    std::string method;
    std::vector<FactorPrepareTaskResult> task_results;
    int clean_count = 0;
    int dirty_count = 0;
    int executed_count = 0;
    int failed_count = 0;
    bool cancelled = false;
    int cancelled_count = 0;
    double snapshot_ms = 0.0;
    double classify_ms = 0.0;
    double execute_ms = 0.0;
    int workers = 1;
    bool created_default_tasks = false;
    std::optional<int> grid_n;
    double power = 2.0;

    // count: tasks considered by this prepare request.
    [[nodiscard]] int count() const {
        return static_cast<int>(task_results.size());
    }
};

// FactorDirtyState (interpolation_fingerprint.py) — string-valued enum.
// All seven Python members: classify_factor_recompute may return
// MISSING_OUTPUT (no committed grid) or UNKNOWN (unclassifiable drift);
// both are non-CLEAN so they land on the dirty side like Python.
enum class FactorDirtyState : std::uint8_t {
    clean,
    dirty_values,
    dirty_geometry,
    dirty_algorithm,
    dirty_constraints,
    missing_output,
    unknown,
};

[[nodiscard]] const char* to_string(FactorDirtyState state) noexcept;
[[nodiscard]] std::optional<FactorDirtyState>
factor_dirty_state_from_string(const std::string& value);

// ---------------------------------------------------------------------------
// Snapshot — the narrow scientific input (never the live project).
// ---------------------------------------------------------------------------

// Coordinate/stratigraphy/constraint slices stay type-erased: only the
// seam layer (fingerprints/batch/group keys) reads inside them, and it owns
// the concrete types. `model_copy(deep=True)` maps to plain copies.
struct FactorPrepareSnapshot {
    int generation = 0;
    std::string method = "IDW";
    int grid_n = 50;
    double power = 2.0;
    bool force = false;
    int seed = 0;
    std::string target_horizon;
    std::optional<std::string> project_crs;
    std::any coordinate;
    std::any stratigraphy;
    std::vector<std::any> constraint_layers;
    std::vector<FactorTaskSlice> tasks;
    bool created_defaults = false;
    double build_ms = 0.0;
};

// ---------------------------------------------------------------------------
// Seams — every kernel the scheduler delegates to (gap ledger G5).
// ---------------------------------------------------------------------------

// Shared fingerprint memo (Python dict shared across classify + batch and
// across parallel groups). Seams lock `mutex` around `entries` — Python's
// dict access was GIL-atomic; C++ needs the explicit guard.
struct FingerprintMemo {
    std::map<std::string, std::any> entries;
    mutable std::mutex mutex;
};

// Execution context the seams see (the throwaway exec project's fields).
// project_crs mirrors project.coordinate.project_crs — fingerprints_for_task
// folds it into the result fingerprint, and the snapshot resolved it once.
struct PrepareExecContext {
    const std::any& coordinate;
    const std::any& stratigraphy;
    const std::vector<std::any>& constraint_layers;
    const std::optional<std::string>& project_crs;
    std::string method;
    int grid_n = 0;
    double power = 2.0;
    int seed = 0;
    std::string target_horizon;
};

struct FactorPrepareSeams {
    // fingerprints_for_task + classify_factor_recompute fused: returns the
    // dirty state + the scheduled result fingerprint.
    std::function<std::pair<FactorDirtyState, std::string>(
        const FactorTaskSlice& task, const PrepareExecContext& ctx,
        bool force, FingerprintMemo* memo)>
        classify_fn;

    // batch_prepare_factor_maps — mutates `tasks` in place (status /
    // parameters / last_error), honoring cancellation internally.
    struct BatchArgs {
        std::vector<FactorTaskSlice>& tasks;
        const PrepareExecContext& ctx;
        bool force;
        FingerprintMemo* memo;
    };
    std::function<void(BatchArgs&, const job::CancellationToken&)> batch_fn;

    // _task_plan_group_key — geometry group key for the parallel path.
    // Python returns str | None: nullopt == the None key (all None-keyed
    // tasks share one group; progress emits group="None" like str(None)).
    std::function<std::optional<std::string>(const FactorTaskSlice& task,
                                             const PrepareExecContext& ctx)>
        group_key_fn;

    // geoviz synthetic_sample_points(seed, factor_type) -> parameters
    // payload. Default: the real C++ port (synthetic_sample_points).
    std::function<std::any(int seed, const std::string& factor_type)>
        synthetic_points_fn;

    // stratigraphy.model_copy(update={"target_horizon": horizon}) for the
    // created-defaults path — the slice's stratigraphy is opaque, so the
    // update is a seam (default: pass through unchanged).
    std::function<std::any(const std::any& stratigraphy,
                           const std::string& horizon)>
        stratigraphy_with_horizon_fn;

    // peek_live_factor_grid(task_id) -> carried grid payload (or empty).
    std::function<std::any(const std::string& task_id)> grid_peek_fn;

    // governance.clamp_workers("background.compute", n) — default: identity.
    std::function<int(int)> governor_clamp_fn;

    // time.perf_counter seconds — default: steady clock; the oracle pins it.
    std::function<double()> clock_fn;
};

// ---------------------------------------------------------------------------
// Scheduler port.
// ---------------------------------------------------------------------------

// prepare_worker_count — PALEO_PREPARE_WORKERS env (int, clamp 1..4) then
// the governor clamp seam.
int prepare_worker_count(const FactorPrepareSeams& seams);

// build_prepare_snapshot — clone scientific fields only; synthesize default
// tasks via the synthetic-points seam when the task list is empty.
struct PrepareProjectSlice {
    std::vector<FactorTaskSlice> factor_map_tasks;
    std::vector<std::any> constraint_layers;
    std::any coordinate;        // slice must carry .project_crs for project_crs
    std::any stratigraphy;
    std::string stratigraphy_target_horizon;  // getattr(stratigraphy,...)
    std::optional<std::string> project_crs;
};

inline const std::vector<std::string> kDefaultFactorTypes = {
    "地层厚度", "砂岩含量", "砂地比", "泥岩含量"};
inline constexpr int kDefaultGridN = 50;
inline constexpr const char* kFactorInterpGeneratorVersion =
    "factor-interp-v1";

FactorPrepareSnapshot build_prepare_snapshot(
    const PrepareProjectSlice& project, int generation,
    const std::string& method, std::optional<int> grid_n, double power,
    bool force, int seed = 0,
    const std::optional<std::string>& target_horizon = std::nullopt,
    const std::optional<std::vector<std::string>>& factor_types =
        std::nullopt,
    const FactorPrepareSeams& seams = {});

// run_factor_prepare_schedule — the full orchestration port: classify ->
// clean results -> serial or geometry-group-parallel execution (std::async
// + completion queue == ThreadPoolExecutor/as_completed) -> staged results.
FactorPrepareBatchResult run_factor_prepare_schedule(
    const FactorPrepareSnapshot& snapshot, const job::CancellationToken& token,
    const std::function<void(const FactorPrepareProgress&)>& progress,
    const FactorPrepareSeams& seams, int workers = 0);

// ---------------------------------------------------------------------------
// Worker input/output + job spec.
// ---------------------------------------------------------------------------

struct FactorPrepareInput {
    // Preferred: a pre-built snapshot (host thread). When absent the worker
    // builds one from `slice` exactly like FactorPrepareWorker.__init__.
    std::optional<FactorPrepareSnapshot> snapshot;
    PrepareProjectSlice slice;
    int generation = 0;
    std::string method = "IDW";
    std::optional<int> grid_n;
    double power = 2.0;
    bool force = false;
    int seed = 0;
    std::optional<std::string> target_horizon;
    int workers = 0;  // 0 -> prepare_worker_count()
    FactorPrepareSeams seams;
    // Typed progress hook (the Python `progress` signal).
    std::function<void(const FactorPrepareProgress&)> on_progress;
};

// Worker-body parity: token check -> schedule -> token check ->
// result.cancelled short-circuit -> result.
FactorPrepareBatchResult run_factor_prepare(const FactorPrepareInput& input,
                                            job::JobContext& ctx);

// JobSpec builder — kind "compute.factor_prepare". on_done receives the
// FactorPrepareBatchResult (a cancelled run lands cancelled with the
// partial result recorded, matching Python's finished(report) parity —
// see decisions D6: the scheduler publishes the result then on_cancel
// fires, and try_result() exposes the staged report).
job::JobSpec make_factor_prepare_job_spec(
    FactorPrepareInput input,
    std::function<void(const FactorPrepareBatchResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

// geoviz synthetic_sample_points(seed, factor_type, count=8) — the real
// C++ port (Python random.Random + sha256 base), used as the default
// synthetic_points_fn. Returns list[dict] semantics as
// vector<map<string,any>> with keys well/x/y/value.
std::vector<std::map<std::string, std::any>> synthetic_sample_points(
    int seed, const std::string& factor_type, int count = 8);

}  // namespace pwb::ui_workers
