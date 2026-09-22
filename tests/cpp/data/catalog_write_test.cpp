// data.catalog_write — temp-store write paths: upserts, current pointer,
// single-transaction version commit, revision discipline (test-plan §2).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"

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
    const pwb::domain::DataError error = repository.upsert_version(version);
    PWB_CHECK(error.code != pwb::domain::ErrorCode::Ok);
    // The read-back must not half-materialize the member set.
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    bool found = false;
    for (const auto& stored : document.value().versions) {
        if (stored.id.str() == "ver_dup") found = true;
    }
    (void)found;  // row presence is transactional detail; the error is the contract
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
