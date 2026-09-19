// CatalogServiceCore + open_catalog (conv-31b; service.py parity).
//
// Python anchors:
//   - open() 779-943, close() 958-985, export_manifest() 987-1011,
//     sweep_temp_on_open() 945-956 — R3 health matrix / mtime accounting /
//     corrupt isolation+reset / manifest migration via write_all.
//   - _CatalogMaps 86-775 — incremental index maintenance with the three
//     DELIBERATE asymmetries (findings B-22, R4 §1.1-1.2):
//       (a) dedup keys: build = setdefault FIRST wins, _add_version =
//           assign LAST wins; _drop_dedup_keys is trash-agnostic and only
//           removes a key the version still OWNS;
//       (b) legacy bridge: build keeps the FIRST bridged holder (trashed or
//           not), while the removal-path rebridge prefers the first LIVE
//           claimant (I2);
//       (c) a single version removal KEEPS the emptied versions_by_asset
//           bucket key, the bulk removal DROPS it.
//   - _save/_flush_canonical_locked 1015-1084 — mutation_serial bumps
//     FIRST and never rolls back; inside a batch the write defers; a failed
//     flush rolls the revision back but does NOT reload; #411 pre-check +
//     #1220 in-transaction CAS (expected_revision through apply_changes /
//     reconcile, Wave2-A2).
//   - _BatchSave 153-217 — only the OUTERMOST exit flushes, exactly one
//     revision bump; body failure / empty pending → reload (discard).
//   - _reload_document_locked 1086-1108 — memory never stays ahead of disk.
//
// Storage design (findings B-20 / R4 §2.2): entities live in a
// CatalogEntityStore of unique_ptr nodes (Python object-reference
// semantics — stable addresses across list mutations), with CatalogMaps
// pointing at those nodes. The public document()/index() faces serve a
// materialized CatalogDocument cache that is refreshed from the nodes
// whenever the nodes moved ahead (DocumentIndex pointers are snapshot-
// scoped: index() rebuilds after every list mutation or re-materialize).
//
// Authority protocol (the one disciplined escape hatch): between
// invalidate_maps() calls the node store + incrementally maintained maps
// are authoritative; document() hands out the materialized cache, and
// direct list edits through that reference require invalidate_maps()
// afterwards — exactly Python's "touch the document, then _invalidate_maps"
// migrate shape. A flush uses the cache when it is current (so edits made
// through document() are persisted, with fresh O(Δ) lookups built over
// that view) and the node store otherwise (lookups = the maintained maps).
//
// CONV-31b Wave4: the fold is node-preserving (surviving entities keep
// their addresses — the "stable until removed" contract now holds across
// invalidate_maps), and cache dirtiness follows the mutation epoch: only
// real mutations clear it; find_* lookups are pure reads and never do.
//
// Honest deviations (beyond findings B-1..B-22 already frozen):
//   - append_parent() is void in the frozen header, so an unknown version
//     id is a silent no-op instead of Python's "Unknown version: <id>"
//     CatalogError (signature-forced; composition layers pre-resolve).
//   - lazy open (findings F-3): the lazy/warm machinery is not ported; a
//     lazy open yields an EMPTY document + the store revision baseline and
//     returns before maps/sweep. Reads are expected to go to SQLite.
//   - A throwing batch body is rolled back (reload) and the exception is
//     re-thrown (Python propagation parity); if the reload itself fails
//     during that unwind the original exception still wins (Python would
//     replace it — not expressible while re-throwing an unknown type).
//
// CONV-31b: implemented in Wave2-A4.
#include "pwb/catalog/service_core.hpp"

#include "pwb/catalog/gc.hpp"
#include "pwb/project/paths.hpp"

#include <sys/stat.h>

#include <algorithm>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <unordered_map>
#include <utility>

namespace pwb::catalog {

namespace {
using domain::DataError;
using domain::ErrorCode;
namespace fs = std::filesystem;

// service.py _disk_mtime_ns (218-222) — POSIX st_mtim ns (findings B-16:
// never a seconds-granularity stat).
std::optional<std::int64_t> disk_mtime_ns(const fs::path& path) {
    struct ::stat info {};
    if (::stat(path.c_str(), &info) != 0) return std::nullopt;
    return static_cast<std::int64_t>(info.st_mtim.tv_sec) * 1000000000LL +
           static_cast<std::int64_t>(info.st_mtim.tv_nsec);
}

bool path_is_file(const fs::path& path) {
    std::error_code ec;
    return std::filesystem::is_regular_file(path, ec);
}
// service.py _maybe_checkpoint_manifest_locked uses Path.exists() (not
// is_file) for the throttling gate.
bool path_exists(const fs::path& path) {
    std::error_code ec;
    return std::filesystem::exists(path, ec);
}

// db.py revision() over a fresh read-only connection (the Python index
// exposes its pooled reader; §C-6 keeps read_revision the single reader).
std::optional<long long> read_store_revision(const fs::path& db_path) {
    auto opened = Database::open(db_path, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return std::nullopt;
    return read_revision(opened.value());
}

// The #411 stale-write channel (findings §C-3): byte-identical Chinese
// texts, ConflictBaseVersion + detail["stale_write"]=true so callers can
// branch programmatically via is_stale_write().
DataError stale_write_error(std::string_view message) {
    domain::Json detail = domain::Json::object();
    detail["stale_write"] = true;
    return DataError(ErrorCode::ConflictBaseVersion, std::string(message),
                     std::move(detail));
}

constexpr std::string_view kStaleSaveMessage =
    "数据目录元数据已被其他实例修改；为避免覆盖他人提交，"
    "本次保存已中止。请重新打开工程后重试。";
constexpr std::string_view kStaleManifestMessage =
    "数据目录元数据已被其他实例修改；为避免覆盖他人提交，"
    "本次 manifest 导出已中止。请重新打开工程后重试。";
constexpr std::string_view kReloadFailureMessage =
    "Canonical store became unreadable while rolling back; "
    "in-memory state may diverge from disk. Reopen the project.";

// Python list.remove-style identity removal (#1044): one pointer-compare
// scan, never a value comparison.
template <typename T>
void discard_by_identity(std::vector<const T*>& bucket, const T* target) {
    for (auto it = bucket.begin(); it != bucket.end(); ++it) {
        if (*it == target) {
            bucket.erase(it);
            return;
        }
    }
}
}  // namespace

// ---------------------------------------------------------------------------
// CatalogEntityStore — stable-address entity graph (Python object refs).
// ---------------------------------------------------------------------------

// TU-internal (findings §D-7: the entity store is not a public face).
// assets/versions/runs live as unique_ptr nodes so pointers handed out by
// the maps stay valid for the core's lifetime until the entity is removed;
// the association-only lists (tags, model registry, working copies, ...)
// carry no identity semantics and stay plain vectors.
class CatalogEntityStore {
public:
    int schema_version = kCatalogSchemaVersion;
    int catalog_revision = 0;

