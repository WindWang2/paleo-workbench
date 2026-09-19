// Legacy ResourceItem → catalog projection + the catalog→legacy mirror
// (conv-31; catalog/migration.py + catalog/legacy_projection.py parity).
//
// migrate_resources projects `.paleo.json` resources[] rows into the
// CatalogDocument in place: one DataAsset + one unmanaged RAW DataVersion
// per resource, id reused, legacy_resource_id recorded — a pure metadata
// projection (no file copies, never managed, #396/C34), idempotent on
// both the projected id and the adapter bridge id, with the #1221 stat
// fingerprint backfill for identity-less external links and #1175 unsafe
// id sanitization.
//
// legacy_projection owns the reverse direction: the catalog is
// authoritative, resources[] is a derived mirror — removal by bridge-id
// set and idempotent re-surfacing, never a third data model.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/domain/json.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

struct MigrationReport {
    int migrated_count = 0;
    int skipped_count = 0;
    std::vector<std::string> asset_ids;
    std::vector<std::string> warnings;
};

// One legacy resources[] row in its persisted .paleo.json shape (the
// ProjectDocument JSON tree is the C++ source of truth — typed Resource
// entities do not exist there).
struct LegacyResourceRow {
    std::string id;
    std::string name;
    std::string type;
    std::string path;
    std::string format;
    std::optional<std::string> checksum;  // "checksum" column, may be absent
    std::vector<std::string> tags;
    domain::Json parsed_summary = domain::Json::object();
    std::optional<std::string> status;
    std::optional<std::string> source;
    std::optional<std::string> artifact_role;
    std::optional<std::string> crs;

    static LegacyResourceRow from_json(const domain::Json& row);
};

// migration.migrate_resources parity. *now supplies created/updated
// timestamps (deterministic tests).
MigrationReport migrate_resources(const std::vector<LegacyResourceRow>& resources,
                                  const std::filesystem::path& project_path,
                                  CatalogDocument* document,
                                  const std::function<std::string()>& now = nullptr);

// migration.needs_migration parity.
std::vector<LegacyResourceRow> needs_migration(
    const std::vector<LegacyResourceRow>& resources,
    const CatalogDocument& document);

// ---- legacy_projection.py ---------------------------------------------------

// The legacy ResourceItem.id an asset projects onto (open-migration rule).
std::string legacy_bridge_id(const DataAsset& asset);

// Mutations over the .paleo.json JSON tree (the C++ project document is a
// JSON view): drop legacy resources/export_artifacts rows whose id is in
// the bridge-id set of the affected assets; idempotent upsert of one
// companion row. Returns rows removed / whether the tree changed.
int remove_legacy_resources_for_assets(domain::Json* project_root,
                                       const std::vector<DataAsset>& assets);
int remove_legacy_resources_by_ids(domain::Json* project_root,
                                   const std::vector<std::string>& ids);
bool upsert_legacy_resource(domain::Json* project_root,
                            const domain::Json& item_row);

}  // namespace pwb::catalog
