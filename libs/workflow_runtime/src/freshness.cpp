// freshness.cpp — C++ port of paleo_workbench/workflow/freshness.py
// (CONV-26). See include/pwb/workflow_runtime/freshness.hpp.

#include <pwb/workflow_runtime/freshness.hpp>

#include "python_compat.hpp"

#include <algorithm>
#include <unordered_set>

namespace pwb::workflow_runtime {

namespace {

// Operations that SHOULD declare inputs; empty input list -> UNKNOWN.
bool lineage_expected(const std::string& operation) {
    static const std::unordered_set<std::string> ops = {
        "factor_map",          "prediction",
        "export",              "horizon_interpretation",
        "map_compile",         "qc",
        "modeling",            // V9 (P1-12): scientific ops that previously
        "factor_fusion",       // escaped lineage expectations — a
        "factor_fusion:confidence",  // lineage-less run read as fresh
        "factor_fusion:variance",    // by default instead of UNKNOWN.
        "constraint_commit",   "map_product_assembly",
        "integrated_interpretation",
    };
    return ops.count(operation) != 0;
}

std::string lower(std::string value) {
    for (char& c : value) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    }
    return value;
}

bool is_hex_checksum(const std::string& checksum) {
    if (checksum.size() != 64) return false;
    for (char c : checksum) {
        const char lc = (c >= 'A' && c <= 'Z')
                            ? static_cast<char>(c - 'A' + 'a')
                            : c;
        if (!((lc >= '0' && lc <= '9') || (lc >= 'a' && lc <= 'f'))) {
            return false;
        }
    }
    return true;
}

Json to_json(const std::optional<std::string>& value) {
    return value ? Json(*value) : Json(nullptr);
}

}  // namespace

const char* freshness_state_value(FreshnessState state) {
    switch (state) {
    case FreshnessState::Fresh: return "FRESH";
    case FreshnessState::Stale: return "STALE";
    case FreshnessState::Unknown: return "UNKNOWN";
    case FreshnessState::Missing: return "MISSING";
    case FreshnessState::Failed: return "FAILED";
    case FreshnessState::Running: return "RUNNING";
    }
    return "?";
}

std::optional<FreshnessState> freshness_state_from_value(
    const std::string& value) {
    if (value == "FRESH") return FreshnessState::Fresh;
    if (value == "STALE") return FreshnessState::Stale;
    if (value == "UNKNOWN") return FreshnessState::Unknown;
    if (value == "MISSING") return FreshnessState::Missing;
    if (value == "FAILED") return FreshnessState::Failed;
    if (value == "RUNNING") return FreshnessState::Running;
    return std::nullopt;
}

const char* freshness_reason_type_value(FreshnessReasonType type) {
    switch (type) {
    case FreshnessReasonType::UpstreamVersionChanged: return "UPSTREAM_VERSION_CHANGED";
    case FreshnessReasonType::ParametersChanged: return "PARAMETERS_CHANGED";
    case FreshnessReasonType::ModelVersionChanged: return "MODEL_VERSION_CHANGED";
    case FreshnessReasonType::GeneratorChanged: return "GENERATOR_CHANGED";
    case FreshnessReasonType::MissingLineage: return "MISSING_LINEAGE";
    case FreshnessReasonType::MissingPayload: return "MISSING_PAYLOAD";
    case FreshnessReasonType::IntegrityModified: return "INTEGRITY_MODIFIED";
    case FreshnessReasonType::RunFailed: return "RUN_FAILED";
    case FreshnessReasonType::RunRunning: return "RUN_RUNNING";
    case FreshnessReasonType::GraphCycle: return "GRAPH_CYCLE";
    case FreshnessReasonType::TransitiveUpstreamStale: return "TRANSITIVE_UPSTREAM_STALE";
    case FreshnessReasonType::Ok: return "OK";
    }
    return "?";
}

