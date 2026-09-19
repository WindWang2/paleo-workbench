// map_product.cpp — see include/pwb/closure_workflow/map_product.hpp.
// Line anchors cite paleo_workbench/workflow/map_product.py.

#include <pwb/closure_workflow/map_product.hpp>

#include <pwb/closure_workflow/python_json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_interpretation/compilation.hpp>

#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <utility>

namespace pwb::closure_workflow {

namespace {

using pwb::domain::Sha256;

// ValueError parity (workflow modules raise ValueError; the C++ surfaces
// map it onto std::invalid_argument so callers can catch the family).
[[noreturn]] void refuse(const std::string& message) {
    throw std::invalid_argument(message);
}

// Python repr(<str>) for embedded ids: single quotes.
std::string repr_str(const std::string& value) {
    return "'" + value + "'";
}

// ------------------------------------------------- Json section seams --

const Json kEmptyArray = Json::array();
const Json& array_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return kEmptyArray;
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_array()) return kEmptyArray;
    return *it;
}

const Json kNullJson = Json(nullptr);
const Json& value_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNullJson;
    const auto it = obj.find(key);
    if (it == obj.end()) return kNullJson;
    return *it;
}

std::string string_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return {};
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) return {};
    return it->get<std::string>();
}

std::optional<std::string> nullable_string_field(const Json& obj,
                                                 const char* key) {
    if (!obj.is_object()) return std::nullopt;
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) {
        return std::nullopt;
    }
    return it->get<std::string>();
}

bool bool_field(const Json& obj, const char* key, bool fallback = false) {
    if (!obj.is_object()) return fallback;
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_boolean()) return fallback;
    return it->get<bool>();
}

std::vector<std::string> string_list_field(const Json& obj, const char* key) {
    std::vector<std::string> out;
    for (const Json& item : array_field(obj, key)) {
        if (item.is_string()) out.push_back(item.get<std::string>());
    }
    return out;
}

}  // namespace

// ----------------------------------------------------------- assembly --

std::string MapProductAssembly::scientific_fingerprint(
    const Json& project) const {
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (task.is_object()) tasks[string_field(task, "id")] = &task;
    }
    // Order-sensitive by design: [[task_id, grid_version], ...].
    Json inputs = Json::array();
    for (const std::string& task_id : factor_task_ids) {
        const auto it = tasks.find(task_id);
        std::string grid_version;
        if (it != tasks.end()) {
            grid_version =
                string_field(*it->second, "grid_artifact_version_id");
        }
        Json pair = Json::array();
        pair.push_back(task_id);
        pair.push_back(grid_version);
        inputs.push_back(std::move(pair));
    }
    std::vector<std::string> interpretations;
    interpretations.reserve(interpretation_refs.size());
    for (const std::string& ref : interpretation_refs) {
        interpretations.push_back(ref);
    }
    std::sort(interpretations.begin(), interpretations.end());
    std::vector<std::string> adjustments;
    adjustments.reserve(manual_adjustments.size());
    for (const Json& adjustment : manual_adjustments) {
        adjustments.push_back(python_dumps_sorted(adjustment));
    }
    std::sort(adjustments.begin(), adjustments.end());

    Json payload = Json::object();
    payload["name"] = product_name;
    payload["factors"] = std::move(inputs);
    payload["interpretations"] = interpretations;
    payload["composition"] = composition_ref.value_or("");
    payload["adjustments"] = adjustments;
    payload["fusion_version"] = fusion_version_id;
    payload["integrated_interpretation"] = integrated_interpretation_id;
    payload["input_set"] = input_set_id;
    return Sha256::of_bytes(python_dumps_sorted(payload));
}

Json build_product_manifest(const Json& project,
                            const std::string& product_name,
                            const std::vector<std::string>& factor_task_ids) {
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (task.is_object()) tasks[string_field(task, "id")] = &task;
    }
    Json factor_tasks = Json::array();
    for (const std::string& task_id : factor_task_ids) {
        const auto it = tasks.find(task_id);
        if (it == tasks.end()) continue;  // walrus-None parity
        Json entry = Json::object();
        entry["id"] = task_id;
        entry["name"] = string_field(*it->second, "name");
        entry["grid_version"] =
            string_field(*it->second, "grid_artifact_version_id");
        factor_tasks.push_back(std::move(entry));
    }
    Json interpretation_refs = Json::array();
    for (const Json& ref : array_field(project, "horizon_interpretations")) {
        interpretation_refs.push_back(string_field(ref, "id"));
    }
    Json manifest = Json::object();
    manifest["product_name"] = product_name;
    manifest["factor_tasks"] = std::move(factor_tasks);
    manifest["interpretation_refs"] = std::move(interpretation_refs);
    return manifest;
}

