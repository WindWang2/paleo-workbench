#include "pwb/catalog/sqlite.hpp"

#include <system_error>

#include <filesystem>

namespace pwb::catalog {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

namespace {
DataError make_error(const std::string& context, sqlite3* db, int code) {
    const char* text = db != nullptr ? sqlite3_errmsg(db) : "unknown";
    return DataError(ErrorCode::CorruptDatabase,
                     context + ": " + std::string(text),
                     domain::Json{{"sqlite_code", code}});
}
}  // namespace

Database::~Database() {
    if (db_ != nullptr) sqlite3_close_v2(db_);
}

void Database::close() {
    if (db_ != nullptr) {
        sqlite3_close_v2(db_);
        db_ = nullptr;
    }
}

Database::Database(Database&& other) noexcept
    : db_(other.db_), last_error_(other.last_error_) {
    other.db_ = nullptr;
}

Database& Database::operator=(Database&& other) noexcept {
    if (this != &other) {
        if (db_ != nullptr) sqlite3_close_v2(db_);
        db_ = other.db_;
        last_error_ = other.last_error_;
        other.db_ = nullptr;
    }
    return *this;
}

Result<Database> Database::open(const std::filesystem::path& file,
                                SqliteOpenMode mode) {
    Database database;
    int flags = SQLITE_OPEN_URI;
    switch (mode) {
        case SqliteOpenMode::ReadOnly:
            flags |= SQLITE_OPEN_READONLY;
            break;
        case SqliteOpenMode::ReadWrite:
            flags |= SQLITE_OPEN_READWRITE;
            break;
        case SqliteOpenMode::Create:
            flags |= SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE;
            break;
    }
    const std::string path = file.generic_string();
    // Read-only WAL access normally CREATES -shm/-wal coordination files —
    // a write, at the filesystem level, for a "read-only" open. Under the
    // single-writer protocol no concurrent writer exists, so a cleanly
    // closed store is opened immutable (provably zero footprint). When a
    // -wal file exists it may hold unmerged committed transactions (e.g.
    // after a crash): fall back to a normal read-only open — correctness
    // over footprint.
    if (mode == SqliteOpenMode::ReadOnly) {
        std::error_code exists_ec;
        const bool has_wal = std::filesystem::exists(
            file.parent_path() / (file.filename().string() + "-wal"),
            exists_ec);
        if (!has_wal) {
            const std::string uri = "file:" + path + "?immutable=1";
            if (sqlite3_open_v2(uri.c_str(), &database.db_, flags,
                                nullptr) == SQLITE_OK) {
                sqlite3_busy_timeout(database.db_, 5000);
                return database;
            }
            if (database.db_ != nullptr) {
                sqlite3_close(database.db_);
                database.db_ = nullptr;
            }
        }
    }
    const int rc = sqlite3_open_v2(path.c_str(), &database.db_, flags, nullptr);
    if (rc != SQLITE_OK) {
        DataError error = make_error("sqlite open failed", database.db_, rc);
        return error;
    }
    sqlite3_busy_timeout(database.db_, 5000);
    if (mode != SqliteOpenMode::ReadOnly) {
        sqlite3_exec(database.db_, "PRAGMA journal_mode=WAL", nullptr,
                     nullptr, nullptr);
    }
    return database;
}

DataError Database::execute(std::string_view sql) {
    char* message = nullptr;
    // sqlite3_exec needs a C string; a string_view slice is not guaranteed
    // NUL-terminated (review CP9 — latent hazard only, every current
    // caller passes a literal, but the wrapper must stay safe to reuse).
    const std::string owned(sql);
    const int rc = sqlite3_exec(db_, owned.c_str(), nullptr, nullptr, &message);
    if (rc != SQLITE_OK) {
        DataError error(ErrorCode::CorruptDatabase,
                        "execute failed: " +
                            (message != nullptr ? std::string(message)
                                                : std::string("unknown")));
        sqlite3_free(message);
        last_error_ = rc;
        return error;
    }
    return DataError(ErrorCode::Ok, "");
}

Result<std::int64_t> Database::scalar_i64(std::string_view sql) {
    Statement statement = prepare(sql);
    if (!statement.is_valid()) {
        return statement.error();
    }
    if (!statement.step()) {
        if (!statement.ok()) return statement.error();
        return DataError(ErrorCode::NotFound, "no row for scalar query");
    }
    return statement.int64(0);
}

bool Database::table_exists(std::string_view name) {
    Statement statement =
        prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
                "name = ?");
    if (!statement.is_valid()) return false;
    statement.bind(1, name);
    return statement.step();
}

