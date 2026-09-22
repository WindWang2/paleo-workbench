// CONV-32 — run_engine.cpp: store-driven workflow lifecycle engine, a full
// port of paleo_workbench/workflow/dag/engine.py WorkflowEngine (see
// run_engine.hpp for the frozen semantics + deferred rails). Sequential
// drive only; every persistence step goes through WorkflowRunStore.
#include <pwb/workflow_engine/run_engine.hpp>

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <random>
#include <set>
#include <thread>
#include <typeinfo>
#include <utility>

#if defined(__GNUG__)
#include <cxxabi.h>
#endif

namespace pwb::workflow_engine {

namespace {

const domain::Json& object_schema(const domain::Json& schema) {
    static const domain::Json kObjectSchema{{"type", "object"}};
    if (schema.is_object() && !schema.empty()) return schema;
    return kObjectSchema;  // Python `action_spec.input_schema or {...}`
}

std::string join(const std::vector<std::string>& parts, const char* sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) out += sep;
        out += parts[i];
    }
    return out;
}

std::string to_lower(const std::string& text) {
    std::string lowered;
    lowered.reserve(text.size());
    for (const char ch : text) {
        lowered.push_back(static_cast<char>(
            std::tolower(static_cast<unsigned char>(ch))));
    }
    return lowered;
}

// engine._input_version_ids — ordered dedupe concat of deps' output ids.
std::vector<std::string> collect_input_version_ids(const workflow_spec::WorkflowRun& run,
                                                   const workflow_spec::NodeSpec& node) {
    std::vector<std::string> ids;
    std::set<std::string> seen;
    for (const auto& dep : node.depends_on) {
        const workflow_spec::NodeRun* nr = run.find_node_run(dep);
        if (nr == nullptr) continue;
        for (const auto& id : nr->output_version_ids) {
            if (seen.insert(id).second) ids.push_back(id);
        }
    }
    return ids;
}

// Python exception-class name for the frozen "__checkpoint__" error text.
// Frozen choice: StoreError family -> "StoreError"; filesystem errors map
// to their errno-class Python name; anything else -> "Exception".
std::string python_typename(const std::exception& exc) {
    if (dynamic_cast<const StoreError*>(&exc) != nullptr) return "StoreError";
    const auto* fs_error =
        dynamic_cast<const std::filesystem::filesystem_error*>(&exc);
    if (fs_error != nullptr) {
        switch (fs_error->code().value()) {
        case EACCES:
        case EPERM: return "PermissionError";
        case ENOENT: return "FileNotFoundError";
        case ENOTDIR: return "NotADirectoryError";
        case EISDIR: return "IsADirectoryError";
        default: return "OSError";
        }
    }
    return "Exception";
}

// engine._ExternalSyncedToken (boundary-polling form): an external token
// feeds the engine token; one cancel path.
void sync_external_cancel(CancelToken& token, const RunOptions& options) {
    if (options.external_cancel != nullptr &&
        options.external_cancel->is_cancelled()) {
        token.cancel();
    }
}

// Python f"{type(exc).__name__}: {exc}" equivalent (readable, not mangled).
std::string exception_typename(const std::exception& exc) {
#if defined(__GNUG__)
    int status = 0;
    char* demangled =
        abi::__cxa_demangle(typeid(exc).name(), nullptr, nullptr, &status);
    if (status == 0 && demangled != nullptr) {
        std::string name = demangled;
        std::free(demangled);
        return name;
    }
#endif
    return typeid(exc).name();
}

bool contains_substring(const std::string& haystack, const char* needle) {
    return haystack.find(needle) != std::string::npos;
}

}  // namespace

// ------------------------------------------------------------- exceptions --

WorkflowValidationError::WorkflowValidationError(
    std::string workflow_id, std::vector<std::string> problems)
    : std::runtime_error("workflow '" + workflow_id + "' invalid: " +
                         join(problems, "; ")),
      problems(std::move(problems)) {}

WorkflowValidationError::~WorkflowValidationError() = default;

// ------------------------------------------------------------- helpers --

bool is_resource_shed(const std::optional<std::string>& error) {
    if (!error.has_value() || error->empty()) return false;
    const std::string lowered = to_lower(*error);
    return contains_substring(lowered, "resourceexhausted") ||
           contains_substring(lowered, "cpu:") ||
           contains_substring(lowered, "ram:") ||
           contains_substring(lowered, "io:") ||
           contains_substring(lowered, "vram:") ||
           contains_substring(lowered, "pressure");
}