MapProductAssembly assembly_from_workspace(
    const Json& project, const std::string& product_name,
    const std::vector<std::string>& interpretation_refs,
    std::optional<std::string> composition_ref) {
    using pwb::workflow_interpretation::active_input_set;
    using pwb::workflow_interpretation::evidence_view;

    // factor ids from the evidence view's `factor:` entries (R2-F3).
    // Python takes value.split(":")[1] — the field between the FIRST and
    // SECOND colon, not the whole remainder.
    std::vector<std::string> factor_ids;
    for (const auto& [key, value] : evidence_view(project)) {
        const std::string prefix = "factor:";
        if (value.rfind(prefix, 0) != 0) continue;
        const std::size_t second = value.find(':', prefix.size());
        const std::string field =
            second == std::string::npos
                ? value.substr(prefix.size())
                : value.substr(prefix.size(), second - prefix.size());
        factor_ids.push_back(field);  // "factor:" splits to ["factor", ""]
    }
    // V9 lineage refs (R3-F9): latest fusion version (the seed may already
    // have been superseded by a rerun) + the integrated interpretation id.
    std::string fusion_version;
    std::string integrated_id;
    for (const Json& interpretation :
         array_field(project, "integrated_interpretations")) {
        if (!interpretation.is_object()) continue;
        std::string candidate;
        const auto latest = interpretation.find("latest_fusion_version_id");
        if (latest != interpretation.end() && latest->is_string()) {
            candidate = latest->get<std::string>();
        }
        if (candidate.empty()) {
            const auto seed = interpretation.find("fusion_version_id");
            if (seed != interpretation.end() && seed->is_string()) {
                candidate = seed->get<std::string>();
            }
        }
        if (!candidate.empty()) fusion_version = candidate;
        const auto id_it = interpretation.find("interpretation_id");
        if (id_it != interpretation.end() && id_it->is_string() &&
            !id_it->get<std::string>().empty()) {
            integrated_id = id_it->get<std::string>();
        }
    }
    const std::optional<pwb::workflow_interpretation::CompilationInputSet>
        input_set = active_input_set(project);

    MapProductAssembly assembly;
    assembly.product_name = product_name;
    assembly.factor_task_ids = std::move(factor_ids);
    assembly.interpretation_refs = interpretation_refs;
    assembly.composition_ref = std::move(composition_ref);
    assembly.fusion_version_id = fusion_version;
    assembly.integrated_interpretation_id = integrated_id;
    assembly.input_set_id =
        input_set.has_value() ? input_set->id : std::string();
    return assembly;
}

// ----------------------------------------------------------- assemble --

MapProductResult assemble_map_product(Json& project,
                                      const MapProductAssembly& assembly,
                                      const AssembleDeps& deps) {
    if (assembly.factor_task_ids.empty()) {
        refuse("map product needs at least one factor task");
    }
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (task.is_object()) tasks[string_field(task, "id")] = &task;
    }
    struct ResolvedFactor {
        const Json* task;
        std::string grid_version;
    };
    std::vector<ResolvedFactor> resolved;
    for (const std::string& task_id : assembly.factor_task_ids) {
        const auto it = tasks.find(task_id);
        if (it == tasks.end()) {
            refuse("unknown factor task " + repr_str(task_id));
        }
        const Json& task = *it->second;
        const std::string source = string_field(task, "source_kind");
        if (source == "mock" || source == "mixed") {
            refuse("factor task " + repr_str(task_id) + " is " + source +
                   "; synthetic factors cannot enter a product");
        }
        const std::string grid_version =
            string_field(task, "grid_artifact_version_id");
        if (grid_version.empty()) {
            refuse("factor task " + repr_str(task_id) +
                   " has no persisted grid version; re-run its interpolation "
                   "before assembling a product");
        }
        resolved.push_back({&task, grid_version});
    }

    if (deps.catalog == nullptr) {
        refuse("map product assembly requires the data catalog");
    }
    if (deps.payload_json.empty()) {
        refuse("map product assembly needs a staged payload file");
    }

    const std::string fingerprint = assembly.scientific_fingerprint(project);
    // #1219: book the run RUNNING first; complete only after the output
    // version registers (a death between the two saves leaves a failed or
    // running run — never a completed ghost that produced nothing).
    Json factor_snapshot = Json::array();
    for (const ResolvedFactor& factor : resolved) {
        Json entry = Json::object();
        entry["task_id"] = string_field(*factor.task, "id");
        entry["method"] = string_field(*factor.task, "method");
        entry["parameters"] = value_field(*factor.task, "parameters");
        if (!entry["parameters"].is_object()) {
            entry["parameters"] = Json::object();
        }
        entry["grid_version_id"] = factor.grid_version;
        entry["quality_metrics"] =
            value_field(*factor.task, "quality_metrics");
        if (!entry["quality_metrics"].is_object()) {
            entry["quality_metrics"] = Json::object();
        }
        factor_snapshot.push_back(std::move(entry));
    }
    Json parameters = Json::object();
    parameters["product_name"] = assembly.product_name;
    parameters["factor_task_ids"] = assembly.factor_task_ids;
    parameters["interpretation_refs"] = assembly.interpretation_refs;
    parameters["composition_ref"] =
        assembly.composition_ref.has_value()
            ? Json(*assembly.composition_ref)
            : Json(nullptr);
    parameters["manual_adjustments"] = assembly.manual_adjustments;
    parameters["notes"] = assembly.notes;
    parameters["scientific_fingerprint"] = fingerprint;
    parameters["fusion_version_id"] = assembly.fusion_version_id;
    parameters["integrated_interpretation_id"] =
        assembly.integrated_interpretation_id;
    parameters["input_set_id"] = assembly.input_set_id;
    // Assembly-time per-factor truth: what the product ACTUALLY consumed;
    // comparisons must read this, not the live tasks.
    parameters["factor_snapshot"] = std::move(factor_snapshot);

    std::vector<std::string> input_version_ids;
    input_version_ids.reserve(resolved.size());
    for (const ResolvedFactor& factor : resolved) {
        input_version_ids.push_back(factor.grid_version);
    }

    const std::string run_id = deps.catalog->register_run(
        "map_product_assembly", input_version_ids, parameters,
        std::string(kMapProductGeneratorId), "running");
    std::string output_version_id;
    try {
        Json asset_metadata = Json::object();
        asset_metadata["product_name"] = assembly.product_name;
        asset_metadata["factor_task_ids"] = assembly.factor_task_ids;
        asset_metadata["scientific_fingerprint"] = fingerprint;
        Json version_metadata = Json::object();
        version_metadata["product_name"] = assembly.product_name;
        version_metadata["generator"] = std::string(kMapProductGeneratorId);
        const pwb::workflow_runtime::RegisteredAssetVersion version =
            deps.catalog->register_result_asset(
                assembly.product_name, "map_product", deps.payload_format,
                asset_metadata, deps.payload_json, "output", run_id,
                version_metadata);
        output_version_id = version.version_id;
    } catch (...) {
        // Output registration failed: the run must NOT stay completed (or
        // running forever) — fail it with the error preserved
        // (extra_parameters parity, map_product.py L277-284).
        try {
            deps.catalog->update_run_status(run_id, "failed",
                                            Json{{"error",
                                                  "output registration failed"}});
        } catch (...) {
        }
        throw;
    }
    deps.catalog->update_run_status(run_id, "complete");

    // MapProductRecord (project/models.py L532) in declaration order.
    Json record = Json::object();
    record["id"] = deps.clock.make_id ? deps.clock.make_id("mapprod")
                                      : pwb::project::default_make_id("mapprod");
    record["product_name"] = assembly.product_name;
    record["factor_task_ids"] = assembly.factor_task_ids;
    record["interpretation_refs"] = assembly.interpretation_refs;
    record["composition_ref"] =
        assembly.composition_ref.has_value()
            ? Json(*assembly.composition_ref)
            : Json(nullptr);
    record["notes"] = assembly.notes;
    record["output_version_id"] = output_version_id;
    record["run_id"] = run_id;
    record["scientific_fingerprint"] = fingerprint;
    record["created_at"] = deps.clock.now_iso
                               ? deps.clock.now_iso()
                               : pwb::project::default_now_iso();
    record["status"] = std::string(kProductStatusFinal);
    record["frozen"] = false;
    record["superseded_by"] = Json(nullptr);
    record["cloned_from"] = Json(nullptr);
    record["lifecycle"] = std::string(kLifecycleDraft);
    record["product_qa"] = Json::object();
    record["manual_adjustments"] = assembly.manual_adjustments;
    record["fusion_version_id"] = assembly.fusion_version_id;
    record["integrated_interpretation_id"] =
        assembly.integrated_interpretation_id;
    record["input_set_id"] = assembly.input_set_id;
    if (!project.is_object()) project = Json::object();
    if (!project.contains("map_products") ||
        !project["map_products"].is_array()) {
        project["map_products"] = Json::array();
    }
    project["map_products"].push_back(record);

    MapProductResult result;
    result.product_name = assembly.product_name;
    result.record_id = record["id"].get<std::string>();
    result.output_version_id = output_version_id;
    result.run_id = run_id;
    result.scientific_fingerprint = fingerprint;
    return result;
}

