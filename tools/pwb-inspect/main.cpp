// pwb-inspect — read-only compatibility inspector + explicit recovery.
//
// Exit codes (contracts.md §8 + v3-contracts.md §7): 0 ok / 2 usage /
// 3 unreadable-corrupt (or recovery refused on a read-only project) /
// 4 future schema (diagnostics still printed) / 5 internal /
// 6 recovery ran but journals remain pending.
#include "pwb/catalog/repository.hpp"
#include "pwb/data/contracts.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <iostream>
#include <string>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

int usage() {
    std::cerr << "usage: pwb-inspect --project <file.paleo.json> "
                 "[--format json|text]\n"
                 "                --asset <id> | --version <id> | "
                 "--run <id> | --provenance <version_id>\n"
                 "                --recover   (explicit writable recovery)\n";
    return 2;
}

void emit_json(const pwb::data::ProjectSnapshotV1& snapshot) {
    Json out = Json::object();
    out["project"] = snapshot.project_file.generic_string();
    out["schema_version"] = snapshot.schema_version;
    out["read_only"] = snapshot.read_only;
    out["recovered"] = snapshot.recovered;
    if (snapshot.recovered) {
        out["recovery_source"] = snapshot.recovery_source;
    }
    out["meta"] = Json{
        {"name", snapshot.meta.name},
        {"region", snapshot.meta.region},
        {"app_version", snapshot.meta.app_version},
        {"updated_at", snapshot.meta.updated_at}};
    Json bindings = Json::array();
    for (const auto& binding : snapshot.layer_bindings) {
        bindings.push_back(
            {{"layer_id", binding.layer_id},
             {"role", binding.role},
             {"asset_id", binding.source_asset_id},
             {"version_id", binding.source_version_id},
             {"binding_kind",
              std::string(pwb::workspace::effective_binding_kind(binding))},
             {"bound_at", binding.bound_at}});
    }
    out["layer_bindings"] = std::move(bindings);
    Json resources = Json::array();
    for (const auto& resource : snapshot.resources) {
        resources.push_back(
            {{"id", resource.id},
             {"stored", resource.stored_path},
             {"resolved", resource.resolved_path},
             {"external", resource.external},
             {"exists", resource.exists},
             {"error", resource.error}});
    }
    out["resources"] = std::move(resources);
    out["catalog_assets"] = snapshot.catalog_assets.size();
    out["catalog_versions"] = snapshot.catalog_versions.size();
    out["catalog_runs"] = snapshot.catalog_runs.size();
    Json findings = Json::array();
    for (const auto& finding : snapshot.catalog_findings) {
        findings.push_back({{"code", finding.code},
                            {"message", finding.message}});
    }
    out["catalog_findings"] = std::move(findings);
    Json lineage = Json::array();
    for (const auto& run : snapshot.catalog_runs) {
        Json inputs = Json::array();
        for (const auto& input : run.input_version_ids) inputs.push_back(input.str());
        Json outputs = Json::array();
        for (const auto& output : run.output_version_ids) {
            outputs.push_back(output.str());
        }
        lineage.push_back({{"run_id", run.id.str()},
                           {"operation", run.operation},
                           {"status", run.status},
                           {"inputs", std::move(inputs)},
                           {"outputs", std::move(outputs)}});
    }
    out["lineage"] = std::move(lineage);
    Json diagnostics = Json::array();
    for (const auto& diagnostic : snapshot.diagnostics) {
        diagnostics.push_back(diagnostic.to_json());
    }
    out["diagnostics"] = std::move(diagnostics);
    std::cout << out.dump(2) << "\n";
}

void emit_text(const pwb::data::ProjectSnapshotV1& snapshot) {
    std::cout << "project: " << snapshot.project_file.generic_string()
              << "\n";
    std::cout << "schema_version: " << snapshot.schema_version
              << (snapshot.read_only ? " (read-only)" : "") << "\n";
    std::cout << "bindings: " << snapshot.layer_bindings.size() << "\n";
    std::cout << "resources: " << snapshot.resources.size() << "\n";
    std::cout << "catalog: " << snapshot.catalog_assets.size() << " assets / "
              << snapshot.catalog_versions.size() << " versions / "
              << snapshot.catalog_runs.size() << " runs\n";
    std::cout << "findings: " << snapshot.catalog_findings.size() << "\n";
    for (const auto& diagnostic : snapshot.diagnostics) {
        std::cout << "  [" << pwb::domain::to_string(diagnostic.severity)
                  << "] " << diagnostic.code << ": " << diagnostic.message
                  << "\n";
    }
}

