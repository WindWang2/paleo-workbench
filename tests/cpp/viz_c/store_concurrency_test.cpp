// viz_c.store_concurrency — deterministic regression for #1380/#1381.
//
// Three writer roles share ONE PwbDataStore, mirroring the production
// entry points the swarm audit listed:
//   A "segy-import"   (JobScheduler worker): register_run +
//     publish_run_result + export_manifest  (main_window publish path)
//   B "attribute-run" (TaskRuntime worker): register_run +
//     publish_run_result                    (CatalogResultPublisher path)
//   C "gui-edit"      (GUI thread): CommitCoordinator::commit +
//     export_manifest                       (stage_commit/closeEvent path)
//
// Determinism:
//  * interleaving is barrier-controlled — every round the three writers
//    are released together (a hand-rolled generation barrier), so the
//    scripted operation sequences overlap at operation granularity;
//  * the coordinator FaultHook runs INSIDE the serialized critical section
//    and acts as a mutual-exclusion probe: peak in-critical count > 1
//    proves two writers were inside at once (a broken/missing lock).
//
// Post-join invariants: no false success, exact row counts, idempotent
// replay, terminal run rows, reopenable store, failed-publish rollback.
#include "pwb_test.hpp"

#include "pwb/application/adapters/data_store.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

#include <atomic>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::application::PwbDataStore;
using pwb::data::CommitCoordinator;

constexpr int kRounds = 6;

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
        fs::temp_directory_path() / ("pwb_vizc_conc_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
    const fs::path source =
        fs::path(VIZ_C_DATA_FIXTURE_DIR) / "typical";
    fs::copy(source, scratch.root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    scratch.project = scratch.root / "typical.paleo.json";
    return scratch;
}

fs::path write_staged(const fs::path& root, const std::string& name,
                      const std::string& bytes) {
    const fs::path file = root / name;
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return file;
}

// Generation barrier: releases all participating threads together once per
// round (deterministic interleave control; no timing dependence).
class Barrier {
public:
    explicit Barrier(int parties) : parties_(parties) {}

    void arrive_and_wait() {
        std::unique_lock<std::mutex> lock(mutex_);
        const std::uint64_t generation = generation_;
        if (++arrived_ == parties_) {
            arrived_ = 0;
            ++generation_;
            cv_.notify_all();
            return;
        }
        cv_.wait(lock, [this, generation] {
            return generation_ != generation;
        });
    }

private:
    const int parties_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::uint64_t generation_ = 0;
    int arrived_ = 0;
};

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

struct FixtureAsset {
    pwb::domain::AssetId asset;
    pwb::domain::VersionId version;
};

FixtureAsset first_current_asset(const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return {};
    for (const auto& asset : document.value().assets) {
        if (asset.current_version_id.has_value()) {
            return {asset.id, *asset.current_version_id};
        }
    }
    return {};
}

// Mutual-exclusion probe: the hook body executes while the coordinator
// mutex is held, so a second writer can only observe in_critical_ > 0 if
// serialization is broken.
struct MutexProbe {
    std::atomic<int> in_critical{0};
    std::atomic<int> peak_in_critical{0};
    std::atomic<int> calls{0};

    std::optional<pwb::domain::DataError> hook(pwb::data::JournalPhase) {
        const int now = in_critical.fetch_add(1) + 1;
        int peak = peak_in_critical.load(std::memory_order_relaxed);
        while (now > peak &&
               !peak_in_critical.compare_exchange_weak(peak, now)) {
        }
        ++calls;
        in_critical.fetch_sub(1);
        return std::nullopt;  // observe only; never inject a fault here
    }
};

struct WriterReport {
    std::atomic<int> failures{0};
    std::string first_error;
    void fail(const std::string& message) {
        int expected = 0;
        if (!failures.compare_exchange_strong(expected, 1) || expected == 0) {
            if (first_error.empty()) first_error = message;
        }
        failures.fetch_add(1);
    }
};

pwb::data::PublishRequestV1 import_like_publish(int round, const fs::path& staged) {
    pwb::data::PublishRequestV1 request;
    request.operation_id = pwb::domain::OperationId(
        "pub_import_" + std::to_string(round));
    request.run_id = pwb::domain::RunId("run_import_" + std::to_string(round));
    request.new_asset_name = "地震数据 conc-" + std::to_string(round);
    request.new_asset_type = "seismic_volume";
    request.stage = pwb::domain::DataStage::Raw;
    pwb::data::StagedAssetV1 product;
    product.source_path = staged;
    product.format = "PWBVOL1";
    request.products.push_back(product);
    request.result_metadata = pwb::domain::Json{
        {"payload_format", "PWBVOL1"}, {"source_format", "SEG-Y"}};
    return request;
}

pwb::data::PublishRequestV1 attribute_like_publish(
    int round, const fs::path& staged) {
    pwb::data::PublishRequestV1 request;
    request.operation_id = pwb::domain::OperationId(
        "pub_attr_" + std::to_string(round));
    request.run_id = pwb::domain::RunId("run_attr_" + std::to_string(round));
    request.new_asset_name = "attribute conc-" + std::to_string(round);
    request.new_asset_type = "volume";
    request.stage = pwb::domain::DataStage::Derived;
    pwb::data::StagedAssetV1 product;
    product.source_path = staged;
    product.sha256 = pwb::domain::Sha256::of_file(staged);
    product.format = "f32";
    request.products.push_back(product);
    request.result_metadata = pwb::domain::Json{{"units", "ms"}};
    return request;
}

}  // namespace

