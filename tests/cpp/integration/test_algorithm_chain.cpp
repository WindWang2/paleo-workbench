// integration.algorithm_chain — REAL C runtime + REAL B catalog, no
// substitutes: coherence_c3 over the frozen tiny.sgy oracle fixture runs
// through TaskRuntime with A's CatalogResultPublisher; the durable result
// (PWBVOL1 payload + catalog version) is re-read after reopening the store
// and compared against the oracle expected volume. Cancel and kernel-error
// paths terminate their runs without any success version; later tasks keep
// running.

#include <atomic>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <string>
#include <stop_token>
#include <thread>
#include <vector>

#include <QTemporaryDir>
#include <qgsapplication.h>

#include <pwb/application/adapters/catalog_publisher.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/viz/seismic_volume.hpp>
#include <pwb/workflow/task_runtime.hpp>

#include "../platform/test_framework.hpp"

namespace fs = std::filesystem;

namespace {

std::vector<float> read_f32(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::vector<float> data(static_cast<size_t>(size / 4));
    if (!data.empty()) {
        input.read(reinterpret_cast<char*>(data.data()), size);
    }
    return data;
}

bool copy_tree(const fs::path& from, const fs::path& to) {
    std::error_code ec;
    fs::create_directories(to, ec);
    for (const auto& entry : fs::recursive_directory_iterator(from, ec)) {
        const auto target = to / fs::relative(entry.path(), from, ec);
        if (entry.is_directory(ec)) fs::create_directories(target, ec);
        else if (entry.is_regular_file(ec)) {
            fs::create_directories(target.parent_path(), ec);
            fs::copy_file(entry.path(), target,
                          fs::copy_options::overwrite_existing, ec);
        }
        if (ec) return false;
    }
    return true;
}

// Host-side blocking algorithm for the cancel path (public interface only).
class BarrierAlgorithm final : public pwb::science::IAlgorithm {
public:
    explicit BarrierAlgorithm(std::string id) : id_(std::move(id)) {}

    const pwb::science::AlgorithmDescriptor& descriptor() const override {
        static pwb::science::AlgorithmDescriptor descriptor = [] {
            pwb::science::AlgorithmDescriptor d;
            d.algorithm_id = "test.barrier";
            d.version = "1.0.0";
            d.display_name = "Barrier (integration test)";
            d.family = "test";
            d.supports_cancel = true;
            return d;
        }();
        return descriptor;
    }