    std::vector<Tag> tags;
    std::vector<Model> models;
    std::vector<ModelVersion> model_versions;
    std::vector<std::pair<std::string, std::string>> asset_tags;
    std::vector<std::pair<std::string, std::string>> version_tags;
    std::vector<WorkingCopy> working_copies;
    std::vector<LineageEdge> lineage;
    std::vector<StagingLease> staging_leases;

    // CONV-31b Wave4 fix (V2-P0-1): the fold REUSES existing nodes instead
    // of destroying them. The old clear-and-rebuild invalidated every node
    // pointer handed out through add_*/find_* whenever invalidate_maps()
    // folded a cache edit — violating the header contract ("stable for
    // the core's lifetime until the entity is removed"; the entity was
    // never removed, ASan-confirmed UAF). Matching is by id: a surviving
    // id keeps its node (value-refreshed in place, address unchanged),
    // document-new ids get fresh nodes, node ids absent from the document
    // are removed here (that removal IS the contract's "until removed"),
    // and the vector is spliced into document order (unique_ptr moves
    // never touch the pointees). Duplicate ids collapse first-match on
    // both sides — same surviving-node count the full rebuild produced.
    void reset_from(const CatalogDocument& document) {
        schema_version = document.schema_version;
        catalog_revision = document.catalog_revision;
        fold_entities(assets_, document.assets);
        fold_entities(versions_, document.versions);
        fold_entities(runs_, document.runs);
        tags = document.tags;
        models = document.models;
        model_versions = document.model_versions;
        asset_tags = document.asset_tags;
        version_tags = document.version_tags;
        working_copies = document.working_copies;
        lineage = document.lineage;
        staging_leases = document.staging_leases;
    }

    // The node-preserving fold half of reset_from (see the comment above).
    template <typename E>
    static void fold_entities(std::vector<std::unique_ptr<E>>& nodes,
                              const std::vector<E>& values) {
        std::unordered_map<std::string, std::size_t> index;
        index.reserve(nodes.size());
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            index.emplace(nodes[i]->id.str(), i);
        }
        std::vector<std::unique_ptr<E>> folded;
        folded.reserve(values.size());
        for (const E& value : values) {
            auto it = index.find(value.id.str());
            if (it != index.end() && nodes[it->second] != nullptr) {
                // Surviving entity: refresh the value in place — the node
                // address every outstanding pointer still targets is kept.
                *nodes[it->second] = value;
                folded.push_back(std::move(nodes[it->second]));
                // (moved-from slot is already null; a duplicate id in
                // values cannot rematch it and mints a fresh node, exactly
                // like the previous per-entry rebuild)
            } else {
                folded.push_back(std::make_unique<E>(value));
            }
        }
        // Unmatched old nodes (ids no longer in the document) die HERE —
        // after the fold, so any pointer reading them during this call is
        // still valid; afterwards they are removed entities.
        nodes = std::move(folded);
    }

    CatalogDocument materialize() const {
        CatalogDocument document;
        document.schema_version = schema_version;
        document.catalog_revision = catalog_revision;
        document.assets.reserve(assets_.size());
        for (const auto& asset : assets_) document.assets.push_back(*asset);
        document.versions.reserve(versions_.size());
        for (const auto& version : versions_) {
            document.versions.push_back(*version);
        }
        document.runs.reserve(runs_.size());
        for (const auto& run : runs_) document.runs.push_back(*run);
        document.tags = tags;
        document.models = models;
        document.model_versions = model_versions;
        document.asset_tags = asset_tags;
        document.version_tags = version_tags;
        document.working_copies = working_copies;
        document.lineage = lineage;
        document.staging_leases = staging_leases;
        return document;
    }

    DataAsset* add_asset(const DataAsset& asset) {
        assets_.push_back(std::make_unique<DataAsset>(asset));
        return assets_.back().get();
    }
    DataVersion* add_version(const DataVersion& version) {
        versions_.push_back(std::make_unique<DataVersion>(version));
        return versions_.back().get();
    }
    DataRun* add_run(const DataRun& run) {
        runs_.push_back(std::make_unique<DataRun>(run));
        return runs_.back().get();
    }

    // Removes *node* from the document-ordered list, transferring ownership
    // to the caller so the entity stays readable while the maps maintenance
    // (which inspects its fields) runs.
    std::unique_ptr<DataAsset> detach_asset(const DataAsset* node) {
        return detach(assets_, node);
    }
    std::unique_ptr<DataVersion> detach_version(const DataVersion* node) {
        return detach(versions_, node);
    }
    std::unique_ptr<DataRun> detach_run(const DataRun* node) {
        return detach(runs_, node);
    }

    const std::vector<std::unique_ptr<DataAsset>>& assets() const {
        return assets_;
    }
    const std::vector<std::unique_ptr<DataVersion>>& versions() const {
        return versions_;
    }
    const std::vector<std::unique_ptr<DataRun>>& runs() const { return runs_; }

private:
    template <typename T>
    static std::unique_ptr<T> detach(std::vector<std::unique_ptr<T>>& list,
                                     const T* node) {
        for (auto it = list.begin(); it != list.end(); ++it) {
            if (it->get() == node) {
                auto owned = std::move(*it);
                list.erase(it);
                return owned;
            }
        }
        return nullptr;
    }

    std::vector<std::unique_ptr<DataAsset>> assets_;
    std::vector<std::unique_ptr<DataVersion>> versions_;
    std::vector<std::unique_ptr<DataRun>> runs_;
};

// ---------------------------------------------------------------------------
// CatalogMaps — the incremental _CatalogMaps equivalent (8 indexes).
// ---------------------------------------------------------------------------

// TU-internal (findings §D-7). `built == false` is Python's `_maps is
// None`: unbuilt maps mean maintenance ops touch only the document.
class CatalogMaps {
public:
    bool built = false;

    // service.py _ensure_maps (521-568). Id maps use assignment (last
    // duplicate wins, Python dict semantics); dedup keys setdefault (FIRST
    // wins); the legacy bridge takes every id key, then setdefault per
    // bridged legacy id — the FIRST bridged asset wins, trashed or not.
    void rebuild(const CatalogEntityStore& store) {
        asset_by_id_.clear();
        version_by_id_.clear();
        run_by_id_.clear();
        versions_by_asset_.clear();
        children_by_parent_.clear();
        assets_by_legacy_id_.clear();
        managed_raw_by_key_.clear();
        external_by_path_.clear();
        for (const auto& asset : store.assets()) {
            asset_by_id_[asset->id.str()] = asset.get();
        }
        for (const auto& run : store.runs()) {
            run_by_id_[run->id.str()] = run.get();
        }
        for (const auto& version : store.versions()) {
            version_by_id_[version->id.str()] = version.get();
            versions_by_asset_[version->asset_id.str()].push_back(
                version.get());
            for (const auto& parent : version->parent_version_ids) {
                children_by_parent_[parent.str()].push_back(version.get());
            }
            if (auto key = managed_raw_dedup_key(*version)) {
                managed_raw_by_key_.emplace(*key, version->id.str());
            }
            if (auto key = external_dedup_key(*version)) {
                external_by_path_.emplace(*key, version->id.str());
            }
        }
        for (const auto& asset : store.assets()) {
            assets_by_legacy_id_[asset->id.str()] = asset.get();
        }
        for (const auto& asset : store.assets()) {
            if (asset->legacy_resource_id.has_value()) {
                assets_by_legacy_id_.emplace(*asset->legacy_resource_id,
                                             asset.get());
            }
        }
        built = true;
    }

