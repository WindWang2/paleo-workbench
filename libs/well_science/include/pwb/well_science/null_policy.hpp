// Null policy (declared vs inferred vs derived-injected) — V6 §4.
// Ported from paleo_workbench/workflow/well_science.py.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace pwb::well_science {

// Whitelist of legacy missing-value sentinels that may be *inferred* when a
// source declares none (ResForm-compatible v1). Inference must always be
// reported as a diagnostic — a hypothesis, not a declaration.
inline constexpr std::array<double, 4> INFERRED_NULL_SENTINELS{
    -999.25, -999.0, -9999.0, -99999.0};

// Default sentinel a DERIVED LAS writer introduces when the source declared
// none (LAS text cannot carry NaN).
inline constexpr double DERIVED_NULL_SENTINEL = -999.25;

// Tolerance for matching a declared sentinel in float data.
inline constexpr double NULL_MATCH_ABS_TOL = 1e-6;

// How missing samples are represented for one dataset.
// source ∈ "declared" | "inferred" | "derived_injected" | "none".
struct NullPolicy {
    std::string source;
    std::optional<double> sentinel{};
    std::vector<double> inferred_sentinels{};

    bool declared() const { return source == "declared"; }

    // Boolean mask of samples equal to the active sentinel(s):
    // |v - s| <= NULL_MATCH_ABS_TOL (numpy isclose rtol=0); NaN never matches;
    // equal non-finite values match each other.
    std::vector<unsigned char> matches(const std::vector<double>& values) const;
};

// Policy for a source that (may have) declared a LAS NULL value. Raw text is
// parsed as float; None/empty/parse-failure → the "none" policy (never a guess).
NullPolicy null_policy_from_declared(std::optional<std::string> declared_sentinel);

}  // namespace pwb::well_science
