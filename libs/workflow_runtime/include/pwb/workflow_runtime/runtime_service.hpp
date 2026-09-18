#pragma once

// WorkflowRuntimeService (CONV-26) — the stable native API composing the
// workflow pure cores into one runtime closure. A C++ application consumes
// this service instead of assembling graphs itself:
//
//   WorkflowSpec -> validate -> (provenance-aware) execute -> publish
//   -> stale/recompute plan -> execute plan via node adapters -> cancel
//   -> inspect / explain stale / list outputs / provenance trace.
//
// Provenance consistency (F): every executed node publishes a DataRun +
// DataVersion pair into the CatalogRepository; freshness, recompute plans,
// provenance traces and downstream state are all derived from that ONE
// store — workflow, catalog and UI cannot hold divergent copies.
//
// Resume/retry seam: successful steps stay done (their runs are completed
// and reuse-matched on the next plan); re-planning after a partial failure
// yields REUSE_EXISTING for finished work and REQUIRES_COMPUTE for the
// rest — that is the resume path. cancel() is cooperative through the
// workflow_engine CancelToken shared by node bodies and admission.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/engine.hpp>
#include <pwb/workflow_graph/graph.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/current_context.hpp>
#include <pwb/workflow_runtime/freshness.hpp>
#include <pwb/workflow_runtime/node_adapters.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;
using pwb::workflow_engine::CancelToken;
using pwb::workflow_engine::WorkflowRun;
using pwb::workflow_engine::WorkflowSpec;
using pwb::workflow_graph::DependencyGraph;

class WorkflowRuntimeService {
public:
    struct Config {
        // Runtime resource model: at most this many node bodies execute
        // concurrently (admission bound; 1 == deterministic serial).
        unsigned max_concurrency = 1;
        // Asset type stamped on workflow output versions.
        std::string output_asset_type = "workflow_output";
    };

    WorkflowRuntimeService(CatalogRepository& repository,
                           NodeAdapterRegistry& adapters, Config config = {});

    // ---- workflow spec lifecycle ----
    // Fail-closed static validation (unknown op / graph problems). Empty
    // return == valid.
    [[nodiscard]] std::vector<std::string> validate(
        const WorkflowSpec& spec) const;

    struct ExecuteOptions {
        // Namespace for published assets ("workflow_id:node_id").
        std::string workflow_name = "workflow";
        // Fixed clock stamp for published records ("" == service default).
        std::optional<std::string> started_at;
        // Progress callback (node_id, state).
        std::function<void(const std::string&, const std::string&)>
            on_progress;
    };

    // Execute a spec through the adapter registry on the calling thread,
    // publishing provenance per node: run opens "running", success appends
    // an output version + asset current pointer + run "complete"; failure
    // or cancel lands the run "failed"/"cancelled". Returns the engine's
    // WorkflowRun.
    WorkflowRun execute(const WorkflowSpec& spec, const CancelToken& token,
                        const ExecuteOptions& options = {});

    // ---- lineage lifecycle (single source of truth: the repository) ----
    // Rebuild the catalog lineage graph + version records from the store.
    struct GraphSnapshot {
        DependencyGraph graph;
        FreshnessService::VersionLookup versions;
        std::vector<RunRecord> runs;
    };
    [[nodiscard]] GraphSnapshot snapshot() const;

    // Deterministic current-version context from the repository's asset
    // current pointers (catalog authority; the project overlay is applied
    // by the caller through CurrentProjectVersionContext::select).
    [[nodiscard]] CurrentProjectVersionContext build_context() const;

    // Freshness session over the latest snapshot + context. Owns the
    // snapshot (heap-stable) so the service's references stay valid for as
    // long as the session lives.
    struct FreshnessSession {
        std::shared_ptr<GraphSnapshot> snapshot;
        std::unique_ptr<FreshnessService> service;
    };
    [[nodiscard]] FreshnessSession make_freshness_session(
        const CurrentProjectVersionContext& context,
        bool check_integrity = false) const;

    // ---- recompute lifecycle ----
    [[nodiscard]] RecomputePlan plan(
        const CurrentProjectVersionContext& context,
        const RecomputePlanOptions& options = {}) const;

    // Execute a plan: steps map to node adapters by operation; reuse steps
    // complete immediately; compute steps run the adapter with admission +
    // cancel and publish provenance. Missing adapters mark the step failed
    // (no invented compute) and poison downstream.
    PlanExecutionResult execute_plan(RecomputePlan& plan,
                                     const CurrentProjectVersionContext& context,
                                     const CancelToken& token,
                                     std::optional<int> generation = std::nullopt);

    // ---- inspection ----
    // Freshness explanation for one subject (run_id / version_id /
    // domain_task_id disambiguated by kind).
    [[nodiscard]] FreshnessReport explain_stale(
        const CurrentProjectVersionContext& context,
        const std::string& subject_kind, const std::string& subject_id,
        bool check_integrity = false) const;

    // Outputs of one run: version ids + their freshness state.
    [[nodiscard]] Json list_outputs(const std::string& run_id,
                                    const CurrentProjectVersionContext& context,
                                    bool check_integrity = false) const;

    // Provenance trace of a version: producing run, inputs (recursively,
    // bounded), downstream runs, evidence selector string.
    [[nodiscard]] Json provenance_trace(
        const std::string& version_id,
        const CurrentProjectVersionContext& context,
        std::size_t max_nodes = 100000) const;

    [[nodiscard]] const Config& config() const { return config_; }
    [[nodiscard]] AdmissionGate& admission() { return admission_; }

private:
    CatalogRepository& repository_;
    NodeAdapterRegistry& adapters_;
    Config config_;
    mutable AdmissionGate admission_;
};

}  // namespace pwb::workflow_runtime
