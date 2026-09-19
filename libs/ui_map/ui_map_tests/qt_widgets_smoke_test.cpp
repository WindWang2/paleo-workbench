// UI-05 — Qt widget smoke test (offscreen): the Qt-only shells construct
// and respond — dock manager + rails, layer tree, document panel, chrome
// panel. The QGIS-backed surfaces (DisplayMapCanvas, MapCanvasPanel,
// WorkAreaMapWidget, MappingPage) are covered by ui_map.qgis_smoke.

#include <QApplication>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QSignalSpy>
#include <QToolButton>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QWidget>

#include <string>
#include <vector>

#include <pwb/ui_map/map_chrome_panel.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/map_document_panel.hpp>
#include <pwb/ui_map/map_layer_tree.hpp>

#include "ui_map_test.hpp"

using namespace pwb::ui_map;

namespace {

Json doc(const std::string& id, const std::string& name,
         const Json& refs = Json::array()) {
    return Json{{"id", id},
                {"name", name},
                {"linked_target_horizon", "T3"},
                {"facies_polygons", Json::array({Json::object()})},
                {"well_overlays", Json::array({Json::object(), Json::object()})},
                {"reference_layers", refs}};
}

}  // namespace

PWB_TEST(dock_manager_panels) {
    MapDockManager manager;

    QWidget* layers_widget = new QWidget;
    QWidget* chrome_widget = new QWidget;
    manager.add_panel("layers", QStringLiteral("图层面板"), "layers",
                      layers_widget, "left", true, "mapping:layers");
    manager.add_panel("chrome", QStringLiteral("图面要素"), "chrome",
                      chrome_widget, "right", false, "mapping:chrome");

    QWidget* bottom_widget = new QWidget;
    bool apply_called = false;
    manager.register_bottom("bottom", QStringLiteral("底部工作区"), "bottom",
                            bottom_widget, [&apply_called]() {
                                apply_called = true;
                            }, "mapping:bottom");

    // panel_title hits — the frozen oracle expectations resolved through
    // the real registry ("mapping:" float keys resolve to panel keys).
    CHECK_EQ(manager.panel_title("layers"), std::string("图层面板"));
    CHECK_EQ(manager.panel_title("mapping:layers"), std::string("图层面板"));
    CHECK_EQ(manager.panel_title("mapping:bottom"),
             std::string("底部工作区"));
    // Fallback branch: rpartition tail, whole key, trailing colon.
    CHECK_EQ(manager.panel_title("missing:key"), std::string("key"));
    CHECK_EQ(manager.panel_title("no_colon"), std::string("no_colon"));
    CHECK_EQ(manager.panel_title("a:b:c"), std::string("c"));

    // Visibility toggles through the rail buttons.
    CHECK(manager.is_panel_visible("layers"));
    CHECK(!manager.is_panel_visible("chrome"));
    manager.set_panel_visible("chrome", true);
    CHECK(manager.is_panel_visible("chrome"));

    // Bottom user preference default true; the apply callback recomputes.
    CHECK(manager.bottom_user_visible());

    // 面板 menu: one action per panel + bottom entry.
    QMenu* menu = manager.panels_menu();
    CHECK(menu != nullptr && menu->actions().size() >= 3);
    delete menu;
    (void)apply_called;
}