Statement Database::prepare(std::string_view sql) {
    sqlite3_stmt* stmt = nullptr;
    const int rc = sqlite3_prepare_v2(db_, sql.data(),
                                      static_cast<int>(sql.size()), &stmt,
                                      nullptr);
    if (rc != SQLITE_OK) {
        last_error_ = rc;
        return Statement(db_, nullptr,
                         make_error("cannot prepare statement", db_, rc));
    }
    return Statement(db_, stmt);
}

DataError Database::begin_immediate() {
    return execute("BEGIN IMMEDIATE");
}

DataError Database::commit() {
    return execute("COMMIT");
}

DataError Database::rollback() {
    return execute("ROLLBACK");
}

DataError Database::ensure_schema() {
    static const char* kStatements[] = {
        // assets
        "CREATE TABLE IF NOT EXISTS assets ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL,"
        " name_search TEXT NOT NULL DEFAULT '',"
        " type TEXT NOT NULL DEFAULT 'unknown',"
        " description TEXT NOT NULL DEFAULT '',"
        " current_version_id TEXT, legacy_resource_id TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}',"
        " created_at TEXT NOT NULL DEFAULT '',"
        " updated_at TEXT NOT NULL DEFAULT '',"
        " trashed INTEGER NOT NULL DEFAULT 0, trashed_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name)",
        "CREATE INDEX IF NOT EXISTS idx_assets_name_search ON "
        "assets(name_search)",
        "CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(type)",
        "CREATE INDEX IF NOT EXISTS idx_assets_name_id ON assets(name, id)",
        "CREATE INDEX IF NOT EXISTS idx_assets_live_name_id ON assets(name, "
        "id) WHERE trashed = 0",
        "CREATE INDEX IF NOT EXISTS idx_assets_type_name_id ON assets(type, "
        "name, id)",
        "CREATE INDEX IF NOT EXISTS idx_assets_updated_name_id ON "
        "assets(updated_at, name, id)",
        // versions
        "CREATE TABLE IF NOT EXISTS versions ("
        " id TEXT PRIMARY KEY, asset_id TEXT NOT NULL,"
        " version_number INTEGER NOT NULL, stage TEXT NOT NULL,"
        " managed INTEGER NOT NULL DEFAULT 1,"
        " path TEXT NOT NULL DEFAULT '', source_uri TEXT,"
        " format TEXT NOT NULL DEFAULT '', size_bytes INTEGER, sha256 TEXT,"
        " run_id TEXT, metadata TEXT NOT NULL DEFAULT '{}',"
        " created_at TEXT NOT NULL DEFAULT '',"
        " trashed INTEGER NOT NULL DEFAULT 0, trashed_at TEXT,"
        " parent_ids TEXT NOT NULL DEFAULT '[]')",
        "CREATE INDEX IF NOT EXISTS idx_versions_asset_id ON "
        "versions(asset_id)",
        "CREATE INDEX IF NOT EXISTS idx_versions_stage ON versions(stage)",
        "CREATE INDEX IF NOT EXISTS idx_versions_trashed ON "
        "versions(trashed)",
        "CREATE INDEX IF NOT EXISTS idx_versions_source_sha ON "
        "versions(source_uri, sha256)",
        "CREATE INDEX IF NOT EXISTS idx_versions_asset_version ON "
        "versions(asset_id, version_number)",
        "CREATE INDEX IF NOT EXISTS idx_versions_external_path ON "
        "versions(path) WHERE managed = 0 AND trashed = 0",
        // tags
        "CREATE TABLE IF NOT EXISTS tags ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
        " display_name TEXT, metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE TABLE IF NOT EXISTS asset_tags ("
        " asset_id TEXT NOT NULL, tag_id TEXT NOT NULL,"
        " PRIMARY KEY (asset_id, tag_id))",
        "CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_id ON "
        "asset_tags(tag_id)",
        "CREATE TABLE IF NOT EXISTS version_tags ("
        " version_id TEXT NOT NULL, tag_id TEXT NOT NULL,"
        " PRIMARY KEY (version_id, tag_id))",
        "CREATE INDEX IF NOT EXISTS idx_version_tags_tag_id ON "
        "version_tags(tag_id)",
        // runs
        "CREATE TABLE IF NOT EXISTS runs ("
        " id TEXT PRIMARY KEY, operation TEXT NOT NULL,"
        " parameters TEXT NOT NULL DEFAULT '{}',"
        " generator TEXT NOT NULL DEFAULT '',"
        " status TEXT NOT NULL DEFAULT 'completed',"
        " model_ref TEXT, created_at TEXT NOT NULL DEFAULT '')",
        "CREATE TABLE IF NOT EXISTS run_inputs ("
        " run_id TEXT NOT NULL, version_id TEXT NOT NULL,"
        " PRIMARY KEY (run_id, version_id))",
        "CREATE INDEX IF NOT EXISTS idx_run_inputs_version_id ON "
        "run_inputs(version_id)",
        "CREATE TABLE IF NOT EXISTS run_outputs ("
        " run_id TEXT NOT NULL, version_id TEXT NOT NULL,"
        " PRIMARY KEY (run_id, version_id))",
        "CREATE INDEX IF NOT EXISTS idx_run_outputs_version_id ON "
        "run_outputs(version_id)",
        "CREATE TABLE IF NOT EXISTS lineage ("
        " parent_version_id TEXT NOT NULL, child_version_id TEXT NOT NULL,"
        " PRIMARY KEY (parent_version_id, child_version_id))",
        "CREATE INDEX IF NOT EXISTS idx_lineage_child ON "
        "lineage(child_version_id)",
        "CREATE INDEX IF NOT EXISTS idx_lineage_parent ON lineage(parent_"
        "version_id, child_version_id)",
        // models
        "CREATE TABLE IF NOT EXISTS models ("
        " id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
        " model_name TEXT NOT NULL,"
        " model_type TEXT NOT NULL DEFAULT 'unknown',"
        " capability TEXT NOT NULL DEFAULT '',"
        " provider TEXT NOT NULL DEFAULT '',"
        " status TEXT NOT NULL DEFAULT 'demo',"
        " metadata TEXT NOT NULL DEFAULT '{}',"
        " created_at TEXT NOT NULL DEFAULT '',"
        " provenance TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_models_model_id ON models(model_id)",
        "CREATE TABLE IF NOT EXISTS model_versions ("
        " id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
        " model_version TEXT NOT NULL DEFAULT '1',"
        " artifact_uri TEXT NOT NULL DEFAULT '', checksum TEXT,"
        " input_schema TEXT NOT NULL DEFAULT '{}',"
        " output_schema TEXT NOT NULL DEFAULT '{}',"
        " preprocessing_version TEXT NOT NULL DEFAULT '',"
        " runtime TEXT NOT NULL DEFAULT '',"
        " deterministic INTEGER NOT NULL DEFAULT 1,"
        " demo_only INTEGER NOT NULL DEFAULT 0,"
        " status TEXT NOT NULL DEFAULT 'production',"
        " metadata TEXT NOT NULL DEFAULT '{}',"
        " created_at TEXT NOT NULL DEFAULT '',"
        " provenance TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_model_versions_model_id ON "
        "model_versions(model_id)",
        // state
        "CREATE TABLE IF NOT EXISTS sync_state ("
        " key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS staging_leases ("
        " lease_id TEXT NOT NULL, target TEXT NOT NULL,"
        " kind TEXT NOT NULL DEFAULT 'register',"
        " acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL,"
        " PRIMARY KEY (lease_id, target))",
        "CREATE INDEX IF NOT EXISTS idx_staging_leases_target ON "
        "staging_leases(target)",
        "CREATE TABLE IF NOT EXISTS working_copies ("
        " working_id TEXT PRIMARY KEY, source_version_id TEXT NOT NULL,"
        " path TEXT NOT NULL UNIQUE,"
        " state TEXT NOT NULL DEFAULT 'checked_out',"
        " display_name TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
        " payload_mtime_ns INTEGER, source_size_bytes INTEGER)",
        "CREATE INDEX IF NOT EXISTS idx_working_copies_source ON "
        "working_copies(source_version_id)",
        // V11 typed lineage / compound payloads
        "CREATE TABLE IF NOT EXISTS run_ports ("
        " run_id TEXT NOT NULL, direction TEXT NOT NULL,"
        " role TEXT NOT NULL DEFAULT '', version_id TEXT NOT NULL,"
        " ordinal INTEGER NOT NULL DEFAULT 0,"
        " required INTEGER NOT NULL DEFAULT 1,"
        " entity_type TEXT NOT NULL DEFAULT '',"
        " entity_id TEXT NOT NULL DEFAULT '',"
        " note TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (run_id, direction, version_id, role, ordinal))",
        "CREATE INDEX IF NOT EXISTS idx_run_ports_version ON "
        "run_ports(version_id)",
        "CREATE TABLE IF NOT EXISTS version_members ("
        " version_id TEXT NOT NULL, name TEXT NOT NULL,"
        " rel_path TEXT NOT NULL, member_role TEXT NOT NULL DEFAULT '',"
        " ordinal INTEGER NOT NULL DEFAULT 0,"
        " required INTEGER NOT NULL DEFAULT 1, sha256 TEXT,"
        " size_bytes INTEGER, PRIMARY KEY (version_id, name))",
        "CREATE INDEX IF NOT EXISTS idx_version_members_version ON "
        "version_members(version_id)",
    };
    for (const char* sql : kStatements) {
        auto error = execute(sql);
        if (error.code != ErrorCode::Ok) return error;
    }
    return DataError(ErrorCode::Ok, "");
}