    pwb::science::Result<pwb::science::AlgorithmResultV1> run(
        const pwb::science::AlgorithmRequestV1& request,
        pwb::science::ProgressSink /*progress*/,
        std::stop_token stop) override {
        ++calls_;
        while (!stop.stop_requested()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        return pwb::science::TaskCancelled{"barrier"};
    }

    int calls() const { return calls_.load(); }

private:
    std::string id_;
    std::atomic<int> calls_{0};
};

// Kernel that throws: the runtime must convert it to failure and the
// publisher to a durable Failed run (never a success version).
class ThrowingAlgorithm final : public pwb::science::IAlgorithm {
public:
    const pwb::science::AlgorithmDescriptor& descriptor() const override {
        static pwb::science::AlgorithmDescriptor descriptor = [] {
            pwb::science::AlgorithmDescriptor d;
            d.algorithm_id = "test.throws";
            d.version = "1.0.0";
            d.display_name = "Throwing (integration test)";
            d.family = "test";
            return d;
        }();
        return descriptor;
    }
    pwb::science::Result<pwb::science::AlgorithmResultV1> run(
        const pwb::science::AlgorithmRequestV1&,
        pwb::science::ProgressSink,
        std::stop_token) override {
        throw std::runtime_error("kernel exploded (test)");
    }
};

int runs_with_status(const pwb::data::ProjectSnapshotV1& snapshot,
                     const std::string& run_id, std::string* status) {
    for (const auto& run : snapshot.catalog_runs) {
        if (run.id.str() == run_id) {
            *status = run.status;
            return 1;
        }
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // ---- B fixture + real store --------------------------------------------
    const fs::path fixtures = PWB_TEST_SRC_DIR "/../data/fixtures";
    QTemporaryDir temp;
    const fs::path work = fs::path(temp.path().toStdWString()) / "project";
    PWB_CHECK(copy_tree(fixtures / "typical", work));
    std::string store_error;
    auto store = pwb::application::PwbDataStore::open(
        work / "typical.paleo.json", &store_error);
    PWB_CHECK_MSG(store != nullptr, "store open failed: " + store_error);

    // An existing catalog input version gives the run real provenance.
    auto initial = store->snapshot();
    PWB_CHECK(initial.is_ok());
    PWB_CHECK(!initial.value().catalog_versions.empty());
    const std::string input_version =
        initial.value().catalog_versions.front().id.str();

    // ---- C fixture (frozen oracle case: real tiny.sgy) ----------------------
    const fs::path case_dir =
        fs::path(PWB_SCIENCE_FIXTURE_ROOT) / "coherence_c3" / "tiny_sgy_real_w3";
    const std::vector<float> input = read_f32(case_dir / "input.f32");
    const std::vector<float> expected = read_f32(case_dir / "expected.f32");
    PWB_CHECK(!input.empty() && expected.size() == input.size());
    const std::int64_t ni = 8, nc = 8, ns = 32;   // frozen fixture shape
    PWB_CHECK(static_cast<size_t>(ni * nc * ns) == input.size());

    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {ni, nc, ns};
    geometry.step = {1.0, 1.0, 2.0};     // dt = 2 ms like tiny.sgy
    geometry.unit = "ms";
    geometry.missing_value = -999.25f;

    const fs::path staged_dir =
        fs::path(temp.path().toStdWString()) / "results";
    pwb::application::CatalogResultPublisher publisher(store, staged_dir);

    // ---- real C3 through the real runtime + B publisher --------------------
    // Registration validates the descriptor; execution submits a second
    // factory instance (the registry owns the first, submit needs a
    // shared_ptr — C's registry API hands out raw pointers only).
    pwb::science::AlgorithmRegistry registry;
    const std::string rejected = registry.register_algorithm(
        pwb::science::algorithms::make_coherence_c3("integration-build"));
    PWB_CHECK_MSG(rejected.empty(), "registry rejected c3: " + rejected);
    const pwb::science::IAlgorithm* registered =
        registry.find("seismic.coherence_c3");
    PWB_CHECK(registered != nullptr);
    const pwb::science::AlgorithmDescriptor& descriptor =
        registered->descriptor();

    pwb::science::AlgorithmRequestV1 request;
    request.request_id = "int-c3-0001";
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.params_json = {{"win_il", "3"}, {"win_xl", "3"}, {"win_t", "3"}};
    request.input_volumes.push_back(
        {input.data(), {ni, nc, ns}, {0, 0, 0}, nullptr});

    pwb::application::RequestContext context;
    context.geometry = geometry;
    context.input_version_ids = {input_version};
    context.params_json = request.params_json;
    publisher.set_request_context(request.request_id,
                                  std::move(context));

    {
        pwb::workflow::TaskRuntime runtime;
        auto handle = runtime.submit(
            pwb::science::algorithms::make_coherence_c3("integration-build"),
            request,
            std::shared_ptr<pwb::application::CatalogResultPublisher>(
                &publisher, [](auto*) {}));
        handle.wait();
        PWB_CHECK(handle.snapshot().status
                  == pwb::workflow::TaskStatus::succeeded);

        const auto outcome = publisher.outcome(request.request_id);
        PWB_CHECK_MSG(outcome.success,
                      "publish failed: " + outcome.error);
        PWB_CHECK(!outcome.version_id.empty());
        runtime.shutdown();
    }

    // ---- durable re-read: reopen store, verify run + version + payload -----
    std::string reopen_error;
    auto reopened = pwb::application::PwbDataStore::open(
        work / "typical.paleo.json", &reopen_error);
    PWB_CHECK_MSG(reopened != nullptr, "reopen: " + reopen_error);
    {
        auto snapshot = reopened->snapshot();
        PWB_CHECK(snapshot.is_ok());
        std::string status;
        PWB_CHECK_MSG(
            runs_with_status(snapshot.value(), "run_int-c3-0001", &status)
            && status == "complete",
            "run row missing or not complete (status=" + status + ")");

        const std::string version_id = publisher.outcome(
            request.request_id).version_id;
        fs::path payload_path;
        bool found = false;
        for (const auto& version : snapshot.value().catalog_versions) {
            if (version.id.str() == version_id) {
                payload_path = work / version.path;
                found = fs::exists(payload_path);
                break;
            }
        }
        PWB_CHECK_MSG(found,
                      "published version missing from catalog or payload "
                      "file absent: " + payload_path.string());

        pwb::application::VolumePayload payload;
        const std::string read_error =
            pwb::application::read_volume_payload(payload_path, &payload);
        PWB_CHECK_MSG(read_error.empty(), "payload read: " + read_error);
        PWB_CHECK(payload.samples.size() == expected.size());
        double max_diff = 0.0;
        for (size_t i = 0; i < expected.size(); ++i) {
            max_diff = std::max(
                max_diff,
                static_cast<double>(std::fabs(
                    static_cast<double>(payload.samples[i])
                    - static_cast<double>(expected[i]))));
        }
        // 2e-3 is C's frozen oracle tolerance (cpp-science 00-baseline §5)
        // — the numerical contract, not a number we invented here.
        PWB_CHECK_MSG(max_diff < 2e-3,
                      "oracle mismatch, max_abs_diff=" + std::to_string(max_diff));
        PWB_CHECK(payload.header.algorithm_id == "seismic.coherence_c3");
        PWB_CHECK(payload.header.sample_unit == "ms");
    }

    // ---- cancel path: durable Cancelled, no success version ----------------
    {
        pwb::workflow::TaskRuntime runtime;
        pwb::science::AlgorithmRequestV1 cancel_request;
        cancel_request.request_id = "int-cancel-0001";
        cancel_request.algorithm_id = "test.barrier";
        cancel_request.algorithm_version = "1.0.0";
        auto barrier = std::make_shared<BarrierAlgorithm>("barrier");
        auto handle = runtime.submit(barrier, cancel_request,
            std::shared_ptr<pwb::application::CatalogResultPublisher>(
                &publisher, [](auto*) {}));
        while (barrier->calls() == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        handle.cancel();
        handle.wait();
        PWB_CHECK(handle.snapshot().status
                  == pwb::workflow::TaskStatus::cancelled);
        const auto outcome = publisher.outcome(cancel_request.request_id);
        PWB_CHECK_MSG(outcome.success, "cancel publish failed: " + outcome.error);

        runtime.shutdown();
        auto snapshot = reopened->snapshot();
        PWB_CHECK(snapshot.is_ok());
        std::string status;
        PWB_CHECK(runs_with_status(snapshot.value(), "run_int-cancel-0001",
                                   &status));
        PWB_CHECK_MSG(status == "cancelled",
                      "cancel run status=" + status);
        int versions_before_cancel = 0;
        for (const auto& v : snapshot.value().catalog_versions) {
            if (v.run_id && v.run_id->str() == "run_int-cancel-0001") {
                ++versions_before_cancel;
            }
        }
        PWB_CHECK(versions_before_cancel == 0);
    }

    // ---- kernel exception path: durable Failed, runtime keeps serving ------
    {
        pwb::workflow::TaskRuntime runtime;
        pwb::science::AlgorithmRequestV1 throw_request;
        throw_request.request_id = "int-throw-0001";
        throw_request.algorithm_id = "test.throws";
        throw_request.algorithm_version = "1.0.0";
        auto handle = runtime.submit(std::make_shared<ThrowingAlgorithm>(),
            throw_request,
            std::shared_ptr<pwb::application::CatalogResultPublisher>(
                &publisher, [](auto*) {}));
        handle.wait();
        PWB_CHECK(handle.snapshot().status
                  == pwb::workflow::TaskStatus::failed);
        runtime.shutdown();

        auto snapshot = reopened->snapshot();
        PWB_CHECK(snapshot.is_ok());
        std::string status;
        PWB_CHECK(runs_with_status(snapshot.value(), "run_int-throw-0001",
                                   &status));
        PWB_CHECK_MSG(status == "failed", "throw run status=" + status);

        // The next task still runs (worker survived the exception).
        pwb::workflow::TaskRuntime next_runtime;
        pwb::science::AlgorithmRequestV1 after;
        after.request_id = "int-after-0001";
        after.algorithm_id = "test.barrier";
        after.algorithm_version = "1.0.0";
        auto barrier = std::make_shared<BarrierAlgorithm>("after");
        auto handle2 = next_runtime.submit(barrier, after,
            std::shared_ptr<pwb::application::CatalogResultPublisher>(
                &publisher, [](auto*) {}));
        while (barrier->calls() == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        handle2.cancel();
        handle2.wait();
        PWB_CHECK(handle2.snapshot().status
                  == pwb::workflow::TaskStatus::cancelled);
        next_runtime.shutdown();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("integration.algorithm_chain");
}
