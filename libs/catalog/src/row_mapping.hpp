// Canonical SQLite row → model mappers for the assets/versions tables
// (internal to pwb_catalog; conv-26). Both the document loader
// (repository.cpp) and the SQL paging path (paged_sql.cpp) decode rows
// through these — a schema column change lands in exactly one place.
//
// Column contracts (the SELECTs must list columns in these orders):
//   assets:  id, name, type, description, current_version_id,
//            legacy_resource_id, metadata, created_at, updated_at,
//            trashed, trashed_at
//   versions: id, asset_id, version_number, stage, managed, path,
//             source_uri, format, size_bytes, sha256, run_id, metadata,
//             created_at, trashed, trashed_at, parent_ids
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"

#include <string>

namespace pwb::catalog::rows {

// A TEXT column that fails to parse falls back to the model default
// instead of poisoning the load.
inline domain::Json parse_json_column(const std::string& text,
                                      const char* fallback) {
    if (text.empty()) return domain::Json::parse(fallback, nullptr, false);
    domain::Json parsed = domain::Json::parse(text, nullptr, false);
    if (parsed.is_discarded()) {
        return domain::Json::parse(fallback, nullptr, false);
    }
    return parsed;
}

inline DataAsset asset_from_row(Statement& rows) {
    DataAsset asset;
    asset.id = domain::AssetId(rows.text(0));
    asset.name = rows.text(1);
    asset.type = rows.text(2);
    asset.description = rows.text(3);
    if (!rows.is_null(4)) {
        asset.current_version_id = domain::VersionId(rows.text(4));
    }
    if (!rows.is_null(5)) asset.legacy_resource_id = rows.text(5);
    asset.metadata = parse_json_column(rows.text(6), "{}");
    asset.created_at = rows.text(7);
    asset.updated_at = rows.text(8);
    asset.trashed = rows.int64(9) != 0;
    if (!rows.is_null(10)) asset.trashed_at = rows.text(10);
    return asset;
}

inline DataVersion version_from_row(Statement& rows) {
    DataVersion version;
    version.id = domain::VersionId(rows.text(0));
    version.asset_id = domain::AssetId(rows.text(1));
    version.version_number = static_cast<int>(rows.int64(2));
    if (auto stage = domain::data_stage_from_string(rows.text(3))) {
        version.stage = *stage;
    }
    version.managed = rows.int64(4) != 0;
    version.path = rows.text(5);
    if (!rows.is_null(6)) version.source_uri = rows.text(6);
    version.format = rows.text(7);
    if (!rows.is_null(8)) version.size_bytes = rows.int64(8);
    if (!rows.is_null(9)) version.sha256 = rows.text(9);
    if (!rows.is_null(10)) version.run_id = domain::RunId(rows.text(10));
    version.metadata = parse_json_column(rows.text(11), "{}");
    version.created_at = rows.text(12);
    version.trashed = rows.int64(13) != 0;
    if (!rows.is_null(14)) version.trashed_at = rows.text(14);
    domain::Json parents = parse_json_column(rows.text(15), "[]");
    if (parents.is_array()) {
        for (const auto& parent : parents) {
            if (parent.is_string()) {
                version.parent_version_ids.emplace_back(
                    parent.get<std::string>());
            }
        }
    }
    return version;
}

}  // namespace pwb::catalog::rows
