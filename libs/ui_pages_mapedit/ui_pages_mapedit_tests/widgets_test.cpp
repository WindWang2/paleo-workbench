// UI-08 — Qt widget/scene parity tests (offscreen): MapEditScene
// load/select/undo/dirty/vertex ops, MapEditToolbar tools + preview,
// BoundaryPanel defaults, FactorPreviewGrid filtering,
// MapTopologyIssuePanel rows + locate, MapAttributeTable edit signals,
// MapWorkbenchBottom tabs, InspectorPanel overview/clear.

#include <pwb/ui_pages_mapedit/boundary_panel.hpp>
#include <pwb/ui_pages_mapedit/factor_preview_grid.hpp>
#include <pwb/ui_pages_mapedit/inspector_panel.hpp>
#include <pwb/ui_pages_mapedit/map_attribute_table.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_toolbar.hpp>
#include <pwb/ui_pages_mapedit/map_topology_issue_panel.hpp>
#include <pwb/ui_pages_mapedit/map_workbench_bottom.hpp>

#include <pwb/ui_pages_mapedit/table_preview_widget.hpp>

#include <QApplication>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QGridLayout>
#include <QLabel>
#include <QPushButton>
#include <QSignalSpy>
#include <QTableWidget>

#include "ui_pages_mapedit_test.hpp"

using pwb::domain::Json;
using namespace pwb::ui_pages_mapedit;

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

Json well_record(const char* id, double x, double y) {
    return Json{{"id", id},
                {"kind", "well"},
                {"name", "井1"},
                {"coordinates", Json::array({x, y})}};
}

}  // namespace

