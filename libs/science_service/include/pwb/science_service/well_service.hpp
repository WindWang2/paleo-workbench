#pragma once

// pwb::science_service — well science services (CONV-28): typed request/
// result envelopes over the frozen well_science kernels.
//
//   well.curve_operation — the frozen interpretation toolbox
//     (pwb::well_science curve_ops.hpp, CONV-11) dispatched by name with
//     required-parameter validation from the same kernel registry table.
//     9 of the 11 registered operations are dispatched (depth_unit_normalize
//     and derive_curve are registered in the table but not dispatched yet —
//     they refuse with a stable error instead of half-running).
//   well.log_match — the DTW correlation kernel (dtw.hpp, CONV-09) with the
//     production decimation policy: curves whose cost matrix would exceed
//     max_dtw_cost_cells are min-max downsampled first (exactly the
//     DTWLogMatcher behaviour), recorded honestly in the envelope.
//
// NaN discipline, duplicate/unsorted depth handling and unit whitelists are
// the kernels' frozen contracts — this layer never relaxes them.

#include <pwb/science/algorithm.hpp>
#include <pwb/science/outcome.hpp>

#include <stop_token>
#include <pwb/well_science/dtw.hpp>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "envelope.hpp"
#include "limits.hpp"

namespace pwb::science_service {

// ---------------------------------------------------------------------------
// Curve operations
// ---------------------------------------------------------------------------

struct CurveOperationRequest {
    // One of the dispatched pwb::well_science::curve_operations() names:
    // smooth | median_filter | normalize | clip_outliers | unit_conversion |
    // resample | depth_shift | despike | baseline_shift
    std::string operation;
    pwb::domain::Json params = pwb::domain::Json::object();
    std::vector<double> depth;   // required for depth-scoped operations
    std::vector<double> values;  // the curve operand
    std::optional<std::string> axis_unit;  // m | ft | (nullopt = unknown)
    std::optional<std::string> from_unit;  // convert_units only
    std::optional<std::string> to_unit;    // convert_units only
};

struct CurveOperationResult {
    ScienceEnvelope envelope;
    std::vector<double> depth;   // new axis when the operation moves it
    std::vector<double> values;  // transformed curve (NaN preserved)
};

class CurveOperationService {
public:
    explicit CurveOperationService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<CurveOperationResult> run(
        const CurveOperationRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// ---------------------------------------------------------------------------
// DTW log matching / correlation
// ---------------------------------------------------------------------------

struct LogMatchRequest {
    std::vector<double> reference;
    std::vector<double> target;
    // Sakoe-Chiba band; nullopt = full matrix (subject to cost-cell limit).
    std::optional<std::int64_t> window;
};

struct LogMatchResult {
    ScienceEnvelope envelope;
    double cost = 0.0;                 // +inf when no alignment exists
    std::vector<std::int64_t> path_reference;
    std::vector<std::int64_t> path_target;
    bool decimated = false;            // curves were min-max downsampled
    std::int64_t bin_size = 1;
};

class LogMatchService {
public:
    explicit LogMatchService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<LogMatchResult> run(
        const LogMatchRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

    // transfer_top_index passthrough (kernel): nearest path_reference sample
    // to ref_top_idx mapped into target index space. ref_top_idx passes
    // through when paths are empty.
    static std::int64_t transfer_top(const LogMatchResult& result,
                                     std::int64_t ref_top_idx);

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

}  // namespace pwb::science_service
