// data.commit_recovery — fault injection at every journal phase, then
// recover(): Written/PayloadStaged roll back, CatalogCommitted and later
// continue; nothing is left pending (test-plan.md §4, Oracle O5).
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/project/manager.hpp"

#include <fstream>

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";

struct Scratch {
    fs::path root;
    fs::path project;
    fs::path staged;
    std::string staged_bytes;
};

Scratch fresh_typical(const char* tag, const char* payload) {
    Scratch scratch;
    scratch.root =
        fs::temp_directory_path() / ("pwb_recover_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
    fs::copy(fs::path(PWB_DATA_FIXTURE_DIR) / "typical", scratch.root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    scratch.project = scratch.root / "typical.paleo.json";
    scratch.staged_bytes = payload;
    scratch.staged = scratch.root / "staged.bin";
    std::ofstream out(scratch.staged, std::ios::binary | std::ios::trunc);
    out.write(payload, static_cast<std::streamsize>(scratch.staged_bytes.size()));
    return scratch;
}

pwb::data::CommitRequestV1 make_request(const fs::path& staged,
                                        const pwb::domain::AssetId& asset,
                                        const pwb::domain::VersionId& base) {
    pwb::domain::seed_id_generator_for_tests(9001ULL);
    pwb::data::CommitRequestV1 request;
    request.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    request.asset_id = asset;
    request.base_version_id = base;
    request.stage = pwb::domain::DataStage::Derived;
    request.staged.source_path = staged;
    request.staged.format = "test";
    return request;
}

std::pair<pwb::domain::AssetId, pwb::domain::VersionId> current_of(
    const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    for (const auto& asset : document.value().assets) {
        if (asset.current_version_id.has_value()) {
            return {asset.id, *asset.current_version_id};
        }
    }
    return {pwb::domain::AssetId(std::string("missing")),
            pwb::domain::VersionId(std::string("missing"))};
}

// Injects a fault right after `phase`, recovers, and classifies.
// expected_receipt: the status the interrupted commit itself reports
// (post-durability faults already flipped it to Committed before the
// injected abort — the operation logically succeeded).
std::string inject_and_recover(const char* tag, const char* payload,
                               pwb::data::JournalPhase phase,
                               pwb::data::CommitStatus expected_receipt) {
    Scratch scratch = fresh_typical(tag, payload);
    const auto [asset, base] = current_of(scratch.project);
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    coordinator.set_fault_hook(
        [phase](pwb::data::JournalPhase reached)
            -> std::optional<pwb::domain::DataError> {
            if (reached == phase) {
                return pwb::domain::DataError(
                    pwb::domain::ErrorCode::IoError, "injected");
            }
            return std::nullopt;
        });
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto receipt =
        coordinator.commit(make_request(scratch.staged, asset, base),
                           loaded.value().document);
    PWB_CHECK(receipt.is_ok());
    PWB_CHECK(receipt.value().status == expected_receipt);

    pwb::data::CommitCoordinator healer(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto report = healer.recover(loaded.value().document);
    PWB_CHECK(report.pending.empty());
    // The staged source is never mutated by placement or recovery.
    std::ifstream in(scratch.staged, std::ios::binary);
    const std::string after((std::istreambuf_iterator<char>(in)),
                            std::istreambuf_iterator<char>());
    PWB_CHECK(after == scratch.staged_bytes);
    std::error_code ec;
    if (!report.continued.empty()) {
        fs::remove_all(scratch.root, ec);
        return "continued";
    }
    if (!report.rolled_back.empty()) {
        fs::remove_all(scratch.root, ec);
        return "rolled_back";
    }
    fs::remove_all(scratch.root, ec);
    return "pending";
}

}  // namespace

PWB_TEST(fault_after_write_rolls_back) {
    PWB_CHECK(inject_and_recover("written", "bytes-written",
                                 pwb::data::JournalPhase::Written,
                                 pwb::data::CommitStatus::Failed) ==
              "rolled_back");
}
PWB_TEST(fault_after_payload_continues) {
    // Payload is durable and content-addressed; recovery reuses it and
    // finishes the catalog transaction instead of deleting work.
    PWB_CHECK(inject_and_recover("staged", "bytes-staged",
                                 pwb::data::JournalPhase::PayloadStaged,
                                 pwb::data::CommitStatus::Failed) ==
              "continued");
}
PWB_TEST(fault_after_catalog_continues) {
    PWB_CHECK(inject_and_recover("catalog", "bytes-catalog",
                                 pwb::data::JournalPhase::CatalogCommitted,
                                 pwb::data::CommitStatus::Committed) ==
              "continued");
}
PWB_TEST(fault_after_project_save_continues) {
    PWB_CHECK(inject_and_recover("saved", "bytes-saved",
                                 pwb::data::JournalPhase::ProjectSaved,
                                 pwb::data::CommitStatus::Failed) ==
              "continued");
}
