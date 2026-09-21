// SQL read side over the canonical catalog.sqlite (conv-31b Wave2-A3;
// db.py lazy entity reads (1745-1949) + query surface (2631-3142) parity,
// R2 recon contract frozen in 31b-findings). Sibling of queries.cpp (the
// document-scan path) — both consume the same AssetSearchQuery, so a
// cross-path test feeds one query object to both sides (audit #849-2).
//
// Every entry point degrades silently (findings B-2/B-10): missing table /
// prepare failure / step error → the default return, never an error. That
// folds Python's two channels — _read_rows ([] on absent store/schema,
// raise otherwise → the service's warm fallback) and _safe (always the
// default) — into one never-throw shape for the single-connection model.
// A step() that returns false mid-scan is indistinguishable from DONE
// through the Statement API, so a hard read error can surface as a short
// result instead of the default; the prepare gate covers the reachable
// degradation paths (absent store, absent table, absent index).
//
// First invariant: row order matches load_document (rowid) so lazy results
// are drop-in identical to the eager document's. SELECTs list explicit
// columns in the row_mapping.hpp contract order (never SELECT * — the
// mappers read by position and `SELECT *` would also surface name_search).
//
// Frozen shape notes: search_assets keeps NO trashed predicate and NO
// ORDER BY (include_trashed is the folded queries.py post-filter, findings
// B-3; row order is the SQL scan order); its stage JOIN matches ANY
// version of the asset — never unify with the paging path's
// current-version subquery or the aggregates' current-version join (three
// deliberately different semantics, R2 ⑥-2); find_* keep INDEXED BY
// verbatim (#1139/#1043) — a missing index makes prepare fail → nullopt →
// the caller falls back to a scan (correctness never depends on the
// index; do not retry without it). The aggregates review bucket skips
// NULL and empty-string keys (`if value:`); a numeric-zero json_extract
// is indistinguishable from the text "0" through the text() API, so that
// unreachable hand-edited edge (governance values are a string
// vocabulary) stays kept here — recorded as an honest fold.
#include "pwb/catalog/queries_sql.hpp"

#include "pwb/catalog/entity_view.hpp"  // normalize_search_name/tag_name — the only fold
#include "pwb/catalog/queries.hpp"      // AssetSearchQuery, metadata_search_value

#include "row_mapping.hpp"             // rows::asset_from_row / version_from_row

#include <algorithm>
#include <cstddef>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace pwb::catalog {

