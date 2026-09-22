// pwb::closure_science — inference job layer implementation. Semantics and
// message texts mirror paleo_workbench/prediction/inference_service.py (the
// frozen Python source stays the reference oracle).

#include <pwb/closure_science/inference_service.hpp>

#include "inference_hash.hpp"

#include <pwb/closure_science/model_seed.hpp>
#include <pwb/catalog/checksum.hpp>
#include <pwb/catalog/model_registry.hpp>
#include <pwb/domain/diagnostics.hpp>
#include <pwb/prediction/spatial_result.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <map>
#include <set>
#include <stdexcept>

namespace pwb::closure_science {

using detail::dump_canonical;

using catalog::DataAsset;
using catalog::DataRun;
using catalog::DataVersion;

namespace {

// inference_service.py _RESERVED_KEYS: run-parameter keys that never reach
// the provider parameters.
constexpr const char* kReservedRunParameterKeys[] = {
    "_finished_at", "_domain_task_id", "_input_snapshot_hash", "model_id",
    "model_version", "model_version_id", "provider", "demo_only", "error"};

// inference_service.py PAYLOAD_RESERVED_KEYS: envelope keys the SERVICE
// owns. A provider result dict is merged only after these are filtered out,
// and the envelope re-asserts them afterwards — a tampered provider can
// never relabel model identity, seed, provenance hash or run linkage.
constexpr const char* kPayloadReservedKeys[] = {
    "schema_version", "model",         "generator_version",
    "input_snapshot_hash", "input_version_ids", "seed",
    "parameters", "run_id", "_finished_at", "output_version_id"};

[[nodiscard]] bool is_reserved_run_parameter(const std::string& key) {
    for (const char* reserved : kReservedRunParameterKeys) {
        if (key == reserved) return true;
    }
    return false;
}

[[nodiscard]] bool is_payload_reserved(const std::string& key) {
    for (const char* reserved : kPayloadReservedKeys) {
        if (key == reserved) return true;
    }
    return false;
}

[[nodiscard]] std::string snapshot_hash(const Json& snapshot) {
    return catalog::sha256_text(dump_canonical(snapshot));
}

[[nodiscard]] int coerce_seed(const Json& parameters) {
    // Python int(params.get("seed", 0) or 0): absent/null/0 -> 0; a
    // non-numeric string falls back to 0 like int() raising -> parity is
    // only claimed for numeric + null values (real runs pass ints).
    if (!parameters.contains("seed")) return 0;
    const Json& seed = parameters["seed"];
    if (seed.is_null() || (seed.is_number_integer() && seed == 0)) return 0;
    if (seed.is_number_integer()) return seed.get<int>();
    if (seed.is_number_float()) return static_cast<int>(seed.get<double>());
    return 0;
}

[[nodiscard]] std::string now_iso() { return domain::now_iso8601(); }

[[nodiscard]] const DataVersion* find_version(
    const catalog::CatalogDocument& document, const std::string& version_id) {
    for (const DataVersion& version : document.versions) {
        if (version.id.str() == version_id) return &version;
    }
    return nullptr;
}

[[nodiscard]] const DataAsset* find_asset(
    const catalog::CatalogDocument& document, const std::string& asset_id) {
    for (const DataAsset& asset : document.assets) {
        if (asset.id.str() == asset_id) return &asset;
    }
    return nullptr;
}

[[nodiscard]] const DataRun* find_run(
    const catalog::CatalogDocument& document, const std::string& run_id) {
    for (const DataRun& run : document.runs) {
        if (run.id.str() == run_id) return &run;
    }
    return nullptr;
}

[[nodiscard]] std::string json_text(const Json& value,
                                    const std::string& fallback = {}) {
    if (value.is_string()) return value.get<std::string>();
    return fallback;
}

// Version payload path -> absolute filesystem path (project-join ladder:
// managed "<name>.artifacts/..." first segment, recorded absolute, naive
// project-relative). Mirrors the missing-scan probe ladder's first rung.
[[nodiscard]] std::filesystem::path version_payload_path(
    const ExecuteRunDeps& deps, const DataVersion& version) {
    const std::string recorded = version.path;
    if (recorded.empty()) return {};
    std::filesystem::path candidate(recorded);
    if (candidate.is_absolute()) return candidate;
    if (!deps.project_dir.empty()) return deps.project_dir / candidate;
    return candidate;
}

// input_info (Python _input_info): the payload location + recorded facts
// one declared input version contributes to the provider inputs dict.
[[nodiscard]] domain::Result<Json> input_info(
    const catalog::CatalogDocument& document, const ExecuteRunDeps& deps,
    const std::string& version_id) {
    const DataVersion* version = find_version(document, version_id);
    if (version == nullptr) {
        return domain::DataError(
            domain::ErrorCode::NotFound,
            "Unknown version: " + version_id);
    }
    if (version->trashed) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "输入版本已被删除: " + version_id);
    }
    const DataAsset* asset = find_asset(document, version->asset_id.str());
    Json info = Json::object();
    info["version_id"] = version->id.str();
    info["name"] = asset != nullptr ? asset->name : "";
    info["asset_type"] = asset != nullptr ? asset->type : "";
    info["format"] = version->format;
    const std::filesystem::path payload = version_payload_path(deps, *version);
    info["path"] = payload.string();
    info["readable"] = !payload.empty() && std::filesystem::exists(payload);
    info["version_metadata"] = version->metadata;
    return info;
}

