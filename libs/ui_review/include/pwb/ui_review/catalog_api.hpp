#pragma once

// UI-11 — catalog service seam (abstract api) for the review/governance
// dialogs. Python's ``service`` argument is a DataCatalogService; the C++
// dialogs depend only on these plain-DTO reads/mutations, so tests can
// drive them with an in-memory fake and wiring binds the real
// catalog-repository adapter in the integration slice.
//
// DTOs are the libs/catalog models directly (DataVersion / DataAsset /
// DataRun / MissingSourceReport / AuditReport) — plain data, no Qt.

#include "pwb/catalog/audit.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sources.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_review {

// resolve_path(version) projection — Python returns a Path whose
// ``.is_file()`` the dialogs probe; the seam reports both halves so a
// binding never has to leak a filesystem opinion it cannot answer.
struct ResolvedPath {
    std::string path;
    bool is_file = false;
};

// One ``service.get_lineage(version_id)`` hop — the dict shape Python
// returns ({version, run, parents, children}).
struct LineageHop {
    catalog::DataVersion version;
    std::optional<catalog::DataRun> run;
    std::vector<catalog::DataVersion> parents;
    std::vector<catalog::DataVersion> children;
};

class ICatalogApi {
public:
    virtual ~ICatalogApi() = default;

    // ---- reads ------------------------------------------------------------
    // std::nullopt mirrors the Python ``except CatalogError: None`` paths
    // (purged zombie objects degrade to the raw id, never crash the UI).
    virtual std::optional<catalog::DataVersion>
    get_version(const std::string& version_id) = 0;
    virtual std::optional<catalog::DataAsset>
    get_asset(const std::string& asset_id) = 0;
    virtual std::optional<LineageHop>
    get_lineage(const std::string& version_id) = 0;
    virtual ResolvedPath
    resolve_path(const catalog::DataVersion& version) = 0;
    virtual std::vector<catalog::DataVersion>
    list_versions(const std::string& asset_id) = 0;

    // ---- version-workbench mutations --------------------------------------
    virtual domain::DataError
    promote_version(const std::string& version_id) = 0;
    virtual domain::DataError
    trash_version(const std::string& version_id, const std::string& reason) = 0;
    virtual domain::DataError
    restore_version(const std::string& version_id) = 0;

    // ---- missing-source scan + relink --------------------------------------
    virtual catalog::MissingSourceReport
    find_missing_sources(const std::function<bool()>& cancel) = 0;
    // The Python dialog distinguishes CatalogRelinkIdentityError (identity
    // unprovable → ConflictBaseVersion here) from other exceptions (other
    // codes) when it renders per-row reasons — the code carries that split.
    virtual domain::DataError relink_external_source(
        const std::string& version_id,
        const std::filesystem::path& new_path) = 0;

    // ---- audit --------------------------------------------------------------
    virtual catalog::AuditReport
    audit(bool deep, const std::function<bool()>& cancel) = 0;
};

}  // namespace pwb::ui_review
