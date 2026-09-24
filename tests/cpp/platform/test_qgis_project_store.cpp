// platform.qgis_project_store — QGIS-native project persistence
// (data-management convergence): QgsProject::write/read round-trip of the
// session's GIS state (layers, sources, CRS, tree order, join keys, view
// extent), honest provider-failure reporting on restore, the workspace
// codec's .qgs handoff (tree de-duplication), path derivation, and the
// provider-registry-driven layer factory.

#include <qgsapplication.h>
#include <QFile>
#include <QTemporaryDir>

#include <cmath>
#include <filesystem>

#include <qgslayertree.h>
#include <qgsfeature.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgsmapcanvas.h>
#include <qgsmapsettings.h>
#include <qgsproject.h>
#include <qgsprojectviewsettings.h>
#include <qgsrasterlayer.h>
#include <qgsrectangle.h>
#include <qgsvectorlayer.h>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/layer_factory.hpp>
#include <pwb/qgis/map_project_store.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/workspace/mutations.hpp>
#include <pwb/workspace/state.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace fs = std::filesystem;

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri =
        pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "GeoPackage fixture creation failed");
    const QString raster_path = pwb::test_fixtures::raster_fixture_path();

    const std::string paleo_project =
        (temp_dir.path() + QStringLiteral("/demo.paleo.json")).toStdString();

    // ---- default_qgs_path derivation ------------------------------------
    using pwb::qgis::map_project_store::default_qgs_path;
    PWB_CHECK(default_qgs_path("/w/proj.paleo.json") == "/w/proj.qgs");
    PWB_CHECK(default_qgs_path("/w/proj.paleo") == "/w/proj.qgs");
    PWB_CHECK(default_qgs_path("/w/odd.json") == "/w/odd.json.qgs");

    // ---- workspace codec handoff (migration de-duplication) -------------
    {
        pwb::domain::DiagnosticList diagnostics;
        pwb::workspace::MappingWorkspaceState state =
            pwb::workspace::MappingWorkspaceState::from_json(
                pwb::domain::Json::object(), diagnostics);
        state.memberships["layer.a"] = pwb::workspace::LayerBinding{};
        state.memberships["layer.a"].layer_id = "layer.a";
        state.memberships["layer.a"].binding_kind = "catalog_version";
        state.tree = pwb::domain::Json::parse(
            R"({"children":[{"type":"group","id":"g1"}]})", nullptr, false);
        PWB_CHECK(!state.tree.empty());

        pwb::domain::Json legacy = state.to_json();
        PWB_CHECK(legacy["tree"] == state.tree);  // legacy keeps the tree
        PWB_CHECK(legacy.value("qgis_project_file", std::string()).empty());

        state.qgis_project_file = "demo.qgs";
        pwb::domain::Json handed_off = state.to_json();
        // Handoff active: NO second tree copy, pointer recorded.
        PWB_CHECK(handed_off["tree"].empty());
        PWB_CHECK(handed_off.value("qgis_project_file", std::string())
                  == "demo.qgs");
        PWB_CHECK(handed_off["memberships"].contains("layer.a"));

        // Round-trip: the codec reads the pointer back verbatim.
        pwb::domain::DiagnosticList read_diag;
        const pwb::workspace::MappingWorkspaceState reloaded =
            pwb::workspace::MappingWorkspaceState::from_json(handed_off,
                                                             read_diag);
        PWB_CHECK(reloaded.qgis_project_file == "demo.qgs");
        PWB_CHECK(reloaded.memberships.count("layer.a") == 1);
    }

    // ---- save → close → restore round-trip --------------------------------
    const std::string qgs_path = default_qgs_path(paleo_project);
    QgsRectangle saved_extent;  // canvas view at save time (aspect-fit X)
    {
        pwb::qgis::MapSession session;
        QgsMapCanvas* canvas = session.createCanvas(nullptr);
        session.createLayerTree(nullptr);
        std::string error;
        QgsVectorLayer* vector_layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "facies",
            {"store.vector", "asset-1", "version-1", "vector"}, &error);
        PWB_CHECK_MSG(vector_layer != nullptr, "vector add failed: " + error);
        QgsRasterLayer* raster_layer = session.addRasterLayer(
            raster_path.toStdString(), "basemap",
            {"store.raster", "asset-2", "version-1", "raster"}, &error);
        PWB_CHECK_MSG(raster_layer != nullptr,
                      "raster add failed: " + error);
        session.setDestinationCrs("EPSG:4326", &error);
        PWB_CHECK(error.empty());
        // A concrete view to verify the restore lands on it. The canvas
        // re-fits X to its pixel aspect ratio on setExtent (standard
        // behavior), so the probe is the canvas's OWN extent at save time.
        canvas->setExtent(QgsRectangle(110.0, 29.0, 118.0, 35.0));
        saved_extent = canvas->extent();

        // Group + placement survive through the QGIS tree (GIS authority).
        session.project()->layerTreeRoot()->insertGroup(0, "evidence");

        PWB_CHECK(pwb::qgis::map_project_store::save(session, qgs_path,
                                                     &error));
        PWB_CHECK_MSG(error.empty(), "save error: " + error);
        session.close();
    }
    {
        PWB_CHECK(std::filesystem::exists(std::filesystem::path(qgs_path)));

        pwb::qgis::MapSession session;
        QgsMapCanvas* canvas = session.createCanvas(nullptr);
        session.createLayerTree(nullptr);
        const pwb::qgis::map_project_store::RestoreReport report =
            pwb::qgis::map_project_store::load(session, qgs_path);
        PWB_CHECK_MSG(report.ok, "restore failed: " + report.error);
        PWB_CHECK(report.warnings.empty());

        // Source/CRS restored by QgsProject.
        PWB_CHECK(session.project()->crs().authid()
                  == QStringLiteral("EPSG:4326"));
        PWB_CHECK(canvas->mapSettings().destinationCrs().authid()
                  == QStringLiteral("EPSG:4326"));
        QgsVectorLayer* vector =
            qobject_cast<QgsVectorLayer*>(session.layerById("store.vector"));
        PWB_CHECK(vector != nullptr && vector->isValid());
        PWB_CHECK(vector->featureCount() == 3);
        PWB_CHECK(vector->crs().authid() == QStringLiteral("EPSG:4326"));
        QgsRasterLayer* raster =
            qobject_cast<QgsRasterLayer*>(session.layerById("store.raster"));
        PWB_CHECK(raster != nullptr && raster->isValid());
        PWB_CHECK(raster->bandCount() == 1);

        // Domain join keys rode along in the project XML.
        std::string legacy_key;
        PWB_CHECK(pwb::qgis::layer_adapter::layer_id_of(vector, &legacy_key)
                  == "store.vector");
        PWB_CHECK(legacy_key.empty());  // no legacy doc_id leakage
        const QVariant asset = vector->customProperty("pwb/asset_id");
        PWB_CHECK(asset.toString() == QStringLiteral("asset-1"));
        const QVariant version = vector->customProperty("pwb/version_id");
        PWB_CHECK(version.toString() == QStringLiteral("version-1"));

        // Tree structure + order restored (group node present).
        PWB_CHECK(session.project()->layerTreeRoot()->findGroup(
                      QStringLiteral("evidence")) != nullptr);
        PWB_CHECK(session.layerIdsTopFirst().size() == 2);

        // The stored view came back with the project: the persisted
        // extent equals what was saved, and the restore applied it to the
        // canvas (the canvas may re-fit X to its pixel aspect ratio —
        // standard QgsMapCanvas::setExtent behavior — so Y is the probe).
        const QgsReferencedRectangle stored =
            session.project()->viewSettings()->defaultViewExtent();
        PWB_CHECK(std::abs(stored.xMinimum() - saved_extent.xMinimum()) < 1e-6);
        PWB_CHECK(std::abs(stored.yMinimum() - saved_extent.yMinimum()) < 1e-6);
        PWB_CHECK(std::abs(stored.xMaximum() - saved_extent.xMaximum()) < 1e-6);
        PWB_CHECK(std::abs(stored.yMaximum() - saved_extent.yMaximum()) < 1e-6);
        PWB_CHECK(std::abs(canvas->extent().yMinimum()
                          - saved_extent.yMinimum()) < 1e-6);
        PWB_CHECK(std::abs(canvas->extent().yMaximum()
                          - saved_extent.yMaximum()) < 1e-6);
        session.close();
    }

    // ---- honest restore of a broken source (scenario 5) ------------------
    {
        std::filesystem::rename(std::filesystem::path(qgs_path),
                                std::filesystem::path(qgs_path + ".bak"));
        // Write a project whose vector source then disappears.
        {
            pwb::qgis::MapSession session;
            std::string error;
            const QString doomed =
                temp_dir.path() + QStringLiteral("/doomed.gpkg");
            QFile::copy(gpkg_uri.left(gpkg_uri.indexOf('|')), doomed);
            session.addVectorLayer(
                doomed.toStdString(), "doomed",
                {"doomed.vector", "a", "v", "vector"}, &error);
            PWB_CHECK(pwb::qgis::map_project_store::save(
                session, qgs_path, &error));
            session.close();
        }
        std::filesystem::remove(
            std::filesystem::path(
                (temp_dir.path() + QStringLiteral("/doomed.gpkg"))
                    .toStdString()));
        pwb::qgis::MapSession session;
        const pwb::qgis::map_project_store::RestoreReport report =
            pwb::qgis::map_project_store::load(session, qgs_path);
        PWB_CHECK(report.ok);  // the FILE read fine…
        PWB_CHECK(!report.warnings.empty());  // …but the layer is honestly
        PWB_CHECK(report.restored_layers == 0);  // reported invalid
        session.close();
    }

    // ---- read failure is an honest error ---------------------------------
    {
        pwb::qgis::MapSession session;
        const pwb::qgis::map_project_store::RestoreReport report =
            pwb::qgis::map_project_store::load(
                session,
                (temp_dir.path() + QStringLiteral("/nope.qgs"))
                    .toStdString());
        PWB_CHECK(!report.ok);
        PWB_CHECK(!report.error.empty());
    }

    // ---- provider-registry-driven factory ---------------------------------
    {
        std::string error;
        const std::vector<pwb::qgis::layer_factory::ProposedSublayer>
            sublayers = pwb::qgis::layer_factory::query_sublayers(
                gpkg_uri.toStdString(), &error);
        PWB_CHECK_MSG(!sublayers.empty(), "query_sublayers: " + error);
        PWB_CHECK(sublayers.size() == 1);
        PWB_CHECK(sublayers[0].provider_key == "ogr");
        PWB_CHECK(sublayers[0].kind == "vector");

        pwb::qgis::MapSession session;
        QgsMapLayer* layer = pwb::qgis::layer_factory::add_sublayer(
            session, sublayers[0], {"factory.vector", "", "", "vector"},
            &error);
        PWB_CHECK_MSG(layer != nullptr, "add_sublayer: " + error);
        PWB_CHECK(layer->isValid());
        PWB_CHECK(qobject_cast<QgsVectorLayer*>(layer) != nullptr);

        // Unknown sources are refused by the registry, not guessed at.
        const std::vector<pwb::qgis::layer_factory::ProposedSublayer> none =
            pwb::qgis::layer_factory::query_sublayers(
                (temp_dir.path() + QStringLiteral("/notes.txt"))
                    .toStdString(),
                &error);
        PWB_CHECK(none.empty());
        PWB_CHECK(!error.empty());

        // Multi-sublayer sources: a two-table GeoPackage yields two
        // proposals with distinct names (the "base · table" admission
        // names in openDataFile depend on this).
        {
            const QString multi =
                temp_dir.path() + QStringLiteral("/multi.gpkg");
            const QString scratch_uri = QStringLiteral(
                "Point?crs=EPSG:4326&field=id:integer");
            QgsVectorLayer scratch(scratch_uri, QStringLiteral("s"),
                                   QStringLiteral("memory"));
            if (scratch.isValid() && scratch.startEditing()) {
                QgsFeature feature(scratch.fields());
                feature.setAttribute(0, 1);
                feature.setGeometry(QgsGeometry::fromWkt(
                    QStringLiteral("POINT(111 31)")));
                scratch.addFeature(feature);
                scratch.commitChanges(true);
                int table_index = 0;
                for (const char* table : {"alpha", "beta"}) {
                    QgsVectorFileWriter::SaveVectorOptions options;
                    options.driverName = QStringLiteral("GPKG");
                    options.layerName = QString::fromLatin1(table);
                    if (table_index > 0) {
                        // Second table: the file exists — append a layer
                        // instead of recreating the container.
                        options.actionOnExistingFile =
                            QgsVectorFileWriter::CreateOrOverwriteLayer;
                    }
                    ++table_index;
                    QString werror;
                    QString fn;
                    QString ln;
                    QgsVectorFileWriter::writeAsVectorFormatV3(
                        &scratch, multi, QgsCoordinateTransformContext(),
                        options, &werror, &fn, &ln);
                }
                std::string multi_error;
                const std::vector<pwb::qgis::layer_factory::ProposedSublayer>
                    multi_sublayers = pwb::qgis::layer_factory::
                        query_sublayers(multi.toStdString(),
                                        &multi_error);
                PWB_CHECK(multi_sublayers.size() == 2);
                bool has_alpha = false;
                bool has_beta = false;
                for (const auto& sublayer : multi_sublayers) {
                    has_alpha = has_alpha || sublayer.name == "alpha";
                    has_beta = has_beta || sublayer.name == "beta";
                }
                PWB_CHECK(has_alpha && has_beta);
            }
        }

        // Provider-declared file filters replace hand-maintained lists.
        PWB_CHECK(!pwb::qgis::layer_factory::vector_file_filter().empty());
        PWB_CHECK(pwb::qgis::layer_factory::vector_file_filter().find(
                      "*.gpkg") != std::string::npos);
        PWB_CHECK(!pwb::qgis::layer_factory::raster_file_filter().empty());
        session.close();
    }

    // ---- real-store migration E2E (save → handoff → reopen) ---------------
    // Acceptance: a legacy project (no .qgs handoff) saves through the
    // convergence path — the document gains the pointer, stops
    // duplicating the tree, and a FRESH session restores the GIS state
    // from the .qgs file while the catalog lineage stays intact.
    {
        const fs::path fixtures = PWB_TEST_SRC_DIR "/../data/fixtures";
        const fs::path typical = fixtures / "typical";
        PWB_CHECK(fs::exists(typical / "typical.paleo.json"));
        QTemporaryDir migrate_dir;
        const fs::path work =
            fs::path(migrate_dir.path().toStdWString()) / "project";
        std::error_code ec;
        fs::copy(typical, work, fs::copy_options::recursive, ec);
        PWB_CHECK_MSG(!ec, "fixture copy failed: " + ec.message());
        const fs::path project_file = work / "typical.paleo.json";

        std::string open_error;
        auto store = pwb::application::PwbDataStore::open(project_file,
                                                          &open_error);
        PWB_CHECK_MSG(store != nullptr, "store open failed: " + open_error);

        // A live layer on the session (working-copy form), then the
        // convergence save: .qgs write + handoff pointer in the document.
        pwb::qgis::MapSession session;
        session.createCanvas(nullptr);
        const QString migrated_uri =
            pwb::test_fixtures::make_gpkg_fixture(migrate_dir.path());
        PWB_CHECK(!migrated_uri.isEmpty());
        std::string add_error;
        pwb::qgis::LayerBinding migration_binding{
            "L_drafted", "asset-migrated", "version-migrated", "vector"};
        QgsVectorLayer* migrated = session.addVectorLayer(
            migrated_uri.toStdString(), "L_drafted", migration_binding,
            &add_error);
        PWB_CHECK_MSG(migrated != nullptr, "migration layer add: " + add_error);

        const std::string qgs =
            pwb::qgis::map_project_store::default_qgs_path(
                project_file.string());
        std::string save_error;
        PWB_CHECK(pwb::qgis::map_project_store::save(session, qgs,
                                                     &save_error));
        pwb::domain::DiagnosticList handoff_diag;
        pwb::workspace::MappingWorkspaceState handoff =
            pwb::workspace::MappingWorkspaceState::from_json(
                store->document().mapping_workspace(), handoff_diag);
        handoff.qgis_project_file =
            pwb::project::relativize_path(fs::path(qgs), project_file)
                .stored;
        pwb::workspace::write_mapping_workspace(store->document().root(),
                                                handoff);
        const pwb::domain::DataError persisted = store->save_document();
        PWB_CHECK(persisted.code == pwb::domain::ErrorCode::Ok);
        session.close();
        store.reset();  // close-then-reopen (one session per project)

        // Reopen: the document hands GIS state to the .qgs file…
        auto reopened = pwb::application::PwbDataStore::open(project_file,
                                                             &open_error);
        PWB_CHECK_MSG(reopened != nullptr, "reopen failed: " + open_error);
        auto snapshot2 = reopened->snapshot();
        PWB_CHECK(snapshot2.is_ok());
        PWB_CHECK(snapshot2.value().workspace.qgis_project_file
                  == "typical.qgs");
        // De-duplication held across the real save: the persisted
        // workspace no longer carries a second copy of the tree.
        PWB_CHECK(snapshot2.value().workspace.tree.empty());
        // …the catalog lineage survived the migration untouched…
        PWB_CHECK(!snapshot2.value().catalog_versions.empty());

        // …and a fresh session restores the layer with its join key.
        pwb::qgis::MapSession session2;
        session2.createCanvas(nullptr);
        const pwb::qgis::map_project_store::RestoreReport restored =
            pwb::qgis::map_project_store::load(session2, qgs);
        PWB_CHECK_MSG(restored.ok, "migration restore: " + restored.error);
        QgsVectorLayer* back = qobject_cast<QgsVectorLayer*>(
            session2.layerById("L_drafted"));
        PWB_CHECK(back != nullptr && back->isValid());
        PWB_CHECK(back->customProperty("pwb/version_id").toString()
                  == QStringLiteral("version-migrated"));
        session2.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.qgis_project_store");
}
