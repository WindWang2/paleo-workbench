#include <pwb/workflow_graph/graph.hpp>

#include "py_text.hpp"

#include <algorithm>
#include <deque>
#include <unordered_set>

namespace pwb::workflow_graph {

using detail::py_str;
using detail::truthy;
using detail::utf8_code_point;

namespace {

// dict.setdefault on insertion-ordered tables.
template <typename V>
V& slot(std::vector<std::pair<std::string, V>>& table,
        std::unordered_map<std::string, std::size_t>& index,
        const std::string& key) {
    auto it = index.find(key);
    if (it == index.end()) {
        index.emplace(key, table.size());
        table.emplace_back(key, V{});
        return table.back().second;
    }
    return table[it->second].second;
}

// _reachable(adj, src, dst) — DFS over producer->consumer adjacency.
bool reachable(
    const std::unordered_map<std::string, std::set<std::string>>& adj,
    const std::string& src, const std::string& dst) {
    if (src == dst) return true;
    std::unordered_set<std::string> seen{src};
    std::vector<std::string> stack{src};
    while (!stack.empty()) {
        std::string node = stack.back();
        stack.pop_back();
        auto it = adj.find(node);
        if (it == adj.end()) continue;
        for (const auto& nxt : it->second) {
            if (nxt == dst) return true;
            if (seen.insert(nxt).second) stack.push_back(nxt);
        }
    }
    return false;
}

}  // namespace

void DependencyGraph::rebuild(const std::vector<DataVersionRef>& versions,
                              const std::vector<DataRunRef>& runs) {
    versions_.clear();
    runs_.clear();
    version_index_.clear();
    run_index_.clear();
    producing_run_.clear();
    producing_run_index_.clear();
    consumers_.clear();
    consumers_index_.clear();
    run_inputs_.clear();
    run_inputs_index_.clear();
    run_outputs_.clear();
    run_outputs_index_.clear();
    version_asset_.clear();
    version_asset_index_.clear();
    asset_versions_.clear();
    asset_versions_index_.clear();
    domain_task_runs_.clear();
    domain_task_index_.clear();
    edges_.clear();
    cycle_nodes_.clear();

    // self.versions/self.runs are Python DICTS — assignment keeps the
    // first-key position but stores the LAST record for duplicated ids
    // (#1340).
    for (const auto& ver : versions) {
        auto [it, inserted] = version_index_.try_emplace(ver.version_id,
                                                         versions_.size());
        if (inserted) {
            versions_.push_back(ver);
        } else {
            versions_[it->second] = ver;
        }
        slot(version_asset_, version_asset_index_, ver.version_id) =
            ver.asset_id;
        slot(asset_versions_, asset_versions_index_, ver.asset_id)
            .push_back(ver.version_id);
        if (ver.producing_run_id.has_value() &&
            !ver.producing_run_id->empty()) {
            slot(producing_run_, producing_run_index_, ver.version_id) =
                *ver.producing_run_id;
        }
    }

    for (const auto& run : runs) {
        auto [it, inserted] =
            run_index_.try_emplace(run.run_id, runs_.size());
        if (inserted) {
            runs_.push_back(run);
        } else {
            runs_[it->second] = run;
        }
        slot(run_inputs_, run_inputs_index_, run.run_id) =
            run.input_version_ids;
        slot(run_outputs_, run_outputs_index_, run.run_id) =
            run.output_version_ids;
        for (const auto& vid : run.input_version_ids)
            slot(consumers_, consumers_index_, vid).push_back(run.run_id);
        for (const auto& vid : run.output_version_ids) {
            // dict.setdefault — installs only when the key is ABSENT; an
            // existing "" value must survive (#1340).
            if (!producing_run_index_.count(vid))
                slot(producing_run_, producing_run_index_, vid) = run.run_id;
        }
        if (run.domain_task_id.has_value() && !run.domain_task_id->empty())
            slot(domain_task_runs_, domain_task_index_, *run.domain_task_id)
                .push_back(run.run_id);
        for (const auto& in_vid : run.input_version_ids)
            for (const auto& out_vid : run.output_version_ids)
                edges_.push_back(GraphEdge{in_vid, run.run_id, out_vid,
                                           run.operation});
    }

    cycle_nodes_ = detect_cycle_nodes();
}

const DataRunRef* DependencyGraph::run(const std::string& run_id) const {
    auto it = run_index_.find(run_id);
    return it == run_index_.end() ? nullptr : &runs_[it->second];
}

const DataVersionRef* DependencyGraph::version(
    const std::string& version_id) const {
    auto it = version_index_.find(version_id);
    return it == version_index_.end() ? nullptr : &versions_[it->second];
}

std::optional<std::string> DependencyGraph::asset_id_for(
    const std::string& version_id) const {
    auto it = version_asset_index_.find(version_id);
    if (it != version_asset_index_.end())
        return version_asset_[it->second].second;
    const auto* ver = version(version_id);
    if (ver) return ver->asset_id;
    return std::nullopt;
}

std::vector<const DataRunRef*> DependencyGraph::direct_downstream_runs(
    const std::string& version_id) const {
    std::vector<const DataRunRef*> out;
    auto it = consumers_index_.find(version_id);
    if (it == consumers_index_.end()) return out;
    for (const auto& rid : consumers_[it->second].second) {
        if (const auto* r = run(rid)) out.push_back(r);
    }
    return out;
}

std::vector<const DataRunRef*> DependencyGraph::transitive_downstream_runs(
    const std::vector<std::string>& version_ids, std::size_t max_nodes) const {
    std::vector<std::string> roots;
    for (const auto& v : version_ids)
        if (!v.empty()) roots.push_back(v);
    std::vector<const DataRunRef*> ordered;
    if (roots.empty()) return ordered;

    std::unordered_set<std::string> visited_versions;
    std::unordered_set<std::string> visited_runs;
    std::deque<std::string> q(roots.begin(), roots.end());
    std::size_t steps = 0;
    while (!q.empty()) {
        if (++steps > max_nodes) break;
        std::string vid = q.front();
        q.pop_front();
        if (!visited_versions.insert(vid).second) continue;
        auto cit = consumers_index_.find(vid);
        if (cit == consumers_index_.end()) continue;
        for (const auto& rid : consumers_[cit->second].second) {
            if (!visited_runs.insert(rid).second) continue;
            const auto* r = run(rid);
            if (!r) continue;
            ordered.push_back(r);
            auto oit = run_outputs_index_.find(rid);
            if (oit == run_outputs_index_.end()) continue;
            for (const auto& out_vid : run_outputs_[oit->second].second) {
                if (!visited_versions.count(out_vid)) q.push_back(out_vid);
            }
        }
    }
    return ordered;
}

std::vector<std::string> DependencyGraph::transitive_downstream_versions(
    const std::vector<std::string>& version_ids) const {
    std::vector<std::string> out;
    std::unordered_set<std::string> seen;
    for (const auto* r : transitive_downstream_runs(version_ids)) {
        auto oit = run_outputs_index_.find(r->run_id);
        if (oit == run_outputs_index_.end()) continue;
        for (const auto& vid : run_outputs_[oit->second].second) {
            if (seen.insert(vid).second) out.push_back(vid);
        }
    }
    return out;
}

const DataRunRef* DependencyGraph::latest_run_for_domain_task(
    const std::string& domain_task_id) const {
    auto it = domain_task_index_.find(domain_task_id);
    if (it == domain_task_index_.end() ||
        domain_task_runs_[it->second].second.empty())
        return nullptr;
    return run(domain_task_runs_[it->second].second.back());
}

const DataRunRef* DependencyGraph::find_reuse_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids,
    const std::optional<std::string>& generator_version,
    const std::optional<std::string>& input_snapshot_hash,
    const Json& parameters, bool require_outputs) const {
    const bool filter_params =
        parameters.is_object() && !parameters.empty();
    // Python iterates reversed(list(self.runs.values())) — runs_ is the
    // deduplicated dict-values view (first-key order, last record) (#1340).
    for (auto it = runs_.rbegin(); it != runs_.rend(); ++it) {
        const auto& r = *it;
        if (r.operation != operation) continue;
        if (r.status != "complete" && r.status != "completed") continue;
        if (r.input_version_ids != input_version_ids) continue;
        if (generator_version.has_value() &&
            r.generator_version.value_or("") != *generator_version)
            continue;
        if (input_snapshot_hash.has_value() &&
            r.input_snapshot_hash.value_or("") != *input_snapshot_hash)
            continue;
        if (filter_params) {
            const Json rp = r.parameters.is_object() ? r.parameters
                                                   : Json::object();
            bool mismatch = false;
            for (const auto& [k, v] : parameters.items()) {
                if (!rp.contains(k) || rp.at(k) != v) {
                    mismatch = true;
                    break;
                }
            }
            if (mismatch) continue;
        }
        if (require_outputs && r.output_version_ids.empty()) continue;
        return &r;
    }
    return nullptr;
}

