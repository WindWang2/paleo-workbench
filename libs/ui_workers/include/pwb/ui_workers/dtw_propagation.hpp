#pragma once

// UI-04 — DtwPropagationWorker core.
// Port of paleo_workbench/ui/pages/dtw_propagation_worker.py +
// geoviz_cross_well CrossWellCanvas.compute_dtw_propagation.
//
// Signal/progress contract (Python parity):
//   run(): recommend_fn first (exception -> None, still emits
//          recommendation_ready) -> cancel check -> cancelled |
//          compute_dtw_propagation(ref, depth, band, progress_cb) ->
//          finished(pairs) | cancelled (progress cb raises JobCancelled on
//          flag) | failed("Class: msg"). progress emits (done, total) per
//          target well AFTER each well completes.
// The picks apply stays GUI-side; this core only computes pairs.

#include <any>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

inline constexpr long long kMaxDtwCells = 4'000'000;

// bounded_dtw_band — verbatim port. `band_radius` nullopt -> engine default
// max(20, n//4); the cap keeps n*(2*band+1) under the cell budget.
int bounded_dtw_band(int n_samples, std::optional<int> band_radius =
                                      std::nullopt);

// One well's curve as _extract_curve returns it (depths + values, or absent
// = un-extractable -> skipped with a progress tick like Python).
struct DtwWellSlice {
    std::string name;
    std::optional<std::vector<double>> depths;
    std::optional<std::vector<double>> values;
};

// The canvas surface compute_dtw_propagation reads: well order + curves.
struct DtwSceneSlice {
    std::vector<DtwWellSlice> wells;  // names == canvas._well_names order
};

// DTWEngine.correlate result slice.
struct DtwCorrelateResult {
    bool feasible = false;
    double suggested_depth = 0.0;
    double cost = 1.0;
    double confidence = 0.0;
};

// DTWEngine.correlate — verbatim port of the banded Sakoe-Chiba kernel
// (geoviz_cross_well/dtw_engine.py). Compact cost matrix, min-plus prefix
// row recurrence, endpoint backtrace, median-target depth pick, and the
// same infeasibility guards (short/non-finite curves, depth-length
// mismatch, |m-n| > band). ref_depth NaN -> Python's ref_depth=None
// mid-index fallback.
DtwCorrelateResult dtw_engine_correlate(
    const std::vector<double>& ref_values,
    const std::vector<double>& ref_depths,
    const std::vector<double>& tgt_values,
    const std::vector<double>& tgt_depths, int band_radius,
    double ref_depth);

// The banded-DTW seam (default: dtw_engine_correlate — deliberately not
// bound to pwb::well_science::match_curves which is a different
// algorithm).
using DtwCorrelateFn = std::function<DtwCorrelateResult(
    const std::vector<double>& ref_values,
    const std::vector<double>& ref_depths,
    const std::vector<double>& tgt_values,
    const std::vector<double>& tgt_depths, int band_radius,
    double ref_depth)>;

// compute_dtw_propagation — pure orchestration port: ref lookup -> per
// non-ref target: curve extract skip OR correlate feasible -> (name,
// depth) pair; progress_callback(step, total) after EVERY target.
std::vector<std::pair<std::string, double>> compute_dtw_propagation(
    const DtwSceneSlice& scene, const std::string& ref_well, double ref_depth,
    int band_radius, const DtwCorrelateFn& correlate_fn,
    const std::function<void(int, int)>& progress_callback);

// The propagation compute seam — default: compute_dtw_propagation on the
// scene slice. Tests may inject a fake (Python _FakeCanvas parity).
using DtwComputeFn = std::function<std::vector<std::pair<std::string, double>>(
    const std::string& ref_well, double ref_depth, int band_radius,
    const std::function<void(int, int)>& progress_callback)>;

struct DtwPropagationInput {
    DtwSceneSlice scene;
    std::string ref_well;
    double ref_depth = 0.0;
    std::string formation;    // carried for parity; not read by the worker
    int n_samples = 0;
    std::optional<int> band_radius;
    // recommend_fn — runs FIRST on the worker thread; exception -> nullopt.
    std::function<std::any()> recommend_fn;
    // correlate_fn feeds the default compute; compute_fn replaces it whole.
    DtwCorrelateFn correlate_fn;
    DtwComputeFn compute_fn;
    // Typed progress + recommendation hooks (the Python signals).
    std::function<void(int, int)> on_progress;
    std::function<void(const std::any&)> on_recommendation;
};

// The finished payload — list[(well_name, depth)].
struct DtwPropagationResult {
    std::vector<std::pair<std::string, double>> pairs;
};

// Worker-body parity: recommendation first (failure -> nullopt, still
// emitted when recommend_fn was given), then cancel check, then compute
// with a cancelling progress callback (JobCancelled on flag).
DtwPropagationResult run_dtw_propagation(const DtwPropagationInput& input,
                                         job::JobContext& ctx);

// JobSpec builder — kind "compute.dtw_propagation". on_done receives
// DtwPropagationResult.
job::JobSpec make_dtw_propagation_job_spec(
    DtwPropagationInput input,
    std::function<void(const DtwPropagationResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_workers
