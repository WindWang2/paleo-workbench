// Service-layer trash / restore / purge state machine (conv-31b;
// service.py 3249-3661 — implementation TU; the frozen contract lives in
// trash_service.hpp / R6 recon, 31b-findings §A-6).
//
// All filesystem moves/renames/unlinks go through trash.hpp (conv-31 D1,
// error strings already byte-identical); this file owns ONLY the
// orchestration: tombstone shape and timing, the locked two-phase save
// order, current reassignment (document-order last live version), zombie /
// pending-commit judgment, the crash-window probe, and purge's
// refcount + full rollback snapshot.
//
// CONV-31b: implemented in Wave2-A6.
#include "pwb/catalog/trash_service.hpp"

#include "pwb/catalog/refs.hpp"     // utc_now_iso
#include "pwb/catalog/resolve.hpp"  // resolve_payload_path

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <system_error>
#include <utility>
#include <vector>

namespace pwb::catalog {

namespace {

using domain::DataError;
using domain::ErrorCode;

constexpr const char* kTrashMetaKey = "trash";

// service.py _tombstone_version writes Python's `reason=None` default as a
// JSON null; the frozen signatures carry std::string, so "" IS the caller's
// spelling of None here.
std::optional<std::string> reason_argument(const std::string& reason) {
    if (reason.empty()) return std::nullopt;
    return reason;
}

// service.py _now_iso (project.models: datetime.now(timezone.utc)
// .isoformat()) — refs.hpp utc_now_iso() produces the same UTC-microsecond
// shape (sources.cpp injectable-clock precedent). [The trash_service.hpp
// prose says "local-time"; the Python source is UTC and UTC parity is what
// is implemented.]
std::string stamp_or(const std::string& now_iso) {
    return now_iso.empty() ? utc_now_iso() : now_iso;
}

// service.py 3251-3268 _tombstone_version — memory-only tombstone, the
// payload is NOT touched here. Returns the original recorded path. Four
// metadata keys in Python dict insertion order.
std::string tombstone_version(DataVersion& version,
                              const std::optional<std::string>& reason,
                              const std::string& trashed_at) {
    const std::string original_path = version.path;
    version.trashed = true;
    version.trashed_at = trashed_at;
    if (!version.metadata.is_object()) version.metadata = domain::Json::object();
    domain::Json meta = domain::Json::object();
    if (reason.has_value()) {
        meta["reason"] = *reason;
    } else {
        meta["reason"] = nullptr;
    }
    meta["original_stage"] = std::string(domain::to_string(version.stage));
    meta["original_path"] = original_path;
    meta["trashed_at"] = trashed_at;
    version.metadata[kTrashMetaKey] = std::move(meta);
    return original_path;
}

// A string field read out of metadata["trash"] (nullopt when absent, null
// or non-string — Python's .get() → None shape).
std::optional<std::string> trash_meta_string(const DataVersion& version,
                                             const char* key) {
    if (!version.metadata.is_object() || !version.metadata.contains(kTrashMetaKey) ||
        !version.metadata[kTrashMetaKey].is_object()) {
        return std::nullopt;
    }
    const domain::Json& trash = version.metadata[kTrashMetaKey];
    if (!trash.contains(key) || !trash[key].is_string()) return std::nullopt;
    return trash[key].get<std::string>();
}

std::optional<std::string> trash_meta_reason(const DataVersion& version) {
    return trash_meta_string(version, "reason");
}

// service.py 3444-3453 _rollback_tombstone — save#1 failed, the payload
// has not moved yet: in-memory flags/metadata/current only.
void rollback_tombstone(DataVersion& version, DataAsset& asset,
                        const std::optional<domain::VersionId>& previous_current) {
    version.trashed = false;
    version.trashed_at = std::nullopt;
    if (version.metadata.is_object()) version.metadata.erase(kTrashMetaKey);
    asset.current_version_id = previous_current;
}

// service.py 3270-3285 _move_payload_to_trash. Python lets a raw OSError
// escape (R6 recon ⑥); C++ has no exception channel, so BOTH error kinds
// (payload missing / move failed) map to the metadata-only branch — the
// same W2-tolerated state Python's crash window already recovers from.
bool move_payload_to_trash(DataVersion& version, const fs::path& project_path) {
    if (!version.managed) return false;
    const fs::path source = resolve_payload_path(project_path, version);
    domain::Result<std::string> moved =
        trash_payload(project_path, source, version.id.str());
    if (!moved.is_ok()) return false;  // already missing → metadata-only
    version.path = moved.value();
    return true;
}

// service.py 3287-3302 _rollback_trash_move — move-back after save#2
// failed. The PERSISTED tombstone is kept: the version stays trashed with
// its payload back at the original location, which restore handles.
void rollback_trash_move(DataVersion& version, const fs::path& project_path) {
    const std::optional<std::string> original_path =
        trash_meta_string(version, "original_path");
    if (!version.managed || !original_path.has_value() || original_path->empty()) {
        return;
    }
    if (version.path == *original_path) return;
    const fs::path source = resolve_payload_path(project_path, version);
    if (restore_payload(project_path, source, *original_path).is_ok()) {
        version.path = *original_path;
    }
}

// service.py 3318-3354 _untombstone_version — in-memory untombstone plus
// the best-effort payload move back; W2 crash-window probe included.
std::string untombstone_version(DataVersion& version, const fs::path& project_path) {
    std::string original_path = version.path;
    if (const std::optional<std::string> recorded =
            trash_meta_string(version, "original_path");
        recorded.has_value() && !recorded->empty()) {
        original_path = *recorded;
    }
    if (version.managed) {
        const domain::Result<std::string> restored = restore_payload(
            project_path, resolve_payload_path(project_path, version), original_path);
        if (restored.is_ok()) {
            version.path = restored.value();
        } else {
            // Crash-window recovery (W2): tombstone persisted, payload moved,
            // path-update save lost — probe trash/{vid}/ and retry once.
            const std::optional<std::string> probed =
                probe_trash_payload(project_path, version.id.str());
            if (probed.has_value()) {
                version.path = *probed;
                const domain::Result<std::string> retry = restore_payload(
                    project_path, resolve_payload_path(project_path, version),
                    original_path);
                version.path = retry.is_ok() ? retry.value() : original_path;
            } else {
                // Metadata-only trash or the payload is gone: keep the
                // original location; integrity will report it missing.
                version.path = original_path;
            }
        }
    } else {
        version.path = original_path;  // external files were never moved
    }
    version.trashed = false;
    version.trashed_at = std::nullopt;
    if (version.metadata.is_object()) version.metadata.erase(kTrashMetaKey);
    return original_path;
}

// service.py 3522-3534 _rollback_untombstone — a failed restore save
// re-tombstones (fresh stamp, captured reason) and re-trashes the payload.
void rollback_untombstone(DataVersion& version, DataAsset& asset,
                          const std::optional<domain::VersionId>& previous_current,
                          const std::optional<std::string>& reason,
                          const fs::path& project_path) {
    tombstone_version(version, reason, utc_now_iso());
    if (version.managed) move_payload_to_trash(version, project_path);
    asset.current_version_id = previous_current;
}

// The SaveHook is the ONLY persistence seam; a missing hook means the
// caller has no store attached (sources.cpp null-hook precedent).
DataError run_save(const SaveHook& save, const DirtySet& dirty) {
    return save ? save(dirty) : DataError(ErrorCode::Ok, "");
}

// Tag-association rows whose OWNER id is in *owners* (document order) —
// the snapshot behind Python's `{vid: tags for vid ... if vid in ids}`.
std::vector<std::pair<std::string, std::string>> tag_rows_for_owners(
    const std::vector<std::pair<std::string, std::string>>& rows,
    const std::set<std::string>& owners) {
    std::vector<std::pair<std::string, std::string>> out;
    for (const auto& row : rows) {
        if (owners.count(row.first) > 0) out.push_back(row);
    }
    return out;
}

void erase_tag_rows(std::vector<std::pair<std::string, std::string>>* rows,
                    const std::set<std::string>& owners) {
    rows->erase(std::remove_if(rows->begin(), rows->end(),
                               [&owners](const std::pair<std::string, std::string>& row) {
                                   return owners.count(row.first) > 0;
                               }),
                rows->end());
}

void erase_versions_by_id(CatalogDocument* document, const std::set<std::string>& ids) {
    auto& rows = document->versions;
    rows.erase(std::remove_if(rows.begin(), rows.end(),
                              [&ids](const DataVersion& v) {
                                  return ids.count(v.id.str()) > 0;
                              }),
               rows.end());
}

void erase_assets_by_id(CatalogDocument* document, const std::set<std::string>& ids) {
    auto& rows = document->assets;
    rows.erase(std::remove_if(rows.begin(), rows.end(),
                              [&ids](const DataAsset& a) {
                                  return ids.count(a.id.str()) > 0;
                              }),
               rows.end());
}

std::optional<domain::VersionId> version_id_or_none(const std::optional<std::string>& id) {
    if (!id.has_value()) return std::nullopt;
    return domain::VersionId(*id);
}

// service.py 1515 anchor (resolve.cpp has the same bounded helper; kept
// per-TU like trash.cpp/dedup.cpp's shared safe_entity_id contract).
fs::path project_anchor_dir(const fs::path& project_path) {
    fs::path expanded = project_path;
    const std::string text = project_path.string();
    if (text.size() >= 1 && text[0] == '~' &&
        (text.size() == 1 || text[1] == '/')) {
        const char* home = std::getenv("HOME");
        if (home != nullptr && *home != '\0') {
            expanded = fs::path(home);
            if (text.size() > 2) expanded /= text.substr(2);
        }
    }
    std::error_code ec;
    return fs::weakly_canonical(expanded, ec).parent_path();
}

}  // namespace

// ---- trash ------------------------------------------------------------------

domain::DataError trash_version(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const std::string& version_id,
                                const std::string& reason, const SaveHook& save,
                                const std::string& now_iso) {
    DataVersion* version =
        document->find_version_mut(domain::VersionId(version_id));
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown version: " + version_id);
    }
    if (version->trashed) {
        return DataError(ErrorCode::Ok, "");  // idempotent, NO save
    }
    DataAsset* asset = document->find_asset_mut(version->asset_id);
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown asset: " + version->asset_id.str());
    }
    const std::optional<domain::VersionId> previous_current =
        asset->current_version_id;
    const std::optional<std::string> why = reason_argument(reason);
    const std::string stamp = stamp_or(now_iso);

    tombstone_version(*version, why, stamp);
    if (asset->current_version_id == version->id) {
        asset->current_version_id = version_id_or_none(
            active_current_candidate(index, *asset, version->id.str()));
    }

    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    dirty.mark_version(version->id.str());
    DataError error = run_save(save, dirty);
    if (!error.ok()) {
        rollback_tombstone(*version, *asset, previous_current);
        return error;
    }
    if (move_payload_to_trash(*version, project_path)) {
        error = run_save(save, dirty);
        if (!error.ok()) {
            rollback_trash_move(*version, project_path);  // tombstone KEPT
            return error;
        }
    }
    return DataError(ErrorCode::Ok, "");
}