namespace {

using domain::Json;

// db.py batches every IN (...) read at 500 ids (SQLITE_LIMIT_VARIABLE_
// NUMBER is far higher; the chunking itself is behavior — the chunk
// sequence drives get_asset_models' first-seen output order, R2 ⑥-8).
constexpr std::size_t kChunk = 500;

// Explicit column lists — the row_mapping.hpp position contracts (assets
// and versions) plus the runs/tags/port/member shapes shared with
// repository.cpp's load_document decode.
const std::string kAssetColumns =
    "id, name, type, description, current_version_id, legacy_resource_id,"
    " metadata, created_at, updated_at, trashed, trashed_at";
const std::string kAssetColumnsAliased =
    "a.id, a.name, a.type, a.description, a.current_version_id,"
    " a.legacy_resource_id, a.metadata, a.created_at, a.updated_at,"
    " a.trashed, a.trashed_at";
const std::string kVersionColumns =
    "id, asset_id, version_number, stage, managed, path, source_uri, format,"
    " size_bytes, sha256, run_id, metadata, created_at, trashed, trashed_at,"
    " parent_ids";
const std::string kRunColumns =
    "id, operation, parameters, generator, status, model_ref, created_at";
const std::string kTagColumns = "id, name, display_name, metadata";

// db.py like_escape_literal (268): % and _ are wildcards in the index
// path but literals in the canonical scan; escaping keeps both paths'
// matching semantics identical (#849-2). Same-text file-local copy as
// paged_sql.cpp:27 (R2 ②-1 — do not touch the delivered TU).
std::string like_escape_literal(const std::string& text) {
    std::string escaped;
    escaped.reserve(text.size());
    for (const char c : text) {
        if (c == '\\' || c == '%' || c == '_') escaped.push_back('\\');
        escaped.push_back(c);
    }
    return escaped;
}

// queries.py:126 — metadata pairs whose string form strips to "" are
// dropped before the SQL layer ever sees them.
bool strips_to_empty(const std::string& text) {
    for (const char c : text) {
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r') return false;
    }
    return true;
}

std::string joined_placeholders(std::size_t count, const char* separator) {
    std::string placeholders;
    for (std::size_t i = 0; i < count; ++i) {
        if (i != 0) placeholders += separator;
        placeholders += "?";
    }
    return placeholders;
}

void bind_params(Statement& statement, const std::vector<std::string>& params) {
    std::size_t next = 1;
    for (const std::string& param : params) {
        statement.bind(int(next++), param);
    }
}

// rows::run_from_row / rows::tag_from_row come from row_mapping.hpp
// (findings §C-10 — the six mappers' single source; D-16 keeps this TU a
// consumer, never a second definition).

// db.py _members_for_versions (228): batched member rows keyed by version
// id, link-table rowid order kept (document order within each version).
std::map<std::string, std::vector<VersionMember>> members_for_versions(
    Database& db, const std::vector<std::string>& version_ids) {
    std::map<std::string, std::vector<VersionMember>> out;
    for (std::size_t start = 0; start < version_ids.size(); start += kChunk) {
        const std::size_t end =
            std::min(start + kChunk, version_ids.size());
        Statement rows = db.prepare(
            "SELECT version_id, name, rel_path, member_role, ordinal,"
            " required, sha256, size_bytes FROM version_members"
            " WHERE version_id IN (" +
            joined_placeholders(end - start, ",") + ") ORDER BY rowid");
        if (!rows.is_valid()) continue;
        for (std::size_t i = start; i < end; ++i) {
            rows.bind(int(i - start + 1), version_ids[i]);
        }
        while (rows.step()) {
            VersionMember member;
            member.name = rows.text(1);
            member.rel_path = rows.text(2);
            member.member_role = rows.text(3);
            member.ordinal = static_cast<int>(rows.int64(4));
            member.required = rows.int64(5) != 0;
            if (!rows.is_null(6)) member.sha256 = rows.text(6);
            if (!rows.is_null(7)) member.size_bytes = rows.int64(7);
            out[rows.text(0)].push_back(std::move(member));
        }
    }
    return out;
}

// db.py _attach_members (1885): only when the table exists — a store
// without version_members reads versions with empty members (pre-V11
// equivalent). Fresh models start empty, so assignment == append.
void attach_members(Database& db, std::vector<DataVersion>& versions) {
    if (versions.empty() || !db.table_exists("version_members")) return;
    std::vector<std::string> ids;
    ids.reserve(versions.size());
    for (const DataVersion& version : versions) {
        ids.push_back(version.id.str());
    }
    std::map<std::string, std::vector<VersionMember>> members =
        members_for_versions(db, ids);
    for (DataVersion& version : versions) {
        auto it = members.find(version.id.str());
        if (it != members.end()) version.members = it->second;
    }
}

// One run_ports row in table order (direction kept raw for bucketing).
struct PortRow {
    std::string run_id;
    std::string direction;
    std::string role;
    std::string version_id;
    int ordinal = 0;
    bool required = true;
    std::string entity_type;
    std::string entity_id;
    std::string note;
};

// db.py _ports_for_runs (167): batched port rows keyed by run id, rowid
// order kept. Callers gate on table_exists("run_ports") exactly like
// Python does before calling it.
std::map<std::string, std::vector<PortRow>> ports_for_runs(
    Database& db, const std::vector<std::string>& run_ids) {
    std::map<std::string, std::vector<PortRow>> out;
    for (std::size_t start = 0; start < run_ids.size(); start += kChunk) {
        const std::size_t end = std::min(start + kChunk, run_ids.size());
        Statement rows = db.prepare(
            "SELECT run_id, direction, role, version_id, ordinal, required,"
            " entity_type, entity_id, note FROM run_ports"
            " WHERE run_id IN (" +
            joined_placeholders(end - start, ",") + ") ORDER BY rowid");
        if (!rows.is_valid()) continue;
        for (std::size_t i = start; i < end; ++i) {
            rows.bind(int(i - start + 1), run_ids[i]);
        }
        while (rows.step()) {
            PortRow port;
            port.run_id = rows.text(0);
            port.direction = rows.text(1);
            port.role = rows.text(2);
            port.version_id = rows.text(3);
            port.ordinal = static_cast<int>(rows.int64(4));
            port.required = rows.int64(5) != 0;
            port.entity_type = rows.text(6);
            port.entity_id = rows.text(7);
            port.note = rows.text(8);
            out[rows.text(0)].push_back(std::move(port));
        }
    }
    return out;
}

// db.py _attach_run_ports (148): direction == "output" → output_ports,
// ANY other value → input_ports. The else branch is the contract — do not
// tighten it (a dirty direction must keep bucketing as input, R2 ⑥-10).
// RunPort::direction stays at its default: Python's RunPort carries no
// direction field and the eager load leaves the default too (lazy/eager
// parity).
void attach_run_ports(DataRun& run, const std::vector<PortRow>& rows) {
    for (const PortRow& row : rows) {
        RunPort port;
        port.role = row.role;
        port.version_id = domain::VersionId(row.version_id);
        port.ordinal = row.ordinal;
        port.required = row.required;
        port.entity_type = row.entity_type;
        port.entity_id = row.entity_id;
        port.note = row.note;
        if (row.direction == "output") {
            run.output_ports.push_back(std::move(port));
        } else {
            run.input_ports.push_back(std::move(port));
        }
    }
}

}  // namespace