std::vector<std::string>
condition_node_ids(const workflow_spec::NodeCondition& condition) {
    std::vector<std::string> ids;
    std::function<void(const workflow_spec::NodeCondition&)> walk =
        [&](const workflow_spec::NodeCondition& cond) {
            if (cond.node.has_value() && !cond.node->empty()) {
                ids.push_back(*cond.node);
            }
            for (const auto& sub : cond.conditions) walk(sub);
            if (cond.has_condition()) walk(cond.inner_condition());
        };
    walk(condition);
    return ids;
}

bool evaluate_condition(const workflow_spec::NodeCondition& condition,
                        const workflow_spec::WorkflowRun& run) {
    const std::string& kind = condition.kind;
    if (kind == "node_succeeded") {
        const workflow_spec::NodeRun* target =
            condition.node.has_value() ? run.find_node_run(*condition.node)
                                       : nullptr;
        return target != nullptr && target->state == workflow_spec::NodeState::succeeded;
    }
    if (kind == "node_output_equals") {
        const workflow_spec::NodeRun* target =
            condition.node.has_value() ? run.find_node_run(*condition.node)
                                       : nullptr;
        if (target == nullptr) return false;
        domain::Json value = nullptr;  // Python .get(key) -> None
        if (target->outputs.is_object() && condition.key.has_value() &&
            target->outputs.contains(*condition.key)) {
            value = target->outputs.at(*condition.key);
        }
        return value == condition.value;
    }
    if (kind == "node_state") {
        const workflow_spec::NodeRun* target =
            condition.node.has_value() ? run.find_node_run(*condition.node)
                                       : nullptr;
        return target != nullptr && condition.state.has_value() &&
               to_string(target->state) == *condition.state;
    }
    if (kind == "all_of") {
        for (const auto& sub : condition.conditions) {
            if (!evaluate_condition(sub, run)) return false;
        }
        return true;
    }
    if (kind == "any_of") {
        for (const auto& sub : condition.conditions) {
            if (evaluate_condition(sub, run)) return true;
        }
        return false;
    }
    if (kind == "not") {
        return condition.has_condition() &&
               !evaluate_condition(condition.inner_condition(), run);
    }
    return false;  // unknown kind — never throws
}

// ------------------------------------------------------------- RunEngine --

RunEngine::RunEngine(const IActionCatalog& catalog, RunFunctionMap functions,
                     WorkflowRunStore& store, Clock clock,
                     BackoffWaiter waiter, EnvironmentProvider env,
                     const CatalogLike* artifact_catalog, RunIdGenerator id_gen,
                     CacheRunRail* cache_run_rail)
    : catalog_(catalog),
      functions_(std::move(functions)),
      store_(store),
      clock_(std::move(clock)),
      waiter_(std::move(waiter)),
      env_(std::move(env)),
      artifact_catalog_(artifact_catalog),
      cache_run_rail_(cache_run_rail),
      id_gen_(std::move(id_gen)) {
    if (!clock_) {
        clock_ = [] {
            return std::chrono::duration<double>(
                       std::chrono::system_clock::now().time_since_epoch())
                .count();
        };
    }
    if (!env_) {
        env_ = [] {
            return EnvironmentIdentity{"", "", ""};
        };
    }
    if (!id_gen_) {
        id_gen_ = [] {
            static std::mt19937_64 generator{std::random_device{}()};
            static const char* kHex = "0123456789abcdef";
            std::string run_id;
            for (int i = 0; i < 16; ++i) {
                run_id += kHex[generator() % 16];
            }
            return run_id;
        };
    }
}

RunEngine::~RunEngine() = default;

double RunEngine::now() { return clock_(); }

workflow_spec::BindEnv RunEngine::bind_env(const workflow_spec::WorkflowRun& run,
                                           const RunContext* context) {
    workflow_spec::BindEnv env;
    env.slot_values = run.slot_values;
    // Python _results_view: node_id -> outputs for non-empty outputs.
    for (const auto& [node_id, node_run] : run.node_runs) {
        if (node_run.outputs.is_object() && !node_run.outputs.empty()) {
            env.results[node_id] = node_run.outputs;
        }
    }
    // Python getattr(context, key): whitelisted keys only, null == absent.
    if (context != nullptr && context->context_values.is_object()) {
        for (const auto& key : workflow_spec::context_binding_whitelist()) {
            if (context->context_values.contains(key) &&
                !context->context_values.at(key).is_null()) {
                env.context_values.emplace(
                    key, context->context_values.at(key));
            }
        }
    }
    return env;
}