// ------------------------------------------------------------ records --

std::optional<Json> find_map_product(const Json& project,
                                     const std::string& record_id) {
    for (const Json& record : array_field(project, "map_products")) {
        if (!record.is_object()) continue;
        if (string_field(record, "id") == record_id) return record;
    }
    return std::nullopt;
}

std::string effective_lifecycle(const Json& record) {
    // Explicit field first; legacy records reconcile on read (读取时和解).
    const std::string explicit_lifecycle = string_field(record, "lifecycle");
    const bool frozen = bool_field(record, "frozen");
    const std::string status = string_field(record, "status");
    if (explicit_lifecycle == kLifecycleDraft) {
        // draft 也可能与 legacy frozen 标志共存（旧 freeze 只翻布尔）。
        if (frozen) return std::string(kLifecycleFrozen);
        if (status == kProductStatusSuperseded) {
            return std::string(kLifecycleSuperseded);
        }
        return std::string(kLifecycleDraft);
    }
    if (explicit_lifecycle == kLifecycleReviewed ||
        explicit_lifecycle == kLifecycleFrozen ||
        explicit_lifecycle == kLifecyclePublished ||
        explicit_lifecycle == kLifecycleSuperseded) {
        return explicit_lifecycle;
    }
    if (frozen) return std::string(kLifecycleFrozen);
    if (status == kProductStatusSuperseded) {
        return std::string(kLifecycleSuperseded);
    }
    return std::string(kLifecycleDraft);
}

bool record_is_frozen(const Json& record) {
    if (bool_field(record, "frozen")) return true;
    const std::string lifecycle = effective_lifecycle(record);
    return lifecycle == kLifecycleFrozen || lifecycle == kLifecyclePublished;
}

Json product_staleness(const Json& record, const Json& project) {
    // V9 (R1-F5): rebuild the CURRENT assembly carrying the V9 refs
    // persisted on the record — otherwise every V9-enriched product reads
    // stale forever and publish is bricked.
    MapProductAssembly current;
    current.product_name = string_field(record, "product_name");
    current.factor_task_ids = string_list_field(record, "factor_task_ids");
    current.interpretation_refs =
        string_list_field(record, "interpretation_refs");
    current.composition_ref = nullable_string_field(record, "composition_ref");
    current.manual_adjustments = value_field(record, "manual_adjustments");
    if (!current.manual_adjustments.is_array()) {
        current.manual_adjustments = Json::array();
    }
    current.fusion_version_id = string_field(record, "fusion_version_id");
    current.integrated_interpretation_id =
        string_field(record, "integrated_interpretation_id");
    current.input_set_id = string_field(record, "input_set_id");
    const std::string current_fingerprint =
        current.scientific_fingerprint(project);
    const std::string record_fingerprint =
        string_field(record, "scientific_fingerprint");
    const bool stale = current_fingerprint != record_fingerprint;
    Json report = Json::object();
    report["stale"] = stale;
    report["record_fingerprint"] = record_fingerprint;
    report["current_fingerprint"] = current_fingerprint;
    report["reason"] =
        stale ? "inputs changed since assembly" : "inputs unchanged";
    return report;
}

// ------------------------------------------------------------- compare --

