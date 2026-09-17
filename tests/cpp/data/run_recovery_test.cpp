// data.run_recovery — crash-after-durable-phase fault injection for the
// run_publish journal (v3-contracts.md §6): written→rolled_back,
// payload_staged→continued, catalog_committed/project_saved/rebound/
// run_completed→continued; pending journals block conflicting writes and
// are never deleted.
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

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
        fs::temp_directory_path() / ("pwb_runrec_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
    const fs::path source = fs::path(PWB_DATA_FIXTURE_DIR) / "typical";
    fs::copy(source, scratch.root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    scratch.project = scratch.root / "typical.paleo.json";
    return scratch;
}

fs::path write_staged(const fs::path& root, const std::string& bytes) {
    const fs::path file = root / "staged_result.bin";
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

struct Scenario {
    pwb::domain::RunId run_id;
    pwb::domain::OperationId operation_id;
    pwb::domain::VersionId base;
    fs::path staged;
};

// Registers a run and injects a fault right AFTER the given publish phase
// became durable (in-process hook — the true kill is data.crash_recovery).
Scenario crash_publish_at(const Scratch& scratch,
                          pwb::data::JournalPhase phase) {
    pwb::domain::seed_id_generator_for_tests(7700 +
        static_cast<int>(phase));
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();

    Scenario scenario;
    scenario.base = first_current_version(scratch.project);
    scenario.staged = write_staged(scratch.root, "volume-bytes");

    pwb::data::RunRegistrationV1 registration;
    scenario.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    registration.run_id = scenario.run_id;
    registration.operation = "seismic.coherence_c3";
    registration.generator = "coherence-c3@0.7.0";
    registration.input_version_ids = {scenario.base};
    PWB_CHECK(coordinator.register_run(registration).is_ok());

    pwb::data::PublishRequestV1 request;
    scenario.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    request.operation_id = scenario.operation_id;
    request.run_id = scenario.run_id;
    request.new_asset_name = "crashed result";
    request.stage = pwb::domain::DataStage::Derived;
    pwb::data::StagedAssetV1 product;
    product.source_path = scenario.staged;
    product.sha256 = pwb::domain::Sha256::of_file(scenario.staged);
    product.format = "f32";
    request.products.push_back(product);
    request.result_metadata =
        pwb::domain::Json{{"units", "ms"}, {"approximate", false}};

    coordinator.set_fault_hook(
        [phase](pwb::data::JournalPhase reached)
            -> std::optional<pwb::domain::DataError> {
            if (reached == phase) {
                return pwb::domain::DataError(
                    pwb::domain::ErrorCode::IoError,
                    "injected fault after " + std::string(to_string(reached)));
            }
            return std::nullopt;
        });
    auto receipt =
        coordinator.publish_run_result(request, loaded.value().document);
    PWB_CHECK(receipt.value().status == pwb::data::PublishStatus::Failed);
    return scenario;
}

pwb::data::RecoveryReportV1 recover_with(const fs::path& project) {
    pwb::project::ProjectManager manager(project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    return coordinator.recover(loaded.value().document);
}

}  // namespace

PWB_TEST(fault_at_written_rolls_back_and_keeps_evidence) {
    Scratch scratch = fresh_typical("wr");
    const Scenario scenario =
        crash_publish_at(scratch, pwb::data::JournalPhase::Written);
    const fs::path journal =
        pwb::data::DataFacade::journal_dir_for(scratch.project) /
        (scenario.operation_id.str() + ".json");
    std::error_code ec;
    PWB_CHECK(fs::is_regular_file(journal, ec));  // evidence exists

    auto report = recover_with(scratch.project);
    PWB_CHECK(report.rolled_back.size() == 1);
    PWB_CHECK(report.pending.empty());
    PWB_CHECK(fs::is_regular_file(journal, ec));  // never deleted

    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 5);  // nothing landed
    PWB_CHECK(document.value().assets.size() == 2);
    const auto* run = document.value().find_run(scenario.run_id);
    PWB_CHECK(run != nullptr);
    PWB_CHECK(run->status == pwb::data::kRunStatusRunning);  // honest state
    PWB_CHECK(run->output_version_ids.empty());

    // Retry the SAME operation id after rollback → a fresh attempt that
    // now succeeds end-to-end.
    {
        pwb::project::ProjectManager manager(scratch.project);
        manager.set_clock_for_tests(kClock);
        pwb::catalog::CatalogRepository repository(
            pwb::project::catalog_sqlite_for(scratch.project));
        pwb::data::CommitCoordinator coordinator(
            manager, repository,
            pwb::data::DataFacade::journal_dir_for(scratch.project));
        auto loaded = manager.load();
        pwb::data::PublishRequestV1 request;
        request.operation_id = scenario.operation_id;
        request.run_id = scenario.run_id;
        request.new_asset_name = "crashed result";
        pwb::data::StagedAssetV1 product;
        product.source_path = scenario.staged;
        product.sha256 = pwb::domain::Sha256::of_file(scenario.staged);
        product.format = "f32";
        request.products.push_back(product);
        request.result_metadata =
            pwb::domain::Json{{"units", "ms"}};
        auto receipt = coordinator.publish_run_result(
            request, loaded.value().document);
        PWB_CHECK(receipt.value().status ==
                  pwb::data::PublishStatus::Published);
    }
}

PWB_TEST(fault_at_payload_staged_resumes_to_success) {
    Scratch scratch = fresh_typical("ps");
    const Scenario scenario =
        crash_publish_at(scratch, pwb::data::JournalPhase::PayloadStaged);

    auto report = recover_with(scratch.project);
    PWB_CHECK(report.continued.size() == 1);
    PWB_CHECK(report.pending.empty());

    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 6);
    PWB_CHECK(document.value().assets.size() == 3);
    const auto* run = document.value().find_run(scenario.run_id);
    PWB_CHECK(run != nullptr);
    PWB_CHECK(run->status == pwb::data::kRunStatusComplete);
    PWB_CHECK(run->output_version_ids.size() == 1);
    const auto* version =
        document.value().find_version(run->output_version_ids.front());
    PWB_CHECK(version != nullptr);
    PWB_CHECK(version->parent_version_ids.size() == 1);
    PWB_CHECK(version->parent_version_ids.front() == scenario.base);
    std::error_code ec;
    PWB_CHECK(fs::is_regular_file(
        scratch.root / "typical.artifacts" / "derived" /
            version->asset_id.str() / version->id.str() /
            "staged_result.bin",
        ec));
}