Json FreshnessReason::to_dict() const {
    Json out = Json::object();
    out["type"] = freshness_reason_type_value(type);
    out["upstream_version_id"] = to_json(upstream_version_id);
    out["current_version_id"] = to_json(current_version_id);
    out["operation"] = operation;
    out["detail"] = detail;
    out["asset_id"] = to_json(asset_id);
    return out;
}

Json FreshnessReport::to_dict() const {
    Json reason_list = Json::array();
    for (const FreshnessReason& r : reasons) {
        reason_list.push_back(r.to_dict());
    }
    Json out = Json::object();
    out["state"] = freshness_state_value(state);
    out["subject_kind"] = subject_kind;
    out["subject_id"] = subject_id;
    out["reasons"] = std::move(reason_list);
    out["operation"] = operation;
    out["domain_task_id"] = to_json(domain_task_id);
    Json outputs = Json::array();
    for (const auto& id : output_version_ids) outputs.push_back(id);
    out["output_version_ids"] = std::move(outputs);
    Json inputs = Json::array();
    for (const auto& id : input_version_ids) inputs.push_back(id);
    out["input_version_ids"] = std::move(inputs);
    out["integrity"] = to_json(integrity);
    return out;
}

const std::map<std::string, std::string> FRESHNESS_UI_LABELS = {
    {"FRESH", "已完成"},   {"STALE", "需更新"}, {"UNKNOWN", "状态未知"},
    {"MISSING", "缺失"},   {"FAILED", "异常"},  {"RUNNING", "处理中"},
};

const std::map<FreshnessState, std::string> WORKFLOW_STATUS_FOR_FRESHNESS = {
    {FreshnessState::Fresh, "complete"},
    {FreshnessState::Stale, "stale"},
    // UNKNOWN must not render as complete: provenance-less results are not
    // 已完成 (H1) — "warning" maps to the 状态未知 label.
    {FreshnessState::Unknown, "warning"},
    {FreshnessState::Missing, "warning"},
    {FreshnessState::Failed, "failed"},
    {FreshnessState::Running, "running"},
};

FreshnessService::FreshnessService(
    const pwb::workflow_graph::DependencyGraph& graph,
    const CurrentProjectVersionContext& context, VersionLookup versions,
    CatalogSeam seam, bool check_integrity)
    : graph_(graph),
      context_(context),
      versions_(std::move(versions)),
      seam_(std::move(seam)),
      check_integrity_(check_integrity) {
    for (const auto& [vid, run_id] : graph.producing_run()) {
        producing_run_index_[vid] = run_id;
    }
    for (const auto& [run_id, outputs] : graph.run_outputs()) {
        run_outputs_[run_id] = outputs;
    }
}

void FreshnessService::clear_cache() {
    run_cache_.clear();
    version_cache_.clear();
    selected_by_key_.clear();
    selected_indexed_ = false;
}

void FreshnessService::index_selected() const {
    if (selected_indexed_) return;
    for (const auto& sel : context_.selected_version_ids()) {
        const auto prod_it = producing_run_index_.find(sel);
        const DataRunRef* run =
            prod_it != producing_run_index_.end() ? graph_.run(prod_it->second)
                                                  : nullptr;
        if (run == nullptr) continue;
        if (run->domain_task_id) {
            selected_by_key_[SelectedKey{true, *run->domain_task_id}]
                .push_back(sel);
        }
        const Json parent =
            run->parameters.is_object()
                ? pycompat::dict_get(run->parameters, "parent_version_id",
                                     Json(nullptr))
                : Json(nullptr);
        if (parent.is_string()) {
            selected_by_key_[SelectedKey{false, parent.get<std::string>()}]
                .push_back(sel);
        }
    }
    selected_indexed_ = true;
}