[[nodiscard]] domain::DataError fail_run(catalog::DataRun& run,
                                         const catalog::SaveHook& save,
                                         const std::string& type,
                                         const std::string& message) {
    run.status = "failed";
    Json extra = run.parameters;
    extra["error"] = type + ": " + message;
    extra["error_type"] = type;
    extra["_finished_at"] = now_iso();
    run.parameters = std::move(extra);
    catalog::DirtySet dirty;
    dirty.runs.push_back(run.id.str());
    auto saved = save(dirty);
    if (saved.code != domain::ErrorCode::Ok) return saved;
    return domain::DataError(domain::ErrorCode::Unknown,
                             type + ": " + message);
}

// _cancel_run parity: a cooperative cancellation is a terminal "cancelled"
// (never "failed") with no output version; partial tiled progress is
// recorded so a resumed execute can pick up the on-disk markers.
[[nodiscard]] domain::Result<ExecuteRunOutcome> cancel_run_forward(
    catalog::DataRun& run, const catalog::SaveHook& save,
    const Json* partial) {
    run.status = "cancelled";
    Json extra = run.parameters;
    extra["_finished_at"] = now_iso();
    if (partial != nullptr && partial->is_object()) {
        if (partial->contains("tiles") && (*partial)["tiles"].is_number()) {
            extra["tiles_done"] = (*partial)["tiles"];
        }
        if (partial->contains("elapsed_s") &&
            (*partial)["elapsed_s"].is_number()) {
            extra["elapsed_s"] = (*partial)["elapsed_s"];
        }
    }
    run.parameters = std::move(extra);
    catalog::DirtySet dirty;
    dirty.runs.push_back(run.id.str());
    auto saved = save(dirty);
    if (saved.code != domain::ErrorCode::Ok) return saved;
    ExecuteRunOutcome outcome;
    outcome.run = run;
    outcome.cancelled = true;
    return outcome;
}

// Persist the result payload (Python _persist_result core): the envelope
// file lands under <artifacts_root>/derived/inference/, and the DERIVED
// version + optional new asset + run link are saved through one SaveHook
// channel (single transaction on the caller's store side; no zero-version
// asset window because rows land together).
[[nodiscard]] domain::Result<DataVersion> persist_result(
    catalog::CatalogDocument& document, const ExecuteRunDeps& deps,
    const DataRun& run, const Json& payload, const std::string& model_name,
    bool demo) {
    const std::filesystem::path dir =
        deps.artifacts_root / "derived" / "inference";
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    if (ec) {
        return domain::DataError(
            domain::ErrorCode::IoError,
            "cannot create inference result dir: " + dir.string());
    }
    const std::string file_name = "result_" + run.id.str() + ".json";
    const std::filesystem::path target = dir / file_name;
    const std::string content = domain::dump_json_python_compatible(payload);
    {
        const std::filesystem::path tmp = dir / ("." + file_name + ".tmp");
        std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
        if (!stream.good()) {
            return domain::DataError(domain::ErrorCode::IoError,
                                     "cannot write " + tmp.string());
        }
        stream.write(content.data(),
                     static_cast<std::streamsize>(content.size()));
        stream.flush();
        if (!stream.good()) {
            stream.close();
            std::filesystem::remove(tmp);
            return domain::DataError(domain::ErrorCode::IoError,
                                     "short write to " + tmp.string());
        }
        stream.close();
        std::filesystem::rename(tmp, target, ec);
        if (ec) {
            std::filesystem::remove(tmp);
            return domain::DataError(domain::ErrorCode::IoError,
                                     "cannot finalize " + target.string());
        }
    }

    DataAsset asset;
    asset.id = domain::AssetId(domain::make_id("asset_"));
    asset.name = model_name + " 结果";
    asset.type = "prediction_result";
    asset.metadata = Json{{"kind", "prediction_result"}};
    asset.created_at = now_iso();
    asset.updated_at = asset.created_at;

    DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.asset_id = domain::AssetId(asset.id.str());
    version.version_number = 1;
    version.stage = domain::DataStage::Derived;
    version.managed = true;
    if (!deps.project_dir.empty()) {
        std::filesystem::path relative = std::filesystem::relative(
            target, deps.project_dir, ec);
        version.path = ec ? target.string()
                          : relative.generic_string();
    } else {
        version.path = target.string();
    }
    version.format = "json";
    version.size_bytes = static_cast<std::int64_t>(content.size());
    version.sha256 = catalog::sha256_text(content);
    version.run_id = run.id;
    version.metadata = Json{
        {"source", json_text(payload["source"], "inference")},
        {"demo", demo},
        {"kind", "prediction_result"},
        {"format", "json"}};
    version.created_at = now_iso();

    document.assets.push_back(asset);
    document.versions.push_back(version);

    catalog::DirtySet dirty;
    dirty.assets.push_back(asset.id.str());
    dirty.versions.push_back(version.id.str());
    auto saved = deps.save(dirty);
    if (saved.code != domain::ErrorCode::Ok) {
        // Roll the in-memory append back so the document never claims a
        // version the store refused — and remove the orphan payload file.
        document.assets.pop_back();
        document.versions.pop_back();
        std::error_code rm_ec;
        std::filesystem::remove(target, rm_ec);
        return saved;
    }
    return version;
}

}  // namespace

