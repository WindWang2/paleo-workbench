#include <pwb/workflow_engine/engine.hpp>

#include <algorithm>
#include <chrono>
#include <cctype>
#include <functional>
#include <iostream>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace pwb::workflow_engine {
namespace {

bool matches_node_id(const std::string& id) {
    // Python: ^[a-z][a-z0-9_]*$
    if (id.empty() || !std::islower(static_cast<unsigned char>(id[0]))) {
        return false;
    }
    for (char c : id) {
        const bool ok = std::isdigit(static_cast<unsigned char>(c))
                        || std::islower(static_cast<unsigned char>(c)) || c == '_';
        if (!ok) return false;
    }
    return true;
}

bool matches_workflow_id(const std::string& id) {
    // Python: ^[a-z][a-z0-9_.-]{1,63}$
    if (id.size() < 2 || id.size() > 64
        || !std::islower(static_cast<unsigned char>(id[0]))) {
        return false;
    }
    for (char c : id) {
        const bool ok = std::isdigit(static_cast<unsigned char>(c))
                        || std::islower(static_cast<unsigned char>(c)) || c == '_'
                        || c == '.' || c == '-';
        if (!ok) return false;
    }
    return true;
}

// Python repr of a list of strings: ['a', 'b'] (str uses single quotes).
std::string py_string_list(const std::vector<std::string>& ids) {
    std::string out = "[";
    for (std::size_t i = 0; i < ids.size(); ++i) {
        if (i) out += ", ";
        out += "'" + ids[i] + "'";
    }
    out += "]";
    return out;
}

// A parameter object is a $ref binding only when its key set is exactly
// {"$ref"} or {"$ref","key"} (Python binding-object contract, $ref half).
struct Binding {
    bool is_binding = false;
    const Json* ref = nullptr;
    const Json* key = nullptr;  // when present (may be a non-string type)
};

Binding as_binding(const Json& value) {
    Binding binding;
    if (!value.is_object()) return binding;
    if (value.size() == 1 && value.contains("$ref")) {
        binding.is_binding = true;
        binding.ref = &value["$ref"];
    } else if (value.size() == 2 && value.contains("$ref")
               && value.contains("key")) {
        binding.is_binding = true;
        binding.ref = &value["$ref"];
        binding.key = &value["key"];
    }
    return binding;
}

double epoch_now() {
    return static_cast<double>(
               std::chrono::duration_cast<std::chrono::microseconds>(
                   std::chrono::system_clock::now().time_since_epoch())
                   .count())
        / 1e6;
}

void finish_node(NodeRun& node_run, NodeState state, std::string error,
                 std::string skip_reason) {
    node_run.state = state;
    node_run.error = std::move(error);
    node_run.skip_reason = std::move(skip_reason);
    node_run.finished_at = epoch_now();
}

}  // namespace

WorkflowSpec WorkflowSpec::from_json(const Json& data) {
    if (!data.is_object()) {
        throw std::invalid_argument("workflow spec must be a JSON object");
    }
    for (const char* key : {"workflow_id", "nodes"}) {
        if (!data.contains(key)) {
            throw std::invalid_argument(std::string("workflow spec missing '")
                                        + key + "'");
        }
    }
    WorkflowSpec spec;
    spec.workflow_id = data["workflow_id"].get<std::string>();
    const Json& nodes = data["nodes"];
    if (!nodes.is_array()) {
        throw std::invalid_argument("workflow spec 'nodes' must be an array");
    }
    for (const Json& n : nodes) {
        if (!n.is_object() || !n.contains("node_id") || !n.contains("op")) {
            throw std::invalid_argument(
                "workflow node needs 'node_id' and 'op'");
        }
        NodeSpec node;
        node.node_id = n["node_id"].get<std::string>();
        node.op = n["op"].get<std::string>();
        if (n.contains("params")) node.params = n["params"];
        if (n.contains("depends_on")) {
            for (const Json& dep : n["depends_on"]) {
                node.depends_on.push_back(dep.get<std::string>());
            }
        }
        spec.nodes.push_back(std::move(node));
    }
    return spec;
}

