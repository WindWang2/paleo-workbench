// Generic dirty-set write channel over the canonical catalog.sqlite
// (conv-31b Wave2-A2; paleo_workbench/catalog/db.py 1951-2604 parity, R1
// recon contract as frozen in 31b-findings).
//
// Ported surface: DirtySet / apply_changes / reconcile / rebuild_once /
// rebuild_store / reset_store_files / sync_store / is_fresh / read_revision
// / read_sync_state plus the write-side keep-rule helpers
// (_reconcile_version_parents, _delete_version_keep_run_edges,
// _reconcile_run_edges, _delete_run_keep_version_edges, _run_covers_edge,
// _version_owns_edge, _write_run_ports, _write_version_members) which stay
// private to this TU.
//
// Registered bounded deviations (31b-findings §E, nothing beyond):
//   B-4  name_search / tag normalization use the bounded ASCII fold
//        (entity_view normalize_search_name / normalize_tag_name), not
//        Python's NFKC+casefold.
//   B-5  JSON TEXT columns serialize with nlohmann dump() (no ", "/": "
//        separators) — same-side canonical, values compare parsed.
//   B-6  Python set iteration order (old_parents, new run-io pairs, the
//        db-only half of _symmetric_diff) becomes a deterministic order
//        (rowid / document order); PK dedup keeps the end state equal.
//   B-7  The rebuild DDL runs inside the single BEGIN IMMEDIATE
//        transaction (strictly more atomic, unobservable — idempotent DDL).
//   B-9  sync_store self-heals ONLY the SQLITE_CORRUPT*/READONLY/NOTADB
//        families (Python catches the broader sqlite3.DatabaseError);
//        stale writes always pass through.
//
// Faithfulness note on statement errors: sqlite.hpp's Statement cannot
// surface a failed sqlite3_step (DONE and an error both read "no row") and
// Transaction::commit() discards the COMMIT return code. This channel must
// propagate both (sync_store's reset+rebuild self-heal keys off them, and a
// swallowed insert failure would COMMIT a partial transaction where Python
// raises and rolls back), so this TU drives the same C API through a
// file-local wrapper that keeps every rc visible.

#include "pwb/catalog/apply_changes.hpp"

#include "pwb/catalog/entity_view.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <optional>
#include <set>
#include <string>
#include <system_error>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace pwb::catalog {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Json;

namespace {

// ==== error surface =========================================================

DataError sqlite_error(sqlite3* handle, const std::string& context, int code) {
    const char* text = handle != nullptr ? sqlite3_errmsg(handle) : "unknown";
    return DataError(ErrorCode::CorruptDatabase,
                     context + ": " + std::string(text),
                     Json{{"sqlite_code", code}});
}

// The CORRUPT*/READONLY/NOTADB family is the ONLY self-heal trigger
// (findings B-9). Python's CatalogStaleWriteError is an OSError, invisible
// to `except sqlite3.DatabaseError`; is_stale_write() is additionally
// checked first so a stale write can never be classified here.
bool is_selfheal_sqlite(const DataError& error) {
    if (!error.detail.is_object()) return false;
    const auto it = error.detail.find("sqlite_code");
    if (it == error.detail.end() || !it->is_number_integer()) return false;
    const int primary = it->get<int>() & 0xff;
    return primary == SQLITE_CORRUPT || primary == SQLITE_READONLY ||
           primary == SQLITE_NOTADB;
}

// Database::execute()-sourced errors carry no sqlite_code; the self-heal
// classifier needs it, so enrich from the recorded rc.
DataError enrich_sqlite_code(DataError error, Database& db) {
    if (error.code != ErrorCode::Ok && error.detail.is_object() &&
        !error.detail.contains("sqlite_code")) {
        error.detail["sqlite_code"] = db.last_extended_error();
    }
    return error;
}

// CONV-31b Wave4 fix (V1-P1-2): the schema-missing fallback in
// apply_changes/reconcile is Python's `self.write_all(document)` — which
// is rebuild (db.py 1471-1487): CLOSE, then two attempts with a reset()
// between them (attempt 0 raises DatabaseError → delete the files →
// attempt 1 rewrites from scratch). The old single rebuild_once(db, …)
// on the caller's live handle lost that reset self-heal: a schema-less
// AND corrupt file errored out to the caller where Python heals.
// Attempt 0 keeps the caller's handle (avoiding an impossible reopen from
// inside a free function over Database&); only the reset sequence closes
// it — db.py's rebuild equally closes the pool first. Callers must treat
// a handle they handed here as single-use and reopen afterwards
// (CatalogRepository::writable_database reconnects lazily, db.py _connect
// parity). An unnamed/in-memory database has no files to reset: single
// attempt, nothing else is expressible.
DataError rebuild_after_schema_loss(Database& db,
                                    const CatalogDocument& document) {
    const char* file = sqlite3_db_filename(db.handle(), "main");
    const std::filesystem::path db_path =
        file != nullptr ? std::filesystem::path(file) : std::filesystem::path();
    if (db_path.empty()) {
        return rebuild_once(db, document);
    }
    DataError first = rebuild_once(db, document);
    if (first.code == ErrorCode::Ok) return first;
    if (!is_selfheal_sqlite(first)) return first;
    db.close();  // release handles before unlink (WAL semantics)
    reset_store_files(db_path);
    return rebuild_store(db_path, document);  // attempt 1: fresh connections
}

// Python int(str): optional surrounding whitespace, optional sign, digits.
// Overflow reads as unparsable (Python bignums have no int64 analogue;
// machine-written revisions never reach that range).
std::optional<long long> parse_python_int(const std::string& raw) {
    auto is_space = [](char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
               c == '\v';
    };
    std::size_t begin = 0;
    std::size_t end = raw.size();
    while (begin < end && is_space(raw[begin])) ++begin;
    while (end > begin && is_space(raw[end - 1])) --end;
    if (begin >= end) return std::nullopt;
    bool negative = false;
    if (raw[begin] == '+' || raw[begin] == '-') {
        negative = raw[begin] == '-';
        ++begin;
    }
    if (begin >= end) return std::nullopt;
    long long value = 0;
    const long long max = std::numeric_limits<long long>::max();
    for (std::size_t i = begin; i < end; ++i) {
        if (raw[i] < '0' || raw[i] > '9') return std::nullopt;
        const int digit = raw[i] - '0';
        if (value > (max - digit) / 10) return std::nullopt;
        value = value * 10 + digit;
    }
    return negative ? -value : value;
}

// Byte-identical #1220 CAS messages (db.py:2047-2051 / 2454-2458). The two
// variants differ only in 保存/同步.
constexpr const char* kStaleSaveMessage =
    "数据目录元数据已被其他实例修改（事务内比对失败）；"
    "为避免覆盖他人提交，本次保存已中止。"
    "请重新打开工程后重试。";
constexpr const char* kStaleSyncMessage =
    "数据目录元数据已被其他实例修改（事务内比对失败）；"
    "为避免覆盖他人提交，本次同步已中止。"
    "请重新打开工程后重试。";

// ==== statement runner ======================================================

class Stmt {
public:
    Stmt(Database& db, const std::string& sql) : handle_(db.handle()) {
        const int rc =
            sqlite3_prepare_v2(handle_, sql.c_str(), -1, &stmt_, nullptr);
        if (rc != SQLITE_OK) {
            stmt_ = nullptr;
            error_ = sqlite_error(handle_, "cannot prepare statement", rc);
        }
    }
    ~Stmt() {
        if (stmt_ != nullptr) sqlite3_finalize(stmt_);
    }
    Stmt(const Stmt&) = delete;
    Stmt& operator=(const Stmt&) = delete;

    bool ok() const { return error_.code == ErrorCode::Ok; }
    const DataError& error() const { return error_; }

    Stmt& text(int index, std::string_view value) {
        sqlite3_bind_text(stmt_, index, value.data(),
                          static_cast<int>(value.size()), SQLITE_TRANSIENT);
        return *this;
    }
    Stmt& i64(int index, std::int64_t value) {
        sqlite3_bind_int64(stmt_, index, value);
        return *this;
    }
    Stmt& dbl(int index, double value) {
        sqlite3_bind_double(stmt_, index, value);
        return *this;
    }
    Stmt& null(int index) {
        sqlite3_bind_null(stmt_, index);
        return *this;
    }

    // True while a row is available; a failed step records the error.
    bool step() {
        if (stmt_ == nullptr) return false;
        const int rc = sqlite3_step(stmt_);
        if (rc == SQLITE_ROW) return true;
        if (rc != SQLITE_DONE) {
            error_ = sqlite_error(handle_, "statement failed", rc);
        }
        return false;
    }

    // Non-query execution: step (draining any unexpected rows), then reset
    // on success so the statement can be rebound in a loop.
    void run() {
        while (step()) {
        }
        if (ok()) reset();
    }

    void reset() {
        if (stmt_ != nullptr) {
            sqlite3_reset(stmt_);
            sqlite3_clear_bindings(stmt_);
        }
    }

