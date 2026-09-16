#include "pwb/catalog/repository.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <set>
#include <unordered_map>
#include <unordered_set>

namespace pwb::catalog {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

namespace {

Json parse_json_column(const std::string& text, const char* fallback) {
    if (text.empty()) return Json::parse(fallback, nullptr, false);
    Json parsed = Json::parse(text, nullptr, false);
    if (parsed.is_discarded()) return Json::parse(fallback, nullptr, false);
    return parsed;
}

std::string json_column(const Json& value, const char* fallback) {
    if (value.is_null()) return fallback;
    return value.dump();
}

std::optional<std::int64_t> opt_int(const Statement& statement, int column) {
    if (statement.is_null(column)) return std::nullopt;
    return statement.int64(column);
}

std::optional<std::string> opt_text(const Statement& statement, int column) {
    if (statement.is_null(column)) return std::nullopt;
    return statement.text(column);
}

}  // namespace

CatalogRepository::CatalogRepository(std::filesystem::path sqlite_path)
    : sqlite_path_(std::move(sqlite_path)) {}

StoreStatus CatalogRepository::status() const {
    StoreStatus status;
    std::error_code ec;
    if (!std::filesystem::is_regular_file(sqlite_path_, ec)) {
        status.health = StoreHealth::Missing;
        return status;
    }
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) {
        status.health = StoreHealth::Unreadable;
        status.detail = opened.error().message;
        return status;
    }
    Database& db = opened.value();
    // A provably unreadable database (torn/garbage bytes) must classify as
    // Corrupt — a missing sync_state alone only means LEGACY (pre-v5).
    {
        Statement probe = db.prepare("SELECT 1 FROM sqlite_master LIMIT 1");
        if (!probe.is_valid()) {
            status.health = StoreHealth::Corrupt;
            status.detail = "sqlite_master unreadable";
            return status;
        }
    }
    if (!db.table_exists("sync_state")) {
        status.health = StoreHealth::Legacy;
        return status;
    }
    // sync_state must be STRICTLY readable on a healthy store (db.py).
    Statement probe = db.prepare("SELECT value FROM sync_state WHERE key = "
                                 "'index_schema_version'");
    if (!probe.is_valid() || !probe.step()) {
        status.health = StoreHealth::Corrupt;
        status.detail = "sync_state/index_schema_version unreadable";
        return status;
    }
    status.index_schema_version = static_cast<int>(probe.int64(0));
    if (status.index_schema_version < kStoreSchemaVersion) {
        status.health = StoreHealth::Legacy;
        status.detail = "index_schema_version " +
                        std::to_string(status.index_schema_version);
        return status;
    }
    Statement revision = db.prepare(
        "SELECT value FROM sync_state WHERE key = 'catalog_revision'");
    if (revision.is_valid() && revision.step()) {
        status.catalog_revision = static_cast<int>(
            std::strtoll(revision.text(0).c_str(), nullptr, 10));
    }
    status.health = StoreHealth::Canonical;
    return status;
}

Result<CatalogDocument> CatalogRepository::load_document(
    SqliteOpenMode mode) const {
    auto opened = Database::open(sqlite_path_, mode);
    if (!opened.is_ok()) return opened.error();
    Database& db = opened.value();
    if (mode == SqliteOpenMode::Create) {
        std::error_code ec;
        std::filesystem::create_directories(sqlite_path_.parent_path(), ec);
        auto schema_error = db.ensure_schema();
        if (schema_error.code != ErrorCode::Ok) return schema_error;
    }
    if (!db.table_exists("sync_state")) {
        return DataError(ErrorCode::CorruptDatabase,
                         "store has no sync_state table (not a v5 store)");
    }
    return load_document_from(db);
}

