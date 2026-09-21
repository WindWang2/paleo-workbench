// integration.attribute_chain — the FIVE-LINE chain with no substitutes:
// a real CPP-E attribute kernel (rms_amplitude / envelope on the frozen
// tiny_sgy_real oracle fixture) runs through CPP-C's TaskRuntime and is
// published by CPP-A's CatalogResultPublisher into a real CPP-B catalog;
// the store is then REOPENED and the durable PWBVOL1 payload is compared
// against E's frozen Python-oracle expected volumes.
//
// E's own suite drives kernels with a baseline runtime + collecting
// publisher; this test proves the same kernels on the production chain
// (registry registration, provenance through A's context, B's run row
// turning "complete" only via publish, readback after reopen).

#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <QTemporaryDir>
#include <qgsapplication.h>

#include <pwb/application/adapters/catalog_publisher.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>
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

// One kernel -> runtime -> publisher -> B -> reopen -> readback round.
// Returns false with a reason on any breach.
bool run_attribute_through_catalog(
    const std::string& label,
    const std::shared_ptr<pwb::science::IAlgorithm>& kernel,
    const std::map<std::string, std::string>& params,
    const std::vector<float>& input, const std::vector<float>& expected,
    const pwb::viz::VolumeGeometryV1& geometry,
    const std::string& input_version, const fs::path& work,
    const fs::path& staged_dir, std::string* reason) {
    const std::string request_id = "attr-" + label + "-0001";
    const std::int64_t ni = geometry.shape[0];
    const std::int64_t nc = geometry.shape[1];
    const std::int64_t ns = geometry.shape[2];

    std::string reopen_error;
    auto store = pwb::application::PwbDataStore::open(
        work / "typical.paleo.json", &reopen_error);
    if (store == nullptr) {
        *reason = "store open failed: " + reopen_error;
        return false;
    }
    pwb::application::CatalogResultPublisher publisher(store, staged_dir);

    pwb::science::AlgorithmRequestV1 request;
    request.request_id = request_id;
    request.algorithm_id = kernel->descriptor().algorithm_id;
    request.algorithm_version = kernel->descriptor().version;
    request.params_json = params;
    request.input_volumes.push_back(
        {input.data(), {ni, nc, ns}, {0, 0, 0}, nullptr});

    pwb::application::RequestContext context;
    context.geometry = geometry;
    context.input_version_ids = {input_version};
    context.params_json = params;
    publisher.set_request_context(request.request_id,
                                  std::move(context));

    {
        pwb::workflow::TaskRuntime runtime;
        auto handle = runtime.submit(kernel, request,
            std::shared_ptr<pwb::application::CatalogResultPublisher>(
                &publisher, [](auto*) {}));
        handle.wait();
        const auto snapshot = handle.snapshot();
        runtime.shutdown();
        if (snapshot.status != pwb::workflow::TaskStatus::succeeded) {
            *reason = label + ": task status != succeeded (error_code="
                + snapshot.error_code + ")";
            return false;
        }
        if (!snapshot.published) {
            *reason = label + ": task reports unpublished success";
            return false;
        }
    }

    const auto outcome = publisher.outcome(request_id);
    if (!outcome.success || outcome.version_id.empty()) {
        *reason = label + ": publish outcome failed: " + outcome.error;
        return false;
    }

    // Durable re-read: fresh store over the same files.
    auto reopened = pwb::application::PwbDataStore::open(
        work / "typical.paleo.json", &reopen_error);
    if (reopened == nullptr) {
        *reason = label + ": reopen failed: " + reopen_error;
        return false;
    }
    auto snapshot = reopened->snapshot();
    if (!snapshot.is_ok()) {
        *reason = label + ": reopened snapshot failed";
        return false;
    }
    std::string status;
    if (!runs_with_status(snapshot.value(), "run_" + request_id, &status)
        || status != "complete") {
        *reason = label + ": run missing or not complete (status=" + status
            + ")";
        return false;
    }
    fs::path payload_path;
    bool found = false;
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() == outcome.version_id) {
            payload_path = work / version.path;
            found = fs::exists(payload_path);
            break;
        }
    }
    if (!found) {
        *reason = label + ": published version/payload missing";
        return false;
    }
    pwb::application::VolumePayload payload;
    const std::string read_error =
        pwb::application::read_volume_payload(payload_path, &payload);
    if (!read_error.empty()) {
        *reason = label + ": payload read: " + read_error;
        return false;
    }
    if (payload.samples.size() != expected.size()) {
        *reason = label + ": payload size mismatch";
        return false;
    }
    double max_diff = 0.0;
    for (size_t i = 0; i < expected.size(); ++i) {
        max_diff = std::max(max_diff,
            static_cast<double>(std::fabs(
                static_cast<double>(payload.samples[i])
                - static_cast<double>(expected[i]))));
    }
    // E's dual-criterion tolerance for rms/envelope is far tighter than
    // 1e-5 on this fixture; 1e-5 only absorbs the f32 payload roundtrip.
    if (!(max_diff < 1e-5)) {
        *reason = label + ": oracle mismatch, max_abs_diff="
            + std::to_string(max_diff);
        return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // ---- B fixture + a real input version for provenance ------------------
    const fs::path b_fixtures = PWB_TEST_SRC_DIR "/../data/fixtures";
    QTemporaryDir temp;
    const fs::path work = fs::path(temp.path().toStdWString()) / "project";
    PWB_CHECK(copy_tree(b_fixtures / "typical", work));
    std::string store_error;
    auto store = pwb::application::PwbDataStore::open(
        work / "typical.paleo.json", &store_error);
    PWB_CHECK_MSG(store != nullptr, "store open failed: " + store_error);
    auto initial = store->snapshot();
    PWB_CHECK(initial.is_ok());
    PWB_CHECK(!initial.value().catalog_versions.empty());
    const std::string input_version =
        initial.value().catalog_versions.front().id.str();

    // ---- E fixture: frozen tiny.sgy oracle case ----------------------------
    const fs::path case_dir =
        fs::path(PWB_ATTRIBUTES_FIXTURE_ROOT) / "tiny_sgy_real";
    const std::vector<float> input = read_f32(case_dir / "input.f32");
    const std::vector<float> expected_rms =
        read_f32(case_dir / "expected_rms_w21.f32");
    const std::vector<float> expected_envelope =
        read_f32(case_dir / "expected_envelope.f32");
    PWB_CHECK(!input.empty());
    PWB_CHECK(expected_rms.size() == input.size());
    PWB_CHECK(expected_envelope.size() == input.size());

    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {8, 8, 32};          // frozen fixture shape
    geometry.step = {1.0, 1.0, 2.0};      // tiny.sgy dt = 2 ms
    geometry.unit = "ms";
    geometry.missing_value = -999.25f;

    // ---- host-side registration (A calls E's explicit registration) -------
    pwb::science::AlgorithmRegistry registry;
    const pwb::seismic_attributes::RegistrationReport registration =
        pwb::seismic_attributes::register_seismic_attributes(
            registry, "integration-build");
    PWB_CHECK_MSG(registration.rejection.empty(),
                  "registration rejected: " + registration.rejection);
    // envelope/phase/frequency/rms + the S-line volume kernels — the
    // registration contract is "size 10 on success" (attributes.hpp).
    PWB_CHECK(registration.registered_ids.size() == 10);
    for (const std::string& id : registration.registered_ids) {
        PWB_CHECK(registry.find(id) != nullptr);
    }

    const fs::path staged_dir =
        fs::path(temp.path().toStdWString()) / "results";
    std::string reason;

    // ---- kernel 1: rms_amplitude (parametric) ------------------------------
    PWB_CHECK_MSG(
        run_attribute_through_catalog(
            "rms", pwb::seismic_attributes::make_rms_amplitude(
                       "integration-build"),
            {{"window", "21"}}, input, expected_rms, geometry, input_version,
            work, staged_dir, &reason),
        reason);

    // ---- kernel 2: envelope (param-free) -----------------------------------
    PWB_CHECK_MSG(
        run_attribute_through_catalog(
            "envelope", pwb::seismic_attributes::make_envelope(
                            "integration-build"),
            {}, input, expected_envelope, geometry, input_version, work,
            staged_dir, &reason),
        reason);

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("integration.attribute_chain");
}
