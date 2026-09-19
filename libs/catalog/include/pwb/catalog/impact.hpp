// Dependency impact & staleness service (conv-31; catalog/impact.py
// parity, V11 §11 / docs 07-staleness.md).
//
// Read-only graph queries over catalog lineage — staleness is NEVER
// written back to versions (recomputed from lineage + current-version
// pointers per query). Pinned downstreams are reported but classified
// "pinned" (a decision, not an error). Trashed ancestors make live
// downstreams stale. Node budgets truncate honestly (marker suffix on the
// last item), matching docs/development/data-fabric-v11/11-scale.md.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"

#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace pwb::catalog {

inline constexpr int kMaxImpactNodes = 20000;  // MAX_IMPACT_NODES
inline constexpr int kMaxStaleItems = 2000;    // MAX_STALE_ITEMS

struct StaleItem {
    std::string version_id;
    std::string asset_id;
    bool direct = false;
    std::optional<std::string> via_run_id;
    // (asset_id, old_version_id, current_version_id); current == old when
    // the evolution is "trashed".
    std::optional<std::tuple<std::string, std::string, std::string>>
        nearest_changed_ancestor;
    std::string reason;
    bool pinned = false;
    bool reproducible = false;
    std::string stage;
    bool trashed = false;

    std::string classification() const { return pinned ? "pinned" : "stale"; }
};

struct UpstreamImpact {
    std::string version_id;
    std::vector<std::string> ancestor_version_ids;
    std::vector<std::string> ancestor_asset_ids;
    std::vector<std::string> runs_involved;
    std::vector<std::string> missing_ancestors;  // referenced, unknown
    std::vector<std::string> trashed_ancestors;
};

struct DeleteImpact {
    std::vector<std::string> target_version_ids;
    std::vector<std::string> target_asset_ids;
    std::vector<StaleItem> live_descendants;
    std::vector<std::string> runs_consuming;
    std::vector<std::string> runs_producing;
    std::vector<std::pair<std::string, std::string>> linked_entities;
    int broken_lineage_edges = 0;
    std::vector<std::string> cascade_advice;
};

class ImpactService {
public:
    ImpactService(const CatalogDocument& document, const DocumentIndex& index)
        : document_(document), index_(index) {}

    // All live downstream versions whose inputs evolved past them. With
    // *changed_version_ids* (hypothetical mode) those versions additionally
    // count as superseded. The Python module-level LRU (8 entries keyed on
    // document identity + revision + mutation serial + fingerprint +
    // include_trashed) is preserved per service instance.
    std::vector<StaleItem> downstream_stale(
        const std::optional<std::set<std::string>>& changed_version_ids =
            std::nullopt,
        bool include_trashed = false);

    // Is THIS version built on evolved/trashed inputs? (reason included.)
    std::pair<bool, std::string> is_stale(const std::string& version_id);

    UpstreamImpact upstream_impact(const std::string& version_id);

    // What breaks (lineage-wise) when a version or asset is removed.
    // *entity_links stands in for project.entity_asset_links (entity_type,
    // entity_id, asset_id triples of the affected assets).
    struct EntityLink {
        std::string entity_type;
        std::string entity_id;
        std::string asset_id;
    };
    DeleteImpact delete_impact(
        const std::optional<std::string>& version_id = std::nullopt,
        const std::optional<std::string>& asset_id = std::nullopt,
        const std::vector<EntityLink>* entity_links = nullptr);

    // Staleness scoped to one well/survey: items with ANY evolved ancestor
    // in *asset_ids* (not merely the nearest one).
    std::vector<StaleItem> entity_staleness(const std::set<std::string>& asset_ids);

private:
    std::optional<std::tuple<std::string, std::string, std::string>>
    nearest_changed_ancestor(
        const std::string& version_id,
        const std::set<std::string>& triggers) const;

    bool has_ancestor_in_assets(const std::string& version_id,
                                const std::set<std::string>& asset_ids,
                                int budget = 4096) const;

    const CatalogDocument& document_;
    const DocumentIndex& index_;
    // LRU cache parity (module-level in Python; instance-scoped here since
    // a C++ service is bound to one document snapshot).
    struct CacheEntry {
        std::size_t key_hash = 0;
        bool include_trashed = false;
        std::vector<StaleItem> items;
    };
    std::vector<CacheEntry> cache_;
    static constexpr std::size_t kCacheMax = 8;

    std::optional<std::size_t> cache_key(
        const std::set<std::string>& changed, bool include_trashed) const;
};

}  // namespace pwb::catalog
