// data.catalog_write — temp-store write paths: upserts, current pointer,
// single-transaction version commit, revision discipline (test-plan §2).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/catalog/trash.hpp"

namespace {

namespace fs = std::filesystem;

pwb::catalog::CatalogRepository fresh_store(const char* tag) {
    const fs::path dir =
        fs::temp_directory_path() / ("pwb_catalog_write_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(dir, ec);
    fs::create_directories(dir, ec);
    return pwb::catalog::CatalogRepository(dir / "catalog.sqlite");
}

pwb::catalog::DataAsset test_asset(const char* id) {
    pwb::catalog::DataAsset asset;
    asset.id = pwb::domain::AssetId(std::string(id));
    asset.name = "test";
    asset.created_at = "2026-09-16T08:00:00.000000+00:00";
    asset.updated_at = asset.created_at;
    return asset;
}

pwb::catalog::DataVersion test_version(const char* id, const char* asset,
                                       int number) {
    pwb::catalog::DataVersion version;
    version.id = pwb::domain::VersionId(std::string(id));
    version.asset_id = pwb::domain::AssetId(std::string(asset));
    version.version_number = number;
    version.stage = pwb::domain::DataStage::Derived;
    version.path = "derived/asset_1/ver_1/payload.bin";
    version.format = "test";
    version.created_at = "2026-09-16T08:00:00.000000+00:00";
    return version;
}

}  // namespace

PWB_TEST(write_paths_persist_and_bump_revision) {
    auto repository = fresh_store("basic");
    auto opened = repository.open_read_write();
    PWB_CHECK(opened.is_ok());
    const int base = repository.current_revision();
    PWB_CHECK(repository.upsert_asset(test_asset("asset_1")).code ==
              pwb::domain::ErrorCode::Ok);
    PWB_CHECK(repository.upsert_version(test_version("ver_1", "asset_1", 1))
                  .code == pwb::domain::ErrorCode::Ok);
    pwb::catalog::DataRun run;
    run.id = pwb::domain::RunId(std::string("run_1"));
    run.operation = "test";
    PWB_CHECK(repository.upsert_run(run).code ==
              pwb::domain::ErrorCode::Ok);
    PWB_CHECK(repository.set_current_version(
                  pwb::domain::AssetId(std::string("asset_1")),
                  pwb::domain::VersionId(std::string("ver_1")),
                  "2026-09-16T08:00:00.000000+00:00")
                  .code == pwb::domain::ErrorCode::Ok);
    PWB_CHECK(repository.current_revision() > base);

    auto reloaded = repository.open_read_only();
    PWB_CHECK(reloaded.is_ok());
    const pwb::catalog::DataAsset* asset = reloaded.value().find_asset(
        pwb::domain::AssetId(std::string("asset_1")));
    PWB_CHECK(asset != nullptr);
    PWB_CHECK(asset->current_version_id.has_value());
    PWB_CHECK(asset->current_version_id->str() == "ver_1");
}

PWB_TEST(version_commit_transaction_is_atomic) {
    auto repository = fresh_store("txn");
    PWB_CHECK(repository.open_read_write().is_ok());
    PWB_CHECK(repository.upsert_asset(test_asset("asset_9")).code ==
              pwb::domain::ErrorCode::Ok);
    pwb::domain::DataError error = repository.commit_version_transaction(
        test_version("ver_9", "asset_9", 1),
        pwb::domain::AssetId(std::string("asset_9")), std::nullopt);
    PWB_CHECK(error.code == pwb::domain::ErrorCode::Ok);
    auto reloaded = repository.open_read_only();
    PWB_CHECK(reloaded.is_ok());
    PWB_CHECK(reloaded.value().find_version(
                  pwb::domain::VersionId(std::string("ver_9"))) != nullptr);
}

PWB_TEST(name_search_is_case_folded_on_write) {
    // Python contract: assets.name_search stores normalize_asset_search_
    // name(name) (NFKC + casefold). The C++ write path folds ASCII case
    // (bounded parity — see search_fold in repository.cpp); non-ASCII
    // text stays verbatim (identical for caseless scripts like CJK).
    auto repository = fresh_store("fold");
    PWB_CHECK(repository.open_read_write().is_ok());
    pwb::catalog::DataAsset asset = test_asset("asset_fold");
    asset.name = "Seismic Attribute GRUNFELD 相带边界";
    PWB_CHECK(repository.upsert_asset(asset).code ==
              pwb::domain::ErrorCode::Ok);

    auto db = pwb::catalog::Database::open(
        fs::temp_directory_path() / "pwb_catalog_write_fold"
            / "catalog.sqlite",
        pwb::catalog::SqliteOpenMode::ReadOnly);
    PWB_CHECK(db.is_ok());
    auto statement = db.value().prepare(
        "SELECT name_search FROM assets WHERE id = 'asset_fold'");
    PWB_CHECK(statement.step());
    PWB_CHECK(statement.text(0) ==
              "seismic attribute grunfeld 相带边界");
}

PWB_TEST(duplicate_member_names_fail_the_upsert_not_silently_commit) {
    // Review C1: the bare INSERT INTO version_members aborted one statement
    // mid-loop on duplicate names, but step_done() swallowed the rc — the
    // upsert returned Ok, the revision bumped, and only the first member
    // row persisted (a durable false-Committed receipt).
    auto repository = fresh_store("dup-members");
    auto opened = repository.open_read_write();
    PWB_CHECK(opened.is_ok());
    PWB_CHECK(repository.upsert_asset(test_asset("asset_dup")).code ==
              pwb::domain::ErrorCode::Ok);
    auto version = test_version("ver_dup", "asset_dup", 1);
    pwb::catalog::VersionMember first;
    first.name = "same.bin";
    first.rel_path = "a/same.bin";
    first.member_role = "file";
    first.ordinal = 0;
    first.required = true;
    pwb::catalog::VersionMember second = first;
    second.rel_path = "b/same.bin";
    second.ordinal = 1;
    version.members = {first, second};
    // The revision BEFORE the failed upsert (read from the store, not the
    // in-memory document): a failed write must not advance it (#1458).
    const int revision_before_value = [&]() {
        auto doc = repository.open_read_only();
        return doc.is_ok() ? doc.value().catalog_revision : -1;
    }();
    const pwb::domain::DataError error = repository.upsert_version(version);
    PWB_CHECK(error.code != pwb::domain::ErrorCode::Ok);
    // The read-back must not half-materialize the member set.
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    // #1458: neither the version row nor the revision advance survived
    // the failed transaction (rollback proof).
    bool found = false;
    for (const auto& stored : document.value().versions) {
        if (stored.id.str() == "ver_dup") found = true;
    }
    PWB_CHECK(!found);
    PWB_CHECK(document.value().catalog_revision == revision_before_value);
}

PWB_TEST(re_saved_version_with_empty_members_drops_stale_rows) {
    // Review C2: the version_members DELETE was gated on !members.empty(),
    // so clearing a version's members resurrected the old rows on load.
    auto repository = fresh_store("clear-members");
    auto opened = repository.open_read_write();
    PWB_CHECK(opened.is_ok());
    PWB_CHECK(repository.upsert_asset(test_asset("asset_clr")).code ==
              pwb::domain::ErrorCode::Ok);
    auto version = test_version("ver_clr", "asset_clr", 1);
    pwb::catalog::VersionMember member;
    member.name = "keep.bin";
    member.rel_path = "keep.bin";
    member.member_role = "file";
    member.ordinal = 0;
    member.required = true;
    version.members = {member};
    PWB_CHECK(repository.upsert_version(version).code ==
              pwb::domain::ErrorCode::Ok);
    version.members.clear();
    PWB_CHECK(repository.upsert_version(version).code ==
              pwb::domain::ErrorCode::Ok);
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    for (const auto& stored : document.value().versions) {
        if (stored.id.str() != "ver_clr") continue;
        PWB_CHECK(stored.members.empty());
    }
}

// ---------------------------------------------------------------------------
// #1458: the Statement error channel is PER-STATEMENT (rc captured at the
// failing prepare/bind/step), an empty statement never silently succeeds,
// and a failed write inside a transaction leaves neither the row nor the
// revision behind.
// ---------------------------------------------------------------------------
PWB_TEST(statement_error_channel_is_per_statement_issue_1458) {
    const fs::path dir =
        fs::temp_directory_path() / "pwb_catalog_write_stmt1458";
    std::error_code ec;
    fs::remove_all(dir, ec);
    fs::create_directories(dir, ec);
    const fs::path db_file = dir / "stmt1458.sqlite";
    auto db_result = pwb::catalog::Database::open(
        db_file, pwb::catalog::SqliteOpenMode::Create);
    PWB_CHECK(db_result.is_ok());
    auto db = std::move(db_result.value());
    PWB_CHECK(db.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)").ok());
    PWB_CHECK(
        db.execute("CREATE TABLE rev (key TEXT PRIMARY KEY, value TEXT)")
            .ok());
    PWB_CHECK(db.execute(
                  "INSERT INTO rev (key, value) VALUES ('r', '7')")
                  .ok());

    // (a) a failed prepare surfaces through step_done — never Ok.
    {
        auto bad = db.prepare("INSERT INTO t (k, v VALUES (1, 'x')");
        PWB_CHECK(!bad.is_valid());
        auto error = bad.step_done();
        PWB_CHECK(!error.ok());
        PWB_CHECK(!bad.ok());
    }
    // (b) a bind failure (out-of-range parameter index) surfaces too.
    {
        auto stmt = db.prepare("INSERT INTO t (k, v) VALUES (?, ?)");
        PWB_CHECK(stmt.is_valid());
        stmt.bind(1, std::int64_t{1});
        stmt.bind(99, "nowhere");
        PWB_CHECK(!stmt.step_done().ok());
    }
    // (c) a step failure (PRIMARY KEY constraint) surfaces, the row is not
    // half-committed, and the transaction rollback keeps the revision
    // where it was.
    {
        pwb::catalog::Transaction transaction(db);
        auto first = db.prepare("INSERT INTO t (k, v) VALUES (1, 'first')");
        PWB_CHECK(first.step_done().ok());
        // Same key again: constraint fires at STEP time — the exact rc
        // the old void step_done() dropped (#1458).
        auto dup = db.prepare("INSERT INTO t (k, v) VALUES (1, 'dup')");
        auto error = dup.step_done();
        PWB_CHECK(!error.ok());
        // The failure propagates before any bump/commit decision.
        auto count = db.scalar_i64("SELECT COUNT(*) FROM t");
        PWB_CHECK(count.is_ok() && count.value() == 1);
    }  // destructor rolls back
    {
        auto count = db.scalar_i64("SELECT COUNT(*) FROM t");
        PWB_CHECK(count.is_ok() && count.value() == 0);
        auto rev = db.scalar_i64(
            "SELECT CAST(value AS INTEGER) FROM rev WHERE key = 'r'");
        PWB_CHECK(rev.is_ok() && rev.value() == 7);
    }
    // (d) the statement is reusable after a successful step_done
    // (auto-reset): bind + step_done loops share one prepared statement.
    {
        pwb::catalog::Transaction transaction(db);
        auto row = db.prepare("INSERT INTO t (k, v) VALUES (?, ?)");
        PWB_CHECK(row.is_valid());
        for (int i = 1; i <= 3; ++i) {
            row.bind(1, static_cast<std::int64_t>(i));
            row.bind(2, "loop");
            PWB_CHECK(row.step_done().ok());
        }
        PWB_CHECK(transaction.commit().ok());
        auto count = db.scalar_i64("SELECT COUNT(*) FROM t");
        PWB_CHECK(count.is_ok() && count.value() == 3);
    }
    // (e) a read loop distinguishes DONE from failure: after a clean
    // exhaust the statement is ok().
    {
        auto rows = db.prepare("SELECT k FROM t ORDER BY k");
        int seen = 0;
        while (rows.step()) ++seen;
        PWB_CHECK(seen == 3);
        PWB_CHECK(rows.ok());
        PWB_CHECK(rows.error().ok());
    }
}

// ---------------------------------------------------------------------------
// #1468: a source read failure mid-copy must fail the checkout and leave
// NO committed target — never rename a truncated temp into place. A
// directory is the deterministic injector: ifstream opens it fine on
// POSIX/Windows but the first read fails (EISDIR) setting badbit, exactly
// the mid-read error the loop used to ignore.
// ---------------------------------------------------------------------------
PWB_TEST(working_copy_source_read_error_never_commits_a_truncated_copy) {
    const fs::path dir =
        fs::temp_directory_path() / "pwb_catalog_write_wcbad";
    std::error_code ec;
    fs::remove_all(dir, ec);
    fs::create_directories(dir / "payload.d", ec);
    const fs::path project_file = dir / "wcbad.paleo.json";
    // A "payload" that opens but cannot be read.
    const fs::path unreadable_payload = dir / "payload.d";

    auto copy = pwb::catalog::create_working_copy(
        project_file, unreadable_payload, "ver_wcbad");
    PWB_CHECK(!copy.is_ok());
    // POSIX: the directory OPENS but the first read fails (EISDIR) — the
    // mid-read badbit path, error IoError. Windows (MSVC) refuses the
    // open itself — NotFound. Either way the checkout fails loudly.
#if !defined(_WIN32)
    PWB_CHECK(copy.error().code == pwb::domain::ErrorCode::IoError);
#else
    PWB_CHECK(copy.error().code == pwb::domain::ErrorCode::NotFound);
#endif

    // The working directory exists (it is created before the copy), but
    // nothing was committed into it and no temp residue survives.
    const fs::path working_dir =
        pwb::catalog::working_dir_for(project_file) / "ver_wcbad";
    PWB_CHECK(fs::is_directory(working_dir, ec));
    int entries = 0;
    for (fs::recursive_directory_iterator it(working_dir, ec), end;
         it != end && !ec; it.increment(ec)) {
        ++entries;
    }
    PWB_CHECK(entries == 0);
}