    // service.py _add_asset (589-607).
    void on_add_asset(const DataAsset* asset) {
        asset_by_id_[asset->id.str()] = asset;
        assets_by_legacy_id_[asset->id.str()] = asset;
        if (asset->legacy_resource_id.has_value()) {
            const std::string& key = *asset->legacy_resource_id;
            auto holder = assets_by_legacy_id_.find(key);
            // A trashed holder is replaced by the live re-import (I2);
            // an existing LIVE holder keeps the bridge (setdefault).
            if (holder == assets_by_legacy_id_.end() || holder->second->trashed) {
                assets_by_legacy_id_[key] = asset;
            } else {
                assets_by_legacy_id_.emplace(key, asset);
            }
        }
    }

    // service.py _remove_asset (609-625): affected keys = {id, legacy_id}.
    void on_remove_asset(const CatalogEntityStore& store,
                         const DataAsset* asset) {
        asset_by_id_.erase(asset->id.str());
        std::set<std::string> keys{asset->id.str()};
        if (asset->legacy_resource_id.has_value()) {
            keys.insert(*asset->legacy_resource_id);
        }
        rebridge_legacy_keys(store, keys);
    }

    // service.py _remove_assets_bulk (627-647): one rebridge over the union.
    void on_remove_assets_bulk(const CatalogEntityStore& store,
                               const std::vector<const DataAsset*>& removed) {
        std::set<std::string> keys;
        for (const DataAsset* asset : removed) {
            asset_by_id_.erase(asset->id.str());
            keys.insert(asset->id.str());
            if (asset->legacy_resource_id.has_value()) {
                keys.insert(*asset->legacy_resource_id);
            }
        }
        rebridge_legacy_keys(store, keys);
    }

    // service.py _add_version (690-712): dedup keys are ASSIGNED here —
    // last write wins, the documented asymmetry vs the first-wins build.
    void on_add_version(const DataVersion* version) {
        version_by_id_[version->id.str()] = version;
        versions_by_asset_[version->asset_id.str()].push_back(version);
        for (const auto& parent : version->parent_version_ids) {
            children_by_parent_[parent.str()].push_back(version);
        }
        if (auto key = managed_raw_dedup_key(*version)) {
            managed_raw_by_key_[*key] = version->id.str();
        }
        if (auto key = external_dedup_key(*version)) {
            external_by_path_[*key] = version->id.str();
        }
    }

    // service.py _remove_version (714-725): identity removal from the three
    // buckets + dedup drop; an emptied versions_by_asset bucket KEEPS its
    // key (only the bulk path drops it).
    void on_remove_version(const DataVersion* version) {
        version_by_id_.erase(version->id.str());
        auto bucket = versions_by_asset_.find(version->asset_id.str());
        if (bucket != versions_by_asset_.end()) {
            discard_by_identity(bucket->second, version);
        }
        for (const auto& parent : version->parent_version_ids) {
            auto children = children_by_parent_.find(parent.str());
            if (children != children_by_parent_.end()) {
                discard_by_identity(children->second, version);
            }
        }
        drop_dedup_keys(version);
    }

    // service.py _remove_versions_bulk (727-756).
    void on_remove_versions_bulk(
        const std::vector<const DataVersion*>& removed) {
        std::set<std::string> affected_assets;
        std::set<std::string> affected_parents;
        for (const DataVersion* version : removed) {
            version_by_id_.erase(version->id.str());
            drop_dedup_keys(version);
            affected_assets.insert(version->asset_id.str());
            for (const auto& parent : version->parent_version_ids) {
                affected_parents.insert(parent.str());
            }
        }
        for (const auto& asset_id : affected_assets) {
            auto bucket = versions_by_asset_.find(asset_id);
            if (bucket == versions_by_asset_.end()) continue;
            bucket->second.erase(
                std::remove_if(bucket->second.begin(), bucket->second.end(),
                               [&](const DataVersion* candidate) {
                                   return std::find(removed.begin(),
                                                    removed.end(),
                                                    candidate) != removed.end();
                               }),
                bucket->second.end());
            if (bucket->second.empty()) {
                // No versions left for this asset: drop the stale bucket so
                // versions-for lookups cannot report on removed assets.
                versions_by_asset_.erase(bucket);
            }
        }
        for (const auto& parent_id : affected_parents) {
            auto children = children_by_parent_.find(parent_id);
            if (children == children_by_parent_.end()) continue;
            children->second.erase(
                std::remove_if(children->second.begin(),
                               children->second.end(),
                               [&](const DataVersion* candidate) {
                                   return std::find(removed.begin(),
                                                    removed.end(),
                                                    candidate) != removed.end();
                               }),
                children->second.end());
        }
    }

    void on_add_run(const DataRun* run) { run_by_id_[run->id.str()] = run; }
    void on_remove_run(const DataRun* run) { run_by_id_.erase(run->id.str()); }

    // service.py _append_parent (768-774).
    void on_append_parent(const DataVersion* child,
                          const std::string& parent_id) {
        children_by_parent_[parent_id].push_back(child);
    }

    // service.py _set_legacy_bridge (1280-1288): metadata-only bridge;
    // setdefault keeps an existing holder.
    void on_set_legacy_bridge(const DataAsset* asset) {
        if (asset->legacy_resource_id.has_value()) {
            assets_by_legacy_id_.emplace(*asset->legacy_resource_id, asset);
        }
    }

    // service.py _drop_dedup_keys (491-519): TRASH-AGNOSTIC (an entry may
    // outlive a later trash flip) and guarded by ownership — a key already
    // reassigned to another version is kept.
    void drop_dedup_keys(const DataVersion* version) {
        if (version->managed && version->stage == domain::DataStage::Raw &&
            version->source_uri.has_value() && !version->source_uri->empty() &&
            version->sha256.has_value() && !version->sha256->empty()) {
            auto key = std::make_pair(*version->source_uri, *version->sha256);
            auto it = managed_raw_by_key_.find(key);
            if (it != managed_raw_by_key_.end() &&
                it->second == version->id.str()) {
                managed_raw_by_key_.erase(it);
            }
        }
        if (!version->managed && !version->path.empty()) {
            auto it = external_by_path_.find(version->path);
            if (it != external_by_path_.end() &&
                it->second == version->id.str()) {
                external_by_path_.erase(it);
            }
        }
    }

