// pwb-platform — CPP-A C++20/Qt/QGIS application entry.
//
// Modes:
//   (no args)     interactive window
//   --self-check  headless-ish smoke: create window offscreen, load a
//                 generated GeoPackage fixture, verify provider/CRS/render,
//                 export a PNG, exit 0/1 (used by CTest and package smoke;
//                 failures print diagnostics, never fake success).

#include <filesystem>

#include <qgsapplication.h>
#include <QCommandLineParser>
#include <QColor>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>

#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsmapcanvas.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsproject.h>
#include <qgsrasterlayer.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/edit_controller.hpp>
#include <pwb/qgis/layout_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "main_window.hpp"

namespace {

QString makeFixtureGpkg(const QString& dir) {
    // Memory layer -> GeoPackage via QGIS's own writer: the fixture is real
    // provider data, not a fake layer.
    const QString uri_base = QStringLiteral(
        "Polygon?crs=EPSG:4326&field=id:integer&field=name:string(64)");
    QgsVectorLayer scratch(uri_base, QStringLiteral("scratch"),
                           QStringLiteral("memory"));
    if (!scratch.isValid()) return QString();
    if (!scratch.startEditing()) return QString();
    for (int i = 0; i < 3; ++i) {
        QgsFeature feature(scratch.fields());
        feature.setAttribute(0, i + 1);
        feature.setAttribute(1, QStringLiteral("poly-%1").arg(i));
        const double x0 = 110.0 + i * 2.0;
        const double y0 = 30.0 + i * 1.0;
        QgsGeometry geometry = QgsGeometry::fromWkt(QStringLiteral(
            "POLYGON((%1 %2, %3 %2, %3 %4, %1 %4, %1 %2))")
            .arg(x0).arg(y0).arg(x0 + 1.5).arg(y0 + 1.2));
        feature.setGeometry(geometry);
        scratch.addFeature(feature);
    }
    if (!scratch.commitChanges(true)) return QString();
    const QString path = dir + QStringLiteral("/fixture.gpkg");
    QgsVectorFileWriter::SaveVectorOptions options;
    options.driverName = QStringLiteral("GPKG");
    options.layerName = QStringLiteral("facies_boundary");
    QString error;
    QString new_filename;
    QString new_layer;
    const auto result = QgsVectorFileWriter::writeAsVectorFormatV3(
        &scratch, path, QgsCoordinateTransformContext(), options, &error,
        &new_filename, &new_layer);
    if (result != QgsVectorFileWriter::NoError) {
        qCritical("fixture write failed: %s", qUtf8Printable(error));
        return QString();
    }
    return path + QStringLiteral("|layername=facies_boundary");
}

int runSelfCheck() {
    QTemporaryDir temp_dir;
    if (!temp_dir.isValid()) {
        qCritical("cannot create temp dir");
        return 1;
    }
    const QString gpkg_uri = makeFixtureGpkg(temp_dir.path());
    if (gpkg_uri.isEmpty()) {
        qCritical("fixture GeoPackage creation failed");
        return 1;
    }

    pwb::app::MainWindow window;
    const QString load_error = window.loadFixtures(gpkg_uri, QString());
    if (!load_error.isEmpty()) {
        qCritical("fixture load failed: %s", qUtf8Printable(load_error));
        return 1;
    }
    pwb::application::ProjectSession* session = window.session();
    pwb::qgis::MapSession& map = session->map();

    // Provider + CRS verification (honest: any failure is fatal).
    QgsVectorLayer* layer = map.vectorLayerById("fixture.facies_boundary");
    if (layer == nullptr || !layer->isValid() || layer->featureCount() != 3) {
        qCritical("vector layer verification failed (layer=%p count=%lld)",
                  static_cast<void*>(layer),
                  layer != nullptr ? layer->featureCount() : -1);
        return 1;
    }
    if (layer->crs().authid() != QStringLiteral("EPSG:4326")
        || map.project()->crs().authid() != QStringLiteral("EPSG:4326")) {
        qCritical("CRS verification failed: layer=%s project=%s",
                  qUtf8Printable(layer->crs().authid()),
                  qUtf8Printable(map.project()->crs().authid()));
        return 1;
    }

    // Render one frame synchronously through the same map-render job engine
    // the canvas uses. Widget->grab() is not deterministic for an unshown
    // window under the offscreen platform; the parallel job renders the
    // canvas's real map settings into a fixed-size image.
    QgsMapCanvas* canvas = window.findChild<QgsMapCanvas*>();
    if (canvas == nullptr) {
        qCritical("canvas not found");
        return 1;
    }
    canvas->resize(800, 600);
    canvas->setExtent(layer->extent());
    QgsMapSettings settings = canvas->mapSettings();
    settings.setOutputSize(QSize(800, 600));
    settings.setBackgroundColor(Qt::white);
    QgsMapRendererParallelJob job(settings);
    job.start();
    job.waitForFinished();
    const QImage frame = job.renderedImage();
    if (frame.size() != QSize(800, 600)) {
        qCritical("render frame size mismatch: %dx%d",
                  frame.width(), frame.height());
        return 1;
    }
    bool non_white = false;
    for (int y = 0; y < frame.height() && !non_white; y += 8) {
        for (int x = 0; x < frame.width() && !non_white; x += 8) {
            if (frame.pixel(x, y) != QColor(Qt::white).rgb()) non_white = true;
        }
    }
    if (!non_white) {
        qCritical("rendered frame is blank (all white)");
        return 1;
    }

    // Layout PNG export smoke.
    pwb::qgis::LayoutService layouts(map);
    pwb::qgis::LayoutSpec spec;
    const std::filesystem::path png =
        std::filesystem::path(temp_dir.path().toStdWString()) / "smoke.png";
    const std::string export_error =
        layouts.export_layout(spec, png, "png", 96.0);
    if (!export_error.empty()) {
        qCritical("layout export failed: %s", export_error.c_str());
        return 1;
    }
#ifdef PWB_WITH_WELL_LOG
    // Well-log dock embedding: the real WLE-backed host loads the committed
    // LAS fixture (dev tree; a missing file is reported, a failed parse of
    // a present fixture is a hard error).
    const QString las_path = QStringLiteral(PWB_SOURCE_DIR
                                             "/tests/fixtures/realdata/A1.Las");
    if (QFile::exists(las_path)) {
        const QString las_error = window.loadLasIntoDock(las_path);
        if (!las_error.isEmpty()) {
            qCritical("well-log dock LAS load failed: %s",
                      qUtf8Printable(las_error));
            return 1;
        }
    } else {
        qInfo("self-check: LAS fixture absent (dev tree only), dock check skipped");
    }
#endif

    qInfo("self-check ok: gpkg=%ls png=%ls bytes=%zu",
          gpkg_uri.toStdWString().c_str(), png.wstring().c_str(),
          static_cast<size_t>(std::filesystem::file_size(png)));
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    QApplication::setApplicationName(QStringLiteral("pwb-platform"));
    QApplication::setOrganizationName(QStringLiteral("paleo-workbench"));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("Paleo Workbench C++ platform"));
    parser.addOption({QStringLiteral("self-check"),
                      QStringLiteral("headless smoke: fixtures + render + export")});
    parser.process(app);

    pwb::qgis::QgisRuntime::acquire();
    int exit_code = 0;
    if (parser.isSet(QStringLiteral("self-check"))) {
        exit_code = runSelfCheck();
    } else {
        pwb::app::MainWindow window;
        window.show();
        exit_code = QApplication::exec();
    }
    pwb::qgis::QgisRuntime::release();
    return exit_code;
}
