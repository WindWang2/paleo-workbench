// Id / lineage / dedup indexes over the catalog document (conv-31;
// service.py `_CatalogMaps` / `_ensure_maps` parity).
//
// One immutable snapshot built from a CatalogDocument: id lookups,
// per-asset version lists (document order), the child index over
// parent_version_ids, the import-dedup identity keys (#1139) and the
// legacy-bridge resolution order of `_find_asset_by_legacy_id` (an asset
// whose id equals the legacy id wins; otherwise the first asset bridged
// via legacy_resource_id — first-wins). Pointers reference the document
// the index was built from; rebuild after any mutation.
#pragma once

#include "pwb/catalog/models.hpp"

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::catalog {

class DocumentIndex {
public:
    DocumentIndex() = default;
    explicit DocumentIndex(const CatalogDocument& document) { rebuild(document); }

    void rebuild(const CatalogDocument& document);

    const DataAsset* asset(const std::string& id) const;
    const DataVersion* version(const std::string& id) const;
    const DataRun* run(const std::string& id) const;

    // Document-order version list for one asset (empty when none).
    const std::vector<const DataVersion*>* versions_of_asset(
        const std::string& asset_id) const;
    // Versions whose parent_version_ids contain *parent_id* (document order).
    const std::vector<const DataVersion*>* children_of(
        const std::string& parent_id) const;

    // Legacy bridge (open-migration identity rule). Exact id match first,
    // then the first asset recording legacy_resource_id == legacy_id.
    const DataAsset* asset_by_legacy_id(const std::string& legacy_id) const;

    // Import-dedup keys (#1139): managed live RAW with source_uri + sha256.
    std::optional<std::string> managed_raw_for(const std::string& source_uri,
                                               const std::string& sha256) const;
    // Live external version carrying this exact path.
    std::optional<std::string> external_for(const std::string& path) const;

    // Number of indexed versions (convenience for bounds/tests).
    std::size_t version_count() const { return version_by_id_.size(); }

private:
    std::unordered_map<std::string, const DataAsset*> asset_by_id_;
    std::unordered_map<std::string, const DataVersion*> version_by_id_;
    std::unordered_map<std::string, const DataRun*> run_by_id_;
    std::unordered_map<std::string, std::vector<const DataVersion*>> versions_by_asset_;
    std::unordered_map<std::string, std::vector<const DataVersion*>> children_by_parent_;
    std::unordered_map<std::string, const DataAsset*> legacy_by_id_;
    std::unordered_map<std::string, std::string> managed_raw_by_key_;
    std::unordered_map<std::string, std::string> external_by_path_;
};

// db.py _managed_raw_dedup_key / _external_dedup_key parity (free
// functions so tests can pin one version in isolation).
std::optional<std::pair<std::string, std::string>> managed_raw_dedup_key(
    const DataVersion& version);
std::optional<std::string> external_dedup_key(const DataVersion& version);

}  // namespace pwb::catalog
