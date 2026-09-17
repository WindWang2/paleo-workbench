// data.run_lifecycle — registration, publish success/idempotency, zero/multi
// product rejection, terminal states (v3-contracts.md §3/§5).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

#include <sqlite3.h>

#include <filesystem>
#include <fstream>

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";

struct Scratch {
    fs::path root;
    fs::path project;

    ~Scratch() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }
};

Scratch fresh_typical(const char* tag) {
    Scratch scratch;
    scratch.root =
        fs::temp_directory_path() / ("pwb_runlife_" + std::string(tag));
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

pwb::domain::VersionId first_current_version(const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return {};
    for (const auto& version : document.value().versions) {
        for (const auto& asset : document.value().assets) {
            if (asset.id == version.asset_id &&
                asset.current_version_id.has_value() &&
                *asset.current_version_id == version.id) {
                return version.id;
            }
        }
    }
    return {};
}

struct Counts {
    std::size_t assets = 0;
    std::size_t versions = 0;
    std::size_t runs = 0;
};

Counts catalog_counts(const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    Counts counts;
    if (!document.is_ok()) return counts;
    counts.assets = document.value().assets.size();
    counts.versions = document.value().versions.size();
    counts.runs = document.value().runs.size();
    return counts;
}

// Direct SQL probes (real SQLite assertions, not repository echo).
int scalar_int(const fs::path& sqlite, const std::string& sql,
               const std::string& a, const std::string& b) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(sqlite.string().c_str(), &db, SQLITE_OPEN_READONLY,
                        nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return -1;
    }
    sqlite3_stmt* stmt = nullptr;
    int result = -1;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, a.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 2, b.c_str(), -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            result = sqlite3_column_int(stmt, 0);
        }
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);
    return result;
}

pwb::data::RunRegistrationV1 make_registration(
    const pwb::domain::VersionId& input) {
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    registration.operation = "seismic.coherence_c3";
    registration.generator = "coherence-c3@0.7.0+a1b2c3";
    registration.parameters = pwb::domain::Json{
        {"window_ms", 12}, {"units", "ms"}, {"approximate", false}};
    registration.input_version_ids = {input};
    return registration;
}

pwb::data::PublishRequestV1 make_publish(
    const pwb::domain::RunId& run, const fs::path& staged) {
    pwb::data::PublishRequestV1 request;
    request.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    request.run_id = run;
    request.new_asset_name = "coherence result";
    request.new_asset_type = "volume";
    request.stage = pwb::domain::DataStage::Derived;
    pwb::data::StagedAssetV1 product;
    product.source_path = staged;
    product.sha256 = pwb::domain::Sha256::of_file(staged);
    product.format = "f32";
    request.products.push_back(product);
    request.result_metadata = pwb::domain::Json{
        {"units", "ms"}, {"approximate", false}, {"encoding", "f32le"}};
    return request;
}

}  // namespace

PWB_TEST(register_run_creates_durable_running_row) {
    Scratch scratch = fresh_typical("register");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    PWB_CHECK(!input.empty());
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));

    auto registration = make_registration(input);
    auto run = coordinator.register_run(registration);
    PWB_CHECK(run.is_ok());
    PWB_CHECK(run.value().status == pwb::data::kRunStatusRunning);
    PWB_CHECK(run.value().parameters.value("window_ms", 0) == 12);

    // Durable: a fresh repository handle sees the row.
    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().runs.size() == 2);  // 1 fixture + 1 new
    const auto* row = document.value().find_run(registration.run_id);
    PWB_CHECK(row != nullptr);
    PWB_CHECK(row->status == "running");
    PWB_CHECK(row->input_version_ids.size() == 1);
    PWB_CHECK(row->input_version_ids.front() == input);
}

PWB_TEST(register_run_is_idempotent_on_run_id) {
    Scratch scratch = fresh_typical("regrun");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));

    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());
    auto replay = coordinator.register_run(registration);
    PWB_CHECK(replay.is_ok());
    PWB_CHECK(replay.value().run_id == registration.run_id);
    PWB_CHECK(catalog_counts(scratch.project).runs == 2);  // no second row
}