    // service.py _rebridge_legacy_keys (649-688). Survivor order decides:
    // an id claimant wins unconditionally (no trash preference, C1);
    // otherwise the first LIVE claimant (I2), else the first claimant.
    // Python collects `claimants` in survivor order (an asset whose id AND
    // legacy id both match is appended twice — harmless, mirrored by the
    // scan order below).
    void rebridge_legacy_keys(const CatalogEntityStore& store,
                              const std::set<std::string>& keys) {
        for (const auto& key : keys) {
            const DataAsset* id_claim = nullptr;
            const DataAsset* live_claim = nullptr;
            const DataAsset* any_claim = nullptr;
            for (const auto& asset : store.assets()) {
                if (id_claim == nullptr && asset->id.str() == key) {
                    id_claim = asset.get();
                }
                if (asset->legacy_resource_id.has_value() &&
                    *asset->legacy_resource_id == key) {
                    if (live_claim == nullptr && !asset->trashed) {
                        live_claim = asset.get();
                    }
                    if (any_claim == nullptr) any_claim = asset.get();
                }
            }
            if (id_claim != nullptr) {
                assets_by_legacy_id_[key] = id_claim;
            } else if (live_claim != nullptr) {
                assets_by_legacy_id_[key] = live_claim;
            } else if (any_claim != nullptr) {
                assets_by_legacy_id_[key] = any_claim;
            } else {
                assets_by_legacy_id_.erase(key);
            }
        }
    }

    // ---- lookups ---------------------------------------------------------
    const DataAsset* asset(std::string_view id) const {
        return find_ptr(asset_by_id_, id);
    }
    const DataVersion* version(std::string_view id) const {
        return find_ptr(version_by_id_, id);
    }
    const DataRun* run(std::string_view id) const {
        return find_ptr(run_by_id_, id);
    }
    const DataAsset* asset_by_legacy_id(std::string_view id) const {
        return find_ptr(assets_by_legacy_id_, id);
    }
    const std::vector<const DataVersion*>* versions_of_asset(
        const std::string& asset_id) const {
        auto it = versions_by_asset_.find(asset_id);
        return it == versions_by_asset_.end() ? nullptr : &it->second;
    }
    const std::vector<const DataVersion*>* children_of(
        const std::string& parent_id) const {
        auto it = children_by_parent_.find(parent_id);
        return it == children_by_parent_.end() ? nullptr : &it->second;
    }
    const std::string* managed_raw_for(const std::string& source_uri,
                                       const std::string& sha256) const {
        auto it = managed_raw_by_key_.find(std::make_pair(source_uri, sha256));
        return it == managed_raw_by_key_.end() ? nullptr : &it->second;
    }
    const std::string* external_for(const std::string& path) const {
        auto it = external_by_path_.find(path);
        return it == external_by_path_.end() ? nullptr : &it->second;
    }

    // The O(Δ) lookup seam for apply_changes (§C-6): pointers into the
    // node store, valid while the flushed document stays immutable.
    ApplyLookups lookups() const {
        return ApplyLookups{&asset_by_id_, &version_by_id_, &run_by_id_};
    }

    // Debug/self-check (service.py _maps_consistent 570-587 shape).
    bool consistent(const CatalogEntityStore& store) const {
        if (!built) return false;
        if (asset_by_id_.size() != store.assets().size()) return false;
        if (version_by_id_.size() != store.versions().size()) return false;
        if (run_by_id_.size() != store.runs().size()) return false;
        for (const auto& entry : store.assets()) {
            if (find_ptr(asset_by_id_, entry->id.str()) != entry.get()) {
                return false;
            }
        }
        for (const auto& entry : store.versions()) {
            if (find_ptr(version_by_id_, entry->id.str()) != entry.get()) {
                return false;
            }
            if (versions_of_asset(entry->asset_id.str()) == nullptr) {
                return false;
            }
        }
        return true;
    }

private:
    template <typename T>
    static const T* find_ptr(
        const std::unordered_map<std::string, const T*>& map,
        std::string_view id) {
        auto it = map.find(std::string(id));
        return it == map.end() ? nullptr : it->second;
    }

    std::unordered_map<std::string, const DataAsset*> asset_by_id_;
    std::unordered_map<std::string, const DataVersion*> version_by_id_;
    std::unordered_map<std::string, const DataRun*> run_by_id_;
    std::unordered_map<std::string, std::vector<const DataVersion*>>
        versions_by_asset_;
    std::unordered_map<std::string, std::vector<const DataVersion*>>
        children_by_parent_;
    std::unordered_map<std::string, const DataAsset*> assets_by_legacy_id_;
    std::map<std::pair<std::string, std::string>, std::string>
        managed_raw_by_key_;
    std::unordered_map<std::string, std::string> external_by_path_;
};

// ---------------------------------------------------------------------------
// CatalogServiceCore::Impl
// ---------------------------------------------------------------------------

struct CatalogServiceCore::Impl {
    Impl(CatalogDocument eager_document, Deps deps_)
        : deps(std::move(deps_)), repo(deps.sqlite_path) {
        store.reset_from(eager_document);
    }

    mutable std::mutex mutex;
    Deps deps;
    CatalogRepository repo;
    CatalogEntityStore store;
    CatalogMaps maps;

    // Materialized value view (document()/index()/flush serve it whenever
    // it is current). Re-materialized from the nodes after every node-side
    // mutation; a caller editing through document() keeps it current until
    // invalidate_maps() folds the edits back into the nodes.
    CatalogDocument cache;
    bool cache_valid = false;
    DocumentIndex index;
    bool index_valid = false;

    std::uint64_t serial = 0;              // mutation_serial — never resets
    int batch_depth = 0;
    DirtySet pending_dirty;
    bool pending_reconcile = false;
    std::optional<long long> batch_base_revision;  // #1139 freshness base
    // Batch dedup overlay (#1139): recorded by add_version while a batch is
    // open, no eligibility predicates (fields may be null). Consumers are
    // the dedup lookup ladder, landing with a later composition wave.
    std::map<std::pair<std::optional<std::string>, std::optional<std::string>>,
             std::string>
        overlay_managed;
    std::map<std::string, std::string> overlay_external;

    std::optional<long long> flushed_revision;  // #411 baseline
    int mutations_since_manifest = 0;
    bool lazy_opened = false;
    ManifestCheckpointState manifest_state;    // store.py _last_write
    CatalogOpenReport report;

    // ---- locked family (mutex held) --------------------------------------
    void sync_cache_locked() {
        if (!cache_valid) {
            cache = store.materialize();
            cache_valid = true;
            index_valid = false;  // old index pointed into the old cache
        }
    }

    void ensure_maps_locked() {
        if (!maps.built) maps.rebuild(store);
    }

    std::optional<long long> store_revision_locked() const {
        return read_store_revision(deps.sqlite_path);
    }

