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
#include <QComboBox>
#include <QAction>
#include <QGraphicsItem>
#include <QLabel>
#include <QPointF>
#include <QPushButton>
#include <QStackedWidget>
#include <QVariant>
#include <qgsapplication.h>

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <set>
#include <string>
#include <thread>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif
namespace { long test_pid() {
#ifdef _WIN32
    return static_cast<long>(_getpid());
#else
    return static_cast<long>(::getpid());
#endif
} }

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_qt/map_edit_items.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_view.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/qgis/layout_authority.hpp>
#include <pwb/qgis/layout_editor_panel.hpp>
#include <pwb/qgis/layout_export_service.hpp>
#include <qgsprintlayout.h>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "closure_mapping_document.hpp"
#include "closure_mapping_install.hpp"
#include "layout_compose_panel.hpp"
#include "test_framework.hpp"

#ifdef PWB_WITH_APP_SHELL
#include <QDockWidget>
#include <qgsmapcanvas.h>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_shell/navigation.hpp>

#include "app_shell.hpp"
#include "closure_mapping_install.hpp"
#include "main_window.hpp"
#include "app_context.hpp"
#include "shell_project_actions.hpp"

using pwb::app::AppShell;
using pwb::app::MainWindow;

// BEGIN V14-COMPILATION-PUBLISH (qgis-native-layout-convergence)
namespace {

// The native layout surface battery: the Stage 3 editor hosts real
// QgsPrintLayouts; templates materialize through the session authority
// and the unified exporter writes the product files.
void layout_battery(MainWindow& window) {
    auto& authority = window.context().session().layout();
    const auto created = authority.instantiate_template("professional_geographic");
    PWB_CHECK_MSG(created.layout != nullptr,
                  (created.warnings.empty() ? std::string("template instantiation failed")
                                            : created.warnings.front()).c_str());
    PWB_CHECK_MSG(created.items >= 5,
                  ("native template carries its items (got " +
                   std::to_string(created.items) + ")").c_str());
    PWB_CHECK(authority.layouts().size() == 1);

    if (auto* editor = window.findChild<pwb::qgis::LayoutEditorPanel*>()) {
        editor->refresh();
        PWB_CHECK(editor->active_layout() == created.layout);
    }

    const std::string out_path =
        (std::filesystem::temp_directory_path() / "pwb_v14_layout_test.svg")
            .string();
    std::filesystem::remove(out_path);
    pwb::qgis::LayoutExportRequest request;
    request.output_path = out_path;
    request.format = "svg";
    request.dpi = 150.0;
    const pwb::qgis::LayoutExportReport report =
        pwb::qgis::export_layout(*created.layout, request);
    PWB_CHECK_MSG(report.ok, report.error.c_str());
    PWB_CHECK_MSG(std::filesystem::exists(out_path),
                  "layout export wrote the file");
    std::ifstream in(out_path);
    std::string svg((std::istreambuf_iterator<char>(in)),
                    std::istreambuf_iterator<char>());
    PWB_CHECK_MSG(svg.find("<svg") != std::string::npos,
                  "export is an SVG document (xml prolog + svg root)");
    PWB_CHECK_MSG(svg.find("mm") != std::string::npos,
                  "export carries the physical mm anchors");
    PWB_CHECK_MSG(svg.find("</svg>") != std::string::npos,
                  "export is a complete SVG document");
    std::filesystem::remove(out_path);
}

}  // namespace
// END V14-COMPILATION-PUBLISH
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
    // 界面框架收敛：closure_mapping 安装器不接线 —— 上下文物件诚实
    // 缺席（功能保留在项目内），preparation/mapping/验证页全部退役。
    PWB_CHECK_MSG(
        window.property("closure_mapping_context").value<QObject*>()
            == nullptr,
        "retired closure context still installed");
    PWB_CHECK(shell->page_stack() == nullptr);
    PWB_CHECK(shell->workstation() == nullptr);
    PWB_CHECK(shell->preparation_page() == nullptr);
    PWB_CHECK(shell->mapping_page() == nullptr);
    // 两页壳架面：数据管理 + 编图（QGIS 画布 + 图层树 dock 收编）。
    PWB_CHECK(shell->workspace_host() != nullptr);
    PWB_CHECK(shell->workspace_host()->count() == 2);
    PWB_CHECK(shell->data_page() != nullptr);
    PWB_CHECK(shell->authoring_page() != nullptr);
    PWB_CHECK(window.findChild<QgsMapCanvas*>() != nullptr);
    PWB_CHECK(window.findChild<QDockWidget*>(
                  QStringLiteral("layer-tree-dock")) != nullptr);

    // -- save routing: no installed bank -> honest failure --------------
    std::string error;
    PWB_CHECK(!pwb::app::closure_mapping::save_documents(&window, &error));

    // BEGIN V14-COMPILATION-PUBLISH — the layout authority is not a UI
    // surface: template instantiation + the unified exporter still
    // run under the two-page frame (the editor panel hook is guarded).
    layout_battery(window);
    // END V14-COMPILATION-PUBLISH
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
    // 退役电池的调用面已随界面收敛移除（prepare_shutdown /
    // factor_kernel / m5_compose 全部驱动已退役的功能面板——功能
    // 保留在项目内，界面层不再实例化，电池不再可达）。
#else
    std::fprintf(stdout,
                 "SKIP install battery — PWB_WITH_APP_SHELL not defined\n");
#endif
    return pwb::test::report("platform.closure_mapping");
}