std::set<std::string> DependencyGraph::detect_cycle_nodes() const {
    // Version->version adjacency via edges, deduped preserving first order.
    std::unordered_map<std::string, std::vector<std::string>> adj;
    std::unordered_map<std::string, std::unordered_set<std::string>> seen;
    std::set<std::string> nodes;
    for (const auto& e : edges_) {
        if (seen[e.source_version_id].insert(e.target_version_id).second)
            adj[e.source_version_id].push_back(e.target_version_id);
    }
    for (const auto& v : versions_) nodes.insert(v.version_id);
    for (const auto& [k, targets] : adj) {
        nodes.insert(k);
        nodes.insert(targets.begin(), targets.end());
    }

    enum : unsigned char { WHITE = 0, GRAY = 1, BLACK = 2 };
    std::unordered_map<std::string, unsigned char> color;
    for (const auto& n : nodes) color.emplace(n, WHITE);
    std::set<std::string> cycle;

    for (const auto& start : nodes) {
        if (color[start] != WHITE) continue;
        std::vector<std::pair<std::string, std::size_t>> stack{{start, 0}};
        color[start] = GRAY;
        while (!stack.empty()) {
            auto& [node, idx] = stack.back();
            auto ait = adj.find(node);
            const std::vector<std::string> empty;
            const auto& children =
                ait == adj.end() ? empty : ait->second;
            if (idx < children.size()) {
                const std::string& nxt = children[idx];
                ++stack.back().second;
                auto cit = color.find(nxt);
                const unsigned char c =
                    cit == color.end() ? WHITE : cit->second;
                if (c == GRAY) {
                    cycle.insert(node);
                    cycle.insert(nxt);
                } else if (c == WHITE) {
                    color[nxt] = GRAY;
                    stack.emplace_back(nxt, 0);
                }
            } else {
                color[node] = BLACK;
                stack.pop_back();
            }
        }
    }
    return cycle;
}