// ---- lazy single-entity reads (db.py:1745-1949, #1212) ----------------------

std::optional<DataAsset> get_asset_model(Database& db, const std::string& id) {
    Statement rows = db.prepare(
        "SELECT " + kAssetColumns + " FROM assets WHERE id = ?");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, id);
    if (!rows.step()) return std::nullopt;
    return rows::asset_from_row(rows);
}

std::vector<std::pair<std::string, DataAsset>> get_asset_models(
    Database& db, const std::vector<std::string>& ids) {
    // Output order = first-seen request id order, duplicates keep the
    // first occurrence; ids fetched in 500-id chunks (db.py:1749, V8 M9).
    std::vector<std::pair<std::string, DataAsset>> out;
    std::set<std::string> emitted;
    for (std::size_t start = 0; start < ids.size(); start += kChunk) {
        const std::size_t end = std::min(start + kChunk, ids.size());
        Statement rows = db.prepare(
            "SELECT " + kAssetColumns + " FROM assets WHERE id IN (" +
            joined_placeholders(end - start, ",") + ")");
        if (!rows.is_valid()) return {};
        for (std::size_t i = start; i < end; ++i) {
            rows.bind(int(i - start + 1), ids[i]);
        }
        std::map<std::string, DataAsset> row_by_id;
        while (rows.step()) {
            DataAsset asset = rows::asset_from_row(rows);
            row_by_id.emplace(asset.id.str(), std::move(asset));
        }
        for (std::size_t i = start; i < end; ++i) {
            auto it = row_by_id.find(ids[i]);
            if (it == row_by_id.end()) continue;
            if (!emitted.insert(ids[i]).second) continue;
            out.emplace_back(ids[i], it->second);
        }
    }
    return out;
}

std::optional<DataVersion> get_version_model(Database& db,
                                             const std::string& id) {
    Statement rows = db.prepare(
        "SELECT " + kVersionColumns + " FROM versions WHERE id = ?");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, id);
    if (!rows.step()) return std::nullopt;
    DataVersion version = rows::version_from_row(rows);
    std::vector<DataVersion> one;
    one.push_back(std::move(version));
    attach_members(db, one);
    return one.front();
}

std::optional<DataRun> get_run_model(Database& db, const std::string& id) {
    Statement rows =
        db.prepare("SELECT " + kRunColumns + " FROM runs WHERE id = ?");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, id);
    if (!rows.step()) return std::nullopt;
    DataRun run = rows::run_from_row(rows);
    {
        Statement inputs = db.prepare(
            "SELECT version_id FROM run_inputs WHERE run_id = ?"
            " ORDER BY rowid");
        if (!inputs.is_valid()) return std::nullopt;
        inputs.bind(1, id);
        while (inputs.step()) {
            run.input_version_ids.emplace_back(inputs.text(0));
        }
    }
    {
        Statement outputs = db.prepare(
            "SELECT version_id FROM run_outputs WHERE run_id = ?"
            " ORDER BY rowid");
        if (!outputs.is_valid()) return std::nullopt;
        outputs.bind(1, id);
        while (outputs.step()) {
            run.output_version_ids.emplace_back(outputs.text(0));
        }
    }
    if (db.table_exists("run_ports")) {
        auto ports = ports_for_runs(db, {id});
        auto it = ports.find(id);
        if (it != ports.end()) attach_run_ports(run, it->second);
    }
    return run;
}