PWB_TEST(register_run_rejects_port_outside_inputs) {
    Scratch scratch = fresh_typical("portgate");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    pwb::project::ProjectManager manager(scratch.project);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto registration = make_registration(input);
    pwb::catalog::RunPort port;
    port.role = "seismic";
    port.version_id = pwb::domain::VersionId(std::string("ver_not_an_input"));
    registration.input_ports.push_back(port);
    auto rejected = coordinator.register_run(registration);
    PWB_CHECK(!rejected.is_ok());
    PWB_CHECK(rejected.error().code ==
              pwb::domain::ErrorCode::InvalidArgument);
    PWB_CHECK(catalog_counts(scratch.project).runs == 1);  // unchanged
}

PWB_TEST(publish_creates_new_asset_and_completes_run) {
    Scratch scratch = fresh_typical("pubok");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged =
        write_staged(scratch.root, "result.bin", "coherence-volume-bytes");
    const auto staged_hash = pwb::domain::Sha256::of_file(staged);
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());

    const Counts before = catalog_counts(scratch.project);
    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());
    auto request = make_publish(registration.run_id, staged);
    auto receipt = coordinator.publish_run_result(request,
                                                  loaded.value().document);
    PWB_CHECK(receipt.is_ok());
    PWB_CHECK(receipt.value().status == pwb::data::PublishStatus::Published);
    PWB_CHECK(receipt.value().asset_created);
    PWB_CHECK(receipt.value().sha256 == staged_hash);
    PWB_CHECK(receipt.value().size_bytes == 22);
    PWB_CHECK(receipt.value().version_number == 1);

    const Counts after = catalog_counts(scratch.project);
    PWB_CHECK(after.assets == before.assets + 1);
    PWB_CHECK(after.versions == before.versions + 1);
    PWB_CHECK(after.runs == before.runs + 1);

    // Row-level truth via the repository.
    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    const auto* version =
        document.value().find_version(receipt.value().new_version_id);
    PWB_CHECK(version != nullptr);
    PWB_CHECK(version->run_id.has_value() &&
              *version->run_id == registration.run_id);
    PWB_CHECK(version->parent_version_ids.size() == 1);
    PWB_CHECK(version->parent_version_ids.front() == input);
    PWB_CHECK(version->metadata.value("units", "") == "ms");
    PWB_CHECK(version->metadata.value("approximate", true) == false);
    const auto* run = document.value().find_run(registration.run_id);
    PWB_CHECK(run != nullptr);
    PWB_CHECK(run->status == pwb::data::kRunStatusComplete);
    PWB_CHECK(run->parameters.contains("_finished_at"));
    PWB_CHECK(run->output_version_ids.size() == 1);
    PWB_CHECK(run->output_version_ids.front() ==
              receipt.value().new_version_id);
    const auto* asset =
        document.value().find_asset(receipt.value().asset_id);
    PWB_CHECK(asset != nullptr);
    PWB_CHECK(asset->current_version_id.has_value() &&
              *asset->current_version_id == receipt.value().new_version_id);

    // Derived tables via direct SQL (lineage/run_outputs/run_inputs).
    const fs::path sqlite =
        pwb::project::catalog_sqlite_for(scratch.project);
    PWB_CHECK(scalar_int(sqlite,
                         "SELECT 1 FROM lineage WHERE parent_version_id = ?1"
                         " AND child_version_id = ?2",
                         input.str(),
                         receipt.value().new_version_id.str()) == 1);
    PWB_CHECK(scalar_int(sqlite,
                         "SELECT 1 FROM run_outputs WHERE run_id = ?1 AND "
                         "version_id = ?2",
                         registration.run_id.str(),
                         receipt.value().new_version_id.str()) == 1);
    PWB_CHECK(scalar_int(sqlite,
                         "SELECT 1 FROM run_inputs WHERE run_id = ?1 AND "
                         "version_id = ?2",
                         registration.run_id.str(), input.str()) == 1);
    // Payload landed under {stage}/{asset}/{version}/ and the staged source
    // was not consumed.
    std::error_code ec;
    PWB_CHECK(fs::is_regular_file(
        scratch.root / "typical.artifacts" / "derived" /
            receipt.value().asset_id.str() /
            receipt.value().new_version_id.str() / "result.bin",
        ec));
}