std::vector<const DataRunRef*> DependencyGraph::topological_runs(
    const std::vector<std::string>& run_ids,
    const std::optional<std::map<std::string, std::set<std::string>>>&
        task_consumers_opt) const {
    std::set<std::string> wanted;
    for (const auto& rid : run_ids)
        if (run_index_.count(rid)) wanted.insert(rid);
    if (wanted.empty()) return {};

    const auto& task_consumers =
        task_consumers_opt.has_value() ? *task_consumers_opt
                                       : std::map<std::string,
                                                  std::set<std::string>>{};

    // Edge A->B means A produces a version B consumes.
    std::unordered_map<std::string, std::set<std::string>> adj;
    std::unordered_map<std::string, int> indeg;
    for (const auto& rid : wanted) indeg[rid] = 0;
    for (const auto& rid : wanted) {
        auto oit = run_outputs_index_.find(rid);
        if (oit == run_outputs_index_.end()) continue;
        for (const auto& out_vid : run_outputs_[oit->second].second) {
            auto cit = consumers_index_.find(out_vid);
            if (cit == consumers_index_.end()) continue;
            for (const auto& consumer : consumers_[cit->second].second) {
                if (consumer != rid && wanted.count(consumer) &&
                    adj[rid].insert(consumer).second) {
                    ++indeg[consumer];
                }
            }
        }
    }

    // Latest run per domain task within `wanted`, max by (started_at, rid).
    std::map<std::string, std::vector<std::string>> by_domain;
    for (const auto& rid : wanted) {
        const auto* r = run(rid);
        if (r && r->domain_task_id.has_value() &&
            !r->domain_task_id->empty())
            by_domain[*r->domain_task_id].push_back(rid);
    }
    std::map<std::string, std::string> latest_by_domain;
    for (const auto& [tid, rids] : by_domain) {
        const std::string* best = nullptr;
        for (const auto& rid : rids) {
            const auto* r = run(rid);
            if (!best ||
                std::make_pair(r->started_at.value_or(""), rid) >
                    std::make_pair(run(*best)->started_at.value_or(""),
                                   *best)) {
                best = &rid;
            }
        }
        if (best) latest_by_domain[tid] = *best;
    }

    std::vector<std::pair<std::string, std::string>> synthetic;
    auto add_synthetic = [&](const std::string& consumer_rid,
                             const std::vector<std::string>& producer_tids) {
        for (const auto& tid : producer_tids) {
            auto lit = latest_by_domain.find(tid);
            if (lit == latest_by_domain.end() || lit->second == consumer_rid ||
                !wanted.count(lit->second))
                continue;
            if (!reachable(adj, consumer_rid, lit->second))
                synthetic.emplace_back(lit->second, consumer_rid);
        }
    };

    for (const auto& rid : wanted) {
        const auto* r = run(rid);
        if (!r) continue;
        if (r->operation == "map_compile") {
            const Json& params =
                r->parameters.is_object() ? r->parameters : Json::object();
            std::vector<std::string> producer_tids;
            if (params.contains("linked_prediction_task_id") &&
                truthy(params.at("linked_prediction_task_id"))) {
                producer_tids.push_back(
                    py_str(params.at("linked_prediction_task_id")));
            }
            if (params.contains("source_task_ids") &&
                truthy(params.at("source_task_ids"))) {
                const Json& s = params.at("source_task_ids");
                if (s.is_array()) {
                    for (const auto& el : s)
                        producer_tids.push_back(py_str(el));
                } else if (s.is_string()) {
                    // Python iterates a string into characters.
                    const std::string& sv = s.get_ref<const std::string&>();
                    for (std::size_t i = 0; i < sv.size();) {
                        const auto d = utf8_code_point(sv, i);
                        const std::size_t len = d ? d->size : 1;
                        producer_tids.push_back(sv.substr(i, len));
                        i += len;
                    }
                } else if (s.is_object()) {
                    // Iterating a dict yields its KEYS (#1343 item 4).
                    for (const auto& [k, _] : s.items())
                        producer_tids.push_back(k);
                } else {
                    // Truthy non-iterable scalar: `for s in <scalar>` raises
                    // TypeError in Python — do not silently swallow (#1343).
                    throw WorkflowTypeError("'" + detail::py_type_name(s) +
                                            "' object is not iterable");
                }
            }
            add_synthetic(rid, producer_tids);
        }
        if (!task_consumers.empty() && r->domain_task_id.has_value()) {
            auto tit = task_consumers.find(*r->domain_task_id);
            if (tit != task_consumers.end()) {
                add_synthetic(
                    rid, std::vector<std::string>(tit->second.begin(),
                                                tit->second.end()));
            }
        }
    }
    for (const auto& [src, dst] : synthetic) {
        if (adj[src].insert(dst).second) ++indeg[dst];
    }

    std::deque<std::string> q;
    {
        std::vector<std::string> zero;
        for (const auto& [rid, d] : indeg)
            if (d == 0) zero.push_back(rid);
        std::sort(zero.begin(), zero.end());
        q.assign(zero.begin(), zero.end());
    }
    std::vector<const DataRunRef*> ordered;
    while (!q.empty()) {
        std::string rid = q.front();
        q.pop_front();
        const auto* r = run(rid);
        if (r) ordered.push_back(r);
        auto ait = adj.find(rid);
        if (ait == adj.end()) continue;
        for (const auto& nxt : ait->second) {  // std::set iterates sorted
            if (--indeg[nxt] == 0) q.push_back(nxt);
        }
    }
    if (ordered.size() != wanted.size()) {
        throw DependencyGraphError(
            "cycle detected in recompute subset; cannot topologically order "
            "plan");
    }
    return ordered;
}

}  // namespace pwb::workflow_graph