std::optional<std::string> RunEngine::cache_identity(
    const workflow_spec::NodeSpec& node, const workflow_spec::WorkflowRun& run,
    const RunContext* context) {
    const auto info = catalog_.get(node.action_id);
    if (!info.has_value()) return std::nullopt;  // registry LookupError
    domain::Json bound;
    try {
        bound = workflow_spec::bind_parameters(node, bind_env(run, context));
    } catch (const workflow_spec::BindingError&) {
        return std::nullopt;
    }
    std::vector<std::string> sorted_ids = collect_input_version_ids(run, node);
    std::sort(sorted_ids.begin(), sorted_ids.end());
    domain::Json identity_payload{
        {"action_id", info->action_id},
        {"action_version", info->version},
        {"parameters", bound},
        {"input_version_ids", std::move(sorted_ids)},
    };
    return workflow_spec::canonical_hash(identity_payload);
}

void RunEngine::check_project_match(const workflow_spec::WorkflowRun& run,
                                    const RunContext* context) {
    if (context == nullptr || !run.project_path.has_value() ||
        run.project_path->empty()) {
        return;
    }
    if (context->project_path.empty()) return;
    if (context->project_path == *run.project_path) return;
    throw WorkflowValidationError(run.workflow.workflow_id,
                                  {"run " + run.run_id + " belongs to project '" +
                                   *run.project_path + "', not the current project '" +
                                   context->project_path +
                                   "' — resume/rerun refused"});
}

// -------------------------------------------------------------- create --

workflow_spec::WorkflowRun RunEngine::create_run(const workflow_spec::WorkflowSpec& spec,
                                  domain::Json slot_values,
                                  const RunContext* context) {
    // validation risk map: every registered action is non-destructive here
    // (the destructive registry gate is Python-side; D2 catalog seam).
    workflow_spec::ActionCatalog catalog_map;
    for (const auto& id : catalog_.ids()) {
        if (catalog_.get(id).has_value()) catalog_map.emplace(id, "compute");
    }
    auto problems = workflow_spec::validate_workflow_spec(spec, catalog_map);
    if (!problems.empty()) {
        throw WorkflowValidationError(spec.workflow_id, problems);
    }
    domain::Json values =
        slot_values.is_object() ? std::move(slot_values) : domain::Json::object();
    values = workflow_spec::materialize_slot_defaults(spec, values);
    problems = workflow_spec::slot_schema_problems(spec, values);
    if (!problems.empty()) {
        throw WorkflowValidationError(spec.workflow_id, problems);
    }
    workflow_spec::WorkflowRun run =
        workflow_spec::create_run(spec, values, id_gen_(), now());
    if (context != nullptr) {
        run.project_name = context->workspace_id.empty()
                               ? std::nullopt
                               : std::optional(context->workspace_id);
        run.project_path = context->project_path.empty()
                               ? std::nullopt
                               : std::optional(context->project_path);
    }
    store_.save(run);
    return run;
}

// ----------------------------------------------------------------- run --

workflow_spec::WorkflowRun RunEngine::run(const std::string& run_id, const RunContext* context,
                           const RunOptions& options) {
    // R3-1: reserve the run slot BEFORE the unguarded store_.load — the
    // old two-critical-section form was a check-then-act TOCTOU (two
    // threads both passed the check across the disk I/O window, the second
    // insert overwrote the first, and both drove the run: nodes double-
    // executed and both raced store_.save). Reservation is released on
    // every early return below.
    auto token = std::make_shared<CancelToken>();
    {
        std::lock_guard<std::mutex> lock(active_mutex_);
        const auto [slot, inserted] = active_.try_emplace(
            run_id, ActiveRun{std::string(), token});
        if (!inserted) {
            throw WorkflowValidationError(
                slot->second.workflow_id.empty() ? "unknown"
                                                 : slot->second.workflow_id,
                {"run " + run_id + " is already executing in this process "
                 "(concurrent run/resume would double-execute nodes)"});
        }
    }
    struct ReservationGuard {
        RunEngine* engine;
        const std::string* run_id;
        std::shared_ptr<CancelToken> token;  // identity of OUR reservation
        ~ReservationGuard() {
            if (engine == nullptr) return;
            std::lock_guard<std::mutex> lock(engine->active_mutex_);
            // Erase only OUR slot: after the explicit erase + checkpoint
            // window, a concurrent retry may have legitimately re-reserved
            // this run_id — a key-only erase would delete ITS reservation
            // and reopen the double-execution race (round-4 finding).
            const auto slot = engine->active_.find(*run_id);
            if (slot != engine->active_.end() &&
                slot->second.token == token) {
                engine->active_.erase(slot);
            }
        }
    } reservation{this, &run_id, token};
    workflow_spec::WorkflowRun run = store_.load(run_id);
    if (run.state == workflow_spec::RunState::completed) return run;
    if (run.state == workflow_spec::RunState::cancelled) return run;
    check_project_match(run, context);
    {
        // Upgrade the reservation with the workflow id now that it is known
        // (error messages stay informative; the token is unchanged).
        std::lock_guard<std::mutex> lock(active_mutex_);
        const auto slot = active_.find(run_id);
        if (slot != active_.end()) {
            slot->second.workflow_id = run.workflow.workflow_id;
        }
    }
    const domain::Json project_identity =
        context != nullptr ? context->project_identity : domain::Json(nullptr);
    try {
        prepare_interrupted(run);
        checkpoint(run);
        try {
            drive(run, context, *token, project_identity, options);
        } catch (const Cancelled&) {
            // Cancellation is a first-class terminal outcome of the RUN.
            cancel_pending(run, "run cancelled");
            finalize(run);
        }
    } catch (...) {
        const std::exception_ptr in_flight = std::current_exception();
        {
            std::lock_guard<std::mutex> lock(active_mutex_);
            active_.erase(run_id);
        }
        checkpoint(run);  // a second failure raises out (Python finally)
        std::rethrow_exception(in_flight);
    }
    {
        std::lock_guard<std::mutex> lock(active_mutex_);
        active_.erase(run_id);
    }
    checkpoint(run);
    return run;
}