domain::DataError trash_asset(CatalogDocument* document,
                              const DocumentIndex& index,
                              const fs::path& project_path,
                              const std::string& asset_id,
                              const std::string& reason, const SaveHook& save,
                              const std::string& now_iso) {
    (void)index;  // batch shape scans the document directly (Python 3411-3414)
    DataAsset* asset = document->find_asset_mut(domain::AssetId(asset_id));
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id);
    }
    if (asset->trashed) return DataError(ErrorCode::Ok, "");  // idempotent

    std::vector<DataVersion*> versions;  // document order, pointer-stable
    for (DataVersion& candidate : document->versions) {
        if (candidate.asset_id == asset->id && !candidate.trashed) {
            versions.push_back(&candidate);
        }
    }
    const std::optional<domain::VersionId> previous_current =
        asset->current_version_id;
    const std::optional<std::string> why = reason_argument(reason);
    const std::string stamp = stamp_or(now_iso);

    for (DataVersion* version : versions) tombstone_version(*version, why, stamp);
    asset->trashed = true;
    asset->trashed_at = stamp;
    asset->current_version_id = std::nullopt;

    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    for (const DataVersion* version : versions) dirty.mark_version(version->id.str());
    DataError error = run_save(save, dirty);
    if (!error.ok()) {
        for (DataVersion* version : versions) {
            rollback_tombstone(*version, *asset, previous_current);
        }
        asset->trashed = false;
        asset->trashed_at = std::nullopt;
        return error;
    }

    std::vector<DataVersion*> moved;
    for (DataVersion* version : versions) {
        if (move_payload_to_trash(*version, project_path)) moved.push_back(version);
    }
    if (!moved.empty()) {
        DirtySet second;
        second.mark_asset(asset->id.str());
        for (const DataVersion* version : moved) {
            second.mark_version(version->id.str());
        }
        error = run_save(save, second);
        if (!error.ok()) {
            for (DataVersion* version : moved) rollback_trash_move(*version, project_path);
            return error;
        }
    }
    return DataError(ErrorCode::Ok, "");
}

