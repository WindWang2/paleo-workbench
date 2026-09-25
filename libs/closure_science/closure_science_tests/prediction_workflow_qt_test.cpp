// closure_science.prediction_workflow_qt — the ws1 prediction workflow
// surface, offscreen through the REAL pages/panels:
//   * WellSeismicLinkController: calibration-gated availability (fail
//     closed with the exact reason, never a fabricated linear velocity),
//     twt->depth cursor conversion through the panels' real gates;
//   * the three production dialogs' data paths (stable ids, package
//     facts, schema-driven params, reset-to-defaults);
//   * PredictionWorkflowController: spec restore/persist seams, honest
//     run refusal, cancel with nothing running;
//   * binding publish seam: a finished demo run's task reaches the
//     project-document publisher (what ws2/ws3 overlays read).

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif
namespace { long test_pid() {
#ifdef _WIN32
    return static_cast<long>(::getpid());
#else
    return static_cast<long>(::getpid());
#endif
} }

#include <QApplication>
#include <QCheckBox>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QSignalSpy>
#include <QSpinBox>
#include <QTableWidget>
#include <QTimer>
#include <QtTest/QTest>

#include <cmath>
#include <filesystem>
#include <string>
#include <vector>

#include <pwb/catalog/service_core.hpp>
#include <pwb/closure_science/qt/page_binding.hpp>
#include <pwb/closure_science/qt/prediction_workflow.hpp>
#include <pwb/closure_science/qt/prediction_workflow_dialogs.hpp>
#include <pwb/closure_science/qt/well_seismic_link.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/run_spec.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_canvas_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

namespace fs = std::filesystem;
namespace csq = pwb::closure_science::qt;
using pwb::domain::Json;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void require_ok(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FATAL %s\n", what.c_str());
        std::exit(2);
    }
}

bool wait_for_signal(const QSignalSpy& spy, int count, int timeout_ms) {
    for (int elapsed = 0; elapsed < timeout_ms && spy.count() < count;
         elapsed += 50) {
        QApplication::processEvents();
        QTest::qWait(50);
    }
    return spy.count() >= count;
}

void auto_close_modals(int after_ms = 60) {
    QTimer::singleShot(after_ms, [] {
        if (auto* modal = QApplication::activeModalWidget()) {
            modal->close();
        }
    });
}

struct TestProject {
    fs::path dir;
    fs::path project_file;
};

TestProject make_project(const std::string& name) {
    TestProject project;
    project.dir = fs::temp_directory_path() /
                  ("closure_science_wf_" + name + "_" +
                   std::to_string(static_cast<long long>(test_pid())));
    fs::remove_all(project.dir);
    fs::create_directories(project.dir);
    project.project_file = project.dir / (name + ".paleo.json");
    fs::create_directories(project.dir / (name + ".artifacts"));
    auto document = pwb::project::ProjectDocument::create_new(name, "");
    pwb::project::ProjectManager manager(project.project_file);
    require_ok(manager.save(document).is_ok(), "project save");
    return project;
}

csq::WellTimeDepthCalibration table_for(const std::string& well_id) {
    csq::WellTimeDepthCalibration table;
    table.well_resource_id = well_id;
    table.well_name = "W-1";
    table.depths_m = {1000.0, 2000.0, 3000.0};
    table.twt_ms = {500.0, 1100.0, 1900.0};
    return table;
}

}  // namespace

