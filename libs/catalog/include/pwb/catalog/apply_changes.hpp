// Generic dirty-set write channel over the canonical catalog.sqlite
// (conv-31b; db.py DirtySet / apply_changes / reconcile / rebuild / sync /
// is_fresh / reset parity — R1 recon contract, frozen 31b-findings).
//
// Every entrypoint runs ONE BEGIN IMMEDIATE transaction (sqlite.hpp
// Transaction); the #1220 revision CAS compares INSIDE the transaction
// (at most one conflicting writer ever commits, zero write amplification
// on the conflict path). A stale baseline surfaces as
//   DataError{ConflictBaseVersion, <byte-identical Chinese message>,
//             detail["stale_write"] = true}
// — recognize it with is_stale_write(). sync_store() never self-heals that
// error (Python's CatalogStaleWriteError is an OSError, invisible to the
// `except sqlite3.DatabaseError` recovery branch).
//
// The mark order of DirtySet is load-bearing: `_ordered` keeps existing
// rows at their rowid and appends new ids in mark order, so a store read
// back with ORDER BY rowid preserves the document mutation order
// (findings §C-1). Rowid + serialization constants live in apply_changes.cpp
// (one serialization per table, shared with reconcile/rebuild).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::catalog {

// ---- DirtySet (db.py:756-829) ----------------------------------------------
// Eight insertion-ordered id buckets: mark_* is idempotent and a repeat
// mark does NOT move the id (Python dict semantics — first-seen position
// wins). asset_tags / version_tags hold OWNER ids whose tag association
// changed. An id absent from the document means "delete".
// CONV-31b: implemented in Wave2-A2.
struct DirtySet {
    std::vector<std::string> assets;
    std::vector<std::string> versions;
    std::vector<std::string> runs;
    std::vector<std::string> tags;
    std::vector<std::string> models;
    std::vector<std::string> model_versions;
    std::vector<std::string> asset_tags;
    std::vector<std::string> version_tags;

    void mark_asset(std::string_view id);
    void mark_version(std::string_view id);
    void mark_run(std::string_view id);
    void mark_tag(std::string_view id);
    void mark_model(std::string_view id);
    void mark_model_version(std::string_view id);
    void mark_asset_tags(std::string_view owner_id);
    void mark_version_tags(std::string_view owner_id);

    // First-seen order, self before other (db.py DirtySet.merge).
    void merge(const DirtySet& other);
    bool is_empty() const;
};

// Unified save seam for the 31b collaborator modules (trash_service /
// model_registry / asset_metadata / v11_bundle): the module computes its
// own dirty set (service.py `_save(DirtySet)` parity); a non-ok return
// triggers the module's in-memory rollback. tags.hpp's zero-arg
// TagSaveHook is the shipped predecessor and stays as is.
using SaveHook = std::function<domain::DataError(const DirtySet&)>;

// Programmable identity of the CatalogStaleWriteError channel (findings
// §C-3): ConflictBaseVersion + detail["stale_write"]. Message texts stay
// byte-identical Chinese for users; code never string-matches.
inline bool is_stale_write(const domain::DataError& error) {
    return error.code == domain::ErrorCode::ConflictBaseVersion &&
           error.detail.is_object() &&
           error.detail.value("stale_write", false);
}

// ---- apply_changes (db.py:1951-2177) ---------------------------------------
// O(Δ) id→object maps from the caller's incrementally-maintained indexes
// (service _ensure_maps parity). Null pointers (or absent entries) fall
// back to a full scan over the document (Python `or {}` semantics). The
// maps point INTO *document; it must stay immutable for the call.
struct ApplyLookups {
    const std::unordered_map<std::string, const DataAsset*>* assets = nullptr;
    const std::unordered_map<std::string, const DataVersion*>* versions =
        nullptr;
    const std::unordered_map<std::string, const DataRun*>* runs = nullptr;
};

struct ApplyChangesOptions {
    ApplyLookups lookups;
    // In-transaction CAS against sync_state 'catalog_revision'; nullopt =
    // no comparison. 0 with a missing/unparsable stored key is a conflict.
    std::optional<long long> expected_revision;
};

// Commits *dirty* in one transaction: ids present in the document are
// upserted (existing rows keep their rowid, new ids append in mark
// order), absent ids are deleted together with their dependent rows;
// lineage is reconciled per touched version/run with the same keep-rules
// as a full rebuild (run-derived edges survive a version-side wipe).
// Schema missing (no sync_state table) → delegates to the rebuild path.
// Net effect == write_all restricted to the dirty set.
// CONV-31b: implemented in Wave2-A2.
domain::DataError apply_changes(Database& db, const CatalogDocument& document,
                                const DirtySet& dirty,
                                const ApplyChangesOptions& options = {});

// ---- reconcile (db.py:2313-2475) --------------------------------------------
// O(N) full diff (six tables via _symmetric_diff, tag associations as
// sets, run io/ports/members drift) feeding the SAME apply_changes
// channel; an empty diff still refreshes the three sync_state keys under
// the same CAS contract (the "同步" message variant). The lineage table
// itself is not diffed (documented Python limitation).
domain::DataError reconcile(Database& db, const CatalogDocument& document,
                            std::optional<long long> expected_revision =
                                std::nullopt);

// ---- rebuild family (db.py:1471-1487 / 2477-2604 / 1578-1586 / 1042-1054) --
// One-transaction full rewrite: ensure_schema → _DELETE_ORDER wipe →
// document-order inserts → three-key stamp. No CAS (rebuild overwrites).
domain::DataError rebuild_once(Database& db, const CatalogDocument& document);

// Best-effort removal of the db plus its ""/-journal/-wal/-shm siblings
// (ENOENT and other OS errors swallowed). The caller must have closed
// every handle to the file first (WAL unlink semantics).
void reset_store_files(const std::filesystem::path& db_path);

// The two-attempt rebuild orchestration (attempt 0; CorruptDatabase →
// reset_store_files → attempt 1; still failing → error). Opens and closes
// its own connection — callers pass a path, not a live Database.
domain::DataError rebuild_store(const std::filesystem::path& db_path,
                                const CatalogDocument& document);

// ---- sync / is_fresh / revision (db.py:1449-1467 / 1427-1447 / 1210-1218) --
// Returns whether a change happened. Self-heals ONLY the CorruptDatabase
// family (SQLITE_CORRUPT*/NOTADB/READONLY — findings §C/B-9) via
// reset+rebuild; stale writes and argument errors pass through.
domain::Result<bool> sync_store(Database& db,
                                const std::filesystem::path& db_path,
                                const CatalogDocument& document);

// The three-key gate: stored revision == document.catalog_revision AND
// schema_version == document.schema_version AND index_schema_version ==
// kStoreSchemaVersion (equality, not a floor — two different gates, see
// db.py:292-310).
bool is_fresh(Database& db, const CatalogDocument& document);

// nullopt = the unified "missing / unparsable / unreadable" sentinel of
// db.py revision() / _read_sync_state (None in Python).
std::optional<long long> read_revision(Database& db);
std::optional<long long> read_sync_state(Database& db, std::string_view key);

}  // namespace pwb::catalog