std::vector<std::string> validate_spec(const WorkflowSpec& spec,
                                       const NodeRegistry& registry) {
    std::vector<std::string> problems;
    if (!matches_workflow_id(spec.workflow_id)) {
        problems.push_back(
            "workflow_id '" + spec.workflow_id
            + "' must match ^[a-z][a-z0-9_.-]{1,63}$");
    }
    if (spec.nodes.empty()) {
        problems.push_back("workflow needs at least one node");
    }

    std::set<std::string> seen;
    for (const NodeSpec& node : spec.nodes) {
        if (!matches_node_id(node.node_id)) {
            problems.push_back("node_id '" + node.node_id
                               + "' must match ^[a-z][a-z0-9_]*$");
        }
        if (!seen.insert(node.node_id).second) {
            problems.push_back("duplicate node id '" + node.node_id + "'");
            continue;  // Python skips the action checks for the duplicate too
        }
        if (!registry.has(node.op)) {
            problems.push_back("node '" + node.node_id
                               + "': unknown action '" + node.op + "'");
        }
    }

    for (const NodeSpec& node : spec.nodes) {
        for (const std::string& dep : node.depends_on) {
            if (seen.find(dep) == seen.end()) {
                problems.push_back("node '" + node.node_id + "': dependency '"
                                   + dep + "' does not exist");
            } else if (dep == node.node_id) {
                problems.push_back("node '" + node.node_id
                                   + "': self-dependency");
            }
        }
        // $ref bindings must reference a node of this workflow listed in
        // depends_on (data dependencies are explicit). Check order mirrors
        // Python _binding_problems: ref existence, depends_on, key type.
        std::function<void(const Json&)> walk = [&](const Json& value) {
            if (value.is_object()) {
                const Binding binding = as_binding(value);
                if (binding.is_binding || value.contains("$ref")) {
                    if (!binding.is_binding) {
                        // Fail-closed: {"$ref": …, …extra keys…} is never a
                        // literal (Python rejects the same shapes).
                        problems.push_back(
                            "node '" + node.node_id
                            + "': binding objects must be exactly "
                              "{\"$ref\": node} or {\"$ref\": node, \"key\": "
                              "key}");
                        return;
                    }
                    const std::string target = binding.ref->is_string()
                        ? binding.ref->get<std::string>()
                        : binding.ref->dump();
                    if (seen.find(target) == seen.end()) {
                        problems.push_back(
                            "node '" + node.node_id + "': binding $ref '"
                            + target + "' is not a node in this workflow");
                    } else if (std::find(node.depends_on.begin(),
                                         node.depends_on.end(), target)
                               == node.depends_on.end()) {
                        problems.push_back(
                            "node '" + node.node_id + "': binding $ref '"
                            + target
                            + "' must be listed in depends_on (data "
                              "dependencies are explicit)");
                    } else if (binding.key != nullptr
                               && !binding.key->is_string()) {
                        problems.push_back("node '" + node.node_id
                                           + "': $ref key must be a string");
                    }
                    return;
                }
                for (auto it = value.begin(); it != value.end(); ++it) {
                    walk(it.value());
                }
            } else if (value.is_array()) {
                for (const Json& item : value) walk(item);
            }
        };
        walk(node.params);
    }

    {
        // Kahn leftover = cycle (Python "dependency cycle among nodes [...]",
        // ids sorted; self-dependencies count, matching _cycle_problems).
        // Python's dict-collapse artifact ("cycle among nodes []" on
        // duplicate-id specs) is not replicated: an EMPTY leftover appends
        // nothing, a non-empty leftover always reports.
        std::unordered_map<std::string, int> indegree;
        std::unordered_map<std::string, std::vector<std::string>> consumers;
        for (const NodeSpec& node : spec.nodes) {
            indegree.emplace(node.node_id, 0);
        }
        for (const NodeSpec& node : spec.nodes) {
            for (const std::string& dep : node.depends_on) {
                if (indegree.find(dep) != indegree.end()) {
                    ++indegree[node.node_id];
                    consumers[dep].push_back(node.node_id);
                }
            }
        }
        std::vector<std::string> ready;
        for (const auto& [id, degree] : indegree) {
            if (degree == 0) ready.push_back(id);
        }
        std::size_t visited = 0;
        while (!ready.empty()) {
            const std::string current = ready.back();
            ready.pop_back();
            ++visited;
            for (const std::string& next : consumers[current]) {
                if (--indegree[next] == 0) ready.push_back(next);
            }
        }
        if (visited != indegree.size()) {
            std::vector<std::string> cyclic;
            for (const auto& [id, degree] : indegree) {
                if (degree > 0) cyclic.push_back(id);
            }
            std::sort(cyclic.begin(), cyclic.end());
            problems.push_back("dependency cycle among nodes "
                               + py_string_list(cyclic));
        }
    }
    return problems;
}

