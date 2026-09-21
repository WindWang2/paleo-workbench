// UI-05 — QGIS-backed smoke (offscreen): the real QgsApplication +
// QgisRuntime stack drives DisplayMapCanvas / MapCanvasPanel /
// WorkAreaMapWidget / MappingPage — never a fake success. When the SDK
// runtime cannot initialize this test FAILS (the unavailable-surface
// contract is exercised separately by construction, not by skipping).

#include <qgsapplication.h>
#include <QPointF>
#include <QSignalSpy>

#include <optional>
#include <string>
#include <vector>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/ui_map/map_canvas_panel.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/map_layer_tree.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_map/workarea_map_widget.hpp>

#include "ui_map_test.hpp"

using namespace pwb::ui_map;

namespace {

Json point_feature(const std::string& well_id, double x, double y) {
    return Json{
        {"type", "Feature"},
        {"geometry",
         Json{{"type", "Point"}, {"coordinates", Json::array({x, y})}}},
        {"properties", Json{{"well_id", well_id}, {"name", well_id}}}};
}

// The snapshot shape DisplayMapCanvas mirrors (workarea vocabulary).
Json workarea_snapshot() {
    return Json{
        {"project_crs", "EPSG:4326"},
        {"layers",
         Json::array(
             {Json{{"id", "home_workarea:wells"},
                   {"name", "井位"},
                   {"layer_type", "vector"},
                   {"crs", "EPSG:4326"},
                   {"features",
                    Json::array({point_feature("w1", 10.0, 10.0),
                                 point_feature("w2", 20.0, 20.0)})}},
              Json{{"id", "home_workarea:wells_flagged"},
                   {"name", "井位（坐标待处理）"},
                   {"layer_type", "vector"},
                   {"crs", "EPSG:4326"},
                   {"features",
                    Json::array({point_feature("w3", 10.0, 40.0)})}}})}};
}

Json project_with_well(const std::string& well_id) {
    return Json{
        {"wells",
         Json::array({Json{{"id", well_id}, {"name", well_id}}})},
        {"seismic_surveys", Json::array()},
        {"entity_asset_links", Json::array()},
        {"geological_entities", Json::array()},
        {"workarea", Json(nullptr)},
        {"coordinate", Json{{"project_crs", "EPSG:4326"}}}};
}

}  // namespace