bool FreshnessService::input_is_withdrawn(
    const std::string& input_version_id) const {
    // A downstream product must never stay FRESH on top of a withdrawn
    // input (H1): a purged/trashed upstream is a provenance defect.
    VersionRecord rec;
    const auto it = versions_.find(input_version_id);
    if (it != versions_.end()) {
        rec = it->second;
    } else if (seam_.resolve_version) {
        auto resolved = seam_.resolve_version(input_version_id);
        if (!resolved) return true;  // purged / unknown version
        rec = *resolved;
    } else {
        return true;
    }
    return rec.trashed;
}

std::string FreshnessService::checksum_for(const std::string& version_id) const {
    const auto it = versions_.find(version_id);
    if (it != versions_.end()) {
        return it->second.checksum;
    }
    if (seam_.resolve_version) {
        auto resolved = seam_.resolve_version(version_id);
        if (resolved) return resolved->checksum;
    }
    return "";
}

bool FreshnessService::content_identical(const std::string& a,
                                         const std::string& b) const {
    // A byte-identical supersession must not invalidate freshness (#373);
    // unknown checksums keep the mismatch (conservative).
    const std::string first = checksum_for(a);
    if (first.empty()) return false;
    return first == checksum_for(b);
}

std::optional<std::pair<std::string, std::optional<std::string>>>
FreshnessService::selection_mismatch(const std::string& input_version_id) const {
    // Matching rules (first hit wins), with content-identical tolerance:
    // 1. project domain-task product pointer; 2. same-asset current;
    // 3. domain-task supersession among selected tips; 4. parent-link
    // supersession; 5. input selected with no competing tip; 6. unknown.
    std::optional<std::string> domain_id;
    const auto prod_it = producing_run_index_.find(input_version_id);
    if (prod_it != producing_run_index_.end()) {
        const DataRunRef* run = graph_.run(prod_it->second);
        if (run != nullptr) domain_id = run->domain_task_id;
    }

    // 1. Explicit project product tip for this domain task.
    if (domain_id) {
        const auto& tips = context_.current_by_domain_task();
        const auto tip_it = tips.find(*domain_id);
        if (tip_it != tips.end() && tip_it->second != input_version_id) {
            if (content_identical(tip_it->second, input_version_id)) {
                return std::nullopt;
            }
            return std::make_pair(
                tip_it->second,
                graph_.asset_id_for(tip_it->second));
        }
    }

    const std::optional<std::string> asset_id =
        graph_.asset_id_for(input_version_id);
    const std::optional<std::string> current =
        context_.current_for_asset(asset_id);
    if (current && *current != input_version_id) {
        if (content_identical(*current, input_version_id)) {
            return std::nullopt;
        }
        return std::make_pair(*current, asset_id);
    }

    // 3. Domain-task supersession among selected tips only (do not force
    // latest run — the user may intentionally select an older tip).
    if (domain_id) {
        index_selected();
        const auto sel_it =
            selected_by_key_.find(SelectedKey{true, *domain_id});
        if (sel_it != selected_by_key_.end()) {
            for (const std::string& sel : sel_it->second) {
                if (sel == input_version_id) continue;
                if (content_identical(sel, input_version_id)) continue;
                return std::make_pair(sel, graph_.asset_id_for(sel));
            }
        }
    }

    // 4. Parent-link supersession (byte-identical branch-off tolerated, #897).
    if (prod_it != producing_run_index_.end()) {
        index_selected();
        const auto sel_it =
            selected_by_key_.find(SelectedKey{false, input_version_id});
        if (sel_it != selected_by_key_.end()) {
            for (const std::string& sel : sel_it->second) {
                if (content_identical(sel, input_version_id)) continue;
                return std::make_pair(sel, graph_.asset_id_for(sel));
            }
        }
    }

    if (context_.is_current_version(input_version_id)) {
        return std::nullopt;
    }
    return std::nullopt;
}

FreshnessReport FreshnessService::evaluate_run(
    const std::string& run_id) const {
    return evaluate_run_impl(run_id, nullptr);
}

