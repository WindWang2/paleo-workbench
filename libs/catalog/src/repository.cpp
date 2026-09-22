#include "posix_shim.hpp"
#include "pwb/catalog/repository.hpp"

#include "row_mapping.hpp"
#include "pwb/catalog/apply_changes.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <random>
#include <set>
#include <sstream>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

#if !defined(_WIN32)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

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

// Manifest row serializers (Python catalog/store.py schema 1; field names
// are the pydantic model's 1:1).
Json manifest_asset(const DataAsset& asset) {
    Json j = Json::object();
    j["id"] = asset.id.str();
    j["name"] = asset.name;
    j["type"] = asset.type;
    j["description"] = asset.description;
    j["current_version_id"] = asset.current_version_id.has_value()
        ? Json(asset.current_version_id->str())
        : Json(nullptr);
    j["legacy_resource_id"] = asset.legacy_resource_id.has_value()
        ? Json(*asset.legacy_resource_id)
        : Json(nullptr);
    j["metadata"] = asset.metadata;
    j["created_at"] = asset.created_at;
    j["updated_at"] = asset.updated_at;
    j["trashed"] = asset.trashed;
    j["trashed_at"] = asset.trashed_at.has_value() ? Json(*asset.trashed_at)
                                                   : Json(nullptr);
    return j;
}

Json manifest_port(const RunPort& port) {
    Json j = Json::object();
    j["role"] = port.role;
    j["version_id"] = port.version_id.str();
    j["ordinal"] = port.ordinal;
    j["required"] = port.required;
    j["entity_type"] = port.entity_type;
    j["entity_id"] = port.entity_id;
    j["note"] = port.note;
    return j;
}

Json manifest_run(const DataRun& run) {
    Json j = Json::object();
    j["id"] = run.id.str();
    j["operation"] = run.operation;
    j["input_version_ids"] = Json::array();
    for (const auto& id : run.input_version_ids) {
        j["input_version_ids"].push_back(id.str());
    }
    j["output_version_ids"] = Json::array();
    for (const auto& id : run.output_version_ids) {
        j["output_version_ids"].push_back(id.str());
    }
    j["input_ports"] = Json::array();
    j["output_ports"] = Json::array();
    for (const auto& port : run.input_ports) {
        j["input_ports"].push_back(manifest_port(port));
    }
    for (const auto& port : run.output_ports) {
        j["output_ports"].push_back(manifest_port(port));
    }
    j["parameters"] = run.parameters;
    j["generator"] = run.generator;
    j["status"] = run.status;
    j["model_ref"] = run.model_ref.has_value() ? *run.model_ref
                                               : Json(nullptr);
    j["created_at"] = run.created_at;
    return j;
}

Json manifest_version(const DataVersion& version) {
    // Key order = the pydantic declaration order (models.py DataVersion), so
    // a compact dump reproduces Python's json.dumps(model_dump()) byte order
    // (conv-31b; export_manifest and save_manifest share this serializer).
    Json j = Json::object();
    j["id"] = version.id.str();
    j["asset_id"] = version.asset_id.str();
    j["version_number"] = version.version_number;
    j["stage"] = std::string(domain::to_string(version.stage));
    j["managed"] = version.managed;
    j["path"] = version.path;
    j["source_uri"] = version.source_uri.has_value() ? Json(*version.source_uri)
                                                     : Json(nullptr);
    j["format"] = version.format;
    j["size_bytes"] = version.size_bytes.has_value()
        ? Json(*version.size_bytes)
        : Json(nullptr);
    j["sha256"] = version.sha256.has_value() ? Json(*version.sha256)
                                             : Json(nullptr);
    j["parent_version_ids"] = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        j["parent_version_ids"].push_back(parent.str());
    }
    j["run_id"] = version.run_id.has_value() ? Json(version.run_id->str())
                                             : Json(nullptr);
    j["metadata"] = version.metadata;
    j["created_at"] = version.created_at;
    j["members"] = Json::array();
    for (const auto& member : version.members) {
        Json m = Json::object();
        m["name"] = member.name;
        m["rel_path"] = member.rel_path;
        m["member_role"] = member.member_role;
        m["ordinal"] = member.ordinal;
        m["required"] = member.required;
        m["sha256"] = member.sha256.has_value() ? Json(*member.sha256)
                                                : Json(nullptr);
        m["size_bytes"] = member.size_bytes.has_value()
            ? Json(*member.size_bytes)
            : Json(nullptr);
        j["members"].push_back(std::move(m));
    }
    j["trashed"] = version.trashed;
    j["trashed_at"] = version.trashed_at.has_value()
        ? Json(*version.trashed_at)
        : Json(nullptr);
    return j;
}

// Raw passthrough for the registry tables (no domain read model yet): the
// manifest must never drop rows this side cannot interpret.
Json passthrough_rows(Database& db, const char* table) {
    Json rows = Json::array();
    if (!db.table_exists(table)) return rows;
    std::vector<std::string> columns;
    std::vector<std::string> json_columns;
    {
        Statement pragma =
            db.prepare(std::string("PRAGMA table_info(") + table + ")");
        while (pragma.step()) {
            const std::string name = pragma.text(1);
            const std::string type = pragma.text(2);
            columns.push_back(name);
            if (type.find("TEXT") != std::string::npos
                && (name == "metadata" || name == "provenance"
                    || name == "input_schema" || name == "output_schema")) {
                json_columns.push_back(name);
            }
        }
    }
    std::string sql = "SELECT ";
    for (std::size_t i = 0; i < columns.size(); ++i) {
        if (i > 0) sql += ", ";
        sql += columns[i];
    }
    sql += std::string(" FROM ") + table + " ORDER BY id";
    Statement rows_statement = db.prepare(sql);
    while (rows_statement.step()) {
        Json row = Json::object();
        for (std::size_t i = 0; i < columns.size(); ++i) {
            const bool is_json = std::find(json_columns.begin(),
                                           json_columns.end(), columns[i])
                != json_columns.end();
            if (is_json) {
                row[columns[i]] = parse_json_column(rows_statement.text(
                    static_cast<int>(i)), "{}");
            } else {
                row[columns[i]] = rows_statement.text(static_cast<int>(i));
            }
        }
        rows.push_back(std::move(row));
    }
    return rows;
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

// name_search fold, aligned with the Python contract
// (normalize_asset_search_name: NFKC + casefold). Full Unicode NFKC needs
// normalization tables this side does not carry yet; the bounded
// implementation here is ASCII case folding, which covers the dominant
// search semantics (case-insensitive ASCII names) and leaves non-ASCII
// text verbatim — identical to Python for scripts without case (CJK) and
// diverging only for non-ASCII cased letters (e.g. Ü). That boundary is
// deliberate and documented; a full NFKC port belongs to the B line.
std::string search_fold(const std::string& name) {
    std::string folded;
    folded.reserve(name.size());
    for (const char c : name) {
        if (c >= 'A' && c <= 'Z') {
            folded.push_back(static_cast<char>(c - 'A' + 'a'));
        } else {
            folded.push_back(c);
        }
    }
    return folded;
}

// ---- conv-31b helpers (db.py / store.py / service.py parity) ---------------

// datetime.now().isoformat(timespec="seconds"): LOCAL time, no timezone
// suffix, second precision. The lease TTL compares these strings lexically
// (gc.hpp default_lease_cutoff reads the same shape), so any precision or
// zone drift silently breaks the cutoff (R2 ⑥-7).
std::string local_iso_seconds(std::time_t time) {
    std::tm local{};
#if !defined(_WIN32)
    localtime_r(&time, &local);
#else
    localtime_s(&local, &time);
#endif
    char buffer[32];
    const std::size_t written =
        std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S", &local);
    return std::string(buffer, written);
}

std::string local_now_iso_seconds() {
    return local_iso_seconds(std::time(nullptr));
}

// random_device hex (B-11: uuid4 parity is shape-only — "wc-" + 12 hex for
// working ids, 32 hex for lease ids).
std::string random_hex(std::size_t characters) {
    std::string out;
    out.reserve(characters + 16);
    std::random_device rd;
    while (out.size() < characters) {
        char buffer[17];
        std::snprintf(buffer, sizeof(buffer), "%016llx",
                      static_cast<unsigned long long>(
                          (static_cast<std::uint64_t>(rd()) << 32) ^ rd()));
        out += buffer;
    }
    out.resize(characters);
    return out;
}

// st_mtime_ns parity (B-16): POSIX st_mtim at full nanosecond ticks — the
// #1183 unchanged-skip and the manifest_mtime_ns accounting both compare
// exact ticks, seconds-grade stat is forbidden. Windows maps the 100ns
// file-time ticks (best-effort, same direction as Python's st_mtime_ns).
std::optional<std::int64_t> disk_mtime_ns(const std::filesystem::path& path) {
    const posix_shim::FileStat st = posix_shim::stat_path(path);
    if (!st.exists) return std::nullopt;
    return st.mtime_ns;
}

// storage.py fsync_dir: best-effort so rename metadata survives a crash;
// a no-op on Windows (storage.py itself returns early there — B-31).
void fsync_dir_best_effort(const std::filesystem::path& directory) {
#if !defined(_WIN32)
    const int fd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) return;
    ::fsync(fd);
    ::close(fd);
#else
    (void)directory;
#endif
}

// store.py save step 3: write + flush + fsync (POSIX; the fsync leg is
// best-effort parity on Windows, B-31).
bool write_file_fsynced(const std::filesystem::path& target,
                        const std::string& payload) {
#if !defined(_WIN32)
    const int fd = ::open(target.c_str(), O_WRONLY | O_CREAT | O_TRUNC,
                          0644);
    if (fd < 0) return false;
    std::size_t written = 0;
    while (written < payload.size()) {
        const ssize_t chunk =
            ::write(fd, payload.data() + written, payload.size() - written);
        if (chunk <= 0) {
            ::close(fd);
            return false;
        }
        written += static_cast<std::size_t>(chunk);
    }
    if (::fsync(fd) != 0) {
        ::close(fd);
        return false;
    }
    ::close(fd);
    return true;
#else
    std::ofstream out(target, std::ios::binary | std::ios::trunc);
    if (!out.good()) return false;
    out.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    out.flush();
    return out.good();
#endif
}

