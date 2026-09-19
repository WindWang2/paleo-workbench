// persistent_catalog.cpp — see include/pwb/closure_workflow/persistent_catalog.hpp.

#include <pwb/closure_workflow/persistent_catalog.hpp>

#include <pwb/domain/json.hpp>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <utility>

namespace pwb::closure_workflow {

namespace {

using pwb::domain::Json;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;

inline constexpr const char* kStoreVersion = "store_version";

std::optional<std::string> opt_of(const std::string& value) {
    return value.empty() ? std::nullopt : std::optional<std::string>(value);
}

// Const-safe field read: missing key reads as null (never operator[]).
const Json kNullNode = Json(nullptr);
const Json& field_or_null(const Json& node, const char* key) {
    const auto it = node.find(key);
    return it == node.end() ? kNullNode : *it;
}

Json encode_asset(const AssetRecord& asset) {
    Json out = Json::object();
    out["id"] = asset.id;
    out["name"] = asset.name;
    out["type"] = asset.type;
    out["format"] = asset.format;
    out["current_version_id"] = asset.current_version_id.has_value()
                                    ? Json(*asset.current_version_id)
                                    : Json(nullptr);
    out["metadata"] = asset.metadata.is_object() ? asset.metadata
                                                 : Json::object();
    return out;
}

AssetRecord decode_asset(const Json& node) {
    AssetRecord asset;
    asset.id = node.at("id").get<std::string>();
    asset.name = node.value("name", std::string());
    asset.type = node.value("type", std::string());
    asset.format = node.value("format", std::string());
    const Json& current = field_or_null(node, "current_version_id");
    if (current.is_string()) asset.current_version_id = current.get<std::string>();
    if (node.contains("metadata") && node["metadata"].is_object()) {
        asset.metadata = node["metadata"];
    }
    return asset;
}

Json encode_version(const VersionRecord& version) {
    Json out = Json::object();
    out["asset_id"] = version.asset_id;
    out["version_id"] = version.version_id;
    out["name"] = version.name;
    out["producing_run_id"] = version.producing_run_id.has_value()
                                  ? Json(*version.producing_run_id)
                                  : Json(nullptr);
    out["checksum"] = version.checksum;
    out["trashed"] = version.trashed;
    out["path"] = version.path;
    out["created_at"] = version.created_at;
    out["metadata"] = version.metadata.is_object() ? version.metadata
                                                   : Json::object();
    out["payload_json"] = version.payload_json;
    return out;
}

VersionRecord decode_version(const Json& node) {
    VersionRecord version;
    version.asset_id = node.at("asset_id").get<std::string>();
    version.version_id = node.at("version_id").get<std::string>();
    version.name = node.value("name", std::string());
    const Json& run = field_or_null(node, "producing_run_id");
    if (run.is_string()) version.producing_run_id = run.get<std::string>();
    version.checksum = node.value("checksum", std::string());
    version.trashed = node.value("trashed", false);
    version.path = node.value("path", std::string());
    version.created_at = node.value("created_at", std::string());
    if (node.contains("metadata") && node["metadata"].is_object()) {
        version.metadata = node["metadata"];
    }
    if (node.contains("payload_json") && node["payload_json"].is_string()) {
        version.payload_json = node["payload_json"].get<std::string>();
    }
    return version;
}

Json encode_run(const RunRecord& run) {
    Json out = Json::object();
    out["run_id"] = run.run_id;
    out["operation"] = run.operation;
    out["input_version_ids"] = run.input_version_ids;
    out["output_version_ids"] = run.output_version_ids;
    out["parameters"] = run.parameters.is_object() ? run.parameters
                                                   : Json::object();
    out["generator_version"] = run.generator_version.has_value()
                                   ? Json(*run.generator_version)
                                   : Json(nullptr);
    out["domain_task_id"] = run.domain_task_id.has_value()
                                ? Json(*run.domain_task_id)
                                : Json(nullptr);
    out["input_snapshot_hash"] = run.input_snapshot_hash.has_value()
                                     ? Json(*run.input_snapshot_hash)
                                     : Json(nullptr);
    out["status"] = run.status;
    out["started_at"] = run.started_at.has_value()
                            ? Json(*run.started_at)
                            : Json(nullptr);
    out["finished_at"] = run.finished_at.has_value()
                             ? Json(*run.finished_at)
                             : Json(nullptr);
    out["actor"] = run.actor.has_value() ? Json(*run.actor) : Json(nullptr);
    out["run_metadata"] = run.run_metadata.is_object() ? run.run_metadata
                                                       : Json::object();
    return out;
}

RunRecord decode_run(const Json& node) {
    RunRecord run;
    run.run_id = node.at("run_id").get<std::string>();
    run.operation = node.value("operation", std::string());
    if (node.contains("input_version_ids") &&
        node["input_version_ids"].is_array()) {
        run.input_version_ids =
            node["input_version_ids"].get<std::vector<std::string>>();
    }
    if (node.contains("output_version_ids") &&
        node["output_version_ids"].is_array()) {
        run.output_version_ids =
            node["output_version_ids"].get<std::vector<std::string>>();
    }
    if (node.contains("parameters") && node["parameters"].is_object()) {
        run.parameters = node["parameters"];
    }
    const Json& generator = field_or_null(node, "generator_version");
    if (generator.is_string()) run.generator_version = generator.get<std::string>();
    const Json& domain_task = field_or_null(node, "domain_task_id");
    if (domain_task.is_string()) run.domain_task_id = domain_task.get<std::string>();
    const Json& snapshot = field_or_null(node, "input_snapshot_hash");
    if (snapshot.is_string()) run.input_snapshot_hash = snapshot.get<std::string>();
    run.status = node.value("status", std::string("running"));
    const Json& started = field_or_null(node, "started_at");
    if (started.is_string()) run.started_at = started.get<std::string>();
    const Json& finished = field_or_null(node, "finished_at");
    if (finished.is_string()) run.finished_at = finished.get<std::string>();
    const Json& actor = field_or_null(node, "actor");
    if (actor.is_string()) run.actor = actor.get<std::string>();
    if (node.contains("run_metadata") && node["run_metadata"].is_object()) {
        run.run_metadata = node["run_metadata"];
    }
    return run;
}

// Atomic whole-file write: tmp sibling + rename (the workflow-store
// convention; a crash leaves the previous full state, never a torn file).
void atomic_write(const std::filesystem::path& file, const std::string& text) {
    static std::atomic<unsigned long long> seq{0};
    const std::filesystem::path tmp =
        file.parent_path() /
        ("." + file.filename().string() + ".tmp-" +
         std::to_string(
             std::chrono::steady_clock::now().time_since_epoch().count()) +
         "-" + std::to_string(seq.fetch_add(1)));
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw std::runtime_error("cannot open catalog store for write: " +
                                     tmp.string());
        }
        out.write(text.data(), static_cast<std::streamsize>(text.size()));
        if (!out) {
            throw std::runtime_error("catalog store write failed: " +
                                     tmp.string());
        }
    }
    std::error_code ec;
    std::filesystem::rename(tmp, file, ec);
    if (ec) {
        std::filesystem::remove(tmp, ec);
        throw std::runtime_error("catalog store rename failed: " + ec.message());
    }
}

}  // namespace