// ---------------------------------------------------------------------------
// ProviderRegistry
// ---------------------------------------------------------------------------

void ProviderRegistry::register_provider(const std::string& name,
                                         ProviderRun run) {
    for (auto& [existing, existing_run] : providers_) {
        if (existing == name) {
            existing_run = std::move(run);
            return;
        }
    }
    providers_.emplace_back(name, std::move(run));
}

std::optional<ProviderRun> ProviderRegistry::get(
    const std::string& name) const {
    for (const auto& [existing, existing_run] : providers_) {
        if (existing == name) return existing_run;
    }
    return std::nullopt;
}

// ---------------------------------------------------------------------------
// Input resolution
// ---------------------------------------------------------------------------

std::optional<std::string> resolve_resource_version_id(
    const catalog::CatalogDocument& document, const ResourceRef& resource) {
    // Explicit re-import bridge first: ResourceItem's parsed_summary records
    // the catalog asset it was re-imported into (inference_service.py
    // catalog_asset_id parity).
    if (!resource.catalog_asset_id.empty()) {
        for (const DataAsset& asset : document.assets) {
            if (asset.trashed) continue;
            if (asset.id.str() == resource.catalog_asset_id &&
                asset.current_version_id.has_value()) {
                return asset.current_version_id->str();
            }
        }
    }
    // The ordinary identity path: catalog asset id / one-to-one legacy
    // bridge.
    for (const DataAsset& asset : document.assets) {
        if (asset.trashed) continue;
        if (asset.id.str() == resource.id ||
            (asset.legacy_resource_id.has_value() &&
             *asset.legacy_resource_id == resource.id)) {
            if (asset.current_version_id.has_value()) {
                return asset.current_version_id->str();
            }
        }
    }
    // Unique live source-URI fallback (absolute paths only; symlink-aware
    // normalization like Python Path.resolve(strict=False)).
    if (resource.path.empty()) return std::nullopt;
    std::error_code ec;
    std::filesystem::path candidate =
        std::filesystem::weakly_canonical(resource.path, ec);
    if (ec) return std::nullopt;
    const std::string source_uri = candidate.generic_string();
    std::vector<std::string> matches;
    for (const DataAsset& asset : document.assets) {
        if (asset.trashed) continue;
        if (!resource.type.empty() && asset.type != resource.type) continue;
        if (!asset.current_version_id.has_value()) continue;
        const DataVersion* version =
            find_version(document, asset.current_version_id->str());
        if (version == nullptr || version->trashed) continue;
        if (!version->source_uri.has_value()) continue;
        std::error_code ec2;
        std::filesystem::path recorded =
            std::filesystem::weakly_canonical(*version->source_uri, ec2);
        if (ec2) continue;
        if (recorded.generic_string() == source_uri) {
            matches.push_back(version->id.str());
        }
    }
    if (matches.size() == 1) return matches.front();
    return std::nullopt;
}

