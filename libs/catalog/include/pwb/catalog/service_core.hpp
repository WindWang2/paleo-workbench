// Catalog service orchestration core (conv-31b; service.py open/_save/
// _flush_canonical_locked/_BatchSave/_CatalogMaps — R3 + R4 recon
// contracts merged, frozen in 31b-findings §D-6/§D-7).
//
// open_catalog() runs the R3 health matrix: status probe → canonical
// load (None → degraded corrupt) → Unreadable raises the byte-identical
// #411-refusal message → corrupt is isolated + reset → manifest mtime
// accounting (strictly-greater adoption) → legacy rebuild via write_all →
// baseline recording → eager index build → optional temp sweep. lazy=true
// keeps ONLY the "empty document + store revision baseline + early exit
// before maps/sweep" semantics (the Python lazy/warm machinery itself is
// not ported — findings F-3).
//
// CatalogServiceCore holds the single-writer discipline: an internal
// std::mutex + *_locked layering (Python RLock reentrancy is restructured
// as non-nested public→locked calls, findings B-18), the document with
// stable-address entity storage, the incrementally-maintained maps (R4
// asymmetry semantics preserved), and the save/flush/batch/revision
// channel over apply_changes:
//   - mutation_serial increments FIRST, unconditionally, and never rolls
//     back (cache keys must treat failed mutations as invalidations);
//   - inside a batch, saves defer (dirty merged / reconcile flagged) and
//     only the OUTERMOST exit flushes exactly once (+1 revision);
//   - a failed flush rolls the revision back but does NOT reload (memory
//     stays ahead of disk until the caller's rollback — Python parity);
//   - #411 pre-check + #1220 in-transaction CAS (is_stale_write).
//
// CONV-31b: implemented in Wave2-A4 (src/service_core.cpp).
#pragma once

#include "pwb/catalog/apply_changes.hpp"  // DirtySet
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/domain/errors.hpp"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::catalog {

struct CatalogOpenOptions {
    bool lazy = false;         // empty doc + revision baseline + early exit
    bool sweep_temp = true;    // open-time conservative sweep (never on lazy)
};

// R3's open report (the degraded-final health value, rebuild/adoption
// flags, isolation target, the _flushed_revision baseline).
struct CatalogOpenReport {
    StoreHealth health = StoreHealth::Missing;
    bool rebuilt_from_manifest = false;
    bool adopted_newer_manifest = false;
    bool manifest_baseline_recorded = false;
    std::filesystem::path isolated_store;  // empty = none
    long long revision_baseline = 0;
};

// The service core. Move-only (owns the repository); constructed via
// open_catalog() or directly with an eager document for tests.
class CatalogServiceCore {
public:
    // A batch body runs under the same single-writer discipline; its
    // DataError return (not exceptions — library convention) decides the
    // exit path: error or an empty pending set → reload (discard
    // everything, memory back to store state) and the error propagates.
    using BatchBody = std::function<domain::DataError()>;

    struct Deps {
        std::filesystem::path sqlite_path;    // canonical catalog.sqlite
        std::filesystem::path manifest_path;  // metadata/catalog.json
    };

    CatalogServiceCore(CatalogDocument eager_document, Deps deps);
    ~CatalogServiceCore();
    CatalogServiceCore(CatalogServiceCore&& other) noexcept;
    CatalogServiceCore& operator=(CatalogServiceCore&& other) noexcept;
    CatalogServiceCore(const CatalogServiceCore&) = delete;
    CatalogServiceCore& operator=(const CatalogServiceCore&) = delete;

    const CatalogOpenReport& open_report() const;

    // Document access for the collaborator modules (trash_service /
    // model_registry / v11_bundle operate on the document pointer +
    // SaveHook). Mutations through the core's maintenance API keep the
    // maps coherent; direct list edits require invalidate_maps() after
    // (the migrate-shaped escape hatch).
    const CatalogDocument& document() const;
    CatalogDocument& document();
    // The query index — rebuilt after every mutation (DocumentIndex
    // snapshot semantics; pointers into the document).
    const DocumentIndex& index() const;
    CatalogRepository& repository();

    // Self-healing lookups (miss → one map rebuild → miss again → null).
    DataAsset* find_asset(std::string_view id);
    DataVersion* find_version(std::string_view id);
    DataRun* find_run(std::string_view id);

    // Maps-cohering entity maintenance (Python _add_*/_remove_*/
    // _rebridge/_drop_dedup_keys semantics incl. the documented
    // asymmetries — findings B-22). Returned pointers are stable for the
    // core's lifetime until the entity is removed.
    DataAsset* add_asset(DataAsset asset);
    DataVersion* add_version(DataVersion version);
    DataRun* add_run(DataRun run);
    void remove_asset(const DataAsset* asset);  // identity, not value (#1044)
    void remove_assets_bulk(const std::vector<const DataAsset*>& assets);
    void remove_version(const DataVersion* version);
    void remove_versions_bulk(const std::vector<const DataVersion*>& versions);
    void remove_run(const DataRun* run);
    void append_parent(const domain::VersionId& version_id,
                       const domain::VersionId& parent_id);  // dedup'd
    void set_legacy_bridge(DataAsset* asset, std::string legacy_id);
    void invalidate_maps();

    // ---- save / revision channel (service.py 1015-1084) ---------------------
    // save() = full reconcile (dirty unknown); save(dirty) = incremental
    // apply_changes with the maps as O(Δ) lookups. Both run the #411
    // pre-check + #1220 in-transaction CAS; both bump the revision only
    // on a successful flush.
    domain::DataError save();
    domain::DataError save(const DirtySet& dirty);

    std::uint64_t mutation_serial() const;      // monotonic, never resets
    int document_revision() const;
    std::optional<long long> index_revision() const;   // store revision
    std::optional<long long> flushed_revision() const;  // CAS baseline
    // Read-side freshness (queries.py 127-144 without the lazy branch):
    // false inside a batch or when the store revision drifted.
    bool index_current_for_read() const;

    // ---- batch (service.py 153-217) ------------------------------------------
    domain::DataError batch(const BatchBody& body);

    // ---- manifest -------------------------------------------------------------
    // #411 pre-check (stale → error, NOT swallowed here — explicit
    // callers get the real error), then store.save semantics via
    // save_manifest + mtime accounting.
    domain::DataError export_manifest(bool pretty = false);
    // Throttled checkpoint: only when the manifest does not exist yet and
    // at most one unsaved mutation; swallows everything.
    void checkpoint_manifest_throttled();
    // checkpoint (swallow) + repository close.
    void close();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;

    // CONV-31b A4: open_catalog seeds the open-time state (flush baseline,
    // report, lazy flag, eager maps) that the public constructor — which
    // mirrors Python __init__'s defaults — leaves unset. Private-section
    // addition only; the public signatures above are unchanged.
    friend domain::Result<CatalogServiceCore> open_catalog(
        const std::filesystem::path&, const CatalogOpenOptions&);
};

// The open flow over a .paleo.json project file (R3 matrix). Corrupt
// stores are isolated + reset + rebuilt from the manifest; Unreadable
// stores raise the byte-identical refusal message (never fall through to
// the manifest — the #411 last-writer-wins refusal).
domain::Result<CatalogServiceCore> open_catalog(
    const std::filesystem::path& project_path,
    const CatalogOpenOptions& options = {});

}  // namespace pwb::catalog
