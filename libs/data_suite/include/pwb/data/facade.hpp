// DataFacade — read-only ProjectSnapshotV1 over one *.paleo.json project
// plus its catalog.sqlite index (contracts.md §3; handoff.md §2 consumer
// contract). Snapshots carry diagnostics, never throw.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace pwb::data {

namespace fs = std::filesystem;

// Runtime resolution state of one cataloged resource path.
struct ResourceStatusV1 {
    std::string id;
    std::string stored_path;
    std::string resolved_path;  // empty when resolution failed
    bool external = false;
    bool exists = false;
    std::string error;  // empty when ok
};

// Immutable read model of a project: document views + workspace projection
// + catalog contents + audit findings + every diagnostic encountered.
struct ProjectSnapshotV1 {
    fs::path project_file;  // *.paleo.json
    int schema_version = 1;
    project::ProjectMetaView meta;
    workspace::MappingWorkspaceState workspace;
    std::vector<ResourceStatusV1> resources;
    std::vector<workspace::LayerBinding> layer_bindings;
    std::string map_qgis_project_xml;  // verbatim envelope
    domain::DiagnosticList diagnostics;
    bool read_only = false;  // future schema / degraded open
    bool recovered = false;
    std::string recovery_source;
    std::vector<catalog::DataAsset> catalog_assets;
    std::vector<catalog::DataVersion> catalog_versions;
    std::vector<catalog::DataRun> catalog_runs;
    std::vector<catalog::AuditFinding> catalog_findings;
};

class DataFacade {
public:
    explicit DataFacade(fs::path project_file);

    // Commit-journal directory for this project (owned by CommitCoordinator).
    static fs::path journal_dir_for(const fs::path& project_file);

    domain::Result<ProjectSnapshotV1> open_snapshot() const;

private:
    fs::path project_file_;
};

}  // namespace pwb::data