namespace {

// input_contract.py parse_input_schema core: the recognized keys and their
// normalized reading (required/optional asset types, required curves,
// min_wells). Interpretation-role requirements (correlation / horizon /
// fault / target horizon) have no native binding yet — the resolver reports
// them explicitly instead of silently skipping.
struct ParsedInputSchema {
    std::vector<std::string> required_asset_types;
    std::vector<std::string> optional_asset_types;
    std::vector<std::string> required_curves;
    int min_wells = 0;
    std::vector<std::string> unrecognized_keys;
    bool has_any_recognized = false;
    std::vector<std::string> unbound_role_requirements;
};

[[nodiscard]] std::vector<std::string> string_list(const Json& value) {
    std::vector<std::string> out;
    if (value.is_array()) {
        for (const auto& item : value) {
            if (item.is_string()) out.push_back(item.get<std::string>());
        }
    } else if (value.is_string()) {
        out.push_back(value.get<std::string>());
    }
    return out;
}

[[nodiscard]] ParsedInputSchema parse_input_schema(const Json& raw) {
    ParsedInputSchema schema;
    std::set<std::string> recognized = {
        "required_asset_types", "asset_types", "optional_asset_types",
        "required_curves",      "curves",     "require_target_horizon",
        "require_correlation",  "require_horizon_interpretation",
        "require_fault_interpretation", "min_wells"};
    bool has_recognized = false;
    for (auto it = raw.begin(); it != raw.end(); ++it) {
        if (recognized.count(it.key()) != 0u) {
            has_recognized = true;
        } else {
            // Model-package band vocabulary (bands/input_bands) and other
            // foreign keys ride along unrecognized; the H5-b refusal below
            // fires only when the schema declares NOTHING we can interpret.
            schema.unrecognized_keys.push_back(it.key());
        }
    }
    schema.has_any_recognized = has_recognized;
    if (raw.contains("required_asset_types")) {
        schema.required_asset_types =
            string_list(raw["required_asset_types"]);
    } else if (raw.contains("asset_types")) {
        schema.required_asset_types = string_list(raw["asset_types"]);
    }
    if (raw.contains("optional_asset_types")) {
        schema.optional_asset_types =
            string_list(raw["optional_asset_types"]);
    }
    if (raw.contains("required_curves")) {
        schema.required_curves = string_list(raw["required_curves"]);
    } else if (raw.contains("curves")) {
        schema.required_curves = string_list(raw["curves"]);
    }
    if (raw.contains("min_wells") && raw["min_wells"].is_number_integer()) {
        schema.min_wells = raw["min_wells"].get<int>();
    }
    const auto require = [&](const char* key, std::string role) {
        if (raw.contains(key) && raw[key].is_boolean() &&
            raw[key].get<bool>()) {
            schema.unbound_role_requirements.push_back(std::move(role));
        }
    };
    require("require_correlation", "correlation");
    require("require_horizon_interpretation", "horizon");
    require("require_fault_interpretation", "fault");
    if (raw.contains("require_target_horizon") &&
        raw["require_target_horizon"].is_boolean() &&
        raw["require_target_horizon"].get<bool>()) {
        schema.unbound_role_requirements.push_back("target_horizon");
    }
    return schema;
}

}  // namespace

domain::Result<std::vector<std::string>> resolve_model_inputs(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources,
    const std::string& model_version_id,
    const std::optional<std::string>& selected_resource_id) {
    auto version_result =
        catalog::get_model_version_by_id(document, model_version_id);
    if (!version_result.is_ok()) return version_result.error();
    const catalog::ModelVersion& model_version = *version_result.value();

    const ParsedInputSchema schema =
        parse_input_schema(model_version.input_schema);

    // H5-b parity: a schema declaring ONLY uninterpretable structure must
    // not silently fall back to the global gather (mixed schemas follow
    // Python: the unrecognized keys are simply not read).
    if (!schema.unrecognized_keys.empty() && !schema.has_any_recognized &&
        schema.required_asset_types.empty() &&
        schema.optional_asset_types.empty() &&
        schema.required_curves.empty() && schema.min_wells == 0 &&
        schema.unbound_role_requirements.empty()) {
        std::string joined;
        std::vector<std::string> sorted = schema.unrecognized_keys;
        std::sort(sorted.begin(), sorted.end());
        for (const std::string& key : sorted) {
            if (!joined.empty()) joined += ", ";
            joined += key;
        }
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "input_schema 使用了未识别的结构，无法按契约解析输入：" + joined);
    }

    // Interpretation-role requirements: explicit native-binding gap.
    if (!schema.unbound_role_requirements.empty()) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "模型要求的解释输入在原生运行时暂未绑定: " +
                schema.unbound_role_requirements.front());
    }

    std::set<std::string> collect(schema.required_asset_types.begin(),
                                  schema.required_asset_types.end());
    for (const std::string& type : schema.optional_asset_types) {
        collect.insert(type);
    }
    std::set<std::string> resource_types;
    for (const std::string& type : collect) {
        if (type == "well_log" || type == "seismic" || type == "factor_map") {
            resource_types.insert(type);
        }
    }

    std::vector<std::string> input_ids;
    std::set<std::string> seen;
    int wells_count = 0;
    const auto add = [&](const std::string& version_id) {
        if (version_id.empty() || seen.count(version_id) != 0u) return;
        seen.insert(version_id);
        input_ids.push_back(version_id);
    };

    const bool filtered = selected_resource_id.has_value() &&
                          !selected_resource_id->empty();
    for (const ResourceRef& resource : resources) {
        if (filtered && resource.id != *selected_resource_id) continue;
        if (resource_types.count(resource.type) == 0u) continue;
        auto version_id = resolve_resource_version_id(document, resource);
        if (!version_id.has_value()) continue;
        add(*version_id);
        if (resource.type == "well_log") ++wells_count;
    }

    if (schema.min_wells > 0 && wells_count < schema.min_wells) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "模型要求至少 " + std::to_string(schema.min_wells) +
                " 口井的测井输入，当前仅解析到 " + std::to_string(wells_count) +
                " 口");
    }
    if (!schema.required_curves.empty() && wells_count == 0 &&
        schema.min_wells == 0) {
        // required_curves enforcement without any bound well still fails
        // loudly (the curves cannot be present).
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "模型要求测井曲线输入，但未解析到可用测井版本");
    }

    // Required-type coverage (strict parity: missing required input fails).
    for (const std::string& type : schema.required_asset_types) {
        if (resource_types.count(type) == 0u) continue;
        bool found = false;
        for (const ResourceRef& resource : resources) {
            if (resource.type != type) continue;
            if (resolve_resource_version_id(document, resource).has_value()) {
                found = true;
                break;
            }
        }
        if (!found) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "模型需要 " + type +
                    " 输入资源，但工程中没有已纳管的可用版本");
        }
    }

    // Legacy global gather for unscoped models: no declared asset types and
    // no other requirement -> gather all well_log/seismic versions.
    if (schema.required_asset_types.empty() &&
        schema.optional_asset_types.empty() && input_ids.empty()) {
        for (const ResourceRef& resource : resources) {
            if (filtered && resource.id != *selected_resource_id) continue;
            if (resource.type != "well_log" && resource.type != "seismic") {
                continue;
            }
            auto version_id = resolve_resource_version_id(document, resource);
            if (version_id.has_value()) add(*version_id);
        }
        if (filtered && input_ids.empty()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "所选井数据尚未纳管为可用版本，无法运行预测");
        }
    }
    return input_ids;
}

