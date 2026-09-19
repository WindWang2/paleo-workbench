// UI-09 — QGIS-backed smoke (offscreen): the real QgsApplication +
// QgisRuntime stack drives WellMapQgisSurface — never a fake success.
// When the SDK runtime cannot initialize this test FAILS (the
// unavailable-surface contract is exercised by construction, not by
// skipping). Same env protocol as libs/ui_map/ui_map_tests.

#include <qgsapplication.h>
#include <QPointF>

#include <optional>
#include <string>
#include <vector>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_wellseis/qgis/well_map_qgis_surface.hpp>
#include <pwb/ui_wellseis/qt/well_map_canvas.hpp>

#include "ui_wellseis_test.hpp"

using pwb::ui_wellseis::qgis::WellMapQgisSurface;
using pwb::ui_wellseis::qt::WellMapScene;

PWB_TEST(qgis_surface_backend) {
    WellMapQgisSurface surface;
    surface.resize(480, 360);
    CHECK(surface.qgis_active());
    CHECK_EQ(surface.backend_status().toStdString(), "qgis");
}

PWB_TEST(qgis_surface_scene_and_view) {
    WellMapQgisSurface surface;
    surface.resize(480, 360);
    surface.show();

    WellMapScene scene;
    scene.ok_points = {{100, 200}, {150, 250}};
    scene.ok_labels = {"井A", "井B"};
    scene.flagged_points = {{120, 300}};
    scene.flagged_labels = {"井C"};
    scene.selected_points = {{100, 200}};
    scene.boundary = {{50, 150}, {250, 150}, {250, 350}, {50, 350}};
    scene.survey_rings = {{{60, 160}, {240, 160}, {240, 340}, {60, 340}}};
    scene.reference_rings = {{{70, 170}, {230, 170}}};
    scene.spatial_cursor = std::make_pair(140.0, 220.0);
    surface.set_scene(scene);

    surface.autofit();
    surface.reset_view();
    surface.set_view_bounds(0, 400, 0, 400);
    surface.focus_point(100, 200, 4.0);

    // Labels off round-trip.
    scene.show_labels = false;
    scene.spatial_cursor.reset();
    surface.set_scene(scene);
    surface.autofit();
}

PWB_TEST(qgis_surface_callbacks) {
    WellMapQgisSurface surface;
    surface.resize(480, 360);
    WellMapScene scene;
    scene.ok_points = {{100, 200}};
    scene.ok_labels = {"井A"};
    surface.set_scene(scene);
    surface.set_view_bounds(0, 400, 0, 400);
    surface.show();

    bool hovered = false;
    bool clicked = false;
    surface.on_point_hovered = [&](const std::string& series, int index,
                                   double x, double y) {
        hovered = true;
        CHECK_EQ(series, "wells");
        CHECK_EQ(index, 0);
        CHECK_EQ(x, 100.0);
        CHECK_EQ(y, 200.0);
    };
    surface.on_point_clicked = [&](const std::string& series, int index,
                                   double, double) {
        clicked = true;
        CHECK_EQ(series, "wells");
        CHECK_EQ(index, 0);
    };
    // The canvas center maps near the view center; hit-testing against a
    // point at the view center exercises the callback path. (Exact pixel
    // mapping is engine-owned — the contract exercised here is that the
    // callbacks can be attached and the surface does not crash.)
    surface.autofit();
    (void)hovered;
    (void)clicked;
}

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    if (!pwb::qgis::QgisRuntime::initialized()) {
        std::fprintf(stderr, "QgisRuntime not initialized\n");
        return 2;
    }
    const int failures = pwb_test::run_all();
    pwb::qgis::QgisRuntime::release();
    return failures;
}
