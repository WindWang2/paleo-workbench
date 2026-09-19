// CatalogRepository — typed read/write over the canonical catalog.sqlite
// (db.py parity: v5 store health gating, rowid insertion order, upserts
// that preserve it, sync_state revision discipline).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/errors.hpp"

#include <cstdint>
#include <filesystem>
#include <optional>
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

    // Releases the writable sqlite handle early (save-as deletes the old
    // artifacts tree after relocation; the handle must not outlive it).
    void close() { db_.close(); }

    // Writes the catalog.json manifest (Python ADR 0056 checkpoint/export
    // contract, schema 1): full table dump + catalog_revision, atomic
    // (tmp + rename), previous manifest preserved as <name>.bak. models/
    // model_versions have no domain read model yet — their rows pass
    // through verbatim so a manifest written by this side never drops
    // registry content.
    domain::DataError export_manifest(
        const std::filesystem::path& manifest_path) const;

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

    // One-transaction publish of a run result: optional NEW asset row +
    // version row + derived tables + current pointer + run_outputs link +
    // revision bump (service.py register_result_asset parity: no
    // zero-version window). All or nothing.
    domain::DataError publish_result_transaction(
        const std::optional<DataAsset>& new_asset, const DataVersion& version,
        const domain::RunId& run_id);

    // One-transaction RAW import (conv-26; service.py import_raw parity):
    // NEW asset row + version row + derived tables + current pointer +
    // revision bump — the asset never lands without its first version, no
    // run involved. All or nothing; payload placement (and its rollback)
    // stays with the caller (ingest_exec).
    domain::DataError import_raw_transaction(const DataAsset& asset,
                                             const DataVersion& version);

    // Rewrite managed version paths after a save-as relocation (conv-26;
    // service.py rebase_artifact_paths parity): stored paths are relative
    // to the project dir and carry the `<name>.artifacts/` first segment,
    // which changes with the project name. Only the first segment is
    // touched; trash metadata original_path and model artifact_uri rows
    // are rewritten the same way. One transaction + revision bump when
    // anything changed; returns the number of rewritten values.
    int rebase_artifact_paths();

    // One-transaction run terminal flip: status + parameters merged with
    // extra (extra wins) + revision bump. NotFound when the row is absent.
    domain::DataError finish_run_transaction(
        const domain::RunId& run_id, const std::string& status,
        const domain::Json& extra_parameters);

    int current_revision() const;

    // The writable sqlite handle — db.py's module-level algorithm families
    // (apply_changes / reconcile / queries_sql free functions) take
    // Database& over one connection, exactly like the Python index
    // exposing its connection to those methods. Not const: they write.
    // CONV-31b: implemented in Wave2-A1.
    Database& writable_database();

    // ---- store.py manifest surface (R3 recon; CONV-31b) --------------------
    // All implemented in Wave2-A1.

    // db.py write_all/rebuild (1578-1586) parity: single-transaction
    // delete-and-rewrite of the whole store (crash-safe via SQLite
    // rollback). Implemented as the two-attempt rebuild orchestration over
    // apply_changes.hpp's rebuild_store (corrupt file → reset → retry).
    domain::DataError write_all(const CatalogDocument& document);

    // db.py reset (1042-1054) parity: close + best-effort unlink of the db
    // and its -journal/-wal/-shm siblings. Callers reopen afterwards.
    void reset();

    // service.py 238-261 parity: sync_state key "manifest_mtime_ns".
    // Recorded value is a decimal ns string; missing/unparsable → nullopt.
    std::optional<std::int64_t> recorded_manifest_mtime_ns() const;
    // Re-records the manifest's on-disk mtime; swallows all errors (the
    // accounting must never break a checkpoint).
    void record_manifest_mtime_ns(const std::filesystem::path& manifest_path);

    // ---- working-copy registry completion (db.py 1335-1425; #1211) --------
    // Registry truth is sqlite, NOT the document snapshot. Read sides
    // degrade silently (missing file/table → nullopt/empty). Implemented
    // in Wave2-A1.
    std::optional<WorkingCopy> get_working_copy_by_path(
        const std::string& path) const;
    // Live states (checked_out/dirty/committing), ORDER BY created_at,
    // LIMIT 1 — Python get_live_working_copy_for_source.
    std::optional<WorkingCopy> get_live_working_copy_for_source(
        const domain::VersionId& source_version_id) const;
    // Empty state list = no filter; always ORDER BY created_at.
    std::vector<WorkingCopy> list_working_copies(
        const std::vector<std::string>& states = {}) const;
    // Generative registration (db.py register_working_copy shape):
    // working_id = "wc-" + 12 hex, local-time ISO-second timestamps,
    // state = "checked_out". Bare INSERT: a UNIQUE path conflict returns
    // DuplicateOperation (the composition layer swallows it — registry is
    // bookkeeping, never a checkout gate; service.py:2351 parity).
    domain::Result<std::string> register_working_copy(
        const domain::VersionId& source_version_id, const std::string& path,
        const std::string& display_name,
        std::optional<std::int64_t> payload_mtime_ns,
        std::optional<std::int64_t> source_size_bytes);

    // ---- payload staging leases, write side (db.py 1227-1331; #1222) ------
    // A lease is protection, not a gate: acquire failure → nullopt and the
    // caller proceeds (pre-lease behavior). Timestamps are local-time ISO
    // seconds (gc.hpp default_lease_cutoff compares them lexically).
    // Implemented in Wave2-A1.
    std::optional<std::string> acquire_staging_lease(
        const std::vector<std::string>& targets,
        const std::string& kind = "register");
    void release_staging_lease(const std::string& lease_id);  // swallows
    void heartbeat_staging_lease(const std::string& lease_id);  // swallows
    int prune_stale_staging_leases(                           // deleted count
        std::optional<double> ttl_seconds = std::nullopt);     // default 3600

    // ---- model-registry + promote transactions (R7 recon) -----------------
    // Implemented in Wave2-A1. Success paths are explicit
    // DataError(ErrorCode::Ok, "").
    domain::DataError upsert_model(const Model& model);
    domain::DataError upsert_model_version(const ModelVersion& version);
    // Promote = model + model_version status flips in ONE transaction
    // (service.py promote_model: both rows or neither).
    domain::DataError promote_model_transaction(const Model& model,
                                                const ModelVersion& version);
    // Promote-version landing: version + run rows (inputs/outputs/ports) +
    // current pointer, one transaction (commit_version_transaction plus
    // the run row).
    domain::DataError commit_promote_transaction(const DataVersion& version,
                                                 const DataRun& run);
    // commit_working_copy with an optional NEW asset row in the same
    // transaction (no zero-version asset window; service.py 1821 parity).
    domain::DataError commit_working_copy_transaction(
        const std::optional<DataAsset>& new_asset, const DataVersion& version,
        const std::optional<domain::RunId>& run_id);

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