std::vector<DataAsset> list_asset_models(Database& db, bool include_trashed,
                                         bool trashed_only) {
    // trashed_only → WHERE trashed = 1; elif include_trashed → no
    // predicate; else → WHERE trashed = 0 (db.py:1803; note the default
    // include_trashed=True is the inverse of the identity rows below).
    std::string sql = "SELECT " + kAssetColumns + " FROM assets";
    if (trashed_only) {
        sql += " WHERE trashed = 1";
    } else if (!include_trashed) {
        sql += " WHERE trashed = 0";
    }
    sql += " ORDER BY rowid";
    Statement rows = db.prepare(sql);
    if (!rows.is_valid()) return {};
    std::vector<DataAsset> assets;
    while (rows.step()) assets.push_back(rows::asset_from_row(rows));
    return assets;
}

std::vector<AssetIdentityRow> list_asset_identity_rows(
    Database& db, bool include_trashed) {
    std::string sql =
        "SELECT id, name, legacy_resource_id FROM assets";
    if (!include_trashed) sql += " WHERE trashed = 0";
    sql += " ORDER BY rowid";
    Statement rows = db.prepare(sql);
    if (!rows.is_valid()) return {};
    std::vector<AssetIdentityRow> identities;
    while (rows.step()) {
        // str(row[...] or "") — NULL normalizes to "" (#1269, never
        // hydrates a DataAsset; text() already folds NULL to "").
        AssetIdentityRow identity;
        identity.id = rows.text(0);
        identity.name = rows.text(1);
        identity.legacy_resource_id = rows.text(2);
        identities.push_back(std::move(identity));
    }
    return identities;
}

std::vector<DataRun> list_run_models(Database& db) {
    Statement rows = db.prepare(
        "SELECT " + kRunColumns + " FROM runs ORDER BY rowid");
    if (!rows.is_valid()) return {};
    std::vector<DataRun> runs;
    while (rows.step()) runs.push_back(rows::run_from_row(rows));
    if (runs.empty()) return {};
    std::map<std::string, std::vector<domain::VersionId>> inputs_by_run;
    {
        Statement link = db.prepare(
            "SELECT run_id, version_id FROM run_inputs ORDER BY rowid");
        if (!link.is_valid()) return {};
        while (link.step()) {
            inputs_by_run[link.text(0)].emplace_back(link.text(1));
        }
    }
    std::map<std::string, std::vector<domain::VersionId>> outputs_by_run;
    {
        Statement link = db.prepare(
            "SELECT run_id, version_id FROM run_outputs ORDER BY rowid");
        if (!link.is_valid()) return {};
        while (link.step()) {
            outputs_by_run[link.text(0)].emplace_back(link.text(1));
        }
    }
    for (DataRun& run : runs) {
        auto inputs = inputs_by_run.find(run.id.str());
        if (inputs != inputs_by_run.end()) {
            run.input_version_ids = inputs->second;
        }
        auto outputs = outputs_by_run.find(run.id.str());
        if (outputs != outputs_by_run.end()) {
            run.output_version_ids = outputs->second;
        }
    }
    if (db.table_exists("run_ports")) {
        std::vector<std::string> run_ids;
        run_ids.reserve(runs.size());
        for (const DataRun& run : runs) run_ids.push_back(run.id.str());
        auto ports = ports_for_runs(db, run_ids);
        for (DataRun& run : runs) {
            auto it = ports.find(run.id.str());
            if (it != ports.end()) attach_run_ports(run, it->second);
        }
    }
    return runs;
}

std::vector<DataVersion> list_version_models_for_asset(
    Database& db, const std::string& asset_id) {
    // Document order within an asset is rowid; the public list_versions
    // (list_versions_sql below) is the one that sorts by version_number.
    Statement rows = db.prepare(
        "SELECT " + kVersionColumns +
        " FROM versions WHERE asset_id = ? ORDER BY rowid");
    if (!rows.is_valid()) return {};
    rows.bind(1, asset_id);
    std::vector<DataVersion> versions;
    while (rows.step()) versions.push_back(rows::version_from_row(rows));
    attach_members(db, versions);
    return versions;
}

std::vector<DataVersion> list_all_version_models(Database& db) {
    Statement rows = db.prepare(
        "SELECT " + kVersionColumns + " FROM versions ORDER BY rowid");
    if (!rows.is_valid()) return {};
    std::vector<DataVersion> versions;
    while (rows.step()) versions.push_back(rows::version_from_row(rows));
    attach_members(db, versions);
    return versions;
}