Statement::Statement(sqlite3* db, sqlite3_stmt* stmt,
                     domain::DataError prepare_error)
    : db_(db), stmt_(stmt), error_(std::move(prepare_error)) {}

Statement::~Statement() {
    if (stmt_ != nullptr) sqlite3_finalize(stmt_);
}

Statement::Statement(Statement&& other) noexcept
    : db_(other.db_), stmt_(other.stmt_), error_(std::move(other.error_)) {
    other.stmt_ = nullptr;
    other.db_ = nullptr;
    other.error_ = DataError(ErrorCode::Ok, "");
}

Statement& Statement::operator=(Statement&& other) noexcept {
    if (this != &other) {
        if (stmt_ != nullptr) sqlite3_finalize(stmt_);
        db_ = other.db_;
        stmt_ = other.stmt_;
        error_ = std::move(other.error_);
        other.stmt_ = nullptr;
        other.db_ = nullptr;
        other.error_ = DataError(ErrorCode::Ok, "");
    }
    return *this;
}

void Statement::reset() {
    if (stmt_ != nullptr) {
        sqlite3_reset(stmt_);
        sqlite3_clear_bindings(stmt_);
    }
    error_ = DataError(ErrorCode::Ok, "");
}

// Bind failures (SQLITE_RANGE on a bad index, SQLITE_NOMEM, binding on an
// empty statement) are recorded and surface at the next step/step_done —
// the first failure wins, mirroring how the step codes are captured.
void Statement::record_bind_error(int rc, const char* what) {
    if (error_.ok() && rc != SQLITE_OK) {
        error_ = make_error(what, db_, rc);
    }
}