int main(int argc, char** argv) {
    qputenv("QT_QPA_PLATFORM", "offscreen");
    QApplication app(argc, argv);

    // =====================================================================
    // 1) WellSeismicLinkController — calibration gate + real conversion
    // =====================================================================
    {
        pwb::ui_wellseis::qt::WellLogPredictionPage well_page;
        pwb::ui_wellseis::qt::SeismicPredictionPage seismic_page;
        csq::WellSeismicLinkController link;
        link.attach(&well_page, &seismic_page);

        // No calibration provider: fail closed with the exact reason.
        check(!link.unavailable_reason().isEmpty(),
              "link unavailable without calibration");
        check(!link.set_enabled(true), "enable without calibration refused");
        check(!link.is_enabled(), "still disabled");

        // Calibration for a DIFFERENT well does not unlock.
        link.set_calibration_provider([](const std::string&) {
            return std::optional<csq::WellTimeDepthCalibration>(
                table_for("res_other"));
        });
        check(!link.unavailable_reason().isEmpty(),
              "foreign-well calibration does not unlock the link");

        // No focused well at all: named reason.
        check(link.unavailable_reason().contains(QStringLiteral("未选择井")) ||
                  link.unavailable_reason()
                          .contains(QStringLiteral("没有已记录的时深标定")),
              "reason names the missing input");

        // Real calibration: available, enables, converts through the
        // panels' real gates (seismic offer -> 30 ms gate -> controller ->
        // conversion -> canvas offer -> 120 ms gate).
        std::string focused;
        link.set_calibration_provider(
            [&focused](const std::string& well_id)
                -> std::optional<csq::WellTimeDepthCalibration> {
                if (well_id == focused) return table_for(well_id);
                return std::nullopt;
            });
        // Focus a well through the page's public selection seam. The page
        // needs a project slice carrying the well resource.
        pwb::ui_wellseis::ProjectSlice slice;
        pwb::ui_wellseis::ResourceSlice well_resource;
        well_resource.id = "res_w1";
        well_resource.name = "W-1";
        well_resource.type = "well_log";
        slice.resources.push_back(well_resource);
        well_page.set_project(&slice);
        check(well_page.select_well_resource("res_w1"),
              "page selects the well (stable id)");
        focused = "res_w1";
        // The provider is already installed; availability refresh happens
        // on selection change — re-focus to re-resolve with the new
        // provider state.
        well_page.select_well_resource("res_w1");
        check(link.unavailable_reason().isEmpty(),
              "link available with a real calibration");
        check(link.set_enabled(true), "enable succeeds with calibration");
        check(link.is_enabled(), "enabled");

        QSignalSpy message_spy(
            &link, &csq::WellSeismicLinkController::link_status_message);
        seismic_page.view_panel()->offer_cursor(3.0, 7.0, 1100.0);
        QApplication::processEvents();
        QTest::qWait(80);  // first event passes the 30 ms gate immediately
        check(link.last_conversion().has_value(),
              "seismic cursor converted through the real gates");
        if (link.last_conversion().has_value()) {
            check(std::abs(link.last_conversion()->depth_m - 2000.0) <
                      1e-9,
                  "twt 1100 ms -> depth 2000 m (calibration node)");
            check(std::abs(link.last_conversion()->twt_ms - 1100.0) < 1e-9,
                  "conversion records the source twt");
        }
        QApplication::processEvents();

        // Outside the table clamps (WellTieCalibration np.interp semantics)
        // — real calibration behaviour, never extrapolation.
        seismic_page.view_panel()->offer_cursor(1.0, 1.0, 99999.0);
        QTest::qWait(80);
        QApplication::processEvents();
        if (link.last_conversion().has_value()) {
            check(std::abs(link.last_conversion()->depth_m - 3000.0) < 1e-9,
                  "clamped past-table twt to the last anchor");
        }

        // Depth cursor echo (status only).
        well_page.canvas_panel()->offer_depth_cursor(2500.0);
        QApplication::processEvents();
        bool echoed = false;
        for (int i = 0; i < message_spy.count(); ++i) {
            if (message_spy.at(i).value(0).toString()
                    .contains(QStringLiteral("深度"))) {
                echoed = true;
            }
        }
        check(echoed, "depth cursor echoed with its twt");

        // Enabling fails again once the calibration disappears (project
        // switch): fail closed automatically.
        focused.clear();
        well_page.select_well_resource("res_w1");
        check(!link.is_enabled(),
              "link auto-disables when the calibration disappears");
        check(!link.unavailable_reason().isEmpty(),
              "availability reason returns after calibration loss");
    }

    // =====================================================================
    // 2) Dialog data paths (offscreen, accept() driven directly)
    // =====================================================================
    {
        // Well selection: stable ids, unusable rows unselectable.
        std::vector<pwb::closure_science::WellCandidate> wells(2);
        wells[0].resource_id = "res_w1";
        wells[0].name = "W-1";
        wells[0].version_id = "ver_1";
        wells[0].availability = "ok";
        wells[1].resource_id = "res_w2";
        wells[1].name = "W-2";
        wells[1].availability = "unmanaged";
        csq::WellSelectionDialog dialog(wells, {"res_w1"});
        auto* table = dialog.findChild<QTableWidget*>();
        require_ok(table != nullptr, "well dialog table");
        auto* ok_w1 = qobject_cast<QCheckBox*>(table->cellWidget(0, 0));
        auto* ok_w2 = qobject_cast<QCheckBox*>(table->cellWidget(1, 0));
        require_ok(ok_w1 != nullptr && ok_w2 != nullptr, "well checkboxes");
        check(ok_w1->isChecked(), "initial selection kept (stable id)");
        check(!ok_w2->isEnabled(), "unmanaged well unselectable");
        dialog.accept();  // triggers the accepted collector
        const auto selected = dialog.selected_resource_ids();
        check(selected.size() == 1 && selected[0] == "res_w1",
              "selection returns stable resource ids");

        // Model selection: demo executor available -> selectable; the
        // online provider (no executor) refuses OK.
        std::vector<pwb::closure_science::ModelCandidate> models(2);
        models[0].model_version_id = "mver_demo";
        models[0].model_id = "demo-facies-v1";
        models[0].model_version = "1";
        models[0].name = "演示";
        models[0].provider = "demo";
        models[0].status = "demo";
        models[0].executor_available = true;
        models[1].model_version_id = "mver_online";
        models[1].model_id = "geoviz-online-v1";
        models[1].model_version = "1";
        models[1].name = "线上";
        models[1].provider = "geoviz_online";
        models[1].status = "production";
        models[1].executor_available = false;
        models[1].executor_note = "无原生执行器";
        std::map<std::string, pwb::closure_science::ModelPackageSummary>
            no_packages;
        csq::ModelSelectionDialog model_dialog(models, no_packages,
                                               "mver_demo");
        auto* list = model_dialog.findChild<QListWidget*>();
        require_ok(list != nullptr, "model dialog list");
        list->setCurrentRow(1);  // online provider
        QApplication::processEvents();
        check(!model_dialog.selection_confirmable(),
              "no-executor model cannot be confirmed");
        list->setCurrentRow(0);
        QApplication::processEvents();
        check(model_dialog.selection_confirmable(),
              "demo model confirmable");
        model_dialog.accept();
        check(model_dialog.selected_model_version_id() == "mver_demo",
              "model selection returns the version id");

        // Params: schema-driven editors, reset-to-defaults, accept mapping.
        Json defaults = pwb::prediction::default_prediction_params();
        csq::PredictionParamsDialog params_dialog(defaults);
        auto* tile_spin =
            params_dialog.findChild<QSpinBox*>(QStringLiteral("tile_inline"));
        require_ok(tile_spin != nullptr, "tile_inline editor by schema key");
        tile_spin->setValue(48);
        params_dialog.accept();
        const Json edited = params_dialog.params();
        check(edited.contains("tile_inline") &&
                  edited["tile_inline"].get<long long>() == 48,
              "edited spin maps into params");
        check(params_dialog.params_changed(), "change detected");
    }

    // =====================================================================
    // 3) Controller: seams, restore, honest refusal, cancel no-op
    // =====================================================================
    {
        pwb::ui_wellseis::qt::WellLogPredictionPage well_page;
        pwb::ui_wellseis::qt::SeismicPredictionPage seismic_page;
        auto* binding = csq::attach_prediction_pages(
            well_page, seismic_page, []() { return fs::path(); });
        auto* controller = csq::install_prediction_workflow(
            binding, &well_page, &seismic_page, nullptr);

        Json stored;
        csq::PredictionWorkflowController::ProjectSeams seams;
        seams.read_run_spec = [&stored]() { return stored; };
        seams.write_run_spec = [&stored](const Json& spec) {
            stored = spec;
            return pwb::domain::DataError(pwb::domain::ErrorCode::Ok, "");
        };
        controller->set_project_seams(seams);

        // Restore: a persisted spec becomes the draft (resolved dropped).
        pwb::prediction::PredictionRunSpec saved;
        saved.model_version_id = "mver_tiled";
        saved.well_resource_ids = {"res_w1"};
        saved.params["tile_inline"] = 64;
        saved.resolved = Json{{"stale", true}};
        stored = saved.to_json();
        check(controller->restore_persisted_spec(), "restore succeeds");
        check(controller->spec().model_version_id == "mver_tiled" &&
                  controller->spec().well_resource_ids ==
                      std::vector<std::string>{"res_w1"},
              "restored spec fields");
        check(controller->spec().resolved.empty(),
              "resolved identity never survives a restore");

        // Run without a project: honest refusal (modal auto-closed).
        auto_close_modals();
        check(!controller->run(), "run refused without a project");
        // Cancel with nothing running: honest no-op.
        check(!controller->cancel(), "cancel no-op without a run");

        // Malformed stored spec: ignored, draft reset to defaults.
        stored = Json{{"schema_version", 99}};
        controller->restore_persisted_spec();
        check(controller->spec().model_version_id.empty(),
              "malformed stored spec ignored");
    }

    // =====================================================================
    // 4) Publish seam end-to-end: demo run -> project-document publisher
    // =====================================================================
    {
        const TestProject project = make_project("publish");
        pwb::ui_wellseis::qt::WellLogPredictionPage well_page;
        pwb::ui_wellseis::qt::SeismicPredictionPage seismic_page;
        pwb::ui_wellseis::ProjectSlice slice;
        pwb::ui_wellseis::ResourceSlice seismic_resource;
        seismic_resource.id = "res-seismic-ui";
        seismic_resource.name = "演示地震体";
        seismic_resource.type = "seismic";
        slice.resources.push_back(seismic_resource);
        slice.project_crs = "EPSG:32650";
        auto* binding = csq::attach_prediction_pages(
            well_page, seismic_page,
            [&]() { return project.project_file; });
        seismic_page.set_project(&slice);
        well_page.set_project(&slice);

        std::vector<Json> published;
        binding->set_publish_task([&published](const Json& task) {
            published.push_back(task);
            return pwb::domain::DataError(pwb::domain::ErrorCode::Ok, "");
        });
        QSignalSpy updated_spy(
            &seismic_page,
            &pwb::ui_wellseis::qt::SeismicPredictionPage::
                prediction_updated);
        seismic_page.on_demo();
        check(wait_for_signal(updated_spy, 1, 30000),
              "demo run completes");
        check(published.size() == 1,
              "materialized task reached the project-document publisher");
        if (!published.empty()) {
            check(published.front().contains("id") &&
                      published.front()["id"].is_string(),
                  "published task carries its stable id");
        }

        // ---- the RunSpec path end-to-end: controller->run() must mark
        // the page in flight, deliver the completion past the session
        // guard and publish the second task — the regression proof that
        // a spec run is not silently dropped.
        auto* controller = csq::install_prediction_workflow(
            binding, &well_page, &seismic_page, nullptr);
        Json stored;
        csq::PredictionWorkflowController::ProjectSeams seams;
        seams.read_run_spec = [&stored]() { return stored; };
        seams.write_run_spec = [&stored](const Json& spec) {
            stored = spec;
            return pwb::domain::DataError(pwb::domain::ErrorCode::Ok, "");
        };
        controller->set_project_seams(seams);
        std::string candidate_error;
        const auto models = binding->model_candidates(&candidate_error);
        std::string demo_id;
        for (const auto& model : models) {
            if (model.provider == "demo") {
                demo_id = model.model_version_id;
                break;
            }
        }
        check(!demo_id.empty(), "demo model discoverable via candidates");
        if (!demo_id.empty()) {
            pwb::prediction::PredictionRunSpec spec;
            spec.model_version_id = demo_id;
            spec.params["tile_inline"] = 32;
            spec.workflow = "seismic_facies";
            spec.demo = true;
            stored = spec.to_json();
            check(controller->restore_persisted_spec(), "spec restored");
            const std::size_t before = published.size();
            check(controller->run(), "controller run starts the spec run");
            check(wait_for_signal(updated_spy, 2, 30000),
                  "spec-run completion reaches the page");
            check(published.size() == before + 1,
                  "spec-run task published (not dropped at the guard)");
        }
    }

    if (g_failures == 0) {
        std::printf("closure_science.prediction_workflow_qt: passed\n");
        return 0;
    }
    std::printf("closure_science.prediction_workflow_qt: %d FAILED\n",
                g_failures);
    return 1;
}
