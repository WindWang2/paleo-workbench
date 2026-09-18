#pragma once

// C++ port of paleo_workbench/workflow/interpretation/staleness.py (CONV-26)
// — the unified staleness vocabulary (V9 ADR-9): the convergence-layer
// verdict CURRENT | STALE_CONTENT | STALE_VERSION | MISSING_INPUT |
// SUPERSEDED | UNKNOWN plus the explicit adapters from the three legacy
// engines (constraint pin states, workspace FreshnessStatus, run freshness).
// No evidence → UNKNOWN, never CURRENT.
//
// NOT ported (documented seam): evaluate_verdict / workspace_verdicts /
// propagate_to_products delegate to mapping_workspace.MappingDependencyService
// (UI workspace domain — separate branch); the vocabulary and adapters here
// are the native consumption surface for those callers.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/freshness.hpp>

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

enum class StalenessVerdict {
    Current,
    StaleContent,
    StaleVersion,
    MissingInput,
    Superseded,
    Unknown,
};
const char* staleness_verdict_value(StalenessVerdict verdict);
std::optional<StalenessVerdict> staleness_verdict_from_value(
    const std::string& value);

// verdict -> is this a problem state (Inspector / publish gate consume).
bool verdict_is_problem(StalenessVerdict verdict);
// verdict -> Chinese label.
std::string verdict_label_zh(StalenessVerdict verdict);

// ---- adapters: legacy vocabularies -> unified verdict ----

// constraint_versions pin state (current/unpinned/unknown/missing/
// stale_version/stale_content/uncommitted) -> verdict.
StalenessVerdict from_constraint_pin(const std::string& state);

// mapping_workspace FreshnessStatus (current/stale/missing_input/
// superseded/unknown) -> verdict.
StalenessVerdict from_workspace_status(const std::string& status);

// workflow FreshnessState value -> verdict (failed/running → UNKNOWN: a
// failed run cannot adjudicate its product's freshness).
StalenessVerdict from_run_freshness(const std::string& state_value);
StalenessVerdict from_run_freshness(FreshnessState state);

// One stage artifact's unified verdict with evidence detail.
struct ArtifactVerdict {
    std::string artifact_key;
    StalenessVerdict verdict = StalenessVerdict::Unknown;
    std::string detail;
    std::vector<std::string> upstream_culprits;

    [[nodiscard]] std::string label() const {
        return verdict_label_zh(verdict);
    }
    [[nodiscard]] bool is_problem() const {
        return verdict_is_problem(verdict);
    }

    Json to_dict() const;
};

}  // namespace pwb::workflow_runtime
