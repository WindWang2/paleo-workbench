// SQL read side over the canonical catalog.sqlite (conv-31b; db.py lazy
// entity reads + query surface parity — R2 recon contract, frozen in
// 31b-findings). Sibling of queries.hpp (the document-scan path): the
// same AssetSearchQuery feeds both, so cross-path tests assert one query
// object against both sides.
//
// Every function degrades silently: missing file / missing table /
// prepare failure / step error → the default return, never an error —
// the composed behavior of Python's _read_rows + _safe with the service
// layer's try/except warm fallback folded in (single-connection model,
// findings B-2). Row order matches load_document (rowid) so lazy results
// are drop-in identical to the eager document's; exceptions are called
// out per function.
//
// CONV-31b: implemented in Wave2-A3 (src/queries_sql.cpp). Row decoding
// goes through src/row_mapping.hpp (single mapping source, findings
// §C-10); SELECTs list explicit column names (never SELECT *).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/queries.hpp"  // AssetSearchQuery (shared, dual-path)
#include "pwb/catalog/sqlite.hpp"

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::catalog {

// ---- lazy single-entity reads (db.py:1745-1949, #1212) ---------------------
// CONV-31b: implemented in Wave2-A3.

std::optional<DataAsset> get_asset_model(Database& db, const std::string& id);

// Output order = FIRST-SEEN request id order (not row order); duplicates
// keep the first occurrence; ids fetched in 500-id chunks (the chunking
// is part of the Python behavior — findings R2 ⑥-8).
std::vector<std::pair<std::string, DataAsset>> get_asset_models(
    Database& db, const std::vector<std::string>& ids);

// + version_members attached when the table exists (else empty members —
// pre-V11 equivalent).
std::optional<DataVersion> get_version_model(Database& db,
                                             const std::string& id);
// + run_inputs/run_outputs in link-table rowid order + ports (a port
// whose direction is not "output" lands in input_ports — the else
// branch is the contract, do not tighten it).
std::optional<DataRun> get_run_model(Database& db, const std::string& id);

// trashed_only=true → WHERE trashed = 1; else include_trashed (default
// true) → unfiltered, false → WHERE trashed = 0. ORDER BY rowid.
std::vector<DataAsset> list_asset_models(Database& db,
                                         bool include_trashed = true,
                                         bool trashed_only = false);

// (id, name, legacy_resource_id) with NULL normalized to "" (#1269 —
// never hydrates a DataAsset).
struct AssetIdentityRow {
    std::string id;
    std::string name;
    std::string legacy_resource_id;
};
std::vector<AssetIdentityRow> list_asset_identity_rows(
    Database& db, bool include_trashed = false);

std::vector<DataRun> list_run_models(Database& db);
std::vector<DataVersion> list_version_models_for_asset(
    Database& db, const std::string& asset_id);
std::vector<DataVersion> list_all_version_models(Database& db);
// Mirror of the DocumentIndex child index (lineage join, document order).
std::vector<DataVersion> child_version_models(
    Database& db, const std::string& parent_version_id);
std::vector<Tag> list_tag_models(Database& db);
// Ordered by the TAGS table's rowid (not the association rows').
std::vector<Tag> tags_for_version(Database& db, const std::string& version_id);
std::vector<std::string> tag_ids_for_asset(Database& db,
                                           const std::string& asset_id);

// ---- query surface (db.py:2631-3142) ----------------------------------------
// CONV-31b: implemented in Wave2-A3.

// SQL path of search_assets: SQL text mirrors db.py branch-for-branch
// (EXISTS-tag lookups, json_extract metadata equality with
// `$."{key}"` paths, name_search LIKE ESCAPE '\'), NO ORDER BY and NO
// trashed predicate (include_trashed is a post-filter here — the
// queries.py consumer filter folded in, findings B-3). Empty-string
// metadata values are dropped before binding (queries.py:126). Row order
// is the SQL scan order; cross-path assertions compare sorted sets.
std::vector<std::string> search_assets_sql(Database& db,
                                           const AssetSearchQuery& query);

struct CatalogAggregates {
    std::int64_t total = 0;
    std::map<std::string, std::int64_t> stages;    // current-version join
    std::map<std::string, std::int64_t> types;
    std::map<std::string, std::int64_t> tags;      // display-or-name keys
    std::map<std::string, std::int64_t> review_status;
};
CatalogAggregates catalog_aggregates_sql(Database& db,
                                         bool include_trashed = false);

// ORDER BY version_number; members NOT attached (Python dict shape has
// no members key here).
std::vector<DataVersion> list_versions_sql(Database& db,
                                           const std::string& asset_id);

struct LineageEdges {
    std::vector<std::string> parents;
    std::vector<std::string> children;
};
LineageEdges lineage_edges_sql(Database& db, const std::string& version_id);

// Tag name is normalized before matching; results INCLUDE trashed
// entities; ORDER BY a.id / v.id.
std::vector<std::string> assets_for_tag_sql(Database& db,
                                            const std::string& tag_name);
std::vector<std::string> versions_for_tag_sql(Database& db,
                                              const std::string& tag_name);

// Tier 1 of the import-dedup ladder (O(log N)). The INDEXED BY clauses
// are a BEHAVIOR contract (#1139/#1043): a missing index makes prepare
// fail → nullopt → the caller falls back to a scan. Correctness never
// depends on the index; do not retry without it.
std::optional<std::string> find_managed_raw_sql(
    Database& db, const std::string& source_uri, const std::string& sha256);
std::optional<std::string> find_external_by_path_sql(Database& db,
                                                     const std::string& path);

// V14-DATA-LINEAGE: distinct run ids whose inputs OR outputs touch any
// version of the given assets (entity workspace related-runs rollup).
// Silent degrade; pre-V11 stores fall back to the versions.run_id column.
std::vector<std::string> run_ids_touching_assets(
    Database& db, const std::vector<std::string>& asset_ids);

// V14-DATA-LINEAGE: per-asset version rollup (entity workspace read
// model): total version count + current-version display fields, in two
// chunked statements per 500 ids. Silent degrade.
struct AssetVersionRollup {
    int version_count = 0;
    bool has_current = false;
    std::string current_stage;
    std::string current_format;
    bool current_trashed = false;
    bool current_managed = true;
    std::string current_path;
    int current_member_count = 0;
};
using AssetVersionRollupMap = std::map<std::string, AssetVersionRollup>;
AssetVersionRollupMap asset_version_rollups_sql(
    Database& db, const std::vector<std::string>& asset_ids);

}  // namespace pwb::catalog
