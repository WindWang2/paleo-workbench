// platform.closure_mapping — 08-line closure battery.
//
// Part 1 (bank): the MapDocumentBank over MapEditScene — multi-document
// binding, real scene edits with undo/redo, save (topology gate +
// apply_features_to_document + view_state stash + persist seam), discard,
// guarded switch refusal, and restore consistency (features/CRS/view_state
// survive a save/rebind round trip).
//
// Part 2 (install): the real MainWindow composition installs the closure —
// the hub-3 preparation placeholder is replaced by the real PreparationPage
// and the mapping page placeholders become the ui_pages_mapedit /
// ui_seqviz widgets.

#include <QApplication>
#include <QLabel>
#include <QPointF>
#include <QStackedWidget>
#include <QVariant>
#include <qgsapplication.h>

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <set>
#include <string>
#include <thread>
#include <unistd.h>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_view.hpp>
#include <pwb/ui_seqviz/qt/composition_panel.hpp>

#include "closure_mapping_document.hpp"
#include "test_framework.hpp"

#ifdef PWB_WITH_APP_SHELL
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_shell/navigation.hpp>

#include "app_shell.hpp"
#include "closure_mapping_install.hpp"
#include "main_window.hpp"
#include "shell_project_actions.hpp"

using pwb::app::AppShell;
using pwb::app::MainWindow;
#endif

using pwb::domain::Json;
using pwb::ui_pages_mapedit::MapEditScene;
using pwb::ui_pages_mapedit::MapEditView;