std::vector<DataVersion> child_version_models(
    Database& db, const std::string& parent_version_id) {
    Statement rows = db.prepare(
        "SELECT v.id, v.asset_id, v.version_number, v.stage, v.managed,"
        " v.path, v.source_uri, v.format, v.size_bytes, v.sha256, v.run_id,"
        " v.metadata, v.created_at, v.trashed, v.trashed_at, v.parent_ids"
        " FROM versions v JOIN lineage l ON l.child_version_id = v.id"
        " WHERE l.parent_version_id = ? ORDER BY v.rowid");
    if (!rows.is_valid()) return {};
    rows.bind(1, parent_version_id);
    std::vector<DataVersion> versions;
    while (rows.step()) versions.push_back(rows::version_from_row(rows));
    attach_members(db, versions);
    return versions;
}

std::vector<Tag> list_tag_models(Database& db) {
    Statement rows = db.prepare(
        "SELECT " + kTagColumns + " FROM tags ORDER BY rowid");
    if (!rows.is_valid()) return {};
    std::vector<Tag> tags;
    while (rows.step()) tags.push_back(rows::tag_from_row(rows));
    return tags;
}

std::vector<Tag> tags_for_version(Database& db, const std::string& version_id) {
    // Ordered by the TAGS table's rowid, not the association rows'.
    Statement rows = db.prepare(
        "SELECT t.id, t.name, t.display_name, t.metadata FROM tags t"
        " JOIN version_tags vt ON vt.tag_id = t.id"
        " WHERE vt.version_id = ? ORDER BY t.rowid");
    if (!rows.is_valid()) return {};
    rows.bind(1, version_id);
    std::vector<Tag> tags;
    while (rows.step()) tags.push_back(rows::tag_from_row(rows));
    return tags;
}

std::vector<std::string> tag_ids_for_asset(Database& db,
                                           const std::string& asset_id) {
    Statement rows = db.prepare(
        "SELECT tag_id FROM asset_tags WHERE asset_id = ? ORDER BY rowid");
    if (!rows.is_valid()) return {};
    rows.bind(1, asset_id);
    std::vector<std::string> tag_ids;
    while (rows.step()) tag_ids.push_back(rows.text(0));
    return tag_ids;
}

// ---- query surface (db.py:2631-3142) ----------------------------------------

std::vector<std::string> search_assets_sql(Database& db,
                                           const AssetSearchQuery& query) {
    // SQL text mirrors db.py _search_assets branch-for-branch (2661-2724):
    // stage → ANY-version JOIN, tag → EXISTS per branch (index-backed, no
    // DISTINCT fanout), text → name_search LIKE ESCAPE '\', type → =,
    // metadata → CAST(json_extract ...) = . No ORDER BY, no trashed
    // predicate (B-3: include_trashed is the post-filter below). tag_op
    // is NOT validated here — anything but "or" takes the AND shape,
    // exactly like db.py (the composition layer validates).
    std::vector<std::string> joins;
    std::vector<std::string> wheres;
    std::vector<std::string> params;
    if (query.stage.has_value()) {
        joins.push_back("JOIN versions v ON v.asset_id = a.id");
        wheres.push_back("v.stage = ?");
        params.push_back(std::string(domain::to_string(*query.stage)));
    }
    std::vector<std::string> tag_list;
    for (const std::string& tag : query.tags) {
        std::string normalized = normalize_tag_name(tag);
        if (!normalized.empty()) tag_list.push_back(std::move(normalized));
    }
    if (!tag_list.empty()) {
        if (query.tag_op == "or") {
            wheres.push_back(
                "EXISTS (SELECT 1 FROM asset_tags at_o"
                " JOIN tags t_o ON t_o.id = at_o.tag_id"
                " WHERE at_o.asset_id = a.id AND t_o.name IN (" +
                joined_placeholders(tag_list.size(), ", ") + "))");
            params.insert(params.end(), tag_list.begin(), tag_list.end());
        } else {
            for (const std::string& tag : tag_list) {
                wheres.push_back(
                    "EXISTS (SELECT 1 FROM asset_tags at_a"
                    " JOIN tags t_a ON t_a.id = at_a.tag_id"
                    " WHERE at_a.asset_id = a.id AND t_a.name = ?)");
                params.push_back(tag);
            }
        }
    }
    if (!query.text.empty()) {
        // ASCII fold of entity_view (the declared bounded fold) — matches
        // the stored name_search column (#897).
        wheres.push_back("a.name_search LIKE ? ESCAPE '\\'");
        params.push_back(
            "%" + like_escape_literal(normalize_search_name(query.text)) +
            "%");
    }
    if (query.type.has_value()) {
        wheres.push_back("a.type = ?");
        params.push_back(*query.type);
    }
    for (const auto& [key, value] : query.metadata) {
        // queries.py:126 drop: a pair whose string form strips to "" never
        // reaches the SQL layer (bool/number forms are never empty).
        if (value.is_string() && strips_to_empty(value.get<std::string>())) {
            continue;
        }
        // The `$."{key}"` path keeps the key verbatim (B-33 — governance
        // vocabulary cannot reach the quote edge); the value takes the
        // db-layer canonical form (bool → "1"/"0", the oracle's frozen
        // db-layer bool quirk).
        wheres.push_back("CAST(json_extract(a.metadata, ?) AS TEXT) = ?");
        params.push_back("$.\"" + key + "\"");
        params.push_back(metadata_search_value(value));
    }
    std::string sql =
        "SELECT DISTINCT " + kAssetColumnsAliased + " FROM assets a";
    for (const std::string& join : joins) {
        sql += " ";
        sql += join;
    }
    if (!wheres.empty()) {
        sql += " WHERE ";
        for (std::size_t i = 0; i < wheres.size(); ++i) {
            if (i != 0) sql += " AND ";
            sql += wheres[i];
        }
    }
    Statement rows = db.prepare(sql);
    if (!rows.is_valid()) return {};
    bind_params(rows, params);
    std::vector<std::string> ids;
    while (rows.step()) {
        DataAsset asset = rows::asset_from_row(rows);
        if (!query.include_trashed && asset.trashed) continue;
        ids.push_back(asset.id.str());
    }
    return ids;
}