    // CONV-31b Wave4 fix (V2-P1-1): composition layers also persist through
    // repository transactions (commit_working_copy / commit_version /
    // publish / promote — one transaction + one revision bump) outside this
    // core. Python's equivalents all flow through service._save, which ends
    // with document revision == store revision == _flushed_revision; the
    // C++ repo channel bumps the store directly and the composition then
    // syncs the document's catalog_revision onto the post-transaction value
    // (working_copy.cpp register_working_version). That sync is the
    // ownership proof: when the document claims EXACTLY the stored revision
    // while this core's baseline lags behind it, the drift came from OUR
    // session's transaction — adopt it as the CAS baseline instead of
    // refusing. A foreign writer never moves THIS document, so there
    // document revision != stored and the #411 refusal stands unchanged.
    void resync_own_transaction_baseline_locked() {
        if (!flushed_revision.has_value()) return;
        auto stored = store_revision_locked();
        if (!stored.has_value() || *stored == *flushed_revision) return;
        const int doc_revision =
            cache_valid ? cache.catalog_revision : store.catalog_revision;
        if (*stored == static_cast<long long>(doc_revision)) {
            store.catalog_revision = static_cast<int>(*stored);
            flushed_revision = stored;
        }
    }

    // service.py _flush_canonical_locked (1049-1084). The #411 pre-check is
    // the cheap fast-fail; the binding comparison is the #1220 CAS inside
    // the write transaction (apply_changes/reconcile, Wave2-A2).
    DataError flush_locked(const DirtySet& dirty, bool reconcile) {
        auto stored = store_revision_locked();
        if (stored.has_value() && stored != flushed_revision) {
            return stale_write_error(kStaleSaveMessage);
        }
        CatalogDocument materialized;
        const CatalogDocument* view = nullptr;
        // Fresh lookup tables over the flushed view when the cache (which
        // may carry direct document() edits) is authoritative; the
        // incrementally maintained maps otherwise.
        std::unordered_map<std::string, const DataAsset*> lookup_assets;
        std::unordered_map<std::string, const DataVersion*> lookup_versions;
        std::unordered_map<std::string, const DataRun*> lookup_runs;
        ApplyChangesOptions options;
        options.expected_revision = flushed_revision;
        if (cache_valid) {
            view = &cache;
            lookup_assets.reserve(cache.assets.size());
            for (const auto& asset : cache.assets) {
                lookup_assets.emplace(asset.id.str(), &asset);
            }
            lookup_versions.reserve(cache.versions.size());
            for (const auto& version : cache.versions) {
                lookup_versions.emplace(version.id.str(), &version);
            }
            lookup_runs.reserve(cache.runs.size());
            for (const auto& run : cache.runs) {
                lookup_runs.emplace(run.id.str(), &run);
            }
            options.lookups = ApplyLookups{&lookup_assets, &lookup_versions,
                                           &lookup_runs};
        } else {
            ensure_maps_locked();
            materialized = store.materialize();
            view = &materialized;
            options.lookups = maps.lookups();
        }
        DataError error =
            reconcile
                ? pwb::catalog::reconcile(repo.writable_database(), *view,
                                          flushed_revision)
                : apply_changes(repo.writable_database(), *view, dirty,
                                options);
        if (error.code != ErrorCode::Ok) return error;
        flushed_revision = static_cast<long long>(view->catalog_revision);
        return DataError(ErrorCode::Ok, "");
    }

    // service.py _save (1015-1047).
    DataError save_locked(const DirtySet* dirty) {
        // Unconditional and FIRST — failed mutations still invalidate
        // (revision, serial)-keyed caches.
        ++serial;
        if (batch_depth > 0) {
            if (dirty != nullptr) {
                pending_dirty.merge(*dirty);
            } else {
                pending_reconcile = true;
            }
            return DataError(ErrorCode::Ok, "");
        }
        resync_own_transaction_baseline_locked();
        ++store.catalog_revision;
        if (cache_valid) ++cache.catalog_revision;
        static const DirtySet kEmpty;
        DataError error =
            flush_locked(dirty != nullptr ? *dirty : kEmpty, dirty == nullptr);
        if (error.code != ErrorCode::Ok) {
            // Revision rolls back; the in-memory changes STAY (memory ahead
            // of disk until the caller reloads/rolls back — Python parity).
            --store.catalog_revision;
            if (cache_valid) --cache.catalog_revision;
            return error;
        }
        ++mutations_since_manifest;
        maybe_checkpoint_locked();
        return DataError(ErrorCode::Ok, "");
    }

    // service.py _reload_document_locked (1086-1108): memory never stays
    // ahead of disk.
    DataError reload_locked() {
        auto reloaded = repo.open_read_only();
        if (!reloaded.is_ok()) {
            pending_dirty = DirtySet();
            pending_reconcile = false;
            return DataError(ErrorCode::CorruptDatabase,
                             std::string(kReloadFailureMessage));
        }
        store.reset_from(reloaded.value());
        maps.built = false;  // _invalidate_maps
        pending_dirty = DirtySet();
        pending_reconcile = false;
        batch_base_revision.reset();
        overlay_managed.clear();
        overlay_external.clear();
        cache_valid = false;
        index_valid = false;
        flushed_revision = store_revision_locked();
        return DataError(ErrorCode::Ok, "");
    }

    // service.py export_manifest (987-1011): #411 guard NOT swallowed.
    DataError export_manifest_locked(bool pretty) {
        auto stored = store_revision_locked();
        if (stored.has_value() && stored != flushed_revision) {
            return stale_write_error(kStaleManifestMessage);
        }
        CatalogDocument view = cache_valid ? cache : store.materialize();
        DataError error =
            save_manifest(deps.manifest_path, view, pretty, &manifest_state);
        if (error.code != ErrorCode::Ok) return error;
        repo.record_manifest_mtime_ns(deps.manifest_path);
        mutations_since_manifest = 0;
        return DataError(ErrorCode::Ok, "");
    }

    // service.py _maybe_checkpoint_manifest_locked (1110-1126): only when
    // no manifest exists yet and at most one unsaved mutation; swallows
    // everything (the manifest is a convenience artifact, never a gate).
    void maybe_checkpoint_locked() {
        if (mutations_since_manifest > 1) return;
        if (path_exists(deps.manifest_path)) return;
        (void)export_manifest_locked(false);
    }

    // _BatchSave.__enter__ (166-179).
    void batch_enter_locked() {
        if (batch_depth == 0) {
            batch_base_revision = static_cast<long long>(store.catalog_revision);
            overlay_managed.clear();
            overlay_external.clear();
        }
        ++batch_depth;
    }