PWB_TEST(concurrent_import_attribute_edit_no_corruption) {
    Scratch scratch = fresh_typical("main");
    std::string open_error;
    auto store = PwbDataStore::open(scratch.project, &open_error);
    PWB_CHECK(store != nullptr);
    PWB_CHECK(open_error.empty());
    const Counts before = catalog_counts(scratch.project);
    const FixtureAsset target = first_current_asset(scratch.project);
    PWB_CHECK(!target.asset.str().empty());

    MutexProbe probe;
    store->coordinator().set_fault_hook(
        [&probe](pwb::data::JournalPhase phase) {
            return probe.hook(phase);
        });

    // Pre-stage every round's payload files (pure file I/O before the
    // barrier so threads only exercise store calls).
    std::vector<fs::path> import_staged(kRounds);
    std::vector<fs::path> attr_staged(kRounds);
    std::vector<fs::path> edit_staged(kRounds);
    for (int i = 0; i < kRounds; ++i) {
        import_staged[i] = write_staged(
            scratch.root, "import_" + std::to_string(i) + ".pwbvol",
            "import-payload-" + std::to_string(i));
        attr_staged[i] = write_staged(
            scratch.root, "attr_" + std::to_string(i) + ".f32",
            "attribute-payload-" + std::to_string(i));
        edit_staged[i] = write_staged(
            scratch.root, "edit_" + std::to_string(i) + ".geojson",
            "{\"features\": " + std::to_string(i) + "}");
    }

    Barrier barrier(3);
    WriterReport import_report;
    WriterReport attr_report;
    WriterReport edit_report;
    std::string first_import_version;
    std::mutex first_version_mutex;

    // A — SEG-Y import publish role (worker thread).
    std::thread import_role([&] {
        for (int i = 0; i < kRounds; ++i) {
            barrier.arrive_and_wait();
            pwb::data::RunRegistrationV1 registration;
            registration.run_id =
                pwb::domain::RunId("run_import_" + std::to_string(i));
            registration.operation = "import.segy";
            registration.generator = "viz-c-conc";
            auto registered =
                store->coordinator().register_run(registration);
            if (!registered.is_ok()) {
                import_report.fail("register_run: " +
                                   registered.error().message);
                continue;
            }
            auto published = store->coordinator().publish_run_result(
                import_like_publish(i, import_staged[i]),
                store->document());
            if (!published.is_ok()) {
                import_report.fail("publish: " +
                                   published.error().message);
                continue;
            }
            if (published.value().new_version_id.str().empty()) {
                import_report.fail("publish: empty version id");
            }
            if (i == 0) {
                std::lock_guard<std::mutex> lock(first_version_mutex);
                first_import_version = published.value().new_version_id.str();
            }
            auto manifest = store->export_manifest();
            if (manifest.code != pwb::domain::ErrorCode::Ok) {
                import_report.fail("manifest: " + manifest.message);
            }
        }
    });

    // B — attribute publisher role (TaskRuntime worker).
    std::thread attr_role([&] {
        for (int i = 0; i < kRounds; ++i) {
            barrier.arrive_and_wait();
            pwb::data::RunRegistrationV1 registration;
            registration.run_id =
                pwb::domain::RunId("run_attr_" + std::to_string(i));
            registration.operation = "seismic.rms_amplitude";
            registration.generator = "viz-c-conc";
            auto registered =
                store->coordinator().register_run(registration);
            if (!registered.is_ok()) {
                attr_report.fail("register_run: " +
                                 registered.error().message);
                continue;
            }
            auto published = store->coordinator().publish_run_result(
                attribute_like_publish(i, attr_staged[i]),
                store->document());
            if (!published.is_ok()) {
                attr_report.fail("publish: " +
                                 published.error().message);
            }
        }
    });

    // C — GUI edit-commit role (stage_commit / closeEvent path). Commits
    // chain on their own previous version (single-threaded optimistic
    // chain; A/B create separate assets so the base stays valid).
    std::thread edit_role([&] {
        pwb::domain::VersionId base = target.version;
        for (int i = 0; i < kRounds; ++i) {
            barrier.arrive_and_wait();
            pwb::data::CommitRequestV1 request;
            request.operation_id = pwb::domain::OperationId(
                "edit_op_" + std::to_string(i));
            request.asset_id = target.asset;
            request.base_version_id = base;
            request.stage = pwb::domain::DataStage::Derived;
            request.staged.source_path = edit_staged[i];
            request.staged.sha256 =
                pwb::domain::Sha256::of_file(edit_staged[i]);
            request.staged.format = "GeoJSON";
            request.version_name = "conc edit " + std::to_string(i);
            auto receipt =
                store->coordinator().commit(request, store->document());
            if (!receipt.is_ok()) {
                edit_report.fail("commit: " + receipt.error().message);
                continue;
            }
            if (receipt.value().status !=
                pwb::data::CommitStatus::Committed) {
                edit_report.fail(
                    "commit status: " +
                    std::string(pwb::data::to_string(
                        receipt.value().status)));
                continue;
            }
            base = receipt.value().new_version_id;
        }
    });

    import_role.join();
    attr_role.join();
    edit_role.join();

    PWB_CHECK(import_report.failures.load() == 0);
    PWB_CHECK(attr_report.failures.load() == 0);
    PWB_CHECK(edit_report.failures.load() == 0);
    if (import_report.failures.load() != 0) {
        std::cout << "  import role: " << import_report.first_error << "\n";
    }
    if (attr_report.failures.load() != 0) {
        std::cout << "  attribute role: " << attr_report.first_error << "\n";
    }
    if (edit_report.failures.load() != 0) {
        std::cout << "  edit role: " << edit_report.first_error << "\n";
    }

    // Mutual exclusion held: the probe only ever saw one writer inside.
    PWB_CHECK(probe.peak_in_critical.load() == 1);
    PWB_CHECK(probe.calls.load() > 0);

    // Exact durable state: 2 new assets + 3 new versions + 2 new runs per
    // round set (A: asset+version+run, B: asset+version+run, C: version).
    const Counts after = catalog_counts(scratch.project);
    PWB_CHECK(after.assets == before.assets + 2 * kRounds);
    PWB_CHECK(after.versions == before.versions + 3 * kRounds);
    PWB_CHECK(after.runs == before.runs + 2 * kRounds);

    // Idempotent replay of A's first publish: same version id, no row
    // growth (crash-safe duplicate contract).
    auto replay = store->coordinator().publish_run_result(
        import_like_publish(0, import_staged[0]), store->document());
    PWB_CHECK(replay.is_ok());
    PWB_CHECK(replay.value().new_version_id.str() == first_import_version);
    const Counts replayed = catalog_counts(scratch.project);
    PWB_CHECK(replayed.assets == after.assets);
    PWB_CHECK(replayed.versions == after.versions);
    PWB_CHECK(replayed.runs == after.runs);

    // All published runs landed terminal ("complete"), none stuck running.
    // (The fixture itself carries one pre-existing complete run; only the
    // runs this test created are asserted.)
    {
        pwb::catalog::CatalogRepository repository(
            pwb::project::catalog_sqlite_for(scratch.project));
        auto document = repository.open_read_only();
        PWB_CHECK(document.is_ok());
        int ours_completed = 0;
        for (const auto& run : document.value().runs) {
            const std::string id = run.id.str();
            if (id.rfind("run_import_", 0) == 0 ||
                id.rfind("run_attr_", 0) == 0) {
                PWB_CHECK(run.status == "complete");
                ++ours_completed;
            }
        }
        PWB_CHECK(ours_completed == 2 * kRounds);
    }

    // The store reopens cleanly (no torn sqlite/document left behind).
    std::string reopen_error;
    auto reopened = PwbDataStore::open(scratch.project, &reopen_error);
    PWB_CHECK(reopened != nullptr);
    PWB_CHECK(reopen_error.empty());
}

