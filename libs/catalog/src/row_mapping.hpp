// Canonical SQLite row → model mappers (internal to pwb_catalog; conv-26,
// extended in conv-31b per findings §C-10: run/tag/model/model_version
// decoding joins assets/versions here as the single fact source shared by
// the document loader (repository.cpp), the SQL paging path (paged_sql.cpp)
// and the lazy reads (queries_sql.cpp) — a schema column change lands in
// exactly one place.
//
// Column contracts (the SELECTs must list columns in these orders):
//   assets:  id, name, type, description, current_version_id,
//            legacy_resource_id, metadata, created_at, updated_at,
//            trashed, trashed_at
//   versions: id, asset_id, version_number, stage, managed, path,
//             source_uri, format, size_bytes, sha256, run_id, metadata,
//             created_at, trashed, trashed_at, parent_ids
//   runs:    id, operation, parameters, generator, status, model_ref,
//            created_at (io lists / ports are attached by the caller from
//            the link tables, db.py _run_model_from_row shape)
//   tags:    id, name, display_name, metadata
//   models:  id, model_id, model_name, model_type, capability, provider,
//            status, metadata, created_at, provenance
//   model_versions: id, model_id, model_version, artifact_uri, checksum,
//            input_schema, output_schema, preprocessing_version, runtime,
//            deterministic, demo_only, status, metadata, created_at,
//            provenance
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

// db.py _run_model_from_row base columns; input/output ids and ports are
// attached separately (their table order is the document order).
inline DataRun run_from_row(Statement& rows) {
    DataRun run;
    run.id = domain::RunId(rows.text(0));
    run.operation = rows.text(1);
    run.parameters = parse_json_column(rows.text(2), "{}");
    run.generator = rows.text(3);
    run.status = rows.text(4);
    // db.py (88): `json.loads(...) if row["model_ref"] else None` — both
    // NULL and empty string decode to nullopt.
    if (!rows.is_null(5) && !rows.text(5).empty()) {
        run.model_ref = parse_json_column(rows.text(5), "{}");
    } else {
        run.model_ref = std::nullopt;
    }
    run.created_at = rows.text(6);
    return run;
}

inline Tag tag_from_row(Statement& rows) {
    Tag tag;
    tag.id = rows.text(0);
    tag.name = rows.text(1);
    if (!rows.is_null(2)) tag.display_name = rows.text(2);
    tag.metadata = parse_json_column(rows.text(3), "{}");
    return tag;
}

inline Model model_from_row(Statement& rows) {
    Model model;
    model.id = rows.text(0);
    model.model_id = rows.text(1);
    model.model_name = rows.text(2);
    model.model_type = rows.text(3);
    model.capability = rows.text(4);
    model.provider = rows.text(5);
    model.status = rows.text(6);
    model.metadata = parse_json_column(rows.text(7), "{}");
    model.created_at = rows.text(8);
    model.provenance = parse_json_column(rows.text(9), "{}");
    return model;
}

inline ModelVersion model_version_from_row(Statement& rows) {
    ModelVersion version;
    version.id = rows.text(0);
    version.model_id = rows.text(1);
    version.model_version = rows.text(2);
    version.artifact_uri = rows.text(3);
    if (!rows.is_null(4)) version.checksum = rows.text(4);
    version.input_schema = parse_json_column(rows.text(5), "{}");
    version.output_schema = parse_json_column(rows.text(6), "{}");
    version.preprocessing_version = rows.text(7);
    version.runtime = rows.text(8);
    version.deterministic = rows.int64(9) != 0;
    version.demo_only = rows.int64(10) != 0;
    version.status = rows.text(11);
    version.metadata = parse_json_column(rows.text(12), "{}");
    version.created_at = rows.text(13);
    version.provenance = parse_json_column(rows.text(14), "{}");
    return version;
}

}  // namespace pwb::catalog::rows
