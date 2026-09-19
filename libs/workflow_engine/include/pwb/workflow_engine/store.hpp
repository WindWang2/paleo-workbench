#pragma once
// CONV-32 — workflow run store + reproduction contract.
// Port of paleo_workbench/workflow/dag/store.py (atomic JSON checkpoints,
// in-memory cache index, lineage walk) and dag/reproduction.py
// (describe_reproduction). Uses the workflow_spec DTOs — NOT the legacy
// in-memory engine-local types (see run_engine.hpp for the store-driven
// engine). Qt-free, Python-free.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_spec/model.hpp>

#include <filesystem>
#include <functional>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace pwb::workflow_engine {

using domain::Json;

// load() failures — message text frozen against Python parity.
struct StoreError : std::runtime_error {
    using std::runtime_error::runtime_error;
};
// "no workflow run '<id>' in <root>"
struct RunNotFound : StoreError {
    RunNotFound(const std::string& run_id, const std::filesystem::path& root);
};
// "workflow run '<id>' checkpoint is corrupted: <parser detail>"
struct CorruptCheckpoint : StoreError {
    CorruptCheckpoint(const std::string& run_id, const std::string& parser_detail);
};

// Duck-typed catalog seam for find_reusable_node output verification.
struct VersionRefLike {
    bool trashed = false;
};
class CatalogLike {
public:
    virtual ~CatalogLike() = default;
    // throw / nullopt == unresolvable (Python: resolve_version raising or None)
    virtual std::optional<VersionRefLike> resolve_version(const std::string& id) = 0;
    // nullopt == catalog has no verify_integrity attribute (Python duck-typing)
    virtual std::optional<std::string> verify_integrity(const std::string& id) {
        return std::nullopt;
    }
};

class WorkflowRunStore {
public:
    using Clock = std::function<double()>;

    // mkdir -p semantics; clock defaults to wall time (epoch seconds).
    explicit WorkflowRunStore(std::filesystem::path root, Clock clock = nullptr);

    [[nodiscard]] const std::filesystem::path& root() const noexcept;

    // Stamps run.updated_at = clock() then atomically writes
    // root/run-<run_id>.json (tmp file + rename, indent=1, no trailing
    // newline, store_version first key). Indexes cache entries on success.
    std::filesystem::path save(workflow_spec::WorkflowRun& run);

    // RunNotFound / CorruptCheckpoint / model coercion errors.
    [[nodiscard]] workflow_spec::WorkflowRun load(const std::string& run_id) const;

    // Lexicographic by run id; dot-prefixed tmp files invisible.
    [[nodiscard]] std::vector<std::string> list_run_ids() const;
    // Unreadable runs skipped with a warning through the log sink.
    [[nodiscard]] std::vector<workflow_spec::WorkflowRun> list_runs() const;

    // Rebuilds the in-memory cache index from list_runs() ordered by
    // (updated_at or 0.0) ascending; returns total indexed entries.
    int rebuild_cache_index();
    // Lazily builds; returns (run_id, node_id) pairs NEWEST FIRST.
    [[nodiscard]] std::vector<std::pair<std::string, std::string>>
    candidates_for_identity(const std::string& cache_identity);

    void set_log_sink(std::function<void(const std::string&)> sink);

private:
    void cache_index_entry(const workflow_spec::WorkflowRun& run);

    std::filesystem::path root_;
    Clock clock_;
    std::function<void(const std::string&)> sink_;
    mutable std::mutex index_mutex_;
    bool index_built_ = false;
    std::unordered_map<std::string, std::vector<std::pair<std::string, std::string>>>
        cache_index_;
    std::unordered_set<std::string> indexed_pairs_;
};

// "<project minus .paleo.json>.artifacts/workflows"
[[nodiscard]] std::filesystem::path default_store_root(const std::string& project_path);
// temp_directory_path() / "paleo-workflow-runs"
[[nodiscard]] std::filesystem::path default_store_root();

// Newest-first candidate walk with full revalidation
// (state/receipt/from_cache/output resolvability). Never invents outputs.
[[nodiscard]] std::optional<workflow_spec::NodeRun> find_reusable_node(
    const WorkflowRunStore& store, const std::string& cache_identity,
    const CatalogLike* catalog = nullptr, bool verify_integrity = true);

// Walks parent_run_id links oldest-first; unreadable link stops the walk.
[[nodiscard]] std::vector<std::string> run_lineage(const WorkflowRunStore& store,
                                                   const std::string& run_id);

// dag/reproduction.py — pure projection of the run (spec node order).
[[nodiscard]] Json describe_reproduction(const workflow_spec::WorkflowRun& run);

}  // namespace pwb::workflow_engine