Json version_row_json(const pwb::catalog::DataVersion& version) {
    Json json = Json::object();
    json["id"] = version.id.str();
    json["asset_id"] = version.asset_id.str();
    json["version_number"] = version.version_number;
    json["stage"] = std::string(pwb::domain::to_string(version.stage));
    json["managed"] = version.managed;
    json["path"] = version.path;
    json["format"] = version.format;
    json["size_bytes"] =
        version.size_bytes.has_value() ? Json(*version.size_bytes)
                                       : Json(nullptr);
    json["sha256"] =
        version.sha256.has_value() ? Json(*version.sha256) : Json(nullptr);
    json["run_id"] = version.run_id.has_value() ? Json(version.run_id->str())
                                                : Json(nullptr);
    json["metadata"] = version.metadata;
    json["created_at"] = version.created_at;
    json["parent_version_ids"] = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        json["parent_version_ids"].push_back(parent.str());
    }
    return json;
}

Json asset_row_json(const pwb::catalog::DataAsset& asset) {
    Json json = Json::object();
    json["id"] = asset.id.str();
    json["name"] = asset.name;
    json["type"] = asset.type;
    json["description"] = asset.description;
    json["current_version_id"] =
        asset.current_version_id.has_value()
            ? Json(asset.current_version_id->str())
            : Json(nullptr);
    json["metadata"] = asset.metadata;
    json["created_at"] = asset.created_at;
    json["updated_at"] = asset.updated_at;
    return json;
}

// Opens the catalog read-only for the query modes (zero writes: no WAL
// switch, no pragma churn — SqliteOpenMode::ReadOnly).
pwb::domain::Result<pwb::catalog::CatalogDocument> open_catalog(
    const fs::path& project_file) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    return repository.open_read_only();
}

int query_asset(const fs::path& project_file, const std::string& id) {
    auto catalog = open_catalog(project_file);
    if (!catalog.is_ok()) {
        std::cerr << "pwb-inspect: " << catalog.error().message << "\n";
        return 3;
    }
    const pwb::catalog::DataAsset* asset =
        catalog.value().find_asset(pwb::domain::AssetId(id));
    if (asset == nullptr) {
        std::cerr << "pwb-inspect: asset not found: " << id << "\n";
        return 3;
    }
    Json out = asset_row_json(*asset);
    out["versions"] = Json::array();
    for (const auto& version : catalog.value().versions) {
        if (version.asset_id == asset->id) {
            out["versions"].push_back(version_row_json(version));
        }
    }
    std::cout << out.dump(2) << "\n";
    return 0;
}

int query_version(const fs::path& project_file, const std::string& id) {
    auto catalog = open_catalog(project_file);
    if (!catalog.is_ok()) {
        std::cerr << "pwb-inspect: " << catalog.error().message << "\n";
        return 3;
    }
    const pwb::catalog::DataVersion* version =
        catalog.value().find_version(pwb::domain::VersionId(id));
    if (version == nullptr) {
        std::cerr << "pwb-inspect: version not found: " << id << "\n";
        return 3;
    }
    std::cout << version_row_json(*version).dump(2) << "\n";
    return 0;
}

int query_run(const fs::path& project_file, const std::string& id) {
    auto catalog = open_catalog(project_file);
    if (!catalog.is_ok()) {
        std::cerr << "pwb-inspect: " << catalog.error().message << "\n";
        return 3;
    }
    const pwb::catalog::DataRun* run =
        catalog.value().find_run(pwb::domain::RunId(id));
    if (run == nullptr) {
        std::cerr << "pwb-inspect: run not found: " << id << "\n";
        return 3;
    }
    pwb::data::RunStateV1 state;
    state.run_id = run->id;
    state.operation = run->operation;
    state.generator = run->generator;
    state.status = run->status;
    state.input_version_ids = run->input_version_ids;
    state.output_version_ids = run->output_version_ids;
    state.input_ports = run->input_ports;
    state.output_ports = run->output_ports;
    state.parameters = run->parameters;
    state.model_ref = run->model_ref;
    state.created_at = run->created_at;
    std::cout << pwb::data::run_state_to_json(state).dump(2) << "\n";
    return 0;
}

