#pragma once

// pwb::mapping — host-side duplicate-sample policy, a faithful C++ port of
// paleo_workbench/workflow/sample_normalization.py (M7). Frozen against
// tools/oracle/generate_sample_norm_fixtures.py.
//
// Policies: mean (default), first, error, keep. Coordinate identity is
// exact equality (no epsilon). Non-finite samples are dropped and counted.
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <string>
#include <utility>

namespace pwb::mapping {

using pwb::domain::Json;

inline constexpr const char* kDuplicatePolicies[] = {
    "mean", "first", "error", "keep",
};
inline constexpr const char* kDefaultDuplicatePolicy = "mean";

struct SampleNormalizationReport {
    std::string policy;
    int n_input = 0;
    int n_valid = 0;
    int n_nonfinite_dropped = 0;
    int n_duplicate_groups = 0;
    int n_duplicates_merged = 0;
    int n_qc_flagged = 0;
    bool duplicates_present() const { return n_duplicate_groups > 0; }
};

// points: JSON array of sample objects. Raises std::invalid_argument with
// the Python ValueError text for unknown policy or policy=error + dupes.
std::pair<Json, SampleNormalizationReport> normalize_factor_samples(
    const Json& points, const std::string& policy = kDefaultDuplicatePolicy);

// Honest fallback to default when params is null/empty/unknown.
std::string duplicate_policy_from_params(const Json& params);

}  // namespace pwb::mapping