workflow_spec::WorkflowRun RunEngine::resume(const std::string& run_id,
                              const RunContext* context,
                              const RunOptions& options) {
    const workflow_spec::WorkflowRun run = store_.load(run_id);
    check_project_match(run, context);
    return this->run(run_id, context, options);
}

// --------------------------------------------------------------- rerun --

workflow_spec::WorkflowRun RunEngine::rerun(const std::string& run_id,
                             const std::vector<std::string>& from_nodes,
                             domain::Json slot_overrides,
                             const RunContext* context,
                             const RunOptions& options) {
    workflow_spec::WorkflowRun prior = store_.load(run_id);
    check_project_match(prior, context);
    const workflow_spec::WorkflowSpec& spec = prior.workflow;
    if (!from_nodes.empty()) {
        for (const auto& node_id : from_nodes) {
            spec.node(node_id);  // KeyError -> ModelError (honest failure)
        }
    }
    // _transitive_dependents closure (roots included).
    std::set<std::string> affected(from_nodes.begin(), from_nodes.end());
    bool changed = true;
    while (changed) {
        changed = false;
        for (const auto& node : spec.nodes) {
            if (affected.count(node.node_id) != 0) continue;
            for (const auto& dep : node.depends_on) {
                if (affected.count(dep) != 0) {
                    affected.insert(node.node_id);
                    changed = true;
                    break;
                }
            }
        }
    }
    domain::Json merged = prior.slot_values.is_object() ? prior.slot_values
                                                        : domain::Json::object();
    if (slot_overrides.is_object()) {
        for (const auto& [key, value] : slot_overrides.items()) {
            merged[key] = value;
        }
    }
    workflow_spec::WorkflowRun new_run = workflow_spec::create_run(
        spec, workflow_spec::materialize_slot_defaults(spec, merged),
        id_gen_(), now());
    auto problems = workflow_spec::slot_schema_problems(spec, new_run.slot_values);
    if (!problems.empty()) {
        throw WorkflowValidationError(spec.workflow_id, problems);
    }
    new_run.project_name = prior.project_name;
    new_run.project_path = prior.project_path;
    new_run.parent_run_id = prior.run_id;  // run lineage
    if (context != nullptr) {
        new_run.project_name = !context->workspace_id.empty()
                                   ? std::optional(context->workspace_id)
                                   : prior.project_name;
        new_run.project_path = !context->project_path.empty()
                                   ? std::optional(context->project_path)
                                   : prior.project_path;
    }
    for (const auto& node : spec.nodes) {
        workflow_spec::NodeRun* fresh = new_run.find_node_run(node.node_id);
        const workflow_spec::NodeRun* old = prior.find_node_run(node.node_id);
        if (fresh == nullptr || old == nullptr ||
            affected.count(node.node_id) != 0 ||
            old->state != workflow_spec::NodeState::succeeded) {
            continue;
        }
        // Carry over only PROVABLY identical work: recorded prior identity
        // vs freshly-rebound live-context identity (never re-binding the
        // prior run against a fake context).
        const auto new_identity = cache_identity(node, new_run, context);
        if (!new_identity.has_value() || !old->cache_identity.has_value() ||
            *old->cache_identity != *new_identity) {
            continue;
        }
        workflow_spec::NodeRun carried;
        carried.node_id = node.node_id;
        carried.state = workflow_spec::NodeState::succeeded;
        carried.attempt = old->attempt;
        carried.action_status = old->action_status;
        carried.from_cache = true;
        carried.parameters = old->parameters;
        carried.input_version_ids = old->input_version_ids;
        carried.cache_identity = new_identity;
        carried.output_version_ids = old->output_version_ids;
        carried.outputs = old->outputs;
        carried.receipt = old->receipt;
        if (carried.receipt.has_value() && carried.receipt->is_object()) {
            // Restamp so provenance reads correctly.
            (*carried.receipt)["node_id"] = node.node_id;
            (*carried.receipt)["workflow_run_id"] = new_run.run_id;
            (*carried.receipt)["from_cache"] = true;
        }
        *fresh = std::move(carried);
        if (context != nullptr && context->session != nullptr) {
            context->session->restore_session_pointers(old->outputs);
        }
    }
    store_.save(new_run);
    return this->run(new_run.run_id, context, options);
}

