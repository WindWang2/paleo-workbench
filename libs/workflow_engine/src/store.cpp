// CONV-32: store.cpp — faithful port of paleo_workbench/workflow/dag/store.py.
// Atomic JSON checkpoints (store_version envelope, indent=1, no trailing
// newline), the in-memory cache index (rebuilt oldest-to-newest, read
// newest-first, maintained incrementally on save), find_reusable_node and
// the lineage walk. Semantics frozen against
// tools/oracle/generate_workflow_store_fixtures.py.
#include <pwb/workflow_engine/store.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <fstream>
#include <sstream>
#include <system_error>
#include <utility>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace pwb::workflow_engine {

namespace {

double wall_clock_seconds() {
    return std::chrono::duration<double>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

long long current_pid() {
#if defined(_WIN32)
    return _getpid();
#else
    return ::getpid();
#endif
}

unsigned long next_tmp_counter() {
    static std::atomic<unsigned long> counter{0};
    return counter.fetch_add(1);
}

// Python repr() of a short run id: single quotes, switching to double
// quotes only when the text holds ' but no " (mirrors CPython repr).
std::string python_repr_string(const std::string& text) {
    const bool has_single = text.find('\'') != std::string::npos;
    const bool has_double = text.find('"') != std::string::npos;
    const char quote = (has_single && !has_double) ? '"' : '\'';
    std::string out(1, quote);
    for (const char ch : text) {
        if (ch == '\\') {
            out += "\\\\";
        } else if (ch == '\n') {
            out += "\\n";
        } else if (ch == '\r') {
            out += "\\r";
        } else if (ch == '\t') {
            out += "\\t";
        } else if (ch == quote) {
            out += '\\';
            out += ch;
        } else {
            out += ch;
        }
    }
    out += quote;
    return out;
}

// getattr(run, "updated_at", None) or 0.0 — null/absent reads as 0.0
// (Python's `or` also maps a falsy 0.0 to 0.0, same value either way).
double updated_or_zero(const workflow_spec::WorkflowRun& run) {
    return run.updated_at.is_number() ? run.updated_at.get<double>() : 0.0;
}

// Sink bookkeeping for the FREE functions (find_reusable_node /
// run_lineage): store.hpp keeps sink_ private with no friend declaration,
// so set_log_sink mirrors the sink into an address-keyed registry the free
// functions can reach. The constructor erases any stale entry left by a
// destroyed store that happened to land on the same address, so a fresh
// store never inherits a dangling sink.
struct SinkRegistry {
    std::mutex mutex;
    std::unordered_map<const WorkflowRunStore*,
                       std::function<void(const std::string&)>>
        sinks;
};

SinkRegistry& sink_registry() {
    static SinkRegistry registry;
    return registry;
}

void log_for_store(const WorkflowRunStore* store, const std::string& message) {
    std::function<void(const std::string&)> sink;
    {
        SinkRegistry& registry = sink_registry();
        std::lock_guard<std::mutex> lock(registry.mutex);
        const auto it = registry.sinks.find(store);
        if (it == registry.sinks.end()) return;
        sink = it->second;
    }
    if (sink) sink(message);
}

void remember_sink(const WorkflowRunStore* store,
                   std::function<void(const std::string&)> sink) {
    SinkRegistry& registry = sink_registry();
    std::lock_guard<std::mutex> lock(registry.mutex);
    if (sink) {
        registry.sinks[store] = std::move(sink);
    } else {
        registry.sinks.erase(store);
    }
}

void forget_sink(const WorkflowRunStore* store) {
    SinkRegistry& registry = sink_registry();
    std::lock_guard<std::mutex> lock(registry.mutex);
    registry.sinks.erase(store);
}

std::string ascii_upper(std::string text) {
    for (char& ch : text) {
        if (ch >= 'a' && ch <= 'z') ch = static_cast<char>(ch - 'a' + 'A');
    }
    return text;
}

// store._outputs_resolvable: every recorded output version must resolve,
// not be trashed, and (when the catalog verifies integrity) be VERIFIED.
// NOTE: store.hpp declares the CatalogLike seam methods NON-const (Python
// duck-typing has no constness) while find_reusable_node receives a const
// pointer — the lookup path is logically non-mutating, so the seam is
// invoked through a const_cast.
bool outputs_resolvable(CatalogLike& catalog,
                        const std::vector<std::string>& version_ids,
                        bool verify_integrity) {
    for (const std::string& id : version_ids) {
        std::optional<VersionRefLike> ref;
        try {
            ref = catalog.resolve_version(id);
        } catch (...) {
            return false;
        }
        if (!ref.has_value()) return false;
        if (ref->trashed) return false;
        if (verify_integrity) {
            // nullopt == the catalog has no verify_integrity attribute.
            std::optional<std::string> status;
            try {
                status = catalog.verify_integrity(id);
            } catch (...) {
                return false;
            }
            if (status.has_value() && ascii_upper(*status) != "VERIFIED") {
                return false;
            }
        }
    }
    return true;
}

}  // namespace

// --------------------------------------------------------- error types --

RunNotFound::RunNotFound(const std::string& run_id,
                         const std::filesystem::path& root)
    : StoreError("no workflow run " + python_repr_string(run_id) + " in " +
                 root.string()) {}

CorruptCheckpoint::CorruptCheckpoint(const std::string& run_id,
                                     const std::string& parser_detail)
    : StoreError("workflow run " + python_repr_string(run_id) +
                 " checkpoint is corrupted: " + parser_detail) {}

// --------------------------------------------------------------- store --

WorkflowRunStore::WorkflowRunStore(std::filesystem::path root, Clock clock)
    : root_(std::move(root)), clock_(std::move(clock)) {
    std::error_code ec;
    std::filesystem::create_directories(root_, ec);  // mkdir -p
    forget_sink(this);
}

const std::filesystem::path& WorkflowRunStore::root() const noexcept {
    return root_;
}

std::filesystem::path WorkflowRunStore::save(workflow_spec::WorkflowRun& run) {
    run.updated_at = domain::Json(clock_ ? clock_() : wall_clock_seconds());
    // store._path: NO sanitization of run_id (parity-first; run ids are
    // engine-generated hex, so traversal is out of scope by design).
    const std::filesystem::path path = root_ / ("run-" + run.run_id + ".json");
    const domain::Json document = run.to_dict();  // stamped after update
    domain::Json payload = domain::Json::object();
    payload["store_version"] = 1;  // {"store_version": 1, **run.to_dict()}
    for (const auto& [key, value] : document.items()) {
        payload[key] = value;
    }
    // tempfile.mkstemp(dir=root, prefix=".tmp-run-", suffix=".json")
    // stand-in: pid + process-local counter keeps concurrent writers apart.
    const std::filesystem::path tmp =
        root_ / (".tmp-run-" + std::to_string(current_pid()) + "-" +
                 std::to_string(next_tmp_counter()) + ".json");
    try {
        {
            std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
            if (!out) {
                throw StoreError("cannot open " + tmp.string() + " for writing");
            }
            // json.dump(..., ensure_ascii=False, indent=1) — no newline.
            out << payload.dump(1, ' ', false);
            out.flush();
            if (!out) {
                throw StoreError("cannot write " + tmp.string());
            }
        }
        // os.replace: POSIX rename over an existing checkpoint is atomic.
        std::filesystem::rename(tmp, path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp, ec);  // best-effort unlink, then rethrow
        throw;
    }
    cache_index_entry(run);
    return path;
}

workflow_spec::WorkflowRun WorkflowRunStore::load(const std::string& run_id) const {
    const std::filesystem::path path = root_ / ("run-" + run_id + ".json");
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) {
        throw RunNotFound(run_id, root_);
    }
    std::ostringstream buffer;
    {
        std::ifstream in(path, std::ios::binary);
        buffer << in.rdbuf();
    }
    domain::Json data;
    try {
        data = domain::Json::parse(buffer.str());
    } catch (const std::exception& exc) {
        // A corrupted checkpoint is never executed from.
        throw CorruptCheckpoint(run_id, exc.what());
    }
    return workflow_spec::WorkflowRun::from_dict(data);
}