std::vector<std::string> topological_order(const WorkflowSpec& spec) {
    std::unordered_map<std::string, int> indegree;
    std::unordered_map<std::string, std::vector<std::string>> consumers;
    for (const NodeSpec& node : spec.nodes) {
        indegree.emplace(node.node_id, 0);
    }
    for (const NodeSpec& node : spec.nodes) {
        for (const std::string& dep : node.depends_on) {
            if (indegree.find(dep) != indegree.end() && dep != node.node_id) {
                ++indegree[node.node_id];
                consumers[dep].push_back(node.node_id);
            }
        }
    }
    // Spec-order tie-break: deterministic topological order.
    std::vector<std::string> order;
    std::unordered_set<std::string> done;
    const std::size_t total = indegree.size();
    while (order.size() < total) {
        bool progress = false;
        for (const NodeSpec& node : spec.nodes) {
            if (done.count(node.node_id)) continue;
            if (indegree[node.node_id] == 0) {
                order.push_back(node.node_id);
                done.insert(node.node_id);
                for (const std::string& next : consumers[node.node_id]) {
                    --indegree[next];
                }
                progress = true;
                break;  // restart scan so earlier nodes win ties
            }
        }
        if (!progress) {
            throw std::logic_error("workflow spec is cyclic");
        }
    }
    return order;
}

const NodeRun* WorkflowRun::find(const std::string& node_id) const {
    for (const NodeRun& node_run : node_runs) {
        if (node_run.node_id == node_id) return &node_run;
    }
    return nullptr;
}

NodeRun* WorkflowRun::find(const std::string& node_id) {
    for (NodeRun& node_run : node_runs) {
        if (node_run.node_id == node_id) return &node_run;
    }
    return nullptr;
}

ValidationError::ValidationError(std::string workflow_id,
                                 std::vector<std::string> problems)
    : std::runtime_error("workflow '" + workflow_id + "' invalid: "
                         + [&] {
                             std::string joined;
                             for (std::size_t i = 0; i < problems.size(); ++i) {
                                 if (i) joined += "; ";
                                 joined += problems[i];
                             }
                             return joined;
                         }()),
      problems(std::move(problems)) {}