PWB_TEST(fault_after_catalog_durability_resumes_tail) {
    for (const auto phase : {pwb::data::JournalPhase::CatalogCommitted,
                             pwb::data::JournalPhase::ProjectSaved,
                             pwb::data::JournalPhase::Rebound,
                             pwb::data::JournalPhase::RunCompleted}) {
        const char* tag = nullptr;
        switch (phase) {
            case pwb::data::JournalPhase::CatalogCommitted: tag = "cc"; break;
            case pwb::data::JournalPhase::ProjectSaved: tag = "pjs"; break;
            case pwb::data::JournalPhase::Rebound: tag = "rb"; break;
            default: tag = "rc"; break;
        }
        Scratch scratch = fresh_typical(tag);
        const Scenario scenario = crash_publish_at(scratch, phase);

        auto report = recover_with(scratch.project);
        PWB_CHECK(report.continued.size() == 1);
        PWB_CHECK(report.pending.empty());

        pwb::catalog::CatalogRepository probe(
            pwb::project::catalog_sqlite_for(scratch.project));
        auto document = probe.open_read_only();
        PWB_CHECK(document.is_ok());
        const auto* run = document.value().find_run(scenario.run_id);
        PWB_CHECK(run != nullptr);
        PWB_CHECK(run->status == pwb::data::kRunStatusComplete);
        PWB_CHECK(run->output_version_ids.size() == 1);
        PWB_CHECK(document.value().versions.size() == 6);

        // Replay after recovery → Duplicate (idempotency preserved).
        pwb::project::ProjectManager manager(scratch.project);
        manager.set_clock_for_tests(kClock);
        pwb::catalog::CatalogRepository repository(
            pwb::project::catalog_sqlite_for(scratch.project));
        pwb::data::CommitCoordinator coordinator(
            manager, repository,
            pwb::data::DataFacade::journal_dir_for(scratch.project));
        auto loaded = manager.load();
        pwb::data::PublishRequestV1 request;
        request.operation_id = scenario.operation_id;
        request.run_id = scenario.run_id;
        pwb::data::StagedAssetV1 product;
        product.source_path = scenario.staged;
        product.format = "f32";
        request.products.push_back(product);
        auto replay = coordinator.publish_run_result(
            request, loaded.value().document);
        PWB_CHECK(replay.value().status ==
                  pwb::data::PublishStatus::Duplicate);
        PWB_CHECK(document.value().versions.size() == 6);
    }
}