Result<CatalogDocument> CatalogRepository::load_document_from(
    Database& db) const {
    CatalogDocument document;
    {
        Statement revision = db.prepare(
            "SELECT value FROM sync_state WHERE key = 'catalog_revision'");
        if (revision.is_valid() && revision.step()) {
            document.catalog_revision = static_cast<int>(
                std::strtoll(revision.text(0).c_str(), nullptr, 10));
        }
    }
    {
        Statement rows =
            db.prepare("SELECT id, name, type, description, "
                       "current_version_id, legacy_resource_id, metadata, "
                       "created_at, updated_at, trashed, trashed_at "
                       "FROM assets");
        while (rows.step()) {
            DataAsset asset;
            asset.id = domain::AssetId(rows.text(0));
            asset.name = rows.text(1);
            asset.type = rows.text(2);
            asset.description = rows.text(3);
            if (!rows.is_null(4)) {
                asset.current_version_id =
                    domain::VersionId(rows.text(4));
            }
            asset.legacy_resource_id = opt_text(rows, 5);
            asset.metadata = parse_json_column(rows.text(6), "{}");
            asset.created_at = rows.text(7);
            asset.updated_at = rows.text(8);
            asset.trashed = rows.int64(9) != 0;
            asset.trashed_at = opt_text(rows, 10);
            document.assets.push_back(std::move(asset));
        }
    }
    std::unordered_map<std::string, std::vector<VersionMember>> members;
    if (db.table_exists("version_members")) {
        Statement rows = db.prepare(
            "SELECT version_id, name, rel_path, member_role, ordinal, "
            "required, sha256, size_bytes FROM version_members");
        while (rows.step()) {
            VersionMember member;
            member.name = rows.text(1);
            member.rel_path = rows.text(2);
            member.member_role = rows.text(3);
            member.ordinal = static_cast<int>(rows.int64(4));
            member.required = rows.int64(5) != 0;
            member.sha256 = opt_text(rows, 6);
            member.size_bytes = opt_int(rows, 7);
            members[rows.text(0)].push_back(std::move(member));
        }
    }
    {
        Statement rows =
            db.prepare("SELECT id, asset_id, version_number, stage, managed,"
                       " path, source_uri, format, size_bytes, sha256,"
                       " run_id, metadata, created_at, trashed, trashed_at,"
                       " parent_ids FROM versions");
        while (rows.step()) {
            DataVersion version;
            version.id = domain::VersionId(rows.text(0));
            version.asset_id = domain::AssetId(rows.text(1));
            version.version_number = static_cast<int>(rows.int64(2));
            if (auto stage = domain::data_stage_from_string(rows.text(3))) {
                version.stage = *stage;
            }
            version.managed = rows.int64(4) != 0;
            version.path = rows.text(5);
            version.source_uri = opt_text(rows, 6);
            version.format = rows.text(7);
            version.size_bytes = opt_int(rows, 8);
            version.sha256 = opt_text(rows, 9);
            if (!rows.is_null(10)) version.run_id = domain::RunId(rows.text(10));
            version.metadata = parse_json_column(rows.text(11), "{}");
            version.created_at = rows.text(12);
            version.trashed = rows.int64(13) != 0;
            version.trashed_at = opt_text(rows, 14);
            Json parents = parse_json_column(rows.text(15), "[]");
            if (parents.is_array()) {
                for (const auto& parent : parents) {
                    if (parent.is_string()) {
                        version.parent_version_ids.emplace_back(
                            parent.get<std::string>());
                    }
                }
            }
            auto it = members.find(version.id.str());
            if (it != members.end()) version.members = it->second;
            document.versions.push_back(std::move(version));
        }
    }
    {
        std::unordered_map<std::string, std::size_t> run_index;
        Statement rows =
            db.prepare("SELECT id, operation, parameters, generator, "
                       "status, model_ref, created_at FROM runs");
        while (rows.step()) {
            DataRun run;
            run.id = domain::RunId(rows.text(0));
            run.operation = rows.text(1);
            run.parameters = parse_json_column(rows.text(2), "{}");
            run.generator = rows.text(3);
            run.status = rows.text(4);
            if (!rows.is_null(5)) {
                run.model_ref = parse_json_column(rows.text(5), "{}");
            } else {
                run.model_ref = std::nullopt;
            }
            run.created_at = rows.text(6);
            run_index[run.id.str()] = document.runs.size();
            document.runs.push_back(std::move(run));
        }
        auto attach = [&](const char* table,
                          bool inputs) {
            Statement link = db.prepare(
                std::string("SELECT run_id, version_id FROM ") + table);
            while (link.step()) {
                const auto it = run_index.find(link.text(0));
                if (it == run_index.end()) continue;
                DataRun& run = document.runs[it->second];
                if (inputs) {
                    run.input_version_ids.emplace_back(link.text(1));
                } else {
                    run.output_version_ids.emplace_back(link.text(1));
                }
            }
        };
        attach("run_inputs", true);
        attach("run_outputs", false);
        if (db.table_exists("run_ports")) {
            Statement ports = db.prepare(
                "SELECT run_id, direction, role, version_id, ordinal, "
                "required, entity_type, entity_id, note FROM run_ports");
            while (ports.step()) {
                const auto it = run_index.find(ports.text(0));
                if (it == run_index.end()) continue;
                RunPort port;
                port.role = ports.text(2);
                port.version_id = domain::VersionId(ports.text(3));
                port.ordinal = static_cast<int>(ports.int64(4));
                port.required = ports.int64(5) != 0;
                port.entity_type = ports.text(6);
                port.entity_id = ports.text(7);
                port.note = ports.text(8);
                DataRun& run = document.runs[it->second];
                if (ports.text(1) == "input") {
                    run.input_ports.push_back(std::move(port));
                } else {
                    run.output_ports.push_back(std::move(port));
                }
            }
        }
    }
    {
        Statement rows =
            db.prepare("SELECT id, name, display_name, metadata FROM tags");
        while (rows.step()) {
            Tag tag;
            tag.id = rows.text(0);
            tag.name = rows.text(1);
            tag.display_name = opt_text(rows, 2);
            tag.metadata = parse_json_column(rows.text(3), "{}");
            document.tags.push_back(std::move(tag));
        }
    }
    {
        Statement rows =
            db.prepare("SELECT asset_id, tag_id FROM asset_tags");
        while (rows.step()) {
            document.asset_tags.emplace_back(rows.text(0), rows.text(1));
        }
    }
    {
        Statement rows =
            db.prepare("SELECT version_id, tag_id FROM version_tags");
        while (rows.step()) {
            document.version_tags.emplace_back(rows.text(0), rows.text(1));
        }
    }
    if (db.table_exists("working_copies")) {
        Statement rows = db.prepare(
            "SELECT working_id, source_version_id, path, state, "
            "display_name, created_at, updated_at, payload_mtime_ns, "
            "source_size_bytes FROM working_copies");
        while (rows.step()) {
            WorkingCopy copy;
            copy.working_id = rows.text(0);
            copy.source_version_id = domain::VersionId(rows.text(1));
            copy.path = rows.text(2);
            copy.state = rows.text(3);
            copy.display_name = rows.text(4);
            copy.created_at = rows.text(5);
            copy.updated_at = rows.text(6);
            copy.payload_mtime_ns = opt_int(rows, 7);
            copy.source_size_bytes = opt_int(rows, 8);
            document.working_copies.push_back(std::move(copy));
        }
    }
    return document;
}

