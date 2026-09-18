// SQL-level paged asset reads (conv-26). Mirrors db.py `_paged_predicates`
// / `_search_assets_page` / `_count_assets` fragment-for-fragment: the
// paging SELECT joins versions only for the order keys that reference
// current-version columns, the keyset cursor fires only for name order,
// current-version rows are batch-fetched in 100-id IN chunks afterwards.
// Text/tag normalization reuses the bounded write-path fold
// (entity_view.hpp), so LIKE patterns match the stored name_search values.
#include "pwb/catalog/paged_sql.hpp"

#include "pwb/catalog/models.hpp"
#include "row_mapping.hpp"

#include <algorithm>
#include <map>
#include <string>
#include <vector>

namespace pwb::catalog {

namespace {

using domain::Json;

// db.py like_escape_literal: % and _ are wildcards in the index path but
// literal characters in the canonical scan; escaping keeps both paths'
// matching semantics identical.
std::string like_escape_literal(const std::string& text) {
    std::string escaped;
    escaped.reserve(text.size());
    for (const char c : text) {
        if (c == '\\' || c == '%' || c == '_') escaped.push_back('\\');
        escaped.push_back(c);
    }
    return escaped;
}

struct SqlFragment {
    std::vector<std::string> wheres;
    std::vector<std::string> params;  // bound as TEXT (assets keys are TEXT)
};

// db.py _PAGE_ORDER_COLUMNS; unknown keys fall back to name order. The
// paging SELECT always tails the order with ", a.id" for stability.
std::string order_columns(const std::string& order_by, bool* needs_version_join) {
    const std::string key = order_by.empty() ? std::string("name") : order_by;
    if (key == "name_desc") return "a.name DESC";
    if (key == "type") return "a.type, a.name";
    if (key == "stage") {
        *needs_version_join = true;
        return "v.stage, a.name";
    }
    if (key == "size") {
        *needs_version_join = true;
        return "v.size_bytes, a.name";
    }
    if (key == "modified") return "a.updated_at, a.name";
    if (key == "version") {
        *needs_version_join = true;
        return "v.version_number, a.name";
    }
    return "a.name";
}

SqlFragment paged_predicates(const EntityPageQuery& query) {
    SqlFragment sql;
    if (query.trashed_only) {
        sql.wheres.push_back("a.trashed = 1");
    } else if (!query.include_trashed) {
        sql.wheres.push_back("a.trashed = 0");
    }
    if (!query.text.empty()) {
        sql.wheres.push_back("a.name_search LIKE ? ESCAPE '\\'");
        sql.params.push_back("%" +
                             like_escape_literal(
                                 normalize_search_name(query.text)) +
                             "%");
    }
    if (query.stage.has_value()) {
        sql.wheres.push_back(
            "a.current_version_id IN (SELECT id FROM versions WHERE stage = ?)");
        sql.params.push_back(*query.stage);
    }
    if (query.type.has_value()) {
        sql.wheres.push_back("a.type = ?");
        sql.params.push_back(*query.type);
    }
    std::vector<std::string> tag_list;
    for (const std::string& tag : query.tags) {
        std::string trimmed = tag;
        while (!trimmed.empty() &&
               (trimmed.back() == ' ' || trimmed.back() == '\t' ||
                trimmed.back() == '\n' || trimmed.back() == '\r')) {
            trimmed.pop_back();
        }
        bool only_space = true;
        for (const char c : trimmed) {
            if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
                only_space = false;
                break;
            }
        }
        if (!trimmed.empty() && !only_space) {
            tag_list.push_back(normalize_tag_name(trimmed));
        }
    }
    if (!tag_list.empty()) {
        if (query.tag_op == "or") {
            std::string placeholders;
            for (std::size_t i = 0; i < tag_list.size(); ++i) {
                if (i != 0) placeholders += ", ";
                placeholders += "?";
            }
            sql.wheres.push_back(
                "a.id IN (SELECT at_p.asset_id FROM asset_tags at_p"
                " JOIN tags t_p ON t_p.id = at_p.tag_id"
                " WHERE t_p.name IN (" + placeholders + "))");
            for (const auto& tag : tag_list) sql.params.push_back(tag);
        } else {
            for (const auto& tag : tag_list) {
                sql.wheres.push_back(
                    "a.id IN (SELECT at_a.asset_id FROM asset_tags at_a"
                    " JOIN tags t_a ON t_a.id = at_a.tag_id"
                    " WHERE t_a.name = ?)");
                sql.params.push_back(tag);
            }
        }
    }
    if (!query.asset_id.empty()) {
        sql.wheres.push_back("a.id = ?");
        sql.params.push_back(query.asset_id);
    }
    if (!query.asset_ids.empty()) {
        // Chunk the IN predicate so a large entity-membership set cannot
        // blow SQLite's bound-variable limit (db.py chunks at 500).
        constexpr std::size_t kChunk = 500;
        for (std::size_t start = 0; start < query.asset_ids.size();
             start += kChunk) {
            const std::size_t end = std::min(start + kChunk,
                                             query.asset_ids.size());
            std::string placeholders;
            for (std::size_t i = start; i < end; ++i) {
                if (i != start) placeholders += ", ";
                placeholders += "?";
            }
            sql.wheres.push_back("a.id IN (" + placeholders + ")");
            for (std::size_t i = start; i < end; ++i) {
                sql.params.push_back(query.asset_ids[i]);
            }
        }
    }
    return sql;
}

}  // namespace