// ---- restore -----------------------------------------------------------------

domain::DataError restore_version(CatalogDocument* document,
                                  const DocumentIndex& index,
                                  const fs::path& project_path,
                                  const std::string& version_id,
                                  const SaveHook& save) {
    (void)index;  // Python scans the document (3467-3470)
    DataVersion* version =
        document->find_version_mut(domain::VersionId(version_id));
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown version: " + version_id);
    }
    if (!version->trashed) return DataError(ErrorCode::Ok, "");  // idempotent
    DataAsset* asset = document->find_asset_mut(version->asset_id);
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown asset: " + version->asset_id.str());
    }
    const std::optional<domain::VersionId> previous_current =
        asset->current_version_id;
    // Captured BEFORE the pop — the rollback re-tombstones with this reason.
    const std::optional<std::string> reason = trash_meta_reason(*version);

    untombstone_version(*version, project_path);

    // current is None, or points at nothing live → point at this version.
    bool current_live = false;
    if (asset->current_version_id.has_value()) {
        for (const DataVersion& candidate : document->versions) {
            if (candidate.id == *asset->current_version_id && !candidate.trashed) {
                current_live = true;
                break;
            }
        }
    }
    if (!current_live) asset->current_version_id = version->id;

    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    dirty.mark_version(version->id.str());
    DataError error = run_save(save, dirty);
    if (!error.ok()) {
        rollback_untombstone(*version, *asset, previous_current, reason,
                             project_path);
        return error;
    }
    return DataError(ErrorCode::Ok, "");
}