PWB_TEST(layer_tree_documents) {
    MapLayerTree tree;
    std::vector<Json> documents{
        doc("m1", "图A", Json::array({Json{{"id", "ref1"},
                                          {"name", "参考一"}}})),
        doc("m2", "图B")};
    tree.set_documents(documents);
    tree.set_active_document(&documents.front());

    // Two document rows keyed doc:<id>.
    const auto keys = tree.document_keys();
    CHECK_EQ(static_cast<long long>(keys.size()), 2);
    CHECK_EQ(keys.at(0), std::string("doc:m1"));
    CHECK_EQ(keys.at(1), std::string("doc:m2"));

    // The active document carries the four layer rows (+ reference group).
    const auto layer_keys = tree.layer_item_keys();
    CHECK_EQ(static_cast<long long>(layer_keys.size()), 4);
    CHECK_EQ(layer_keys.at(0), std::string("facies"));
    CHECK_EQ(layer_keys.at(3), std::string("label"));

    // Visibility defaults true; lock flag round-trips.
    CHECK(tree.layer_is_visible("facies"));
    CHECK(!tree.layer_is_locked("well"));
    tree.set_layer_locked("well", true);
    CHECK(tree.layer_is_locked("well"));

    // Switching the active document repopulates the subtree on the new row.
    tree.set_active_document(&documents.back());
    const auto keys2 = tree.layer_item_keys();
    CHECK_EQ(static_cast<long long>(keys2.size()), 4);
    // Structure parity: a single 图件 root at top level carrying both
    // document rows (Python _ROOT_KEY reconcile under invisibleRootItem).
    CHECK(tree.tree() != nullptr &&
          tree.tree()->topLevelItemCount() == 1 &&
          tree.tree()->topLevelItem(0) != nullptr &&
          tree.tree()->topLevelItem(0)->childCount() == 2);
}

PWB_TEST(document_panel_state) {
    MapDocumentPanel panel;
    panel.update_state({});
    CHECK_EQ(panel.name_text(), std::string("未选择古地理图"));
    CHECK_EQ(panel.horizon_text(), std::string("未设置"));
    CHECK_EQ(panel.polygon_count_text(), std::string("0 个相带"));
    CHECK_EQ(panel.well_count_text(), std::string("0 口井"));

    std::vector<Json> documents{doc("m1", "图A"), doc("m2", "图B")};
    panel.update_state(documents);
    // The last document is the active fallback (active_map_document
    // parity): 图B, horizon T3, 1 polygon, 2 wells.
    CHECK_EQ(panel.name_text(), std::string("图B"));
    CHECK_EQ(panel.horizon_text(), std::string("T3"));
    CHECK_EQ(panel.polygon_count_text(), std::string("1 个相带"));
    CHECK_EQ(panel.well_count_text(), std::string("2 口井"));
    CHECK(panel.document_list() != nullptr &&
          panel.document_list()->count() == 2);
}

PWB_TEST(chrome_panel_state) {
    MapChromePanel panel;
    QSignalSpy spy(&panel, &MapChromePanel::chrome_changed);

    panel.update_state(Json{{"name", "图A"},
                            {"map_chrome",
                             Json{{"title", "工区位置图"},
                                  {"elements",
                                   Json::array({"图例", "指北针"})}}}});
    CHECK_EQ(panel.title_text(), std::string("工区位置图"));
    CHECK(panel.elements_text().find("图例") != std::string::npos);
    // update_state must not emit (blockSignals parity).
    CHECK_EQ(static_cast<long long>(spy.count()), 0);
    const Json chrome = panel.current_chrome();
    CHECK_EQ(chrome.at("title").get<std::string>(),
             std::string("工区位置图"));

    // Empty document -> fallback title 未设置 + default elements.
    panel.update_state(Json::object());
    CHECK_EQ(panel.title_text(), std::string("未设置"));

    // Editing the title emits chrome_changed with the new title.
    panel.update_state(Json{{"name", "图B"}});
    spy.clear();
    QLineEdit* edit = panel.findChild<QLineEdit*>();
    CHECK(edit != nullptr);
    if (edit != nullptr) {
        edit->setText(QStringLiteral("新标题"));
        emit edit->editingFinished();
    }
    CHECK(spy.count() >= 1);
    if (spy.count() >= 1) {
        const Json emitted =
            spy.at(0).at(0).value<pwb::ui_map::Json>();
        CHECK_EQ(emitted.at("title").get<std::string>(),
                 std::string("新标题"));
    }
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    qRegisterMetaType<pwb::ui_map::Json>("pwb::ui_map::Json");
    return pwb_test::run_all();
}
