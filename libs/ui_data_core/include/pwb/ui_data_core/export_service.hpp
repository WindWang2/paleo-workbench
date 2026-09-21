#pragma once

// CONV-36 — resources/export_service.py port (Qt-free half).
//
// The widget/duck-type half of export_service.py (view_export_capabilities,
// _resolve_export_target, _export_widget_*, export_widget_snapshot) probes
// Qt objects at runtime — that stays in the Qt shell. This header carries
// the Qt-free orchestration: ExportJobResult, asset→file export through the
// interchange converter table, project inventory JSON export, the
// record_export seam (domain artifact + defensive catalog registration),
// and the io_registry format tables.
//
// Catalog parity: Python resolves register_export_output through
// get_catalog() and degrades to "domain artifact only" when no backend is
// active. Here the registrar is injected; an empty std::function is the
// "no catalog backend" state. Registrar exceptions are swallowed into
// catalog_version_id=None — provenance loss never breaks the export path
// (matching _register_catalog_output's defensive wrap).

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/project/document.hpp>
#include <pwb/ui_data_core/asset_view.hpp>

namespace pwb::ui_data_core {

namespace fs = std::filesystem;

// export_service.ExportJobResult parity.
struct ExportJobResult {
    bool success = false;
    std::string output_path;
    std::string format;
    std::optional<ExportArtifact> artifact;
    std::string message;
    std::vector<std::string> warnings;
};

// ---------------------------------------------------------------------------
// io_registry tables
// ---------------------------------------------------------------------------

// ExportFormatSpec parity.
struct ViewExportFormatSpec {
    std::string label;       // shown in menus, e.g. "PNG"
    std::string extension;   // ".png"
    std::string category;    // "convert" | "engine" | "project"
    std::string description;
};

// VIEW_EXPORT_FORMATS parity (PNG/SVG/PDF engine row set).
const std::vector<ViewExportFormatSpec>& view_export_formats();

// _view_format_rank parity: PNG→0, SVG→1, PDF→2, else 99 (case-insensitive).
int view_format_rank(std::string_view label);

// ---------------------------------------------------------------------------
// Catalog registration seam
// ---------------------------------------------------------------------------

// What the catalog registrar needs to register an OUTPUT DataVersion —
// mirrors register_export_output's kwargs. `declared_ids` is the resolved
// lineage input list (source_resource_ids + linked_id + source_task_ids,
// deduped, order preserved).
struct CatalogExportRequest {
    std::string name;          // Path(output_path).name at call time
    std::string output_path;   // absolute path used for hashing/integrity
    std::string format;
    std::vector<std::string> declared_ids;
    std::string linked_id;
};

// Returns the registered DataVersion id, or std::nullopt when no catalog
// backend is active. Throwing is allowed — record_export swallows it into
// catalog_version_id=None like Python's try/except.
using CatalogExportFn =
    std::function<std::optional<std::string>(const CatalogExportRequest&)>;

// ---------------------------------------------------------------------------
// Export operations
// ---------------------------------------------------------------------------

// get_available_formats label list (list_asset_export_labels parity).
std::vector<std::string> list_asset_export_labels(std::string_view format);

// record_export parity: append a fresh ExportArtifact (id
// "artifact_<12hex>", generated_at now-iso) to the project's
// export_artifacts section, then run the catalog seam defensively.
// Returns the domain artifact either way.
ExportArtifact record_export(
    project::ProjectDocument& project, std::string linked_id,
    std::string output_path, std::string fmt,
    std::vector<std::string> source_task_ids,
    std::vector<std::string> source_resource_ids = {},
    const CatalogExportFn& register_catalog = {},
    std::string_view catalog_output_path = {});

// export_asset_to_path parity: resolve the stored path against the project
// (or CWD fallback), dispatch the registered converter, optionally record
// the artifact. `source_task_ids` propagates real lineage.
ExportJobResult export_asset_to_path(
    const ResourceItem& asset, std::string_view format_label,
    const fs::path& output_path, project::ProjectDocument* project = nullptr,
    const fs::path* project_path = nullptr, bool do_register = true,
    std::vector<std::string> source_task_ids = {},
    const CatalogExportFn& register_catalog = {});

// export_project_inventory parity: resources + export_artifacts inventory
// JSON written through the atomic output path; registers an
// "inventory.json" artifact.
ExportJobResult export_project_inventory(
    project::ProjectDocument& project, const fs::path& output_path,
    const fs::path* project_path = nullptr, bool do_register = true,
    const CatalogExportFn& register_catalog = {});

// register_exported_view parity: record an already-written view export
// (rendering happened elsewhere — the Qt shell owns that). `surface_kind`
// is the resolved _export_surface_kind value ("well_log", "unified_map",…).
std::optional<ExportArtifact> register_exported_view(
    std::string_view surface_kind, const fs::path& output_path,
    std::string_view format_label, project::ProjectDocument* project,
    const fs::path* project_path, std::string_view linked_id = "viz_view",
    bool do_register = true, std::vector<std::string> source_task_ids = {},
    const CatalogExportFn& register_catalog = {});

// default_export_dir parity: ~/paleo_exports without a project, else
// <project>/exports (artifact layout ensured first).
fs::path default_export_dir(const fs::path* project_path);

}  // namespace pwb::ui_data_core
