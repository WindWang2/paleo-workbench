// Service-layer trash / restore / purge state machine (conv-31b;
// service.py 3249-3661 — R6 recon contract, frozen in 31b-findings).
//
// The storage-level moves (trash_payload / restore_payload /
// purge_trashed_payload, error strings byte-identical) are already
// delivered by trash.hpp (conv-31 D1); this header adds the ORCHESTRATION
// on top: tombstone metadata shape and write timing, the locked two-phase
// save order (tombstone → persist → move → path write-back), current
// pointer reassignment (document-order last live version, NOT
// max(version_number)), zombie/pending-commit asset judgment, the crash
// window probe, and purge's refcount + rollback snapshot.
//
// The SaveHook is the ONLY persistence seam (findings §C-2): each
// function computes its own dirty set and calls the hook; a non-ok
// return triggers the function's specific in-memory rollback (the
// Python monkeypatch-able _flush_canonical_locked test surface).
// DocumentIndex is a const snapshot — the caller rebuilds it after any
// of these functions returns.
//
// CONV-31b: implemented in Wave2-A6 (src/trash_service.cpp).
#pragma once

#include "pwb/catalog/apply_changes.hpp"  // SaveHook
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/trash.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <optional>
#include <set>
#include <string>

namespace pwb::catalog {

namespace fs = std::filesystem;

// Idempotent (already trashed / already live → no-op success). Unknown
// ids are NotFound with the byte-identical "Unknown version: <id>" /
// "Unknown asset: <id>" texts. *now_iso empty → the implementation takes
// the local-time ISO stamp (sources.hpp injectable-clock precedent).
//
// trash_version: two-phase order — tombstone (+ current reassignment) →
// save#1(dirty assets+versions) [fail → untombstone rollback] → payload
// move → save#2 path write-back [fail → move back, tombstone KEPT].
// trash_asset: batch shape; save#2's dirty covers only the MOVED subset.
domain::DataError trash_version(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const std::string& version_id,
                                const std::string& reason,
                                const SaveHook& save,
                                const std::string& now_iso = "");
domain::DataError trash_asset(CatalogDocument* document,
                              const DocumentIndex& index,
                              const fs::path& project_path,
                              const std::string& asset_id,
                              const std::string& reason,
                              const SaveHook& save,
                              const std::string& now_iso = "");

// Reverse order. restore_version captures the reason BEFORE the pop (the
// rollback re-tombstones with it); a restore failure keeps live versions
// live. Crash-window recovery: a CatalogError from restore_payload probes
// trash/<vid>/ and retries once (W2 window).
domain::DataError restore_version(CatalogDocument* document,
                                  const DocumentIndex& index,
                                  const fs::path& project_path,
                                  const std::string& version_id,
                                  const SaveHook& save);
domain::DataError restore_asset(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const std::string& asset_id,
                                const SaveHook& save);

// Purge: payload_purges resolved BEFORE row deletion; only SURVIVING
// versions' digests protect blobs; zombie assets = non-trashed with no
// version AND not in pending_commit_assets (#1218); trashed assets with
// surviving versions are KEPT and un-trashed (C3). Save failure → full
// in-memory rollback INCLUDING the three tag maps. Unlink only AFTER the
// save succeeds. The returned count excludes zombies.
struct TrashPurgeResult {
    std::size_t removed = 0;  // trashed versions + trashed assets
};
domain::DataError purge_trashed(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const SaveHook& save,
                                const std::set<std::string>&
                                    pending_commit_assets,
                                TrashPurgeResult* out);

// Crash-window probe (3304-3316): first (sorted) top-level FILE under
// trash/<version_id>, as a project-relative posix path; nullopt when the
// directory is missing or holds no files. Deliberately ineffective for
// directory-tree payloads (is_file() filter) — Python behavior kept as
// contract, findings B-26.
std::optional<std::string> probe_trash_payload(const fs::path& project_path,
                                               const std::string& version_id);

// metadata["trash"] four-key view for tests/oracles (empty view = no
// tombstone).
struct TrashMetaView {
    std::optional<std::string> reason;
    std::optional<std::string> original_stage;
    std::optional<std::string> original_path;
    std::optional<std::string> trashed_at;
};
TrashMetaView trash_meta_of(const DataVersion& version);

// Document-order last non-trashed version of the asset excluding
// *exclude_id* (the current-reassignment rule; nullopt when none).
std::optional<std::string> active_current_candidate(
    const DocumentIndex& index, const DataAsset& asset,
    const std::string& exclude_id);

}  // namespace pwb::catalog