    // _BatchSave.__exit__ (181-217): only the outermost exit flushes.
    DataError batch_exit_locked(bool body_failed, const DataError& body_error) {
        --batch_depth;
        if (batch_depth > 0) return DataError(ErrorCode::Ok, "");
        batch_base_revision.reset();
        overlay_managed.clear();
        overlay_external.clear();
        if (body_failed || (pending_dirty.is_empty() && !pending_reconcile)) {
            // Nothing may persist — reload the untouched canonical state so
            // memory matches the store again.
            DataError reload_error = reload_locked();
            if (reload_error.code != ErrorCode::Ok) return reload_error;
            return body_failed ? body_error : DataError(ErrorCode::Ok, "");
        }
        DirtySet combined = std::move(pending_dirty);
        pending_dirty = DirtySet();
        bool reconcile = pending_reconcile;
        pending_reconcile = false;
        // The revision advances exactly once, HERE (one transaction for the
        // whole batch, #1139). A failed flush reloads the document (which
        // restores the pre-batch revision) and the error propagates.
        resync_own_transaction_baseline_locked();
        ++store.catalog_revision;
        if (cache_valid) ++cache.catalog_revision;
        DataError error = flush_locked(combined, reconcile);
        if (error.code != ErrorCode::Ok) {
            DataError reload_error = reload_locked();
            if (reload_error.code != ErrorCode::Ok) return reload_error;
            return error;
        }
        maybe_checkpoint_locked();
        return DataError(ErrorCode::Ok, "");
    }

    void note_document_mutated_locked() {
        // The mutation epoch (Wave4 fix V2-P1-2/V1-P2-1): ONLY real
        // node-side mutations invalidate the value cache — lookups are
        // pure reads and never clear it, so a document() direct edit
        // survives an intervening find_* until invalidate_maps() folds it.
        cache_valid = false;
        index_valid = false;
    }
};

// ---------------------------------------------------------------------------
// CatalogServiceCore — public face (frozen signatures)
// ---------------------------------------------------------------------------

CatalogServiceCore::CatalogServiceCore(CatalogDocument eager_document,
                                       Deps deps)
    : impl_(std::make_unique<Impl>(std::move(eager_document), std::move(deps))) {
}

CatalogServiceCore::~CatalogServiceCore() = default;

CatalogServiceCore::CatalogServiceCore(CatalogServiceCore&& other) noexcept =
    default;

CatalogServiceCore& CatalogServiceCore::operator=(
    CatalogServiceCore&& other) noexcept = default;

const CatalogOpenReport& CatalogServiceCore::open_report() const {
    return impl_->report;
}

const CatalogDocument& CatalogServiceCore::document() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->sync_cache_locked();
    return impl_->cache;
}

CatalogDocument& CatalogServiceCore::document() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->sync_cache_locked();
    return impl_->cache;
}

const DocumentIndex& CatalogServiceCore::index() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->sync_cache_locked();
    if (!impl_->index_valid) {
        impl_->index.rebuild(impl_->cache);
        impl_->index_valid = true;
    }
    return impl_->index;
}

CatalogRepository& CatalogServiceCore::repository() { return impl_->repo; }

// Self-healing lookups (service.py _asset_or_raise 1238-1250): a miss
// rebuilds the maps once from the document before the second probe; the
// C++ face returns null instead of raising "Unknown asset: <id>".
//
// CONV-31b Wave4 fix (V2-P1-2 / V1-P2-1): these are PURE READS now — the
// value cache is only invalidated by real mutations (the add_*/remove_*/
// append_parent/set_legacy_bridge family via note_document_mutated_locked,
// i.e. the mutation-epoch discipline: cache dirtiness tracks actual node-
// side mutations, not lookups). Previously every find_* unconditionally
// cleared cache_valid, which (a) made an intervening find_* between a
// document() direct edit and invalidate_maps() skip the fold and silently
// DROP the edit, and (b) forced an O(N) full re-materialization on every
// read. Contract for the returned pointer: it aliases a stable node
// (Wave4 fix V2-P0-1) usable for reads and identity-based ops
// (remove_*(ptr)); field mutations belong to the document() +
// invalidate_maps() protocol — they are not tracked by the cache epoch.
DataAsset* CatalogServiceCore::find_asset(std::string_view id) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->ensure_maps_locked();
    const DataAsset* found = impl_->maps.asset(id);
    if (found == nullptr) {
        impl_->maps.rebuild(impl_->store);
        found = impl_->maps.asset(id);
    }
    return const_cast<DataAsset*>(found);
}

DataVersion* CatalogServiceCore::find_version(std::string_view id) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->ensure_maps_locked();
    const DataVersion* found = impl_->maps.version(id);
    if (found == nullptr) {
        impl_->maps.rebuild(impl_->store);
        found = impl_->maps.version(id);
    }
    return const_cast<DataVersion*>(found);
}

DataRun* CatalogServiceCore::find_run(std::string_view id) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->ensure_maps_locked();
    const DataRun* found = impl_->maps.run(id);
    if (found == nullptr) {
        impl_->maps.rebuild(impl_->store);
        found = impl_->maps.run(id);
    }
    return const_cast<DataRun*>(found);
}

DataAsset* CatalogServiceCore::add_asset(DataAsset asset) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    DataAsset* node = impl_->store.add_asset(asset);
    if (impl_->maps.built) impl_->maps.on_add_asset(node);
    impl_->note_document_mutated_locked();
    return node;
}

DataVersion* CatalogServiceCore::add_version(DataVersion version) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    DataVersion* node = impl_->store.add_version(version);
    if (impl_->batch_depth > 0) {
        // #1139 overlay: no eligibility predicates, fields may be null;
        // consumers validate liveness/predicates at lookup.
        if (version.managed) {
            impl_->overlay_managed[{version.source_uri, version.sha256}] =
                version.id.str();
        } else {
            impl_->overlay_external[version.path] = version.id.str();
        }
    }
    if (impl_->maps.built) impl_->maps.on_add_version(node);
    impl_->note_document_mutated_locked();
    return node;
}

DataRun* CatalogServiceCore::add_run(DataRun run) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    DataRun* node = impl_->store.add_run(run);
    if (impl_->maps.built) impl_->maps.on_add_run(node);
    impl_->note_document_mutated_locked();
    return node;
}

void CatalogServiceCore::remove_asset(const DataAsset* asset) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    std::unique_ptr<DataAsset> kept = impl_->store.detach_asset(asset);
    if (!kept) return;
    if (impl_->maps.built) impl_->maps.on_remove_asset(impl_->store, asset);
    impl_->note_document_mutated_locked();
}

void CatalogServiceCore::remove_assets_bulk(
    const std::vector<const DataAsset*>& assets) {
    if (assets.empty()) return;
    std::lock_guard<std::mutex> lock(impl_->mutex);
    std::vector<const DataAsset*> removed;
    removed.reserve(assets.size());
    // CONV-31b Wave3 fix: the detached nodes must OUTLIVE the maps
    // maintenance below (it reads their fields). `if (detach(...))`
    // destroyed each temporary unique_ptr — and the node with it —
    // before on_remove_assets_bulk dereferenced the pointers (UAF).
    std::vector<std::unique_ptr<DataAsset>> detached;
    detached.reserve(assets.size());
    for (const DataAsset* asset : assets) {
        auto owned = impl_->store.detach_asset(asset);
        if (owned) {
            removed.push_back(asset);
            detached.push_back(std::move(owned));
        }
    }
    if (impl_->maps.built && !removed.empty()) {
        impl_->maps.on_remove_assets_bulk(impl_->store, removed);
    }
    impl_->note_document_mutated_locked();
}

