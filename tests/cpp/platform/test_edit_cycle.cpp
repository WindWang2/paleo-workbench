// platform.edit.cycle — Oracle 4: one vertex move -> undo/redo -> staged
// asset with correct geometry+attributes on re-read; topology errors block
// the commit (session kept, honest reason); edit buffer is the only mutable
// geometry state (no second undo stack).

#include <cmath>
#include <memory>

#include <qgsapplication.h>
#include <QFile>
#include <QTemporaryDir>

#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsproject.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/edit_controller.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

using pwb::qgis::EditController;
using pwb::qgis::MapSession;

namespace {

QgsPointXY vertex_of(QgsVectorLayer* layer, long long fid, int index) {
    QgsFeature feature = layer->getFeature(static_cast<QgsFeatureId>(fid));
    return feature.geometry().vertexAt(index);
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");

    const std::string layer_id = "edit.facies_boundary";
    const std::filesystem::path staged_dir =
        std::filesystem::path(temp_dir.path().toStdWString()) / "staged";

    {
        MapSession session;
        std::string error;
        pwb::qgis::LayerBinding binding{layer_id, "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "edit_layer", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, "layer add failed: " + error);
        EditController edit(session);

        // -- start editing ------------------------------------------------
        PWB_CHECK(edit.start_editing(layer_id).empty());
        PWB_CHECK(edit.start_editing(layer_id).empty());  // idempotent
        PWB_CHECK(edit.editing(layer_id));
        PWB_CHECK(!edit.dirty(layer_id));
        PWB_CHECK(!edit.can_undo(layer_id));

        // -- one vertex move = one undoable macro -------------------------
        const QgsPointXY before = vertex_of(layer, 1, 0);
        PWB_CHECK(edit.move_vertex(layer_id, 1, 0, before.x() + 0.25,
                                   before.y() + 0.15).empty());
        PWB_CHECK(edit.dirty(layer_id));
        PWB_CHECK(edit.can_undo(layer_id));
        const QgsPointXY moved = vertex_of(layer, 1, 0);
        PWB_CHECK(std::abs(moved.x() - (before.x() + 0.25)) < 1e-9);
        PWB_CHECK(std::abs(moved.y() - (before.y() + 0.15)) < 1e-9);

        // -- undo/redo (QGIS undo stack is the single undo authority) ------
        PWB_CHECK(edit.undo(layer_id).empty());
        const QgsPointXY undone = vertex_of(layer, 1, 0);
        PWB_CHECK(std::abs(undone.x() - before.x()) < 1e-9);
        PWB_CHECK(std::abs(undone.y() - before.y()) < 1e-9);
        PWB_CHECK(edit.can_redo(layer_id));
        PWB_CHECK(edit.redo(layer_id).empty());
        const QgsPointXY redone = vertex_of(layer, 1, 0);
        PWB_CHECK(std::abs(redone.x() - moved.x()) < 1e-9);

        // -- clean topology -> commit -> staged asset ----------------------
        PWB_CHECK(edit.validate_topology(layer_id).empty());
        pwb::qgis::StagedAsset staged;
        pwb::qgis::EditDeltaV1 delta;
        const std::string commit_error =
            edit.commit(layer_id, staged_dir, &staged, &delta);
        PWB_CHECK_MSG(commit_error.empty(), "commit failed: " + commit_error);
        PWB_CHECK(std::filesystem::exists(staged.geojson_path));
        PWB_CHECK(!staged.sha256.empty());
        PWB_CHECK(staged.source_layer_id == layer_id);
        PWB_CHECK(staged.feature_count == 3);
        PWB_CHECK(delta.source_layer_id == layer_id);
        PWB_CHECK(delta.geometry_changes.size() == 1);
        PWB_CHECK(delta.geometry_changes[0].host_fid == 1);
        PWB_CHECK(!edit.editing(layer_id));  // session closed by commit

        // -- staged asset re-read: geometry + attributes survive -----------
        QgsVectorLayer staged_layer(
            QString::fromStdWString(staged.geojson_path.wstring()),
            QStringLiteral("staged"), QStringLiteral("ogr"));
        PWB_CHECK_MSG(staged_layer.isValid(), "staged asset unreadable");
        PWB_CHECK(staged_layer.featureCount() == 3);
        QgsFeature reloaded = staged_layer.getFeature(1);
        PWB_CHECK(reloaded.hasGeometry());
        const QgsPointXY reloaded_vertex = reloaded.geometry().vertexAt(0);
        PWB_CHECK(std::abs(reloaded_vertex.x() - moved.x()) < 1e-9);
        const int name_index = staged_layer.fields().indexOf(QStringLiteral("name"));
        PWB_CHECK(name_index >= 0);
        PWB_CHECK(reloaded.attribute(name_index).toString() == QStringLiteral("poly-0"));
        session.close();
    }

    {
        // -- topology gate: bowtie polygon blocks the commit ----------------
        MapSession session;
        std::string error;
        pwb::qgis::LayerBinding binding{"topo.layer", "asset-2", "version-1", "vector"};
        // Local square 0,0 10,0 10,10 0,10 — swivel two vertices into a bowtie.
        const QString uri = QStringLiteral(
            "Polygon?crs=EPSG:4326&field=id:integer");
        std::unique_ptr<QgsVectorLayer> scratch(
            new QgsVectorLayer(uri, QStringLiteral("scratch"),
                               QStringLiteral("memory")));
        PWB_CHECK(scratch->startEditing());
        QgsFeature feature(scratch->fields());
        feature.setAttribute(0, 1);
        feature.setGeometry(QgsGeometry::fromWkt(
            QStringLiteral("POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))")));
        scratch->addFeature(feature);
        PWB_CHECK(scratch->commitChanges(true));
        const QString path = temp_dir.path() + QStringLiteral("/topo.gpkg");
        QgsVectorFileWriter::SaveVectorOptions options;
        options.driverName = QStringLiteral("GPKG");
        QString writer_error;
        QString new_filename;
        QString new_layer;
        PWB_CHECK(QgsVectorFileWriter::writeAsVectorFormatV3(
            scratch.get(), path, QgsCoordinateTransformContext(), options,
            &writer_error, &new_filename, &new_layer)
            == QgsVectorFileWriter::NoError);
        scratch.reset();

        QgsVectorLayer* layer = session.addVectorLayer(
            (path + QStringLiteral("|layername=topo")).toStdString(), "topo",
            binding, &error);
        PWB_CHECK_MSG(layer != nullptr, "topo layer add failed: " + error);
        EditController edit(session);
        PWB_CHECK(edit.start_editing("topo.layer").empty());
        // Bowtie: swap vertices 1 and 2 -> crossing edges.
        PWB_CHECK(edit.move_vertex("topo.layer", 1, 1, 10.0, 10.0).empty());
        PWB_CHECK(edit.move_vertex("topo.layer", 1, 2, 10.0, 0.0).empty());
        const std::vector<std::string> topo_errors =
            edit.validate_topology("topo.layer");
        PWB_CHECK_MSG(!topo_errors.empty(),
                      "bowtie geometry was not flagged by topology validation");
        pwb::qgis::StagedAsset staged;
        const std::string blocked =
            edit.commit("topo.layer", staged_dir, &staged, nullptr);
        PWB_CHECK_MSG(!blocked.empty(), "illegal commit was not blocked");
        PWB_CHECK(blocked.find("拓扑校验失败") == 0);
        PWB_CHECK(edit.editing("topo.layer"));   // session kept for repair
        PWB_CHECK(edit.dirty("topo.layer"));     // buffer intact
        // Repair: undo both moves, then commit succeeds.
        PWB_CHECK(edit.undo("topo.layer").empty());
        PWB_CHECK(edit.undo("topo.layer").empty());
        PWB_CHECK(edit.validate_topology("topo.layer").empty());
        const std::string repaired = edit.commit("topo.layer", staged_dir,
                                                 &staged, nullptr);
        PWB_CHECK_MSG(repaired.empty(), "repaired commit failed: " + repaired);
        session.close();
    }

    {
        // -- #1467: newly digitized features enter the topology gate -------
        // Pending adds live in editBuffer()->addedFeatures(), not
        // changedGeometries() — the gate must validate exactly the
        // geometry set the staged writer will emit.
        MapSession session;
        std::string error;
        pwb::qgis::LayerBinding binding{"added.layer", "asset-3", "version-1",
                                        "vector"};
        const QString uri = QStringLiteral(
            "Polygon?crs=EPSG:4326&field=id:integer");
        std::unique_ptr<QgsVectorLayer> scratch(
            new QgsVectorLayer(uri, QStringLiteral("scratch_added"),
                               QStringLiteral("memory")));
        PWB_CHECK(scratch->startEditing());
        QgsFeature seed(scratch->fields());
        seed.setAttribute(0, 1);
        seed.setGeometry(QgsGeometry::fromWkt(
            QStringLiteral("POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))")));
        scratch->addFeature(seed);
        PWB_CHECK(scratch->commitChanges(true));
        const QString path = temp_dir.path() + QStringLiteral("/added.gpkg");
        QgsVectorFileWriter::SaveVectorOptions options;
        options.driverName = QStringLiteral("GPKG");
        QString writer_error;
        QString new_filename;
        QString new_layer;
        PWB_CHECK(QgsVectorFileWriter::writeAsVectorFormatV3(
            scratch.get(), path, QgsCoordinateTransformContext(), options,
            &writer_error, &new_filename, &new_layer)
            == QgsVectorFileWriter::NoError);
        scratch.reset();

        QgsVectorLayer* layer = session.addVectorLayer(
            (path + QStringLiteral("|layername=added")).toStdString(),
            "added", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, "added layer add failed: " + error);
        EditController edit(session);
        PWB_CHECK(edit.start_editing("added.layer").empty());
        // Bowtie as a NEW feature — no existing geometry is touched, so
        // changedGeometries() stays empty and only addedFeatures() has it.
        const std::string bowtie_feature =
            R"({"type":"Feature","properties":{"id":2},"geometry":)"
            R"({"type":"Polygon","coordinates":)"
            R"([[[0,0],[10,0],[0,10],[10,10],[0,0]]]}})";
        PWB_CHECK(edit.add_feature_geojson("added.layer", bowtie_feature)
                      .empty());
        const std::vector<std::string> added_errors =
            edit.validate_topology("added.layer");
        PWB_CHECK_MSG(!added_errors.empty(),
                      "bowtie ADDED feature bypassed the topology gate "
                      "(#1467: gate must cover addedFeatures())");
        pwb::qgis::StagedAsset staged;
        const std::string blocked =
            edit.commit("added.layer", staged_dir, &staged, nullptr);
        PWB_CHECK_MSG(!blocked.empty(),
                      "commit was not blocked by an illegal ADDED feature");
        PWB_CHECK(blocked.find("拓扑校验失败") == 0);
        PWB_CHECK(edit.editing("added.layer"));   // session kept for repair
        PWB_CHECK(edit.dirty("added.layer"));     // buffer intact

        // Repair: undo the add — validation passes and the commit lands.
        PWB_CHECK(edit.undo("added.layer").empty());
        PWB_CHECK(edit.validate_topology("added.layer").empty());

        // Delete-only edits carry no pending geometry to validate.
        QgsFeatureIds select;
        select << 1;
        layer->selectByIds(select);
        int deleted = 0;
        PWB_CHECK(edit.delete_selected("added.layer", &deleted).empty());
        PWB_CHECK(deleted == 1);
        PWB_CHECK(edit.validate_topology("added.layer").empty());
        const std::string repaired =
            edit.commit("added.layer", staged_dir, &staged, nullptr);
        PWB_CHECK_MSG(repaired.empty(),
                      "repaired added-feature commit failed: " + repaired);
        session.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.edit.cycle");
}