std::vector<std::string> resolve_postprocess_inputs(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources) {
    std::vector<std::string> input_ids;
    std::set<std::string> seen;
    for (const ResourceRef& resource : resources) {
        if (resource.type != "well_stratification") continue;
        auto version_id = resolve_resource_version_id(document, resource);
        if (!version_id.has_value()) continue;
        if (seen.count(*version_id) != 0u) continue;
        seen.insert(*version_id);
        input_ids.push_back(*version_id);
    }
    return input_ids;
}

// ---------------------------------------------------------------------------
// Run lifecycle
// ---------------------------------------------------------------------------

Json run_to_json(const catalog::DataRun& run) {
    Json value = Json::object();
    value["id"] = run.id.str();
    Json input_ids = Json::array();
    for (const auto& id : run.input_version_ids) input_ids.push_back(id.str());
    value["input_version_ids"] = std::move(input_ids);
    Json output_ids = Json::array();
    for (const auto& id : run.output_version_ids) {
        output_ids.push_back(id.str());
    }
    value["output_version_ids"] = std::move(output_ids);
    value["parameters"] = run.parameters;
    value["generator"] = run.generator;
    value["status"] = run.status;
    value["model_ref"] = run.model_ref.has_value() ? *run.model_ref
                                                   : Json(nullptr);
    value["created_at"] = run.created_at;
    return value;
}

domain::Result<catalog::DataRun> start_inference(
    catalog::CatalogDocument& document, const catalog::SaveHook& save,
    const StartInferenceRequest& request) {
    auto version_result =
        catalog::get_model_version_by_id(document, request.model_version_id);
    if (!version_result.is_ok()) return version_result.error();
    const catalog::ModelVersion& model_version = *version_result.value();
    auto model_result = catalog::get_model(document, model_version.model_id);
    if (!model_result.is_ok()) return model_result.error();
    const catalog::Model& model = *model_result.value();

    const int seed = coerce_seed(request.parameters);
    std::set<std::string> unique_inputs(request.input_version_ids.begin(),
                                        request.input_version_ids.end());
    const std::vector<std::string> input_ids(unique_inputs.begin(),
                                             unique_inputs.end());

    Json snapshot_parameters = Json::object();
    for (auto it = request.parameters.begin(); it != request.parameters.end();
         ++it) {
        const std::string key = it.key();
        if (!key.empty() && key.front() == '_') continue;
        snapshot_parameters[key] = it.value();
    }
    Json snapshot = Json::object();
    snapshot["model_version_id"] = model_version.id;
    snapshot["model_id"] = model.model_id;
    snapshot["model_version"] = model_version.model_version;
    snapshot["input_version_ids"] = input_ids;
    snapshot["preprocessing_version"] = model_version.preprocessing_version;
    snapshot["artifact_checksum"] =
        model_version.checksum.has_value() ? *model_version.checksum : "";
    snapshot["parameters"] = snapshot_parameters;

    Json run_parameters = Json::object();
    run_parameters["model_id"] = model.model_id;
    run_parameters["model_version"] = model_version.model_version;
    run_parameters["model_version_id"] = model_version.id;
    run_parameters["provider"] = model.provider;
    run_parameters["demo_only"] = model_version.demo_only;
    run_parameters["preprocessing_version"] =
        model_version.preprocessing_version;
    run_parameters["seed"] = seed;
    run_parameters["_input_snapshot_hash"] = snapshot_hash(snapshot);
    for (auto it = request.parameters.begin(); it != request.parameters.end();
         ++it) {
        run_parameters[it.key()] = it.value();
    }

    Json model_ref = Json::object();
    model_ref["model_id"] = model.model_id;
    model_ref["model_version"] = model_version.model_version;
    model_ref["model_version_id"] = model_version.id;

    DataRun run;
    run.id = domain::RunId(domain::make_id("run_"));
    run.operation = request.operation;
    for (const std::string& id : input_ids) {
        run.input_version_ids.push_back(domain::VersionId(id));
    }
    run.parameters = std::move(run_parameters);
    run.generator = request.generator.empty() ? model.provider
                                              : request.generator;
    run.status = "running";
    run.model_ref = model_ref;
    run.created_at = now_iso();

    document.runs.push_back(run);
    catalog::DirtySet dirty;
    dirty.runs.push_back(run.id.str());
    auto saved = save(dirty);
    if (saved.code != domain::ErrorCode::Ok) {
        document.runs.pop_back();
        return saved;
    }
    return run;
}

