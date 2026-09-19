// Minimal production consumer of Pwb::Geo3DViz (A-line embedding sample
// and offscreen smoke canary): builds a small demo geomodel scene through
// the controller (wells + horizon + fault, demo provenance), opens the
// native viewport, takes a screenshot when GL is available and exits.
//
//   QT_QPA_PLATFORM=offscreen ./geo3d_viewer_example   (GL-less degrade)
//   ./geo3d_viewer_example                             (windowed)

#include <QApplication>
#include <QImage>
#include <QTimer>

#include <cstdio>

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/geomodel/builders.hpp>

using namespace pwb::geo3d_viz;
using pwb::geomodel::DomainObject;

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    Geo3DViewportWidget widget;
    Geo3DWorkspaceController controller(
        [&widget]() { return &widget.scene_manager(); });
    controller.set_viewport(&widget);

    // Demo scene (honest demo provenance, like the Python demo ingest).
    DomainObject well = pwb::geomodel::build_simplified_vertical_well(
        "demo-well", {10.0, 10.0, 0.0}, 120.0, "demo");
    well.provenance.demo = true;
    controller.add_object(std::move(well));

    DomainObject horizon;
    horizon.object_id = "horizon:demo-top";
    horizon.name = "demo top";
    horizon.crs = "demo";
    horizon.origin = {0.0, 0.0};
    horizon.spacing = {10.0, 10.0};
    horizon.z_grid = {
        {0.0, 1.0, 2.0, 1.0, 0.0},
        {1.0, 2.0, 3.0, 2.0, 1.0},
        {2.0, 3.0, std::nan(""), 3.0, 2.0},
        {1.0, 2.0, 3.0, 2.0, 1.0},
        {0.0, 1.0, 2.0, 1.0, 0.0},
    };
    horizon.provenance.demo = true;
    controller.add_object(std::move(horizon));

    DomainObject fault;
    fault.object_id = "fault:demo-curtain";
    fault.name = "demo curtain";
    fault.crs = "demo";
    fault.representation = "curtain_2p5d";
    fault.verts = {{0, 0, 0}, {80, 80, 0}, {80, 80, 120}, {0, 0, 120}};
    fault.faces = {{0, 1, 2}, {0, 2, 3}};
    fault.provenance.demo = true;
    controller.add_object(std::move(fault));

    controller.fit_all();
    widget.resize(800, 600);
    widget.show();

    QObject::connect(
        &widget, &Geo3DViewportWidget::coordinate_hovered, &widget,
        [&controller](const QString& text) {
            if (!text.isEmpty()) {
                std::printf("coord: %s\n", text.toUtf8().constData());
            }
            (void)controller;
        });

    QTimer::singleShot(400, &app, [&app, &widget, &controller]() {
        const QImage shot = widget.grab_scene_screenshot();
        if (!shot.isNull()) {
            std::printf("screenshot: %dx%d\n", shot.width(), shot.height());
        } else {
            std::printf("screenshot: unavailable (no GL context)\n");
        }
        const auto state = controller.save_state();
        std::printf("state keys: %zu objects (demo objects are never "
                    "persisted)\n",
                    state.contains("objects") ? state["objects"].size() : 0);
        app.quit();
    });

    return app.exec();
}