domain::DataError restore_asset(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const std::string& asset_id,
                                const SaveHook& save) {
    (void)index;  // Python scans the document (3485)
    DataAsset* asset = document->find_asset_mut(domain::AssetId(asset_id));
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id);
    }
    std::vector<DataVersion*> versions;  // ALL versions, document order
    for (DataVersion& candidate : document->versions) {
        if (candidate.asset_id == asset->id) versions.push_back(&candidate);
    }
    const std::optional<domain::VersionId> previous_current =
        asset->current_version_id;
    const bool previous_trashed = asset->trashed;
    const std::optional<std::string> previous_trashed_at = asset->trashed_at;

    // (version, captured reason) pairs — the reason must be snapshotted
    // before untombstone pops the metadata.
    std::vector<std::pair<DataVersion*, std::optional<std::string>>> restore_targets;
    for (DataVersion* version : versions) {
        if (version->trashed) {
            restore_targets.emplace_back(version, trash_meta_reason(*version));
            untombstone_version(*version, project_path);
        }
    }
    asset->trashed = false;
    asset->trashed_at = std::nullopt;
    if (!asset->current_version_id.has_value() && !versions.empty()) {
        const DataVersion* last_live = nullptr;
        for (const DataVersion* version : versions) {
            if (!version->trashed) last_live = version;
        }
        asset->current_version_id =
            last_live != nullptr
                ? std::optional<domain::VersionId>(last_live->id)
                : std::nullopt;
    }

    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    for (const auto& target : restore_targets) {
        dirty.mark_version(target.first->id.str());
    }
    DataError error = run_save(save, dirty);
    if (!error.ok()) {
        asset->trashed = previous_trashed;
        asset->trashed_at = previous_trashed_at;
        // Roll back ONLY the versions this restore untombstoned; versions
        // that were already live must stay live.
        for (const auto& target : restore_targets) {
            rollback_untombstone(*target.first, *asset, previous_current,
                                 target.second, project_path);
        }
        return error;
    }
    return DataError(ErrorCode::Ok, "");
}