domain::Result<ExecuteRunOutcome> execute_run(
    catalog::CatalogDocument& document, const ExecuteRunDeps& deps,
    const std::string& run_id, const std::function<bool()>& cancel) {
    DataRun* run_ptr = nullptr;
    for (DataRun& run : document.runs) {
        if (run.id.str() == run_id) {
            run_ptr = &run;
            break;
        }
    }
    if (run_ptr == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "Unknown run: " + run_id);
    }
    const std::string run_key = run_id;
    DataRun& run = *run_ptr;
    std::string lowered = run.status;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    if (lowered != "running") {
        // Late/duplicate execution must not touch a terminal run — and must
        // not be swallowed into a "failed" relabel of a completed run.
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "execute_run requires a running run; " + run_id + " is '" +
                run.status + "'");
    }
    if (deps.providers == nullptr) {
        return fail_run(run, deps.save, "CatalogError",
                        "no provider registry is bound to this execution");
    }

    const std::string model_version_id =
        run.parameters.is_object() &&
                run.parameters.contains("model_version_id")
            ? json_text(run.parameters["model_version_id"])
            : std::string();
    if (model_version_id.empty()) {
        return fail_run(run, deps.save, "CatalogError",
                        "Run " + run_id + " has no model_version_id");
    }
    auto model_version_result =
        catalog::get_model_version_by_id(document, model_version_id);
    if (!model_version_result.is_ok()) {
        return fail_run(run, deps.save, "CatalogError",
                        model_version_result.error().message);
    }
    const catalog::ModelVersion& model_version = *model_version_result.value();
    auto model_result = catalog::get_model(document, model_version.model_id);
    if (!model_result.is_ok()) {
        return fail_run(run, deps.save, "CatalogError",
                        model_result.error().message);
    }
    const catalog::Model& model = *model_result.value();

    auto provider = deps.providers->get(model.provider);
    if (!provider.has_value()) {
        return fail_run(run, deps.save, "KeyError",
                        "Unknown model provider: '" + model.provider + "'");
    }
    // A registered model whose runtime has no native executor (e.g. the
    // HTTP geoviz_online service) must fail here — advertised but not
    // executable is worse than unknown.
    if (model.provider == std::string(kProviderGeovizOnline)) {
        return fail_run(
            run, deps.save, "CatalogError",
            "provider 'geoviz_online' 没有原生执行器（线上 HTTP 推理未接入本"
            "运行时）");
    }

    const int seed = coerce_seed(run.parameters);
    Json inputs = Json::object();
    for (const domain::VersionId& version_id : run.input_version_ids) {
        auto info = input_info(document, deps, version_id.str());
        if (!info.is_ok()) {
            return fail_run(run, deps.save, "CatalogError",
                            info.error().message);
        }
        inputs[version_id.str()] = std::move(info.value());
    }

    Json parameters = Json::object();
    for (auto it = run.parameters.begin(); it != run.parameters.end(); ++it) {
        const std::string key = it.key();
        if (!key.empty() && key.front() == '_') continue;
        if (is_reserved_run_parameter(key)) continue;
        parameters[key] = it.value();
    }
    parameters["seed"] = seed;
    Json registered_model = Json::object();
    registered_model["model_id"] = model.model_id;
    registered_model["model_version"] = model_version.model_version;
    registered_model["model_version_id"] = model_version.id;
    registered_model["artifact_uri"] = model_version.artifact_uri;
    registered_model["checksum"] = model_version.checksum.has_value()
                                       ? *model_version.checksum
                                       : "";
    parameters["_registered_model"] = std::move(registered_model);

    // Run the provider. All provider-side failures — including a raised
    // TaskCancelled-shaped cancellation — are translated here so the run
    // never strands in "running". `parameters` is passed by copy: the
    // service envelope below re-reads it for the persisted payload.
    domain::Result<Json> provider_result =
        (*provider)(inputs, parameters, cancel);
    if (!provider_result.is_ok()) {
        if (provider_result.error().code == domain::ErrorCode::Cancelled) {
            return cancel_run_forward(run, deps.save, nullptr);
        }
        return fail_run(run, deps.save,
                        provider_result.error().code ==
                                domain::ErrorCode::NotFound
                            ? "NotFound"
                            : "ProviderError",
                        provider_result.error().message);
    }
    Json result = std::move(provider_result.value());
    if (result.contains("cancelled") && result["cancelled"].is_boolean() &&
        result["cancelled"].get<bool>()) {
        return cancel_run_forward(run, deps.save, &result);
    }

    // Stage-13: validate the spatial output when the model declares one.
    const Json expected = Json(model_version.output_schema.contains(
                                   "spatial_output_type")
                                   ? model_version.output_schema["spatial_output_type"]
                                   : Json(""));
    if (expected.is_string() && !expected.get<std::string>().empty() &&
        expected.get<std::string>() != "NONE") {
        Json spatial_errors = pwb::prediction::validate_spatial_result(
            result, expected, /*require_scientific=*/false);
        if (spatial_errors.is_array() && !spatial_errors.empty()) {
            std::string joined;
            for (const auto& item : spatial_errors) {
                if (!joined.empty()) joined += "; ";
                joined += item.is_string() ? item.get<std::string>()
                                           : item.dump();
            }
            return fail_run(run, deps.save, "SpatialResultError", joined);
        }
    }

    // Envelope assembly: reserved keys are service-owned. Only the FILTERED
    // provider payload is merged; the envelope re-asserts the reserved keys
    // afterwards.
    const std::string service_generator =
        !run.generator.empty() ? run.generator
                               : (!model.provider.empty() ? model.provider
                                                          : std::string(kInferenceGenerator));
    Json provider_payload = Json::object();
    for (auto it = result.begin(); it != result.end(); ++it) {
        if (is_payload_reserved(it.key())) continue;
        provider_payload[it.key()] = it.value();
    }
    Json payload = Json::object();
    payload["schema_version"] = "1.0";
    Json model_identity = Json::object();
    model_identity["model_id"] = model.model_id;
    model_identity["model_version"] = model_version.model_version;
    model_identity["model_name"] = model.model_name;
    model_identity["demo_only"] = model_version.demo_only;
    model_identity["preprocessing_version"] =
        model_version.preprocessing_version;
    model_identity["checksum"] = model_version.checksum.has_value()
                                     ? *model_version.checksum
                                     : std::string();
    model_identity["model_version_id"] = model_version.id;
    payload["model"] = std::move(model_identity);
    payload["generator_version"] = service_generator;
    payload["input_snapshot_hash"] = run.parameters.contains(
        "_input_snapshot_hash")
        ? run.parameters["_input_snapshot_hash"]
        : Json(nullptr);
    Json payload_inputs = Json::array();
    for (const auto& id : run.input_version_ids) {
        payload_inputs.push_back(id.str());
    }
    payload["input_version_ids"] = std::move(payload_inputs);
    payload["seed"] = seed;
    Json payload_parameters = Json::object();
    for (auto it = parameters.begin(); it != parameters.end(); ++it) {
        const std::string key = it.key();
        if (!key.empty() && key.front() == '_') continue;
        payload_parameters[key] = it.value();
    }
    payload["parameters"] = std::move(payload_parameters);
    payload["run_id"] = run_id;
    for (auto it = provider_payload.begin(); it != provider_payload.end();
         ++it) {
        payload[it.key()] = it.value();
    }

    // Persist (DERIVED version + run link), then flip the run terminal.
    bool demo = model_version.demo_only;
    auto version = persist_result(document, deps, run, payload,
                                  model.model_name, demo);
    if (!version.is_ok()) {
        // If an output version was registered the run DID produce; the
        // failure path above already returned the error before rows landed
        // (rows land only on a successful save) — record the failure.
        return fail_run(run, deps.save, "IoError",
                        version.error().message);
    }
    run.output_version_ids.push_back(
        domain::VersionId(version.value().id.str()));
    run.status = "complete";
    Json finished = run.parameters;
    finished["_finished_at"] = now_iso();
    finished["output_version_id"] = version.value().id.str();
    run.parameters = std::move(finished);
    catalog::DirtySet dirty;
    dirty.versions.push_back(version.value().id.str());
    dirty.runs.push_back(run.id.str());
    auto saved = deps.save(dirty);
    if (saved.code != domain::ErrorCode::Ok) {
        return saved;
    }

    ExecuteRunOutcome outcome;
    outcome.run = run;
    outcome.payload = std::move(payload);
    outcome.output_version = version.value();
    outcome.output_version_id = version.value().id.str();
    return outcome;
}