int query_provenance(const fs::path& project_file,
                     const std::string& version_id) {
    auto catalog = open_catalog(project_file);
    if (!catalog.is_ok()) {
        std::cerr << "pwb-inspect: " << catalog.error().message << "\n";
        return 3;
    }
    const pwb::catalog::DataVersion* version =
        catalog.value().find_version(pwb::domain::VersionId(version_id));
    if (version == nullptr) {
        std::cerr << "pwb-inspect: version not found: " << version_id
                  << "\n";
        return 3;
    }
    Json out = Json::object();
    out["project"] = project_file.generic_string();
    out["version"] = version_row_json(*version);
    // Result file envelope: bytes + hash + size (B owns bytes, A owns the
    // numeric encoding; metadata rides verbatim in version.metadata).
    Json file = Json::object();
    file["path"] = version->path;
    std::error_code ec;
    const fs::path resolved =
        fs::path(pwb::project::project_dir_for(project_file)) /
        pwb::project::path_from_u8(version->path);
    file["resolved"] = pwb::project::path_to_u8(resolved);
    file["exists"] = fs::is_regular_file(resolved, ec);
    if (file["exists"].get<bool>()) {
        const auto digest = pwb::domain::Sha256::of_file(resolved);
        file["sha256_measured"] =
            digest.has_value() ? Json(*digest) : Json(nullptr);
        file["size_bytes_measured"] =
            fs::file_size(resolved, ec);
    }
    out["file"] = std::move(file);
    if (version->run_id.has_value()) {
        if (const pwb::catalog::DataRun* run =
                catalog.value().find_run(*version->run_id)) {
            out["run"] = Json{{"run_id", run->id.str()},
                              {"operation", run->operation},
                              {"generator", run->generator},
                              {"status", run->status},
                              {"parameters", run->parameters},
                              {"created_at", run->created_at}};
        }
    } else {
        out["run"] = Json(nullptr);
    }
    Json parents = Json::array();
    for (const auto& parent : version->parent_version_ids) {
        parents.push_back(parent.str());
    }
    out["lineage"] = Json{{"parents", std::move(parents)}};
    std::cout << out.dump(2) << "\n";
    return 0;
}

int run_recovery(const fs::path& project_file) {
    auto session = pwb::data::WritableSession::open(project_file);
    if (!session.is_ok()) {
        std::cerr << "pwb-inspect: recovery refused: "
                  << session.error().message << "\n";
        return 3;
    }
    pwb::data::RecoveryReportV1 report = session.value().recover();
    Json out = Json::object();
    out["continued"] = report.continued;
    out["rolled_back"] = report.rolled_back;
    out["pending"] = report.pending;
    Json diagnostics = Json::array();
    for (const auto& diagnostic : report.diagnostics) {
        diagnostics.push_back(diagnostic.to_json());
    }
    out["diagnostics"] = std::move(diagnostics);
    std::cout << out.dump(2) << "\n";
    return report.pending.empty() ? 0 : 6;
}

}  // namespace

int main(int argc, char** argv) {
    std::string project_arg;
    std::string format = "json";
    std::string asset_arg;
    std::string version_arg;
    std::string run_arg;
    std::string provenance_arg;
    bool recover = false;
    for (int i = 1; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--project" && i + 1 < argc) {
            project_arg = argv[++i];
        } else if (flag == "--format" && i + 1 < argc) {
            format = argv[++i];
        } else if (flag == "--asset" && i + 1 < argc) {
            asset_arg = argv[++i];
        } else if (flag == "--version" && i + 1 < argc) {
            version_arg = argv[++i];
        } else if (flag == "--run" && i + 1 < argc) {
            run_arg = argv[++i];
        } else if (flag == "--provenance" && i + 1 < argc) {
            provenance_arg = argv[++i];
        } else if (flag == "--recover") {
            recover = true;
        } else {
            return usage();
        }
    }
    if (project_arg.empty() || (format != "json" && format != "text")) {
        return usage();
    }
    const int query_flags = (asset_arg.empty() ? 0 : 1) +
                            (version_arg.empty() ? 0 : 1) +
                            (run_arg.empty() ? 0 : 1) +
                            (provenance_arg.empty() ? 0 : 1) +
                            (recover ? 1 : 0);
    if (query_flags > 1) return usage();
    std::filesystem::path project_file(project_arg);
    if (!std::filesystem::is_regular_file(project_file)) {
        std::cerr << "pwb-inspect: project file not found: " << project_arg
                  << "\n";
        return 3;
    }
    if (recover) return run_recovery(project_file);
    if (!asset_arg.empty()) return query_asset(project_file, asset_arg);
    if (!version_arg.empty()) return query_version(project_file, version_arg);
    if (!run_arg.empty()) return query_run(project_file, run_arg);
    if (!provenance_arg.empty()) {
        return query_provenance(project_file, provenance_arg);
    }
    pwb::data::DataFacade facade(project_file);
    auto snapshot = facade.open_snapshot();
    if (!snapshot.is_ok()) {
        std::cerr << "pwb-inspect: " << snapshot.error().message << "\n";
        return 3;
    }
    if (format == "json") {
        emit_json(snapshot.value());
    } else {
        emit_text(snapshot.value());
    }
    return snapshot.value().read_only ? 4 : 0;
}