PWB_TEST(concurrent_failed_publish_rolls_back_and_finishes_run) {
    Scratch scratch = fresh_typical("fail");
    std::string open_error;
    auto store = PwbDataStore::open(scratch.project, &open_error);
    PWB_CHECK(store != nullptr);
    const Counts before = catalog_counts(scratch.project);

    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(std::string("run_badpublish"));
    registration.operation = "seismic.rms_amplitude";
    registration.generator = "viz-c-conc";
    auto registered = store->coordinator().register_run(registration);
    PWB_CHECK(registered.is_ok());

    // Publish pointing at a payload that does not exist: must fail (never
    // a false success) and leave no version behind.
    pwb::data::PublishRequestV1 request;
    request.operation_id = pwb::domain::OperationId(std::string("pub_badpublish"));
    request.run_id = registration.run_id;
    request.new_asset_name = "broken";
    request.new_asset_type = "volume";
    pwb::data::StagedAssetV1 product;
    product.source_path = scratch.root / "missing-payload.f32";
    product.format = "f32";
    request.products.push_back(product);
    auto published =
        store->coordinator().publish_run_result(request, store->document());
    PWB_CHECK(!published.is_ok() ||
              published.value().status ==
                  pwb::data::PublishStatus::Failed);

    // Failure -> task-failure semantics: the run can be finished Failed
    // (the CatalogResultPublisher publish_failure path) even while another
    // writer commits concurrently.
    std::thread gui_editor([&] {
        const FixtureAsset target = first_current_asset(scratch.project);
        const fs::path staged =
            write_staged(scratch.root, "edit.geojson", "{\"ok\": true}");
        pwb::data::CommitRequestV1 commit_request;
        commit_request.operation_id =
            pwb::domain::OperationId(
                std::string("edit_op_concurrent_fail"));
        commit_request.asset_id = target.asset;
        commit_request.base_version_id = target.version;
        commit_request.stage = pwb::domain::DataStage::Derived;
        commit_request.staged.source_path = staged;
        commit_request.staged.sha256 =
            pwb::domain::Sha256::of_file(staged);
        commit_request.staged.format = "GeoJSON";
        auto receipt = store->coordinator().commit(commit_request,
                                                   store->document());
        PWB_CHECK(receipt.is_ok());
    });
    auto finished = store->coordinator().finish_run(
        registration.run_id, pwb::data::RunTerminalStatus::Failed,
        pwb::domain::Json{{"reason", "payload missing"}});
    gui_editor.join();
    PWB_CHECK(finished.is_ok());

    const Counts after = catalog_counts(scratch.project);
    // One extra run row (register_run) and one extra version (the GUI
    // commit); the failed publish contributed neither asset nor version.
    PWB_CHECK(after.assets == before.assets);
    PWB_CHECK(after.versions == before.versions + 1);
    PWB_CHECK(after.runs == before.runs + 1);

    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    const auto* run =
        document.value().find_run(registration.run_id);
    PWB_CHECK(run != nullptr);
    PWB_CHECK(run->status == "failed");
}

// Negative self-check: the counting assertions really do observe the
// catalog (a tampered expectation must flip the check, proving the test
// is not vacuously green).
PWB_TEST(concurrency_counts_are_real_observations) {
    Scratch scratch = fresh_typical("negative");
    std::string open_error;
    auto store = PwbDataStore::open(scratch.project, &open_error);
    PWB_CHECK(store != nullptr);
    const Counts before = catalog_counts(scratch.project);

    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(std::string("run_import_99"));
    registration.operation = "import.segy";
    registration.generator = "viz-c-conc";
    PWB_CHECK(store->coordinator().register_run(registration).is_ok());
    const fs::path staged =
        write_staged(scratch.root, "neg.pwbvol", "neg-payload");
    PWB_CHECK(store->coordinator()
                  .publish_run_result(import_like_publish(99, staged),
                                      store->document())
                  .is_ok());

    const Counts after = catalog_counts(scratch.project);
    // If these deltas ever read zero, the assertions above would be
    // vacuous — the writer really must move the counts.
    PWB_CHECK(after.runs == before.runs + 1);
    PWB_CHECK(after.assets == before.assets + 1);
    PWB_CHECK(after.versions == before.versions + 1);
}