Statement& Statement::bind(int index, std::string_view text) {
    if (stmt_ == nullptr) {
        record_bind_error(SQLITE_MISUSE, "bind on empty statement");
        return *this;
    }
    record_bind_error(
        sqlite3_bind_text(stmt_, index, text.data(),
                          static_cast<int>(text.size()), SQLITE_TRANSIENT),
        "bind text failed");
    return *this;
}

Statement& Statement::bind(int index, std::int64_t value) {
    if (stmt_ == nullptr) {
        record_bind_error(SQLITE_MISUSE, "bind on empty statement");
        return *this;
    }
    record_bind_error(sqlite3_bind_int64(stmt_, index, value),
                      "bind int failed");
    return *this;
}

Statement& Statement::bind(int index, double value) {
    if (stmt_ == nullptr) {
        record_bind_error(SQLITE_MISUSE, "bind on empty statement");
        return *this;
    }
    record_bind_error(sqlite3_bind_double(stmt_, index, value),
                      "bind double failed");
    return *this;
}

Statement& Statement::bind_null(int index) {
    if (stmt_ == nullptr) {
        record_bind_error(SQLITE_MISUSE, "bind on empty statement");
        return *this;
    }
    record_bind_error(sqlite3_bind_null(stmt_, index), "bind null failed");
    return *this;
}