PWB_TEST(display_canvas_backend) {
    DisplayMapCanvas canvas;
    // Square canvas: QgsMapCanvas::setExtent expands the requested extent
    // to the viewport aspect ratio — a square viewport keeps a square
    // extent verbatim so the zoom bounds stay deterministic.
    canvas.resize(400, 400);
    CHECK(canvas.backend_available());
    CHECK_EQ(canvas.backend_status().toStdString(), std::string("qgis"));

    // Empty snapshot -> clean mirror, no failures.
    canvas.set_layer_snapshot(Json::object());
    CHECK(canvas.mirror_failures().empty());
    CHECK_EQ(canvas.backend_status().toStdString(), std::string("qgis"));

    // Real vector snapshot mirrors into the session project.
    canvas.set_layer_snapshot(workarea_snapshot());
    CHECK(canvas.mirror_failures().empty());
    CHECK(canvas.snapshot().at("layers").size() == 2);
    CHECK(canvas.snapshot_source_version_ids().empty());

    // Extent + zoom + history navigation.
    canvas.set_extent(Extent{0.0, 0.0, 100.0, 100.0});
    Extent e = canvas.view_extent();
    CHECK(e[0] < 1.0 && e[2] > 99.0);
    const double width_before_zoom = e[2] - e[0];
    canvas.zoom_by(0.5);
    e = canvas.view_extent();
    // Relative check: the live extent halves (aspect-fit may expand the
    // requested box, but zoom still scales the ADJUSTED extent by 0.5).
    CHECK(e[2] - e[0] < width_before_zoom * 0.75);
    CHECK(canvas.can_previous_extent());
    CHECK(canvas.previous_extent());
    e = canvas.view_extent();
    CHECK(e[2] - e[0] > width_before_zoom * 0.75);
    CHECK(canvas.next_extent());

    // map->screen is finite inside the extent; invalid zoom throws.
    const auto px = canvas.map_to_screen(50.0, 50.0);
    CHECK(px.has_value());
    bool threw = false;
    try {
        canvas.zoom_by(0.0);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
    CHECK(canvas.map_units_per_pixel() > 0.0);

    // Overlay provider feeds the decoration layer without throwing.
    // The contract takes a cached const Json& — per-frame rebuild is the
    // regression #1392 removed.
    canvas.set_overlay_provider([]() -> const Json& {
        static const Json state{
            {"decorations",
             Json{{"title", "工区图"},
                  {"elements", Json::array({"比例尺", "指北针"})},
                  {"legend_items", Json::array()}}}};
        return state;
    });
    canvas.update();  // force a repaint path under offscreen

    // Mirror failure honesty: a non-vector layer reports, not crashes.
    canvas.set_layer_snapshot(
        Json{{"layers",
              Json::array({Json{{"id", "r1"},
                                {"layer_type", "raster"},
                                {"name", "栅格"}}})}});
    CHECK(!canvas.mirror_failures().empty());
    CHECK(canvas.backend_status().toStdString().find("degraded") !=
          std::string::npos);

    // Idempotent shutdown.
    canvas.shutdown();
    canvas.shutdown();
    CHECK(!canvas.backend_available());
}

PWB_TEST(canvas_panel_surfaces) {
    MapCanvasPanel panel;
    CHECK_EQ(panel.current_surface().toStdString(), std::string("empty"));
    panel.load_preview(Json::array());
    CHECK_EQ(panel.current_surface().toStdString(), std::string("empty"));
    panel.load_preview(
        Json::array({Json{{"type", "Feature"},
                          {"geometry",
                           Json{{"type", "Point"},
                                {"coordinates", Json::array({1.0, 2.0})}}}}}));
    CHECK_EQ(panel.current_surface().toStdString(), std::string("canvas"));
    CHECK(panel.canvas() != nullptr && panel.canvas()->backend_available());
}

PWB_TEST(workarea_widget_flow) {
    WorkAreaMapWidget widget(nullptr, "工区图", true);
    widget.resize(400, 300);
    QSignalSpy selected(&widget, &WorkAreaMapWidget::well_selected);
    QSignalSpy activated(&widget, &WorkAreaMapWidget::well_activated);

    CHECK(!widget.has_snapshot());
    widget.set_project(project_with_well("w1"),
                       [](const Json&) { return workarea_snapshot(); });
    CHECK(widget.has_snapshot());
    CHECK(widget.snapshot().at("layers").size() == 2);

    // Same project -> signature cache skips the rebuild (snapshot kept).
    widget.set_project(project_with_well("w1"),
                       [](const Json&) {
                           return Json{{"layers", Json::array()}};
                       });
    CHECK(widget.snapshot().at("layers").size() == 2);

    // Selection + zoom.
    widget.select_well("w2", true);
    CHECK_EQ(widget.selected_well_id(), std::string("w2"));
    widget.zoom_to_all();
    CHECK(widget.current_half_span() >= 1.0);

    // emit_signal=True re-emits for a non-empty id (Python parity).
    widget.select_well("w1", false, true);
    CHECK_EQ(static_cast<long long>(selected.count()), 1);
    CHECK_EQ(static_cast<long long>(activated.count()), 0);

    widget.shutdown();
    widget.shutdown();
}

PWB_TEST(mapping_page_shell) {
    MappingPage page;
    page.resize(1200, 800);
    CHECK(page.dock_manager() != nullptr);
    CHECK(page.float_controller() != nullptr);
    CHECK(page.layer_tree() != nullptr);
    CHECK(page.chrome_panel() != nullptr);
    CHECK(page.canvas_panel() != nullptr);
    CHECK(page.unified_canvas() != nullptr);
    CHECK(page.bottom_workbench() != nullptr);
    CHECK(page.status_bar() != nullptr);
    CHECK(!page.is_preview_mode());
    CHECK(!page.is_canvas_priority());
    CHECK(!page.is_dirty());

    // Documents reconcile: active falls back to the last document.
    std::vector<Json> docs{
        Json{{"id", "m1"}, {"name", "图A"},
             {"linked_target_horizon", "T3"}},
        Json{{"id", "m2"}, {"name", "图B"},
             {"linked_target_horizon", "T5"}}};
    QSignalSpy ctx_spy(&page, &MappingPage::mapping_context_changed);
    page.update_state(docs, "m1");
    CHECK(page.active_document() != nullptr);
    CHECK_EQ(page.active_document()->at("id").get<std::string>(),
             std::string("m1"));
    const Json ctx = page.mapping_context();
    CHECK_EQ(ctx.at("map_name").get<std::string>(), std::string("图A"));
    CHECK_EQ(ctx.at("horizon").get<std::string>(), std::string("T3"));
    CHECK(ctx.at("dirty").get<bool>() == false);
    CHECK(ctx_spy.count() >= 1);

    // prefer_id miss -> last document wins (active_map_document parity).
    page.update_state(docs, "missing");
    CHECK_EQ(page.active_document()->at("id").get<std::string>(),
             std::string("m2"));

    // Mode rules: preview flips the center stack + hides the bottom.
    page.set_preview_mode(true);
    CHECK(page.is_preview_mode());
    CHECK_EQ(page.mapping_context().at("preview").get<bool>(), true);
    page.set_preview_mode(false);
    page.set_canvas_priority(true);
    CHECK(page.is_canvas_priority());
    page.apply_mode_ui();

    // Dock splitter persistence round-trips through the fallback chain.
    const auto sizes = page.saved_dock_splitter_sizes();
    CHECK(sizes.size() >= 2);

    // Bottom height cap constant is the frozen 220.
    CHECK_EQ(static_cast<long long>(kBottomDockedMaxHeight), 220);
}

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    qRegisterMetaType<pwb::ui_map::Json>("pwb::ui_map::Json");
    pwb::qgis::QgisRuntime::acquire();
    if (!pwb::qgis::QgisRuntime::initialized()) {
        std::fprintf(stderr, "QgisRuntime not initialized\n");
        return 2;
    }
    const int failures = pwb_test::run_all();
    pwb::qgis::QgisRuntime::release();
    return failures;
}