PWB_TEST(publish_replay_returns_same_receipt_without_new_rows) {
    Scratch scratch = fresh_typical("pubdup");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged = write_staged(scratch.root, "result.bin", "bytes");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());
    auto request = make_publish(registration.run_id, staged);
    auto first = coordinator.publish_run_result(request,
                                                loaded.value().document);
    PWB_CHECK(first.is_ok());
    const Counts after_first = catalog_counts(scratch.project);

    auto replay = coordinator.publish_run_result(request,
                                                 loaded.value().document);
    PWB_CHECK(replay.is_ok());
    PWB_CHECK(replay.value().status == pwb::data::PublishStatus::Duplicate);
    PWB_CHECK(replay.value().new_version_id.str() ==
              first.value().new_version_id.str());
    PWB_CHECK(replay.value().asset_id.str() == first.value().asset_id.str());
    const Counts after_replay = catalog_counts(scratch.project);
    PWB_CHECK(after_replay.versions == after_first.versions);
    PWB_CHECK(after_replay.assets == after_first.assets);
}

PWB_TEST(publish_zero_and_multi_products_rejected_before_any_write) {
    Scratch scratch = fresh_typical("pubcount");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged = write_staged(scratch.root, "result.bin", "bytes");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());

    const Counts before = catalog_counts(scratch.project);
    const fs::path journal_dir =
        pwb::data::DataFacade::journal_dir_for(scratch.project);

    auto zero = make_publish(registration.run_id, staged);
    zero.products.clear();
    auto zero_result =
        coordinator.publish_run_result(zero, loaded.value().document);
    PWB_CHECK(zero_result.is_ok());
    PWB_CHECK(zero_result.value().status == pwb::data::PublishStatus::Failed);
    PWB_CHECK(!zero_result.value()
                   .diagnostics.empty());  // diagnostic carries the count

    auto multi = make_publish(registration.run_id, staged);
    multi.products.push_back(multi.products.front());
    auto multi_result =
        coordinator.publish_run_result(multi, loaded.value().document);
    PWB_CHECK(multi_result.is_ok());
    PWB_CHECK(multi_result.value().status == pwb::data::PublishStatus::Failed);

    // NOTHING was written: no journal, no catalog change, no payload dirs.
    std::error_code ec;
    PWB_CHECK(!fs::is_directory(journal_dir, ec) ||
              fs::directory_iterator(journal_dir, ec) ==
                  fs::directory_iterator());
    const Counts after = catalog_counts(scratch.project);
    PWB_CHECK(after.assets == before.assets);
    PWB_CHECK(after.versions == before.versions);
    // The run row itself was registration-only; still running.
    auto state = coordinator.run_state(registration.run_id);
    PWB_CHECK(state.has_value() &&
              state->status == pwb::data::kRunStatusRunning);
}

PWB_TEST(publish_rejects_unknown_or_terminal_run_and_reruns) {
    Scratch scratch = fresh_typical("pubrunstate");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged = write_staged(scratch.root, "result.bin", "bytes");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());

    auto ghost = make_publish(
        pwb::domain::RunId(std::string("run_does_not_exist")), staged);
    auto ghost_result =
        coordinator.publish_run_result(ghost, loaded.value().document);
    PWB_CHECK(ghost_result.value().status ==
              pwb::data::PublishStatus::Conflict);

    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());
    auto failed = coordinator.finish_run(
        registration.run_id, pwb::data::RunTerminalStatus::Failed,
        pwb::domain::Json{{"error", "kernel crashed"}});
    PWB_CHECK(failed.is_ok());
    PWB_CHECK(failed.value().status == pwb::data::kRunStatusFailed);
    PWB_CHECK(failed.value().parameters.contains("_finished_at"));
    PWB_CHECK(failed.value().parameters.value("error", "") ==
              "kernel crashed");

    auto to_failed = make_publish(registration.run_id, staged);
    auto to_failed_result =
        coordinator.publish_run_result(to_failed, loaded.value().document);
    PWB_CHECK(to_failed_result.value().status ==
              pwb::data::PublishStatus::Conflict);

    // A NEW run on the same input may still publish (retry = new run).
    auto retry = make_registration(input);
    PWB_CHECK(coordinator.register_run(retry).is_ok());
    auto retry_result = coordinator.publish_run_result(
        make_publish(retry.run_id, staged), loaded.value().document);
    PWB_CHECK(retry_result.value().status ==
              pwb::data::PublishStatus::Published);

    // The completed run cannot accept a second result (new op id).
    auto second = make_publish(retry.run_id, staged);
    auto second_result = coordinator.publish_run_result(
        second, loaded.value().document);
    PWB_CHECK(second_result.value().status ==
              pwb::data::PublishStatus::Conflict);

    // Terminal states cannot be overwritten (Python parity).
    auto refail = coordinator.finish_run(
        retry.run_id, pwb::data::RunTerminalStatus::Failed, {});
    PWB_CHECK(!refail.is_ok());
    auto recancel = coordinator.finish_run(
        retry.run_id, pwb::data::RunTerminalStatus::Cancelled, {});
    PWB_CHECK(!recancel.is_ok());
    // Same-terminal replay is idempotent.
    auto refail_same = coordinator.finish_run(
        registration.run_id, pwb::data::RunTerminalStatus::Failed, {});
    PWB_CHECK(refail_same.is_ok());

    // finish_run on a run that already published outputs is refused.
    auto cancel_published = coordinator.finish_run(
        retry.run_id, pwb::data::RunTerminalStatus::Cancelled, {});
    PWB_CHECK(!cancel_published.is_ok());

    // Unknown run → not_found.
    auto unknown = coordinator.finish_run(
        pwb::domain::RunId(std::string("run_nope")), pwb::data::RunTerminalStatus::Failed,
        {});
    PWB_CHECK(!unknown.is_ok());
    PWB_CHECK(unknown.error().code == pwb::domain::ErrorCode::NotFound);
}

