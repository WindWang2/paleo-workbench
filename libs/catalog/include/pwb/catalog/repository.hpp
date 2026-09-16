// CatalogRepository — typed read/write over the canonical catalog.sqlite
// (db.py parity: v5 store health gating, rowid insertion order, upserts
// that preserve it, sync_state revision discipline).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace pwb::catalog {

enum class StoreHealth { Canonical, Legacy, Missing, Corrupt, Unreadable };

struct StoreStatus {
    StoreHealth health = StoreHealth::Missing;
    int index_schema_version = 0;   // 0 when unreadable
    int catalog_revision = 0;
    std::string detail;
};

class CatalogRepository {
public:
    explicit CatalogRepository(std::filesystem::path sqlite_path);

    // Read-only probe: sync_state strictly readable + index_schema_version
    // >= 5 → Canonical (db.py load_document floor semantics).
    StoreStatus status() const;

    // Opens read-write (creating parents + schema on demand) and loads the
    // full document. Corrupt → error, never a silent rebuild.
    domain::Result<CatalogDocument> open_read_write();
    // Read-only load (no schema creation, no WAL switch).
    domain::Result<CatalogDocument> open_read_only() const;

    const std::filesystem::path& path() const { return sqlite_path_; }

    // ---- write paths (each is one transaction + revision bump) ----------
    domain::DataError upsert_asset(const DataAsset& asset);
    domain::DataError upsert_version(const DataVersion& version);
    domain::DataError upsert_run(const DataRun& run);
    domain::DataError set_current_version(const domain::AssetId& asset_id,
                                          const domain::VersionId& version_id,
                                          const std::string& updated_at);
    domain::DataError insert_working_copy(const WorkingCopy& copy);
    domain::DataError remove_working_copy(const std::string& working_id);
    domain::DataError set_working_copy_state(const std::string& working_id,
                                             const std::string& state);

    // One-transaction commit of a new version: version row + derived
    // tables + current pointer + run output linkage + revision bump. All
    // or nothing (db.py write discipline).
    domain::DataError commit_version_transaction(
        const DataVersion& version, const domain::AssetId& asset_id,
        const std::optional<domain::RunId>& run_id);

    int current_revision() const;

private:
    domain::DataError upsert_asset_in_transaction(const DataAsset& asset);
    domain::DataError upsert_version_rows(const DataVersion& version);
    domain::DataError upsert_run_rows(const DataRun& run);
    domain::Result<CatalogDocument> load_document(SqliteOpenMode mode) const;
    domain::Result<CatalogDocument> load_document_from(Database& db) const;
    domain::DataError bump_revision();

    std::filesystem::path sqlite_path_;
    Database db_;
};

// ---- consistency audit (queries/audit parity subset) --------------------

// Minimal binding reference for cross-store checks (filled by the caller
// from the project document; the catalog library never reads .paleo.json).
struct WorkspaceBindingRef {
    std::string layer_id;
    std::string asset_id;
    std::string version_id;
};

struct AuditFinding {
    std::string code;     // orphan_version | dangling_current | ...
    std::string message;
    domain::Json detail = domain::Json::object();
};

std::vector<AuditFinding> audit_catalog(
    const CatalogDocument& document,
    const std::filesystem::path& project_path,
    const std::vector<WorkspaceBindingRef>& bindings = {});

}  // namespace pwb::catalog