namespace {

// Assembly-time factor truth from the record's run, when resolvable
// (_run_factor_snapshot L732); nullopt == catalog missing / run unavailable.
std::optional<Json> run_factor_snapshot(const Json& record,
                                        CatalogRepository* catalog) {
    if (catalog == nullptr) return std::nullopt;
    const std::string run_id = string_field(record, "run_id");
    if (run_id.empty()) return std::nullopt;
    const std::optional<pwb::workflow_runtime::RunRecord> run =
        catalog->resolve_run(run_id);
    if (!run.has_value()) return std::nullopt;
    const auto snapshot_it = run->parameters.find("factor_snapshot");
    if (snapshot_it == run->parameters.end() || !snapshot_it->is_array()) {
        return std::nullopt;
    }
    Json view = Json::object();
    for (const Json& entry : *snapshot_it) {
        if (!entry.is_object()) continue;
        const auto task_id = entry.find("task_id");
        if (task_id == entry.end() || task_id->is_null()) continue;
        Json projected = Json::object();
        projected["method"] = value_field(entry, "method");
        projected["parameters"] = value_field(entry, "parameters");
        projected["grid_version_id"] =
            value_field(entry, "grid_version_id");
        projected["quality_metrics"] = value_field(entry, "quality_metrics");
        view[task_id->is_string() ? task_id->get<std::string>()
                                  : task_id->dump()] =
            std::move(projected);
    }
    return view;
}

// No catalog / run unavailable: fall back to the LIVE task state and say
// so — the comparison then covers structure only (_factor_views L754).
Json live_factor_views(const Json& record, const Json& project) {
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (task.is_object()) tasks[string_field(task, "id")] = &task;
    }
    Json view = Json::object();
    for (const std::string& task_id :
         string_list_field(record, "factor_task_ids")) {
        const auto it = tasks.find(task_id);
        Json projected = Json::object();
        if (it != tasks.end()) {
            const Json& task = *it->second;
            projected["method"] = value_field(task, "method");
            projected["parameters"] = value_field(task, "parameters");
            projected["grid_version_id"] =
                value_field(task, "grid_artifact_version_id");
            projected["quality_metrics"] =
                value_field(task, "quality_metrics");
        } else {
            projected["method"] = kNullJson;
            projected["parameters"] = kNullJson;
            projected["grid_version_id"] = kNullJson;
            projected["quality_metrics"] = kNullJson;
        }
        view[task_id] = std::move(projected);
    }
    return view;
}

std::string factor_source(const Json& record, CatalogRepository* catalog) {
    return run_factor_snapshot(record, catalog).has_value() ? "run_snapshot"
                                                            : "live_fallback";
}

std::optional<std::string> output_hash(const Json& record,
                                       CatalogRepository* catalog) {
    if (catalog == nullptr) return std::nullopt;
    const std::string version_id = string_field(record, "output_version_id");
    if (version_id.empty()) return std::nullopt;
    const std::optional<pwb::workflow_runtime::VersionRecord> version =
        catalog->resolve_version(version_id);
    if (!version.has_value()) return std::nullopt;
    if (version->checksum.empty()) return std::nullopt;
    return version->checksum;
}

}  // namespace

Json compare_map_products(const Json& a, const Json& b, const Json& project,
                          CatalogRepository* catalog) {
    const std::optional<Json> snapshot_a = run_factor_snapshot(a, catalog);
    const std::optional<Json> snapshot_b = run_factor_snapshot(b, catalog);
    const Json factors_a = snapshot_a.has_value() ? *snapshot_a
                                                  : live_factor_views(a, project);
    const Json factors_b = snapshot_b.has_value() ? *snapshot_b
                                                  : live_factor_views(b, project);

    std::set<std::string> keys_a;
    std::set<std::string> keys_b;
    for (auto it = factors_a.begin(); it != factors_a.end(); ++it) {
        keys_a.insert(it.key());
    }
    for (auto it = factors_b.begin(); it != factors_b.end(); ++it) {
        keys_b.insert(it.key());
    }
    std::vector<std::string> only_in_a;
    std::vector<std::string> only_in_b;
    std::vector<std::string> common;
    std::set_difference(keys_a.begin(), keys_a.end(), keys_b.begin(),
                        keys_b.end(), std::back_inserter(only_in_a));
    std::set_difference(keys_b.begin(), keys_b.end(), keys_a.begin(),
                        keys_a.end(), std::back_inserter(only_in_b));
    std::set_intersection(keys_a.begin(), keys_a.end(), keys_b.begin(),
                          keys_b.end(), std::back_inserter(common));

    Json changed = Json::object();
    for (const std::string& task_id : common) {
        const Json& fa = factors_a.at(task_id);
        const Json& fb = factors_b.at(task_id);
        Json differences = Json::object();
        for (const char* key :
             {"method", "parameters", "grid_version_id", "quality_metrics"}) {
            const Json& va = value_field(fa, key);
            const Json& vb = value_field(fb, key);
            if (va != vb) {
                Json pair = Json::object();
                pair["a"] = va;
                pair["b"] = vb;
                differences[key] = std::move(pair);
            }
        }
        if (!differences.empty()) {
            changed[task_id] = std::move(differences);
        }
    }

    Json factor_diff = Json::object();
    factor_diff["only_in_a"] = only_in_a;
    factor_diff["only_in_b"] = only_in_b;
    factor_diff["changed"] = std::move(changed);

    std::vector<std::string> refs_a =
        string_list_field(a, "interpretation_refs");
    std::vector<std::string> refs_b =
        string_list_field(b, "interpretation_refs");
    std::set<std::string> ref_set_a(refs_a.begin(), refs_a.end());
    std::set<std::string> ref_set_b(refs_b.begin(), refs_b.end());
    std::vector<std::string> refs_only_a;
    std::vector<std::string> refs_only_b;
    std::set_difference(ref_set_a.begin(), ref_set_a.end(), ref_set_b.begin(),
                        ref_set_b.end(), std::back_inserter(refs_only_a));
    std::set_difference(ref_set_b.begin(), ref_set_b.end(), ref_set_a.begin(),
                        ref_set_a.end(), std::back_inserter(refs_only_b));

    Json interpretation_diff = Json::object();
    interpretation_diff["only_in_a"] = refs_only_a;
    interpretation_diff["only_in_b"] = refs_only_b;

    const std::optional<std::string> hash_a = output_hash(a, catalog);
    const std::optional<std::string> hash_b = output_hash(b, catalog);
    Json output = Json::object();
    output["version_a"] = string_field(a, "output_version_id");
    output["version_b"] = string_field(b, "output_version_id");
    output["checksum_a"] = hash_a.has_value() ? Json(*hash_a) : Json(nullptr);
    output["checksum_b"] = hash_b.has_value() ? Json(*hash_b) : Json(nullptr);

    Json result = Json::object();
    result["factor_source"] = Json::object();
    result["factor_source"]["a"] = factor_source(a, catalog);
    result["factor_source"]["b"] = factor_source(b, catalog);
    result["scientific_fingerprint_equal"] =
        string_field(a, "scientific_fingerprint") ==
        string_field(b, "scientific_fingerprint");
    result["fingerprint_a"] = string_field(a, "scientific_fingerprint");
    result["fingerprint_b"] = string_field(b, "scientific_fingerprint");
    result["factor_tasks"] = std::move(factor_diff);
    result["interpretation_refs"] = std::move(interpretation_diff);
    result["composition_ref_equal"] =
        nullable_string_field(a, "composition_ref") ==
        nullable_string_field(b, "composition_ref");
    result["output"] = std::move(output);
    return result;
}

