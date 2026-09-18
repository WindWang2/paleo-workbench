#pragma once

// C++ port of paleo_workbench/workflow/dependency_graph.py (CONV-25).
// Runtime DAG over catalog lineage (version --input--> run --output-->
// version): rebuild indexes, cycle detection, downstream traversals,
// provenance-reuse matching, topological ordering with synthetic task
// edges. Catalog access is the documented seam — callers pass listings.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::workflow_graph {

using pwb::domain::Json;

struct DependencyGraphError : std::runtime_error {
    using std::runtime_error::runtime_error;
    const char* python_class() const { return "DependencyGraphError"; }
};

// Lightweight reference mirrors (catalog.types) — restricted to the fields
// the graph and evidence surfaces actually read (D2).
struct DataVersionRef {
    std::string asset_id;
    std::string version_id;
    std::string name;
    std::optional<std::string> producing_run_id;
};

struct DataRunRef {
    std::string run_id;
    std::string operation;
    std::vector<std::string> input_version_ids;
    std::vector<std::string> output_version_ids;
    Json parameters = Json::object();
    std::optional<std::string> generator_version;
    std::string status = "running";
    std::optional<std::string> started_at;
    std::optional<std::string> finished_at;
    std::optional<std::string> domain_task_id;
    std::optional<std::string> input_snapshot_hash;
};

struct GraphEdge {
    std::string source_version_id;
    std::string run_id;
    std::string target_version_id;
    std::string operation;
};

class DependencyGraph {
public:
    // from_catalog seam: callers pass catalog.list_versions()/list_runs().
    static DependencyGraph from_listings(
        const std::vector<DataVersionRef>& versions,
        const std::vector<DataRunRef>& runs) {
        DependencyGraph g;
        g.rebuild(versions, runs);
        return g;
    }

    void rebuild(const std::vector<DataVersionRef>& versions,
                 const std::vector<DataRunRef>& runs);

    bool has_cycle() const { return !cycle_nodes.empty(); }
    const std::set<std::string>& cycles() const { return cycle_nodes; }

    // Read-only index views (frozen via freeze_graph in the oracle).
    const std::vector<DataVersionRef>& version_list() const { return versions_; }
    const std::vector<DataRunRef>& run_list() const { return runs_; }
    const DataRunRef* run(const std::string& run_id) const;
    const DataVersionRef* version(const std::string& version_id) const;

    // Ordered index views — key order = Python dict insertion order.
    const std::vector<std::pair<std::string, std::string>>& producing_run()
        const { return producing_run_; }
    const std::vector<std::pair<std::string, std::vector<std::string>>>&
    consumers() const { return consumers_; }
    const std::vector<std::pair<std::string, std::vector<std::string>>>&
    run_inputs() const { return run_inputs_; }
    const std::vector<std::pair<std::string, std::vector<std::string>>>&
    run_outputs() const { return run_outputs_; }
    const std::vector<std::pair<std::string, std::string>>& version_asset()
        const { return version_asset_; }
    const std::vector<std::pair<std::string, std::vector<std::string>>>&
    asset_versions() const { return asset_versions_; }
    const std::vector<std::pair<std::string, std::vector<std::string>>>&
    domain_task_runs() const { return domain_task_runs_; }
    const std::vector<GraphEdge>& edges() const { return edges_; }

    std::optional<std::string> asset_id_for(const std::string& version_id) const;
    std::vector<const DataRunRef*> direct_downstream_runs(
        const std::string& version_id) const;
    std::vector<const DataRunRef*> transitive_downstream_runs(
        const std::vector<std::string>& version_ids,
        std::size_t max_nodes = 100000) const;
    std::vector<std::string> transitive_downstream_versions(
        const std::vector<std::string>& version_ids) const;
    const DataRunRef* latest_run_for_domain_task(
        const std::string& domain_task_id) const;

    const DataRunRef* find_reuse_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const std::optional<std::string>& generator_version = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const Json& parameters = Json(nullptr),
        bool require_outputs = true) const;

    // task_consumers: consumer domain_task_id -> producer task ids (H11).
    std::vector<const DataRunRef*> topological_runs(
        const std::vector<std::string>& run_ids,
        const std::optional<std::map<std::string, std::set<std::string>>>&
            task_consumers = std::nullopt) const;

private:
    std::vector<DataVersionRef> versions_;
    std::vector<DataRunRef> runs_;
    std::unordered_map<std::string, std::size_t> version_index_;
    std::unordered_map<std::string, std::size_t> run_index_;

    // Insertion-ordered indexes (Python dict semantics).
    std::vector<std::pair<std::string, std::string>> producing_run_;
    std::unordered_map<std::string, std::size_t> producing_index_;
    std::vector<std::pair<std::string, std::vector<std::string>>> consumers_;
    std::unordered_map<std::string, std::size_t> consumers_index_;
    std::vector<std::pair<std::string, std::vector<std::string>>> run_inputs_;
    std::unordered_map<std::string, std::size_t> run_inputs_index_;
    std::vector<std::pair<std::string, std::vector<std::string>>> run_outputs_;
    std::unordered_map<std::string, std::size_t> run_outputs_index_;
    std::vector<std::pair<std::string, std::string>> version_asset_;
    std::unordered_map<std::string, std::size_t> version_asset_index_;
    std::vector<std::pair<std::string, std::vector<std::string>>> asset_versions_;
    std::unordered_map<std::string, std::size_t> asset_versions_index_;
    std::vector<std::pair<std::string, std::vector<std::string>>> domain_task_runs_;
    std::unordered_map<std::string, std::size_t> domain_task_index_;
    std::vector<GraphEdge> edges_;
    std::set<std::string> cycle_nodes;

    std::set<std::string> detect_cycle_nodes() const;
};

}  // namespace pwb::workflow_graph