    int column_count() const {
        return stmt_ != nullptr ? sqlite3_column_count(stmt_) : 0;
    }
    int col_type(int column) const {
        return sqlite3_column_type(stmt_, column);
    }
    bool is_null(int column) const { return col_type(column) == SQLITE_NULL; }
    std::string col_text(int column) const {
        const unsigned char* value = sqlite3_column_text(stmt_, column);
        if (value == nullptr) return std::string();
        const int size = sqlite3_column_bytes(stmt_, column);
        return std::string(reinterpret_cast<const char*>(value),
                           static_cast<std::size_t>(size));
    }
    std::int64_t col_i64(int column) const {
        return sqlite3_column_int64(stmt_, column);
    }
    double col_double(int column) const {
        return sqlite3_column_double(stmt_, column);
    }
    std::string col_blob(int column) const {
        const void* data = sqlite3_column_blob(stmt_, column);
        if (data == nullptr) return std::string();
        const int size = sqlite3_column_bytes(stmt_, column);
        return std::string(static_cast<const char*>(data),
                           static_cast<std::size_t>(size));
    }

private:
    sqlite3* handle_ = nullptr;
    sqlite3_stmt* stmt_ = nullptr;
    DataError error_{ErrorCode::Ok, ""};
};

// BEGIN IMMEDIATE … COMMIT with a best-effort ROLLBACK on every early-exit
// path and COMMIT-failure propagation (Python: try / except: ROLLBACK;
// re-raise).
class TxnGuard {
public:
    explicit TxnGuard(Database& db) : db_(db) {
        Stmt begin(db_, "BEGIN IMMEDIATE");
        begin.run();
        if (!begin.ok()) begin_error_ = begin.error();
    }
    bool begun() const { return !begin_error_.has_value(); }
    const DataError& begin_error() const { return *begin_error_; }

    DataError commit() {
        Stmt commit_stmt(db_, "COMMIT");
        commit_stmt.run();
        if (!commit_stmt.ok()) {
            rollback();
            return commit_stmt.error();
        }
        committed_ = true;
        return DataError(ErrorCode::Ok, "");
    }
    void rollback() {
        if (committed_ || !begun()) return;
        Stmt rollback_stmt(db_, "ROLLBACK");
        rollback_stmt.run();  // best effort (Python swallows sqlite3.Error)
        committed_ = true;
    }
    ~TxnGuard() { rollback(); }

private:
    Database& db_;
    bool committed_ = false;
    std::optional<DataError> begin_error_;
};

// ==== row serialization (ONE per table; column order == DDL order) =========

// A dynamic SQLite value for the type-sensitive reconcile diff. Equality
// mirrors Python tuple comparison: int==float compares numerically, str vs
// int never equals, None only equals None.
struct Val {
    enum Kind { Null, Int, Real, Text, Blob };
    Kind kind = Null;
    std::int64_t i = 0;
    double d = 0.0;
    std::string s;