void FileCatalogRepository::open(const std::filesystem::path& root) {
    file_ = root;
    file_ += ".json";
    if (!std::filesystem::exists(file_)) {
        restore_state({}, {}, {});
        return;  // fresh store
    }
    std::ifstream in(file_, std::ios::binary);
    if (!in) {
        throw std::runtime_error("cannot open catalog store: " + file_.string());
    }
    const std::string text((std::istreambuf_iterator<char>(in)),
                           std::istreambuf_iterator<char>());
    Json parsed;
    try {
        parsed = Json::parse(text);
    } catch (const std::exception& exc) {
        throw std::runtime_error("corrupt catalog store " + file_.string() +
                                 ": " + exc.what());
    }
    if (!parsed.is_object() || !parsed.contains(kStoreVersion) ||
        !parsed[kStoreVersion].is_number_integer() ||
        parsed[kStoreVersion].get<int>() != 1) {
        throw std::runtime_error("unsupported catalog store: " + file_.string());
    }
    std::vector<AssetRecord> assets;
    std::vector<VersionRecord> versions;
    std::vector<RunRecord> runs;
    if (parsed.contains("assets") && parsed["assets"].is_array()) {
        for (const Json& node : parsed["assets"]) assets.push_back(decode_asset(node));
    }
    if (parsed.contains("versions") && parsed["versions"].is_array()) {
        for (const Json& node : parsed["versions"]) {
            versions.push_back(decode_version(node));
        }
    }
    if (parsed.contains("runs") && parsed["runs"].is_array()) {
        for (const Json& node : parsed["runs"]) runs.push_back(decode_run(node));
    }
    restore_state(std::move(assets), std::move(versions), std::move(runs));
}