void CatalogServiceCore::remove_version(const DataVersion* version) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    std::unique_ptr<DataVersion> kept = impl_->store.detach_version(version);
    if (!kept) return;
    if (impl_->maps.built) impl_->maps.on_remove_version(version);
    impl_->note_document_mutated_locked();
}

void CatalogServiceCore::remove_versions_bulk(
    const std::vector<const DataVersion*>& versions) {
    if (versions.empty()) return;
    std::lock_guard<std::mutex> lock(impl_->mutex);
    std::vector<const DataVersion*> removed;
    removed.reserve(versions.size());
    // CONV-31b Wave3 fix: same UAF as remove_assets_bulk — keep the
    // detached nodes alive through on_remove_versions_bulk.
    std::vector<std::unique_ptr<DataVersion>> detached;
    detached.reserve(versions.size());
    for (const DataVersion* version : versions) {
        auto owned = impl_->store.detach_version(version);
        if (owned) {
            removed.push_back(version);
            detached.push_back(std::move(owned));
        }
    }
    if (impl_->maps.built && !removed.empty()) {
        impl_->maps.on_remove_versions_bulk(removed);
    }
    impl_->note_document_mutated_locked();
}

void CatalogServiceCore::remove_run(const DataRun* run) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    std::unique_ptr<DataRun> kept = impl_->store.detach_run(run);
    if (!kept) return;
    if (impl_->maps.built) impl_->maps.on_remove_run(run);
    impl_->note_document_mutated_locked();
}

// service.py _append_parent (768-774). The frozen void signature cannot
// carry Python's "Unknown version: <id>" CatalogError — an unknown id (or
// an already-recorded parent) is a no-op here.
void CatalogServiceCore::append_parent(const domain::VersionId& version_id,
                                       const domain::VersionId& parent_id) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->ensure_maps_locked();
    DataVersion* node = const_cast<DataVersion*>(
        impl_->maps.version(version_id.str()));
    if (node == nullptr) {
        impl_->maps.rebuild(impl_->store);
        node = const_cast<DataVersion*>(impl_->maps.version(version_id.str()));
    }
    if (node == nullptr) return;
    if (std::find(node->parent_version_ids.begin(),
                  node->parent_version_ids.end(),
                  parent_id) != node->parent_version_ids.end()) {
        return;
    }
    node->parent_version_ids.push_back(parent_id);
    if (impl_->maps.built) {
        impl_->maps.on_append_parent(node, parent_id.str());
    }
    impl_->note_document_mutated_locked();
}

// service.py _set_legacy_bridge (1280-1288).
void CatalogServiceCore::set_legacy_bridge(DataAsset* asset,
                                           std::string legacy_id) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    asset->legacy_resource_id = std::move(legacy_id);
    if (impl_->maps.built) impl_->maps.on_set_legacy_bridge(asset);
    impl_->note_document_mutated_locked();
}

// service.py _invalidate_maps (400-402) + the direct-edit protocol: edits
// made through document() live in the value cache, so they are folded back
// into the node store here; the maps themselves rebuild lazily on next
// use (full-build semantics — exactly Python's invalidate + ensure_maps).
void CatalogServiceCore::invalidate_maps() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->cache_valid) impl_->store.reset_from(impl_->cache);
    impl_->maps.built = false;
    impl_->index_valid = false;
}

domain::DataError CatalogServiceCore::save() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->save_locked(nullptr);
}

domain::DataError CatalogServiceCore::save(const DirtySet& dirty) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->save_locked(&dirty);
}

std::uint64_t CatalogServiceCore::mutation_serial() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->serial;
}

int CatalogServiceCore::document_revision() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->store.catalog_revision;
}

std::optional<long long> CatalogServiceCore::index_revision() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->store_revision_locked();
}

std::optional<long long> CatalogServiceCore::flushed_revision() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->flushed_revision;
}

// queries.py _query_index_if_current without the lazy branch (findings
// F-3): inside a batch the store has not seen the mutations, and a drifted
// store revision means the index cannot answer for this document.
bool CatalogServiceCore::index_current_for_read() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->batch_depth > 0) return false;
    auto stored = impl_->store_revision_locked();
    return stored.has_value() &&
           *stored == static_cast<long long>(impl_->store.catalog_revision);
}

domain::DataError CatalogServiceCore::batch(const BatchBody& body) {
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        impl_->batch_enter_locked();
    }
    // The body runs OUTSIDE the lock (Python's context manager releases
    // between __enter__ and __exit__); it drives the core through the
    // public locking API.
    bool body_failed = false;
    DataError body_error(ErrorCode::Unknown, "batch body is empty");
    if (body) {
        try {
            body_error = body();
            body_failed = body_error.code != ErrorCode::Ok;
        } catch (...) {
            // Body threw: nothing may persist — reload, then let the
            // caller's exception propagate (Python parity, findings B-19).
            {
                std::lock_guard<std::mutex> lock(impl_->mutex);
                (void)impl_->batch_exit_locked(true, body_error);
            }
            throw;
        }
    } else {
        body_failed = true;
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->batch_exit_locked(body_failed, body_error);
}

domain::DataError CatalogServiceCore::export_manifest(bool pretty) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->export_manifest_locked(pretty);
}

void CatalogServiceCore::checkpoint_manifest_throttled() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->maybe_checkpoint_locked();
}

// service.py close (958-985): the manifest checkpoint is best-effort (a
// failure never blocks closing the canonical store). The lazy-session
// fast path skips the rewrite when the recorded mtime still matches the
// on-disk manifest; eager sessions always export.
void CatalogServiceCore::close() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    bool manifest_current = false;
    if (impl_->lazy_opened && impl_->mutations_since_manifest == 0) {
        if (path_is_file(impl_->deps.manifest_path)) {
            auto recorded = impl_->repo.recorded_manifest_mtime_ns();
            auto current = disk_mtime_ns(impl_->deps.manifest_path);
            if (recorded.has_value() && current.has_value() &&
                *recorded == *current) {
                manifest_current = true;
            }
        }
        if (!manifest_current) (void)impl_->export_manifest_locked(false);
    } else {
        (void)impl_->export_manifest_locked(false);
    }
    impl_->repo.close();
}

// ---------------------------------------------------------------------------
// open_catalog — the R3 health matrix (service.py open 779-943)
// ---------------------------------------------------------------------------