// --------------------------------------------------------------- cancel --

bool RunEngine::cancel(const std::string& run_id) {
    std::shared_ptr<CancelToken> token;
    {
        std::lock_guard<std::mutex> lock(active_mutex_);
        const auto active = active_.find(run_id);
        if (active == active_.end()) return false;
        token = active->second.token;
    }
    if (token) token->cancel();
    return true;
}

// --------------------------------------------------------------- driver --

void RunEngine::drive(workflow_spec::WorkflowRun& run, const RunContext* context,
                      CancelToken& token, const domain::Json& project_identity,
                      const RunOptions& options) {
    run.state = workflow_spec::RunState::running;
    while (true) {
        sync_external_cancel(token, options);
        token.throw_if_cancelled();
        auto batch = ready_batch(run, /*limit=*/1);
        if (!batch.has_value()) break;  // no runnable node and no pending work
        if (batch->empty()) continue;   // nodes are running (parallel-only)
        const std::string& node_id = (*batch)[0];
        // _guard: cancel requested / project switched.
        if (token.is_cancelled()) {
            cancel_pending(run, "run cancelled");
            break;
        }
        if (options.project_probe) {
            domain::Json current;
            try {
                current = options.project_probe();
            } catch (...) {
                // probe failure must not execute nodes unguarded
                cancel_pending(run, "project identity probe failed");
                break;
            }
            if (current != project_identity) {
                // Nothing may be written into the new project; the run
                // stays resumable against the matched project.
                for (auto& [id, node_run] : run.node_runs) {
                    if (node_run.state == workflow_spec::NodeState::pending ||
                        node_run.state == workflow_spec::NodeState::running) {
                        node_run.state = workflow_spec::NodeState::pending;
                        node_run.error = "project switched during run; re-run pending";
                    }
                }
                run.state = workflow_spec::RunState::interrupted;
                break;
            }
        }
        execute_node(run, node_id, context, token, options);
        try {
            checkpoint(run);
        } catch (const CheckpointFailed&) {
            return;  // run already marked FAILED; stop driving
        }
        notify(run, options);
    }
    finalize(run);
}

// ---------------------------------------------------------- node logic --