// ---- purge -------------------------------------------------------------------

domain::DataError purge_trashed(CatalogDocument* document,
                                const DocumentIndex& index,
                                const fs::path& project_path,
                                const SaveHook& save,
                                const std::set<std::string>& pending_commit_assets,
                                TrashPurgeResult* out) {
    (void)index;  // Python iterates the document directly (3542-3543)
    // 1. Collect trashed rows (copies — the originals are erased below)
    //    and snapshot the purged tag associations.
    std::vector<DataVersion> trashed_versions;
    for (const DataVersion& version : document->versions) {
        if (version.trashed) trashed_versions.push_back(version);
    }
    std::vector<DataAsset> trashed_assets;
    for (const DataAsset& asset : document->assets) {
        if (asset.trashed) trashed_assets.push_back(asset);
    }
    std::set<std::string> trashed_version_ids;
    for (const DataVersion& version : trashed_versions) {
        trashed_version_ids.insert(version.id.str());
    }
    std::set<std::string> purged_ids = trashed_version_ids;
    for (const DataAsset& asset : trashed_assets) {
        purged_ids.insert(asset.id.str());
    }
    const std::vector<std::pair<std::string, std::string>> removed_version_tags =
        tag_rows_for_owners(document->version_tags, purged_ids);
    const std::vector<std::pair<std::string, std::string>> removed_asset_tags =
        tag_rows_for_owners(document->asset_tags, purged_ids);

    // 2. Only SURVIVING versions' digests protect blobs (shared refcount):
    // two same-digest trashed versions may perish together.
    std::set<std::string> surviving_digests;
    for (const DataVersion& version : document->versions) {
        if (!version.trashed && version.sha256.has_value() && !version.sha256->empty()) {
            surviving_digests.insert(*version.sha256);
        }
    }

    // 3. Payload unlink jobs resolved BEFORE the rows go away — resolve
    //    reads the version records (a trashed managed path is the trash
    //    relative path).
    struct PayloadPurge {
        fs::path path;
        bool shared = false;
    };
    std::vector<PayloadPurge> payload_purges;
    for (const DataVersion& version : trashed_versions) {
        if (!version.managed) continue;
        const bool shared =
            version.sha256.has_value() && surviving_digests.count(*version.sha256) > 0;
        payload_purges.push_back({resolve_payload_path(project_path, version), shared});
    }

    // 4. Drop the trashed version rows.
    erase_versions_by_id(document, trashed_version_ids);

    // 5. Zombies: a LIVE asset with no surviving version row — unless an
    //    in-flight working-copy commit owns it (#1218).
    std::set<std::string> live_asset_ids;
    for (const DataVersion& version : document->versions) {
        live_asset_ids.insert(version.asset_id.str());
    }
    live_asset_ids.insert(pending_commit_assets.begin(), pending_commit_assets.end());
    std::vector<DataAsset> zombie_assets;
    for (const DataAsset& asset : document->assets) {
        if (!asset.trashed && live_asset_ids.count(asset.id.str()) == 0) {
            zombie_assets.push_back(asset);
        }
    }
    std::set<std::string> zombie_ids;
    for (const DataAsset& asset : zombie_assets) zombie_ids.insert(asset.id.str());
    const std::vector<std::pair<std::string, std::string>> removed_zombie_tags =
        tag_rows_for_owners(document->asset_tags, zombie_ids);
    erase_assets_by_id(document, zombie_ids);
    erase_tag_rows(&document->asset_tags, zombie_ids);

    // 6. A trashed asset with a SURVIVING version is KEPT and un-trashed
    //    (restore_version can untrash one version of it; deleting the
    //    asset would orphan that live version — review finding C3).
    std::set<std::string> surviving_asset_ids;
    for (const DataVersion& version : document->versions) {
        if (!version.trashed) surviving_asset_ids.insert(version.asset_id.str());
    }
    struct UntrashedSnapshot {
        std::string asset_id;
        bool was_trashed = true;
        std::optional<std::string> trashed_at;
        domain::Json metadata;
    };
    std::vector<UntrashedSnapshot> untrashed_snapshots;
    std::vector<DataAsset> removed_trashed_assets;  // copies for rollback
    std::set<std::string> removed_trashed_ids;
    for (const DataAsset& trashed : trashed_assets) {
        DataAsset* asset = document->find_asset_mut(domain::AssetId(trashed.id.str()));
        if (asset != nullptr && surviving_asset_ids.count(asset->id.str()) > 0) {
            untrashed_snapshots.push_back(
                {asset->id.str(), asset->trashed, asset->trashed_at, asset->metadata});
            asset->trashed = false;
            asset->trashed_at = std::nullopt;
            if (asset->metadata.is_object()) asset->metadata.erase(kTrashMetaKey);
            continue;
        }
        removed_trashed_assets.push_back(trashed);
        removed_trashed_ids.insert(trashed.id.str());
    }
    erase_assets_by_id(document, removed_trashed_ids);

    // 7. Drop the purged tag associations.
    erase_tag_rows(&document->version_tags, purged_ids);
    erase_tag_rows(&document->asset_tags, purged_ids);

    DirtySet dirty;
    for (const DataVersion& version : trashed_versions) {
        dirty.mark_version(version.id.str());
    }
    for (const DataAsset& asset : trashed_assets) dirty.mark_asset(asset.id.str());
    for (const DataAsset& asset : zombie_assets) dirty.mark_asset(asset.id.str());
    for (const auto& row : removed_version_tags) dirty.mark_version_tags(row.first);
    for (const auto& row : removed_asset_tags) dirty.mark_asset_tags(row.first);
    DataError error = run_save(save, dirty);
    if (!error.ok()) {
        // Full in-memory rollback (3653-3655) INCLUDING the three tag maps.
        for (const DataVersion& version : trashed_versions) {
            document->versions.push_back(version);
        }
        for (const DataAsset& asset : zombie_assets) {
            document->assets.push_back(asset);
        }
        for (const DataAsset& asset : removed_trashed_assets) {
            // Only re-add assets actually removed (un-trashed assets stayed
            // in the document the whole time) — id membership, not pointer
            // identity (the rows were destroyed above).
            if (document->find_asset(domain::AssetId(asset.id.str())) == nullptr) {
                document->assets.push_back(asset);
            }
        }
        for (const UntrashedSnapshot& snapshot : untrashed_snapshots) {
            DataAsset* asset =
                document->find_asset_mut(domain::AssetId(snapshot.asset_id));
            if (asset != nullptr) {
                asset->trashed = snapshot.was_trashed;
                asset->trashed_at = snapshot.trashed_at;
                asset->metadata = snapshot.metadata;
            }
        }
        for (const auto& row : removed_version_tags) {
            document->version_tags.push_back(row);
        }
        for (const auto& row : removed_asset_tags) {
            document->asset_tags.push_back(row);
        }
        for (const auto& row : removed_zombie_tags) {
            document->asset_tags.push_back(row);
        }
        return error;
    }

    // State is durable now; the unlink is best-effort and cannot corrupt
    // it (a leftover trash payload is a harmless orphan).
    for (const PayloadPurge& job : payload_purges) {
        purge_trashed_payload(project_path, job.path, job.shared);
    }
    if (out != nullptr) {
        out->removed = trashed_versions.size() + trashed_assets.size();
    }
    return DataError(ErrorCode::Ok, "");
}

