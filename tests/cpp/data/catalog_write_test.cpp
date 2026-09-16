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