Result<CatalogDocument> CatalogRepository::open_read_write() {
    auto status_result = status();
    if (status_result.health == StoreHealth::Corrupt ||
        status_result.health == StoreHealth::Unreadable) {
        return DataError(ErrorCode::CorruptDatabase,
                         "catalog store unreadable: " + status_result.detail);
    }
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::Create);
    if (!opened.is_ok()) return opened.error();
    db_ = std::move(opened.value());
    std::error_code ec;
    std::filesystem::create_directories(sqlite_path_.parent_path(), ec);
    auto schema_error = db_.ensure_schema();
    if (schema_error.code != ErrorCode::Ok) return schema_error;
    return load_document_from(db_);
}

Result<CatalogDocument> CatalogRepository::open_read_only() const {
    auto status_result = status();
    if (status_result.health == StoreHealth::Corrupt ||
        status_result.health == StoreHealth::Unreadable) {
        return DataError(ErrorCode::CorruptDatabase,
                         "catalog store unreadable: " + status_result.detail);
    }
    if (status_result.health == StoreHealth::Missing) {
        return DataError(ErrorCode::NotFound, "catalog store missing");
    }
    return load_document(SqliteOpenMode::ReadOnly);
}

DataError CatalogRepository::upsert_asset_in_transaction(
    const DataAsset& asset) {
    Statement statement = db_.prepare(
        "INSERT INTO assets (id, name, name_search, type, description, "
        "current_version_id, legacy_resource_id, metadata, created_at, "
        "updated_at, trashed, trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
        " name_search=excluded.name_search, type=excluded.type,"
        " description=excluded.description,"
        " current_version_id=excluded.current_version_id,"
        " legacy_resource_id=excluded.legacy_resource_id,"
        " metadata=excluded.metadata, created_at=excluded.created_at,"
        " updated_at=excluded.updated_at, trashed=excluded.trashed,"
        " trashed_at=excluded.trashed_at");
    statement.bind(1, asset.id.str());
    statement.bind(2, asset.name);
    statement.bind(3, asset.name);  // name_search: NFKC+casefold ≈ identity
    statement.bind(4, asset.type);
    statement.bind(5, asset.description);
    if (asset.current_version_id.has_value()) {
        statement.bind(6, asset.current_version_id->str());
    } else {
        statement.bind_null(6);
    }
    if (asset.legacy_resource_id.has_value()) {
        statement.bind(7, *asset.legacy_resource_id);
    } else {
        statement.bind_null(7);
    }
    statement.bind(8, json_column(asset.metadata, "{}"));
    statement.bind(9, asset.created_at);
    statement.bind(10, asset.updated_at);
    statement.bind(11, static_cast<std::int64_t>(asset.trashed ? 1 : 0));
    if (asset.trashed_at.has_value()) {
        statement.bind(12, *asset.trashed_at);
    } else {
        statement.bind_null(12);
    }
    statement.step_done();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_version_rows(const DataVersion& version) {
    Json parents = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        parents.push_back(parent.str());
    }
    Statement statement = db_.prepare(
        "INSERT INTO versions (id, asset_id, version_number, stage, managed,"
        " path, source_uri, format, size_bytes, sha256, run_id, metadata,"
        " created_at, trashed, trashed_at, parent_ids)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET asset_id=excluded.asset_id,"
        " version_number=excluded.version_number, stage=excluded.stage,"
        " managed=excluded.managed, path=excluded.path,"
        " source_uri=excluded.source_uri, format=excluded.format,"
        " size_bytes=excluded.size_bytes, sha256=excluded.sha256,"
        " run_id=excluded.run_id, metadata=excluded.metadata,"
        " created_at=excluded.created_at, trashed=excluded.trashed,"
        " trashed_at=excluded.trashed_at, parent_ids=excluded.parent_ids");
    statement.bind(1, version.id.str());
    statement.bind(2, version.asset_id.str());
    statement.bind(3, static_cast<std::int64_t>(version.version_number));
    statement.bind(4, std::string(domain::to_string(version.stage)));
    statement.bind(5, static_cast<std::int64_t>(version.managed ? 1 : 0));
    statement.bind(6, version.path);
    if (version.source_uri.has_value()) {
        statement.bind(7, *version.source_uri);
    } else {
        statement.bind_null(7);
    }
    statement.bind(8, version.format);
    if (version.size_bytes.has_value()) {
        statement.bind(9, *version.size_bytes);
    } else {
        statement.bind_null(9);
    }
    if (version.sha256.has_value()) {
        statement.bind(10, *version.sha256);
    } else {
        statement.bind_null(10);
    }
    if (version.run_id.has_value()) {
        statement.bind(11, version.run_id->str());
    } else {
        statement.bind_null(11);
    }
    statement.bind(12, json_column(version.metadata, "{}"));
    statement.bind(13, version.created_at);
    statement.bind(14, static_cast<std::int64_t>(version.trashed ? 1 : 0));
    if (version.trashed_at.has_value()) {
        statement.bind(15, *version.trashed_at);
    } else {
        statement.bind_null(15);
    }
    statement.bind(16, parents.dump());
    statement.step_done();

    // Derived tables owned by the version row (db.py derived-collection
    // writers): lineage from parent_ids, members.
    {
        Statement clear = db_.prepare(
            "DELETE FROM lineage WHERE child_version_id = ?");
        clear.bind(1, version.id.str());
        clear.step_done();
        for (const auto& parent : version.parent_version_ids) {
            Statement row = db_.prepare(
                "INSERT OR IGNORE INTO lineage (parent_version_id, "
                "child_version_id) VALUES (?,?)");
            row.bind(1, parent.str());
            row.bind(2, version.id.str());
            row.step_done();
        }
    }
    if (!version.members.empty()) {
        Statement clear = db_.prepare(
            "DELETE FROM version_members WHERE version_id = ?");
        clear.bind(1, version.id.str());
        clear.step_done();
        for (const auto& member : version.members) {
            Statement row = db_.prepare(
                "INSERT INTO version_members (version_id, name, rel_path,"
                " member_role, ordinal, required, sha256, size_bytes)"
                " VALUES (?,?,?,?,?,?,?,?)");
            row.bind(1, version.id.str());
            row.bind(2, member.name);
            row.bind(3, member.rel_path);
            row.bind(4, member.member_role);
            row.bind(5, static_cast<std::int64_t>(member.ordinal));
            row.bind(6, static_cast<std::int64_t>(member.required ? 1 : 0));
            if (member.sha256.has_value()) {
                row.bind(7, *member.sha256);
            } else {
                row.bind_null(7);
            }
            if (member.size_bytes.has_value()) {
                row.bind(8, *member.size_bytes);
            } else {
                row.bind_null(8);
            }
            row.step_done();
        }
    }
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_run_rows(const DataRun& run) {
    Statement statement = db_.prepare(
        "INSERT INTO runs (id, operation, parameters, generator, status,"
        " model_ref, created_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET operation=excluded.operation,"
        " parameters=excluded.parameters, generator=excluded.generator,"
        " status=excluded.status, model_ref=excluded.model_ref,"
        " created_at=excluded.created_at");
    statement.bind(1, run.id.str());
    statement.bind(2, run.operation);
    statement.bind(3, json_column(run.parameters, "{}"));
    statement.bind(4, run.generator);
    statement.bind(5, run.status);
    if (run.model_ref.has_value()) {
        statement.bind(6, run.model_ref->dump());
    } else {
        statement.bind_null(6);
    }
    statement.bind(7, run.created_at);
    statement.step_done();

    Statement clear_inputs =
        db_.prepare("DELETE FROM run_inputs WHERE run_id = ?");
    clear_inputs.bind(1, run.id.str());
    clear_inputs.step_done();
    for (const auto& input : run.input_version_ids) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_inputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run.id.str());
        row.bind(2, input.str());
        row.step_done();
    }
    Statement clear_outputs =
        db_.prepare("DELETE FROM run_outputs WHERE run_id = ?");
    clear_outputs.bind(1, run.id.str());
    clear_outputs.step_done();
    for (const auto& output : run.output_version_ids) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_outputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run.id.str());
        row.bind(2, output.str());
        row.step_done();
    }
    if (db_.table_exists("run_ports")) {
        Statement clear_ports =
            db_.prepare("DELETE FROM run_ports WHERE run_id = ?");
        clear_ports.bind(1, run.id.str());
        clear_ports.step_done();
        auto write_ports = [&](const std::vector<RunPort>& ports,
                               const char* direction) {
            for (const auto& port : ports) {
                Statement row = db_.prepare(
                    "INSERT OR IGNORE INTO run_ports (run_id, direction,"
                    " role, version_id, ordinal, required, entity_type,"
                    " entity_id, note) VALUES (?,?,?,?,?,?,?,?,?)");
                row.bind(1, run.id.str());
                row.bind(2, direction);
                row.bind(3, port.role);
                row.bind(4, port.version_id.str());
                row.bind(5, static_cast<std::int64_t>(port.ordinal));
                row.bind(6, static_cast<std::int64_t>(port.required ? 1 : 0));
                row.bind(7, port.entity_type);
                row.bind(8, port.entity_id);
                row.bind(9, port.note);
                row.step_done();
            }
        };
        write_ports(run.input_ports, "input");
        write_ports(run.output_ports, "output");
    }
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::bump_revision() {
    Statement statement = db_.prepare(
        "INSERT INTO sync_state (key, value) VALUES ('catalog_revision', '1')"
        " ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS "
        "INTEGER) + 1 AS TEXT)");
    statement.step_done();
    Statement stamp = db_.prepare(
        "INSERT INTO sync_state (key, value) VALUES ('schema_version', '1')"
        " ON CONFLICT(key) DO NOTHING");
    stamp.step_done();
    Statement index_stamp = db_.prepare(
        "INSERT INTO sync_state (key, value) VALUES ('index_schema_version',"
        " '5') ON CONFLICT(key) DO NOTHING");
    index_stamp.step_done();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_asset(const DataAsset& asset) {
    Transaction transaction(db_);
    auto error = upsert_asset_in_transaction(asset);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_version(const DataVersion& version) {
    Transaction transaction(db_);
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_run(const DataRun& run) {
    Transaction transaction(db_);
    auto error = upsert_run_rows(run);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::set_current_version(
    const domain::AssetId& asset_id, const domain::VersionId& version_id,
    const std::string& updated_at) {
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    statement.bind(1, version_id.str());
    statement.bind(2, updated_at);
    statement.bind(3, asset_id.str());
    statement.step_done();
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::insert_working_copy(const WorkingCopy& copy) {
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "INSERT OR REPLACE INTO working_copies (working_id, "
        "source_version_id, path, state, display_name, created_at, "
        "updated_at, payload_mtime_ns, source_size_bytes) "
        "VALUES (?,?,?,?,?,?,?,?,?)");
    statement.bind(1, copy.working_id);
    statement.bind(2, copy.source_version_id.str());
    statement.bind(3, copy.path);
    statement.bind(4, copy.state);
    statement.bind(5, copy.display_name);
    statement.bind(6, copy.created_at);
    statement.bind(7, copy.updated_at);
    if (copy.payload_mtime_ns.has_value()) {
        statement.bind(8, *copy.payload_mtime_ns);
    } else {
        statement.bind_null(8);
    }
    if (copy.source_size_bytes.has_value()) {
        statement.bind(9, *copy.source_size_bytes);
    } else {
        statement.bind_null(9);
    }
    statement.step_done();
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::remove_working_copy(
    const std::string& working_id) {
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "DELETE FROM working_copies WHERE working_id = ?");
    statement.bind(1, working_id);
    statement.step_done();
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::set_working_copy_state(
    const std::string& working_id, const std::string& state) {
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "UPDATE working_copies SET state = ? WHERE working_id = ?");
    statement.bind(1, state);
    statement.bind(2, working_id);
    statement.step_done();
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::commit_version_transaction(
    const DataVersion& version, const domain::AssetId& asset_id,
    const std::optional<domain::RunId>& run_id) {
    Transaction transaction(db_);
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    Statement pointer = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    pointer.bind(1, version.id.str());
    pointer.bind(2, version.created_at);
    pointer.bind(3, asset_id.str());
    pointer.step_done();
    if (run_id.has_value()) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_outputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run_id->str());
        row.bind(2, version.id.str());
        row.step_done();
    }
    bump_revision();
    transaction.commit();
    return DataError(ErrorCode::Ok, "");
}

int CatalogRepository::current_revision() const {
    auto status_result = status();
    return status_result.catalog_revision;
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

std::vector<AuditFinding> audit_catalog(
    const CatalogDocument& document, const std::filesystem::path& project_path,
    const std::vector<WorkspaceBindingRef>& bindings) {
    std::vector<AuditFinding> findings;
    std::unordered_set<std::string> asset_ids;
    for (const auto& asset : document.assets) {
        asset_ids.insert(asset.id.str());
    }
    std::unordered_set<std::string> version_ids;
    for (const auto& version : document.versions) {
        version_ids.insert(version.id.str());
    }

    for (const auto& version : document.versions) {
        if (asset_ids.find(version.asset_id.str()) == asset_ids.end()) {
            findings.push_back({"orphan_version",
                                "version " + version.id.str() +
                                    " references missing asset " +
                                    version.asset_id.str(),
                                Json{{"version_id", version.id.str()},
                                     {"asset_id", version.asset_id.str()}}});
        }
    }
    for (const auto& asset : document.assets) {
        if (asset.current_version_id.has_value() &&
            version_ids.find(asset.current_version_id->str()) ==
                version_ids.end()) {
            findings.push_back(
                {"dangling_current",
                 "asset " + asset.id.str() +
                     " points at missing version " +
                     asset.current_version_id->str(),
                 Json{{"asset_id", asset.id.str()},
                      {"current_version_id",
                       asset.current_version_id->str()}}});
        }
    }
    for (const auto& run : document.runs) {
        for (const auto& input : run.input_version_ids) {
            if (version_ids.find(input.str()) == version_ids.end()) {
                findings.push_back(
                    {"run_missing_input",
                     "run " + run.id.str() + " input " + input.str() +
                         " has no version row",
                     Json{{"run_id", run.id.str()},
                          {"version_id", input.str()}}});
            }
        }
        for (const auto& output : run.output_version_ids) {
            if (version_ids.find(output.str()) == version_ids.end()) {
                findings.push_back(
                    {"run_missing_output",
                     "run " + run.id.str() + " output " + output.str() +
                         " has no version row",
                     Json{{"run_id", run.id.str()},
                          {"version_id", output.str()}}});
            }
        }
        if (run.status == "running") {
            findings.push_back({"run_incomplete",
                                "run " + run.id.str() + " still running",
                                Json{{"run_id", run.id.str()},
                                     {"operation", run.operation}}});
        }
    }
    // Missing payloads for managed, live versions.
    for (const auto& version : document.versions) {
        if (!version.managed || version.trashed || version.path.empty()) {
            continue;
        }
        const std::filesystem::path resolved =
            std::filesystem::path(
                pwb::project::project_dir_for(project_path)) /
            pwb::project::path_from_u8(version.path);
        std::error_code ec;
        if (!std::filesystem::is_regular_file(resolved, ec)) {
            findings.push_back(
                {"missing_payload",
                 "version " + version.id.str() + " payload missing: " +
                     version.path,
                 Json{{"version_id", version.id.str()},
                      {"path", version.path}}});
        }
    }
    // Workspace bindings pointing at absent catalog rows.
    for (const auto& binding : bindings) {
        if (!binding.asset_id.empty() &&
            asset_ids.find(binding.asset_id) == asset_ids.end()) {
            findings.push_back(
                {"binding_unknown_asset",
                 "layer " + binding.layer_id + " binds missing asset " +
                     binding.asset_id,
                 Json{{"layer_id", binding.layer_id},
                      {"asset_id", binding.asset_id}}});
        }
        if (!binding.version_id.empty() &&
            version_ids.find(binding.version_id) == version_ids.end()) {
            findings.push_back(
                {"binding_stale_version",
                 "layer " + binding.layer_id + " pins missing version " +
                     binding.version_id + " (recycled?)",
                 Json{{"layer_id", binding.layer_id},
                      {"version_id", binding.version_id}}});
        }
    }
    // Duplicate current pointers / duplicate version numbers per asset.
    std::unordered_map<std::string, std::set<int>> numbers;
    for (const auto& version : document.versions) {
        auto& seen = numbers[version.asset_id.str()];
        if (seen.count(version.version_number) != 0) {
            findings.push_back(
                {"duplicate_version_number",
                 "asset " + version.asset_id.str() + " has duplicate number " +
                     std::to_string(version.version_number),
                 Json{{"asset_id", version.asset_id.str()},
                      {"version_number", version.version_number}}});
        }
        seen.insert(version.version_number);
    }
    // Working copies against missing sources.
    for (const auto& copy : document.working_copies) {
        if (version_ids.find(copy.source_version_id.str()) ==
            version_ids.end()) {
            findings.push_back(
                {"working_copy_missing_source",
                 "working copy " + copy.working_id +
                     " sources missing version " +
                     copy.source_version_id.str(),
                 Json{{"working_id", copy.working_id}}});
        }
    }
    return findings;
}

}  // namespace pwb::catalog