    bool operator==(const Val& other) const {
        if (kind == Int && other.kind == Real) {
            return static_cast<double>(i) == other.d;
        }
        if (kind == Real && other.kind == Int) {
            return d == static_cast<double>(other.i);
        }
        if (kind != other.kind) return false;
        switch (kind) {
            case Null:
                return true;
            case Int:
                return i == other.i;
            case Real:
                return d == other.d;
            default:
                return s == other.s;
        }
    }
};

Val val_text(std::string s) {
    Val v;
    v.kind = Val::Text;
    v.s = std::move(s);
    return v;
}
Val val_int(std::int64_t i) {
    Val v;
    v.kind = Val::Int;
    v.i = i;
    return v;
}

Val read_val(const Stmt& st, int column) {
    switch (st.col_type(column)) {
        case SQLITE_INTEGER:
            return val_int(st.col_i64(column));
        case SQLITE_FLOAT: {
            Val v;
            v.kind = Val::Real;
            v.d = st.col_double(column);
            return v;
        }
        case SQLITE_TEXT:
            return val_text(st.col_text(column));
        case SQLITE_BLOB: {
            Val v;
            v.kind = Val::Blob;
            v.s = st.col_blob(column);
            return v;
        }
        default:
            return Val{};  // SQLITE_NULL
    }
}

// Python json.dumps(..., ensure_ascii=False) → nlohmann dump() (B-5).
std::string json_text(const Json& value) { return value.dump(); }

// db.py _run_row: `json.dumps(run.model_ref) if run.model_ref else None` —
// None and the falsy empty dict both store NULL.
Val model_ref_val(const DataRun& run) {
    if (!run.model_ref.has_value()) return Val{};
    const Json& ref = *run.model_ref;
    if (ref.is_null()) return Val{};
    if (ref.is_object() && ref.empty()) return Val{};
    return val_text(ref.dump());
}

std::vector<Val> asset_row(const DataAsset& a) {
    std::vector<Val> row;
    row.reserve(11);
    row.push_back(val_text(a.name));
    // Python normalize_asset_search_name is NFKC+casefold; this side uses
    // the bounded ASCII fold (B-4, entity_view single definition point).
    row.push_back(val_text(normalize_search_name(a.name)));
    row.push_back(val_text(a.type));
    row.push_back(val_text(a.description));
    row.push_back(a.current_version_id.has_value()
                      ? val_text(a.current_version_id->str())
                      : Val{});
    row.push_back(a.legacy_resource_id.has_value()
                      ? val_text(*a.legacy_resource_id)
                      : Val{});
    row.push_back(val_text(json_text(a.metadata)));
    row.push_back(val_text(a.created_at));
    row.push_back(val_text(a.updated_at));
    row.push_back(val_int(a.trashed ? 1 : 0));
    row.push_back(a.trashed_at.has_value() ? val_text(*a.trashed_at) : Val{});
    return row;
}

std::vector<Val> version_row(const DataVersion& v) {
    std::vector<Val> row;
    row.reserve(15);
    row.push_back(val_text(v.asset_id.str()));
    row.push_back(val_int(v.version_number));
    row.push_back(val_text(std::string(domain::to_string(v.stage))));
    row.push_back(val_int(v.managed ? 1 : 0));
    row.push_back(val_text(v.path));
    row.push_back(v.source_uri.has_value() ? val_text(*v.source_uri) : Val{});
    row.push_back(val_text(v.format));
    row.push_back(v.size_bytes.has_value() ? val_int(*v.size_bytes) : Val{});
    row.push_back(v.sha256.has_value() ? val_text(*v.sha256) : Val{});
    row.push_back(v.run_id.has_value() ? val_text(v.run_id->str()) : Val{});
    row.push_back(val_text(json_text(v.metadata)));
    row.push_back(val_text(v.created_at));
    row.push_back(val_int(v.trashed ? 1 : 0));
    row.push_back(v.trashed_at.has_value() ? val_text(*v.trashed_at) : Val{});
    Json parents = Json::array();
    for (const auto& parent : v.parent_version_ids) {
        parents.push_back(parent.str());
    }
    row.push_back(val_text(parents.dump()));
    return row;
}

std::vector<Val> run_row(const DataRun& run) {
    std::vector<Val> row;
    row.reserve(6);
    row.push_back(val_text(run.operation));
    row.push_back(val_text(json_text(run.parameters)));
    row.push_back(val_text(run.generator));
    row.push_back(val_text(run.status));
    row.push_back(model_ref_val(run));
    row.push_back(val_text(run.created_at));
    return row;
}

std::vector<Val> tag_row(const Tag& t) {
    std::vector<Val> row;
    row.reserve(3);
    row.push_back(val_text(normalize_tag_name(t.name)));
    row.push_back(t.display_name.has_value() ? val_text(*t.display_name) : Val{});
    row.push_back(val_text(json_text(t.metadata)));
    return row;
}

std::vector<Val> model_row(const Model& m) {
    std::vector<Val> row;
    row.reserve(9);
    row.push_back(val_text(m.model_id));
    row.push_back(val_text(m.model_name));
    row.push_back(val_text(m.model_type));
    row.push_back(val_text(m.capability));
    row.push_back(val_text(m.provider));
    row.push_back(val_text(m.status));
    row.push_back(val_text(json_text(m.metadata)));
    row.push_back(val_text(m.created_at));
    row.push_back(val_text(json_text(m.provenance)));
    return row;
}

std::vector<Val> model_version_row(const ModelVersion& mv) {
    std::vector<Val> row;
    row.reserve(14);
    row.push_back(val_text(mv.model_id));
    row.push_back(val_text(mv.model_version));
    row.push_back(val_text(mv.artifact_uri));
    row.push_back(mv.checksum.has_value() ? val_text(*mv.checksum) : Val{});
    row.push_back(val_text(json_text(mv.input_schema)));
    row.push_back(val_text(json_text(mv.output_schema)));
    row.push_back(val_text(mv.preprocessing_version));
    row.push_back(val_text(mv.runtime));
    row.push_back(val_int(mv.deterministic ? 1 : 0));
    row.push_back(val_int(mv.demo_only ? 1 : 0));
    row.push_back(val_text(mv.status));
    row.push_back(val_text(json_text(mv.metadata)));
    row.push_back(val_text(mv.created_at));
    row.push_back(val_text(json_text(mv.provenance)));
    return row;
}

// Full derived-collection rows (owner column included); the reconcile drift
// compares the tails (row[1:]).
std::vector<Val> run_port_row(const std::string& run_id, bool output,
                              const RunPort& p) {
    std::vector<Val> row;
    row.reserve(9);
    row.push_back(val_text(run_id));
    row.push_back(val_text(output ? "output" : "input"));
    row.push_back(val_text(p.role));
    row.push_back(val_text(p.version_id.str()));
    row.push_back(val_int(p.ordinal));
    row.push_back(val_int(p.required ? 1 : 0));
    row.push_back(val_text(p.entity_type));
    row.push_back(val_text(p.entity_id));
    row.push_back(val_text(p.note));
    return row;
}

std::vector<Val> version_member_row(const std::string& version_id,
                                    const VersionMember& m) {
    std::vector<Val> row;
    row.reserve(8);
    row.push_back(val_text(version_id));
    row.push_back(val_text(m.name));
    row.push_back(val_text(m.rel_path));
    row.push_back(val_text(m.member_role));
    row.push_back(val_int(m.ordinal));
    row.push_back(val_int(m.required ? 1 : 0));
    row.push_back(m.sha256.has_value() ? val_text(*m.sha256) : Val{});
    row.push_back(m.size_bytes.has_value() ? val_int(*m.size_bytes) : Val{});
    return row;
}

void bind_val(Stmt& st, int index, const Val& v) {
    switch (v.kind) {
        case Val::Null:
            st.null(index);
            break;
        case Val::Int:
            st.i64(index, v.i);
            break;
        case Val::Real:
            st.dbl(index, v.d);
            break;
        default:
            st.text(index, v.s);
            break;
    }
}

void bind_vals(Stmt& st, int start, const std::vector<Val>& row) {
    for (std::size_t i = 0; i < row.size(); ++i) {
        bind_val(st, static_cast<int>(start + i), row[i]);
    }
}

// ==== SQL constants (db.py 588-735 / 319-351 / 543-560) =====================

constexpr const char* kAssetUpsertSql =
    "INSERT INTO assets (id, name, name_search, type, description,"
    " current_version_id, legacy_resource_id, metadata, created_at, updated_at,"
    " trashed, trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
    " name_search=excluded.name_search, type=excluded.type,"
    " description=excluded.description,"
    " current_version_id=excluded.current_version_id,"
    " legacy_resource_id=excluded.legacy_resource_id,"
    " metadata=excluded.metadata, created_at=excluded.created_at,"
    " updated_at=excluded.updated_at, trashed=excluded.trashed,"
    " trashed_at=excluded.trashed_at";

constexpr const char* kVersionUpsertSql =
    "INSERT INTO versions (id, asset_id, version_number, stage,"
    " managed, path, source_uri, format, size_bytes, sha256, run_id, metadata,"
    " created_at, trashed, trashed_at, parent_ids)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET asset_id=excluded.asset_id,"
    " version_number=excluded.version_number, stage=excluded.stage,"
    " managed=excluded.managed, path=excluded.path,"
    " source_uri=excluded.source_uri, format=excluded.format,"
    " size_bytes=excluded.size_bytes, sha256=excluded.sha256,"
    " run_id=excluded.run_id, metadata=excluded.metadata,"
    " created_at=excluded.created_at, trashed=excluded.trashed,"
    " trashed_at=excluded.trashed_at, parent_ids=excluded.parent_ids";

constexpr const char* kRunUpsertSql =
    "INSERT INTO runs (id, operation, parameters, generator, status,"
    " model_ref, created_at) VALUES (?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET operation=excluded.operation,"
    " parameters=excluded.parameters, generator=excluded.generator,"
    " status=excluded.status, model_ref=excluded.model_ref,"
    " created_at=excluded.created_at";

constexpr const char* kTagUpsertSql =
    "INSERT INTO tags (id, name, display_name, metadata)"
    " VALUES (?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
    " display_name=excluded.display_name, metadata=excluded.metadata";

constexpr const char* kModelUpsertSql =
    "INSERT INTO models (id, model_id, model_name, model_type,"
    " capability, provider, status, metadata, created_at, provenance)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
    " model_name=excluded.model_name, model_type=excluded.model_type,"
    " capability=excluded.capability, provider=excluded.provider,"
    " status=excluded.status, metadata=excluded.metadata,"
    " created_at=excluded.created_at, provenance=excluded.provenance";

constexpr const char* kModelVersionUpsertSql =
    "INSERT INTO model_versions (id, model_id, model_version,"
    " artifact_uri, checksum, input_schema, output_schema, preprocessing_version,"
    " runtime, deterministic, demo_only, status, metadata, created_at, provenance)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
    " model_version=excluded.model_version, artifact_uri=excluded.artifact_uri,"
    " checksum=excluded.checksum, input_schema=excluded.input_schema,"
    " output_schema=excluded.output_schema,"
    " preprocessing_version=excluded.preprocessing_version,"
    " runtime=excluded.runtime, deterministic=excluded.deterministic,"
    " demo_only=excluded.demo_only, status=excluded.status,"
    " metadata=excluded.metadata, created_at=excluded.created_at,"
    " provenance=excluded.provenance";

// Defensive DDL (db.py:319-346): a store whose connect-time DDL loop broke
// early must not fail the next save.
constexpr const char* kRunPortsDdl =
    "CREATE TABLE IF NOT EXISTS run_ports ("
    " run_id TEXT NOT NULL, direction TEXT NOT NULL,"
    " role TEXT NOT NULL DEFAULT '', version_id TEXT NOT NULL,"
    " ordinal INTEGER NOT NULL DEFAULT 0,"
    " required INTEGER NOT NULL DEFAULT 1,"
    " entity_type TEXT NOT NULL DEFAULT '',"
    " entity_id TEXT NOT NULL DEFAULT '',"
    " note TEXT NOT NULL DEFAULT '',"
    " PRIMARY KEY (run_id, direction, version_id, role, ordinal))";
constexpr const char* kVersionMembersDdl =
    "CREATE TABLE IF NOT EXISTS version_members ("
    " version_id TEXT NOT NULL, name TEXT NOT NULL,"
    " rel_path TEXT NOT NULL,"
    " member_role TEXT NOT NULL DEFAULT '',"
    " ordinal INTEGER NOT NULL DEFAULT 0,"
    " required INTEGER NOT NULL DEFAULT 1, sha256 TEXT,"
    " size_bytes INTEGER, PRIMARY KEY (version_id, name))";

// Children first (db.py:543-560). rebuild wipes all of them.
constexpr const char* kDeleteOrder[] = {
    "run_ports",   "version_members", "working_copies", "staging_leases",
    "lineage",     "version_tags",    "asset_tags",     "run_outputs",
    "run_inputs",  "versions",        "runs",           "tags",
    "assets",      "model_versions",  "models",         "sync_state",
};

// Explicit id-first column lists for the reconcile `SELECT *` diff — column
// order == table definition order == the row builders above (C-10).
constexpr const char* kAssetDiffColumns =
    "id, name, name_search, type, description, current_version_id,"
    " legacy_resource_id, metadata, created_at, updated_at, trashed,"
    " trashed_at";
constexpr const char* kVersionDiffColumns =
    "id, asset_id, version_number, stage, managed, path, source_uri, format,"
    " size_bytes, sha256, run_id, metadata, created_at, trashed, trashed_at,"
    " parent_ids";
constexpr const char* kRunDiffColumns =
    "id, operation, parameters, generator, status, model_ref, created_at";
constexpr const char* kTagDiffColumns = "id, name, display_name, metadata";
constexpr const char* kModelDiffColumns =
    "id, model_id, model_name, model_type, capability, provider, status,"
    " metadata, created_at, provenance";
constexpr const char* kModelVersionDiffColumns =
    "id, model_id, model_version, artifact_uri, checksum, input_schema,"
    " output_schema, preprocessing_version, runtime, deterministic, demo_only,"
    " status, metadata, created_at, provenance";

constexpr std::size_t kIdBatchSize = 500;

// ==== shared write helpers ==================================================

DataError check_cas(Database& db, std::optional<long long> expected_revision,
                    const char* message) {
    if (!expected_revision.has_value()) return DataError(ErrorCode::Ok, "");
    Stmt query(db,
               "SELECT value FROM sync_state WHERE key = 'catalog_revision'");
    if (!query.ok()) return query.error();
    std::optional<long long> stored_rev;
    if (query.step()) {
        stored_rev = parse_python_int(query.col_text(0));
    }
    if (!query.ok()) return query.error();
    // A missing or unparsable stored key conflicts with ANY expected value,
    // including 0 (Python: stored None != expected int).
    if (stored_rev != expected_revision) {
        return DataError(ErrorCode::ConflictBaseVersion, message,
                         Json{{"stale_write", true}});
    }
    return DataError(ErrorCode::Ok, "");
}

DataError stamp_sync_state(Database& db, const CatalogDocument& document) {
    // The stamp carries DOCUMENT-carried values (service bumps in memory
    // before saving); index layout is the fixed constant 5.
    Stmt stamp(db,
               "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)");
    if (!stamp.ok()) return stamp.error();
    const std::pair<const char*, std::string> rows[] = {
        {"schema_version", std::to_string(document.schema_version)},
        {"catalog_revision", std::to_string(document.catalog_revision)},
        {"index_schema_version", std::to_string(kStoreSchemaVersion)},
    };
    for (const auto& entry : rows) {
        stamp.text(1, entry.first).text(2, entry.second);
        stamp.run();
        if (!stamp.ok()) return stamp.error();
    }
    return DataError(ErrorCode::Ok, "");
}

// Document-order iteration for one table's dirty ids (db.py:2001-2026):
// existing rows keep their rowid, ids not yet stored are NEW appends in
// mark order — both match how load_document restores list order.
DataError ordered_ids(Database& db, const std::vector<std::string>& marks,
                      const char* table, std::vector<std::string>& out) {
    out.clear();
    if (marks.empty()) return DataError(ErrorCode::Ok, "");
    std::unordered_map<std::string, std::int64_t> rowid_of;
    for (std::size_t start = 0; start < marks.size(); start += kIdBatchSize) {
        const std::size_t n = std::min(kIdBatchSize, marks.size() - start);
        std::string sql = "SELECT id, rowid FROM ";
        sql += table;
        sql += " WHERE id IN (";
        for (std::size_t i = 0; i < n; ++i) sql += (i == 0 ? "?" : ",?");
        sql += ")";
        Stmt query(db, sql);
        if (!query.ok()) return query.error();
        for (std::size_t i = 0; i < n; ++i) {
            query.text(static_cast<int>(i + 1), marks[start + i]);
        }
        while (query.step()) {
            rowid_of[query.col_text(0)] = query.col_i64(1);
        }
        if (!query.ok()) return query.error();
    }
    std::vector<std::pair<std::int64_t, const std::string*>> existing;
    for (const auto& id : marks) {
        const auto it = rowid_of.find(id);
        if (it != rowid_of.end()) existing.emplace_back(it->second, &id);
    }
    std::stable_sort(existing.begin(), existing.end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });
    for (const auto& entry : existing) out.push_back(*entry.second);
    for (const auto& id : marks) {
        if (rowid_of.find(id) == rowid_of.end()) out.push_back(id);
    }
    return DataError(ErrorCode::Ok, "");
}