// ---------------------------------------------------------------------------
// materialize_prediction_task (Python parity)
// ---------------------------------------------------------------------------

Json materialize_prediction_task(const catalog::CatalogDocument& document,
                                 const Json& payload,
                                 const PredictionTaskOptions& options) {
    (void)document;  // the horizon fallback reads the caller's project in
                     // Python; the binding passes target_horizon directly.
    Json result_summary;
    if (payload.contains("result_summary") &&
        payload["result_summary"].is_object()) {
        auto bounded = pwb::prediction::bounded_result_summary(payload);
        result_summary = bounded.is_object() ? std::move(bounded)
                                             : payload["result_summary"];
    } else {
        result_summary = Json::object();
    }
    const Json model = payload.contains("model") && payload["model"].is_object()
                           ? payload["model"]
                           : Json::object();
    const auto text_of = [&](const Json& value,
                             const std::string& fallback) {
        return value.is_string() ? value.get<std::string>() : fallback;
    };
    std::string adapter_kind;
    if (payload.contains("adapter_kind") &&
        payload["adapter_kind"].is_string()) {
        adapter_kind = payload["adapter_kind"].get<std::string>();
    } else {
        const bool is_mock =
            result_summary.contains("is_mock") &&
            result_summary["is_mock"].is_boolean() &&
            result_summary["is_mock"].get<bool>();
        adapter_kind = is_mock ? "mock" : "local";
    }
    const std::string horizon = !options.target_horizon.empty()
                                    ? options.target_horizon
                                    : "demo";
    const std::string resolved_run =
        !options.run_id.empty()
            ? options.run_id
            : text_of(payload.contains("run_id") ? payload["run_id"]
                                                 : Json(nullptr),
                      "");
    std::string resolved_out;
    if (!options.output_version_id.empty()) {
        resolved_out = options.output_version_id;
    } else if (payload.contains("output_version_id") &&
               payload["output_version_id"].is_string()) {
        resolved_out = payload["output_version_id"].get<std::string>();
    } else if (payload.contains("parameters") &&
               payload["parameters"].is_object() &&
               payload["parameters"].contains("output_version_id") &&
               payload["parameters"]["output_version_id"].is_string()) {
        // Python fallback ladder: (payload.parameters).output_version_id.
        resolved_out =
            payload["parameters"]["output_version_id"].get<std::string>();
    }

    // Python dict.fromkeys: unique, order-preserving.
    const auto unique = [](const std::vector<std::string>& values) {
        std::vector<std::string> out;
        std::set<std::string> seen;
        for (const std::string& value : values) {
            if (value.empty() || seen.count(value) != 0u) continue;
            seen.insert(value);
            out.push_back(value);
        }
        return out;
    };

    Json input_refs = Json::object();
    {
        Json well_ids = Json::array();
        for (const std::string& id :
             unique(options.well_log_resource_ids)) {
            well_ids.push_back(id);
        }
        input_refs["well_log_resource_ids"] = std::move(well_ids);
        Json seismic_ids = Json::array();
        for (const std::string& id : unique(options.seismic_resource_ids)) {
            seismic_ids.push_back(id);
        }
        input_refs["seismic_resource_ids"] = std::move(seismic_ids);
    }

    const bool demo = result_summary.contains("demo") &&
                      result_summary["demo"].is_boolean() &&
                      result_summary["demo"].get<bool>();

    Json model_metadata = Json::object();
    model_metadata["workflow"] = options.workflow;
    model_metadata["target_horizon"] = options.target_horizon;
    model_metadata["adapter"] = adapter_kind;
    model_metadata["model_id"] = text_of(model.contains("model_id")
                                             ? model["model_id"]
                                             : Json(nullptr),
                                         "");
    model_metadata["model_version"] = text_of(model.contains("model_version")
                                                  ? model["model_version"]
                                                  : Json(nullptr),
                                              "");
    model_metadata["model_name"] = text_of(model.contains("model_name")
                                               ? model["model_name"]
                                               : Json(nullptr),
                                           "");
    model_metadata["model_version_id"] =
        text_of(model.contains("model_version_id") ? model["model_version_id"]
                                                   : Json(nullptr),
                "");
    model_metadata["preprocessing_version"] =
        text_of(model.contains("preprocessing_version")
                    ? model["preprocessing_version"]
                    : Json(nullptr),
                "");
    model_metadata["demo_only"] =
        model.contains("demo_only") && model["demo_only"].is_boolean() &&
                model["demo_only"].get<bool>()
            ? Json(true)
            : Json(false);
    model_metadata["demo"] = demo ? Json(true) : Json(false);
    model_metadata["run_id"] = resolved_run;
    model_metadata["prediction_version_id"] = resolved_out;

    Json task = Json::object();
    task["name"] = options.name_prefix + " · " + horizon;
    task["adapter_kind"] = adapter_kind;
    task["input_factor_map_ids"] = Json::array();
    task["input_refs"] = std::move(input_refs);
    task["model_metadata"] = std::move(model_metadata);
    task["result_summary"] = result_summary;
    task["probability_summary"] =
        payload.contains("probability_summary") &&
                payload["probability_summary"].is_object()
            ? payload["probability_summary"]
            : Json::object();
    task["evidence_contribution"] =
        payload.contains("evidence_contribution") &&
                payload["evidence_contribution"].is_array()
            ? payload["evidence_contribution"]
            : Json::array();
    task["review_areas"] =
        payload.contains("review_areas") && payload["review_areas"].is_array()
            ? payload["review_areas"]
            : Json::array();
    task["status"] = "complete";
    task["adapter_schema_version"] =
        text_of(payload.contains("schema_version") ? payload["schema_version"]
                                                   : Json(nullptr),
                "1.0");
    task["input_snapshot_hash"] =
        text_of(payload.contains("input_snapshot_hash")
                    ? payload["input_snapshot_hash"]
                    : Json(nullptr),
                "");
    task["generator_version"] =
        payload.contains("generator_version") &&
                payload["generator_version"].is_string()
            ? Json(payload["generator_version"].get<std::string>())
            : Json(nullptr);
    task["seed"] = payload.contains("seed") ? payload["seed"] : Json(nullptr);
    return task;
}

}  // namespace pwb::closure_science