// ----------------------------------------------------------------- QA --

Json product_qa(Json& record, const Json& project,
                CatalogRepository* catalog) {
    Json findings = Json::array();
    auto add = [&](const char* severity, const char* stage,
                   const std::string& message) {
        Json finding = Json::object();
        finding["severity"] = severity;
        finding["stage"] = stage;
        finding["message"] = message;
        findings.push_back(std::move(finding));
    };

    // 输入完备性。
    const std::vector<std::string> factor_task_ids =
        string_list_field(record, "factor_task_ids");
    if (factor_task_ids.empty()) {
        add(kQaError, "input", "产品未引用任何单因素任务");
    }
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (task.is_object()) tasks[string_field(task, "id")] = &task;
    }
    for (const std::string& task_id : factor_task_ids) {
        const auto it = tasks.find(task_id);
        if (it == tasks.end()) {
            add(kQaError, "input",
                "单因素任务 " + task_id + " 不存在（输入缺失）");
            continue;
        }
        const Json& task = *it->second;
        const std::string grid_version =
            string_field(task, "grid_artifact_version_id");
        if (grid_version.empty()) {
            add(kQaError, "input",
                "单因素 " + string_field(task, "name") + "：结果无登记版本");
        } else if (catalog != nullptr) {
            std::optional<pwb::workflow_runtime::VersionRecord> resolved;
            try {
                resolved = catalog->resolve_version(grid_version);
            } catch (...) {  // 解析失败按不可解析处理
                resolved = std::nullopt;
            }
            if (!resolved.has_value()) {
                // goal §30 BLOCKER: unresolvable product input — the
                // product is scientifically dead; publish cannot be
                // exempted via accept_warnings.
                add(kQaBlocker, "input",
                    "单因素 " + string_field(task, "name") + "：结果版本 " +
                        grid_version +
                        " 在目录中不可解析（载荷缺失/被清理）——产品输入已"
                        "失效");
            }
        }
        const Json& quality_metrics = value_field(task, "quality_metrics");
        const Json& parameters = value_field(task, "parameters");
        std::string unit;
        const Json& unit_from_qm = value_field(quality_metrics, "unit");
        if (unit_from_qm.is_string()) unit = unit_from_qm.get<std::string>();
        if (unit.empty()) {
            const Json& unit_from_params = value_field(parameters, "unit");
            if (unit_from_params.is_string()) {
                unit = unit_from_params.get<std::string>();
            }
        }
        if (unit.find_first_not_of(" \t\r\n") == std::string::npos) {
            add(kQaWarning, "input",
                "单因素 " + string_field(task, "name") + "：单位未声明");
        }
        if (value_field(quality_metrics, "variance_min").is_null()) {
            add(kQaWarning, "result",
                "单因素 " + string_field(task, "name") + "：无不确定度面");
        }
        const Json& constraint_diag =
            value_field(parameters, "constraint_diagnostics");
        const Json& unsupported =
            value_field(constraint_diag, "unsupported_constraints");
        if (!unsupported.is_null() &&
            (!unsupported.is_array() || !unsupported.empty())) {
            add(kQaWarning, "input",
                "单因素 " + string_field(task, "name") + "：约束 " +
                    (unsupported.is_string()
                         ? unsupported.get<std::string>()
                         : unsupported.dump()) +
                    " 被方法忽略");
        }
        const std::string source_kind = string_field(task, "source_kind");
        if (source_kind == "mock" || source_kind == "mixed") {
            add(kQaWarning, "input",
                "单因素 " + string_field(task, "name") + "：含模拟数据");
        }
    }

    // 统一 staleness verdict（V9：产品域）— the mapproduct slice of
    // MappingDependencyService._evaluate_map_products (dependencies.py
    // L436-446), evaluated straight from the catalog authority: no output
    // version / no resolvable run inputs → UNKNOWN「产品未登记完整溯源
    // run」; resolvable inputs compared against the catalog current
    // pointers → 版本过期 ERROR. (The full workspace dependency graph is
    // the mapping-workspace line's domain — this slice covers the product
    // QA question without it; no fabricated pass either way.)
    {
        const std::string run_id = string_field(record, "run_id");
        const std::string output_version =
            string_field(record, "output_version_id");
        std::optional<pwb::workflow_runtime::RunRecord> run;
        bool lineage_resolvable = false;
        std::string stale_detail;
        if (catalog != nullptr && !output_version.empty() && !run_id.empty()) {
            run = catalog->resolve_run(run_id);
            if (run.has_value() && !run->input_version_ids.empty()) {
                lineage_resolvable = true;
                for (const std::string& in_vid : run->input_version_ids) {
                    const auto ver = catalog->resolve_version(in_vid);
                    if (!ver.has_value()) {
                        lineage_resolvable = false;  // unresolvable input
                        stale_detail.clear();
                        break;
                    }
                    const auto asset = catalog->resolve_asset(ver->asset_id);
                    if (asset.has_value() &&
                        asset->current_version_id.has_value() &&
                        *asset->current_version_id != in_vid) {
                        stale_detail = "run used " + in_vid + "; current is " +
                                       *asset->current_version_id;
                        break;
                    }
                }
            }
        }
        if (!lineage_resolvable) {
            add(kQaWarning, "input",
                "产品新鲜度未知（产品未登记完整溯源 run）——不可证明为最新");
        } else if (!stale_detail.empty()) {
            add(kQaError, "input",
                "产品版本过期：" + stale_detail + "——上游已变化");
        }
    }

    // 溯源完备性。
    if (string_field(record, "run_id").empty()) {
        add(kQaError, "provenance", "产品无溯源 run（组装未登记）");
    }
    if (string_field(record, "output_version_id").empty()) {
        add(kQaError, "provenance", "产品无输出版本");
    }

    int info_count = 0;
    int warning_count = 0;
    int error_count = 0;
    int blocker_count = 0;
    for (const Json& finding : findings) {
        const std::string severity = finding["severity"].get<std::string>();
        if (severity == kQaInfo) {
            ++info_count;
        } else if (severity == kQaWarning) {
            ++warning_count;
        } else if (severity == kQaError) {
            ++error_count;
        } else if (severity == kQaBlocker) {
            ++blocker_count;
        }
    }
    Json counts = Json::object();
    counts[kQaInfo] = info_count;
    counts[kQaWarning] = warning_count;
    counts[kQaError] = error_count;
    counts[kQaBlocker] = blocker_count;

    Json report = Json::object();
    report["schema"] = 1;
    report["product_id"] = string_field(record, "id");
    report["findings"] = findings;
    report["counts"] = counts;
    report["has_blocker"] = blocker_count > 0;
    report["has_error"] = error_count > 0;
    report["status"] = blocker_count > 0   ? "blocked"
                       : error_count > 0   ? "error"
                       : warning_count > 0 ? "warning"
                                           : "passed";
    record["product_qa"] = report;
    return report;
}