CatalogAggregates catalog_aggregates_sql(Database& db,
                                         bool include_trashed) {
    CatalogAggregates result;
    const std::string trash_sql =
        include_trashed ? "" : " WHERE a.trashed = 0";
    {
        // Current-version join — deliberately NOT the any-version join of
        // search_assets (db.py:3004, R2 ⑥-2).
        Statement rows = db.prepare(
            "SELECT v.stage, count(*) FROM assets a"
            " JOIN versions v ON v.id = a.current_version_id" +
            trash_sql + " GROUP BY v.stage");
        if (!rows.is_valid()) return CatalogAggregates{};
        while (rows.step()) result.stages[rows.text(0)] = rows.int64(1);
    }
    {
        Statement rows = db.prepare(
            "SELECT a.type, count(*) FROM assets a" + trash_sql +
            " GROUP BY a.type");
        if (!rows.is_valid()) return CatalogAggregates{};
        while (rows.step()) result.types[rows.text(0)] = rows.int64(1);
    }
    {
        Statement rows = db.prepare(
            "SELECT t.name, t.display_name, count(at_c.asset_id)"
            " FROM tags t"
            " JOIN asset_tags at_c ON at_c.tag_id = t.id"
            " JOIN assets a ON a.id = at_c.asset_id" +
            (include_trashed ? std::string()
                             : std::string(" WHERE a.trashed = 0")) +
            " GROUP BY t.id");
        if (!rows.is_valid()) return CatalogAggregates{};
        while (rows.step()) {
            const std::string display =
                rows.is_null(1) ? std::string() : rows.text(1);
            result.tags[display.empty() ? rows.text(0) : display] =
                rows.int64(2);
        }
    }
    {
        Statement rows = db.prepare(
            "SELECT json_extract(a.metadata, '$.review_status'), count(*)"
            " FROM assets a" +
            trash_sql + " GROUP BY 1");
        if (!rows.is_valid()) return CatalogAggregates{};
        while (rows.step()) {
            // Python `if value:` — NULL and the empty string never enter
            // the bucket (a numeric zero would also be falsy in Python;
            // unreachable for the governance string vocabulary, see the
            // TU header note).
            if (rows.is_null(0)) continue;
            const std::string key = rows.text(0);
            if (key.empty()) continue;
            result.review_status[key] = rows.int64(1);
        }
    }
    {
        Statement rows =
            db.prepare("SELECT count(*) FROM assets a" + trash_sql);
        if (!rows.is_valid()) return CatalogAggregates{};
        if (rows.step()) result.total = rows.int64(0);
    }
    return result;
}

std::vector<DataVersion> list_versions_sql(Database& db,
                                           const std::string& asset_id) {
    Statement rows = db.prepare(
        "SELECT " + kVersionColumns +
        " FROM versions WHERE asset_id = ? ORDER BY version_number");
    if (!rows.is_valid()) return {};
    rows.bind(1, asset_id);
    std::vector<DataVersion> versions;
    while (rows.step()) versions.push_back(rows::version_from_row(rows));
    return versions;
}