// Flat (owner, tag) document pairs grouped owner-major, first-seen owner
// order — the shape of Python's document.asset_tags / version_tags dicts.
struct OwnerTagIndex {
    std::vector<std::string> owners;
    std::unordered_map<std::string, std::vector<std::string>> tags_of;
};

OwnerTagIndex group_owner_tags(
    const std::vector<std::pair<std::string, std::string>>& flat) {
    OwnerTagIndex index;
    for (const auto& link : flat) {
        const auto it = index.tags_of.find(link.first);
        if (it == index.tags_of.end()) {
            index.owners.push_back(link.first);
            index.tags_of.emplace(link.first,
                                  std::vector<std::string>{link.second});
        } else {
            it->second.push_back(link.second);
        }
    }
    return index;
}

// ==== write-side keep-rules (db.py:2179-2311 / 136-208) =====================

DataError run_covers_edge(Database& db, const std::string& parent,
                          const std::string& child, bool& covered) {
    Stmt query(db,
               "SELECT 1 FROM run_inputs ri JOIN run_outputs ro ON"
               " ro.run_id = ri.run_id"
               " WHERE ri.version_id = ? AND ro.version_id = ? LIMIT 1");
    if (!query.ok()) return query.error();
    query.text(1, parent).text(2, child);
    covered = query.step();
    if (!query.ok()) return query.error();
    return DataError(ErrorCode::Ok, "");
}

DataError version_owns_edge(Database& db, const std::string& parent,
                            const std::string& child, bool& owned) {
    owned = false;
    Stmt query(db, "SELECT parent_ids FROM versions WHERE id = ?");
    if (!query.ok()) return query.error();
    query.text(1, child);
    if (query.step()) {
        const Json parents = Json::parse(query.col_text(0), nullptr, false);
        if (!parents.is_discarded() && parents.is_array()) {
            for (const auto& entry : parents) {
                if (entry.is_string() &&
                    entry.get<std::string>() == parent) {
                    owned = true;
                    break;
                }
            }
        }
    }
    if (!query.ok()) return query.error();
    return DataError(ErrorCode::Ok, "");
}

