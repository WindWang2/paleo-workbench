// DTW well-log matcher kernel — faithful port of
// paleo_workbench/viz/dtw_log_matcher.py (CONV-09, plan M8 first slice).
// Qt-free, Python-free, numpy-free; frozen against the Python oracle
// (tools/oracle/generate_dtw_fixtures.py). Normalization replicates
// numpy's pairwise summation bit-exactly because the Python backtracker
// breaks DP ties with exact `==` comparisons — path identity (the
// acceptance contract) requires bit-identical cost matrices.
#pragma once

#include <cstdint>
#include <optional>
#include <vector>

namespace pwb::well_science {

// Python module constant _MAX_COST_CELLS: upper bound on cost-matrix cells
// before the curves are decimated (two 100k-sample LAS previews would
// otherwise need ~75 GiB).
inline constexpr std::int64_t kMaxCostCells = 1'000'000;

struct AlignmentResult {
    double cost = 0.0;  // +inf when the alignment failed (empty/window guard)
    std::vector<std::int64_t> path_ref;
    std::vector<std::int64_t> path_target;
};

// DTWLogMatcher._normalized: z-normalize, imputing NaN/±inf with the finite
// mean (0.0 when no finite sample); non-positive or non-finite std -> 1.0.
std::vector<double> normalized(const std::vector<double>& curve);

struct Downsampling {
    std::vector<double> values;
    std::vector<std::int64_t> indices;  // strictly increasing, original space
};

// DTWLogMatcher._min_max_downsample: each bin contributes its min and max
// samples ordered by original index (#1054 peak preservation). bin_size <= 1
// is the identity. argmin/argmax replicate numpy: first extremal index wins;
// a NaN chunk yields the first NaN index.
Downsampling min_max_downsample(const std::vector<double>& curve,
                                std::int64_t bin_size);

// DTWLogMatcher.match_curves: optimal non-linear DTW alignment. Returns
// cost=+inf with empty paths for empty inputs or when a Sakoe-Chiba band of
// `window` cannot reach the DP endpoint (#897 — never fabricate a path
// through inf cells).
AlignmentResult match_curves(const std::vector<double>& curve_ref,
                             const std::vector<double>& curve_target,
                             std::optional<std::int64_t> window = std::nullopt);

// DTWLogMatcher.transfer_top_index: nearest path_ref sample to *ref_top_idx*
// (ties keep the earliest) mapped to its path_target index; empty paths pass
// ref_top_idx through.
std::int64_t transfer_top_index(
    std::int64_t ref_top_idx,
    const std::vector<std::int64_t>& path_ref,
    const std::vector<std::int64_t>& path_target);

}  // namespace pwb::well_science
