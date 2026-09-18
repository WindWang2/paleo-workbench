// runtime_service.cpp — WorkflowRuntimeService (CONV-26). See
// include/pwb/workflow_runtime/runtime_service.hpp.

#include <pwb/workflow_runtime/runtime_service.hpp>

#include <pwb/workflow_graph/evidence.hpp>

#include <algorithm>
#include <filesystem>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace pwb::workflow_runtime {

namespace {

Json to_json(const std::optional<std::string>& value) {
    return value ? Json(*value) : Json(nullptr);
}

std::vector<pwb::workflow_graph::DataVersionRef> to_graph_versions(
    const std::vector<VersionRecord>& versions,
    FreshnessService::VersionLookup& lookup) {
    std::vector<pwb::workflow_graph::DataVersionRef> out;
    out.reserve(versions.size());
    for (const VersionRecord& ver : versions) {
        out.push_back(pwb::workflow_graph::DataVersionRef{
            ver.asset_id, ver.version_id, ver.name, ver.producing_run_id});
        lookup[ver.version_id] = ver;
    }
    return out;
}

std::vector<pwb::workflow_graph::DataRunRef> to_graph_runs(
    const std::vector<RunRecord>& runs) {
    std::vector<pwb::workflow_graph::DataRunRef> out;
    out.reserve(runs.size());
    for (const RunRecord& run : runs) {
        out.push_back(pwb::workflow_graph::DataRunRef{
            run.run_id, run.operation, run.input_version_ids,
            run.output_version_ids, run.parameters, run.generator_version,
            run.status, run.started_at, run.finished_at, run.domain_task_id,
            run.input_snapshot_hash});
    }
    return out;
}

}  // namespace

WorkflowRuntimeService::WorkflowRuntimeService(CatalogRepository& repository,
                                               NodeAdapterRegistry& adapters,
                                               Config config)
    : repository_(repository),
      adapters_(adapters),
      config_(std::move(config)),
      admission_(config_.max_concurrency) {}

std::vector<std::string> WorkflowRuntimeService::validate(
    const WorkflowSpec& spec) const {
    // Reuse the engine's frozen validator (CONV-07: unknown action,
    // graph problems, Python message vocabulary) — no second
    // implementation here. The adapter registry fills the NodeRegistry.
    pwb::workflow_engine::NodeRegistry registry;
    for (const std::string& op : adapters_.operations()) {
        const NodeAdapter* adapter = adapters_.find(op);
        registry.register_op(op, adapter->fn);
    }
    return pwb::workflow_engine::validate_spec(spec, registry);
}

WorkflowRun WorkflowRuntimeService::execute(const WorkflowSpec& spec,
                                            const CancelToken& token,
                                            const ExecuteOptions& options) {
    const auto problems = validate(spec);
    if (!problems.empty()) {
        throw pwb::workflow_engine::ValidationError(spec.workflow_id,
                                                    problems);
    }

    pwb::workflow_engine::NodeRegistry registry;
    for (const std::string& op : adapters_.operations()) {
        const NodeAdapter* adapter = adapters_.find(op);
        registry.register_op(op, adapter->fn);
    }

    pwb::workflow_engine::Engine engine(registry);
    WorkflowRun run = engine.run(spec, token);

    // Provenance publish (F): one DataRun per executed node; success also
    // appends an output DataVersion and advances the asset current pointer.
    // The engine already ran; a repository failure must not silently lose
    // the run record — poison the open run "failed" and surface the error.
    for (const auto& node_run : run.node_runs) {
        const auto* node = [&] {
            for (const auto& n : spec.nodes) {
                if (n.node_id == node_run.node_id) return &n;
            }
            return static_cast<const pwb::workflow_engine::NodeSpec*>(
                nullptr);
        }();
        if (node == nullptr) continue;
        if (options.on_progress) {
            options.on_progress(node_run.node_id,
                                pwb::workflow_engine::to_string(
                                    node_run.state));
        }
        if (node_run.state == pwb::workflow_engine::NodeState::pending) {
            continue;  // never reached (cancel pre-flight)
        }

        Json bound_params = node->params;
        const std::vector<std::string> input_versions =
            extract_version_bindings(node->params, &bound_params);

        std::string status;
        if (node_run.state == pwb::workflow_engine::NodeState::succeeded) {
            status = "complete";
        } else if (node_run.state ==
                   pwb::workflow_engine::NodeState::failed) {
            status = "failed";
        } else if (node_run.state ==
                   pwb::workflow_engine::NodeState::cancelled) {
            status = "cancelled";
        } else if (node_run.state ==
                   pwb::workflow_engine::NodeState::skipped) {
            status = "cancelled";  // skipped nodes never ran
        } else {
            continue;
        }

        const std::string operation = options.workflow_name + ":" +
                                      node->op;
        std::string run_id;
        try {
            run_id = repository_.register_run(
                operation, input_versions, bound_params, std::nullopt,
                status, node_run.node_id);
            if (node_run.state ==
                pwb::workflow_engine::NodeState::succeeded) {
                Json payload = node_run.outputs.is_null()
                                   ? Json::object()
                                   : node_run.outputs;
                Json metadata = Json::object();
                metadata["node_id"] = node_run.node_id;
                metadata["workflow_id"] = spec.workflow_id;
                const RegisteredAssetVersion registered =
                    repository_.register_result_asset(
                        options.workflow_name + ":" + node_run.node_id,
                        config_.output_asset_type, "json", Json::object(),
                        payload.dump(), "DERIVED", run_id, metadata);
                repository_.attach_run_output(run_id, registered.version_id);
            }
        } catch (...) {
            if (!run_id.empty()) {
                try {
                    repository_.update_run_status(run_id, "failed");
                } catch (...) {
                }
            }
            throw;
        }
    }
    return run;
}