namespace {

// Resolve {"$ref": node[, "key"]} against completed node outputs (the
// resolve_value $ref half; message strings are Python's).
Json resolve_value(const Json& value, const WorkflowRun& run) {
    if (value.is_object()) {
        const Binding binding = as_binding(value);
        if (!binding.is_binding && value.contains("$ref")) {
            // Validate rejects this shape; this guard keeps run-time honest
            // for directly-constructed specs.
            throw std::runtime_error(
                "binding objects must be exactly {\"$ref\": node} or "
                "{\"$ref\": node, \"key\": key}");
        }
        if (binding.is_binding) {
            const std::string target = binding.ref->get<std::string>();
            const NodeRun* source = run.find(target);
            // Python's results view only carries nodes with non-empty
            // outputs, so an empty-outputs node is "not resolved yet" there
            // too.
            if (source == nullptr || source->outputs.empty()) {
                throw std::runtime_error("reference '" + target
                                         + "' has no resolved output yet");
            }
            if (binding.key == nullptr) {
                return source->outputs;
            }
            const auto slot = source->outputs.find(binding.key->get<std::string>());
            if (slot == source->outputs.end()) {
                throw std::runtime_error("reference '" + target
                                         + "' produced no output key '"
                                         + binding.key->get<std::string>()
                                         + "'");
            }
            return *slot;
        }
        Json out = Json::object();
        for (auto it = value.begin(); it != value.end(); ++it) {
            out[it.key()] = resolve_value(it.value(), run);
        }
        return out;
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const Json& item : value) out.push_back(resolve_value(item, run));
        return out;
    }
    return value;
}

}  // namespace

Engine::Engine(const NodeRegistry& registry, LogSink sink)
    : registry_(registry), sink_(std::move(sink)) {}

void Engine::log(const std::string& line) const {
    if (sink_) {
        sink_("[workflow_engine] " + line);
        return;
    }
    std::cout << "[workflow_engine] " << line << std::endl;
}

WorkflowRun Engine::run(const WorkflowSpec& spec) const {
    CancelToken token;
    return run(spec, token);
}