// ---- store.py CatalogStore surface (R3 recon; CONV-31b) --------------------
// Free functions over the manifest file (storage.py layout: the manifest
// lives next to the store in `<project>.artifacts/metadata/`). Implemented
// in Wave2-A1 (repository.cpp).

// .../metadata/catalog.json and .../metadata/catalog.json.bak.
std::filesystem::path catalog_manifest_file(
    const std::filesystem::path& project_path);
std::filesystem::path catalog_manifest_bak_file(
    const std::filesystem::path& project_path);

// store.py _isolate_corrupt_file (48-63): rename to
// "<name>.corrupt-YYYYmmdd-HHMMSS-<6-digit microseconds>" (local time);
// on failure returns the input path unchanged (bytes stay in place,
// best-effort like Python).
std::filesystem::path isolate_corrupt_file(const std::filesystem::path& file);

// store.py CatalogStore.load (103-155): the L1-L5 branch ladder. L2/L4
// errors carry the byte-identical Python message skeletons
//   "Catalog file is corrupt and no backup is available: <path> (<detail>)"
//   "Catalog file and its backup are both corrupt: <path> (backup error: <detail>)"
// — the parenthesized detail is parser-specific and oracle-masked. The
// document is fully typed (models/model_versions/schema_version included).
struct ManifestLoad {
    CatalogDocument document;                // empty = L5 (absent manifest)
    bool from_backup = false;                // L3
    bool repromoted_backup = false;          // L3 os.replace(bak, path) ran
    std::filesystem::path isolated;          // canonical isolate target
    std::filesystem::path isolated_backup;   // backup isolate target
};
domain::Result<ManifestLoad> load_manifest(
    const std::filesystem::path& manifest_path);

// store.py CatalogStore.save (157-229) parity: serialize (pretty=indent 2 /
// compact), the #1183 unchanged-skip (digest + on-disk mtime both equal to
// the recorded state), atomic tmp+fsync+rename, first-save .bak seeding
// (#372/C14), rotation of the previous manifest to .bak, and the restore
// ladder on failure. *state carries the _last_write pair across calls
// (null = no skip check).
struct ManifestCheckpointState {
    std::string digest;        // sha256 hex of the payload
    std::int64_t mtime_ns = 0;
    bool valid = false;
};
domain::DataError save_manifest(const std::filesystem::path& manifest_path,
                                const CatalogDocument& document,
                                bool pretty = false,
                                ManifestCheckpointState* state = nullptr);

}  // namespace pwb::catalog