// storage.py safe_unlink (the read-only-attribute dance is Windows NTFS
// specific and unreachable here; missing files are already gone).
void safe_unlink(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::remove(path, ec);
}

// Column contract: working_id, source_version_id, path, state, display_name,
// created_at, updated_at, payload_mtime_ns, source_size_bytes.
WorkingCopy working_copy_from_row(Statement& rows) {
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
    return copy;
}

// Post-step sqlite failure probe (the Statement wrapper swallows step
// errors): anything other than the OK/ROW/DONE family becomes a
// CorruptDatabase carrying the sqlite code, mirroring sqlite.cpp's
// make_error channel.
std::optional<DataError> sqlite_step_error(Database& db, const char* what) {
    const int rc = sqlite3_errcode(db.handle());
    if (rc == SQLITE_OK || rc == SQLITE_ROW || rc == SQLITE_DONE) {
        return std::nullopt;
    }
    const char* text = sqlite3_errmsg(db.handle());
    return DataError(ErrorCode::CorruptDatabase,
                     std::string(what) + ": " +
                         (text != nullptr ? text : "unknown"),
                     Json{{"sqlite_code", rc}});
}

// Fetch a connection for the bookkeeping write/read families: the resident
// writable handle when open, otherwise a short-lived one opened like
// db.py's _connect (READWRITE|CREATE, no schema seeding — the connect-time
// DDL that would auto-create the registry tables is NOT mirrored; every
// real flow opens the canonical store first).
Database* bookkeeping_connection(std::optional<Database>& scratch,
                                  Database& resident,
                                  const std::filesystem::path& path,
                                  SqliteOpenMode mode) {
    if (resident.is_open()) return &resident;
    auto opened = Database::open(path, mode);
    if (!opened.is_ok()) return nullptr;
    scratch = std::move(opened.value());
    return &*scratch;
}

// db.py _MODEL_UPSERT_SQL verbatim (ON CONFLICT(id) DO UPDATE keeps the
// rowid insertion order; INSERT OR REPLACE would float updated rows).
DataError upsert_model_in_transaction(Database& db, const Model& model) {
    Statement statement = db.prepare(
        "INSERT INTO models (id, model_id, model_name, model_type,"
        " capability, provider, status, metadata, created_at, provenance)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
        " model_name=excluded.model_name, model_type=excluded.model_type,"
        " capability=excluded.capability, provider=excluded.provider,"
        " status=excluded.status, metadata=excluded.metadata,"
        " created_at=excluded.created_at, provenance=excluded.provenance");
    statement.bind(1, model.id);
    statement.bind(2, model.model_id);
    statement.bind(3, model.model_name);
    statement.bind(4, model.model_type);
    statement.bind(5, model.capability);
    statement.bind(6, model.provider);
    statement.bind(7, model.status);
    statement.bind(8, json_column(model.metadata, "{}"));
    statement.bind(9, model.created_at);
    statement.bind(10, json_column(model.provenance, "{}"));
    statement.step_done();
    if (auto failure = sqlite_step_error(db, "upsert model")) {
        return *failure;
    }
    return DataError(ErrorCode::Ok, "");
}

// db.py _MODEL_VERSION_UPSERT_SQL verbatim.
DataError upsert_model_version_in_transaction(Database& db,
                                              const ModelVersion& version) {
    Statement statement = db.prepare(
        "INSERT INTO model_versions (id, model_id, model_version,"
        " artifact_uri, checksum, input_schema, output_schema, "
        "preprocessing_version, runtime, deterministic, demo_only, status,"
        " metadata, created_at, provenance)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
        " model_version=excluded.model_version,"
        " artifact_uri=excluded.artifact_uri, checksum=excluded.checksum,"
        " input_schema=excluded.input_schema,"
        " output_schema=excluded.output_schema,"
        " preprocessing_version=excluded.preprocessing_version,"
        " runtime=excluded.runtime, deterministic=excluded.deterministic,"
        " demo_only=excluded.demo_only, status=excluded.status,"
        " metadata=excluded.metadata, created_at=excluded.created_at,"
        " provenance=excluded.provenance");
    statement.bind(1, version.id);
    statement.bind(2, version.model_id);
    statement.bind(3, version.model_version);
    statement.bind(4, version.artifact_uri);
    if (version.checksum.has_value()) {
        statement.bind(5, *version.checksum);
    } else {
        statement.bind_null(5);
    }
    statement.bind(6, json_column(version.input_schema, "{}"));
    statement.bind(7, json_column(version.output_schema, "{}"));
    statement.bind(8, version.preprocessing_version);
    statement.bind(9, version.runtime);
    statement.bind(10, static_cast<std::int64_t>(version.deterministic ? 1 : 0));
    statement.bind(11, static_cast<std::int64_t>(version.demo_only ? 1 : 0));
    statement.bind(12, version.status);
    statement.bind(13, json_column(version.metadata, "{}"));
    statement.bind(14, version.created_at);
    statement.bind(15, json_column(version.provenance, "{}"));
    statement.step_done();
    if (auto failure = sqlite_step_error(db, "upsert model version")) {
        return *failure;
    }
    return DataError(ErrorCode::Ok, "");
}

// ---- manifest parsing (store.py CatalogDocument.model_validate parity) -----
// Strict-typed readers (B-15): absent → keep the pydantic default; present
// but wrong-typed → error (load_manifest maps that to the corrupt branch).
// Unknown keys are ignored, like pydantic's default extra behavior.

bool manifest_field_string(const Json& data, const char* key,
                           std::string& out, bool required,
                           std::string* error) {
    if (!data.contains(key)) {
        if (required) {
            *error = std::string("field '") + key + "' is required";
            return false;
        }
        return true;
    }
    const Json& value = data.at(key);
    if (!value.is_string()) {
        *error = std::string("field '") + key + "' is not a string";
        return false;
    }
    out = value.get<std::string>();
    return true;
}

bool manifest_field_opt_string(const Json& data, const char* key,
                               std::optional<std::string>& out,
                               std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (value.is_null()) {
        out = std::nullopt;
        return true;
    }
    if (!value.is_string()) {
        *error = std::string("field '") + key + "' is not a string";
        return false;
    }
    out = value.get<std::string>();
    return true;
}

bool manifest_field_int(const Json& data, const char* key, long long& out,
                        std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (!value.is_number_integer()) {
        *error = std::string("field '") + key + "' is not an integer";
        return false;
    }
    out = value.get<long long>();
    return true;
}

template <typename T>
bool manifest_field_opt_int(const Json& data, const char* key,
                            std::optional<T>& out, std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (value.is_null()) {
        out = std::nullopt;
        return true;
    }
    if (!value.is_number_integer()) {
        *error = std::string("field '") + key + "' is not an integer";
        return false;
    }
    out = static_cast<T>(value.get<long long>());
    return true;
}

bool manifest_field_bool(const Json& data, const char* key, bool& out,
                         std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (!value.is_boolean()) {
        *error = std::string("field '") + key + "' is not a boolean";
        return false;
    }
    out = value.get<bool>();
    return true;
}

bool manifest_field_object(const Json& data, const char* key, Json& out,
                           std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (!value.is_object()) {
        *error = std::string("field '") + key + "' is not an object";
        return false;
    }
    out = value;
    return true;
}

bool manifest_field_string_array(const Json& data, const char* key,
                                 std::vector<std::string>& out,
                                 std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (!value.is_array()) {
        *error = std::string("field '") + key + "' is not an array";
        return false;
    }
    for (const auto& item : value) {
        if (!item.is_string()) {
            *error = std::string("field '") + key +
                     "' contains a non-string item";
            return false;
        }
        out.push_back(item.get<std::string>());
    }
    return true;
}

template <typename T, typename Parse>
bool manifest_field_entities(const Json& data, const char* key,
                             std::vector<T>& out, const char* entity,
                             Parse parse, std::string* error) {
    if (!data.contains(key)) return true;
    const Json& value = data.at(key);
    if (!value.is_array()) {
        *error = std::string("field '") + key + "' is not an array";
        return false;
    }
    for (const auto& item : value) {
        out.push_back(T{});
        if (!parse(item, out.back(), error)) {
            *error = std::string(key) + "[" +
                     std::to_string(out.size() - 1) + "]: " + *error;
            out.pop_back();
            return false;
        }
    }
    (void)entity;
    return true;
}

bool manifest_parse_member(const Json& data, VersionMember& member,
                           std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    long long ordinal = member.ordinal;
    if (!manifest_field_string(data, "name", member.name, true, error) ||
        !manifest_field_string(data, "rel_path", member.rel_path, true,
                               error) ||
        !manifest_field_string(data, "member_role", member.member_role,
                               false, error) ||
        !manifest_field_int(data, "ordinal", ordinal, error) ||
        !manifest_field_bool(data, "required", member.required, error) ||
        !manifest_field_opt_string(data, "sha256", member.sha256, error) ||
        !manifest_field_opt_int(data, "size_bytes", member.size_bytes,
                                error)) {
        return false;
    }
    member.ordinal = static_cast<int>(ordinal);
    return true;
}

bool manifest_parse_port(const Json& data, RunPort& port,
                         std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    long long ordinal = port.ordinal;
    std::string version_id;
    if (!manifest_field_string(data, "role", port.role, true, error) ||
        !manifest_field_string(data, "version_id", version_id, true,
                               error) ||
        !manifest_field_int(data, "ordinal", ordinal, error) ||
        !manifest_field_bool(data, "required", port.required, error) ||
        !manifest_field_string(data, "entity_type", port.entity_type,
                               false, error) ||
        !manifest_field_string(data, "entity_id", port.entity_id, false,
                               error) ||
        !manifest_field_string(data, "note", port.note, false, error)) {
        return false;
    }
    port.version_id = domain::VersionId(version_id);
    port.ordinal = static_cast<int>(ordinal);
    return true;
}