std::vector<Json> search_assets_page_sql(Database& db,
                                         const EntityPageQuery& query) {
    if (!db.table_exists("assets")) return {};
    SqlFragment sql = paged_predicates(query);
    const bool name_order = query.order_by.empty() || query.order_by == "name";
    if (query.after.has_value() && name_order) {
        sql.wheres.push_back("(a.name > ? OR (a.name = ? AND a.id > ?))");
        sql.params.push_back(query.after->first);
        sql.params.push_back(query.after->first);
        sql.params.push_back(query.after->second);
    }
    std::string where;
    if (!sql.wheres.empty()) {
        where = "WHERE " + [&sql] {
            std::string joined;
            for (std::size_t i = 0; i < sql.wheres.size(); ++i) {
                if (i != 0) joined += " AND ";
                joined += sql.wheres[i];
            }
            return joined;
        }();
    }
    bool needs_version_join = false;
    const std::string order = order_columns(query.order_by,
                                            &needs_version_join);
    const std::string join = needs_version_join
        ? " LEFT JOIN versions v ON v.id = a.current_version_id"
        : "";
    // Step 1: page the assets table alone (index order, no join unless the
    // order key itself references the current version).
    Statement page = db.prepare(
        "SELECT a.id, a.name, a.type, a.description, a.current_version_id,"
        " a.legacy_resource_id, a.metadata, a.created_at, a.updated_at,"
        " a.trashed, a.trashed_at FROM assets a" +
        join + " " + where + " ORDER BY " + order + ", a.id LIMIT ? OFFSET ?");
    if (!page.is_valid()) return {};
    std::size_t next = 1;
    for (const std::string& param : sql.params) page.bind(int(next++), param);
    page.bind(int(next), std::max<std::int64_t>(0, query.limit));
    page.bind(int(next + 1), std::max<std::int64_t>(0, query.offset));

    std::vector<DataAsset> assets;
    while (page.step()) assets.push_back(rows::asset_from_row(page));
    if (assets.empty()) return {};

    // Step 2: batch-fetch the page's current versions by primary key.
    std::map<std::string, DataVersion> versions_by_id;
    std::vector<std::string> version_ids;
    for (const DataAsset& asset : assets) {
        if (asset.current_version_id.has_value()) {
            version_ids.push_back(asset.current_version_id->str());
        }
    }
    constexpr std::size_t kChunk = 100;
    for (std::size_t start = 0; start < version_ids.size(); start += kChunk) {
        const std::size_t end = std::min(start + kChunk, version_ids.size());
        std::string placeholders;
        for (std::size_t i = start; i < end; ++i) {
            if (i != start) placeholders += ", ";
            placeholders += "?";
        }
        Statement rows = db.prepare(
            "SELECT id, asset_id, version_number, stage, managed, path,"
            " source_uri, format, size_bytes, sha256, run_id, metadata,"
            " created_at, trashed, trashed_at, parent_ids FROM versions"
            " WHERE id IN (" +
            placeholders + ")");
        if (!rows.is_valid()) continue;
        for (std::size_t i = start; i < end; ++i) {
            rows.bind(int(i - start + 1), version_ids[i]);
        }
        while (rows.step()) {
            DataVersion version = rows::version_from_row(rows);
            versions_by_id[version.id.str()] = std::move(version);
        }
    }

    std::vector<Json> result;
    result.reserve(assets.size());
    for (const DataAsset& asset : assets) {
        const DataVersion* current = nullptr;
        if (asset.current_version_id.has_value()) {
            auto it = versions_by_id.find(asset.current_version_id->str());
            if (it != versions_by_id.end()) current = &it->second;
        }
        result.push_back(asset_page_row(asset, current));
    }
    return result;
}

std::int64_t count_assets_sql(Database& db, const EntityPageQuery& query) {
    if (!db.table_exists("assets")) return 0;
    SqlFragment sql = paged_predicates(query);
    std::string where;
    if (!sql.wheres.empty()) {
        where = "WHERE " + [&sql] {
            std::string joined;
            for (std::size_t i = 0; i < sql.wheres.size(); ++i) {
                if (i != 0) joined += " AND ";
                joined += sql.wheres[i];
            }
            return joined;
        }();
    }
    Statement count = db.prepare(
        "SELECT count(*) FROM assets a " + where);
    if (!count.is_valid()) return 0;
    std::size_t next = 1;
    for (const std::string& param : sql.params) count.bind(int(next++), param);
    if (!count.step()) return 0;
    return count.int64(0);
}

}  // namespace pwb::catalog
