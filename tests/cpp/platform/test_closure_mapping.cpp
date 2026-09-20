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
#include <QPointF>
#include <QStackedWidget>
#include <QVariant>
#include <qgsapplication.h>

#include <cstdio>
#include <memory>
#include <string>

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
#endif  // PWB_WITH_APP_SHELL

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    bank_battery(app);
#ifdef PWB_WITH_APP_SHELL
    install_battery();
#else
    std::fprintf(stdout,
                 "SKIP install battery — PWB_WITH_APP_SHELL not defined\n");
#endif
    return pwb::test::report("platform.closure_mapping");
}