void RunEngine::execute_node(workflow_spec::WorkflowRun& run, const std::string& node_id,
                             const RunContext* context, CancelToken& token,
                             const RunOptions& options) {
    const workflow_spec::NodeSpec& node = run.workflow.node(node_id);
    workflow_spec::NodeRun* node_run = run.find_node_run(node_id);
    if (node_run == nullptr) {
        throw std::runtime_error("run '" + run.run_id + "' has no node '" +
                                 node_id + "'");
    }
    const auto info = catalog_.get(node.action_id);
    if (!info.has_value()) {
        // Python registry.get raises KeyError (str == "'<id>'").
        throw std::runtime_error("'" + node.action_id + "'");
    }
    node_run->state = workflow_spec::NodeState::running;
    node_run->attempt += 1;
    node_run->started_at = domain::Json(now());
    node_run->error.reset();

    domain::Json bound;
    try {
        bound = workflow_spec::bind_parameters(node, bind_env(run, context));
    } catch (const workflow_spec::BindingError& exc) {
        finish_node(*node_run, workflow_spec::NodeState::failed, std::string(exc.what()),
                    std::nullopt, "rejected");
        skip_dependents(run, node_id,
                        "upstream " + node_id + " failed: " + exc.what());
        return;
    }
    node_run->parameters = bound;

    const auto schema_problems = workflow_spec::validate_parameters(
        object_schema(info->input_schema), bound);
    if (!schema_problems.empty()) {
        finish_node(*node_run, workflow_spec::NodeState::failed,
                    "bound parameters invalid: " + join(schema_problems, "; "),
                    std::nullopt, "rejected");
        skip_dependents(run, node_id, "upstream " + node_id + " failed");
        return;
    }

    const std::vector<std::string> input_version_ids =
        collect_input_version_ids(run, node);
    // Identity of this execution: ALWAYS recorded on the checkpoint; reuse
    // stays gated on the action's cacheable declaration.
    std::vector<std::string> sorted_ids = input_version_ids;
    std::sort(sorted_ids.begin(), sorted_ids.end());
    const std::string identity = workflow_spec::canonical_hash(domain::Json{
        {"action_id", info->action_id},
        {"action_version", info->version},
        {"parameters", node_run->parameters},
        {"input_version_ids", std::move(sorted_ids)},
    });
    node_run->cache_identity = identity;
    if (info->cacheable && options.use_cache) {
        const auto hit = find_reusable_node(store_, identity, artifact_catalog_,
                                            options.reverify_cache);
        if (hit.has_value()) {
            domain::Json receipt = hit->receipt.has_value()
                                       ? *hit->receipt
                                       : domain::Json(nullptr);
            if (!receipt.is_null()) {
                receipt["from_cache"] = true;
                receipt["node_id"] = node_id;
                receipt["workflow_run_id"] = run.run_id;
            }
            node_run->output_version_ids = hit->output_version_ids;
            node_run->outputs = hit->outputs;
            node_run->receipt = std::move(receipt);
            node_run->finished_at = domain::Json(now());
            node_run->state = workflow_spec::NodeState::succeeded;
            node_run->action_status = "success";
            node_run->from_cache = true;
            if (context != nullptr && context->session != nullptr) {
                context->session->restore_session_pointers(hit->outputs);
            }
            return;
        }
    }

    const double started_at = now();
    while (true) {
        ActionResultView result;
        const auto fn = functions_.find(node.action_id);
        if (fn == functions_.end()) {
            // executor isolation: unknown action -> rejected, never a crash.
            result.status = "rejected";
            result.error = "'" + node.action_id + "'";
        } else {
            try {
                result = fn->second(bound, token);
            } catch (const Cancelled& exc) {
                result.status = "cancelled";
                result.error = std::string("cancelled: ") + exc.what();
            } catch (const std::exception& exc) {
                result.status = "failed";
                result.error = exception_typename(exc) + ": " + exc.what();
            } catch (...) {
                result.status = "failed";
                result.error = "unknown exception";
            }
        }
        if (result.status == "success" || result.status == "degraded") {
            const ExecutionReceipt receipt = build_receipt(
                result,
                BuildReceiptArgs{node_id,
                                 run.run_id,
                                 info->action_id,
                                 info->version,
                                 node.description.empty() ? info->description
                                                          : node.description,
                                 node_run->parameters,
                                 input_version_ids,
                                 domain::Json::object(),  // estimated_resources
                                 std::nullopt,            // resource_category
                                 identity,
                                 /*from_cache=*/false,
                                 node_run->attempt,
                                 started_at},
                env_, clock_);
            // Order matters for crash safety: the payload fields land BEFORE
            // the terminal state, so a torn checkpoint can never claim
            // "succeeded" with empty outputs.
            node_run->output_version_ids = receipt.output_version_ids;
            node_run->outputs = result.outputs;
            node_run->receipt = receipt.to_dict();
            node_run->finished_at = domain::Json(now());
            node_run->state = workflow_spec::NodeState::succeeded;
            node_run->action_status = result.status;
            if (!identity.empty() && cache_run_rail_ != nullptr) {
                // engine.py _register_cache_run (L735): the cacheable node
                // execution rides the catalog provenance rail so reuse is
                // traceable. Best-effort — a rail failure never invalidates
                // the execution (reuse for it stays store-limited).
                try {
                    Json rail_params = Json::object();
                    rail_params["workflow_id"] = run.workflow.workflow_id;
                    rail_params["run_id"] = run.run_id;
                    rail_params["node_id"] = node.node_id;
                    rail_params["cache_identity"] = identity;
                    const std::string rail_run_id =
                        cache_run_rail_->register_cache_run(
                            "workflow.node." + node.action_id,
                            receipt.input_version_ids, rail_params,
                            "workflow-dag/" + run.workflow.schema_version);
                    if (!rail_run_id.empty() &&
                        !receipt.catalog_run_id.has_value()) {
                        (*node_run->receipt)["catalog_run_id"] =
                            rail_run_id;
                    }
                } catch (...) {
                    // logged in Python; this library has no log sink and a
                    // rail failure must not fail the node.
                }
            }
            if (context != nullptr && context->session != nullptr) {
                context->session->merge_session_pointers();
            }
            return;
        }
        if (result.status == "cancelled") {
            finish_node(*node_run, workflow_spec::NodeState::cancelled, result.error,
                        std::nullopt, result.status);
            cancel_pending(run, "cancelled at " + node_id);
            return;
        }
        const bool retryable =
            result.status == "failed" ||
            (result.status == "rejected" && is_resource_shed(result.error));
        if (retryable && node_run->attempt < node.retry.max_attempts) {
            const double backoff = node.retry.backoff_seconds > 0.0
                                       ? node.retry.backoff_seconds
                                       : 0.0;
            if (backoff > 0.0) {
                if (waiter_) {
                    waiter_(token, backoff);
                } else {
                    // Python token.wait: wake early on cancel (best effort).
                    const auto deadline = std::chrono::steady_clock::now() +
                                          std::chrono::duration<double>(backoff);
                    while (!token.is_cancelled() &&
                           std::chrono::steady_clock::now() < deadline) {
                        std::this_thread::sleep_for(std::chrono::milliseconds(2));
                    }
                }
                sync_external_cancel(token, options);
                token.throw_if_cancelled();
            }
            node_run->attempt += 1;
            node_run->error = result.error;
            continue;
        }
        const workflow_spec::NodeState state = result.status == "unavailable"
                                    ? workflow_spec::NodeState::unavailable
                                    : workflow_spec::NodeState::failed;
        finish_node(*node_run, state, result.error, std::nullopt, result.status);
        skip_dependents(run, node_id,
                        "upstream " + node_id + " " + to_string(state));
        return;
    }
}