domain::Result<CatalogServiceCore> open_catalog(
    const std::filesystem::path& project_path, const CatalogOpenOptions& options) {
    namespace fs = std::filesystem;
    const fs::path sqlite_path = pwb::project::catalog_sqlite_for(project_path);
    const fs::path json_path = catalog_manifest_file(project_path);

    CatalogRepository repo(sqlite_path);
    StoreHealth health = repo.status().health;
    CatalogOpenReport report;
    report.health = health;  // classified input; path B degrades below

    std::optional<CatalogDocument> document;
    if (health == StoreHealth::Canonical && !options.lazy) {
        auto loaded = repo.open_read_write();
        if (loaded.is_ok()) {
            document = std::move(loaded.value());
        } else {
            // Path B (#1027 review): the store passed the health probes but
            // its rows cannot be read — degrade to the corrupt flow
            // (forensics + manifest rebuild), never a silent empty store.
            health = StoreHealth::Corrupt;
            report.health = health;
        }
    }
    if (health == StoreHealth::Unreadable) {
        // Transient read failure (busy/locked): falling through to the
        // manifest would silently overwrite committed canonical data with
        // a stale checkpoint — the exact last-writer-wins #411 refuses.
        return DataError(ErrorCode::IoError,
                         "Canonical catalog store exists but is unreadable: " +
                             sqlite_path.string() +
                             ". Not overwriting it with the manifest; "
                             "resolve the read failure (close other instances, "
                             "retry) and reopen.");
    }
    if (health == StoreHealth::Corrupt) {
        // Deterministic damage: isolate the bytes for forensics (best-effort
        // rename; reset removes whatever remains anyway), then reset — the
        // disposable-store recovery rebuilds from the manifest below.
        const fs::path isolated = isolate_corrupt_file(sqlite_path);
        if (!isolated.empty() && isolated != sqlite_path) {
            report.isolated_store = isolated;
        }
        repo.reset();
    }
    if (health == StoreHealth::Canonical && options.lazy) {
        // Lazy open (findings F-3): store revision baseline + manifest mtime
        // adoption, EMPTY document, early exit BEFORE maps and sweep.
        auto revision = read_store_revision(sqlite_path);
        if (path_is_file(json_path)) {
            auto recorded = repo.recorded_manifest_mtime_ns();
            auto current = disk_mtime_ns(json_path);
            if (!recorded.has_value() || !current.has_value() ||
                *recorded != *current) {
                auto legacy = load_manifest(json_path);
                // A corrupt manifest never blocks open (CatalogError →
                // legacy is skipped); adoption needs a STRICTLY greater
                // revision — equal revisions are ignored.
            if (legacy.is_ok() && revision.has_value() &&
                legacy.value().document.catalog_revision > *revision) {
                    DataError written =
                        repo.write_all(legacy.value().document);
                    if (written.code != ErrorCode::Ok) return written;
                    // CONV-31b Wave3 fix: write_all closes the resident
                    // handle (two-attempt rebuild discipline) — reopen so
                    // the core's save channel has a live database.
                    auto reopened = repo.open_read_write();
                    if (!reopened.is_ok()) return reopened.error();
                    revision = legacy.value().document.catalog_revision;
                    report.adopted_newer_manifest = true;
                }
            }
        }
        CatalogDocument lazy_document;
        lazy_document.catalog_revision = static_cast<int>(revision.value_or(0));
        CatalogServiceCore core(std::move(lazy_document),
                                CatalogServiceCore::Deps{sqlite_path, json_path});
        core.impl_->repo = std::move(repo);
        core.impl_->flushed_revision =
            static_cast<long long>(core.impl_->store.catalog_revision);
        core.impl_->lazy_opened = true;
        report.revision_baseline = core.impl_->store.catalog_revision;
        core.impl_->report = report;
        return core;
    }
    if (document.has_value() && path_is_file(json_path)) {
        // The manifest should be exactly what we last checkpointed; a moved
        // mtime means an old (json-canonical) app version wrote it behind
        // our back — honor the STRICTLY newer revision, transactionally.
        auto recorded = repo.recorded_manifest_mtime_ns();
        auto current = disk_mtime_ns(json_path);
        if (!recorded.has_value() || !current.has_value() ||
            *recorded != *current) {
            auto legacy = load_manifest(json_path);
            if (legacy.is_ok() &&
                legacy.value().document.catalog_revision >
                    document->catalog_revision) {
                DataError written = repo.write_all(legacy.value().document);
                if (written.code != ErrorCode::Ok) return written;
                // CONV-31b Wave3 fix: same reopen-after-write_all as below
                // (the adoption path also hands the core a closed handle).
                auto reopened = repo.open_read_write();
                if (!reopened.is_ok()) return reopened.error();
                document = std::move(legacy.value().document);
                report.adopted_newer_manifest = true;
            }
        }
    }
    if (!document.has_value()) {
        // Migration / initialization (absent, legacy or corrupt-reset
        // stores): the manifest (or an empty document) is imported in one
        // transaction; a failure propagates — the source json is untouched
        // and the retry starts clean.
        auto loaded = load_manifest(json_path);
        if (!loaded.is_ok()) return loaded.error();
        document = std::move(loaded.value().document);
        DataError written = repo.write_all(*document);
        if (written.code != ErrorCode::Ok) return written;
        // CONV-31b Wave3 fix: write_all closes the resident handle — the
        // disposable-store rebuild leaves the repository WITHOUT a live
        // database, so the new core's first save failed with "cannot
        // prepare statement" (Python's pooled index keeps its connection
        // across rebuilds). Reopen before the baseline is recorded.
        auto reopened = repo.open_read_write();
        if (!reopened.is_ok()) return reopened.error();
        report.rebuilt_from_manifest = true;
        if (path_is_file(json_path)) {
            // F8: record the baseline now so subsequent opens skip the
            // full manifest parse. Swallows its own errors (A1 contract).
            repo.record_manifest_mtime_ns(json_path);
            report.manifest_baseline_recorded = true;
        }
    }
    report.revision_baseline = document->catalog_revision;

    if (options.sweep_temp) {
        // sweep_temp_on_open (945-956): conservative gc sweep, all errors
        // swallowed — residual cleanup never blocks project open.
        try {
            GcContext context{project_path, &*document};
            (void)sweep_gc(context, /*dry_run=*/false, /*explicit_sweep=*/false);
        } catch (...) {
            // best-effort
        }
    }

    CatalogServiceCore core(std::move(*document),
                            CatalogServiceCore::Deps{sqlite_path, json_path});
    core.impl_->repo = std::move(repo);
    core.impl_->flushed_revision =
        static_cast<long long>(core.impl_->store.catalog_revision);
    core.impl_->report = report;
    {
        // Eager maps build (open line 940): the first mutation stays O(Δ).
        std::lock_guard<std::mutex> lock(core.impl_->mutex);
        core.impl_->ensure_maps_locked();
    }
    return core;
}

}  // namespace pwb::catalog
