// pwb-inspect — read-only compatibility inspector.
//
// Exit codes (contracts.md §8): 0 ok / 2 usage / 3 unreadable-corrupt /
// 4 future schema (diagnostics still printed) / 5 internal.
#include "pwb/catalog/repository.hpp"
#include "pwb/data/contracts.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <iostream>
#include <string>

namespace {

int usage() {
    std::cerr << "usage: pwb-inspect --project <file.paleo.json> "
                 "[--format json|text]\n";
    return 2;
}

void emit_json(const pwb::data::ProjectSnapshotV1& snapshot) {
    pwb::domain::Json out = pwb::domain::Json::object();
    out["project"] = snapshot.project_file.generic_string();
    out["schema_version"] = snapshot.schema_version;
    out["read_only"] = snapshot.read_only;
    out["recovered"] = snapshot.recovered;
    if (snapshot.recovered) {
        out["recovery_source"] = snapshot.recovery_source;
    }
    out["meta"] = pwb::domain::Json{
        {"name", snapshot.meta.name},
        {"region", snapshot.meta.region},
        {"app_version", snapshot.meta.app_version},
        {"updated_at", snapshot.meta.updated_at}};
    pwb::domain::Json bindings = pwb::domain::Json::array();
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
    pwb::domain::Json resources = pwb::domain::Json::array();
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
    pwb::domain::Json findings = pwb::domain::Json::array();
    for (const auto& finding : snapshot.catalog_findings) {
        findings.push_back({{"code", finding.code},
                            {"message", finding.message}});
    }
    out["catalog_findings"] = std::move(findings);
    pwb::domain::Json lineage = pwb::domain::Json::array();
    for (const auto& run : snapshot.catalog_runs) {
        pwb::domain::Json inputs = pwb::domain::Json::array();
        for (const auto& input : run.input_version_ids) inputs.push_back(input.str());
        pwb::domain::Json outputs = pwb::domain::Json::array();
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
    pwb::domain::Json diagnostics = pwb::domain::Json::array();
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

}  // namespace

int main(int argc, char** argv) {
    std::string project_arg;
    std::string format = "json";
    for (int i = 1; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--project" && i + 1 < argc) {
            project_arg = argv[++i];
        } else if (flag == "--format" && i + 1 < argc) {
            format = argv[++i];
        } else {
            return usage();
        }
    }
    if (project_arg.empty() || (format != "json" && format != "text")) {
        return usage();
    }
    std::filesystem::path project_file(project_arg);
    if (!std::filesystem::is_regular_file(project_file)) {
        std::cerr << "pwb-inspect: project file not found: " << project_arg
                  << "\n";
        return 3;
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