// ------------------------------------------------------ ready/finality --

std::optional<std::vector<std::string>> RunEngine::ready_batch(workflow_spec::WorkflowRun& run,
                                                               int limit) {
    std::vector<std::string> ready;
    bool pending_left = false;
    for (const auto& node : run.workflow.nodes) {
        workflow_spec::NodeRun* node_run = run.find_node_run(node.node_id);
        if (node_run == nullptr) continue;
        if (node_run->state == workflow_spec::NodeState::pending) {
            pending_left = true;
            bool all_terminal = true;
            for (const auto& dep : node.depends_on) {
                const workflow_spec::NodeRun* dep_run = run.find_node_run(dep);
                if (dep_run == nullptr ||
                    !workflow_spec::is_terminal_node_state(dep_run->state)) {
                    all_terminal = false;
                    break;
                }
            }
            if (!all_terminal) continue;
            bool hard_failure = false;
            bool any_skipped = false;
            for (const auto& dep : node.depends_on) {
                const workflow_spec::NodeRun* dep_run = run.find_node_run(dep);
                if (dep_run->state == workflow_spec::NodeState::failed ||
                    dep_run->state == workflow_spec::NodeState::cancelled ||
                    dep_run->state == workflow_spec::NodeState::unavailable) {
                    hard_failure = true;
                }
                if (dep_run->state == workflow_spec::NodeState::skipped) any_skipped = true;
            }
            if (!node.condition.has_value()) {
                if (hard_failure || any_skipped) {
                    finish_node(*node_run, workflow_spec::NodeState::skipped, std::nullopt,
                                "dependency did not succeed");
                    continue;
                }
            } else {
                // The condition may reference nodes beyond depends_on:
                // evaluation waits until every referenced node is terminal.
                std::vector<std::string> cond_nodes = node.depends_on;
                for (const auto& ref : condition_node_ids(*node.condition)) {
                    cond_nodes.push_back(ref);
                }
                bool cond_ready = true;
                for (const auto& ref : cond_nodes) {
                    const workflow_spec::NodeRun* ref_run = run.find_node_run(ref);
                    if (ref_run != nullptr &&
                        !workflow_spec::is_terminal_node_state(ref_run->state)) {
                        cond_ready = false;
                        break;
                    }
                }
                if (!cond_ready) continue;
                if (!evaluate_condition(*node.condition, run)) {
                    finish_node(*node_run, workflow_spec::NodeState::skipped, std::nullopt,
                                "condition false");
                    continue;
                }
            }
            if (static_cast<int>(ready.size()) < std::max(0, limit)) {
                ready.push_back(node.node_id);
            }
        } else if (node_run->state == workflow_spec::NodeState::running) {
            pending_left = true;
        }
    }
    if (ready.empty() && !pending_left) return std::nullopt;
    return ready;
}