// ---- probe + views -------------------------------------------------------------

std::optional<std::string> probe_trash_payload(const fs::path& project_path,
                                               const std::string& version_id) {
    // service.py 3304-3316: the first (sorted) top-level FILE under
    // trash/{version_id}. Deliberately ineffective for directory-tree
    // payloads (is_file filter) — Python behavior kept as contract
    // (findings B-26); do not "fix".
    const fs::path root = trash_dir_for(project_path) / version_id;
    std::error_code ec;
    if (!fs::is_directory(root, ec)) return std::nullopt;
    std::vector<std::string> names;
    for (fs::directory_iterator it(root, ec), end; !ec && it != end;
         it.increment(ec)) {
        std::error_code file_ec;
        if (it->is_regular_file(file_ec)) {
            names.push_back(it->path().filename().string());
        }
    }
    if (ec || names.empty()) return std::nullopt;
    std::sort(names.begin(), names.end());  // Path sort == filename sort (same parent)
    const fs::path project_dir = project_anchor_dir(project_path);
    std::error_code rel_ec;
    const fs::path relative = fs::relative(root / names.front(), project_dir, rel_ec);
    if (rel_ec) return std::nullopt;
    return relative.generic_string();
}

TrashMetaView trash_meta_of(const DataVersion& version) {
    TrashMetaView view;  // empty view = no tombstone
    if (!version.metadata.is_object() || !version.metadata.contains(kTrashMetaKey) ||
        !version.metadata[kTrashMetaKey].is_object()) {
        return view;
    }
    const domain::Json& meta = version.metadata[kTrashMetaKey];
    const auto read = [&meta](const char* key) -> std::optional<std::string> {
        if (meta.contains(key) && meta[key].is_string()) {
            return meta[key].get<std::string>();
        }
        return std::nullopt;
    };
    view.reason = read("reason");
    view.original_stage = read("original_stage");
    view.original_path = read("original_path");
    view.trashed_at = read("trashed_at");
    return view;
}

std::optional<std::string> active_current_candidate(
    const DocumentIndex& index, const DataAsset& asset,
    const std::string& exclude_id) {
    // service.py 3356-3363: document-order LAST non-trashed version
    // (versions_by_asset follows rowid/document order) — NOT
    // max(version_number).
    const std::vector<const DataVersion*>* versions =
        index.versions_of_asset(asset.id.str());
    if (versions == nullptr) return std::nullopt;
    const DataVersion* last = nullptr;
    for (const DataVersion* version : *versions) {
        if (version->trashed || version->id.str() == exclude_id) continue;
        last = version;
    }
    if (last == nullptr) return std::nullopt;
    return last->id.str();
}

}  // namespace pwb::catalog