WorkflowRuntimeService::GraphSnapshot WorkflowRuntimeService::snapshot()
    const {
    GraphSnapshot snap;
    const auto versions = repository_.list_assets();
    std::vector<VersionRecord> all_versions;
    for (const AssetRecord& asset : versions) {
        for (VersionRecord ver : repository_.list_versions(asset.id)) {
            all_versions.push_back(std::move(ver));
        }
    }
    snap.runs = repository_.list_runs();
    snap.graph = pwb::workflow_graph::DependencyGraph::from_listings(
        to_graph_versions(all_versions, snap.versions), to_graph_runs(snap.runs));
    return snap;
}

CurrentProjectVersionContext WorkflowRuntimeService::build_context() const {
    CurrentProjectVersionContext context;
    for (const AssetRecord& asset : repository_.list_assets()) {
        if (asset.current_version_id) {
            context.select(asset.id, *asset.current_version_id,
                           asset.name);
        }
    }
    return context;
}

WorkflowRuntimeService::FreshnessSession
WorkflowRuntimeService::make_freshness_session(
    const CurrentProjectVersionContext& context, bool check_integrity) const {
    auto snap = std::make_shared<GraphSnapshot>(snapshot());
    CatalogSeam seam;
    seam.resolve_version = [repo = &repository_](const std::string& id) {
        try {
            return repo->resolve_version(id);
        } catch (...) {
            return std::optional<VersionRecord>(std::nullopt);
        }
    };
    seam.verify_integrity = [repo = &repository_](const std::string& id) {
        try {
            return repo->verify_integrity(id);
        } catch (...) {
            return std::optional<std::string>(std::nullopt);
        }
    };
    seam.file_exists = [](const std::string& path) {
        std::error_code ec;
        return !path.empty() && std::filesystem::exists(path, ec);
    };
    FreshnessSession session;
    session.snapshot = std::move(snap);
    session.context = context;  // own a copy — caller temporaries die at
                                // the end of the calling expression
    session.service = std::make_unique<FreshnessService>(
        session.snapshot->graph, session.context,
        session.snapshot->versions, seam, check_integrity);
    return session;
}

RecomputePlan WorkflowRuntimeService::plan(
    const CurrentProjectVersionContext& context,
    const RecomputePlanOptions& options) const {
    GraphSnapshot snap = snapshot();
    FreshnessService service(snap.graph, context, snap.versions);
    return build_recompute_plan(service, options);
}

PlanExecutionResult WorkflowRuntimeService::execute_plan(
    RecomputePlan& plan, const CancelToken& token,
    std::optional<int> generation) {
    std::map<std::string, StepHandler> handlers;
    for (const std::string& op : adapters_.operations()) {
        const NodeAdapter* adapter = adapters_.find(op);
        handlers.emplace(op, [this, adapter, &token](
                                 const RecomputeStep& step) {
            AdmissionGate::Lease lease =
                admission_.acquire(token)
                    ? AdmissionGate::Lease(&admission_)
                    : AdmissionGate::Lease();
            if (!lease.holds()) {
                throw std::runtime_error("workflow run cancelled");
            }
            Json params = Json::object();
            params["run_id"] = to_json(step.run_id);
            params["operation"] = step.operation;
            Json inputs = Json::array();
            for (const auto& vid : step.input_version_ids) {
                inputs.push_back(vid);
            }
            params["input_version_ids"] = std::move(inputs);
            const pwb::workflow_engine::NodeResult result =
                adapter->fn(params, token);
            // Recompute provenance: a new completed run over CURRENT
            // inputs, carrying the compute parameters (freshness compares
            // run parameters against expected identities).
            const std::string run_id = repository_.register_run(
                step.operation, step.input_version_ids,
                params, std::nullopt, "complete",
                step.domain_task_id);
            if (!result.outputs.is_null() && !result.outputs.empty()) {
                Json metadata = Json::object();
                metadata["recompute_of"] = to_json(step.run_id);
                const RegisteredAssetVersion registered =
                    repository_.register_result_asset(
                        step.label.empty() ? step.operation : step.label,
                        config_.output_asset_type, "json", Json::object(),
                        result.outputs.dump(), "DERIVED", run_id, metadata);
                repository_.attach_run_output(run_id, registered.version_id);
            }
        });
    }
    PlanExecutor executor(std::move(handlers), generation.value_or(0));
    if (token.is_cancelled()) {
        executor.cancel();
    }
    return executor.execute(plan, generation);
}

