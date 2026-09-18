#pragma once

// C++ port of paleo_workbench/workflow/freshness.py (CONV-26) — derived
// scientific freshness (Stage 9). Integrity (payload checksum) and freshness
// (up-to-date vs current project selection) are distinct dimensions;
// historical DataVersions are never mutated with a stale flag — status is
// always recomputed from catalog lineage + CurrentProjectVersionContext.
//
// Ported surface: FreshnessState / FreshnessReasonType / FreshnessReason /
// FreshnessReport / FreshnessService (evaluate_run with cycle-stack
// recursion, evaluate_version, evaluate_domain_task, downstream_impact,
// stale_downstream, evaluate_operation, step_freshness aggregation), the
// _LINEAGE_EXPECTED_OPS table, FRESHNESS_UI_LABELS and
// WORKFLOW_STATUS_FOR_FRESHNESS.
//
// Seams (documented): catalog resolution (resolve_version / verify_integrity
// / file existence) is a CatalogSeam callback bundle; Python's module-level
// DependencyGraph cache (_cached_graph_for) is host-side policy and stays
// with the caller. The graph topology comes from pwb::workflow_graph
// (CONV-25); the richer version records (checksum / trashed / path) live in
// the VersionLookup this service is constructed with.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_graph/graph.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/current_context.hpp>

#include <map>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;
using pwb::workflow_graph::DataRunRef;

enum class FreshnessState {
    Fresh,
    Stale,
    Unknown,
    Missing,
    Failed,
    Running,
};
const char* freshness_state_value(FreshnessState state);
std::optional<FreshnessState> freshness_state_from_value(
    const std::string& value);

enum class FreshnessReasonType {
    UpstreamVersionChanged,
    ParametersChanged,
    ModelVersionChanged,
    GeneratorChanged,
    MissingLineage,
    MissingPayload,
    IntegrityModified,
    RunFailed,
    RunRunning,
    GraphCycle,
    TransitiveUpstreamStale,
    Ok,
};
const char* freshness_reason_type_value(FreshnessReasonType type);

struct FreshnessReason {
    FreshnessReasonType type;
    std::optional<std::string> upstream_version_id;
    std::optional<std::string> current_version_id;
    std::string operation;
    std::string detail;
    std::optional<std::string> asset_id;

    Json to_dict() const;
};

struct FreshnessReport {
    FreshnessState state = FreshnessState::Unknown;
    std::string subject_kind;  // "run" | "version" | "domain_task"
    std::string subject_id;
    std::vector<FreshnessReason> reasons;
    std::string operation;
    std::optional<std::string> domain_task_id;
    std::vector<std::string> output_version_ids;
    std::vector<std::string> input_version_ids;
    std::optional<std::string> integrity;  // verified|modified|missing|unknown

    [[nodiscard]] bool is_fresh() const {
        return state == FreshnessState::Fresh;
    }
    [[nodiscard]] bool is_stale() const {
        return state == FreshnessState::Stale;
    }
    [[nodiscard]] const FreshnessReason* primary_reason() const {
        return reasons.empty() ? nullptr : &reasons.front();
    }

    Json to_dict() const;
};

// Chinese UI labels (dashboard) — FreshnessState value -> label.
extern const std::map<std::string, std::string> FRESHNESS_UI_LABELS;
// Workflow step status strings — FreshnessState -> step status.
extern const std::map<FreshnessState, std::string>
    WORKFLOW_STATUS_FOR_FRESHNESS;

class FreshnessService {
public:
    using VersionLookup = std::unordered_map<std::string, VersionRecord>;

    // graph: catalog lineage topology (CONV-25 DependencyGraph).
    // versions: extended version records keyed by version id (Python
    //   graph.versions carries the full catalog DataVersionRef).
    FreshnessService(const pwb::workflow_graph::DependencyGraph& graph,
                     const CurrentProjectVersionContext& context,
                     VersionLookup versions = {},
                     CatalogSeam seam = {},
                     bool check_integrity = false);

    void clear_cache();

    FreshnessReport evaluate_run(const std::string& run_id) const;
    FreshnessReport evaluate_version(const std::string& version_id) const;
    FreshnessReport evaluate_domain_task(
        const std::string& domain_task_id) const;

    std::vector<FreshnessReport> downstream_impact(
        const std::vector<std::string>& version_ids) const;
    std::vector<FreshnessReport> stale_downstream(
        const std::vector<std::string>& version_ids) const;
    std::vector<FreshnessReport> evaluate_operation(
        const std::string& operation) const;

    // Aggregate freshness for a workflow step type; nullopt when no catalog
    // runs exist for the step (caller keeps evidence-based semantics).
    std::optional<FreshnessState> step_freshness(
        const std::string& step_type) const;

    [[nodiscard]] const pwb::workflow_graph::DependencyGraph& graph() const {
        return graph_;
    }
    [[nodiscard]] const CurrentProjectVersionContext& context() const {
        return context_;
    }

    // (current_version_id, asset_id) when *input_version_id* is not current.
    std::optional<std::pair<std::string, std::optional<std::string>>>
    selection_mismatch(const std::string& input_version_id) const;

private:
    const pwb::workflow_graph::DependencyGraph& graph_;
    const CurrentProjectVersionContext& context_;
    VersionLookup versions_;
    CatalogSeam seam_;
    bool check_integrity_;

    mutable std::unordered_map<std::string, FreshnessReport> run_cache_;
    mutable std::unordered_map<std::string, FreshnessReport> version_cache_;
    // selected tips indexed by producing domain task / parent link
    // (freshness rules 3/4 O(1) lookups).
    struct SelectedKey {
        bool is_domain;  // true: ("domain", task) — false: ("parent", vid)
        std::string id;
        bool operator<(const SelectedKey& o) const {
            return is_domain != o.is_domain
                       ? is_domain < o.is_domain
                       : id < o.id;
        }
    };
    mutable std::map<SelectedKey, std::vector<std::string>> selected_by_key_;
    mutable bool selected_indexed_ = false;

    // Insertion-ordered snapshots of the graph's dict views.
    std::unordered_map<std::string, std::string> producing_run_index_;
    std::unordered_map<std::string, std::vector<std::string>> run_outputs_;

    void index_selected() const;
    [[nodiscard]] bool input_is_withdrawn(
        const std::string& input_version_id) const;
    [[nodiscard]] std::string checksum_for(
        const std::string& version_id) const;
    [[nodiscard]] bool content_identical(const std::string& a,
                                         const std::string& b) const;
    FreshnessReport evaluate_run_impl(const std::string& run_id,
                                      const std::set<std::string>* stack) const;
};

}  // namespace pwb::workflow_runtime