void RunEngine::skip_dependents(workflow_spec::WorkflowRun& run, const std::string& node_id,
                                const std::string& reason) {
    bool changed = true;
    while (changed) {
        changed = false;
        for (const auto& node : run.workflow.nodes) {
            workflow_spec::NodeRun* node_run = run.find_node_run(node.node_id);
            if (node_run == nullptr || node_run->state != workflow_spec::NodeState::pending ||
                node.condition.has_value()) {
                continue;
            }
            bool trigger = false;
            for (const auto& dep : node.depends_on) {
                if (dep == node_id) {
                    trigger = true;
                    break;
                }
                const workflow_spec::NodeRun* dep_run = run.find_node_run(dep);
                if (dep_run != nullptr &&
                    dep_run->state == workflow_spec::NodeState::skipped) {
                    trigger = true;
                    break;
                }
            }
            if (trigger) {
                finish_node(*node_run, workflow_spec::NodeState::skipped, std::nullopt, reason);
                changed = true;
            }
        }
    }
}

void RunEngine::cancel_pending(workflow_spec::WorkflowRun& run, const std::string& reason) {
    for (auto& [id, node_run] : run.node_runs) {
        if (node_run.state == workflow_spec::NodeState::pending ||
            node_run.state == workflow_spec::NodeState::running) {
            finish_node(node_run, workflow_spec::NodeState::cancelled, reason);
        }
    }
}

void RunEngine::finalize(workflow_spec::WorkflowRun& run) {
    bool unfinished = false;
    bool failed = false;
    bool cancelled = false;
    for (const auto& [id, node_run] : run.node_runs) {
        if (node_run.state == workflow_spec::NodeState::running ||
            node_run.state == workflow_spec::NodeState::pending) {
            unfinished = true;  // mid-run abort: resumable
        }
        if (node_run.state == workflow_spec::NodeState::failed ||
            node_run.state == workflow_spec::NodeState::unavailable) {
            failed = true;
        }
        if (node_run.state == workflow_spec::NodeState::cancelled) cancelled = true;
    }
    if (unfinished) {
        run.state = workflow_spec::RunState::interrupted;
        return;
    }
    if (failed) run.state = workflow_spec::RunState::failed;
    else if (cancelled) run.state = workflow_spec::RunState::cancelled;
    else run.state = workflow_spec::RunState::completed;
}

void RunEngine::prepare_interrupted(workflow_spec::WorkflowRun& run) {
    // Crash mapping: RUNNING => PENDING (interrupted); a persisted RUNNING
    // run state resumes instead of doubling.
    if (run.state == workflow_spec::RunState::running) run.state = workflow_spec::RunState::interrupted;
    if (run.state == workflow_spec::RunState::interrupted) {
        for (auto& [id, node_run] : run.node_runs) {
            if (node_run.state == workflow_spec::NodeState::running) {
                node_run.state = workflow_spec::NodeState::pending;
                node_run.error = "interrupted before completion; re-executing";
                node_run.started_at = domain::Json(nullptr);
            }
        }
    }
}

void RunEngine::checkpoint(workflow_spec::WorkflowRun& run) {
    try {
        store_.save(run);
    } catch (const std::exception& exc) {
        // A failing checkpoint ABORTS the run (fail-closed): silently
        // continuing would report COMPLETED while every resume/cache
        // guarantee is void.
        for (auto& [id, node_run] : run.node_runs) {
            if (node_run.state == workflow_spec::NodeState::pending ||
                node_run.state == workflow_spec::NodeState::running) {
                node_run.state = workflow_spec::NodeState::pending;
            }
        }
        run.state = workflow_spec::RunState::failed;
        workflow_spec::NodeRun marker;
        marker.node_id = "__checkpoint__";
        marker.state = workflow_spec::NodeState::failed;
        marker.error = "checkpoint persistence failed: " +
                       python_typename(exc) + ": " + exc.what();
        if (workflow_spec::NodeRun* existing = run.find_node_run("__checkpoint__")) {
            *existing = std::move(marker);
        } else {
            run.node_runs.emplace_back("__checkpoint__", std::move(marker));
        }
        throw CheckpointFailed(exc.what());
    }
}

void RunEngine::finish_node(workflow_spec::NodeRun& node_run, workflow_spec::NodeState state,
                            std::optional<std::string> error,
                            std::optional<std::string> skip_reason,
                            std::optional<std::string> action_status) {
    node_run.state = state;
    node_run.error = std::move(error);
    node_run.skip_reason = std::move(skip_reason);
    if (action_status.has_value()) node_run.action_status = std::move(*action_status);
    node_run.finished_at = domain::Json(now());
}

void RunEngine::notify(const workflow_spec::WorkflowRun& run,
                       const RunOptions& options) const {
    if (!options.on_update) return;
    try {
        options.on_update(run);
    } catch (...) {
        // callback failures never abort the run (Python logs + swallows)
    }
}

}  // namespace pwb::workflow_engine