LineageEdges lineage_edges_sql(Database& db, const std::string& version_id) {
    LineageEdges edges;
    {
        // No ORDER BY — implicit rowid order, exactly like db.py:3063.
        Statement rows = db.prepare(
            "SELECT parent_version_id FROM lineage WHERE child_version_id ="
            " ?");
        if (!rows.is_valid()) return LineageEdges{};
        rows.bind(1, version_id);
        while (rows.step()) edges.parents.push_back(rows.text(0));
    }
    {
        Statement rows = db.prepare(
            "SELECT child_version_id FROM lineage WHERE parent_version_id ="
            " ?");
        if (!rows.is_valid()) return LineageEdges{};
        rows.bind(1, version_id);
        while (rows.step()) edges.children.push_back(rows.text(0));
    }
    return edges;
}

std::vector<std::string> assets_for_tag_sql(Database& db,
                                            const std::string& tag_name) {
    Statement rows = db.prepare(
        "SELECT a.id FROM assets a"
        " JOIN asset_tags at ON at.asset_id = a.id"
        " JOIN tags t ON t.id = at.tag_id"
        " WHERE t.name = ? ORDER BY a.id");
    if (!rows.is_valid()) return {};
    rows.bind(1, normalize_tag_name(tag_name));
    std::vector<std::string> ids;
    while (rows.step()) ids.push_back(rows.text(0));
    return ids;
}

std::vector<std::string> versions_for_tag_sql(Database& db,
                                              const std::string& tag_name) {
    Statement rows = db.prepare(
        "SELECT v.id FROM versions v"
        " JOIN version_tags vt ON vt.version_id = v.id"
        " JOIN tags t ON t.id = vt.tag_id"
        " WHERE t.name = ? ORDER BY v.id");
    if (!rows.is_valid()) return {};
    rows.bind(1, normalize_tag_name(tag_name));
    std::vector<std::string> ids;
    while (rows.step()) ids.push_back(rows.text(0));
    return ids;
}

std::optional<std::string> find_managed_raw_sql(
    Database& db, const std::string& source_uri, const std::string& sha256) {
    // INDEXED BY pins the covering index (#1139: without it the planner
    // prefers idx_versions_trashed — matching ~all rows, an effective
    // full scan). A missing index → prepare fails → nullopt → the caller
    // falls back to a scan; correctness never depends on the index.
    Statement rows = db.prepare(
        "SELECT id FROM versions INDEXED BY idx_versions_source_sha"
        " WHERE managed = 1 AND stage = 'raw'"
        " AND trashed = 0 AND source_uri = ? AND sha256 = ? LIMIT 1");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, source_uri);
    rows.bind(2, sha256);
    if (!rows.step()) return std::nullopt;
    return rows.text(0);
}

