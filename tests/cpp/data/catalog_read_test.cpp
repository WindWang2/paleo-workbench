// data.catalog_read — typical store reads table-by-table; counts match the
// oracle manifest; missing stores degrade gracefully (test-plan.md §2).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/project/paths.hpp"

namespace {

namespace fs = std::filesystem;

fs::path typical_project() {
    return fs::path(PWB_DATA_FIXTURE_DIR) / "typical" / "typical.paleo.json";
}

}  // namespace

PWB_TEST(typical_store_is_canonical) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(typical_project()));
    const pwb::catalog::StoreStatus status = repository.status();
    PWB_CHECK(status.health == pwb::catalog::StoreHealth::Canonical);
    PWB_CHECK(status.index_schema_version >= 5);
}

PWB_TEST(typical_counts_match_manifest) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(typical_project()));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    // Fixture manifest: 2 assets / 5 versions / 1 run / 2 tags.
    PWB_CHECK(document.value().assets.size() == 2);
    PWB_CHECK(document.value().versions.size() == 5);
    PWB_CHECK(document.value().runs.size() == 1);
}

PWB_TEST(asset_lookup_and_version_chain) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(typical_project()));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    const auto& assets = document.value().assets;
    PWB_CHECK(!assets.empty());
    const pwb::catalog::DataAsset* found =
        document.value().find_asset(assets[0].id);
    PWB_CHECK(found != nullptr);
    PWB_CHECK(found->id == assets[0].id);
    PWB_CHECK(document.value().next_version_number(assets[0].id) > 0);
    PWB_CHECK(document.value().find_version(
                  pwb::domain::VersionId(std::string("ver_does_not_exist"))) ==
              nullptr);
}

PWB_TEST(audit_runs_without_crash) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(typical_project()));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    const auto findings = pwb::catalog::audit_catalog(
        document.value(), typical_project(), {});
    // A generated-healthy store may still report informational findings;
    // the contract is termination + well-formed entries.
    for (const auto& finding : findings) {
        PWB_CHECK(!finding.code.empty());
        PWB_CHECK(!finding.message.empty());
    }
}

PWB_TEST(missing_store_degrades) {
    const fs::path absent =
        fs::temp_directory_path() / "pwb_no_such_catalog.sqlite";
    fs::remove(absent);
    pwb::catalog::CatalogRepository repository(absent);
    PWB_CHECK(repository.status().health ==
              pwb::catalog::StoreHealth::Missing);
    auto document = repository.open_read_only();
    PWB_CHECK(!document.is_ok());
    PWB_CHECK(document.error().code == pwb::domain::ErrorCode::NotFound);
}