// Make the run's port rows equal its input_ports/output_ports — the DELETE
// is unconditional so an emptied collection clears its rows (never gate on
// table_exists; the defensive CREATE runs first).
DataError write_run_ports(Database& db, const DataRun& run) {
    {
        Stmt ddl(db, kRunPortsDdl);
        ddl.run();
        if (!ddl.ok()) return ddl.error();
    }
    {
        Stmt del(db, "DELETE FROM run_ports WHERE run_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, run.id.str());
        del.run();
        if (!del.ok()) return del.error();
    }
    Stmt ins(db,
             "INSERT OR IGNORE INTO run_ports (run_id, direction, role,"
             " version_id, ordinal, required, entity_type, entity_id, note)"
             " VALUES (?,?,?,?,?,?,?,?,?)");
    if (!ins.ok()) return ins.error();
    for (const auto& port : run.input_ports) {
        bind_vals(ins, 1, run_port_row(run.id.str(), false, port));
        ins.run();
        if (!ins.ok()) return ins.error();
    }
    for (const auto& port : run.output_ports) {
        bind_vals(ins, 1, run_port_row(run.id.str(), true, port));
        ins.run();
        if (!ins.ok()) return ins.error();
    }
    return DataError(ErrorCode::Ok, "");
}

// Same unconditional-clear discipline for the version's member rows.
DataError write_version_members(Database& db, const DataVersion& version) {
    {
        Stmt ddl(db, kVersionMembersDdl);
        ddl.run();
        if (!ddl.ok()) return ddl.error();
    }
    {
        Stmt del(db, "DELETE FROM version_members WHERE version_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, version.id.str());
        del.run();
        if (!del.ok()) return del.error();
    }
    Stmt ins(db,
             "INSERT OR IGNORE INTO version_members (version_id, name,"
             " rel_path, member_role, ordinal, required, sha256, size_bytes)"
             " VALUES (?,?,?,?,?,?,?,?)");
    if (!ins.ok()) return ins.error();
    for (const auto& member : version.members) {
        bind_vals(ins, 1, version_member_row(version.id.str(), member));
        ins.run();
        if (!ins.ok()) return ins.error();
    }
    return DataError(ErrorCode::Ok, "");
}

// Old parent edges are dropped unless a retained run still produces them.
DataError reconcile_version_parents(Database& db, const DataVersion& version) {
    std::vector<std::string> old_parents;
    {
        Stmt query(db,
                   "SELECT parent_version_id FROM lineage WHERE"
                   " child_version_id = ?");
        if (!query.ok()) return query.error();
        query.text(1, version.id.str());
        while (query.step()) old_parents.push_back(query.col_text(0));
        if (!query.ok()) return query.error();
    }
    std::unordered_set<std::string> new_parents;
    for (const auto& parent : version.parent_version_ids) {
        new_parents.insert(parent.str());
    }
    {
        Stmt del(db,
                 "DELETE FROM lineage WHERE parent_version_id = ? AND"
                 " child_version_id = ?");
        if (!del.ok()) return del.error();
        for (const auto& parent : old_parents) {
            if (new_parents.count(parent) != 0) continue;
            bool covered = false;
            DataError error =
                run_covers_edge(db, parent, version.id.str(), covered);
            if (error.code != ErrorCode::Ok) return error;
            if (covered) continue;
            del.text(1, parent).text(2, version.id.str());
            del.run();
            if (!del.ok()) return del.error();
        }
    }
    {
        Stmt ins(db,
                 "INSERT OR IGNORE INTO lineage (parent_version_id,"
                 " child_version_id) VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& parent : version.parent_version_ids) {  // B-6 order
            ins.text(1, parent.str()).text(2, version.id.str());
            ins.run();
            if (!ins.ok()) return ins.error();
        }
    }
    return DataError(ErrorCode::Ok, "");
}

// Delete a version; run input/output link rows SURVIVE (owned by the run
// record as historical provenance); run-covered lineage edges survive.
DataError delete_version_keep_run_edges(Database& db,
                                        const std::string& version_id) {
    {
        Stmt del(db, "DELETE FROM versions WHERE id = ?");
        if (!del.ok()) return del.error();
        del.text(1, version_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt del(db, "DELETE FROM version_tags WHERE version_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, version_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt ddl(db, kVersionMembersDdl);  // db.py:2214 defensive DDL
        ddl.run();
        if (!ddl.ok()) return ddl.error();
    }
    {
        Stmt del(db, "DELETE FROM version_members WHERE version_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, version_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    std::vector<std::string> parents;  // snapshot before deleting (fetchall)
    {
        Stmt query(db,
                   "SELECT parent_version_id FROM lineage WHERE"
                   " child_version_id = ?");
        if (!query.ok()) return query.error();
        query.text(1, version_id);
        while (query.step()) parents.push_back(query.col_text(0));
        if (!query.ok()) return query.error();
    }
    {
        Stmt del(db,
                 "DELETE FROM lineage WHERE parent_version_id = ? AND"
                 " child_version_id = ?");
        if (!del.ok()) return del.error();
        for (const auto& parent : parents) {
            bool covered = false;
            DataError error = run_covers_edge(db, parent, version_id, covered);
            if (error.code != ErrorCode::Ok) return error;
            if (covered) continue;
            del.text(1, parent).text(2, version_id);
            del.run();
            if (!del.ok()) return del.error();
        }
    }
    return DataError(ErrorCode::Ok, "");
}

// Make run-derived lineage rows equal the run's io product. NOTE: the
// caller has already rewritten run_inputs/run_outputs, so the "old" pairs
// read the NEW io — a shrinking run's stale derived edge therefore
// survives (frozen Python order; oracle db_reconcile_drift pins the
// divergence against a full rebuild).
DataError reconcile_run_edges(Database& db, const DataRun& run) {
    std::set<std::pair<std::string, std::string>> new_pairs;
    for (const auto& input : run.input_version_ids) {
        for (const auto& output : run.output_version_ids) {
            new_pairs.emplace(input.str(), output.str());
        }
    }
    std::set<std::pair<std::string, std::string>> old_pairs;
    {
        Stmt query(db,
                   "SELECT ri.version_id, ro.version_id FROM run_inputs ri"
                   " JOIN run_outputs ro ON ro.run_id = ri.run_id"
                   " WHERE ri.run_id = ?");
        if (!query.ok()) return query.error();
        query.text(1, run.id.str());
        while (query.step()) {
            old_pairs.emplace(query.col_text(0), query.col_text(1));
        }
        if (!query.ok()) return query.error();
    }
    {
        Stmt del(db,
                 "DELETE FROM lineage WHERE parent_version_id = ? AND"
                 " child_version_id = ?");
        if (!del.ok()) return del.error();
        for (const auto& edge : old_pairs) {
            if (new_pairs.count(edge) != 0) continue;
            bool owned = false;
            DataError error = version_owns_edge(db, edge.first, edge.second, owned);
            if (error.code != ErrorCode::Ok) return error;
            if (owned) continue;
            del.text(1, edge.first).text(2, edge.second);
            del.run();
            if (!del.ok()) return del.error();
        }
    }
    {
        Stmt ins(db,
                 "INSERT OR IGNORE INTO lineage (parent_version_id,"
                 " child_version_id) VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& edge : new_pairs) {  // B-6 deterministic order
            ins.text(1, edge.first).text(2, edge.second);
            ins.run();
            if (!ins.ok()) return ins.error();
        }
    }
    return DataError(ErrorCode::Ok, "");
}

// Delete a run together with its io/ports rows; version-owned lineage
// edges survive.
DataError delete_run_keep_version_edges(Database& db,
                                        const std::string& run_id) {
    std::vector<std::pair<std::string, std::string>> io_pairs;  // snapshot
    {
        Stmt query(db,
                   "SELECT ri.version_id, ro.version_id FROM run_inputs ri"
                   " JOIN run_outputs ro ON ro.run_id = ri.run_id"
                   " WHERE ri.run_id = ?");
        if (!query.ok()) return query.error();
        query.text(1, run_id);
        while (query.step()) {
            io_pairs.emplace_back(query.col_text(0), query.col_text(1));
        }
        if (!query.ok()) return query.error();
    }
    {
        Stmt del(db, "DELETE FROM runs WHERE id = ?");
        if (!del.ok()) return del.error();
        del.text(1, run_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt del(db, "DELETE FROM run_inputs WHERE run_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, run_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt del(db, "DELETE FROM run_outputs WHERE run_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, run_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt ddl(db, kRunPortsDdl);  // db.py:2278 defensive DDL
        ddl.run();
        if (!ddl.ok()) return ddl.error();
    }
    {
        Stmt del(db, "DELETE FROM run_ports WHERE run_id = ?");
        if (!del.ok()) return del.error();
        del.text(1, run_id);
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt del(db,
                 "DELETE FROM lineage WHERE parent_version_id = ? AND"
                 " child_version_id = ?");
        if (!del.ok()) return del.error();
        for (const auto& edge : io_pairs) {
            bool owned = false;
            DataError error =
                version_owns_edge(db, edge.first, edge.second, owned);
            if (error.code != ErrorCode::Ok) return error;
            if (owned) continue;
            del.text(1, edge.first).text(2, edge.second);
            del.run();
            if (!del.ok()) return del.error();
        }
    }
    return DataError(ErrorCode::Ok, "");
}

// ==== reconcile diff helpers ================================================

using DocRows = std::vector<std::pair<std::string, std::vector<Val>>>;

// _symmetric_diff (db.py:738-752): doc-ordered changed ids, then db-only
// ids (deterministic read order; B-6). Comparison is per-column type
// sensitive (Val equality == Python tuple equality).
DataError diff_table(Database& db, const char* table, const char* columns,
                     const DocRows& doc_rows, std::vector<std::string>& out) {
    out.clear();
    std::string sql = "SELECT ";
    sql += columns;
    sql += " FROM ";
    sql += table;
    Stmt query(db, sql);
    if (!query.ok()) return query.error();
    std::unordered_map<std::string, std::vector<Val>> db_rows;
    std::vector<std::string> db_order;
    while (query.step()) {
        std::vector<Val> row;
        row.reserve(static_cast<std::size_t>(query.column_count() - 1));
        for (int c = 1; c < query.column_count(); ++c) {
            row.push_back(read_val(query, c));
        }
        const std::string id = query.col_text(0);
        if (db_rows.find(id) == db_rows.end()) db_order.push_back(id);
        db_rows[id] = std::move(row);
    }
    if (!query.ok()) return query.error();
    std::unordered_set<std::string> doc_ids;
    doc_ids.reserve(doc_rows.size());
    for (const auto& entry : doc_rows) {
        doc_ids.insert(entry.first);
        const auto it = db_rows.find(entry.first);
        if (it == db_rows.end() || it->second != entry.second) {
            out.push_back(entry.first);
        }
    }
    for (const auto& id : db_order) {
        if (doc_ids.count(id) == 0) out.push_back(id);
    }
    return DataError(ErrorCode::Ok, "");
}

// Set equality over row tuples (Python compares sets of tuples).
bool val_set_equal(const std::vector<std::vector<Val>>& a,
                   const std::vector<std::vector<Val>>& b) {
    auto contains = [](const std::vector<std::vector<Val>>& rows,
                       const std::vector<Val>& row) {
        for (const auto& candidate : rows) {
            if (candidate == row) return true;
        }
        return false;
    };
    auto distinct_count = [](const std::vector<std::vector<Val>>& rows) {
        std::size_t count = 0;
        for (std::size_t i = 0; i < rows.size(); ++i) {
            bool first = true;
            for (std::size_t j = 0; j < i; ++j) {
                if (rows[j] == rows[i]) {
                    first = false;
                    break;
                }
            }
            if (first) ++count;
        }
        return count;
    };
    if (distinct_count(a) != distinct_count(b)) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        bool first = true;
        for (std::size_t j = 0; j < i; ++j) {
            if (a[j] == a[i]) {
                first = false;
                break;
            }
        }
        if (first && !contains(b, a[i])) return false;
    }
    return true;
}

// Tag-association drift (db.py:2359-2382). Emulates `group_concat(tag_id)`
// + split(",") + discard(""): a tag id containing "," misreads IDENTICALLY
// on both sides, preserving behavioral parity with Python (R1 ⑤-6).
DataError diff_tag_links(Database& db, const char* table,
                         const char* owner_column, const OwnerTagIndex& doc_side,
                         std::vector<std::string>& out_bucket) {
    out_bucket.clear();
    std::string sql = "SELECT ";
    sql += owner_column;
    sql += ", tag_id FROM ";
    sql += table;
    Stmt query(db, sql);
    if (!query.ok()) return query.error();
    std::unordered_map<std::string, std::vector<std::string>> db_links;
    std::vector<std::string> db_order;
    while (query.step()) {
        const std::string owner = query.col_text(0);
        if (db_links.find(owner) == db_links.end()) {
            db_order.push_back(owner);
            db_links.emplace(owner, std::vector<std::string>{});
        }
        db_links[owner].push_back(query.col_text(1));
    }
    if (!query.ok()) return query.error();
    auto db_set_for = [&](const std::string& owner) {
        std::set<std::string> result;
        std::string joined;
        const auto it = db_links.find(owner);
        if (it != db_links.end()) {
            for (std::size_t i = 0; i < it->second.size(); ++i) {
                if (i > 0) joined += ',';
                joined += it->second[i];
            }
        }
        std::size_t start = 0;
        while (start <= joined.size()) {
            const std::size_t comma = joined.find(',', start);
            const std::string token =
                joined.substr(start, comma == std::string::npos
                                         ? std::string::npos
                                         : comma - start);
            if (!token.empty()) result.insert(token);
            if (comma == std::string::npos) break;
            start = comma + 1;
        }
        return result;
    };
    const std::set<std::string> kEmpty;
    for (const auto& owner : doc_side.owners) {
        const auto it = doc_side.tags_of.find(owner);
        const std::set<std::string> expected =
            it != doc_side.tags_of.end()
                ? std::set<std::string>(it->second.begin(), it->second.end())
                : std::set<std::string>{};
        if (db_set_for(owner) != expected) out_bucket.push_back(owner);
    }
    for (const auto& owner : db_order) {  // db-only owners
        if (doc_side.tags_of.count(owner) != 0) continue;
        if (db_set_for(owner) != kEmpty) out_bucket.push_back(owner);
    }
    return DataError(ErrorCode::Ok, "");
}

}  // namespace

// ==== DirtySet (db.py:756-829) ==============================================

namespace {

void mark_id(std::vector<std::string>& bucket, std::string_view id) {
    for (const auto& existing : bucket) {
        if (existing == id) return;  // idempotent; first-seen position kept
    }
    bucket.emplace_back(id);
}

void merge_bucket(std::vector<std::string>& self,
                  const std::vector<std::string>& other) {
    std::unordered_set<std::string> seen(self.begin(), self.end());
    for (const auto& id : other) {
        if (seen.insert(id).second) self.push_back(id);
    }
}

}  // namespace

void DirtySet::mark_asset(std::string_view id) { mark_id(assets, id); }
void DirtySet::mark_version(std::string_view id) { mark_id(versions, id); }
void DirtySet::mark_run(std::string_view id) { mark_id(runs, id); }
void DirtySet::mark_tag(std::string_view id) { mark_id(tags, id); }
void DirtySet::mark_model(std::string_view id) { mark_id(models, id); }
void DirtySet::mark_model_version(std::string_view id) {
    mark_id(model_versions, id);
}
void DirtySet::mark_asset_tags(std::string_view owner_id) {
    mark_id(asset_tags, owner_id);
}
void DirtySet::mark_version_tags(std::string_view owner_id) {
    mark_id(version_tags, owner_id);
}

// First-seen order, self before other (db.py DirtySet.merge).
void DirtySet::merge(const DirtySet& other) {
    merge_bucket(assets, other.assets);
    merge_bucket(versions, other.versions);
    merge_bucket(runs, other.runs);
    merge_bucket(tags, other.tags);
    merge_bucket(models, other.models);
    merge_bucket(model_versions, other.model_versions);
    merge_bucket(asset_tags, other.asset_tags);
    merge_bucket(version_tags, other.version_tags);
}

bool DirtySet::is_empty() const {
    return assets.empty() && versions.empty() && runs.empty() &&
           tags.empty() && models.empty() && model_versions.empty() &&
           asset_tags.empty() && version_tags.empty();
}

// ==== apply_changes (db.py:1951-2177) =======================================

DataError apply_changes(Database& db, const CatalogDocument& document,
                        const DirtySet& dirty,
                        const ApplyChangesOptions& options) {
    if (!db.table_exists("sync_state")) {
        // Schema-less store (deleted mid-session, or a zero-byte file left
        // by a failed flush): fall back to a full rewrite from the document
        // — the canonical truth. db.py 1977-1983 parity: write_all →
        // rebuild's two attempts + reset self-heal (Wave4 fix V1-P1-2);
        // no CAS on the rebuild path.
        return rebuild_after_schema_loss(db, document);
    }
    // O(Δ) lookups with Python `or {}` fallback semantics: a null OR EMPTY
    // map falls back to the full document scan (an empty dict is falsy in
    // Python); a non-empty map is used as-is — a dirty id missing from it
    // reads as a delete, exactly like Python's map.get(id) → None.
    // Duplicated document ids: last one wins (Python dict comprehension).
    std::unordered_map<std::string, const DataAsset*> asset_by_id;
    std::unordered_map<std::string, const DataVersion*> version_by_id;
    std::unordered_map<std::string, const DataRun*> run_by_id;
    if (options.lookups.assets != nullptr && !options.lookups.assets->empty()) {
        for (const auto& entry : *options.lookups.assets) {
            asset_by_id[entry.first] = entry.second;
        }
    } else {
        for (const auto& asset : document.assets) {
            asset_by_id[asset.id.str()] = &asset;
        }
    }
    if (options.lookups.versions != nullptr &&
        !options.lookups.versions->empty()) {
        for (const auto& entry : *options.lookups.versions) {
            version_by_id[entry.first] = entry.second;
        }
    } else {
        for (const auto& version : document.versions) {
            version_by_id[version.id.str()] = &version;
        }
    }
    if (options.lookups.runs != nullptr && !options.lookups.runs->empty()) {
        for (const auto& entry : *options.lookups.runs) {
            run_by_id[entry.first] = entry.second;
        }
    } else {
        for (const auto& run : document.runs) {
            run_by_id[run.id.str()] = &run;
        }
    }
    // tags and the model registry always scan (small collections).
    std::unordered_map<std::string, const Tag*> tag_by_id;
    for (const auto& tag : document.tags) tag_by_id[tag.id] = &tag;
    std::unordered_map<std::string, const Model*> model_by_id;
    for (const auto& model : document.models) model_by_id[model.id] = &model;
    std::unordered_map<std::string, const ModelVersion*> mver_by_id;
    for (const auto& mv : document.model_versions) {
        mver_by_id[mv.id] = &mv;
    }
    const OwnerTagIndex asset_tags = group_owner_tags(document.asset_tags);
    const OwnerTagIndex version_tags = group_owner_tags(document.version_tags);

    // BEGIN IMMEDIATE, then the #1220 CAS INSIDE the transaction and
    // BEFORE any write statement — the conflict path has zero write
    // amplification.
    TxnGuard txn(db);
    if (!txn.begun()) return txn.begin_error();
    DataError error = check_cas(db, options.expected_revision, kStaleSaveMessage);
    if (error.code != ErrorCode::Ok) return error;

    std::vector<std::string> ordered;

    // -- assets: delete cascades asset_tags only; versions/runs/lineage are
    //    driven by their own dirty marks (the document is the authority).
    error = ordered_ids(db, dirty.assets, "assets", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kAssetUpsertSql);
        Stmt del(db, "DELETE FROM assets WHERE id = ?");
        Stmt del_tags(db, "DELETE FROM asset_tags WHERE asset_id = ?");
        if (!upsert.ok()) return upsert.error();
        if (!del.ok()) return del.error();
        if (!del_tags.ok()) return del_tags.error();
        for (const auto& id : ordered) {
            const auto it = asset_by_id.find(id);
            if (it == asset_by_id.end() || it->second == nullptr) {
                del.text(1, id);
                del.run();
                if (!del.ok()) return del.error();
                del_tags.text(1, id);
                del_tags.run();
                if (!del_tags.ok()) return del_tags.error();
            } else {
                upsert.text(1, id);
                bind_vals(upsert, 2, asset_row(*it->second));
                upsert.run();
                if (!upsert.ok()) return upsert.error();
            }
        }
    }

    // -- versions ------------------------------------------------------------
    error = ordered_ids(db, dirty.versions, "versions", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kVersionUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& id : ordered) {
            const auto it = version_by_id.find(id);
            if (it == version_by_id.end() || it->second == nullptr) {
                error = delete_version_keep_run_edges(db, id);
                if (error.code != ErrorCode::Ok) return error;
                continue;
            }
            upsert.text(1, id);
            bind_vals(upsert, 2, version_row(*it->second));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
            error = reconcile_version_parents(db, *it->second);
            if (error.code != ErrorCode::Ok) return error;
            error = write_version_members(db, *it->second);
            if (error.code != ErrorCode::Ok) return error;
        }
    }

    // -- runs: io rewrite precedes _reconcile_run_edges (frozen order) ------
    error = ordered_ids(db, dirty.runs, "runs", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kRunUpsertSql);
        Stmt del_inputs(db, "DELETE FROM run_inputs WHERE run_id = ?");
        Stmt del_outputs(db, "DELETE FROM run_outputs WHERE run_id = ?");
        Stmt ins_input(
            db, "INSERT OR IGNORE INTO run_inputs (run_id, version_id)"
                " VALUES (?,?)");
        Stmt ins_output(
            db, "INSERT OR IGNORE INTO run_outputs (run_id, version_id)"
                " VALUES (?,?)");
        if (!upsert.ok()) return upsert.error();
        if (!del_inputs.ok()) return del_inputs.error();
        if (!del_outputs.ok()) return del_outputs.error();
        if (!ins_input.ok()) return ins_input.error();
        if (!ins_output.ok()) return ins_output.error();
        for (const auto& id : ordered) {
            const auto it = run_by_id.find(id);
            if (it == run_by_id.end() || it->second == nullptr) {
                error = delete_run_keep_version_edges(db, id);
                if (error.code != ErrorCode::Ok) return error;
                continue;
            }
            const DataRun& run = *it->second;
            upsert.text(1, id);
            bind_vals(upsert, 2, run_row(run));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
            del_inputs.text(1, id);
            del_inputs.run();
            if (!del_inputs.ok()) return del_inputs.error();
            del_outputs.text(1, id);
            del_outputs.run();
            if (!del_outputs.ok()) return del_outputs.error();
            for (const auto& vid : run.input_version_ids) {
                ins_input.text(1, id).text(2, vid.str());
                ins_input.run();
                if (!ins_input.ok()) return ins_input.error();
            }
            for (const auto& vid : run.output_version_ids) {
                ins_output.text(1, id).text(2, vid.str());
                ins_output.run();
                if (!ins_output.ok()) return ins_output.error();
            }
            error = write_run_ports(db, run);
            if (error.code != ErrorCode::Ok) return error;
            error = reconcile_run_edges(db, run);
            if (error.code != ErrorCode::Ok) return error;
        }
    }

    // -- tags: the document's object survives a legacy name collision ------
    error = ordered_ids(db, dirty.tags, "tags", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kTagUpsertSql);
        Stmt del(db, "DELETE FROM tags WHERE id = ?");
        Stmt del_asset_tags(db, "DELETE FROM asset_tags WHERE tag_id = ?");
        Stmt del_version_tags(db, "DELETE FROM version_tags WHERE tag_id = ?");
        Stmt del_collide(db, "DELETE FROM tags WHERE name = ? AND id <> ?");
        if (!upsert.ok()) return upsert.error();
        if (!del.ok()) return del.error();
        if (!del_asset_tags.ok()) return del_asset_tags.error();
        if (!del_version_tags.ok()) return del_version_tags.error();
        if (!del_collide.ok()) return del_collide.error();
        for (const auto& id : ordered) {
            const auto it = tag_by_id.find(id);
            if (it == tag_by_id.end() || it->second == nullptr) {
                del.text(1, id);
                del.run();
                if (!del.ok()) return del.error();
                del_asset_tags.text(1, id);
                del_asset_tags.run();
                if (!del_asset_tags.ok()) return del_asset_tags.error();
                del_version_tags.text(1, id);
                del_version_tags.run();
                if (!del_version_tags.ok()) return del_version_tags.error();
            } else {
                // Pre-#884 documents can carry two tags colliding under the
                // current normalizer (tags.name UNIQUE): drop the stale
                // colliding row first, the document's object is the
                // survivor.
                const std::string normalized =
                    normalize_tag_name(it->second->name);
                del_collide.text(1, normalized).text(2, id);
                del_collide.run();
                if (!del_collide.ok()) return del_collide.error();
                upsert.text(1, id);
                bind_vals(upsert, 2, tag_row(*it->second));
                upsert.run();
                if (!upsert.ok()) return upsert.error();
            }
        }
    }

    // -- tag associations: NOT _ordered — plain mark (owner) order, clear
    //    then reinsert the document's list (possibly empty).
    {
        Stmt del(db, "DELETE FROM asset_tags WHERE asset_id = ?");
        Stmt ins(db, "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id)"
                     " VALUES (?,?)");
        if (!del.ok()) return del.error();
        if (!ins.ok()) return ins.error();
        for (const auto& owner : dirty.asset_tags) {
            del.text(1, owner);
            del.run();
            if (!del.ok()) return del.error();
            const auto it = asset_tags.tags_of.find(owner);
            if (it == asset_tags.tags_of.end()) continue;
            for (const auto& tag_id : it->second) {
                ins.text(1, owner).text(2, tag_id);
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt del(db, "DELETE FROM version_tags WHERE version_id = ?");
        Stmt ins(db, "INSERT OR IGNORE INTO version_tags (version_id, tag_id)"
                     " VALUES (?,?)");
        if (!del.ok()) return del.error();
        if (!ins.ok()) return ins.error();
        for (const auto& owner : dirty.version_tags) {
            del.text(1, owner);
            del.run();
            if (!del.ok()) return del.error();
            const auto it = version_tags.tags_of.find(owner);
            if (it == version_tags.tags_of.end()) continue;
            for (const auto& tag_id : it->second) {
                ins.text(1, owner).text(2, tag_id);
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }

    // -- models / model_versions (no cascades) -------------------------------
    error = ordered_ids(db, dirty.models, "models", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kModelUpsertSql);
        Stmt del(db, "DELETE FROM models WHERE id = ?");
        if (!upsert.ok()) return upsert.error();
        if (!del.ok()) return del.error();
        for (const auto& id : ordered) {
            const auto it = model_by_id.find(id);
            if (it == model_by_id.end() || it->second == nullptr) {
                del.text(1, id);
                del.run();
                if (!del.ok()) return del.error();
            } else {
                upsert.text(1, id);
                bind_vals(upsert, 2, model_row(*it->second));
                upsert.run();
                if (!upsert.ok()) return upsert.error();
            }
        }
    }
    error = ordered_ids(db, dirty.model_versions, "model_versions", ordered);
    if (error.code != ErrorCode::Ok) return error;
    {
        Stmt upsert(db, kModelVersionUpsertSql);
        Stmt del(db, "DELETE FROM model_versions WHERE id = ?");
        if (!upsert.ok()) return upsert.error();
        if (!del.ok()) return del.error();
        for (const auto& id : ordered) {
            const auto it = mver_by_id.find(id);
            if (it == mver_by_id.end() || it->second == nullptr) {
                del.text(1, id);
                del.run();
                if (!del.ok()) return del.error();
            } else {
                upsert.text(1, id);
                bind_vals(upsert, 2, model_version_row(*it->second));
                upsert.run();
                if (!upsert.ok()) return upsert.error();
            }
        }
    }

    // -- three-key stamp with document-carried values, then COMMIT ----------
    error = stamp_sync_state(db, document);
    if (error.code != ErrorCode::Ok) return error;
    return txn.commit();
}

// ==== reconcile (db.py:2313-2475) ===========================================

DataError reconcile(Database& db, const CatalogDocument& document,
                    std::optional<long long> expected_revision) {
    if (!db.table_exists("sync_state")) {
        // Deleted mid-session or schema-less: the compare below has no
        // tables to read — full rewrite from the document (db.py
        // 2327-2331: write_all → rebuild's two attempts + reset
        // self-heal, Wave4 fix V1-P1-2).
        return rebuild_after_schema_loss(db, document);
    }
    DirtySet dirty;
    DataError error = DataError(ErrorCode::Ok, "");

    // -- six-table row diff (doc order + db-only) ----------------------------
    {
        DocRows doc_rows;
        doc_rows.reserve(document.assets.size());
        for (const auto& asset : document.assets) {
            doc_rows.emplace_back(asset.id.str(), asset_row(asset));
        }
        error = diff_table(db, "assets", kAssetDiffColumns, doc_rows,
                           dirty.assets);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        DocRows doc_rows;
        doc_rows.reserve(document.versions.size());
        for (const auto& version : document.versions) {
            doc_rows.emplace_back(version.id.str(), version_row(version));
        }
        error = diff_table(db, "versions", kVersionDiffColumns, doc_rows,
                           dirty.versions);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        DocRows doc_rows;
        doc_rows.reserve(document.runs.size());
        for (const auto& run : document.runs) {
            doc_rows.emplace_back(run.id.str(), run_row(run));
        }
        error =
            diff_table(db, "runs", kRunDiffColumns, doc_rows, dirty.runs);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        DocRows doc_rows;
        doc_rows.reserve(document.tags.size());
        for (const auto& tag : document.tags) {
            doc_rows.emplace_back(tag.id, tag_row(tag));
        }
        error =
            diff_table(db, "tags", kTagDiffColumns, doc_rows, dirty.tags);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        DocRows doc_rows;
        doc_rows.reserve(document.models.size());
        for (const auto& model : document.models) {
            doc_rows.emplace_back(model.id, model_row(model));
        }
        error = diff_table(db, "models", kModelDiffColumns, doc_rows,
                           dirty.models);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        DocRows doc_rows;
        doc_rows.reserve(document.model_versions.size());
        for (const auto& mv : document.model_versions) {
            doc_rows.emplace_back(mv.id, model_version_row(mv));
        }
        error = diff_table(db, "model_versions", kModelVersionDiffColumns,
                           doc_rows, dirty.model_versions);
        if (error.code != ErrorCode::Ok) return error;
    }

    // -- tag association drift ------------------------------------------------
    {
        const OwnerTagIndex doc_asset_tags =
            group_owner_tags(document.asset_tags);
        error = diff_tag_links(db, "asset_tags", "asset_id", doc_asset_tags,
                               dirty.asset_tags);
        if (error.code != ErrorCode::Ok) return error;
    }
    {
        const OwnerTagIndex doc_version_tags =
            group_owner_tags(document.version_tags);
        error = diff_tag_links(db, "version_tags", "version_id",
                               doc_version_tags, dirty.version_tags);
        if (error.code != ErrorCode::Ok) return error;
    }

    // -- run io drift (one grouped join read; the lineage table itself is
    //    NOT diffed — the documented Python limitation) ----------------------
    std::unordered_set<std::string> marked_runs(dirty.runs.begin(),
                                                dirty.runs.end());
    auto mark_run = [&](const std::string& id) {
        if (marked_runs.insert(id).second) dirty.runs.push_back(id);
    };
    {
        std::unordered_map<std::string,
                           std::set<std::pair<std::string, std::string>>>
            db_run_io;
        Stmt query(db,
                   "SELECT ri.run_id, ri.version_id, ro.version_id FROM"
                   " run_inputs ri JOIN run_outputs ro ON ro.run_id = ri.run_id");
        if (!query.ok()) return query.error();
        while (query.step()) {
            db_run_io[query.col_text(0)].emplace(query.col_text(1),
                                                 query.col_text(2));
        }
        if (!query.ok()) return query.error();
        const std::set<std::pair<std::string, std::string>> kEmpty;
        for (const auto& run : document.runs) {
            std::set<std::pair<std::string, std::string>> expected;
            for (const auto& input : run.input_version_ids) {
                for (const auto& output : run.output_version_ids) {
                    expected.emplace(input.str(), output.str());
                }
            }
            const auto it = db_run_io.find(run.id.str());
            if ((it == db_run_io.end() ? kEmpty : it->second) != expected) {
                mark_run(run.id.str());
            }
        }
    }

    // -- run_ports drift: absent table + non-empty document ports → the
    //    STORE is what needs repair (the write path CREATEs defensively).
    {
        const bool has_ports_table = db.table_exists("run_ports");
        std::unordered_map<std::string, std::vector<std::vector<Val>>> db_ports;
        if (has_ports_table) {
            Stmt query(db,
                       "SELECT run_id, direction, role, version_id, ordinal,"
                       " required, entity_type, entity_id, note FROM run_ports");
            if (!query.ok()) return query.error();
            while (query.step()) {
                std::vector<Val> tail;
                tail.reserve(8);
                for (int c = 1; c < 9; ++c) tail.push_back(read_val(query, c));
                db_ports[query.col_text(0)].push_back(std::move(tail));
            }
            if (!query.ok()) return query.error();
        }
        const std::vector<std::vector<Val>> kEmpty;
        for (const auto& run : document.runs) {
            std::vector<std::vector<Val>> expected;
            for (const auto& port : run.input_ports) {
                const std::vector<Val> row =
                    run_port_row(run.id.str(), false, port);
                expected.emplace_back(row.begin() + 1, row.end());
            }
            for (const auto& port : run.output_ports) {
                const std::vector<Val> row =
                    run_port_row(run.id.str(), true, port);
                expected.emplace_back(row.begin() + 1, row.end());
            }
            if (!expected.empty() && !has_ports_table) {
                mark_run(run.id.str());
                continue;
            }
            const auto it = db_ports.find(run.id.str());
            if (!val_set_equal(it == db_ports.end() ? kEmpty : it->second,
                              expected)) {
                mark_run(run.id.str());
            }
        }
    }

    // -- version_members drift (same shape; None columns participate in
    //    the equality).
    {
        const bool has_members_table = db.table_exists("version_members");
        std::unordered_map<std::string, std::vector<std::vector<Val>>> db_members;
        if (has_members_table) {
            Stmt query(db,
                       "SELECT version_id, name, rel_path, member_role,"
                       " ordinal, required, sha256, size_bytes FROM"
                       " version_members");
            if (!query.ok()) return query.error();
            while (query.step()) {
                std::vector<Val> tail;
                tail.reserve(7);
                for (int c = 1; c < 8; ++c) tail.push_back(read_val(query, c));
                db_members[query.col_text(0)].push_back(std::move(tail));
            }
            if (!query.ok()) return query.error();
        }
        std::unordered_set<std::string> marked_versions(dirty.versions.begin(),
                                                        dirty.versions.end());
        const std::vector<std::vector<Val>> kEmpty;
        for (const auto& version : document.versions) {
            std::vector<std::vector<Val>> expected;
            for (const auto& member : version.members) {
                const std::vector<Val> row =
                    version_member_row(version.id.str(), member);
                expected.emplace_back(row.begin() + 1, row.end());
            }
            if (!expected.empty() && !has_members_table) {
                if (marked_versions.insert(version.id.str()).second) {
                    dirty.versions.push_back(version.id.str());
                }
                continue;
            }
            const auto it = db_members.find(version.id.str());
            if (!val_set_equal(it == db_members.end() ? kEmpty : it->second,
                              expected)) {
                if (marked_versions.insert(version.id.str()).second) {
                    dirty.versions.push_back(version.id.str());
                }
            }
        }
    }

    if (dirty.is_empty()) {
        // Still refresh the three-key stamp (the caller bumped the
        // revision) under the same CAS contract — the "同步" message
        // variant (db.py:2437-2474).
        TxnGuard txn(db);
        if (!txn.begun()) return txn.begin_error();
        error = check_cas(db, expected_revision, kStaleSyncMessage);
        if (error.code != ErrorCode::Ok) return error;
        error = stamp_sync_state(db, document);
        if (error.code != ErrorCode::Ok) return error;
        return txn.commit();
    }
    // Non-empty: the SAME writer as the dirty-set path, no lookups (the
    // diff was already O(N)).
    ApplyChangesOptions options;
    options.expected_revision = expected_revision;
    return apply_changes(db, document, dirty, options);
}

// ==== rebuild family (db.py:2477-2604 / 1471-1487 / 1042-1054) =============

DataError rebuild_once(Database& db, const CatalogDocument& document) {
    TxnGuard txn(db);
    if (!txn.begun()) return txn.begin_error();
    // Full _SCHEMA_DDL (sqlite.cpp ensure_schema, same statement list),
    // inside the transaction — strictly more atomic than Python's
    // connect-time DDL, unobservable (idempotent IF NOT EXISTS) (B-7).
    DataError error = db.ensure_schema();
    if (error.code != ErrorCode::Ok) return enrich_sqlite_code(error, db);
    for (const char* table : kDeleteOrder) {
        Stmt del(db, std::string("DELETE FROM ") + table);
        if (!del.ok()) return del.error();
        del.run();
        if (!del.ok()) return del.error();
    }
    {
        Stmt upsert(db, kAssetUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& asset : document.assets) {
            upsert.text(1, asset.id.str());
            bind_vals(upsert, 2, asset_row(asset));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
        }
    }
    {
        Stmt upsert(db, kVersionUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& version : document.versions) {
            upsert.text(1, version.id.str());
            bind_vals(upsert, 2, version_row(version));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
        }
    }
    {
        Stmt ins(db,
                 "INSERT OR IGNORE INTO version_members (version_id, name,"
                 " rel_path, member_role, ordinal, required, sha256, size_bytes)"
                 " VALUES (?,?,?,?,?,?,?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& version : document.versions) {
            for (const auto& member : version.members) {
                bind_vals(ins, 1, version_member_row(version.id.str(), member));
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        // INSERT OR IGNORE, not the upsert: a legacy document can hold two
        // tags colliding under the current normalizer (pre-#884); migration
        // must tolerate them instead of bricking project open.
        Stmt ins(db,
                 "INSERT OR IGNORE INTO tags (id, name, display_name, metadata)"
                 " VALUES (?,?,?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& tag : document.tags) {
            ins.text(1, tag.id);
            bind_vals(ins, 2, tag_row(tag));
            ins.run();
            if (!ins.ok()) return ins.error();
        }
    }
    {
        Stmt ins(db, "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id)"
                     " VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        const OwnerTagIndex index = group_owner_tags(document.asset_tags);
        for (const auto& owner : index.owners) {
            for (const auto& tag_id : index.tags_of.at(owner)) {
                ins.text(1, owner).text(2, tag_id);
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt ins(db, "INSERT OR IGNORE INTO version_tags (version_id, tag_id)"
                     " VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        const OwnerTagIndex index = group_owner_tags(document.version_tags);
        for (const auto& owner : index.owners) {
            for (const auto& tag_id : index.tags_of.at(owner)) {
                ins.text(1, owner).text(2, tag_id);
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt upsert(db, kRunUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& run : document.runs) {
            upsert.text(1, run.id.str());
            bind_vals(upsert, 2, run_row(run));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
        }
    }
    {
        Stmt ins(db,
                 "INSERT OR IGNORE INTO run_ports (run_id, direction, role,"
                 " version_id, ordinal, required, entity_type, entity_id, note)"
                 " VALUES (?,?,?,?,?,?,?,?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& run : document.runs) {
            for (const auto& port : run.input_ports) {
                bind_vals(ins, 1, run_port_row(run.id.str(), false, port));
                ins.run();
                if (!ins.ok()) return ins.error();
            }
            for (const auto& port : run.output_ports) {
                bind_vals(ins, 1, run_port_row(run.id.str(), true, port));
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt ins(db, "INSERT OR IGNORE INTO run_inputs (run_id, version_id)"
                     " VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& run : document.runs) {
            for (const auto& vid : run.input_version_ids) {
                ins.text(1, run.id.str()).text(2, vid.str());
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt ins(db, "INSERT OR IGNORE INTO run_outputs (run_id, version_id)"
                     " VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        for (const auto& run : document.runs) {
            for (const auto& vid : run.output_version_ids) {
                ins.text(1, run.id.str()).text(2, vid.str());
                ins.run();
                if (!ins.ok()) return ins.error();
            }
        }
    }
    {
        Stmt upsert(db, kModelUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& model : document.models) {
            upsert.text(1, model.id);
            bind_vals(upsert, 2, model_row(model));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
        }
    }
    {
        Stmt upsert(db, kModelVersionUpsertSql);
        if (!upsert.ok()) return upsert.error();
        for (const auto& mv : document.model_versions) {
            upsert.text(1, mv.id);
            bind_vals(upsert, 2, model_version_row(mv));
            upsert.run();
            if (!upsert.ok()) return upsert.error();
        }
    }
    {
        // Materialized lineage: explicit parents (document order) plus the
        // run input×output cross product, seen-deduped (db.py:2576-2595).
        Stmt ins(db,
                 "INSERT OR IGNORE INTO lineage (parent_version_id,"
                 " child_version_id) VALUES (?,?)");
        if (!ins.ok()) return ins.error();
        std::set<std::pair<std::string, std::string>> seen;
        for (const auto& version : document.versions) {
            for (const auto& parent : version.parent_version_ids) {
                if (seen.emplace(parent.str(), version.id.str()).second) {
                    ins.text(1, parent.str()).text(2, version.id.str());
                    ins.run();
                    if (!ins.ok()) return ins.error();
                }
            }
        }
        for (const auto& run : document.runs) {
            for (const auto& input : run.input_version_ids) {
                for (const auto& output : run.output_version_ids) {
                    if (seen.emplace(input.str(), output.str()).second) {
                        ins.text(1, input.str()).text(2, output.str());
                        ins.run();
                        if (!ins.ok()) return ins.error();
                    }
                }
            }
        }
    }
    error = stamp_sync_state(db, document);
    if (error.code != ErrorCode::Ok) return error;
    return txn.commit();
}

void reset_store_files(const std::filesystem::path& db_path) {
    // Best-effort: db + "-journal"/"-wal"/"-shm", every OS error swallowed.
    // The caller must have closed all handles first (WAL unlink semantics).
    for (const char* suffix : {"", "-journal", "-wal", "-shm"}) {
        std::error_code ec;
        std::filesystem::path file = db_path;
        file += suffix;  // native string append: Path(f"{db_path}{suffix}")
        std::filesystem::remove(file, ec);
    }
}

DataError rebuild_store(const std::filesystem::path& db_path,
                        const CatalogDocument& document) {
    std::error_code ec;
    const std::filesystem::path parent = db_path.parent_path();
    if (!parent.empty()) std::filesystem::create_directories(parent, ec);
    for (int attempt = 0; attempt < 2; ++attempt) {
        auto opened = Database::open(db_path, SqliteOpenMode::Create);
        if (!opened.is_ok()) {
            DataError error = opened.error();
            if (attempt == 0 && is_selfheal_sqlite(error)) {
                reset_store_files(db_path);
                continue;
            }
            return error;
        }
        Database db = std::move(opened.value());
        DataError error = rebuild_once(db, document);
        if (error.code == ErrorCode::Ok) return error;
        if (attempt == 0 && is_selfheal_sqlite(error)) {
            db.close();  // release handles before unlink
            reset_store_files(db_path);
            continue;
        }
        return error;
    }
    return DataError(ErrorCode::CorruptDatabase, "rebuild failed after retry");
}

// ==== sync / is_fresh / revision (db.py:1449-1467 / 1427-1447 / 1210-1218) =

domain::Result<bool> sync_store(Database& db,
                                const std::filesystem::path& db_path,
                                const CatalogDocument& document) {
    if (is_fresh(db, document)) {
        return domain::Result<bool>(false);  // unchanged
    }
    DataError error = reconcile(db, document, std::nullopt);
    if (error.code != ErrorCode::Ok) {
        // CatalogStaleWriteError is an OSError in Python: sync's
        // `except sqlite3.DatabaseError` never sees it — always pass
        // through, never self-heal.
        if (is_stale_write(error)) return error;
        if (is_selfheal_sqlite(error)) {
            // Python reset() closes the pool first; this caller's handle is
            // left CLOSED here too (post-reset lazy reconnect, db.py:1048).
            db.close();
            reset_store_files(db_path);
            error = rebuild_store(db_path, document);
            if (error.code != ErrorCode::Ok) return error;
        } else {
            return error;
        }
    }
    return domain::Result<bool>(true);
}

bool is_fresh(Database& db, const CatalogDocument& document) {
    const std::optional<long long> revision = read_revision(db);
    if (!revision.has_value() || *revision != document.catalog_revision) {
        return false;  // None != any int (db.py revision() None semantics)
    }
    const std::optional<long long> schema =
        read_sync_state(db, "schema_version");
    if (!schema.has_value() || *schema != document.schema_version) {
        return false;
    }
    // Index-layout gate: EQUALITY, not a floor — a different gate than
    // load_document's "≥5" (db.py:292-310 pins the conflation data-loss
    // trap; is_fresh decides staleness, load_document decides usability).
    const std::optional<long long> layout =
        read_sync_state(db, "index_schema_version");
    return layout.has_value() && *layout == kStoreSchemaVersion;
}

std::optional<long long> read_sync_state(Database& db, std::string_view key) {
    // nullopt = the unified "missing / unparsable / unreadable" sentinel
    // (Python _read_sync_state returns None on a failed read; the handle is
    // open by contract, so a failed query is the unreadable branch).
    Stmt query(db, "SELECT value FROM sync_state WHERE key = ?");
    if (!query.ok()) return std::nullopt;
    query.text(1, key);
    if (!query.step()) return std::nullopt;  // no row, or failed step
    return parse_python_int(query.col_text(0));
}

std::optional<long long> read_revision(Database& db) {
    return read_sync_state(db, "catalog_revision");
}

}  // namespace pwb::catalog