FreshnessReport FreshnessService::evaluate_run_impl(
    const std::string& run_id, const std::set<std::string>* stack) const {
    // Python checks the cache BEFORE the cycle stack — a cached report wins
    // even mid-recursion.
    const auto cached = run_cache_.find(run_id);
    if (cached != run_cache_.end()) {
        return cached->second;
    }
    std::set<std::string> local_stack;
    if (stack == nullptr) {
        stack = &local_stack;
    } else if (stack->count(run_id) != 0) {
        FreshnessReport report;
        report.state = FreshnessState::Unknown;
        report.subject_kind = "run";
        report.subject_id = run_id;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::GraphCycle, std::nullopt, std::nullopt, "",
            "cycle while evaluating run freshness", std::nullopt});
        return report;
    }

    const DataRunRef* run_ptr = graph_.run(run_id);
    // Python falls back to catalog.resolve_run here; the C++ catalog seam
    // exposes version resolution only, so an off-graph run stays
    // MISSING_LINEAGE unless the caller seeded it into the graph snapshots
    // (documented seam divergence — the runtime service always builds the
    // graph from the full repository listing).
    if (run_ptr == nullptr) {
        FreshnessReport report;
        report.state = FreshnessState::Unknown;
        report.subject_kind = "run";
        report.subject_id = run_id;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::MissingLineage, std::nullopt, std::nullopt,
            "", "run not found in catalog", std::nullopt});
        run_cache_[run_id] = report;
        return report;
    }
    const DataRunRef& run = *run_ptr;

    // Run entangled in a provenance cycle -> UNKNOWN (never guessed).
    if (graph_.has_cycle()) {
        for (const std::string& vnode : graph_.cycles()) {
            const auto prod_it = producing_run_index_.find(vnode);
            if (prod_it != producing_run_index_.end() &&
                prod_it->second == run_id) {
                FreshnessReport report;
                report.state = FreshnessState::Unknown;
                report.subject_kind = "run";
                report.subject_id = run_id;
                report.operation = run.operation;
                report.domain_task_id = run.domain_task_id;
                report.input_version_ids = run.input_version_ids;
                report.output_version_ids = run.output_version_ids;
                report.reasons.push_back(FreshnessReason{
                    FreshnessReasonType::GraphCycle, std::nullopt,
                    std::nullopt, run.operation, "provenance cycle detected",
                    std::nullopt});
                run_cache_[run_id] = report;
                return report;
            }
        }
    }

    const std::string status = lower(run.status);
    if (status == "failed" || status == "error" || status == "cancelled" ||
        status == "canceled") {
        FreshnessReport report;
        report.state = FreshnessState::Failed;
        report.subject_kind = "run";
        report.subject_id = run_id;
        report.operation = run.operation;
        report.domain_task_id = run.domain_task_id;
        report.input_version_ids = run.input_version_ids;
        report.output_version_ids = run.output_version_ids;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::RunFailed, std::nullopt, std::nullopt,
            run.operation, "", std::nullopt});
        run_cache_[run_id] = report;
        return report;
    }
    if (status == "running" || status == "pending") {
        FreshnessReport report;
        report.state = FreshnessState::Running;
        report.subject_kind = "run";
        report.subject_id = run_id;
        report.operation = run.operation;
        report.domain_task_id = run.domain_task_id;
        report.input_version_ids = run.input_version_ids;
        report.output_version_ids = run.output_version_ids;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::RunRunning, std::nullopt, std::nullopt,
            run.operation, "", std::nullopt});
        run_cache_[run_id] = report;
        return report;
    }

    const std::vector<std::string>& inputs = run.input_version_ids;
    if (inputs.empty() && lineage_expected(run.operation)) {
        FreshnessReport report;
        report.state = FreshnessState::Unknown;
        report.subject_kind = "run";
        report.subject_id = run_id;
        report.operation = run.operation;
        report.domain_task_id = run.domain_task_id;
        report.input_version_ids = inputs;
        report.output_version_ids = run.output_version_ids;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::MissingLineage, std::nullopt, std::nullopt,
            run.operation, "run has no input_version_ids", std::nullopt});
        run_cache_[run_id] = report;
        return report;
    }

    std::set<std::string> next_stack = *stack;
    next_stack.insert(run_id);

    std::vector<FreshnessReason> reasons;

    // Output assets of this run — parent versions of the same asset are
    // lineage history (branch-from), not external upstream selection.
    std::set<std::string> output_assets;
    for (const std::string& out : run.output_version_ids) {
        const auto asset = graph_.asset_id_for(out);
        if (asset) output_assets.insert(*asset);
    }

    // Direct upstream version selection mismatches.
    for (const std::string& in_vid : inputs) {
        const auto in_asset = graph_.asset_id_for(in_vid);
        if (in_asset && output_assets.count(*in_asset) != 0) {
            continue;
        }
        if (input_is_withdrawn(in_vid)) {
            reasons.push_back(FreshnessReason{
                FreshnessReasonType::MissingLineage, in_vid, std::nullopt,
                run.operation,
                "input " + in_vid + " withdrawn/trashed from catalog",
                std::nullopt});
            continue;
        }
        auto mismatch = selection_mismatch(in_vid);
        if (!mismatch) continue;
        reasons.push_back(FreshnessReason{
            FreshnessReasonType::UpstreamVersionChanged, in_vid,
            mismatch->first, run.operation, mismatch->second,
            "run used " + in_vid + "; current is " + mismatch->first});
    }

    // Transitive: an input produced by a stale run makes this run stale.
    if (reasons.empty()) {
        for (const std::string& in_vid : inputs) {
            const auto prod_it = producing_run_index_.find(in_vid);
            if (prod_it == producing_run_index_.end() ||
                prod_it->second == run_id) {
                continue;
            }
            const FreshnessReport up =
                evaluate_run_impl(prod_it->second, &next_stack);
            if (up.state == FreshnessState::Stale) {
                reasons.push_back(FreshnessReason{
                    FreshnessReasonType::TransitiveUpstreamStale, in_vid,
                    std::nullopt, run.operation,
                    "upstream run " + prod_it->second + " is STALE",
                    std::nullopt});
                break;
            }
            const FreshnessReason* primary = up.primary_reason();
            if (up.state == FreshnessState::Unknown && primary != nullptr &&
                primary->type == FreshnessReasonType::GraphCycle) {
                reasons.push_back(*primary);
                break;
            }
        }
    }

    // Computation identity (parameters / model / generator).
    const std::string identity_key =
        run.domain_task_id ? *run.domain_task_id : run_id;
    const auto expected_it = context_.expected_identity().find(identity_key);
    if (expected_it != context_.expected_identity().end()) {
        const Json& expected = expected_it->second;
        if (expected.contains("generator_version") &&
            expected.at("generator_version").is_string()) {
            const std::string exp_gen =
                expected.at("generator_version").get<std::string>();
            const std::string run_gen = run.generator_version.value_or("");
            if (run_gen != exp_gen) {
                reasons.push_back(FreshnessReason{
                    FreshnessReasonType::GeneratorChanged, std::nullopt,
                    std::nullopt, run.operation,
                    "run generator=" + pycompat::repr_optional_str(
                                           run.generator_version) +
                        " expected=" + pycompat::repr_str(exp_gen),
                    std::nullopt});
            }
        }
        if (expected.contains("input_snapshot_hash") &&
            expected.at("input_snapshot_hash").is_string() &&
            !expected.at("input_snapshot_hash")
                 .get_ref<const std::string&>()
                 .empty()) {
            const std::string exp_snap =
                expected.at("input_snapshot_hash").get<std::string>();
            if (run.input_snapshot_hash.value_or("") != exp_snap) {
                reasons.push_back(FreshnessReason{
                    FreshnessReasonType::ParametersChanged, std::nullopt,
                    std::nullopt, run.operation, "input_snapshot_hash mismatch",
                    std::nullopt});
            }
        }
        const Json exp_params = expected.contains("parameters")
                                    ? expected.at("parameters")
                                    : Json(nullptr);
        if (exp_params.is_object() && !exp_params.empty()) {
            const Json& run_params = run.parameters;
            for (auto exp_it = exp_params.begin();
                 exp_it != exp_params.end(); ++exp_it) {
                const std::string& k = exp_it.key();
                if (context_.display_only_keys().count(k) != 0) continue;
                // Python: only keys PRESENT in the run params compare — a
                // missing key is not a change (no reason).
                if (run_params.is_object() && run_params.contains(k) &&
                    run_params.at(k) != exp_it.value()) {
                    reasons.push_back(FreshnessReason{
                        FreshnessReasonType::ParametersChanged, std::nullopt,
                        std::nullopt, run.operation,
                        "parameter " + pycompat::repr_str(k) + " changed",
                        std::nullopt});
                    break;
                }
            }
        }
        const Json exp_model = expected.contains("model_ref")
                                   ? expected.at("model_ref")
                                   : Json(nullptr);
        if (exp_model.is_object() && !exp_model.empty()) {
            Json run_model = Json(nullptr);
            if (run.parameters.is_object() &&
                run.parameters.contains("model_ref")) {
                run_model = run.parameters.at("model_ref");
            }
            if (!run_model.is_object()) {
                run_model = Json::object();
                if (run.parameters.is_object()) {
                    for (const char* mk : {"model_id", "model_version",
                                           "model_version_id",
                                           "preprocessing_version"}) {
                        if (run.parameters.contains(mk)) {
                            run_model[mk] = run.parameters.at(mk);
                        }
                    }
                }
            }
            for (const char* mk : {"model_version_id", "model_version",
                                   "model_id"}) {
                if (!exp_model.contains(mk)) continue;
                const Json run_value = run_model.contains(mk)
                                           ? run_model.at(mk)
                                           : Json(nullptr);
                if (run_value != exp_model.at(mk)) {
                    reasons.push_back(FreshnessReason{
                        FreshnessReasonType::ModelVersionChanged, std::nullopt,
                        std::nullopt, run.operation,
                        std::string(mk) + " changed", std::nullopt});
                    break;
                }
            }
        }
    }

    // Payload / integrity on outputs (orthogonal; off by default).
    std::optional<std::string> integrity_note;
    if (check_integrity_) {
        for (const std::string& out_vid : run.output_version_ids) {
            std::optional<VersionRecord> ver;
            const auto ver_it = versions_.find(out_vid);
            if (ver_it != versions_.end()) {
                ver = ver_it->second;
            } else if (seam_.resolve_version) {
                ver = seam_.resolve_version(out_vid);
            }
            if (!ver) continue;
            const std::string& path = ver->path;
            if (path.empty()) continue;
            if (seam_.verify_integrity && seam_.file_exists) {
                const bool exists = seam_.file_exists(path);
                const bool real_digest = is_hex_checksum(ver->checksum);
                if (!exists) {
                    if (real_digest) {
                        integrity_note = "missing";
                        reasons.push_back(FreshnessReason{
                            FreshnessReasonType::MissingPayload, std::nullopt,
                            std::nullopt, run.operation,
                            "output " + out_vid + " payload missing",
                            std::nullopt});
                    }
                    continue;
                }
                const auto status_i = seam_.verify_integrity(out_vid);
                if (status_i) {
                    integrity_note = *status_i;
                    if (*status_i == "modified") {
                        reasons.push_back(FreshnessReason{
                            FreshnessReasonType::IntegrityModified,
                            std::nullopt, std::nullopt, run.operation,
                            "output " + out_vid + " integrity modified",
                            std::nullopt});
                    }
                }
            }
        }
    }

    // State precedence (port of the Python decision ladder).
    const auto any_of_type = [&reasons](FreshnessReasonType t) {
        return std::any_of(reasons.begin(), reasons.end(),
                           [t](const FreshnessReason& r) { return r.type == t; });
    };
    FreshnessState state;
    const bool scientific_changed =
        any_of_type(FreshnessReasonType::UpstreamVersionChanged) ||
        any_of_type(FreshnessReasonType::TransitiveUpstreamStale) ||
        any_of_type(FreshnessReasonType::ParametersChanged) ||
        any_of_type(FreshnessReasonType::ModelVersionChanged) ||
        any_of_type(FreshnessReasonType::GeneratorChanged);
    if (any_of_type(FreshnessReasonType::MissingPayload) &&
        !scientific_changed) {
        state = FreshnessState::Missing;
    } else if (any_of_type(FreshnessReasonType::GraphCycle)) {
        state = FreshnessState::Unknown;
    } else if (!reasons.empty() &&
               std::any_of(reasons.begin(), reasons.end(),
                           [](const FreshnessReason& r) {
                               return r.type !=
                                      FreshnessReasonType::IntegrityModified;
                           })) {
        // integrity-modified alone → still FRESH scientifically.
        state = FreshnessState::Stale;
    } else if (!reasons.empty()) {
        state = FreshnessState::Fresh;  // only integrity notes
    } else {
        state = FreshnessState::Fresh;
        reasons.push_back(FreshnessReason{FreshnessReasonType::Ok,
                                          std::nullopt, std::nullopt,
                                          run.operation, "", std::nullopt});
    }

    FreshnessReport report;
    report.state = state;
    report.subject_kind = "run";
    report.subject_id = run_id;
    report.reasons = std::move(reasons);
    report.operation = run.operation;
    report.domain_task_id = run.domain_task_id;
    report.input_version_ids = run.input_version_ids;
    report.output_version_ids = run.output_version_ids;
    report.integrity = integrity_note;
    run_cache_[run_id] = report;
    return report;
}