std::vector<std::string> WorkflowRunStore::list_run_ids() const {
    static constexpr std::string_view kPrefix = "run-";
    static constexpr std::string_view kSuffix = ".json";
    std::vector<std::string> ids;
    std::error_code ec;
    // root.glob("run-*.json"): dot-prefixed tmp files never match.
    for (const auto& entry : std::filesystem::directory_iterator(root_, ec)) {
        const std::string name = entry.path().filename().string();
        if (name.size() < kPrefix.size() + kSuffix.size()) continue;
        if (!name.starts_with(kPrefix) || !name.ends_with(kSuffix)) continue;
        ids.push_back(name.substr(kPrefix.size(),
                                  name.size() - kPrefix.size() - kSuffix.size()));
    }
    std::sort(ids.begin(), ids.end());
    return ids;
}

std::vector<workflow_spec::WorkflowRun> WorkflowRunStore::list_runs() const {
    std::vector<workflow_spec::WorkflowRun> runs;
    for (const std::string& run_id : list_run_ids()) {
        try {
            runs.push_back(load(run_id));
        } catch (...) {  // a corrupted run must not poison cache lookups
            if (sink_) sink_("skipping unreadable workflow run " + run_id);
        }
    }
    return runs;
}

void WorkflowRunStore::cache_index_entry(
    const workflow_spec::WorkflowRun& run) {
    if (!index_built_) return;  // Python: _cache_index is None -> no-op
    if (run.state == workflow_spec::RunState::running) {
        return;  // not reusable evidence until terminal
    }
    std::lock_guard<std::mutex> lock(index_mutex_);
    for (const auto& [node_id, node_run] : run.node_runs) {
        if (to_string(node_run.state) != "succeeded") continue;
        // `node_run.cache_identity` truthy: present AND non-empty.
        if (!node_run.cache_identity.has_value() ||
            node_run.cache_identity->empty()) {
            continue;
        }
        if (node_run.from_cache) continue;  // reuse chains to first execution
        if (node_run.output_version_ids.empty()) continue;
        const std::string pair_key = run.run_id + '\x1f' + node_id;
        if (indexed_pairs_.count(pair_key) != 0) continue;
        indexed_pairs_.insert(pair_key);
        cache_index_[*node_run.cache_identity].emplace_back(run.run_id, node_id);
    }
}