bool manifest_parse_asset(const Json& data, DataAsset& asset,
                          std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    std::string id;
    std::optional<std::string> current_version_id;
    if (!manifest_field_string(data, "name", asset.name, true, error) ||
        !manifest_field_string(data, "id", id, false, error) ||
        !manifest_field_string(data, "type", asset.type, false, error) ||
        !manifest_field_string(data, "description", asset.description,
                               false, error) ||
        !manifest_field_opt_string(data, "current_version_id",
                                   current_version_id, error) ||
        !manifest_field_opt_string(data, "legacy_resource_id",
                                   asset.legacy_resource_id, error) ||
        !manifest_field_object(data, "metadata", asset.metadata, error) ||
        !manifest_field_string(data, "created_at", asset.created_at,
                               false, error) ||
        !manifest_field_string(data, "updated_at", asset.updated_at,
                               false, error) ||
        !manifest_field_bool(data, "trashed", asset.trashed, error) ||
        !manifest_field_opt_string(data, "trashed_at", asset.trashed_at,
                                   error)) {
        return false;
    }
    asset.id = domain::AssetId(id);
    if (current_version_id.has_value()) {
        asset.current_version_id = domain::VersionId(*current_version_id);
    }
    return true;
}

bool manifest_parse_version(const Json& data, DataVersion& version,
                            std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    long long number = version.version_number;
    std::string id;
    std::string asset_id;
    std::optional<std::string> run_id;
    std::vector<std::string> parents;
    if (!manifest_field_string(data, "asset_id", asset_id, true, error) ||
        !manifest_field_string(data, "id", id, false, error) ||
        !manifest_field_int(data, "version_number", number, error)) {
        return false;
    }
    if (!data.contains("stage")) {
        *error = "field 'stage' is required";
        return false;
    }
    const Json& stage = data.at("stage");
    if (!stage.is_string()) {
        *error = "field 'stage' is not a string";
        return false;
    }
    const std::string stage_text = stage.get<std::string>();
    if (auto parsed = domain::data_stage_from_string(stage_text)) {
        version.stage = *parsed;
    } else {
        *error = "field 'stage' is not a valid DataStage";
        return false;
    }
    if (!manifest_field_bool(data, "managed", version.managed, error) ||
        !manifest_field_string(data, "path", version.path, false, error) ||
        !manifest_field_opt_string(data, "source_uri", version.source_uri,
                                   error) ||
        !manifest_field_string(data, "format", version.format, false,
                               error) ||
        !manifest_field_opt_int(data, "size_bytes", version.size_bytes,
                                error) ||
        !manifest_field_opt_string(data, "sha256", version.sha256,
                                   error) ||
        !manifest_field_string_array(data, "parent_version_ids", parents,
                                     error) ||
        !manifest_field_opt_string(data, "run_id", run_id, error) ||
        !manifest_field_object(data, "metadata", version.metadata,
                               error) ||
        !manifest_field_string(data, "created_at", version.created_at,
                               false, error) ||
        !manifest_field_entities(data, "members", version.members,
                                 "member", manifest_parse_member, error) ||
        !manifest_field_bool(data, "trashed", version.trashed, error) ||
        !manifest_field_opt_string(data, "trashed_at", version.trashed_at,
                                   error)) {
        return false;
    }
    version.id = domain::VersionId(id);
    version.asset_id = domain::AssetId(asset_id);
    version.version_number = static_cast<int>(number);
    if (run_id.has_value()) version.run_id = domain::RunId(*run_id);
    for (const auto& parent : parents) {
        version.parent_version_ids.emplace_back(parent);
    }
    return true;
}

bool manifest_parse_run(const Json& data, DataRun& run, std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    std::vector<std::string> inputs;
    std::vector<std::string> outputs;
    std::string id;
    const bool has_model_ref = data.contains("model_ref") &&
                               !data.at("model_ref").is_null();
    if (!manifest_field_string(data, "operation", run.operation, true,
                               error) ||
        !manifest_field_string(data, "id", id, false, error) ||
        !manifest_field_string_array(data, "input_version_ids", inputs,
                                     error) ||
        !manifest_field_string_array(data, "output_version_ids", outputs,
                                     error) ||
        !manifest_field_entities(data, "input_ports", run.input_ports,
                                 "port", manifest_parse_port, error) ||
        !manifest_field_entities(data, "output_ports", run.output_ports,
                                 "port", manifest_parse_port, error) ||
        !manifest_field_object(data, "parameters", run.parameters,
                               error) ||
        !manifest_field_string(data, "generator", run.generator, false,
                               error) ||
        !manifest_field_string(data, "status", run.status, false,
                               error) ||
        !manifest_field_string(data, "created_at", run.created_at,
                               false, error)) {
        return false;
    }
    if (has_model_ref) {
        if (!data.at("model_ref").is_object()) {
            *error = "field 'model_ref' is not an object";
            return false;
        }
        run.model_ref = data.at("model_ref");
    }
    run.id = domain::RunId(id);
    for (const auto& input : inputs) {
        run.input_version_ids.emplace_back(input);
    }
    for (const auto& output : outputs) {
        run.output_version_ids.emplace_back(output);
    }
    return true;
}

bool manifest_parse_tag(const Json& data, Tag& tag, std::string* error) {
    if (!data.is_object()) {
        *error = "entry is not an object";
        return false;
    }
    return manifest_field_string(data, "name", tag.name, true, error) &&
           manifest_field_string(data, "id", tag.id, false, error) &&
           manifest_field_opt_string(data, "display_name",
                                     tag.display_name, error) &&
           manifest_field_object(data, "metadata", tag.metadata, error);
}

// store.py json.loads + CatalogDocument.model_validate, folded into one
// strict parse (B-15): any missing-required/wrong-typed field reports the
// reason and load_manifest routes it to the corrupt branch.
Result<CatalogDocument> parse_manifest_document(const Json& root) {
    if (!root.is_object()) {
        return DataError(ErrorCode::InvalidArgument,
                         "document is not a JSON object");
    }
    CatalogDocument document;
    std::string error;
    long long schema_version = document.schema_version;
    long long revision = document.catalog_revision;
    if (!manifest_field_int(root, "schema_version", schema_version,
                            &error) ||
        !manifest_field_int(root, "catalog_revision", revision, &error) ||
        !manifest_field_entities(root, "assets", document.assets, "asset",
                                 manifest_parse_asset, &error) ||
        !manifest_field_entities(root, "versions", document.versions,
                                 "version", manifest_parse_version,
                                 &error) ||
        !manifest_field_entities(root, "runs", document.runs, "run",
                                 manifest_parse_run, &error) ||
        !manifest_field_entities(root, "tags", document.tags, "tag",
                                 manifest_parse_tag, &error)) {
        return DataError(ErrorCode::InvalidArgument, error);
    }
    document.schema_version = static_cast<int>(schema_version);
    document.catalog_revision = static_cast<int>(revision);
    if (root.contains("models")) {
        if (!root.at("models").is_array()) {
            return DataError(ErrorCode::InvalidArgument,
                             "field 'models' is not an array");
        }
        for (const auto& item : root.at("models")) {
            auto model = Model::from_dict(item);
            if (!model.is_ok()) return model.error();
            document.models.push_back(std::move(model.value()));
        }
    }
    if (root.contains("model_versions")) {
        if (!root.at("model_versions").is_array()) {
            return DataError(ErrorCode::InvalidArgument,
                             "field 'model_versions' is not an array");
        }
        for (const auto& item : root.at("model_versions")) {
            auto version = ModelVersion::from_dict(item);
            if (!version.is_ok()) return version.error();
            document.model_versions.push_back(std::move(version.value()));
        }
    }
    auto parse_map = [&root, &error](const char* key,
                                     std::vector<std::pair<std::string,
                                         std::string>>& out) -> bool {
        if (!root.contains(key)) return true;
        const Json& value = root.at(key);
        if (!value.is_object()) {
            error = std::string("field '") + key + "' is not an object";
            return false;
        }
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (!it.value().is_array()) {
                error = std::string("field '") + key +
                        "' has a non-array value";
                return false;
            }
            for (const auto& tag : it.value()) {
                if (!tag.is_string()) {
                    error = std::string("field '") + key +
                            "' has a non-string tag id";
                    return false;
                }
                out.emplace_back(it.key(), tag.get<std::string>());
            }
        }
        return true;
    };
    if (!parse_map("asset_tags", document.asset_tags) ||
        !parse_map("version_tags", document.version_tags)) {
        return DataError(ErrorCode::InvalidArgument, error);
    }
    return document;
}

// store.py path.read_text + json.loads: the error text feeds the
// parenthesized detail of the L2/L4 skeletons (parser-specific, B-14 — the
// oracle masks it; the skeleton is the byte-identical part).
Result<Json> read_manifest_json(const std::filesystem::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream.good()) {
        return DataError(ErrorCode::IoError,
                         "cannot read file: " + file.generic_string());
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const std::string text = buffer.str();
    Json parsed = Json::parse(text, nullptr, false);
    if (parsed.is_discarded()) {
        return DataError(ErrorCode::CorruptJson, "invalid JSON document");
    }
    return parsed;
}