FreshnessReport WorkflowRuntimeService::explain_stale(
    const CurrentProjectVersionContext& context,
    const std::string& subject_kind, const std::string& subject_id,
    bool check_integrity) const {
    GraphSnapshot snap = snapshot();
    FreshnessService service(snap.graph, context, snap.versions, {},
                             check_integrity);
    if (subject_kind == "run") return service.evaluate_run(subject_id);
    if (subject_kind == "version") return service.evaluate_version(subject_id);
    if (subject_kind == "domain_task") {
        return service.evaluate_domain_task(subject_id);
    }
    throw std::invalid_argument("unknown subject kind: " + subject_kind);
}

Json WorkflowRuntimeService::list_outputs(
    const std::string& run_id, const CurrentProjectVersionContext& context,
    bool check_integrity) const {
    GraphSnapshot snap = snapshot();
    FreshnessService service(snap.graph, context, snap.versions, {},
                             check_integrity);
    Json out = Json::object();
    out["run_id"] = run_id;
    const auto run = repository_.resolve_run(run_id);
    if (!run) {
        out["found"] = false;
        out["outputs"] = Json::array();
        return out;
    }
    out["found"] = true;
    out["operation"] = run->operation;
    out["run_status"] = run->status;
    Json outputs = Json::array();
    for (const std::string& vid : run->output_version_ids) {
        Json entry = Json::object();
        entry["version_id"] = vid;
        entry["freshness"] =
            service.evaluate_version(vid).to_dict();
        outputs.push_back(std::move(entry));
    }
    out["outputs"] = std::move(outputs);
    return out;
}

Json WorkflowRuntimeService::provenance_trace(
    const std::string& version_id, const CurrentProjectVersionContext& context,
    std::size_t max_nodes) const {
    GraphSnapshot snap = snapshot();
    FreshnessService service(snap.graph, context, snap.versions);

    Json out = Json::object();
    out["version_id"] = version_id;

    const DataRunRef* producing = nullptr;
    for (const auto& [vid, rid] : snap.graph.producing_run()) {
        if (vid == version_id) {
            producing = snap.graph.run(rid);
            break;
        }
    }
    if (producing == nullptr) {
        out["producing_run"] = nullptr;
        out["evidence_selector"] = pwb::workflow_graph::
            format_evidence_selector(
                pwb::workflow_graph::EvidenceKind::CatalogVersion,
                version_id);
        out["downstream_runs"] = Json::array();
        out["inputs"] = Json::array();
        return out;
    }

    Json run_json = Json::object();
    run_json["run_id"] = producing->run_id;
    run_json["operation"] = producing->operation;
    run_json["status"] = producing->status;
    run_json["domain_task_id"] = to_json(producing->domain_task_id);
    out["producing_run"] = std::move(run_json);
    out["evidence_selector"] =
        pwb::workflow_graph::format_evidence_selector(
            pwb::workflow_graph::EvidenceKind::CatalogVersion, version_id);

    Json inputs = Json::array();
    for (const std::string& in_vid : producing->input_version_ids) {
        Json entry = Json::object();
        entry["version_id"] = in_vid;
        const DataRunRef* up = nullptr;
        for (const auto& [vid, rid] : snap.graph.producing_run()) {
            if (vid == in_vid) {
                up = snap.graph.run(rid);
                break;
            }
        }
        if (up != nullptr) {
            Json up_json = Json::object();
            up_json["run_id"] = up->run_id;
            up_json["operation"] = up->operation;
            entry["producing_run"] = std::move(up_json);
        } else {
            entry["producing_run"] = nullptr;
        }
        entry["freshness"] = service.evaluate_version(in_vid).to_dict();
        inputs.push_back(std::move(entry));
    }
    out["inputs"] = std::move(inputs);

    Json downstream = Json::array();
    for (const DataRunRef* run :
         snap.graph.transitive_downstream_runs({version_id}, max_nodes)) {
        Json entry = Json::object();
        entry["run_id"] = run->run_id;
        entry["operation"] = run->operation;
        entry["freshness_state"] =
            freshness_state_value(service.evaluate_run(run->run_id).state);
        downstream.push_back(std::move(entry));
    }
    out["downstream_runs"] = std::move(downstream);
    return out;
}

}  // namespace pwb::workflow_runtime