int WorkflowRunStore::rebuild_cache_index() {
    {
        std::lock_guard<std::mutex> lock(index_mutex_);
        cache_index_.clear();
        indexed_pairs_.clear();
        index_built_ = true;
    }
    std::vector<workflow_spec::WorkflowRun> runs = list_runs();
    // Oldest to newest by (updated_at or 0.0), stable — the newest-first
    // read is real recency, not a lexicographic accident.
    std::stable_sort(runs.begin(), runs.end(),
                     [](const workflow_spec::WorkflowRun& a,
                        const workflow_spec::WorkflowRun& b) {
                         return updated_or_zero(a) < updated_or_zero(b);
                     });
    for (const auto& run : runs) {
        cache_index_entry(run);
    }
    std::lock_guard<std::mutex> lock(index_mutex_);
    int total = 0;
    for (const auto& [identity, entries] : cache_index_) {
        total += static_cast<int>(entries.size());
    }
    return total;
}

std::vector<std::pair<std::string, std::string>>
WorkflowRunStore::candidates_for_identity(const std::string& cache_identity) {
    if (!index_built_) rebuild_cache_index();  // lazy build
    std::vector<std::pair<std::string, std::string>> entries;
    {
        std::lock_guard<std::mutex> lock(index_mutex_);
        const auto it = cache_index_.find(cache_identity);
        if (it != cache_index_.end()) entries = it->second;
    }
    std::reverse(entries.begin(), entries.end());  // newest first
    return entries;
}

void WorkflowRunStore::set_log_sink(
    std::function<void(const std::string&)> sink) {
    sink_ = sink;
    remember_sink(this, std::move(sink));
}

// -------------------------------------------------------- default root --

std::filesystem::path default_store_root(const std::string& project_path) {
    if (project_path.empty()) {
        return default_store_root();
    }
    // paths.artifact_dir_for: strip ".paleo.json" from the FILENAME and
    // append ".artifacts" as a sibling directory.
    const std::filesystem::path project(project_path);
    std::string name = project.filename().string();
    static constexpr std::string_view kSuffix = ".paleo.json";
    if (name.size() >= kSuffix.size() &&
        name.compare(name.size() - kSuffix.size(), kSuffix.size(), kSuffix) ==
            0) {
        name.resize(name.size() - kSuffix.size());
    }
    return (project.parent_path() / (name + ".artifacts")) / "workflows";
}

std::filesystem::path default_store_root() {
    return std::filesystem::temp_directory_path() / "paleo-workflow-runs";
}

// ----------------------------------------------------- reuse + lineage --

std::optional<workflow_spec::NodeRun> find_reusable_node(
    const WorkflowRunStore& store, const std::string& cache_identity,
    const CatalogLike* catalog, bool verify_integrity) {
    // candidates_for_identity lazily builds the index (mutating cache
    // state) but is observationally a lookup; store.hpp models the Python
    // seam without const, hence the cast.
    WorkflowRunStore& mutable_store = const_cast<WorkflowRunStore&>(store);
    for (const auto& [run_id, node_id] :
         mutable_store.candidates_for_identity(cache_identity)) {
        workflow_spec::WorkflowRun run;
        try {
            run = store.load(run_id);
        } catch (...) {
            log_for_store(&store,
                          "cache candidate run " + run_id + " unreadable; skipping");
            continue;
        }
        using workflow_spec::RunState;
        if (run.state != RunState::completed && run.state != RunState::failed &&
            run.state != RunState::interrupted) {
            continue;  // a still-running execution is not reusable evidence
        }
        const workflow_spec::NodeRun* node_run = run.find_node_run(node_id);
        if (node_run == nullptr) continue;
        if (to_string(node_run->state) != "succeeded" ||
            !node_run->cache_identity.has_value() ||
            node_run->cache_identity->empty()) {
            continue;
        }
        if (*node_run->cache_identity != cache_identity) continue;
        if (node_run->from_cache) continue;
        if (node_run->output_version_ids.empty()) continue;
        if (catalog != nullptr &&
            !outputs_resolvable(*const_cast<CatalogLike*>(catalog),
                                node_run->output_version_ids,
                                verify_integrity)) {
            continue;
        }
        return *node_run;
    }
    return std::nullopt;
}

std::vector<std::string> run_lineage(const WorkflowRunStore& store,
                                     const std::string& run_id) {
    std::vector<std::string> chain;
    std::unordered_set<std::string> seen;
    std::optional<std::string> current = run_id;
    while (current.has_value() && seen.count(*current) == 0) {
        seen.insert(*current);
        chain.push_back(*current);
        try {
            const workflow_spec::WorkflowRun run = store.load(*current);
            current = run.parent_run_id;
        } catch (...) {
            break;  // unreadable link stops the walk, keeping what walked
        }
    }
    std::reverse(chain.begin(), chain.end());  // oldest first
    return chain;
}

}  // namespace pwb::workflow_engine