FreshnessReport FreshnessService::evaluate_version(
    const std::string& version_id) const {
    const auto cached = version_cache_.find(version_id);
    if (cached != version_cache_.end()) return cached->second;
    const auto prod_it = producing_run_index_.find(version_id);
    if (prod_it == producing_run_index_.end()) {
        // RAW / root versions are always fresh relative to themselves.
        FreshnessReport report;
        report.state = FreshnessState::Fresh;
        report.subject_kind = "version";
        report.subject_id = version_id;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::Ok, std::nullopt, std::nullopt, "",
            "root/raw version (no producing run)", std::nullopt});
        version_cache_[version_id] = report;
        return report;
    }
    const FreshnessReport run_report = evaluate_run(prod_it->second);
    FreshnessReport report;
    report.state = run_report.state;
    report.subject_kind = "version";
    report.subject_id = version_id;
    report.reasons = run_report.reasons;
    report.operation = run_report.operation;
    report.domain_task_id = run_report.domain_task_id;
    report.input_version_ids = run_report.input_version_ids;
    report.output_version_ids = run_report.output_version_ids;
    report.integrity = run_report.integrity;
    version_cache_[version_id] = report;
    return report;
}

FreshnessReport FreshnessService::evaluate_domain_task(
    const std::string& domain_task_id) const {
    const DataRunRef* run = graph_.latest_run_for_domain_task(domain_task_id);
    if (run == nullptr) {
        FreshnessReport report;
        report.state = FreshnessState::Unknown;
        report.subject_kind = "domain_task";
        report.subject_id = domain_task_id;
        report.domain_task_id = domain_task_id;
        report.reasons.push_back(FreshnessReason{
            FreshnessReasonType::MissingLineage, std::nullopt, std::nullopt,
            "", "no DataRun linked to domain task", std::nullopt});
        return report;
    }
    const FreshnessReport base = evaluate_run(run->run_id);
    FreshnessReport report;
    report.state = base.state;
    report.subject_kind = "domain_task";
    report.subject_id = domain_task_id;
    report.reasons = base.reasons;
    report.operation = base.operation;
    report.domain_task_id = domain_task_id;
    report.input_version_ids = base.input_version_ids;
    report.output_version_ids = base.output_version_ids;
    report.integrity = base.integrity;
    return report;
}