// CatalogDocument.model_dump: the 10-key portable manifest, key order =
// pydantic declaration order (ordered_json round-trips it; models/model_
// versions go through the typed to_dict codecs).
Json manifest_document_json(const CatalogDocument& document) {
    Json manifest = Json::object();
    manifest["schema_version"] = document.schema_version;
    manifest["catalog_revision"] = document.catalog_revision;
    manifest["assets"] = Json::array();
    for (const auto& asset : document.assets) {
        manifest["assets"].push_back(manifest_asset(asset));
    }
    manifest["versions"] = Json::array();
    for (const auto& version : document.versions) {
        manifest["versions"].push_back(manifest_version(version));
    }
    manifest["runs"] = Json::array();
    for (const auto& run : document.runs) {
        manifest["runs"].push_back(manifest_run(run));
    }
    manifest["tags"] = Json::array();
    for (const auto& tag : document.tags) {
        Json j = Json::object();
        j["id"] = tag.id;
        j["name"] = tag.name;
        j["display_name"] = tag.display_name.has_value()
            ? Json(*tag.display_name)
            : Json(nullptr);
        j["metadata"] = tag.metadata;
        manifest["tags"].push_back(std::move(j));
    }
    manifest["models"] = Json::array();
    for (const auto& model : document.models) {
        manifest["models"].push_back(model.to_dict());
    }
    manifest["model_versions"] = Json::array();
    for (const auto& version : document.model_versions) {
        manifest["model_versions"].push_back(version.to_dict());
    }
    manifest["asset_tags"] = Json::object();
    for (const auto& [asset_id, tag_id] : document.asset_tags) {
        manifest["asset_tags"][asset_id].push_back(tag_id);
    }
    manifest["version_tags"] = Json::object();
    for (const auto& [version_id, tag_id] : document.version_tags) {
        manifest["version_tags"][version_id].push_back(tag_id);
    }
    return manifest;
}

// storage.py ensure_catalog_layout: the artifacts-root stage/aux
// directories. save_manifest only receives the manifest path, so the root
// is derived for the standard `<name>.artifacts/metadata` layout; foreign
// locations get just the manifest's own directory.
void ensure_manifest_layout(const std::filesystem::path& manifest_path) {
    std::error_code ec;
    std::filesystem::create_directories(manifest_path.parent_path(), ec);
    const std::filesystem::path metadata = manifest_path.parent_path();
    if (metadata.filename() != "metadata") return;
    const std::filesystem::path root = metadata.parent_path();
    const std::string name = root.filename().string();
    constexpr std::string_view suffix = ".artifacts";
    if (name.size() < suffix.size() ||
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) !=
            0) {
        return;
    }
    for (const char* stage : kStageDirs) {
        std::filesystem::create_directories(root / stage, ec);
    }
    for (const char* extra : {"working", "metadata", "trash"}) {
        std::filesystem::create_directories(root / extra, ec);
    }
}

}  // namespace

CatalogRepository::CatalogRepository(std::filesystem::path sqlite_path)
    : sqlite_path_(std::move(sqlite_path)) {}

CatalogRepository::CatalogRepository(CatalogRepository&& other) {
    const std::lock_guard<std::recursive_mutex> lock(other.mutex_);
    sqlite_path_ = std::move(other.sqlite_path_);
    db_ = std::move(other.db_);
}

CatalogRepository& CatalogRepository::operator=(CatalogRepository&& other) {
    if (this != &other) {
        const std::scoped_lock lock(mutex_, other.mutex_);
        sqlite_path_ = std::move(other.sqlite_path_);
        db_ = std::move(other.db_);
    }
    return *this;
}

StoreStatus CatalogRepository::status() const {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
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
            document.assets.push_back(rows::asset_from_row(rows));
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
            DataVersion version = rows::version_from_row(rows);
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
            DataRun run = rows::run_from_row(rows);
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
                // db.py _attach_run_ports (161): only "output" goes to the
                // output bucket; any other direction value lands in input.
                if (ports.text(1) == "output") {
                    run.output_ports.push_back(std::move(port));
                } else {
                    run.input_ports.push_back(std::move(port));
                }
            }
        }
    }
    {
        Statement rows =
            db.prepare("SELECT id, name, display_name, metadata FROM tags");
        while (rows.step()) {
            document.tags.push_back(rows::tag_from_row(rows));
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
            document.working_copies.push_back(working_copy_from_row(rows));
        }
    }
    // Model registry (conv-31b): document order = rowid order (db.py 1686/
    // 1706), the invariant _ordered() and list_models rely on (R7 ⑥-1).
    if (db.table_exists("models")) {
        Statement rows = db.prepare(
            "SELECT id, model_id, model_name, model_type, capability, "
            "provider, status, metadata, created_at, provenance"
            " FROM models ORDER BY rowid");
        while (rows.step()) {
            document.models.push_back(rows::model_from_row(rows));
        }
    }
    if (db.table_exists("model_versions")) {
        Statement rows = db.prepare(
            "SELECT id, model_id, model_version, artifact_uri, checksum, "
            "input_schema, output_schema, preprocessing_version, runtime, "
            "deterministic, demo_only, status, metadata, created_at, "
            "provenance FROM model_versions ORDER BY rowid");
        while (rows.step()) {
            document.model_versions.push_back(
                rows::model_version_from_row(rows));
        }
    }
    if (db.table_exists("lineage")) {
        Statement rows = db.prepare(
            "SELECT parent_version_id, child_version_id FROM lineage");
        while (rows.step()) {
            LineageEdge edge;
            edge.parent_version_id = rows.text(0);
            edge.child_version_id = rows.text(1);
            document.lineage.push_back(std::move(edge));
        }
    }
    if (db.table_exists("staging_leases")) {
        Statement rows = db.prepare(
            "SELECT lease_id, target, kind, acquired_at, heartbeat_at "
            "FROM staging_leases");
        while (rows.step()) {
            StagingLease lease;
            lease.lease_id = rows.text(0);
            lease.target = rows.text(1);
            lease.kind = rows.text(2);
            lease.acquired_at = rows.text(3);
            lease.heartbeat_at = rows.text(4);
            document.staging_leases.push_back(std::move(lease));
        }
    }
    return document;
}

DataError CatalogRepository::export_manifest(
    const std::filesystem::path& manifest_path) const {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return opened.error();
    Database db = std::move(opened.value());
    auto loaded = load_document_from(db);
    if (!loaded.is_ok()) return loaded.error();
    CatalogDocument document = std::move(loaded.value());

    Json manifest = Json::object();
    manifest["schema_version"] = kCatalogSchemaVersion;
    manifest["catalog_revision"] = document.catalog_revision;
    manifest["assets"] = Json::array();
    for (const auto& asset : document.assets) {
        manifest["assets"].push_back(manifest_asset(asset));
    }
    manifest["versions"] = Json::array();
    for (const auto& version : document.versions) {
        manifest["versions"].push_back(manifest_version(version));
    }
    manifest["runs"] = Json::array();
    for (const auto& run : document.runs) {
        manifest["runs"].push_back(manifest_run(run));
    }
    manifest["tags"] = Json::array();
    for (const auto& tag : document.tags) {
        Json j = Json::object();
        j["id"] = tag.id;
        j["name"] = tag.name;
        j["display_name"] = tag.display_name.has_value()
            ? Json(*tag.display_name)
            : Json(nullptr);
        j["metadata"] = tag.metadata;
        manifest["tags"].push_back(std::move(j));
    }
    manifest["asset_tags"] = Json::object();
    for (const auto& [asset_id, tag_id] : document.asset_tags) {
        manifest["asset_tags"][asset_id].push_back(tag_id);
    }
    manifest["version_tags"] = Json::object();
    for (const auto& [version_id, tag_id] : document.version_tags) {
        manifest["version_tags"][version_id].push_back(tag_id);
    }
    manifest["models"] = passthrough_rows(db, "models");
    manifest["model_versions"] = passthrough_rows(db, "model_versions");

    // Atomic write with the previous revision kept as .bak (store.py save
    // pattern): existing manifest -> .bak, tmp -> manifest.
    std::error_code ec;
    std::filesystem::create_directories(manifest_path.parent_path(), ec);
    const std::string text = manifest.dump(2);
    const std::filesystem::path tmp =
        manifest_path.parent_path()
        / ("." + manifest_path.filename().generic_string() + ".tmp");
    const std::filesystem::path bak =
        manifest_path.parent_path()
        / (manifest_path.filename().generic_string() + ".bak");
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out.good()) {
            return DataError(ErrorCode::IoError,
                             "manifest temp file unwritable");
        }
        out.write(text.data(), static_cast<std::streamsize>(text.size()));
        out.flush();
        if (!out.good()) {
            std::filesystem::remove(tmp, ec);
            return DataError(ErrorCode::IoError, "manifest temp write failed");
        }
    }
    if (std::filesystem::exists(manifest_path, ec)) {
        std::filesystem::rename(manifest_path, bak, ec);
        if (ec) {
            std::filesystem::remove(tmp, ec);
            return DataError(ErrorCode::IoError,
                             "manifest .bak rotation failed: " + ec.message());
        }
    }
    std::filesystem::rename(tmp, manifest_path, ec);
    if (ec) {
        return DataError(ErrorCode::IoError,
                         "manifest rename failed: " + ec.message());
    }
    return DataError(ErrorCode::Ok, "");
}

void CatalogRepository::close() {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    db_.close();
}

Result<CatalogDocument> CatalogRepository::open_read_write() {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    auto status_result = status();
    if (status_result.health == StoreHealth::Corrupt ||
        status_result.health == StoreHealth::Unreadable) {
        return DataError(ErrorCode::CorruptDatabase,
                         "catalog store unreadable: " + status_result.detail);
    }
    // Parents first: sqlite cannot create the metadata/ directory itself,
    // so a fresh project (no artifacts tree yet) must have it staged
    // before the Create open (conv-26 fix; previously only worked when the
    // caller had pre-built the layout).
    {
        std::error_code ec;
        std::filesystem::create_directories(sqlite_path_.parent_path(), ec);
    }
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::Create);
    if (!opened.is_ok()) return opened.error();
    db_ = std::move(opened.value());
    auto schema_error = db_.ensure_schema();
    if (schema_error.code != ErrorCode::Ok) return schema_error;
    // A freshly created store has no sync_state rows yet — the status
    // probe (and therefore every subsequent open) would refuse it. Seed
    // idempotently so create-then-reopen works. CONV-31b Wave3 fix: ALL
    // three keys seed with ON CONFLICT DO NOTHING — the previous call to
    // bump_revision() here INCREMENTED an existing catalog_revision on
    // every reopen (contradicting this very comment, db.py _connect —
    // which touches only indexes/tables — and the #411 CAS baseline: a
    // reopen bumped the store past the document and made the next save
    // stale).
    {
        Statement seed = db_.prepare(
            "INSERT INTO sync_state (key, value) VALUES"
            " ('catalog_revision', '1') ON CONFLICT(key) DO NOTHING");
        seed.step_done();
        if (auto failure = sqlite_step_error(db_, "open_read_write")) {
            return *failure;
        }
        Statement stamp = db_.prepare(
            "INSERT INTO sync_state (key, value) VALUES"
            " ('schema_version', '1') ON CONFLICT(key) DO NOTHING");
        stamp.step_done();
        if (auto failure = sqlite_step_error(db_, "open_read_write")) {
            return *failure;
        }
        Statement index_stamp = db_.prepare(
            "INSERT INTO sync_state (key, value) VALUES"
            " ('index_schema_version', '5') ON CONFLICT(key) DO NOTHING");
        index_stamp.step_done();
        if (auto failure = sqlite_step_error(db_, "open_read_write")) {
            return *failure;
        }
    }
    return load_document_from(db_);
}