void FileCatalogRepository::flush() {
    if (file_.empty()) {
        throw std::runtime_error("catalog store not opened");
    }
    Json out = Json::object();
    out[kStoreVersion] = 1;
    Json assets = Json::array();
    for (const AssetRecord& asset : this->assets()) {
        assets.push_back(encode_asset(asset));
    }
    out["assets"] = std::move(assets);
    Json versions = Json::array();
    for (const VersionRecord& version : this->versions()) {
        versions.push_back(encode_version(version));
    }
    out["versions"] = std::move(versions);
    Json runs = Json::array();
    for (const RunRecord& run : this->runs()) {
        runs.push_back(encode_run(run));
    }
    out["runs"] = std::move(runs);
    std::filesystem::create_directories(file_.parent_path());
    atomic_write(file_, pwb::domain::dump_json_python_compatible(out));
}

std::string FileCatalogRepository::register_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids,
    const pwb::domain::Json& parameters,
    const std::optional<std::string>& generator_version,
    const std::string& status,
    const std::optional<std::string>& domain_task_id,
    const std::optional<std::string>& input_snapshot_hash,
    const std::optional<std::string>& actor) {
    const std::string run_id = RuntimeStore::register_run(
        operation, input_version_ids, parameters, generator_version, status,
        domain_task_id, input_snapshot_hash, actor);
    flush();
    return run_id;
}

pwb::workflow_runtime::RegisteredAssetVersion
FileCatalogRepository::register_result_asset(
    const std::string& name, const std::string& type,
    const std::string& format, const pwb::domain::Json& asset_metadata,
    const std::string& payload_json, const std::string& stage,
    const std::string& run_id, const pwb::domain::Json& version_metadata) {
    const pwb::workflow_runtime::RegisteredAssetVersion result =
        RuntimeStore::register_result_asset(name, type, format, asset_metadata,
                                            payload_json, stage, run_id,
                                            version_metadata);
    flush();
    return result;
}

std::string FileCatalogRepository::register_version(
    const std::string& asset_id, const std::string& payload_json,
    const std::string& stage,
    const std::vector<std::string>& parent_version_ids,
    const std::string& run_id, const pwb::domain::Json& metadata) {
    const std::string version_id = RuntimeStore::register_version(
        asset_id, payload_json, stage, parent_version_ids, run_id, metadata);
    flush();
    return version_id;
}

void FileCatalogRepository::update_run_status(const std::string& run_id,
                                              const std::string& status) {
    RuntimeStore::update_run_status(run_id, status);
    flush();
}

void FileCatalogRepository::update_run_status(
    const std::string& run_id, const std::string& status,
    const pwb::domain::Json& extra_parameters) {
    RuntimeStore::update_run_status(run_id, status, extra_parameters);
    flush();
}

void FileCatalogRepository::set_current_version(const std::string& asset_id,
                                                const std::string& version_id) {
    RuntimeStore::set_current_version(asset_id, version_id);
    flush();
}

void FileCatalogRepository::attach_run_output(const std::string& run_id,
                                              const std::string& version_id) {
    RuntimeStore::attach_run_output(run_id, version_id);
    flush();
}

}  // namespace pwb::closure_workflow
