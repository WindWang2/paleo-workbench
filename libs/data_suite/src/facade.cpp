#include "pwb/data/facade.hpp"

#include "pwb/workspace/state.hpp"

#include <algorithm>

namespace pwb::data {

using pwb::domain::DataError;
using pwb::domain::Diagnostic;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

DataFacade::DataFacade(std::filesystem::path project_file)
    : project_file_(std::move(project_file)) {}

std::filesystem::path DataFacade::journal_dir_for(
    const std::filesystem::path& project_file) {
    return pwb::project::catalog_dir_for(project_file) / "commit_journal";
}

Result<ProjectSnapshotV1> DataFacade::open_snapshot() const {
    project::ProjectManager manager(project_file_);
    auto loaded = manager.load();
    if (!loaded.is_ok()) {
        return DataError(loaded.error().code, loaded.error().message);
    }
    ProjectSnapshotV1 snapshot;
    snapshot.project_file = project_file_;
    snapshot.recovered = loaded.value().recovered;
    snapshot.recovery_source = loaded.value().recovery_source;
    project::ProjectDocument& document = loaded.value().document;
    snapshot.schema_version = document.schema_version();
    snapshot.read_only = document.read_only();
    if (auto meta = document.meta()) {
        snapshot.meta = *meta;
    }
    snapshot.diagnostics = document.diagnostics();
    snapshot.workspace = workspace::MappingWorkspaceState::from_json(
        document.mapping_workspace(), snapshot.diagnostics);
    snapshot.layer_bindings = snapshot.workspace.catalog_bindings();
    snapshot.map_qgis_project_xml =
        document.find_section("map_qgis_project_xml") != nullptr &&
                document.find_section("map_qgis_project_xml")->is_string()
            ? document.find_section("map_qgis_project_xml")
                  ->get<std::string>()
            : "";

    for (const auto& resolved :
         project::resolve_resource_paths(document, project_file_)) {
        ResourceStatusV1 status;
        status.id = resolved.id;
        status.stored_path = resolved.stored;
        status.resolved_path = resolved.resolved;
        status.external = resolved.external;
        status.exists = resolved.exists;
        status.error = resolved.error;
        snapshot.resources.push_back(std::move(status));
        if (!resolved.error.empty() && resolved.error != "missing_file") {
            snapshot.diagnostics.push_back(Diagnostic::warning(
                "resource_unresolvable",
                "resource " + resolved.id + " path '" + resolved.stored +
                    "' → " + resolved.error));
        } else if (resolved.error == "missing_file") {
            snapshot.diagnostics.push_back(Diagnostic::warning(
                "resource_missing",
                "resource " + resolved.id + " file missing: " +
                    resolved.resolved));
        }
    }

    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file_));
    auto catalog = repository.open_read_only();
    if (catalog.is_ok()) {
        snapshot.catalog_assets = std::move(catalog.value().assets);
        snapshot.catalog_versions = std::move(catalog.value().versions);
        snapshot.catalog_runs = std::move(catalog.value().runs);
        std::vector<pwb::catalog::WorkspaceBindingRef> bindings;
        for (const auto& binding : snapshot.layer_bindings) {
            bindings.push_back({binding.layer_id, binding.source_asset_id,
                                binding.source_version_id});
        }
        snapshot.catalog_findings = pwb::catalog::audit_catalog(
            catalog.value(), project_file_, bindings);
        for (const auto& finding : snapshot.catalog_findings) {
            snapshot.diagnostics.push_back(Diagnostic::warning(
                finding.code, finding.message, finding.detail));
        }
    } else if (catalog.error().code != ErrorCode::NotFound) {
        snapshot.diagnostics.push_back(Diagnostic::error(
            "catalog_unreadable", catalog.error().message));
    }
    return snapshot;
}

}  // namespace pwb::data