WorkflowRun Engine::run(const WorkflowSpec& spec,
                        const CancelToken& token) const {
    const std::vector<std::string> problems =
        validate_spec(spec, registry_);
    if (!problems.empty()) {
        throw ValidationError(spec.workflow_id, problems);
    }

    WorkflowRun run;
    run.spec = spec;
    run.state = RunState::running;
    for (const NodeSpec& node : spec.nodes) {
        NodeRun node_run;
        node_run.node_id = node.node_id;
        run.node_runs.push_back(std::move(node_run));
    }
    log("run " + spec.workflow_id + ": start (" + std::to_string(spec.nodes.size())
        + " nodes)");

    for (const std::string& node_id : topological_order(spec)) {
        if (token.is_cancelled()) {
            // Cancel observed at a node boundary: nothing pending may run.
            for (NodeRun& node_run : run.node_runs) {
                if (node_run.state == NodeState::pending
                    || node_run.state == NodeState::running) {
                    finish_node(node_run, NodeState::cancelled,
                                "run cancelled", "");
                    log("node " + node_run.node_id + ": cancelled");
                }
            }
            break;
        }
        NodeRun& node_run = *run.find(node_id);
        if (node_run.state != NodeState::pending) {
            // Already terminal (e.g. eagerly skipped after an upstream
            // failure) — Python's _ready_batch only judges PENDING nodes.
            continue;
        }
        const NodeSpec& node = *std::find_if(
            spec.nodes.begin(), spec.nodes.end(),
            [&](const NodeSpec& n) { return n.node_id == node_id; });

        // Python _ready_batch: a dependency that did not succeed skips the
        // node (belt-and-braces — _skip_dependents usually marked it first).
        bool blocked = false;
        for (const std::string& dep : node.depends_on) {
            const NodeRun* dep_run = run.find(dep);
            if (dep_run == nullptr || dep_run->state != NodeState::succeeded) {
                blocked = true;
                break;
            }
        }
        if (blocked) {
            finish_node(node_run, NodeState::skipped, "",
                        "dependency did not succeed");
            log("node " + node_id + ": skipped (dependency did not succeed)");
            continue;
        }

        node_run.state = NodeState::running;
        node_run.attempt = 1;
        node_run.started_at = epoch_now();
        log("node " + node_id + " (op=" + node.op + "): running");

        // _skip_dependents: every pending node that depends (directly or
        // transitively) on this node is skipped, never executed. The reason
        // tail ": <cause>" is Python's binding-failure branch.
        const auto skip_dependents = [&](const std::string& failed_id,
                                         const std::string& reason_tail) {
            const std::string reason =
                "upstream " + failed_id + " failed"
                + (reason_tail.empty() ? "" : ": " + reason_tail);
            bool changed = true;
            while (changed) {
                changed = false;
                for (const NodeSpec& other : spec.nodes) {
                    NodeRun& other_run = *run.find(other.node_id);
                    if (other_run.state != NodeState::pending) continue;
                    const bool direct =
                        std::find(other.depends_on.begin(),
                                  other.depends_on.end(), failed_id)
                        != other.depends_on.end();
                    const bool via_skipped =
                        std::any_of(other.depends_on.begin(),
                                    other.depends_on.end(),
                                    [&](const std::string& dep) {
                                        return run.find(dep)->state
                                               == NodeState::skipped;
                                    });
                    if (direct || via_skipped) {
                        finish_node(other_run, NodeState::skipped, "", reason);
                        log("node " + other.node_id + ": skipped (" + reason
                            + ")");
                        changed = true;
                    }
                }
            }
        };
        const auto fail_node_and_skip = [&](const std::string& error,
                                            const std::string& reason_tail) {
            finish_node(node_run, NodeState::failed, error, "");
            log("node " + node_id + " (op=" + node.op + "): failed: " + error);
            skip_dependents(node_id, reason_tail);
        };

        // Python binds parameters BEFORE the executor loop (validation.py
        // bind_parameters): a binding failure is a node failure whose
        // dependents are skipped with the reason tail ": <cause>".
        Json bound;
        std::string bind_error;
        try {
            bound = resolve_value(node.params, run);
        } catch (const std::exception& exc) {
            bind_error = exc.what();
        }
        if (!bind_error.empty()) {
            fail_node_and_skip(bind_error, bind_error);
            continue;
        }

        try {
            const NodeFunction* fn = registry_.find(node.op);
            const NodeResult result = (*fn)(bound, token);
            node_run.outputs = result.outputs;
            node_run.payload = result.payload;
            node_run.state = NodeState::succeeded;
            node_run.finished_at = epoch_now();
            const double elapsed_ms =
                (node_run.finished_at - node_run.started_at) * 1000.0;
            log("node " + node_id + " (op=" + node.op + "): succeeded in "
                + std::to_string(elapsed_ms) + " ms");
        } catch (const Cancelled& exc) {
            finish_node(node_run, NodeState::cancelled,
                        std::string("cancelled: ") + exc.what(), "");
            log("node " + node_id + ": cancelled");
            for (NodeRun& other : run.node_runs) {
                if (other.state == NodeState::pending
                    || other.state == NodeState::running) {
                    finish_node(other, NodeState::cancelled,
                                "cancelled at " + node_id, "");
                    log("node " + other.node_id + ": cancelled");
                }
            }
            break;
        } catch (const std::exception& exc) {
            fail_node_and_skip(exc.what(), "");
        } catch (...) {
            // A node body throwing a non-standard exception is still a node
            // failure — the run must land honestly, never terminate.
            fail_node_and_skip("unknown non-standard exception", "");
        }
    }

    // _finalize: failure dominates cancellation dominates completion.
    const bool any_failed = std::any_of(
        run.node_runs.begin(), run.node_runs.end(),
        [](const NodeRun& nr) { return nr.state == NodeState::failed; });
    const bool any_cancelled = std::any_of(
        run.node_runs.begin(), run.node_runs.end(),
        [](const NodeRun& nr) { return nr.state == NodeState::cancelled; });
    if (any_failed) {
        run.state = RunState::failed;
    } else if (any_cancelled) {
        run.state = RunState::cancelled;
    } else {
        run.state = RunState::completed;
    }
    log("run " + spec.workflow_id + ": " + to_string(run.state));
    return run;
}

}  // namespace pwb::workflow_engine
