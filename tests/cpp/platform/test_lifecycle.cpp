// platform.lifecycle.cycles — Oracle 5: >=20 automatic open/close cycles
// (session + canvas + tree + layer + one edit + commit) with the contract
// teardown order; a crash anywhere fails the process. The 500-cycle soak +
// sanitizers are an integration/stability gate and are NOT claimed here.

#include <qgsapplication.h>
#include <QTemporaryDir>

#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/edit_controller.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");
    const std::filesystem::path staged_dir =
        std::filesystem::path(temp_dir.path().toStdWString()) / "staged";

    constexpr int kCycles = 20;
    int completed = 0;
    for (int cycle = 0; cycle < kCycles; ++cycle) {
        pwb::qgis::MapSession session;
        QgsMapCanvas* canvas = session.createCanvas(nullptr);
        auto* view = session.createLayerTree(nullptr);
        PWB_CHECK(canvas != nullptr && view != nullptr);

        std::string error;
        pwb::qgis::LayerBinding binding{
            "cycle.layer", "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "cycle", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, error);

        pwb::qgis::EditController edit(session);
        PWB_CHECK(edit.start_editing("cycle.layer").empty());
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        // Commit persists into this cycle's GPKG working copy, so alternate
        // the move direction — a monotone drift walks vertex 0 past the
        // right edge after ~17 cycles and trips the topology gate.
        const double dir = (cycle % 2 == 0) ? 1.0 : -1.0;
        PWB_CHECK(edit.move_vertex("cycle.layer", 1, 0, v0.x() + 0.01 * dir,
                                   v0.y() + 0.01 * dir).empty());
        pwb::qgis::StagedAsset staged;
        const std::string cycle_commit_error =
            edit.commit("cycle.layer", staged_dir, &staged, nullptr);
        PWB_CHECK_MSG(cycle_commit_error.empty(),
                      "cycle " + std::to_string(cycle) + " commit failed: "
                      + cycle_commit_error);

        session.close();   // ordered teardown per the contract
        PWB_CHECK(session.project() == nullptr);
        ++completed;
    }
    PWB_CHECK(completed == kCycles);

    pwb::qgis::QgisRuntime::release();
    std::printf("lifecycle cycles completed: %d/20 (crash count: 0)\n", completed);
    return ::pwb::test::report("platform.lifecycle.cycles");
}
