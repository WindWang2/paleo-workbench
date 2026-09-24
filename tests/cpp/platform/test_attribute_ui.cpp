// platform.attribute_ui — M1 end-to-end in the REAL MainWindow with the
// real B store, real E kernels and the native seismic volume service
// (no substitutes): open a project that carries a PWBVOL1 version, run
// an attribute through MainWindow::runAttribute (phase 4: synchronous
// QgsProcessingRegistry run + CatalogResultPublisher into B), reach a
// durable success with a published version, then open that version
// through SeismicVolumeService (the slice-dock display leg is retired
// out of the two-page shell — openVolumeVersion reports honest absence).

#include <cmath>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <QCoreApplication>
#include <QDockWidget>
#include <QTemporaryDir>
#include <QThread>
#include <qgsapplication.h>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#if defined(PWB_WITH_SEISMIC_SERVICE)
#include <pwb/seismic_service/volume_service.hpp>
#endif

#include "main_window.hpp"

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace fs = std::filesystem;
using pwb::app::MainWindow;

namespace {

std::vector<float> read_f32(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::vector<float> data(static_cast<std::size_t>(size / 4));
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

// Seeds the project with one PWBVOL1 volume version: publishes a tiny
// synthetic volume through B's run lifecycle exactly the way A's adapter
// does (register -> payload -> publish), so the version is real catalog
// state (run complete + payload file present).
std::string seed_volume_version(const fs::path& project_file) {
    std::string open_error;
    auto store =
        pwb::application::PwbDataStore::open(project_file, &open_error);
    if (store == nullptr) return "store open: " + open_error;
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) return "snapshot failed";
    std::string input_version;
    if (!snapshot.value().catalog_versions.empty()) {
        input_version =
            snapshot.value().catalog_versions.front().id.str();
    }

    constexpr std::int64_t ni = 4, nc = 4, ns = 64;
    pwb::application::VolumePayload payload;
    payload.header.ni = 4;
    payload.header.nc = 4;
    payload.header.ns = 64;
    payload.header.inline_step = 1.0;
    payload.header.crossline_step = 1.0;
    payload.header.sample_step = 2.0;
    payload.header.sample_unit = "ms";
    payload.header.value_unit = "amplitude";
    payload.header.algorithm_id = "seed.synthetic";
    payload.header.algorithm_version = "1.0.0";
    payload.header.build_identity = "attribute-ui-test";
    payload.header.request_id = "seed-0001";
    payload.samples.resize(static_cast<size_t>(ni * nc * ns));
    for (std::int64_t i = 0; i < ni; ++i) {
        for (std::int64_t c = 0; c < nc; ++c) {
            for (std::int64_t s = 0; s < ns; ++s) {
                const double t = static_cast<double>(s) * 2.0;
                payload.samples[static_cast<size_t>((i * nc + c) * ns + s)] =
                    static_cast<float>(
                        std::sin(t * 0.08 + i * 0.3 + c * 0.2));
            }
        }
    }

    const fs::path staged_dir = project_file.parent_path() / ".pwb-runs";
    std::error_code ec;
    fs::create_directories(staged_dir, ec);
    const fs::path payload_path = staged_dir / "seed-0001.pwbvol";
    const std::string write_error =
        pwb::application::write_volume_payload(payload, payload_path);
    if (!write_error.empty()) return "payload write: " + write_error;

    const pwb::domain::RunId run_id{std::string("run_seed-0001")};
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id;
    registration.operation = "seed.synthetic";
    registration.generator = "seed@1.0.0+attribute-ui-test";
    if (!input_version.empty()) {
        registration.input_version_ids.push_back(
            pwb::domain::VersionId(input_version));
    }
    auto registered = store->coordinator().register_run(registration);
    if (!registered.is_ok()) {
        return "register_run: " + registered.error().message;
    }

    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId{std::string("pub_seed-0001")};
    publish.run_id = run_id;
    publish.new_asset_name = "seed-synthetic-volume";
    publish.new_asset_type = "seismic_volume";
    publish.stage = pwb::domain::DataStage::Raw;
    pwb::data::StagedAssetV1 staged;
    staged.source_path = payload_path;
    staged.format = "PWBVOL1";
    publish.products.push_back(std::move(staged));
    publish.result_metadata = pwb::domain::Json::object();
    publish.result_metadata["payload_format"] = "PWBVOL1";
    auto published =
        store->coordinator().publish_run_result(publish, store->document());
    if (!published.is_ok()) {
        return "publish: " + published.error().message;
    }
    return published.value().new_version_id.str();
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const fs::path fixtures =
        fs::path(PWB_TEST_SRC_DIR) / ".." / "data" / "fixtures";
    const fs::path work =
        fs::path(temp_dir.path().toStdWString()) / "project";
    PWB_CHECK(copy_tree(fixtures / "typical", work));
    const fs::path project_file = work / "typical.paleo.json";
    const std::string seed_version = seed_volume_version(project_file);
    PWB_CHECK_MSG(!seed_version.empty(), seed_version);

    MainWindow window;
    const QString open_error =
        window.openProject(QString::fromStdString(project_file.string()));
    PWB_CHECK_MSG(open_error.isEmpty(), open_error.toStdString());

    // The seeded volume is discoverable as an attribute input.
    const std::vector<std::string> versions = window.volumeVersionIds();
    PWB_CHECK(!versions.empty());
    bool found = false;
    for (const std::string& id : versions) {
        if (id == seed_version) found = true;
    }
    PWB_CHECK(found);

    // Run one attribute over the seeded volume through the real chain.
    std::string error;
    const std::string request_id = window.runAttribute(
        "seismic.rms_amplitude", {{"window", "21"}}, seed_version, &error);
    PWB_CHECK_MSG(!request_id.empty(), error);

    bool reached_terminal = false;
    for (int i = 0; i < 2000; ++i) {
        const auto outcome = window.attributeOutcome(request_id);
        if (outcome.status == "queued" || outcome.status == "running"
            || outcome.status == "publishing") {
            QThread::msleep(5);
            continue;
        }
        reached_terminal = true;
        PWB_CHECK_MSG(outcome.status == "succeeded",
                      "status=" + outcome.status + " error=" + outcome.error);
        PWB_CHECK(!outcome.version_id.empty());
        PWB_CHECK(!outcome.run_id.empty());

        // Durable: the published version is in the (reopened) catalog and
        // the run row is complete.
        {
            std::string reopen_error;
            auto reopened = pwb::application::PwbDataStore::open(
                project_file, &reopen_error);
            PWB_CHECK_MSG(reopened != nullptr, reopen_error);
            auto snapshot = reopened->snapshot();
            PWB_CHECK(snapshot.is_ok());
            bool version_found = false;
            std::string run_status;
            for (const auto& version : snapshot.value().catalog_versions) {
                if (version.id.str() == outcome.version_id) {
                    version_found = version.format == "PWBVOL1";
                }
            }
            for (const auto& run : snapshot.value().catalog_runs) {
                if (run.id.str() == outcome.run_id) {
                    run_status = run.status;
                }
            }
            PWB_CHECK(version_found);
            PWB_CHECK_MSG(run_status == "complete",
                          "run status=" + run_status);
        }

        // 两页壳层：地震视图面板已退役出界面 —— openVolumeVersion 诚实
        // 报告无显示宿主；链路验证改走服务端开卷（与 openVolumeVersion
        // 内部同一条 SeismicVolumeService 路径）。
        const QString view_error = window.openVolumeVersion(
            outcome.version_id);
        PWB_CHECK(!view_error.isEmpty());   // 诚实缺席，不伪造显示
#if defined(PWB_WITH_SEISMIC_SERVICE)
        {
            fs::path payload_path;
            std::string reopen_error;
            auto reopened = pwb::application::PwbDataStore::open(
                project_file, &reopen_error);
            PWB_CHECK_MSG(reopened != nullptr, reopen_error);
            auto snapshot = reopened->snapshot();
            PWB_CHECK(snapshot.is_ok());
            for (const auto& version :
                 snapshot.value().catalog_versions) {
                if (version.id.str() == outcome.version_id) {
                    payload_path = work / version.path;
                }
            }
            PWB_CHECK(!payload_path.empty());
            pwb::seismic_service::SeismicVolumeService service;
            std::string open_error;
            auto opened = service.open_pwbvol(payload_path, &open_error);
            PWB_CHECK_MSG(opened.volume != nullptr, open_error);
        }
#endif
        break;
    }
    PWB_CHECK_MSG(reached_terminal, "attribute run never reached a terminal state");

#if defined(PWB_WITH_SEISMIC_IO)
    // ---- M3 end-to-end: real SEG-Y import -> attribute -> frozen oracle
    // -> viewer. The imported volume is sample-identical to the geoviz
    // oracle input, so rms(window=21) must match the frozen expected file.
    {
        std::string import_error;
        const std::string imported = window.importSegy(
            QString::fromStdString(
                (fs::path(PWB_REALDATA_DIR) / "tiny.sgy").string()),
            &import_error);
        PWB_CHECK_MSG(!imported.empty(), import_error);

        std::string run_error;
        const std::string rms_request = window.runAttribute(
            "seismic.rms_amplitude", {{"window", "21"}}, imported,
            &run_error);
        PWB_CHECK_MSG(!rms_request.empty(), run_error);
        for (int i = 0; i < 2000; ++i) {
            const auto outcome = window.attributeOutcome(rms_request);
            if (outcome.status == "queued" || outcome.status == "running"
                || outcome.status == "publishing") {
                QThread::msleep(5);
                continue;
            }
            PWB_CHECK_MSG(outcome.status == "succeeded",
                          "imported rms status=" + outcome.status
                              + " error=" + outcome.error);
            // Oracle accounting: read the durable payload and compare
            // against E's frozen expected_rms_w21.
            std::string reopen_error;
            auto reopened = pwb::application::PwbDataStore::open(
                project_file, &reopen_error);
            PWB_CHECK_MSG(reopened != nullptr, reopen_error);
            auto snapshot = reopened->snapshot();
            PWB_CHECK(snapshot.is_ok());
            fs::path payload_path;
            for (const auto& version :
                 snapshot.value().catalog_versions) {
                if (version.id.str() == outcome.version_id) {
                    payload_path = work / version.path;
                }
            }
            PWB_CHECK(!payload_path.empty());
            pwb::application::VolumePayload payload;
            PWB_CHECK(pwb::application::read_volume_payload(
                          payload_path, &payload)
                          .empty());
            std::vector<float> expected = read_f32(
                fs::path(PWB_ATTRIBUTE_FIXTURES) / "tiny_sgy_real"
                / "expected_rms_w21.f32");
            PWB_CHECK(payload.samples.size() == expected.size());
            double max_diff = 0.0;
            for (std::size_t i = 0; i < expected.size(); ++i) {
                max_diff = std::max(max_diff,
                    std::fabs(static_cast<double>(payload.samples[i])
                              - static_cast<double>(expected[i])));
            }
            PWB_CHECK_MSG(max_diff < 1e-5,
                          "imported rms oracle mismatch, max_abs_diff="
                              + std::to_string(max_diff));
            break;
        }

        // 同样，被导入体版本经服务端开卷可达（显示面板已退役）。
        const QString view_error = window.openVolumeVersion(imported);
        PWB_CHECK(!view_error.isEmpty());
#if defined(PWB_WITH_SEISMIC_SERVICE)
        {
            fs::path payload_path;
            std::string reopen_error;
            auto reopened = pwb::application::PwbDataStore::open(
                project_file, &reopen_error);
            PWB_CHECK_MSG(reopened != nullptr, reopen_error);
            auto snapshot = reopened->snapshot();
            PWB_CHECK(snapshot.is_ok());
            for (const auto& version :
                 snapshot.value().catalog_versions) {
                if (version.id.str() == imported
                    && version.format == "PWBVOL1") {
                    payload_path = work / version.path;
                }
            }
            PWB_CHECK(!payload_path.empty());
            pwb::seismic_service::SeismicVolumeService service;
            std::string open_error;
            auto opened = service.open_pwbvol(payload_path, &open_error);
            PWB_CHECK_MSG(opened.volume != nullptr, open_error);
        }
#endif
    }
#endif

    window.close();
    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.attribute_ui");
}