Json review_map_product(Json& record, const Json& project,
                        CatalogRepository* catalog) {
    const std::string lifecycle = effective_lifecycle(record);
    if (lifecycle != kLifecycleDraft) {
        refuse("product " + string_field(record, "id") + " lifecycle is " +
               lifecycle + "; only draft products can be reviewed");
    }
    Json report = product_qa(record, project, catalog);
    const bool has_error = report["has_error"].get<bool>();
    const bool has_blocker = report["has_blocker"].get<bool>();
    if (has_error || has_blocker) {
        std::string messages;
        for (const Json& finding : report["findings"]) {
            const std::string severity =
                finding["severity"].get<std::string>();
            if (severity == kQaError || severity == kQaBlocker) {
                if (!messages.empty()) messages += "; ";
                messages += finding["message"].get<std::string>();
            }
        }
        refuse("product " + string_field(record, "id") +
               " cannot pass review — QA status " +
               report["status"].get<std::string>() + ": " + messages);
    }
    record["lifecycle"] = std::string(kLifecycleReviewed);
    return report;
}

Json clone_map_product(const Json& record, Json& project,
                       pwb::project::ModelClock clock,
                       std::optional<std::string> new_name,
                       std::optional<std::string> notes) {
    if (record_is_frozen(record)) {
        refuse("product " + string_field(record, "id") +
               " is frozen; unfreeze before cloning");
    }
    if (string_field(record, "status") == kProductStatusSuperseded) {
        refuse("product " + string_field(record, "id") +
               " is superseded; clone its successor instead");
    }
    Json clone = Json::object();
    clone["id"] = clock.make_id
                      ? clock.make_id("mapprod")
                      : pwb::project::default_make_id("mapprod");
    clone["product_name"] =
        new_name.has_value() ? *new_name
                             : string_field(record, "product_name") + " (副本)";
    clone["factor_task_ids"] = value_field(record, "factor_task_ids");
    if (!clone["factor_task_ids"].is_array()) {
        clone["factor_task_ids"] = Json::array();
    }
    clone["interpretation_refs"] = value_field(record, "interpretation_refs");
    if (!clone["interpretation_refs"].is_array()) {
        clone["interpretation_refs"] = Json::array();
    }
    clone["composition_ref"] = value_field(record, "composition_ref");
    clone["notes"] = notes.has_value() ? *notes : string_field(record, "notes");
    clone["output_version_id"] = string_field(record, "output_version_id");
    clone["run_id"] = string_field(record, "run_id");
    clone["scientific_fingerprint"] =
        string_field(record, "scientific_fingerprint");
    clone["created_at"] =
        clock.now_iso ? clock.now_iso() : pwb::project::default_now_iso();
    clone["status"] = std::string(kProductStatusFinal);
    clone["frozen"] = false;
    clone["superseded_by"] = Json(nullptr);
    clone["cloned_from"] = string_field(record, "id");
    clone["lifecycle"] = std::string(kLifecycleDraft);
    clone["product_qa"] = Json::object();
    clone["manual_adjustments"] = value_field(record, "manual_adjustments");
    if (!clone["manual_adjustments"].is_array()) {
        clone["manual_adjustments"] = Json::array();
    }
    clone["fusion_version_id"] = string_field(record, "fusion_version_id");
    clone["integrated_interpretation_id"] =
        string_field(record, "integrated_interpretation_id");
    clone["input_set_id"] = string_field(record, "input_set_id");
    if (!project.is_object()) project = Json::object();
    if (!project.contains("map_products") ||
        !project["map_products"].is_array()) {
        project["map_products"] = Json::array();
    }
    project["map_products"].push_back(clone);
    return clone;
}