Result<CatalogDocument> CatalogRepository::open_read_only() const {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
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
    statement.bind(3, search_fold(asset.name));  // see search_fold()
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
    if (auto failure = sqlite_step_error(db_, "upsert_asset_in_transaction")) {
        return *failure;
    }
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
    if (auto failure = sqlite_step_error(db_, "upsert_version_rows")) {
        return *failure;
    }

    // Derived tables owned by the version row (db.py derived-collection
    // writers): lineage from parent_ids, members.
    {
        Statement clear = db_.prepare(
            "DELETE FROM lineage WHERE child_version_id = ?");
        clear.bind(1, version.id.str());
        clear.step_done();
        if (auto failure = sqlite_step_error(db_, "upsert_version_rows")) {
            return *failure;
        }
        for (const auto& parent : version.parent_version_ids) {
            Statement row = db_.prepare(
                "INSERT OR IGNORE INTO lineage (parent_version_id, "
                "child_version_id) VALUES (?,?)");
            row.bind(1, parent.str());
            row.bind(2, version.id.str());
            row.step_done();
            if (auto failure = sqlite_step_error(db_, "upsert_version_rows")) {
                return *failure;
            }
        }
    }
    {
        // Unconditional clear (review C2): a version re-saved with members
        // emptied must drop its old rows — the gated DELETE resurrected
        // removed members on the next load (apply_changes.cpp already
        // clears unconditionally).
        Statement clear = db_.prepare(
            "DELETE FROM version_members WHERE version_id = ?");
        clear.bind(1, version.id.str());
        clear.step_done();
        if (auto failure = sqlite_step_error(db_, "upsert_version_rows")) {
            return *failure;
        }
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
            if (auto failure = sqlite_step_error(db_, "upsert_version_rows")) {
                return *failure;
            }
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
    if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
        return *failure;
    }

    Statement clear_inputs =
        db_.prepare("DELETE FROM run_inputs WHERE run_id = ?");
    clear_inputs.bind(1, run.id.str());
    clear_inputs.step_done();
    if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
        return *failure;
    }
    for (const auto& input : run.input_version_ids) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_inputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run.id.str());
        row.bind(2, input.str());
        row.step_done();
        if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
            return *failure;
        }
    }
    Statement clear_outputs =
        db_.prepare("DELETE FROM run_outputs WHERE run_id = ?");
    clear_outputs.bind(1, run.id.str());
    clear_outputs.step_done();
    if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
        return *failure;
    }
    for (const auto& output : run.output_version_ids) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_outputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run.id.str());
        row.bind(2, output.str());
        row.step_done();
        if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
            return *failure;
        }
    }
    if (db_.table_exists("run_ports")) {
        Statement clear_ports =
            db_.prepare("DELETE FROM run_ports WHERE run_id = ?");
        clear_ports.bind(1, run.id.str());
        clear_ports.step_done();
        if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
            return *failure;
        }
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
                if (auto failure = sqlite_step_error(db_, "upsert_run_rows")) {
                    // Void lambda context: early return only — a value
                    // return would change the deduced lambda type and make
                    // the normal loop fall-through UB (found by
                    // data.consumer_loop segfault).
                    std::fprintf(stderr,
                                 "pwb-catalog: run port write failed: %s\n",
                                 failure->message.c_str());
                    return;
                }
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
    if (auto failure = sqlite_step_error(db_, "bump_revision")) {
        return *failure;
    }
    Statement stamp = db_.prepare(
        "INSERT INTO sync_state (key, value) VALUES ('schema_version', '1')"
        " ON CONFLICT(key) DO NOTHING");
    stamp.step_done();
    if (auto failure = sqlite_step_error(db_, "bump_revision")) {
        return *failure;
    }
    Statement index_stamp = db_.prepare(
        "INSERT INTO sync_state (key, value) VALUES ('index_schema_version',"
        " '5') ON CONFLICT(key) DO NOTHING");
    index_stamp.step_done();
    if (auto failure = sqlite_step_error(db_, "bump_revision")) {
        return *failure;
    }
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_asset(const DataAsset& asset) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    auto error = upsert_asset_in_transaction(asset);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_version(const DataVersion& version) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_run(const DataRun& run) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    auto error = upsert_run_rows(run);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::set_current_version(
    const domain::AssetId& asset_id, const domain::VersionId& version_id,
    const std::string& updated_at) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    statement.bind(1, version_id.str());
    statement.bind(2, updated_at);
    statement.bind(3, asset_id.str());
    statement.step_done();
    if (auto failure = sqlite_step_error(db_, "set_current_version")) {
        return *failure;
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::insert_working_copy(const WorkingCopy& copy) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    // conv-31b (R2 fix ② + ③): a BARE insert — Python's register path
    // never replaces, a UNIQUE path conflict surfaces as an error (the
    // composition layer swallows it; service.py:2351 parity) — and the
    // registry writes never touch sync_state, so catalog_revision stays
    // put (a bookkeeping bump would poison the #411/#1220 CAS baseline
    // and flip is_fresh false on every checkout).
    Transaction transaction(db_);
    {
        Statement existing =
            db_.prepare("SELECT 1 FROM working_copies WHERE path = ?");
        existing.bind(1, copy.path);
        if (existing.is_valid() && existing.step()) {
            return DataError(ErrorCode::DuplicateOperation,
                             "UNIQUE constraint failed: working_copies.path",
                             Json{{"working_copy_path", copy.path}});
        }
    }
    Statement statement = db_.prepare(
        "INSERT INTO working_copies (working_id, "
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
    if (auto failure = sqlite_step_error(db_, "insert working copy")) {
        return *failure;
    }
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::remove_working_copy(
    const std::string& working_id) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    // conv-31b (R2 fix ③): no revision bump — db.py's working-copy writes
    // never touch sync_state.
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "DELETE FROM working_copies WHERE working_id = ?");
    statement.bind(1, working_id);
    statement.step_done();
    if (auto failure = sqlite_step_error(db_, "remove_working_copy")) {
        return *failure;
    }
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::set_working_copy_state(
    const std::string& working_id, const std::string& state) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    // conv-31b (R2 fix ② + ③): update_working_copy_state ALWAYS refreshes
    // updated_at (db.py:1402) and never bumps the revision.
    Transaction transaction(db_);
    Statement statement = db_.prepare(
        "UPDATE working_copies SET state = ?, updated_at = ? "
        "WHERE working_id = ?");
    statement.bind(1, state);
    statement.bind(2, local_now_iso_seconds());
    statement.bind(3, working_id);
    statement.step_done();
    if (auto failure = sqlite_step_error(db_, "set_working_copy_state")) {
        return *failure;
    }
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::commit_version_transaction(
    const DataVersion& version, const domain::AssetId& asset_id,
    const std::optional<domain::RunId>& run_id) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
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
    if (auto failure = sqlite_step_error(db_, "commit_version_transaction")) {
        return *failure;
    }
    if (run_id.has_value()) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_outputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run_id->str());
        row.bind(2, version.id.str());
        row.step_done();
        if (auto failure = sqlite_step_error(db_, "commit_version_transaction")) {
            return *failure;
        }
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::publish_result_transaction(
    const std::optional<DataAsset>& new_asset, const DataVersion& version,
    const domain::RunId& run_id) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    if (new_asset.has_value()) {
        auto error = upsert_asset_in_transaction(*new_asset);
        if (error.code != ErrorCode::Ok) return error;
    }
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    Statement pointer = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    pointer.bind(1, version.id.str());
    pointer.bind(2, version.created_at);
    pointer.bind(3, version.asset_id.str());
    pointer.step_done();
    if (auto failure = sqlite_step_error(db_, "publish_result_transaction")) {
        return *failure;
    }
    Statement row = db_.prepare(
        "INSERT OR IGNORE INTO run_outputs (run_id, version_id) VALUES (?,?)");
    row.bind(1, run_id.str());
    row.bind(2, version.id.str());
    row.step_done();
    if (auto failure = sqlite_step_error(db_, "publish_result_transaction")) {
        return *failure;
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::import_raw_transaction(const DataAsset& asset,
                                                    const DataVersion& version) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    auto error = upsert_asset_in_transaction(asset);
    if (error.code != ErrorCode::Ok) return error;
    error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    Statement pointer = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    pointer.bind(1, version.id.str());
    pointer.bind(2, version.created_at);
    pointer.bind(3, version.asset_id.str());
    pointer.step_done();
    if (auto failure = sqlite_step_error(db_, "import_raw_transaction")) {
        return *failure;
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

int CatalogRepository::rebase_artifact_paths() {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    // The staged catalog belongs to the target before its project JSON
    // lands (service.py rebase_artifact_paths): an interruption after the
    // JSON replace must never leave a valid target project pointing at
    // the old artifact-directory name.
    auto status_result = status();
    if (status_result.health == StoreHealth::Corrupt ||
        status_result.health == StoreHealth::Unreadable) {
        return -1;
    }
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadWrite);
    if (!opened.is_ok()) return -1;
    db_ = std::move(opened.value());
    auto document = load_document_from(db_);
    if (!document.is_ok()) return -1;
    const std::string current =
        sqlite_path_.parent_path().parent_path().filename().string();
    auto rewrite = [&current](const std::string& raw,
                              std::string* out) -> bool {
        if (raw.empty()) return false;
        const std::string posix =
            std::filesystem::path(raw).generic_string();
        const std::size_t slash = posix.find('/');
        if (slash == std::string::npos || slash == 0) return false;
        const std::string head = posix.substr(0, slash);
        const std::string suffix = ".artifacts";
        if (head.size() < suffix.size() ||
            head.compare(head.size() - suffix.size(), suffix.size(),
                         suffix) != 0 ||
            head == current) {
            return false;
        }
        *out = current + posix.substr(slash);
        return true;
    };
    int changed = 0;
    Transaction transaction(db_);
    for (auto& version : document.value().versions) {
        if (!version.managed) continue;
        std::string rewritten;
        if (rewrite(version.path, &rewritten)) {
            Statement update = db_.prepare(
                "UPDATE versions SET path = ? WHERE id = ?");
            update.bind(1, rewritten);
            update.bind(2, version.id.str());
            update.step_done();
            if (auto failure = sqlite_step_error(db_, "rebase_artifact_paths")) {
                // int sentinel: -1 tells the caller the rebase is unreliable
                // (save_as refuses to publish on a failed rebase).
                return -1;
            }
            ++changed;
        }
        auto trash = version.metadata.find("trash");
        if (trash != version.metadata.end() && trash->is_object()) {
            auto original = trash->find("original_path");
            if (original != trash->end() && original->is_string()) {
                std::string trash_rewritten;
                if (rewrite(original->get<std::string>(),
                            &trash_rewritten)) {
                    Json merged = version.metadata;
                    merged["trash"]["original_path"] = trash_rewritten;
                    Statement update = db_.prepare(
                        "UPDATE versions SET metadata = ? WHERE id = ?");
                    update.bind(1, json_column(merged, "{}"));
                    update.bind(2, version.id.str());
                    update.step_done();
                    if (auto failure = sqlite_step_error(db_, "rebase_artifact_paths")) {
                        return -1;
                    }
                    ++changed;
                }
            }
        }
    }
    if (db_.table_exists("model_versions")) {
        // Registry rows pass through verbatim on this side; the URI prefix
        // rewrite is mechanical and stays schema-stable. Collect first,
        // update after — never modify a table mid-scan.
        Statement scan =
            db_.prepare("SELECT id, artifact_uri FROM model_versions");
        std::vector<std::pair<std::string, std::string>> rewrites;
        while (scan.step()) {
            if (scan.is_null(1)) continue;
            std::string rewritten;
            if (rewrite(scan.text(1), &rewritten)) {
                rewrites.emplace_back(scan.text(0), rewritten);
            }
        }
        for (const auto& [id, uri] : rewrites) {
            Statement update = db_.prepare(
                "UPDATE model_versions SET artifact_uri = ? WHERE id = ?");
            update.bind(1, uri);
            update.bind(2, id);
            update.step_done();
            if (auto failure = sqlite_step_error(db_, "rebase_artifact_paths")) {
                // int sentinel: -1 tells the caller the rebase is unreliable
                // (save_as refuses to publish on a failed rebase).
                return -1;
            }
            ++changed;
        }
    }
    if (changed > 0) bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return -1;
    return changed;
}

DataError CatalogRepository::finish_run_transaction(
    const domain::RunId& run_id, const std::string& status,
    const domain::Json& extra_parameters) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    Transaction transaction(db_);
    Json merged;
    {
        Statement select =
            db_.prepare("SELECT parameters FROM runs WHERE id = ?");
        select.bind(1, run_id.str());
        if (!select.step()) {
            return DataError(ErrorCode::NotFound,
                             "run not found: " + run_id.str());
        }
        merged = parse_json_column(select.text(0), "{}");
        if (!merged.is_object()) merged = Json::object();
    }
    if (extra_parameters.is_object()) {
        for (auto it = extra_parameters.begin();
             it != extra_parameters.end(); ++it) {
            merged[it.key()] = *it;
        }
    }
    Statement update =
        db_.prepare("UPDATE runs SET status = ?, parameters = ? WHERE id = ?");
    update.bind(1, status);
    update.bind(2, json_column(merged, "{}"));
    update.bind(3, run_id.str());
    update.step_done();
    if (auto failure = sqlite_step_error(db_, "finish_run_transaction")) {
        return *failure;
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

// ---- conv-31b: db.py module-level algorithm bridge + store surface ----------

Database& CatalogRepository::writable_database() {
    // The apply_changes / reconcile / queries_sql free-function families
    // take Database& over one connection — exactly the Python index
    // exposing its connection to those module-level methods (findings
    // §C-6). Callers open_read_write() first.
    //
    // CONV-31b Wave4 fix (V1-P1-2): the schema-loss rebuild inside
    // apply_changes/reconcile follows db.py's rebuild discipline — the
    // reset sequence CLOSES every handle to the store, this resident one
    // included (Python closes the whole pool; its connections then
    // reconnect transparently on next use). Reconnect the same way:
    // _connect parity — Create open + per-connection DDL. If the reopen
    // itself fails the caller receives the closed handle and the next
    // prepare reports it, exactly like a Python connection error.
    if (!db_.is_open()) {
        std::error_code ec;
        std::filesystem::create_directories(sqlite_path_.parent_path(), ec);
        auto opened = Database::open(sqlite_path_, SqliteOpenMode::Create);
        if (opened.is_ok()) {
            db_ = std::move(opened.value());
            (void)db_.ensure_schema();
        }
    }
    return db_;
}

DataError CatalogRepository::write_all(const CatalogDocument& document) {
    // db.py write_all → rebuild: close first (the rebuild opens its own
    // connection; a resident handle would keep the file alive across the
    // reset between the two attempts), then the two-attempt orchestration
    // lives in rebuild_store (findings §D-5 layering: A1 orchestration
    // shell over A2's rebuild_once primitive).
    close();
    return rebuild_store(sqlite_path_, document);
}

void CatalogRepository::reset() {
    // db.py reset (1042-1054): close + best-effort unlink of the db and
    // its -journal/-wal/-shm siblings (a stale -wal would resurrect old
    // pages in the rebuilt store).
    close();
    reset_store_files(sqlite_path_);
}

std::optional<std::int64_t> CatalogRepository::recorded_manifest_mtime_ns()
    const {
    // service.py _recorded_manifest_mtime_ns: read_sync_state parses;
    // missing/unparsable/unreadable all collapse to nullopt (the single
    // revision-read source, findings §C-6).
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return std::nullopt;
    return read_sync_state(opened.value(), "manifest_mtime_ns");
}

void CatalogRepository::record_manifest_mtime_ns(
    const std::filesystem::path& manifest_path) {
    // service.py _record_manifest_mtime_ns: INSERT OR REPLACE, everything
    // swallowed — the accounting must never break a checkpoint. Note this
    // is a plain sync_state write: no revision bump.
    const auto mtime = disk_mtime_ns(manifest_path);
    if (!mtime.has_value()) return;
    std::optional<Database> scratch;
    Database* db =
        bookkeeping_connection(scratch, db_, sqlite_path_,
                               SqliteOpenMode::ReadWrite);
    if (db == nullptr) return;
    Transaction transaction(*db);
    Statement statement = db->prepare(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)");
    statement.bind(1, "manifest_mtime_ns");
    statement.bind(2, std::to_string(*mtime));
    statement.step_done();
    if (auto failure = sqlite_step_error(*db, "record_manifest_mtime_ns")) {
        // Void bookkeeping helper: detect + report, then abandon the write
        // (the transaction rolls back on scope exit — never a silent
        // partial commit; review C1).
        std::fprintf(stderr, "pwb-catalog: %s failed: %s\n", "record_manifest_mtime_ns",
                     failure->message.c_str());
        return;
    }
    (void)transaction.commit();  // swallow parity (bookkeeping writes)
}

// ---- working-copy registry completion (db.py 1335-1425) ---------------------

std::optional<WorkingCopy> CatalogRepository::get_working_copy_by_path(
    const std::string& path) const {
    // _read_rows semantics: missing file / no schema → miss (never throws).
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return std::nullopt;
    Database& db = opened.value();
    if (!db.table_exists("sync_state") ||
        !db.table_exists("working_copies")) {
        return std::nullopt;
    }
    Statement rows = db.prepare(
        "SELECT working_id, source_version_id, path, state, display_name, "
        "created_at, updated_at, payload_mtime_ns, source_size_bytes"
        " FROM working_copies WHERE path = ?");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, path);
    if (!rows.step()) return std::nullopt;
    return working_copy_from_row(rows);
}

std::optional<WorkingCopy>
CatalogRepository::get_live_working_copy_for_source(
    const domain::VersionId& source_version_id) const {
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return std::nullopt;
    Database& db = opened.value();
    if (!db.table_exists("sync_state") ||
        !db.table_exists("working_copies")) {
        return std::nullopt;
    }
    Statement rows = db.prepare(
        "SELECT working_id, source_version_id, path, state, display_name, "
        "created_at, updated_at, payload_mtime_ns, source_size_bytes"
        " FROM working_copies WHERE source_version_id = ?"
        " AND state IN ('checked_out','dirty','committing')"
        " ORDER BY created_at LIMIT 1");
    if (!rows.is_valid()) return std::nullopt;
    rows.bind(1, source_version_id.str());
    if (!rows.step()) return std::nullopt;
    return working_copy_from_row(rows);
}

std::vector<WorkingCopy> CatalogRepository::list_working_copies(
    const std::vector<std::string>& states) const {
    std::vector<WorkingCopy> copies;
    auto opened = Database::open(sqlite_path_, SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return copies;
    Database& db = opened.value();
    if (!db.table_exists("sync_state") ||
        !db.table_exists("working_copies")) {
        return copies;
    }
    // db.py list_working_copies: an EMPTY state list means no filter (the
    // `if states:` truthiness gate), not "match nothing".
    Statement rows = [&]() {
        if (states.empty()) {
            return db.prepare(
                "SELECT working_id, source_version_id, path, state, "
                "display_name, created_at, updated_at, payload_mtime_ns, "
                "source_size_bytes FROM working_copies ORDER BY created_at");
        }
        std::string marks;
        for (std::size_t i = 0; i < states.size(); ++i) {
            marks += i == 0 ? "?" : ",?";
        }
        return db.prepare(
            "SELECT working_id, source_version_id, path, state, "
            "display_name, created_at, updated_at, payload_mtime_ns, "
            "source_size_bytes FROM working_copies WHERE state IN (" +
            marks + ") ORDER BY created_at");
    }();
    if (!rows.is_valid()) return copies;
    for (std::size_t i = 0; i < states.size(); ++i) {
        rows.bind(static_cast<int>(i + 1), states[i]);
    }
    while (rows.step()) {
        copies.push_back(working_copy_from_row(rows));
    }
    return copies;
}

Result<std::string> CatalogRepository::register_working_copy(
    const domain::VersionId& source_version_id, const std::string& path,
    const std::string& display_name,
    std::optional<std::int64_t> payload_mtime_ns,
    std::optional<std::int64_t> source_size_bytes) {
    // db.py register_working_copy: generative id + local ISO-second twin
    // timestamps + state='checked_out'; bare INSERT; sync_state untouched.
    const std::string working_id = "wc-" + random_hex(12);
    const std::string now = local_now_iso_seconds();
    std::optional<Database> scratch;
    Database* db = bookkeeping_connection(scratch, db_, sqlite_path_,
                                          SqliteOpenMode::Create);
    if (db == nullptr) {
        return DataError(ErrorCode::CorruptDatabase,
                         "cannot open working-copy registry");
    }
    Transaction transaction(*db);
    {
        Statement existing =
            db->prepare("SELECT 1 FROM working_copies WHERE path = ?");
        if (existing.is_valid()) {
            existing.bind(1, path);
            if (existing.step()) {
                return DataError(ErrorCode::DuplicateOperation,
                                 "UNIQUE constraint failed: "
                                 "working_copies.path",
                                 Json{{"working_copy_path", path}});
            }
        }
    }
    Statement statement = db->prepare(
        "INSERT INTO working_copies (working_id, source_version_id, path,"
        " state, display_name, created_at, updated_at, payload_mtime_ns,"
        " source_size_bytes) VALUES (?,?,?,?,?,?,?,?,?)");
    if (!statement.is_valid()) {
        return DataError(ErrorCode::CorruptDatabase,
                         "cannot prepare working-copy insert");
    }
    statement.bind(1, working_id);
    statement.bind(2, source_version_id.str());
    statement.bind(3, path);
    statement.bind(4, "checked_out");
    statement.bind(5, display_name);
    statement.bind(6, now);
    statement.bind(7, now);
    if (payload_mtime_ns.has_value()) {
        statement.bind(8, *payload_mtime_ns);
    } else {
        statement.bind_null(8);
    }
    if (source_size_bytes.has_value()) {
        statement.bind(9, *source_size_bytes);
    } else {
        statement.bind_null(9);
    }
    statement.step_done();
    if (auto failure = sqlite_step_error(*db, "register working copy")) {
        return *failure;
    }
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return working_id;
}

// ---- payload staging leases, write side (db.py 1227-1331) -------------------

std::optional<std::string> CatalogRepository::acquire_staging_lease(
    const std::vector<std::string>& targets, const std::string& kind) {
    // A lease is protection, not a gate: any failure → nullopt and the
    // caller proceeds (pre-lease behavior). No sync_state (schema missing
    // → nullopt, mirroring _schema_present) and no revision bump.
    const std::string lease_id = random_hex(32);
    const std::string now = local_now_iso_seconds();
    std::optional<Database> scratch;
    Database* db = bookkeeping_connection(scratch, db_, sqlite_path_,
                                          SqliteOpenMode::Create);
    if (db == nullptr) return std::nullopt;
    if (!db->table_exists("sync_state")) return std::nullopt;
    Transaction transaction(*db);
    for (const auto& target : targets) {
        Statement row = db->prepare(
            "INSERT OR REPLACE INTO staging_leases"
            " (lease_id, target, kind, acquired_at, heartbeat_at)"
            " VALUES (?,?,?,?,?)");
        if (!row.is_valid()) return std::nullopt;
        row.bind(1, lease_id);
        row.bind(2, target);
        row.bind(3, kind);
        row.bind(4, now);
        row.bind(5, now);
        row.step_done();
        if (auto failure = sqlite_step_error(*db, "acquire staging lease")) {
            return std::nullopt;  // RAII rolls the transaction back
        }
    }
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return std::nullopt;
    return lease_id;
}

void CatalogRepository::release_staging_lease(const std::string& lease_id) {
    std::optional<Database> scratch;
    Database* db = bookkeeping_connection(scratch, db_, sqlite_path_,
                                          SqliteOpenMode::Create);
    if (db == nullptr) return;
    Transaction transaction(*db);
    Statement statement =
        db->prepare("DELETE FROM staging_leases WHERE lease_id = ?");
    if (!statement.is_valid()) return;
    statement.bind(1, lease_id);
    statement.step_done();
    if (auto failure = sqlite_step_error(*db, "release_staging_lease")) {
        // Void bookkeeping helper: detect + report, then abandon the write
        // (the transaction rolls back on scope exit — never a silent
        // partial commit; review C1).
        std::fprintf(stderr, "pwb-catalog: %s failed: %s\n", "release_staging_lease",
                     failure->message.c_str());
        return;
    }
    (void)transaction.commit();  // swallow parity (bookkeeping writes)
}

void CatalogRepository::heartbeat_staging_lease(
    const std::string& lease_id) {
    std::optional<Database> scratch;
    Database* db = bookkeeping_connection(scratch, db_, sqlite_path_,
                                          SqliteOpenMode::Create);
    if (db == nullptr) return;
    Transaction transaction(*db);
    Statement statement = db->prepare(
        "UPDATE staging_leases SET heartbeat_at = ? WHERE lease_id = ?");
    if (!statement.is_valid()) return;
    statement.bind(1, local_now_iso_seconds());
    statement.bind(2, lease_id);
    statement.step_done();
    if (auto failure = sqlite_step_error(*db, "heartbeat_staging_lease")) {
        // Void bookkeeping helper: detect + report, then abandon the write
        // (the transaction rolls back on scope exit — never a silent
        // partial commit; review C1).
        std::fprintf(stderr, "pwb-catalog: %s failed: %s\n", "heartbeat_staging_lease",
                     failure->message.c_str());
        return;
    }
    (void)transaction.commit();  // swallow parity (bookkeeping writes)
}

int CatalogRepository::prune_stale_staging_leases(
    std::optional<double> ttl_seconds) {
    // cutoff = (now - ttl) in the same local ISO-second format the
    // heartbeat writes and gc.hpp compares lexically.
    const double ttl = ttl_seconds.value_or(3600.0);
    const std::time_t cutoff = static_cast<std::time_t>(
        static_cast<double>(std::time(nullptr)) - ttl);
    std::optional<Database> scratch;
    Database* db = bookkeeping_connection(scratch, db_, sqlite_path_,
                                          SqliteOpenMode::Create);
    if (db == nullptr) return 0;
    Transaction transaction(*db);
    Statement statement = db->prepare(
        "DELETE FROM staging_leases WHERE heartbeat_at <= ?");
    if (!statement.is_valid()) return 0;
    statement.bind(1, local_iso_seconds(cutoff));
    statement.step_done();
    if (auto failure = sqlite_step_error(*db, "prune_stale_staging_leases")) {
        return -1;  // int sentinel (same contract as the commit failure below)
    }
    const int removed = sqlite3_changes(db->handle());
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return -1;
    return removed >= 0 ? removed : 0;
}

// ---- model-registry + promote transactions (R7) ------------------------------

DataError CatalogRepository::upsert_model(const Model& model) {
    Transaction transaction(db_);
    auto error = upsert_model_in_transaction(db_, model);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::upsert_model_version(
    const ModelVersion& version) {
    Transaction transaction(db_);
    auto error = upsert_model_version_in_transaction(db_, version);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::promote_model_transaction(
    const Model& model, const ModelVersion& version) {
    // service.py promote_model: BOTH rows flip in ONE transaction (both or
    // neither), one revision bump.
    Transaction transaction(db_);
    auto error = upsert_model_in_transaction(db_, model);
    if (error.code != ErrorCode::Ok) return error;
    error = upsert_model_version_in_transaction(db_, version);
    if (error.code != ErrorCode::Ok) return error;
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::commit_promote_transaction(
    const DataVersion& version, const DataRun& run) {
    // promote_version landing: version rows + FULL run row (inputs/
    // outputs/ports) + current pointer + one revision bump — the
    // commit_version_transaction shape plus the run row.
    Transaction transaction(db_);
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    error = upsert_run_rows(run);
    if (error.code != ErrorCode::Ok) return error;
    Statement pointer = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    pointer.bind(1, version.id.str());
    pointer.bind(2, version.created_at);
    pointer.bind(3, version.asset_id.str());
    pointer.step_done();
    if (auto failure = sqlite_step_error(db_, "commit_promote_transaction")) {
        return *failure;
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

DataError CatalogRepository::commit_working_copy_transaction(
    const std::optional<DataAsset>& new_asset, const DataVersion& version,
    const std::optional<domain::RunId>& run_id) {
    // service.py 1821 parity: an optional NEW asset row lands in the SAME
    // transaction as its first version — no zero-version asset window.
    Transaction transaction(db_);
    if (new_asset.has_value()) {
        auto error = upsert_asset_in_transaction(*new_asset);
        if (error.code != ErrorCode::Ok) return error;
    }
    auto error = upsert_version_rows(version);
    if (error.code != ErrorCode::Ok) return error;
    Statement pointer = db_.prepare(
        "UPDATE assets SET current_version_id = ?, updated_at = ? "
        "WHERE id = ?");
    pointer.bind(1, version.id.str());
    pointer.bind(2, version.created_at);
    pointer.bind(3, version.asset_id.str());
    pointer.step_done();
    if (auto failure = sqlite_step_error(db_, "commit_working_copy_transaction")) {
        return *failure;
    }
    if (run_id.has_value()) {
        Statement row = db_.prepare(
            "INSERT OR IGNORE INTO run_outputs (run_id, version_id) "
            "VALUES (?,?)");
        row.bind(1, run_id->str());
        row.bind(2, version.id.str());
        row.step_done();
        if (auto failure = sqlite_step_error(db_, "commit_working_copy_transaction")) {
            return *failure;
        }
    }
    bump_revision();
    if (auto commit_error = transaction.commit();
        commit_error.code != ErrorCode::Ok) return commit_error;
    return DataError(ErrorCode::Ok, "");
}

int CatalogRepository::current_revision() const {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
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

// ---------------------------------------------------------------------------
// store.py manifest surface (conv-31b; free functions over the file)
// ---------------------------------------------------------------------------

std::filesystem::path catalog_manifest_file(
    const std::filesystem::path& project_path) {
    // storage.py catalog_file_for = <proj>.artifacts/metadata/catalog.json.
    // pwb::project::catalog_manifest_for is that derivation — one source.
    return pwb::project::catalog_manifest_for(project_path);
}

std::filesystem::path catalog_manifest_bak_file(
    const std::filesystem::path& project_path) {
    const std::filesystem::path manifest =
        pwb::project::catalog_manifest_for(project_path);
    return manifest.parent_path() /
           (manifest.filename().string() + ".bak");
}

std::filesystem::path isolate_corrupt_file(
    const std::filesystem::path& file) {
    // store.py _isolate_corrupt_file: rename to
    // "<name>.corrupt-YYYYmmdd-HHMMSS-<6-digit microseconds>" (LOCAL time),
    // fsync the directory, and on any failure return the input path so the
    // corrupt bytes stay in place (best-effort forensics, never a gate).
    const auto now = std::chrono::system_clock::now();
    const std::time_t seconds =
        std::chrono::system_clock::to_time_t(now);
    const auto fraction =
        now - std::chrono::system_clock::from_time_t(seconds);
    const int microseconds = static_cast<int>(
        std::chrono::duration_cast<std::chrono::microseconds>(fraction)
            .count());
    std::tm local{};
#if !defined(_WIN32)
    localtime_r(&seconds, &local);
#else
    localtime_s(&local, &seconds);
#endif
    char date[32];
    const std::size_t written =
        std::strftime(date, sizeof(date), "%Y%m%d-%H%M%S", &local);
    char stamp[48];
    std::snprintf(stamp, sizeof(stamp), "%.*s-%06d",
                  static_cast<int>(written), date, microseconds);
    const std::filesystem::path isolated =
        file.parent_path() /
        (file.filename().string() + ".corrupt-" + stamp);
    std::error_code ec;
    std::filesystem::rename(file, isolated, ec);
    if (ec) return file;
    fsync_dir_best_effort(file.parent_path());
    return isolated;
}

Result<ManifestLoad> load_manifest(
    const std::filesystem::path& manifest_path) {
    // store.py CatalogStore.load — the L1-L5 ladder. The L2/L4 message
    // skeletons are byte-identical to Python; the parenthesized detail is
    // parser-specific (B-14, oracle-masked). The isolated/isolated_backup
    // members are only meaningful on the success ladder — on L2/L4 the
    // Result channel carries the error alone and the isolation targets
    // are observable on disk.
    ManifestLoad load;
    const std::filesystem::path bak =
        manifest_path.parent_path() /
        (manifest_path.filename().string() + ".bak");
    const std::string path_text = manifest_path.generic_string();
    auto is_file = [](const std::filesystem::path& candidate) {
        std::error_code ec;
        return std::filesystem::is_regular_file(candidate, ec);
    };
    auto l2 = [&](const std::string& detail) -> DataError {
        load.isolated = isolate_corrupt_file(manifest_path);
        return DataError(ErrorCode::CorruptDatabase,
                         "Catalog file is corrupt and no backup is "
                         "available: " +
                             path_text + " (" + detail + ")");
    };

    if (is_file(manifest_path)) {
        auto json = read_manifest_json(manifest_path);
        if (json.is_ok()) {
            auto document = parse_manifest_document(json.value());
            if (document.is_ok()) {
                load.document = std::move(document.value());
                return load;  // L1
            }
            if (!is_file(bak)) return l2(document.error().message);
        } else if (!is_file(bak)) {
            return l2(json.error().message);
        }
        // Corrupt canonical with a live backup: fall through to the bak
        // ladder below.
    }
    if (is_file(bak)) {
        auto json = read_manifest_json(bak);
        if (json.is_ok()) {
            auto document = parse_manifest_document(json.value());
            if (document.is_ok()) {
                // L3: re-promote the backup so subsequent saves start from
                // a clean canonical state (rename failure is swallowed —
                // the document still loads).
                std::error_code ec;
                std::filesystem::rename(bak, manifest_path, ec);
                if (!ec) {
                    fsync_dir_best_effort(manifest_path.parent_path());
                    load.repromoted_backup = true;
                }
                load.from_backup = true;
                load.document = std::move(document.value());
                return load;
            }
            load.isolated = isolate_corrupt_file(manifest_path);
            load.isolated_backup = isolate_corrupt_file(bak);
            return DataError(
                ErrorCode::CorruptDatabase,
                "Catalog file and its backup are both corrupt: " +
                    path_text + " (backup error: " +
                    document.error().message + ")");
        }
        load.isolated = isolate_corrupt_file(manifest_path);
        load.isolated_backup = isolate_corrupt_file(bak);
        return DataError(ErrorCode::CorruptDatabase,
                         "Catalog file and its backup are both corrupt: " +
                             path_text + " (backup error: " +
                             json.error().message + ")");
    }
    return load;  // L5: absent manifest and absent backup = empty document
}

DataError save_manifest(const std::filesystem::path& manifest_path,
                        const CatalogDocument& document, bool pretty,
                        ManifestCheckpointState* state) {
    // store.py CatalogStore.save: serialize → #1183 unchanged-skip → tmp
    // (fsync) → rotate/seed .bak → rename home → fsync dir, with the
    // restore ladder (old revision goes back when the new one never
    // landed).
    const Json manifest = manifest_document_json(document);
    const std::string payload =
        pretty ? manifest.dump(2) : manifest.dump();
    const std::string digest = domain::Sha256::of_bytes(payload);
    if (state != nullptr && state->valid && state->digest == digest) {
        // Skip only when the on-disk file still carries OUR last write's
        // mtime — an externally replaced/deleted manifest defeats the skip.
        const auto current = disk_mtime_ns(manifest_path);
        if (current.has_value() && *current == state->mtime_ns) {
            return DataError(ErrorCode::Ok, "");
        }
    }
    ensure_manifest_layout(manifest_path);
    const std::filesystem::path parent = manifest_path.parent_path();
    const std::filesystem::path bak =
        parent / (manifest_path.filename().string() + ".bak");
    const std::filesystem::path tmp =
        parent / ("." + manifest_path.filename().string() + "." +
                  random_hex(8) + ".tmp");
    bool old_moved = false;
    std::error_code ec;
    if (!write_file_fsynced(tmp, payload)) {
        return DataError(ErrorCode::IoError,
                         "manifest temp write failed: " +
                             tmp.generic_string());
    }
    if (std::filesystem::exists(manifest_path, ec)) {
        std::filesystem::rename(manifest_path, bak, ec);
        if (ec) {
            safe_unlink(tmp);
            return DataError(ErrorCode::IoError,
                             "manifest .bak rotation failed: " +
                                 ec.message());
        }
        old_moved = true;
    } else {
        // First save: seed the .bak with the SAME revision so a once-saved
        // catalog never sits in a no-backup window (#372/C14).
        const std::filesystem::path seed_tmp =
            parent / ("." + bak.filename().string() + "." +
                      random_hex(8) + ".tmp");
        if (!write_file_fsynced(seed_tmp, payload)) {
            safe_unlink(tmp);
            return DataError(ErrorCode::IoError,
                             "manifest backup seed failed: " +
                                 seed_tmp.generic_string());
        }
        std::filesystem::rename(seed_tmp, bak, ec);
        if (ec) {
            safe_unlink(seed_tmp);
            safe_unlink(tmp);
            return DataError(ErrorCode::IoError,
                             "manifest backup seed rename failed: " +
                                 ec.message());
        }
        fsync_dir_best_effort(parent);
    }
    std::filesystem::rename(tmp, manifest_path, ec);
    if (ec) {
        safe_unlink(tmp);
        std::error_code probe;
        if (old_moved && !std::filesystem::exists(manifest_path, probe) &&
            std::filesystem::exists(bak, probe)) {
            // The canonical file was moved aside but the new one never
            // landed: put the previous revision back (best-effort).
            std::error_code restore;
            std::filesystem::rename(bak, manifest_path, restore);
            fsync_dir_best_effort(parent);
        }
        return DataError(ErrorCode::IoError,
                         "manifest rename failed: " + ec.message());
    }
    fsync_dir_best_effort(parent);
    if (state != nullptr) {
        // An unreadable post-write mtime leaves the previous pair in
        // place, exactly like store.py's `if written_mtime is not None`.
        if (const auto written = disk_mtime_ns(manifest_path)) {
            state->digest = digest;
            state->mtime_ns = *written;
            state->valid = true;
        }
    }
    return DataError(ErrorCode::Ok, "");
}

}  // namespace pwb::catalog