std::optional<std::string> find_external_by_path_sql(Database& db,
                                                     const std::string& path) {
    // INDEXED BY pins the partial covering index (#1043) — same trap, and
    // trashed versions must never resolve as dedup targets (review I2).
    Statement rows = db.prepare(
        "SELECT id FROM versions INDEXED BY idx_versions_external_path"
        " WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, path);
    if (!rows.step()) return std::nullopt;
    return rows.text(0);
}

// V14-DATA-LINEAGE: distinct run ids whose inputs OR outputs touch any
// version of the given assets (entity workspace "related runs"). Degrades
// silently like every entry point; ids chunked at the shared 500 ceiling.
// Pre-V11 stores without run_inputs/run_outputs tables (prepare failure)
// fall back to the runs.run_id column on versions of those assets.
std::vector<std::string> run_ids_touching_assets(
    Database& db, const std::vector<std::string>& asset_ids) {
    std::vector<std::string> result;
    if (asset_ids.empty()) return result;
    std::set<std::string> seen;
    const auto emit = [&](const std::string& id) {
        if (!id.empty() && seen.insert(id).second) result.push_back(id);
    };
    for (std::size_t begin = 0; begin < asset_ids.size(); begin += kChunk) {
        const std::size_t end =
            std::min(begin + kChunk, asset_ids.size());
        std::string sql =
            "SELECT DISTINCT ri.run_id FROM run_inputs ri"
            " JOIN versions v ON v.id = ri.version_id"
            " WHERE v.asset_id IN (";
        for (std::size_t i = begin; i < end; ++i) {
            sql += (i == begin ? "?" : ", ?");
        }
        sql += ") UNION SELECT DISTINCT ro.run_id FROM run_outputs ro"
               " JOIN versions v ON v.id = ro.version_id"
               " WHERE v.asset_id IN (";
        for (std::size_t i = begin; i < end; ++i) {
            sql += (i == begin ? "?" : ", ?");
        }
        sql += ")";
        Statement rows = db.prepare(sql);
        if (!rows.is_valid()) break;
        for (std::size_t i = begin; i < end; ++i) {
            const int slot = static_cast<int>(i - begin) + 1;
            rows.bind(slot, asset_ids[i]);
            rows.bind(slot + static_cast<int>(end - begin), asset_ids[i]);
        }
        while (rows.step()) emit(rows.text(0));
    }
    // UNION (not fallback): pre-run_inputs stores keep the flat
    // versions.run_id column, and runs registered WITHOUT typed ports
    // (e.g. a context-free manual_edit run) appear only there. Python-
    // written stores have no run_inputs/run_outputs tables at all, so
    // treating this as an all-or-nothing backup would silently drop runs
    // from the entity-workspace related-runs rollup.
    for (std::size_t begin = 0; begin < asset_ids.size(); begin += kChunk) {
        const std::size_t end =
            std::min(begin + kChunk, asset_ids.size());
        std::string sql =
            "SELECT DISTINCT v.run_id FROM versions v"
            " WHERE v.run_id IS NOT NULL AND v.asset_id IN (";
        for (std::size_t i = begin; i < end; ++i) {
            sql += (i == begin ? "?" : ", ?");
        }
        sql += ")";
        Statement rows = db.prepare(sql);
        if (!rows.is_valid()) break;
        for (std::size_t i = begin; i < end; ++i) {
            rows.bind(static_cast<int>(i - begin) + 1, asset_ids[i]);
        }
        while (rows.step()) emit(rows.text(0));
    }
    return result;
}

// V14-DATA-LINEAGE: per-asset version rollup for the entity workspace —
// one chunked GROUP BY for version counts + one chunked current-version
// JOIN for the display fields. Absent current pointer → default fields
// (nullopt stage). Silent degrade like every entry point.
AssetVersionRollupMap asset_version_rollups_sql(
    Database& db, const std::vector<std::string>& asset_ids) {
    AssetVersionRollupMap result;
    if (asset_ids.empty()) return result;
    for (std::size_t begin = 0; begin < asset_ids.size(); begin += kChunk) {
        const std::size_t end =
            std::min(begin + kChunk, asset_ids.size());
        std::string marks;
        for (std::size_t i = begin; i < end; ++i) {
            marks += (i == begin) ? "?" : ", ?";
        }
        std::vector<std::string> ids(asset_ids.begin() + begin,
                                     asset_ids.begin() + end);
        Statement counts = db.prepare(
            "SELECT asset_id, COUNT(*) FROM versions WHERE asset_id IN (" +
            marks + ") GROUP BY asset_id");
        if (counts.is_valid()) {
            for (std::size_t i = 0; i < ids.size(); ++i) {
                counts.bind(static_cast<int>(i) + 1, ids[i]);
            }
            while (counts.step()) {
                result[counts.text(0)].version_count =
                    static_cast<int>(counts.int64(1));
            }
        }
        Statement current = db.prepare(
            "SELECT a.id, v.stage, v.format, v.trashed, v.managed, v.path,"
            " (SELECT COUNT(*) FROM version_members m"
            "   WHERE m.version_id = v.id)"
            " FROM assets a LEFT JOIN versions v ON v.id ="
            " a.current_version_id WHERE a.id IN (" + marks + ")");
        if (current.is_valid()) {
            for (std::size_t i = 0; i < ids.size(); ++i) {
                current.bind(static_cast<int>(i) + 1, ids[i]);
            }
            while (current.step()) {
                AssetVersionRollup& rollup = result[current.text(0)];
                if (current.is_null(1)) continue;  // no current version
                rollup.has_current = true;
                rollup.current_stage = current.text(1);
                rollup.current_format = current.text(2);
                rollup.current_trashed = current.int64(3) != 0;
                rollup.current_managed = current.int64(4) != 0;
                rollup.current_path = current.text(5);
                rollup.current_member_count =
                    static_cast<int>(current.int64(6));
            }
        }
    }
    return result;
}

}  // namespace pwb::catalog
