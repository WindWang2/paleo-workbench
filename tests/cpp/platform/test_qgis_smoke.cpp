// platform.qgis_smoke — real QGIS smoke (Oracle 2): canvas + layer tree
// creation, vector (GeoPackage) + raster (GeoTIFF) fixtures through real
// providers, provider/CRS verification, one synchronous render, tree order
// read-back, honest provider-failure diagnostics. Never a fake success.

#include <qgsapplication.h>
#include <QColor>
#include <QEventLoop>
#include <QImage>
#include <QTemporaryDir>

#include <qgsmapcanvas.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsproject.h>
#include <qgsrasterlayer.h>
#include <qgsvectorlayer.h>
#include <qgslayertreeview.h>

#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "GeoPackage fixture creation failed");

    {
        pwb::qgis::MapSession session;
        QgsMapCanvas* canvas = session.createCanvas(nullptr);
        auto* view = session.createLayerTree(nullptr);
        PWB_CHECK(canvas != nullptr);
        PWB_CHECK(view != nullptr && view->model() != nullptr);

        std::string error;
        const pwb::qgis::LayerBinding vector_binding{
            "smoke.vector", "asset-1", "version-1", "vector"};
        QgsVectorLayer* vector_layer = session.addVectorLayer(
            gpkg_uri.toStdString(), "smoke_vector", vector_binding, &error);
        PWB_CHECK_MSG(vector_layer != nullptr, "vector add failed: " + error);
        PWB_CHECK(vector_layer->isValid());
        PWB_CHECK(vector_layer->featureCount() == 3);
        PWB_CHECK(vector_layer->crs().authid() == QStringLiteral("EPSG:4326"));

        const QString raster_path = pwb::test_fixtures::raster_fixture_path();
        const pwb::qgis::LayerBinding raster_binding{
            "smoke.raster", "asset-2", "version-1", "raster"};
        QgsRasterLayer* raster_layer = session.addRasterLayer(
            raster_path.toStdString(), "smoke_raster", raster_binding, &error);
        PWB_CHECK_MSG(raster_layer != nullptr,
                      "raster add failed: " + error + " path=" + raster_path.toStdString());
        PWB_CHECK(raster_layer->isValid());
        PWB_CHECK(raster_layer->bandCount() == 1);
        PWB_CHECK(!raster_layer->extent().isNull());
        PWB_CHECK(raster_layer->crs().authid() == QStringLiteral("EPSG:4326"));

        // Destination CRS + project CRS authority.
        session.setDestinationCrs("EPSG:4326", &error);
        PWB_CHECK(error.empty());
        PWB_CHECK(session.project()->crs().authid() == QStringLiteral("EPSG:4326"));
        session.setDestinationCrs("EPSG:NOPE", &error);
        PWB_CHECK(!error.empty());  // invalid CRS reported honestly

        // Join key + tree order (tree is the order authority).
        PWB_CHECK(pwb::qgis::layer_adapter::layer_id_of(vector_layer)
                  == "smoke.vector");
        const std::vector<std::string> order = session.layerIdsTopFirst();
        PWB_CHECK(order.size() == 2);

        // Provider failure is a hard error with a diagnostic (no fallback).
        std::string missing_error;
        QgsVectorLayer* missing = session.addVectorLayer(
            "Z:/definitely/missing.gpkg|layername=x", "missing",
            {"x", "", "", "vector"}, &missing_error);
        PWB_CHECK(missing == nullptr);
        PWB_CHECK(!missing_error.empty());

        // One real render through the map settings the canvas uses.
        canvas->resize(640, 480);
        canvas->setExtent(QgsRectangle(108.0, 28.0, 118.0, 36.0));
        QgsMapSettings settings = canvas->mapSettings();
        settings.setOutputSize(QSize(640, 480));
        settings.setBackgroundColor(Qt::white);
        QgsMapRendererParallelJob job(settings);
        job.start();
        job.waitForFinished();
        const QImage image = job.renderedImage();
        PWB_CHECK(!image.isNull());
        PWB_CHECK(image.width() == 640 && image.height() == 480);
        bool non_white = false;
        for (int y = 0; y < image.height() && !non_white; y += 4) {
            for (int x = 0; x < image.width() && !non_white; x += 4) {
                if (image.pixel(x, y) != QColor(Qt::white).rgb()) non_white = true;
            }
        }
        PWB_CHECK_MSG(non_white, "rendered image is blank");

        session.close();
        PWB_CHECK(session.project() == nullptr);
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.qgis_smoke");
}
