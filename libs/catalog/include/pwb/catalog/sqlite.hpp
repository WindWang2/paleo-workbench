// Minimal RAII wrapper over the SQLite C API (amalgamation vendored in
// libs/data_suite/third_party/sqlite). Mirrors the Python store's
// connection discipline: WAL journal, 5000 ms busy timeout, explicit
// transactions with rollback on scope exit.
#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <sqlite3.h>

#include <memory>
#include <string>
#include <string_view>

namespace pwb::catalog {

enum class SqliteOpenMode { ReadOnly, ReadWrite, Create };

class Statement;

class Database {
public:
    Database() = default;
    ~Database();

    Database(Database&&) noexcept;
    Database& operator=(Database&&) noexcept;
    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    // Opens with journal/busy pragmas applied (WAL + 5000 ms). `create`
    // controls SQLITE_OPEN_CREATE; read-only opens never write pragmas.
    static domain::Result<Database> open(const std::filesystem::path& file,
                                         SqliteOpenMode mode);

    bool is_open() const { return db_ != nullptr; }
    sqlite3* handle() { return db_; }

    // Releases the handle early (callers use it before deleting the
    // underlying file, e.g. save-as source relocation).
    void close();

    // Executes one or more statements with no parameters (DDL etc.).
    domain::DataError execute(std::string_view sql);

    // One-shot scalar/row helpers.
    domain::Result<std::int64_t> scalar_i64(std::string_view sql);
    bool table_exists(std::string_view name);

    // Prepares a statement. On failure the returned Statement is invalid
    // AND carries the prepare error (checked via is_valid()/error()).
    Statement prepare(std::string_view sql);

    // BEGIN IMMEDIATE … COMMIT/ROLLBACK guard. Each returns the sqlite
    // error verbatim (a failed BEGIN marks the guard inactive; a failed
    // COMMIT leaves the transaction open for the destructor's rollback —
    // the error is never swallowed, #1398 leftover).
    domain::DataError begin_immediate();
    domain::DataError commit();
    domain::DataError rollback();

    // Applies the canonical v5 schema (idempotent, IF NOT EXISTS) — the
    // same statement list db.py runs per connection.
    domain::DataError ensure_schema();

    int last_extended_error() const { return last_error_; }

private:
    sqlite3* db_ = nullptr;
    int last_error_ = SQLITE_OK;
};

class Statement {
public:
    Statement() = default;
    ~Statement();

    Statement(Statement&&) noexcept;
    Statement& operator=(Statement&&) noexcept;

    void reset();
    bool is_valid() const { return stmt_ != nullptr; }

    Statement& bind(int index, std::string_view text);
    Statement& bind(int index, std::int64_t value);
    Statement& bind(int index, double value);
    Statement& bind_null(int index);

    // Advances one step. Returns true when a row is available; false when
    // the statement is done OR failed — a failed step records the error
    // (check ok()/error() after the loop; DONE leaves ok() true).
    bool step();

    // Checked non-query step (issue #1458): Ok only when the statement
    // prepared, every bind succeeded and sqlite3_step returned DONE or
    // ROW. A failed prepare (empty statement), a failed bind or a failed
    // step returns the recorded DataError instead of silently succeeding.
    // The statement is reset on success so bind + step_done loops reuse
    // one prepared statement.
    [[nodiscard]] domain::DataError step_done();

    std::string text(int column) const;
    std::int64_t int64(int column) const;
    bool is_null(int column) const;
    int column_count() const;
    std::string column_name(int column) const;

    // ---- error surface (issue #1458) ----------------------------------
    // Every failure is captured AT the failing call (prepare/bind/step
    // return codes), never re-read from the connection-level
    // sqlite3_errcode — a later successful API call overwrites that state.
    // A Statement that failed to prepare, failed to bind, or whose last
    // step returned an error is !ok() until reset.

    // True when no prepare/bind/step failure is recorded.
    bool ok() const { return error_.ok(); }
    // The first recorded failure (stable until reset or destruction).
    const domain::DataError& error() const { return error_; }

private:
    // Database::prepare is the only factory (a failed prepare passes the
    // error in so the empty statement fails loudly at step time).
    friend class Database;
    Statement(sqlite3* db, sqlite3_stmt* stmt,
              domain::DataError prepare_error = domain::DataError(
                  domain::ErrorCode::Ok, ""));

    void record_bind_error(int rc, const char* what);

    sqlite3* db_ = nullptr;
    sqlite3_stmt* stmt_ = nullptr;
    domain::DataError error_{domain::ErrorCode::Ok, ""};
};

class Transaction {
public:
    explicit Transaction(Database& db);  // BEGIN IMMEDIATE
    ~Transaction();                      // ROLLBACK unless committed
    // Returns the COMMIT error verbatim; the transaction stays open on
    // failure so the destructor rolls back (committed_ is only set on a
    // verified commit — a disk-full/BUSY commit can no longer be mistaken
    // for success).
    domain::DataError commit();
    domain::DataError rollback();

private:
    Database& db_;
    bool committed_ = false;
    bool began_ = false;
    domain::DataError begin_error_{domain::ErrorCode::Ok, ""};
};

}  // namespace pwb::catalog