std::vector<FreshnessReport> FreshnessService::downstream_impact(
    const std::vector<std::string>& version_ids) const {
    std::vector<FreshnessReport> reports;
    for (const DataRunRef* run : graph_.transitive_downstream_runs(version_ids)) {
        reports.push_back(evaluate_run(run->run_id));
    }
    return reports;
}

std::vector<FreshnessReport> FreshnessService::stale_downstream(
    const std::vector<std::string>& version_ids) const {
    std::vector<FreshnessReport> out;
    for (const FreshnessReport& r : downstream_impact(version_ids)) {
        if (r.is_stale()) out.push_back(r);
    }
    return out;
}

std::vector<FreshnessReport> FreshnessService::evaluate_operation(
    const std::string& operation) const {
    std::vector<FreshnessReport> out;
    for (const DataRunRef& run : graph_.run_list()) {
        if (run.operation == operation) {
            out.push_back(evaluate_run(run.run_id));
        }
    }
    return out;
}

std::optional<FreshnessState> FreshnessService::step_freshness(
    const std::string& step_type) const {
    static const std::map<std::string, std::string> op_map = {
        {"factor_map", "factor_map"},     {"prediction", "prediction"},
        {"map_compile", "map_compile"},   {"qc", "qc"},
        {"export", "export"},             {"factor_fusion", "factor_fusion"},
    };
    const auto map_it = op_map.find(step_type);
    if (map_it == op_map.end()) return std::nullopt;
    const std::string& op = map_it->second;

    std::vector<FreshnessReport> reports = evaluate_operation(op);
    // inference_service historically used operation="inference"; treat
    // those runs as prediction until fully migrated.
    if (op == "prediction") {
        for (FreshnessReport& r : evaluate_operation("inference")) {
            reports.push_back(std::move(r));
        }
    }
    if (reports.empty()) return std::nullopt;

    // Superseded runs must not poison the step: within each domain task
    // only the most recent run participates; untasked runs keep their slot.
    std::map<std::string, std::pair<std::string, const FreshnessReport*>>
        latest;
    for (const FreshnessReport& r : reports) {
        const DataRunRef* run = graph_.run(r.subject_id);
        const std::string started = run ? run->started_at.value_or("") : "";
        const std::string key =
            r.domain_task_id ? *r.domain_task_id : "run:" + r.subject_id;
        const auto prev = latest.find(key);
        // Equal timestamps resolve to the later entry in catalog order.
        if (prev == latest.end() || started >= prev->second.first) {
            latest[key] = {started, &r};
        }
    }
    std::vector<const FreshnessReport*> selected;
    for (const auto& [key, entry] : latest) {
        selected.push_back(entry.second);
    }
    const auto any_state = [&selected](FreshnessState s) {
        return std::any_of(selected.begin(), selected.end(),
                           [s](const FreshnessReport* r) {
                               return r->state == s;
                           });
    };
    if (any_state(FreshnessState::Failed)) return FreshnessState::Failed;
    if (any_state(FreshnessState::Running)) return FreshnessState::Running;
    if (any_state(FreshnessState::Stale)) return FreshnessState::Stale;
    if (any_state(FreshnessState::Missing)) return FreshnessState::Missing;
    if (std::all_of(selected.begin(), selected.end(),
                    [](const FreshnessReport* r) {
                        return r->state == FreshnessState::Fresh;
                    })) {
        return FreshnessState::Fresh;
    }
    if (any_state(FreshnessState::Unknown)) return FreshnessState::Unknown;
    return FreshnessState::Fresh;
}

}  // namespace pwb::workflow_runtime