MapProductResult rerun_map_product(Json& project, const Json& record,
                                   const AssembleDeps& deps,
                                   std::optional<MapProductAssembly> assembly) {
    if (string_field(record, "status") == kProductStatusSuperseded) {
        refuse("product " + string_field(record, "id") +
               " is already superseded; rerun its successor instead");
    }
    if (record_is_frozen(record)) {
        refuse("product " + string_field(record, "id") +
               " is frozen; unfreeze before rerunning");
    }
    MapProductAssembly effective;
    if (assembly.has_value()) {
        effective = std::move(*assembly);
    } else {
        effective.product_name = string_field(record, "product_name");
        effective.factor_task_ids = string_list_field(record, "factor_task_ids");
        effective.interpretation_refs =
            string_list_field(record, "interpretation_refs");
        effective.composition_ref =
            nullable_string_field(record, "composition_ref");
        effective.notes = string_field(record, "notes");
        effective.manual_adjustments =
            value_field(record, "manual_adjustments");
        if (!effective.manual_adjustments.is_array()) {
            effective.manual_adjustments = Json::array();
        }
    }
    MapProductResult result = assemble_map_product(project, effective, deps);
    std::optional<Json> successor = find_map_product(project, result.record_id);
    if (!successor.has_value()) {
        // assemble just appended it; never expected.
        throw std::runtime_error(
            "assemble_map_product did not register the successor");
    }
    {
        // Python `successor.cloned_from or record.id` — null or "" links.
        Json& mutable_successor = project["map_products"].back();
        if (string_field(mutable_successor, "id") == result.record_id) {
            const std::string cloned_from =
                string_field(mutable_successor, "cloned_from");
            if (cloned_from.empty()) {
                mutable_successor["cloned_from"] = string_field(record, "id");
            }
        }
    }
    // Supersede the original (the first successor wins).
    const std::string original_id = string_field(record, "id");
    for (Json& entry : project["map_products"]) {
        if (entry.is_object() && string_field(entry, "id") == original_id) {
            entry["status"] = std::string(kProductStatusSuperseded);
            entry["superseded_by"] = result.record_id;
            entry["lifecycle"] = std::string(kLifecycleSuperseded);
            break;
        }
    }
    result.superseded_record_id = original_id;
    return result;
}

void freeze_map_product(Json& record, bool frozen) {
    const std::string lifecycle = effective_lifecycle(record);
    const std::string explicit_lifecycle = string_field(record, "lifecycle");
    if (frozen) {
        if (lifecycle == kLifecyclePublished) {
            refuse("product " + string_field(record, "id") +
                   " is published — published products are immutable; "
                   "supersede instead");
        }
        if (lifecycle == kLifecycleDraft && !bool_field(record, "frozen")) {
            refuse("product " + string_field(record, "id") +
                   " is draft — review before freezing (goal §31 ladder: "
                   "review → freeze → publish)");
        }
        record["frozen"] = true;
        record["lifecycle"] = std::string(kLifecycleFrozen);
    } else {
        if (lifecycle == kLifecyclePublished ||
            explicit_lifecycle == kLifecyclePublished) {
            refuse("product " + string_field(record, "id") +
                   " is published — published products are immutable; "
                   "supersede instead of unfreezing");
        }
        record["frozen"] = false;
        record["lifecycle"] = std::string(kLifecycleDraft);
    }
}

void supersede_map_product(Json& record, const Json& successor) {
    if (string_field(record, "id") == string_field(successor, "id")) {
        refuse("a product cannot supersede itself");
    }
    if (record_is_frozen(record)) {
        refuse("product " + string_field(record, "id") +
               " is frozen; unfreeze before superseding");
    }
    if (string_field(record, "status") == kProductStatusSuperseded) {
        refuse("product " + string_field(record, "id") +
               " is already superseded by " +
               string_field(record, "superseded_by") +
               "; the first successor wins");
    }
    record["status"] = std::string(kProductStatusSuperseded);
    record["superseded_by"] = string_field(successor, "id");
    record["lifecycle"] = std::string(kLifecycleSuperseded);
}

std::string promote_map_product(const Json& record, const PromoteFn& promote) {
    if (!promote) {
        refuse("promote requires the data catalog");
    }
    const std::string output_version_id =
        string_field(record, "output_version_id");
    if (output_version_id.empty()) {
        refuse("product " + string_field(record, "id") +
               " has no output version to promote");
    }
    if (string_field(record, "status") == kProductStatusSuperseded) {
        refuse("product " + string_field(record, "id") +
               " is superseded; promote its successor instead");
    }
    return promote(output_version_id);
}