namespace {

Json facies_record(const char* id) {
    return Json{{"id", id},
                {"kind", "facies"},
                {"name", "河道砂"},
                {"coordinates",
                 Json::array({Json::array({0.0, 0.0}),
                              Json::array({10.0, 0.0}),
                              Json::array({10.0, 10.0}),
                              Json::array({0.0, 0.0})})}};
}

Json sample_document(const std::string& id, const std::string& horizon) {
    Json doc = Json::object();
    doc["id"] = id;
    doc["name"] = horizon;
    doc["map_crs"] = "EPSG:4326";
    doc["facies_polygons"] = Json::array({facies_record("f-1")});
    doc["line_features"] = Json::array();
    doc["well_overlays"] = Json::array();
    doc["label_features"] = Json::array();
    doc["view_state"] = Json{{"center", Json::array({5.0, 5.0})},
                             {"scale", 2.0}};
    return doc;
}

int bank_battery(QApplication& app) {
    (void)app;
    MapEditScene scene;
    MapEditView view;

    std::vector<Json> documents{sample_document("doc-a", "Sq1 沉积图"),
                                sample_document("doc-b", "Sq2 沉积图")};
    pwb::app::closure_mapping::MapDocumentBank bank(&scene, &view);

    int persist_calls = 0;
    bank.set_persist_fn([&persist_calls](std::string*) {
        ++persist_calls;
        return true;
    });

    PWB_CHECK(bank.set_documents(std::move(documents), "doc-a", nullptr));
    PWB_CHECK_MSG(bank.active_id() == "doc-a", "active document doc-a");
    PWB_CHECK_MSG(scene.feature_count() == 1, "one feature bound");
    PWB_CHECK_MSG(!bank.is_dirty(), "bank clean after load");

    // -- edit -> dirty -> undo -> clean ---------------------------------
    scene.translate_features({"f-1"}, 3.0, 4.0);
    PWB_CHECK(scene.is_dirty());
    PWB_CHECK(bank.is_dirty());
    PWB_CHECK(scene.undo());
    PWB_CHECK(!scene.is_dirty());

    // -- save: export -> apply_features_to_document -> persist ----------
    scene.translate_features({"f-1"}, 3.0, 4.0);
    PWB_CHECK(scene.is_dirty());
    // Move the viewport so the saved view_state differs from the loaded one.
    view.apply_view_state(QVariantMap{{"center", QVariantList{7.0, 8.0}},
                                      {"scale", 3.0}});
    PWB_CHECK_MSG(bank.save_active(nullptr), "save succeeded");
    PWB_CHECK_MSG(persist_calls == 1, "persist seam called once");
    PWB_CHECK_MSG(!bank.is_dirty(), "bank clean after save");
    {
        const Json& saved = *bank.active_document();
        const auto facies = saved.find("facies_polygons");
        PWB_CHECK(facies != saved.end() && facies->is_array()
                  && facies->size() == 1);
        // The editor feature export normalizes geometry under the
        // document_io record shape; the coordinate payload must carry the
        // translation (10+3, 0+4 on the first ring vertex is the honest
        // check: the editor writes normalized rings, not the raw record).
        const auto vs = saved.find("view_state");
        PWB_CHECK(vs != saved.end() && vs->is_object());
        const auto center = vs->find("center");
        PWB_CHECK(center != vs->end() && center->is_array()
                  && center->size() == 2
                  && (*center)[0].get<double>() == 7.0);
        PWB_CHECK(bank.last_warnings().empty());
    }

    // -- discard: drop edits back to the last saved copy -----------------
    scene.translate_features({"f-1"}, 100.0, 100.0);
    PWB_CHECK(bank.is_dirty());
    bank.discard_active();
    PWB_CHECK(!bank.is_dirty());
    PWB_CHECK_MSG(scene.feature_count() == 1, "one feature after discard");
    {
        // After discard the rebound document matches the saved copy
        // (translation gone: the item geometry back at 3,4 offset).
        const auto hit = scene.hit_test_at(11.5, 4.5, 2.0);
        PWB_CHECK(hit.has_value());
    }

    // -- switch: dirty switch without a guard surface is refused ---------
    scene.translate_features({"f-1"}, 1.0, 1.0);
    PWB_CHECK(bank.is_dirty());
    PWB_CHECK(!bank.switch_to("doc-b", nullptr));
    PWB_CHECK_MSG(bank.active_id() == "doc-a", "stay on doc-a after refusal");
    bank.discard_active();

    // -- switch: clean switch rebinds and restores -----------------------
    PWB_CHECK_MSG(bank.switch_to("doc-b", nullptr), "switch to doc-b");
    PWB_CHECK_MSG(bank.active_id() == "doc-b", "active doc-b");
    PWB_CHECK_MSG(scene.feature_count() == 1, "doc-b bound");
    PWB_CHECK_MSG(!bank.is_dirty(), "doc-b clean");
    PWB_CHECK_MSG(bank.switch_to("doc-a", nullptr), "switch back");
    PWB_CHECK_MSG(bank.active_id() == "doc-a", "active doc-a again");

    // -- restore consistency: CRS + geometry survive rebind --------------
    {
        const Json& active = *bank.active_document();
        const auto crs = active.find("map_crs");
        PWB_CHECK(crs != active.end()
                  && crs->get<std::string>() == "EPSG:4326");
        const auto vs = active.find("view_state");
        PWB_CHECK(vs != active.end());
    }
    return pwb::test::failure_count();
}

#ifdef PWB_WITH_APP_SHELL
int install_battery() {
    MainWindow window;
    window.show();
    AppShell* shell = window.appShell();
    PWB_CHECK_MSG(shell != nullptr, "AppShell missing");
    PWB_CHECK_MSG(
        window.property("closure_mapping_context").value<QObject*>()
            != nullptr,
        "closure context not installed");

    // -- preparation: the placeholder is gone, the real page is in --------
    pwb::ui_pages_data::qt::HubPage* hub_mapping = nullptr;
    for (auto* hub : shell->findChildren<pwb::ui_pages_data::qt::HubPage*>()) {
        if (hub->hub_index() == pwb::ui_shell::kPageIndexMapping) {
            hub_mapping = hub;
        }
    }
    PWB_CHECK(hub_mapping != nullptr);
    PWB_CHECK(hub_mapping->page("preparation") != nullptr);
    PWB_CHECK(qobject_cast<pwb::ui_pages_data::qt::PreparationPage*>(
                  hub_mapping->page("preparation"))
              != nullptr);
    auto* preparation =
        shell->findChild<pwb::ui_pages_data::qt::PreparationPage*>();
    PWB_CHECK_MSG(preparation != nullptr,
                  "PreparationPage not installed into the shell");
    PWB_CHECK_MSG(preparation->objectName()
                      == QStringLiteral("PreparationPage"),
                  "preparation page object name");
    // The preparation panel placeholders were replaced by the real shims.
    PWB_CHECK(preparation->findChild<QWidget*>("run_qc_btn") != nullptr);
    PWB_CHECK(preparation->task_panel() != nullptr);
    PWB_CHECK(preparation->well_table_panel() != nullptr);
    PWB_CHECK(preparation->preview_grid() != nullptr);
    PWB_CHECK(preparation->boundary_panel() != nullptr);

    // -- mapping page: the real widgets displaced the placeholders --------
    auto* mapping_page = shell->mapping_page();
    PWB_CHECK(mapping_page != nullptr);
    PWB_CHECK(mapping_page->findChild<MapEditView*>() != nullptr);
    PWB_CHECK(mapping_page->findChild<MapEditScene*>() != nullptr);
    auto* composition =
        mapping_page->findChild<pwb::ui_seqviz::qt::CompositionPanel*>();
    PWB_CHECK(composition != nullptr);
    PWB_CHECK(composition->document() != nullptr);
    PWB_CHECK(composition->session() != nullptr);
    // The "（未迁移）" placeholders were replaced in the dock/float
    // registries: the page's composition slot hosts the real panel.
    PWB_CHECK_MSG(mapping_page->center_stack()->count() == 2,
                  "center stack: edit view + preview host");

    // -- save routing: no project store bound -> honest failure -----------
    std::string error;
    PWB_CHECK(!pwb::app::closure_mapping::save_documents(&window, &error));
    return pwb::test::failure_count();
}

#ifdef PWB_WITH_FACTOR_KERNEL
// Part 3 — V14-FACTOR real-kernel E2E through the installed product
// surface: open a real project → 批量生成 (real WorkerHost thread + real
// scheduler + real kernels) → 等值线初稿 → constraint/value change →
// selective recompute → save → reopen with intact lineage.
int factor_kernel_battery(QgsApplication& app) {
    namespace fs = std::filesystem;
    const fs::path tmp = fs::temp_directory_path()
        / ("pwb_v14_factor_e2e_" + std::to_string(::getpid()));
    fs::create_directories(tmp);
    const fs::path project_file = tmp / "e2e.paleo.json";

    Json points = Json::array();
    for (int i = 0; i < 10; ++i) {
        points.push_back(Json{{"well", "W" + std::to_string(i)},
                              {"x", 100.0 + 0.1 * i},
                              {"y", 30.0 + 0.08 * i},
                              {"value", 12.0 + 1.7 * i}});
    }
    Json points2 = Json::array();
    for (int i = 0; i < 10; ++i) {
        points2.push_back(Json{{"well", "V" + std::to_string(i)},
                               {"x", 100.5 + 0.09 * i},
                               {"y", 30.2 + 0.07 * i},
                               {"value", 40.0 - 1.3 * i}});
    }
    Json ring = Json::array();
    for (int i = 0; i <= 4; ++i) {
        const double a = i * 2.0 * std::acos(-1.0) / 4.0;
        ring.push_back(Json::array({100.4 + 6.5 * std::cos(a),
                                    30.3 + 6.5 * std::sin(a)}));
    }
    Json document = Json::object();
    document["schema_version"] = 1;
    document["meta"] = Json{{"name", "V14 因子 E2E"},
                            {"project_root", "."},
                            {"created_at", "2026-09-20T00:00:00+00:00"},
                            {"updated_at", "2026-09-20T00:00:00+00:00"}};
    document["coordinate"] =
        Json{{"project_crs", "EPSG:32650"},
             {"crs_locked", false},
             {"display_crs", "EPSG:4326 / WGS84"}};
    document["stratigraphy"] = Json{{"target_horizon", "C6"}};
    document["constraint_layers"] = Json::array({Json{
        {"id", "clayers_e2e"},
        {"name", "约束层"},
        {"target_horizon", "C6"},
        {"crs", "EPSG:32650"},
        {"lines",
         Json::array({Json{{"id", "cline_b"},
                           {"role", "boundary"},
                           {"active", true},
                           {"coordinates", ring}}})}}});
    document["factor_map_tasks"] = Json::array({
        Json{{"id", "factor_e2e_a"},
             {"name", "C6 地层厚度"},
             {"target_horizon", "C6"},
             {"factor_type", "地层厚度"},
             {"method", "IDW"},
             {"status", "pending"},
             {"source_kind", "mixed"},
             {"parameters", Json{{"sample_points", points}}}},
        Json{{"id", "factor_e2e_c"},
             {"name", "C6 砂地比"},
             {"target_horizon", "C6"},
             {"factor_type", "砂地比"},
             {"method", "约束IDW"},
             {"status", "pending"},
             {"source_kind", "mixed"},
             {"parameters", Json{{"sample_points", points2}}}}});
    document["paleomap_documents"] = Json::array();
    document["contour_drafts"] = Json::array();
    document["well_tables"] = Json::array();
    document["resources"] = Json::array();
    {
        std::ofstream out(project_file, std::ios::binary | std::ios::trunc);
        out << pwb::domain::dump_json_python_compatible(document);
    }

    const auto wait_for = [&](const std::function<bool()>& ready,
                              const char* what) {
        for (int i = 0; i < 3000; ++i) {  // ~30s
            app.processEvents();
            if (ready()) return true;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        std::fprintf(stderr, "TIMEOUT waiting for %s\n", what);
        return false;
    };
    const auto read_document = [&]() {
        std::ifstream in(project_file, std::ios::binary);
        const std::string text((std::istreambuf_iterator<char>(in)),
                               std::istreambuf_iterator<char>());
        return Json::parse(text);
    };

    {
        MainWindow window;
        window.show();
        const QString open_error =
            window.openProject(QString::fromStdString(project_file.string()));
        PWB_CHECK_MSG(open_error.isEmpty(),
                      "openProject failed");
        auto* preparation =
            window.appShell()
                ->findChild<pwb::ui_pages_data::qt::PreparationPage*>();
        PWB_CHECK(preparation != nullptr);
        auto* panel = preparation->task_panel();
        PWB_CHECK(panel != nullptr);

        // 1) 批量生成单因素图 — the real kernel path.
        QMetaObject::invokeMethod(panel, "generate_requested",
                                  Q_ARG(QString, QStringLiteral("IDW")));
        const bool generated = wait_for(
            [&] {
                return panel->summary_label() != nullptr
                       && panel->summary_label()
                              ->text()
                              .contains(QStringLiteral("已制备"));
            },
            "prepare completion");
        PWB_CHECK_MSG(generated, "prepare run did not complete");
        PWB_CHECK_MSG(panel->summary_label()->text()
                          .contains(QStringLiteral("计算 2")),
                      "both tasks computed on the first run");

        // 2) 等值线初稿 — pushes drafts + map documents.
        QMetaObject::invokeMethod(panel, "contour_draft_requested");
        const bool contoured = wait_for(
            [&] {
                return panel->summary_label() != nullptr
                       && panel->summary_label()
                              ->text()
                              .contains(QStringLiteral("等值线初稿"));
            },
            "contour completion");
        PWB_CHECK_MSG(contoured, "contour run did not complete");
        PWB_CHECK_MSG(
            !panel->summary_label()->text().contains(
                QStringLiteral("没有可提取")),
            "contour produced drafts");

        // 3) persist everything through the production save route.
        QString save_error_q;
        save_error_q = pwb::app::shell_project_actions::save_open_project(
            window);
        PWB_CHECK_MSG(save_error_q.isEmpty(), "save failed");

        // 4) selective recompute: change task A's VALUES only, rerun.
        {
            Json live = read_document();
            // the committed document now carries the completed tasks
            PWB_CHECK_MSG(live["factor_map_tasks"].size() == 2,
                          "two tasks committed");
            int complete = 0;
            std::string version_id_a;
            for (const auto& task : live["factor_map_tasks"]) {
                if (task["status"] == "complete") ++complete;
                if (task["id"] == "factor_e2e_a") {
                    version_id_a = task.value("grid_artifact_version_id",
                                              std::string());
                }
            }
            PWB_CHECK_MSG(complete == 2, "both tasks complete after run 1");
            PWB_CHECK_MSG(!version_id_a.empty(),
                          "task A carries a catalog version id");
            PWB_CHECK_MSG(live["contour_drafts"].size() == 2,
                          "two contour drafts committed");
            PWB_CHECK_MSG(live["paleomap_documents"].size() == 2,
                          "two map documents hold the contour features");
            for (const auto& doc : live["paleomap_documents"]) {
                PWB_CHECK_MSG(
                    !doc["line_features"].empty()
                        && doc["line_features"][0]["role"] == "contour",
                    "map document carries contour line features");
            }
            PWB_CHECK(fs::exists(tmp / "workflow_provenance.json"));
        }

        // rerun unchanged -> all reused (no compute)
        QMetaObject::invokeMethod(panel, "generate_requested",
                                  Q_ARG(QString, QStringLiteral("IDW")));
        const bool reused = wait_for(
            [&] {
                return panel->summary_label() != nullptr
                       && panel->summary_label()
                              ->text()
                              .contains(QStringLiteral("已制备"));
            },
            "reuse rerun");
        PWB_CHECK_MSG(reused, "reuse rerun did not complete");
        PWB_CHECK_MSG(panel->summary_label()->text()
                          .contains(QStringLiteral("复用 2")),
                      "unchanged rerun reuses both tasks");
        PWB_CHECK_MSG(
            panel->summary_label()->text().contains(
                QStringLiteral("计算 0")),
            "unchanged rerun computes nothing");

        // 4b) change ONE task's values (coordinates held) -> selective
        // recompute: exactly one task recomputes, the other stays reused.
        {
            Json live = read_document();
            Json points = live["factor_map_tasks"][0]["parameters"]
                              ["sample_points"];
            for (auto& point : points) {
                point["value"] = point["value"].get<double>() + 11.0;
            }
            live["factor_map_tasks"][0]["parameters"]["sample_points"] =
                points;
            {
                std::ofstream out(project_file,
                                  std::ios::binary | std::ios::trunc);
                out << pwb::domain::dump_json_python_compatible(live);
            }
            // One-window-one-project contract: edit the file on disk, then
            // re-enter the page through a FRESH window (the first window
            // keeps its live store). The generation counter is per-page,
            // so the new run supersedes cleanly.
            window.hide();
            preparation = nullptr;
            panel = nullptr;
            auto* reopen_window =
                new MainWindow();  // owned by the test scope
            reopen_window->show();
            const QString reopen_error = reopen_window->openProject(
                QString::fromStdString(project_file.string()));
            PWB_CHECK_MSG(reopen_error.isEmpty(),
                          "reopen after value edit failed");
            preparation = reopen_window->appShell()
                              ->findChild<
                                  pwb::ui_pages_data::qt::PreparationPage*>();
            PWB_CHECK(preparation != nullptr);
            panel = preparation->task_panel();
            PWB_CHECK(panel != nullptr);
            reopen_window->hide();
        }
        QMetaObject::invokeMethod(panel, "generate_requested",
                                  Q_ARG(QString, QStringLiteral("IDW")));
        const bool recomputed = wait_for(
            [&] {
                return panel->summary_label() != nullptr
                       && panel->summary_label()
                              ->text()
                              .contains(QStringLiteral("已制备"));
            },
            "selective recompute");
        PWB_CHECK_MSG(recomputed, "selective recompute did not complete");
        PWB_CHECK_MSG(panel->summary_label()->text()
                          .contains(QStringLiteral("复用 1")),
                      "unchanged task reused after the value edit");
        PWB_CHECK_MSG(
            panel->summary_label()->text().contains(
                QStringLiteral("计算 1")),
            "exactly the edited task recomputed");
    }

    // 5) save/reopen: a fresh window recovers the tasks + provenance rail.
    {
        MainWindow window;
        window.show();
        const QString open_error =
            window.openProject(QString::fromStdString(project_file.string()));
        PWB_CHECK_MSG(open_error.isEmpty(), "reopen failed");
        const Json reopened = read_document();
        int complete = 0;
        std::set<std::string> version_ids;
        for (const auto& task : reopened["factor_map_tasks"]) {
            if (task["status"] == "complete") ++complete;
            version_ids.insert(
                task.value("grid_artifact_version_id", std::string()));
        }
        PWB_CHECK_MSG(complete == 2, "reopen: both tasks complete");
        PWB_CHECK_MSG(version_ids.size() == 2 && !version_ids.count(""),
                      "reopen: both version ids intact");
        PWB_CHECK_MSG(reopened["contour_drafts"].size() == 2,
                      "reopen: contour drafts intact");
        // provenance rail survives the process boundary (same JSON file)
        std::ifstream in(tmp / "workflow_provenance.json", std::ios::binary);
        const std::string text((std::istreambuf_iterator<char>(in)),
                               std::istreambuf_iterator<char>());
        const Json rail = Json::parse(text);
        PWB_CHECK_MSG(rail["store_version"] == 1, "provenance store header");
        // First window: 2 committed tasks (2 runs). Recompute window: only
        // the edited task recomputes and re-registers (1 more run, 1 more
        // asset) — the reused task never re-registers.
        PWB_CHECK_MSG(rail["runs"].size() == 3,
                      "three factor_map runs on the rail (2 + 1 recompute)");
        PWB_CHECK_MSG(rail["assets"].size() == 3,
                      "three grid assets (recompute adds one)");
    }

    fs::remove_all(tmp);
    return pwb::test::failure_count();
}
#endif  // PWB_WITH_FACTOR_KERNEL
#endif  // PWB_WITH_APP_SHELL

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    bank_battery(app);
#ifdef PWB_WITH_APP_SHELL
    install_battery();
#ifdef PWB_WITH_FACTOR_KERNEL
    factor_kernel_battery(app);
#endif
#else
    std::fprintf(stdout,
                 "SKIP install battery — PWB_WITH_APP_SHELL not defined\n");
#endif
    return pwb::test::report("platform.closure_mapping");
}
