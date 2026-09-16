// data.commit_coordinator — happy path, idempotent replay, base-version
// conflict, payload immutability (test-plan.md §2, Oracle O4).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

#include <fstream>

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";

struct Scratch {
    fs::path root;
    fs::path project;
};

Scratch fresh_typical(const char* tag) {
    Scratch scratch;
    scratch.root =
        fs::temp_directory_path() / ("pwb_commit_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
    const fs::path source = fs::path(PWB_DATA_FIXTURE_DIR) / "typical";
    fs::copy(source, scratch.root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    scratch.project = scratch.root / "typical.paleo.json";
    return scratch;
}

fs::path write_staged(const fs::path& root, const char* name,
                      const std::string& bytes) {
    const fs::path file = root / name;
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return file;
}

struct FixtureAsset {
    pwb::domain::AssetId asset;
    pwb::domain::VersionId current;
};

// Local aliases keep the helper independent of using-declarations.
using AssetIdAlias = pwb::domain::AssetId;
using VersionIdAlias = pwb::domain::VersionId;

FixtureAsset first_current_asset(const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    FixtureAsset out{AssetIdAlias(), VersionIdAlias()};
    if (!document.is_ok()) return out;
    for (const auto& asset : document.value().assets) {
        if (asset.current_version_id.has_value()) {
            out.asset = asset.id;
            out.current = *asset.current_version_id;
            return out;
        }
    }
    return out;
}

pwb::data::CommitRequestV1 make_request(const FixtureAsset& target,
                                        const fs::path& staged) {
    pwb::domain::seed_id_generator_for_tests(4242ULL);
    pwb::data::CommitRequestV1 request;
    request.operation_id = pwb::domain::OperationId(
        pwb::domain::make_id("op_"));
    request.asset_id = target.asset;
    request.base_version_id = target.current;
    request.stage = pwb::domain::DataStage::Derived;
    request.staged.source_path = staged;
    request.staged.format = "test";
    request.version_name = "r13-probe";
    return request;
}

}  // namespace

PWB_TEST(commit_happy_path) {
    Scratch scratch = fresh_typical("happy");
    const FixtureAsset target = first_current_asset(scratch.project);
    PWB_CHECK(!target.asset.str().empty());
    const fs::path staged =
        write_staged(scratch.root, "staged.bin", "payload-bytes-001");
    const auto staged_hash =
        pwb::domain::Sha256::of_file(staged);

    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto receipt = coordinator.commit(make_request(target, staged),
                                      loaded.value().document);
    PWB_CHECK(receipt.is_ok());
    PWB_CHECK(receipt.value().status ==
              pwb::data::CommitStatus::Committed);
    PWB_CHECK(receipt.value().version_number > 0);
    PWB_CHECK(receipt.value().sha256 == staged_hash);
    PWB_CHECK(receipt.value().size_bytes == 17);
    // Catalog current pointer advanced past the fixture base.
    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    const pwb::catalog::DataAsset* asset =
        document.value().find_asset(target.asset);
    PWB_CHECK(asset != nullptr);
    PWB_CHECK(asset->current_version_id.has_value());
    PWB_CHECK(asset->current_version_id->str() ==
              receipt.value().new_version_id.str());
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
}

PWB_TEST(duplicate_operation_replays_receipt) {
    Scratch scratch = fresh_typical("dup");
    const FixtureAsset target = first_current_asset(scratch.project);
    const fs::path staged =
        write_staged(scratch.root, "staged.bin", "payload-bytes-002");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    const auto request = make_request(target, staged);
    auto first = coordinator.commit(request, loaded.value().document);
    PWB_CHECK(first.is_ok());
    PWB_CHECK(first.value().status == pwb::data::CommitStatus::Committed);
    auto again = coordinator.commit(request, loaded.value().document);
    PWB_CHECK(again.is_ok());
    PWB_CHECK(again.value().status == pwb::data::CommitStatus::Duplicate);
    PWB_CHECK(again.value().new_version_id.str() ==
              first.value().new_version_id.str());
    // No second version row was created.
    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 6);  // 5 fixture + 1
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
}

PWB_TEST(stale_base_version_conflicts) {
    Scratch scratch = fresh_typical("conflict");
    const FixtureAsset target = first_current_asset(scratch.project);
    const fs::path staged =
        write_staged(scratch.root, "staged.bin", "payload-bytes-003");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto request = make_request(target, staged);
    request.base_version_id =
        pwb::domain::VersionId(std::string("ver_stale_base"));
    auto receipt = coordinator.commit(request, loaded.value().document);
    PWB_CHECK(receipt.is_ok());
    PWB_CHECK(receipt.value().status == pwb::data::CommitStatus::Conflict);
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
}
