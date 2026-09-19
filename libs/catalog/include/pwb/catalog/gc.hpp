// Conservative GC for the `<project>.artifacts/` tree (conv-15; gc.py
// parity). plan_gc classifies orphaned files with ZERO deletion; sweep_gc
// deletes only the safe classes; cleanup_working_copies is the explicit
// working-copy hook. Invariants carried over verbatim:
//
// - A reachable committed DataVersion payload is NEVER deleted (referenced
//   paths derive from the document before any sweep).
// - External source files are never touched (they live outside artifacts/).
// - Working copies are user work: only the explicit hook removes them, and
//   only when the version id does not exist at all.
// - Temp-named files that a version references are never orphans (#889), and
//   the temp scan never descends into working/ or trash/.
//
// Paths in reports are project-dir-relative POSIX strings (the same shape a
// DataVersion.path uses), so reports are directly comparable across machines.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"  // CONV-31b: live lease read (Database&)

#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::catalog {

namespace fs = std::filesystem;

inline constexpr const char* kGcStageOrphan = "stage_orphan";
inline constexpr const char* kGcWorkingOrphan = "working_orphan";
inline constexpr const char* kGcTempOrphan = "temp_orphan";
inline constexpr const char* kGcTrashOrphan = "trash_orphan";
inline constexpr const char* kGcBlobOrphan = "blob_orphan";
inline constexpr const char* kGcEmptyDir = "empty_dir";

struct GcItem {
    std::string kind;
    std::string rel_path;   // project-dir-relative POSIX
    std::int64_t size = 0;
};

struct GcReport {
    std::vector<GcItem> items;

    std::int64_t count(std::optional<std::string_view> kind = std::nullopt) const;
    std::int64_t bytes_for(std::string_view kind) const;
    std::int64_t total_bytes() const;
};

struct GcContext {
    fs::path project_path;          // the .paleo.json project FILE
    // Non-owning; must outlive the call; must not be null (every entrypoint
    // dereferences it).
    const CatalogDocument* document = nullptr;
};

// Python db.py `active_staging_targets`: lease rows whose heartbeat_at
// string compares greater than *cutoff_iso* (ISO-8601 lexicographic = time
// order). Callers derive the cutoff from now − STAGING_LEASE_TTL (3600s);
// `default_lease_cutoff` formats that value.
//
// CONV-31b (A5, findings §F-2): this snapshot read can no longer see a
// lease acquired after the document was loaded — the R-leak that let an
// explicit sweep delete in-flight bytes (#1222). plan/sweep now use the
// LIVE sqlite read below (db.py 1289-1308 parity: Python queries the table
// directly). This document-snapshot form stays exported for connection-less
// callers (backward compatible).
std::set<std::string> active_staging_targets(const CatalogDocument& document,
                                             const std::string& cutoff_iso);
// The live read: `SELECT DISTINCT target FROM staging_leases WHERE
// heartbeat_at > ?` over an open database. Missing table / failed prepare →
// empty set (db.py _read_rows failure → set(), swallow parity).
std::set<std::string> active_staging_targets_live(Database& database,
                                                  const std::string& cutoff_iso);
// Convenience overload: opens catalog.sqlite read-only from the project
// file (metadata/catalog.sqlite); missing or unreadable store → empty set.
std::set<std::string> active_staging_targets_live(
    const std::filesystem::path& project_path,
    const std::string& cutoff_iso);
std::string default_lease_cutoff();  // local now − 3600s, ISO seconds

GcReport plan_gc(const GcContext& context, bool explicit_plan = true);

// Plan (dry_run) or perform a sweep. explicit=false (the conservative
// open-time sweep) removes only temp orphans and empty dirs; explicit=true
// adds stage/trash/blob orphans. Working copies are never swept here. Each
// candidate is re-validated against the referenced set and the active
// leases before deletion (single-writer model: 15-decisions.md D4).
GcReport sweep_gc(const GcContext& context, bool dry_run = true,
                  bool explicit_sweep = false,
                  const GcReport* precomputed = nullptr);

// Remove abandoned working-copy payloads (explicit user action only).
GcReport cleanup_working_copies(const GcContext& context);

}  // namespace pwb::catalog