Json publish_map_product(Json& record, const Json& project,
                         CatalogRepository* catalog, bool accept_warnings,
                         std::optional<std::string> export_path) {
    std::vector<std::string> problems;
    std::vector<std::string> warnings;

    if (string_field(record, "status") == kProductStatusSuperseded) {
        problems.push_back("superseded by " +
                           string_field(record, "superseded_by"));
    }
    const std::string lifecycle = effective_lifecycle(record);
    if (lifecycle != kLifecycleFrozen) {
        problems.push_back("lifecycle is " + lifecycle +
                           " — only frozen products publish (review → "
                           "freeze first; goal §31 ladder)");
    }
    // 产品级 QA：BLOCKER 一票否决；ERROR 同样阻断（指纹说"没变"而统一
    // staleness 说"上游已过期"时，发布绝不能拣乐观的引擎放行）。
    Json qa = product_qa(record, project, catalog);
    for (const Json& finding : value_field(qa, "findings")) {
        const std::string severity = string_field(finding, "severity");
        const std::string message = string_field(finding, "message");
        if (severity == kQaBlocker) {
            problems.push_back("[BLOCKER] " + message);
        } else if (severity == kQaError) {
            problems.push_back("[ERROR] " + message);
        }
    }
    Json staleness = product_staleness(record, project);
    if (staleness["stale"].get<bool>()) {
        problems.push_back(staleness["reason"].get<std::string>());
    }

    // QC status gate: the active quality report must not carry errors.
    const std::string active_qc_id =
        string_field(project, "active_quality_report_id");
    const Json* active_qc = nullptr;
    for (const Json& report_obj : array_field(project, "quality_reports")) {
        if (!active_qc_id.empty() &&
            string_field(report_obj, "id") == active_qc_id) {
            active_qc = &report_obj;
            break;
        }
    }
    if (active_qc != nullptr &&
        string_field(*active_qc, "status") == "error") {
        problems.push_back("active quality report " +
                           string_field(*active_qc, "id") +
                           " has status error — fix the reported issues "
                           "before publishing");
    }
    // V8 M11: skipped QC rules must be visible at publish — a rule that
    // never evaluated is not a pass.
    if (active_qc != nullptr) {
        const Json& rule_status = value_field(*active_qc, "rule_status");
        std::vector<std::string> skipped_rules;
        if (rule_status.is_object()) {
            // Python: only dict entries count as rule statuses.
            for (auto it = rule_status.begin(); it != rule_status.end();
                 ++it) {
                const bool evaluated =
                    it->is_object() && bool_field(*it, "evaluated");
                if (it->is_object() && !evaluated) {
                    skipped_rules.push_back(it.key());
                }
            }
        }
        std::sort(skipped_rules.begin(), skipped_rules.end());
        if (!skipped_rules.empty()) {
            std::string joined = "[";
            for (size_t i = 0; i < skipped_rules.size(); ++i) {
                if (i != 0) joined += ", ";
                joined += repr_str(skipped_rules[i]);
            }
            joined += "]";
            warnings.push_back("QC skipped " +
                               std::to_string(skipped_rules.size()) +
                               " rule(s) — pass status does not cover them: " +
                               joined);
        }
    }

    const std::vector<std::string> factor_task_ids =
        string_list_field(record, "factor_task_ids");
    const std::set<std::string> record_tasks(factor_task_ids.begin(),
                                             factor_task_ids.end());
    auto is_record_task = [&](const Json& task) {
        return record_tasks.count(string_field(task, "id")) != 0;
    };

    // kriging fallback honesty (V8 M1).
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (!task.is_object() || !is_record_task(task)) continue;
        const Json& grid_metadata = value_field(task, "grid_metadata");
        const Json& algorithm_parameters =
            value_field(grid_metadata, "algorithm_parameters");
        const std::string algo_method =
            string_field(algorithm_parameters, "method");
        const Json& parameters = value_field(task, "parameters");
        const std::string interp_backend =
            string_field(parameters, "interp_backend");
        if (algo_method == "kriging_fallback" ||
            interp_backend == "kriging_fallback") {
            warnings.push_back("factor " +
                               repr_str(string_field(task, "name")) +
                               ": computed by the numpy kriging fallback "
                               "(grid-OLS variogram fit, not engine WLS)");
        }
    }

    // CRS verifiability (review R2-P0): honest warning, never a fabricated
    // pass. The project-level CRS declaration is reported for the caller.
    const Json& coordinate = value_field(project, "coordinate");
    const std::string project_crs = string_field(coordinate, "project_crs");
    if (nullable_string_field(record, "composition_ref").has_value() &&
        !string_field(record, "composition_ref").empty()) {
        warnings.push_back(
            "map CRS not verifiable from the composition reference (no CRS "
            "storage on the map document); project CRS is '" +
            project_crs + "'");
    } else {
        warnings.push_back(
            "no composition reference: map CRS cannot be verified");
    }

    // Units + constraint diagnostics + uncertainty: warnings, never silent.
    if (factor_task_ids.empty()) {
        warnings.push_back("product references no factor tasks");
    }
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (!task.is_object() || !is_record_task(task)) continue;
        const Json& quality_metrics = value_field(task, "quality_metrics");
        const Json& parameters = value_field(task, "parameters");
        std::string unit;
        const Json& unit_from_qm = value_field(quality_metrics, "unit");
        if (unit_from_qm.is_string()) unit = unit_from_qm.get<std::string>();
        if (unit.empty()) {
            const Json& unit_from_params = value_field(parameters, "unit");
            if (unit_from_params.is_string()) {
                unit = unit_from_params.get<std::string>();
            }
        }
        if (unit.find_first_not_of(" \t\r\n") == std::string::npos) {
            warnings.push_back("factor " +
                               repr_str(string_field(task, "name")) +
                               ": unit undeclared");
        }
        const Json& constraint_diag =
            value_field(parameters, "constraint_diagnostics");
        const Json& unsupported =
            value_field(constraint_diag, "unsupported_constraints");
        if (!unsupported.is_null() &&
            (!unsupported.is_array() || !unsupported.empty())) {
            warnings.push_back(
                "factor " + repr_str(string_field(task, "name")) +
                ": constraints " +
                (unsupported.is_string()
                     ? unsupported.get<std::string>()
                     : unsupported.dump()) +
                " were ignored by " +
                (string_field(constraint_diag, "method").empty()
                     ? "?"
                     : string_field(constraint_diag, "method")) +
                " — review before relying on this product");
        }
        if (value_field(quality_metrics, "variance_min").is_null()) {
            warnings.push_back("factor " +
                               repr_str(string_field(task, "name")) +
                               ": no uncertainty surface");
        }
    }

    if (!warnings.empty() && !accept_warnings) {
        problems.insert(problems.end(), warnings.begin(), warnings.end());
    }

    Json report = Json::object();
    report["ok"] = problems.empty();
    report["problems"] = problems;
    report["warnings"] = warnings;
    report["staleness"] = std::move(staleness);
    report["product_qa"] = std::move(qa);
    report["lifecycle_before"] = lifecycle;
    report["export_path"] =
        export_path.has_value() ? Json(*export_path) : Json(nullptr);
    if (!problems.empty()) {
        std::string joined;
        for (size_t i = 0; i < problems.size(); ++i) {
            if (i != 0) joined += "; ";
            joined += problems[i];
        }
        refuse("product cannot be published: " + joined);
    }
    record["lifecycle"] = std::string(kLifecyclePublished);
    return report;
}

}  // namespace pwb::closure_workflow