PWB_TEST(pending_journal_blocks_conflicting_writes) {
    Scratch scratch = fresh_typical("pending");
    const Scenario scenario =
        crash_publish_at(scratch, pwb::data::JournalPhase::PayloadStaged);

    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());

    // finish_run on the held run → refused.
    auto finish = coordinator.finish_run(
        scenario.run_id, pwb::data::RunTerminalStatus::Cancelled, {});
    PWB_CHECK(!finish.is_ok());
    PWB_CHECK(finish.error().code ==
              pwb::domain::ErrorCode::RecoveryRequired);

    // A different publish against the same run → refused.
    pwb::data::PublishRequestV1 clash;
    clash.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    clash.run_id = scenario.run_id;
    clash.new_asset_name = "clash";
    pwb::data::StagedAssetV1 product;
    product.source_path = scenario.staged;
    product.format = "f32";
    clash.products.push_back(product);
    auto clash_result =
        coordinator.publish_run_result(clash, loaded.value().document);
    PWB_CHECK(clash_result.value().status ==
              pwb::data::PublishStatus::Failed);
    bool blocked = false;
    for (const auto& diagnostic : clash_result.value().diagnostics) {
        if (diagnostic.code == "recovery_required") blocked = true;
    }
    PWB_CHECK(blocked);

    // Nothing changed while blocked.
    pwb::catalog::CatalogRepository probe(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = probe.open_read_only();
    PWB_CHECK(document.value().versions.size() == 5);

    // Recovery clears the gate; the clash operation (different id) now gets
    // an honest per-state answer — the run is complete, so a new publish
    // against it conflicts, NOT a silent duplicate hit.
    auto report = coordinator.recover(loaded.value().document);
    PWB_CHECK(report.continued.size() == 1);
    auto retry =
        coordinator.publish_run_result(clash, loaded.value().document);
    PWB_CHECK(retry.value().status == pwb::data::PublishStatus::Conflict);
    auto after = probe.open_read_only();
    PWB_CHECK(after.value().versions.size() == 6);
}

PWB_TEST(edit_commit_blocked_by_pending_publish_journal) {
    Scratch scratch = fresh_typical("editpend");
    // Crash a publish that targets an EXISTING asset so the edit-commit
    // overlap check has a shared asset id.
    pwb::domain::seed_id_generator_for_tests(9911);
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());

    const fs::path staged = write_staged(scratch.root, "vol");
    const pwb::domain::VersionId base = first_current_version(scratch.project);
    pwb::domain::AssetId target;
    pwb::domain::RunId run(pwb::domain::make_id("run_"));
    {
        pwb::data::RunRegistrationV1 registration;
        registration.run_id = run;
        registration.operation = "op";
        registration.input_version_ids = {base};
        PWB_CHECK(coordinator.register_run(registration).is_ok());
        auto catalog = repository.open_read_only();
        for (const auto& asset : catalog.value().assets) {
            target = asset.id;  // any asset
        }
    }
    pwb::data::PublishRequestV1 publish;
    publish.operation_id = pwb::domain::OperationId(pwb::domain::make_id("op_"));
    publish.run_id = run;
    publish.target_asset_id = target;
    pwb::data::StagedAssetV1 product;
    product.source_path = staged;
    product.format = "f32";
    publish.products.push_back(product);
    coordinator.set_fault_hook(
        [](pwb::data::JournalPhase reached)
            -> std::optional<pwb::domain::DataError> {
            if (reached == pwb::data::JournalPhase::PayloadStaged) {
                return pwb::domain::DataError(
                    pwb::domain::ErrorCode::IoError, "injected");
            }
            return std::nullopt;
        });
    auto crashed =
        coordinator.publish_run_result(publish, loaded.value().document);
    PWB_CHECK(crashed.value().status == pwb::data::PublishStatus::Failed);

    // Edit commit against the SAME asset is blocked until recovery.
    pwb::data::CommitRequestV1 edit;
    edit.operation_id = pwb::domain::OperationId(pwb::domain::make_id("op_"));
    edit.asset_id = target;
    edit.base_version_id = base;
    edit.staged.source_path = staged;
    edit.staged.format = "bin";
    auto blocked_receipt =
        coordinator.commit(edit, loaded.value().document);
    PWB_CHECK(blocked_receipt.value().status == pwb::data::CommitStatus::Failed);
    bool saw_gate = false;
    for (const auto& diagnostic : blocked_receipt.value().diagnostics) {
        if (diagnostic.code == "recovery_required") saw_gate = true;
    }
    PWB_CHECK(saw_gate);

    auto report = coordinator.recover(loaded.value().document);
    PWB_CHECK(report.continued.size() == 1);
    // After recovery the edit can proceed (base now advanced → conflict is
    // the expected honest answer, NOT a recovery_required block).
    auto after = coordinator.commit(edit, loaded.value().document);
    bool gate_gone = true;
    for (const auto& diagnostic : after.value().diagnostics) {
        if (diagnostic.code == "recovery_required") gate_gone = false;
    }
    PWB_CHECK(gate_gone);
}