PWB_TEST(toolbar_defaults_and_signals) {
    MapEditToolbar toolbar;
    PWB_CHECK_EQ(toolbar.current_tool().toStdString(), "select");
    PWB_CHECK_EQ(tool_ids().size(), 6);
    PWB_CHECK_EQ(tool_label(QStringLiteral("vertex")).toStdString(), "节点");

    QSignalSpy tool_spy(&toolbar, &MapEditToolbar::tool_changed);
    toolbar.set_tool(QStringLiteral("move"));
    PWB_CHECK_EQ(tool_spy.count(), 1);
    PWB_CHECK_EQ(tool_spy.takeFirst().at(0).toString().toStdString(),
                 "move");
    PWB_CHECK_EQ(toolbar.current_tool().toStdString(), "move");
    // Re-applying the same tool does not re-emit.
    toolbar.set_tool(QStringLiteral("move"));
    PWB_CHECK_EQ(tool_spy.count(), 0);
    // Unknown tool id → std::invalid_argument (Python KeyError parity).
    bool threw = false;
    try {
        toolbar.set_tool(QStringLiteral("bogus"));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    PWB_CHECK(threw);
}

PWB_TEST(toolbar_snap_and_preview) {
    MapEditToolbar toolbar;
    QSignalSpy snap_spy(&toolbar, &MapEditToolbar::snap_toggled);
    toolbar.snap_btn->click();
    PWB_CHECK_EQ(snap_spy.count(), 1);

    toolbar.set_preview_mode(true);
    PWB_CHECK(toolbar.is_preview_mode());
    // Preview disables editing controls; the snap toggle stays in sync.
    PWB_CHECK(!toolbar.snap_btn->isEnabled());
    PWB_CHECK(!toolbar.topology_btn->isEnabled());
    PWB_CHECK(!toolbar.merge_btn->isEnabled());
    toolbar.set_preview_mode(false);
    PWB_CHECK(toolbar.snap_btn->isEnabled());
}

PWB_TEST(boundary_panel_defaults) {
    BoundaryPanel panel;
    PWB_CHECK(panel.title_label != nullptr);
    PWB_CHECK_NEAR(panel.threshold_spin->value(), 0.55, 1e-9);
    PWB_CHECK_NEAR(panel.threshold_spin->minimum(), 0.0, 1e-9);
    PWB_CHECK_NEAR(panel.threshold_spin->maximum(), 1.0, 1e-9);
    PWB_CHECK_NEAR(panel.threshold_spin->singleStep(), 0.05, 1e-9);
    PWB_CHECK_EQ(panel.threshold_spin->decimals(), 2);
    PWB_CHECK_EQ(panel.smoothing_combo->count(), 3);
    PWB_CHECK_EQ(
        panel.smoothing_combo->itemText(1).toStdString(), "中");
    PWB_CHECK_EQ(panel.smoothing_combo->currentIndex(), 1);
    PWB_CHECK_NEAR(panel.area_spin->singleStep(), 0.1, 1e-9);
    PWB_CHECK_EQ(panel.area_spin->decimals(), 1);
    PWB_CHECK_EQ(panel.area_spin->suffix().toStdString(), " km²");
    PWB_CHECK(panel.generate_btn != nullptr);
}

PWB_TEST(factor_grid_filters_completed) {
    FactorPreviewGrid grid;
    grid.update_state({
        Json{{"id", "t1"}, {"status", "complete"},
             {"factor_type", "sand"}},
        Json{{"id", "t2"}, {"status", "running"},
             {"factor_type", "sand"}},
        Json{{"id", "t3"}, {"status", "complete"},
             {"factor_type", "mud"}},
    });
    // Only completed tasks materialize cards.
    PWB_CHECK_EQ(grid.findChildren<FactorPreviewCard*>().size(), 2);
    // Empty grid → no cards (empty state covers the grid).
    grid.update_state({});
    PWB_CHECK_EQ(grid.findChildren<FactorPreviewCard*>().size(), 0);
}

PWB_TEST(topology_panel_rows_and_locate) {
    MapTopologyIssuePanel panel;
    panel.set_issues({QVariantMap{{"feature_id", "f1"},
                                  {"message", "自相交"},
                                  {"severity", "error"}},
                      QVariantMap{{"feature_id", "f2"},
                                  {"message", "间隙"},
                                  {"severity", "warning"}}});
    PWB_CHECK_EQ(panel.issues().size(), 2);
    PWB_CHECK(panel.summary != nullptr);
    PWB_CHECK(panel.summary->text().contains('2'));
    QSignalSpy spy(&panel, &MapTopologyIssuePanel::locate_requested);
    panel.table->emit_item_double_clicked(
        panel.table->model()->index(0, 0));
    PWB_CHECK_EQ(spy.count(), 1);
    PWB_CHECK_EQ(spy.takeFirst().at(0).toString().toStdString(), "f1");
}

PWB_TEST(attribute_table_edit_signal) {
    MapAttributeTable table;
    const Json feature = facies_record("f-1");
    table.set_feature(feature);
    PWB_CHECK(table.table->rowCount() >= 3);
    // Find the "name" row and edit it → property_changed(feature_id,...).
    int name_row = -1;
    for (int r = 0; r < table.table->rowCount(); ++r) {
        auto* key_item = table.table->item(r, 0);
        if (key_item != nullptr && key_item->text() == "name") {
            name_row = r;
            break;
        }
    }
    PWB_CHECK(name_row >= 0);
    QSignalSpy spy(&table, &MapAttributeTable::property_changed);
    table.table->item(name_row, 1)->setText(QStringLiteral("三角洲"));
    PWB_CHECK_EQ(spy.count(), 1);
    const auto args = spy.takeFirst();
    PWB_CHECK_EQ(args.at(0).toString().toStdString(), "f-1");
    PWB_CHECK_EQ(args.at(1).toString().toStdString(), "name");
    PWB_CHECK_EQ(args.at(2).toString().toStdString(), "三角洲");
}

PWB_TEST(workbench_bottom_tabs) {
    MapWorkbenchBottom bottom;
    // attributes / topology / factor shelf tabs exist.
    PWB_CHECK_EQ(bottom.count(), 3);
    const Json feature = facies_record("f-9");
    bottom.set_feature(feature);
    bottom.set_collapsed(true);
    PWB_CHECK(!bottom.isVisible());
}

PWB_TEST(scene_load_document_features) {
    MapEditScene scene;
    Json doc = Json::object();
    doc["facies_polygons"] = Json::array({facies_record("f-1")});
    doc["well_overlays"] =
        Json::array({well_record("w-1", 3.0, 3.0)});
    scene.load_document(&doc);
    PWB_CHECK_EQ(scene.feature_count(), 2);
    PWB_CHECK(scene.item_by_id("f-1") != nullptr);
    PWB_CHECK(scene.item_by_id("w-1") != nullptr);
    PWB_CHECK_EQ(scene.current_tool(), "select");
    // Hit path: index candidates → api.hit_test.
    const auto hit = scene.hit_test_at(3.0, 3.0, 0.5);
    PWB_CHECK(hit.has_value());
    PWB_CHECK_EQ(*hit, "w-1");
    // Layer visibility gates the index at query time.
    scene.set_layer_visible("well", false);
    const auto hit2 = scene.hit_test_at(3.0, 3.0, 0.5);
    PWB_CHECK(!hit2.has_value() || *hit2 != "w-1");
    scene.set_layer_visible("well", true);
}

PWB_TEST(scene_dirty_and_undo) {
    MapEditScene scene;
    Json doc = Json::object();
    doc["facies_polygons"] = Json::array({facies_record("f-1")});
    scene.load_document(&doc);
    QSignalSpy dirty_spy(&scene, &MapEditScene::document_dirty_changed);
    PWB_CHECK(!scene.is_dirty());
    // Property change → dirty + undoable.
    PWB_CHECK(scene.apply_property_change("f-1", "name",
                                          Json("滨岸")));
    PWB_CHECK(scene.is_dirty());
    PWB_CHECK_EQ(dirty_spy.count(), 1);
    PWB_CHECK(scene.undo());
    PWB_CHECK(!scene.is_dirty());
    PWB_CHECK(scene.redo());
    PWB_CHECK(scene.is_dirty());
}

PWB_TEST(scene_vertex_ops_undoable) {
    MapEditScene scene;
    Json doc = Json::object();
    doc["facies_polygons"] = Json::array({facies_record("f-1")});
    scene.load_document(&doc);
    // apply_set_vertex → undoable VertexEditCommand.
    PWB_CHECK(scene.apply_set_vertex("f-1", 1, 12.0, 0.0));
    PWB_CHECK(scene.is_dirty());
    PWB_CHECK(scene.undo());
    // Insert/delete also route through commands.
    PWB_CHECK(scene.apply_insert_vertex("f-1", 1, 5.0, 0.0));
    PWB_CHECK(scene.undo());
    PWB_CHECK(!scene.apply_delete_vertex("f-1", 99));
}

PWB_TEST(scene_create_feature_and_export) {
    MapEditScene scene;
    Json doc = Json::object();
    scene.load_document(&doc);
    const auto created = scene.create_feature(facies_record("f-new"));
    PWB_CHECK(created.has_value());
    PWB_CHECK_EQ(*created, "f-new");
    PWB_CHECK_EQ(scene.feature_count(), 1);
    const auto records = scene.features_to_records();
    PWB_CHECK_EQ(records.size(), 1);
    PWB_CHECK_EQ(records[0].at("id").get<std::string>(), "f-new");
}

PWB_TEST(scene_snap_settings) {
    MapEditScene scene;
    PWB_CHECK_NEAR(scene.snap_tolerance(), kDefaultSnapTol, 1e-9);
    PWB_CHECK(!scene.snap_enabled());
    scene.set_snap_enabled(true);
    PWB_CHECK(scene.snap_enabled());
    scene.set_snap_tolerance(12.0);
    PWB_CHECK_NEAR(scene.snap_tolerance(), 12.0, 1e-9);
}

PWB_TEST(inspector_empty_and_clear) {
    InspectorPanel panel;
    // isHidden() mirrors the Python show()/hide() state (widget unshown).
    PWB_CHECK(panel.tabs->isHidden());
    // A duck-typed generic asset → overview populated.
    auto handle = pwb::ui_data_core::make_asset_handle(
        pwb::ui_data_core::GenericAsset{Json{
            {"id", "a-1"}, {"name", "测试资产"},
            {"type", "geojson"}, {"format", "geojson"},
            {"path", "/tmp/a.geojson"},
        }});
    panel.update_asset(handle);
    PWB_CHECK(!panel.tabs->isHidden());
    PWB_CHECK(panel.current_view() != nullptr);
    PWB_CHECK_EQ(panel.current_view()->name, "测试资产");
    PWB_CHECK(panel.overview_table->rowCount() >= 5);
    panel.clear_asset();
    PWB_CHECK(panel.tabs->isHidden());
    PWB_CHECK(panel.current_view() == nullptr);
}

PWB_TEST_MAIN_QAPP()