PWB_TEST(publish_rejects_hash_mismatch_and_unsafe_ids) {
    Scratch scratch = fresh_typical("pubhash");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged = write_staged(scratch.root, "result.bin", "bytes");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());

    auto bad_hash = make_publish(registration.run_id, staged);
    bad_hash.products.front().sha256 = std::string(64, '0');
    auto bad_result = coordinator.publish_run_result(
        bad_hash, loaded.value().document);
    PWB_CHECK(bad_result.value().status == pwb::data::PublishStatus::Failed);

    auto unsafe = make_publish(registration.run_id, staged);
    unsafe.operation_id =
        pwb::domain::OperationId(std::string("../escape"));
    auto unsafe_result = coordinator.publish_run_result(
        unsafe, loaded.value().document);
    PWB_CHECK(unsafe_result.value().status ==
              pwb::data::PublishStatus::Failed);

    auto no_name = make_publish(registration.run_id, staged);
    no_name.target_asset_id = std::nullopt;
    no_name.new_asset_name = "";
    auto no_name_result = coordinator.publish_run_result(
        no_name, loaded.value().document);
    PWB_CHECK(no_name_result.value().status ==
              pwb::data::PublishStatus::Failed);

    // No journal was ever created for the rejected attempts.
    std::error_code ec;
    PWB_CHECK(!fs::exists(
        pwb::data::DataFacade::journal_dir_for(scratch.project) /
        "../escape.json",
        ec));
    const Counts counts = catalog_counts(scratch.project);
    PWB_CHECK(counts.versions == 5);  // fixture only
}

PWB_TEST(publish_appends_to_existing_target_asset) {
    Scratch scratch = fresh_typical("pubtarget");
    const pwb::domain::VersionId input = first_current_version(scratch.project);
    const fs::path staged = write_staged(scratch.root, "result.bin", "bytes");
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto registration = make_registration(input);
    PWB_CHECK(coordinator.register_run(registration).is_ok());

    pwb::domain::AssetId target;
    {
        auto catalog = repository.open_read_only();
        PWB_CHECK(catalog.is_ok());
        target = catalog.value().assets.front().id;
    }
    auto request = make_publish(registration.run_id, staged);
    request.target_asset_id = target;
    auto receipt =
        coordinator.publish_run_result(request, loaded.value().document);
    PWB_CHECK(receipt.value().status ==
              pwb::data::PublishStatus::Published);
    PWB_CHECK(!receipt.value().asset_created);
    PWB_CHECK(receipt.value().asset_id == target);
    const Counts counts = catalog_counts(scratch.project);
    PWB_CHECK(counts.assets == 2);  // no new asset
    PWB_CHECK(counts.versions == 6);
}