bool Statement::step() {
    if (stmt_ == nullptr) return false;  // prepare error already recorded
    if (!error_.ok()) return false;      // bind failure pending
    const int rc = sqlite3_step(stmt_);
    if (rc == SQLITE_ROW) return true;
    if (rc != SQLITE_DONE) {
        error_ = make_error("statement failed", db_, rc);
    }
    return false;
}

DataError Statement::step_done() {
    if (!error_.ok()) return error_;
    if (stmt_ == nullptr) {
        // Unreachable through Database::prepare (it records the prepare
        // error); guards a default-constructed or moved-from statement.
        error_ = DataError(ErrorCode::CorruptDatabase,
                           "step_done on empty statement");
        return error_;
    }
    const int rc = sqlite3_step(stmt_);
    if (rc != SQLITE_DONE && rc != SQLITE_ROW) {
        error_ = make_error("statement failed", db_, rc);
        return error_;
    }
    // Re-arm for bind + step_done loops: reset keeps the prepared
    // statement reusable without re-preparing per row.
    sqlite3_reset(stmt_);
    return DataError(ErrorCode::Ok, "");
}

std::string Statement::text(int column) const {
    const unsigned char* value = sqlite3_column_text(stmt_, column);
    if (value == nullptr) return "";
    const int size = sqlite3_column_bytes(stmt_, column);
    return std::string(reinterpret_cast<const char*>(value),
                       static_cast<std::size_t>(size));
}

std::int64_t Statement::int64(int column) const {
    return sqlite3_column_int64(stmt_, column);
}

bool Statement::is_null(int column) const {
    return sqlite3_column_type(stmt_, column) == SQLITE_NULL;
}

int Statement::column_count() const {
    return sqlite3_column_count(stmt_);
}

std::string Statement::column_name(int column) const {
    const char* name = sqlite3_column_name(stmt_, column);
    return name != nullptr ? std::string(name) : std::string();
}

Transaction::Transaction(Database& db) : db_(db) {
    begin_error_ = db_.begin_immediate();
    began_ = begin_error_.ok();
}

Transaction::~Transaction() {
    if (began_ && !committed_) {
        db_.rollback();  // best-effort; nothing to surface from a destructor
    }
}

DataError Transaction::commit() {
    // A failed BEGIN means there is nothing to commit — surface the begin
    // error instead of issuing a stray COMMIT outside any transaction.
    if (!began_) return begin_error_;
    DataError error = db_.commit();
    if (error.code != ErrorCode::Ok) {
        // COMMIT failed (disk full / BUSY / I/O): the transaction is still
        // open per sqlite semantics — leave it for the destructor's
        // rollback and report the error. Never mark committed.
        return error;
    }
    committed_ = true;
    return DataError(ErrorCode::Ok, "");
}

DataError Transaction::rollback() {
    if (!began_) return begin_error_;
    if (committed_) return DataError(ErrorCode::Ok, "");
    DataError error = db_.rollback();
    committed_ = true;  // nothing left to roll back either way
    return error;
}

}  // namespace pwb::catalog
