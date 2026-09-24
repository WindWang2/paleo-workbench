// Governance closure (ws0 data governance) — the write/read service over
// the project's TWO existing persistence authorities. No new store:
//   * entity↔asset links + role edits  → the project JSON document, via a
//     short-lived WritableSession and the entity_identity kernel (one
//     atomic document save per operation; a failed save leaves disk
//     untouched — the session's in-memory copy is discarded with it);
//   * tags / trash / restore            → catalog.sqlite, via the deep
//     core (catalog::open_catalog: R3 health matrix, #411/#1220
//     transaction CAS, journaled rollback). A governance open is
//     short-lived like the ingest path's — single-writer honesty: the CAS
//     surfaces a concurrent writer as an explicit error, never a silent
//     overwrite.
//
// RAW immutability: no governance action rewrites managed payload bytes.
// Trash MOVES payloads into artifacts/trash/ (reversible); tags/roles/links
// are metadata only.
//
// Failure contract: every writer returns WriteOutcome{ok=false, error}
// instead of throwing; success carries a user-facing (Chinese) summary.
// Callers must not report success unless ok.
#pragma once

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "entity_identity.hpp"

namespace pwb::data::governance {

namespace fs = std::filesystem;

struct WriteOutcome {
    bool ok = false;
    std::string error;    // non-empty on failure (user-facing)
    std::string summary;  // user-facing success text
};

// ---- entity / link reads (project JSON, best-effort fresh read) ----------

struct WellEntry {
    std::string id;
    std::string name;
    std::string uwi;
    std::string spatial_scope;  // schema default "workarea"
};

std::vector<WellEntry> wells(const fs::path& project_file);

// Display name of one entity node ("" when the node is unknown).
std::string entity_display_name(const fs::path& project_file,
                                std::string_view entity_type,
                                std::string_view entity_id);

std::vector<EntityLinkView> links_for_asset(const fs::path& project_file,
                                            std::string_view asset_id);

// True when the catalog holds this asset and it is NOT soft-deleted.
bool asset_is_live(const fs::path& project_file, const std::string& asset_id);

// ---- link writes (project JSON via WritableSession) -----------------------

// Create/update the (entity_type, entity_id, asset_id, role) link. Rejects
// unknown entities, unknown/trashed assets and blank roles BEFORE mutating;
// the kernel keeps the single-primary invariant. An explicit manual link
// CLEARS the row's unresolved flag (operator confirmation semantics).
WriteOutcome link_asset(const fs::path& project_file,
                        const std::string& entity_type,
                        const std::string& entity_id,
                        const std::string& asset_id, const std::string& role,
                        bool is_primary, const std::string& note = "");

// Remove the exact link row (role identifies the row on multi-role pairs).
WriteOutcome unlink_asset(const fs::path& project_file,
                          const std::string& entity_type,
                          const std::string& entity_id,
                          const std::string& asset_id,
                          const std::string& role);

// Move one link row's role (identity fields preserved; primary demotes
// siblings of the NEW role; a pair already holding new_role refuses).
WriteOutcome set_asset_link_role(const fs::path& project_file,
                                 const std::string& entity_type,
                                 const std::string& entity_id,
                                 const std::string& asset_id,
                                 const std::string& old_role,
                                 const std::string& new_role);

// ---- tags (catalog.sqlite via the deep core) ------------------------------

// Add tag_names to every asset (names normalized by the TagStore: ASCII
// fold + whitespace collapse; blank names rejected up front). One bulk
// transaction per name.
WriteOutcome add_tags(const fs::path& project_file,
                      const std::vector<std::string>& asset_ids,
                      const std::vector<std::string>& tag_names);

WriteOutcome remove_tags(const fs::path& project_file,
                         const std::vector<std::string>& asset_ids,
                         const std::string& tag_name);

struct AssetTags {
    std::string asset_id;
    std::vector<std::string> tags;  // display names, document order
};

// Per-asset tag display names (assets with no tags still appear, empty).
std::vector<AssetTags> tags_for_assets(
    const fs::path& project_file,
    const std::vector<std::string>& asset_ids);

// Every tag name in the catalog (normalized names, document order).
std::vector<std::string> all_tag_names(const fs::path& project_file);

// ---- trash (soft delete; entity links are KEPT — history stays
// resolvable, restore revives both sides; purge stays with the catalog's
// own GC path, never automatic here) ---------------------------------------

struct TrashedEntry {
    std::string asset_id;
    std::string name;
    std::string type;
    std::string reason;      // first trashed version's tombstone reason
    std::string trashed_at;  // asset tombstone stamp
    int version_count = 0;   // trashed versions of the asset
};

std::vector<TrashedEntry> trashed_assets(const fs::path& project_file);

// Soft-delete assets (payloads move to artifacts/trash/, catalog rows get
// tombstones). Per-asset two-phase save; the outcome reports exactly how
// many landed when a later asset fails.
WriteOutcome trash_assets(const fs::path& project_file,
                          const std::vector<std::string>& asset_ids,
                          const std::string& reason);

WriteOutcome restore_assets(const fs::path& project_file,
                            const std::vector<std::string>& asset_ids);

// ---- delete impact (read model over catalog::ImpactService) ---------------

struct ImpactFacts {
    bool ok = false;
    std::string error;
    int affected_versions = 0;
    int live_descendants = 0;   // direct + indirect (supersede-aware BFS)
    int broken_edges = 0;
    int linked_entities = 0;
    std::vector<std::string> advice;  // service-supplied Chinese advice
};

// What breaks if this version (or the asset's current version when only
// the asset is given) disappears: downstream consumers, lineage edges and
// entity bindings. Cycle-guarded and node-budgeted by the service.
ImpactFacts delete_impact_facts(
    const fs::path& project_file,
    const std::optional<std::string>& version_id,
    const std::optional<std::string>& asset_id);

}  // namespace pwb::data::governance
