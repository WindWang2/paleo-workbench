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
#include <QThread>

#include <cstdio>

#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsmapcanvas.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsproject.h>
#include <qgsrasterlayer.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>

#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
#include <QDockWidget>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#endif

#include <pwb/qgis/edit_controller.hpp>
#include <pwb/qgis/layout_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include <pwb/platform_services/diagnostics_report.hpp>
#include <pwb/platform_services/qt_session_policy.hpp>
#include <pwb/platform_services/settings_service.hpp>

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

#if defined(PWB_WITH_DATA_INTEGRATION)
    // ---- project lifecycle (M2): fresh project -> open layer -> edit ->
    // save through the real catalog transaction -> manifest checkpoint.
    {
        const QString fresh_dir = temp_dir.path()
            + QStringLiteral("/fresh-project");
        const QString new_error =
            window.newProject(fresh_dir, QStringLiteral("selfcheck"));
        if (!new_error.isEmpty()) {
            qCritical("newProject failed: %s", qUtf8Printable(new_error));
            return 1;
        }
        if (window.session()->store() == nullptr) {
            qCritical("newProject attached no store");
            return 1;
        }
        const QString open_error = window.openVectorLayer(gpkg_uri);
        if (!open_error.isEmpty()) {
            qCritical("self-check layer open failed: %s",
                      qUtf8Printable(open_error));
            return 1;
        }
        const std::string layer_id = "fixture";
        if (window.session()->edit().start_editing(layer_id).empty()) {
            QgsVectorLayer* fresh_layer =
                window.session()->map().vectorLayerById(layer_id);
            const QgsPointXY v0 =
                fresh_layer->getFeature(1).geometry().vertexAt(0);
            window.session()->edit().move_vertex(layer_id, 1, 0,
                                                 v0.x() + 0.2, v0.y());
            const QString save_error = window.commitActiveLayer(
                std::filesystem::path(temp_dir.path().toStdWString())
                / "selfcheck-staged");
            if (!save_error.isEmpty()) {
                qCritical("self-check commit failed: %s",
                          qUtf8Printable(save_error));
                return 1;
            }
        } else {
            qCritical("self-check edit session failed to start");
            return 1;
        }
        const std::filesystem::path manifest =
            std::filesystem::path(fresh_dir.toStdWString())
            / "selfcheck.artifacts" / "metadata" / "catalog.json";
        if (!std::filesystem::exists(manifest)) {
            qCritical("catalog.json manifest checkpoint missing");
            return 1;
        }
    }

#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_SEISMIC_VIEWER) \
    && defined(PWB_WITH_SEISMIC_ATTRIBUTES)
    // ---- M3 chain: SEG-Y import -> attribute run -> slice display. The
    // real fixture only exists in dev trees; deployed packages skip the
    // check (like the LAS dock check above).
    const QString sgy_path = QStringLiteral(PWB_SOURCE_DIR
                                             "/tests/fixtures/realdata/tiny.sgy");
    if (QFile::exists(sgy_path)) {
        std::string import_error;
        const std::string imported =
            window.importSegy(sgy_path, &import_error);
        if (imported.empty()) {
            qCritical("self-check SEG-Y import failed: %s",
                      import_error.c_str());
            return 1;
        }
        std::string run_error;
        const std::string request_id = window.runAttribute(
            "seismic.rms_amplitude", {{"window", "21"}}, imported,
            &run_error);
        if (request_id.empty()) {
            qCritical("self-check attribute submit failed: %s",
                      run_error.c_str());
            return 1;
        }
        std::string status;
        for (int i = 0; i < 2000; ++i) {
            const auto outcome = window.attributeOutcome(request_id);
            status = outcome.status;
            if (status != "queued" && status != "running"
                && status != "publishing") {
                if (status != "succeeded") {
                    qCritical("self-check attribute run %s: %s",
                              status.c_str(), outcome.error.c_str());
                    return 1;
                }
                break;
            }
            QThread::msleep(5);
        }
        if (status != "succeeded") {
            qCritical("self-check attribute run never finished");
            return 1;
        }
        const QString view_error = window.openVolumeVersion(imported);
        if (!view_error.isEmpty()) {
            qCritical("self-check volume view failed: %s",
                      qUtf8Printable(view_error));
            return 1;
        }
        QDockWidget* seismic_dock =
            window.findChild<QDockWidget*>("seismic-dock");
        auto* slice = static_cast<pwb::seismic_viewer::SeismicSliceWidget*>(
            seismic_dock != nullptr ? seismic_dock->widget() : nullptr);
        if (slice == nullptr) {
            qCritical("seismic dock missing");
            return 1;
        }
        for (int spin = 0; spin < 200
                 && slice->state() != pwb::seismic_viewer::ViewerState::ok;
             ++spin) {
            QCoreApplication::processEvents();
            QThread::msleep(5);
        }
        if (slice->state() != pwb::seismic_viewer::ViewerState::ok) {
            qCritical("slice viewer did not reach ok state");
            return 1;
        }
    } else {
        qInfo("self-check: SEG-Y fixture absent (dev tree only), M3 chain skipped");
    }
#endif
#endif

    qInfo("self-check ok: gpkg=%ls png=%ls bytes=%zu",
          gpkg_uri.toStdWString().c_str(), png.wstring().c_str(),
          static_cast<size_t>(std::filesystem::file_size(png)));
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    // Session policy must run before the application object exists
    // (qt_platform.py contract): EGL pin, xcb clear, fractional-scale guard.
    pwb::platform_services::configure_qt_platform_for_session();
    pwb::platform_services::apply_wayland_fractional_scale_guard();

    QgsApplication app(argc, argv, true);
    QApplication::setApplicationName(QStringLiteral("pwb-platform"));
    QApplication::setOrganizationName(QStringLiteral("paleo-workbench"));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("Paleo Workbench C++ platform"));
    parser.addOption({QStringLiteral("self-check"),
                      QStringLiteral("headless smoke: fixtures + render + export")});
    parser.addOption({QStringLiteral("version"),
                      QStringLiteral("print the application version line")});
    parser.addOption({QStringLiteral("diagnostics"),
                      QStringLiteral("print the platform diagnostics report")});
    parser.process(app);

    // --version / --diagnostics answer before any QGIS init (cheap, no GUI).
    if (parser.isSet(QStringLiteral("version"))) {
        std::printf("%s\n",
                    pwb::platform_services::version_line().c_str());
        return 0;
    }

    // The unified settings identity predates the native shell: migrate the
    // legacy (WorkstationV3 / paleo-workbench) stores on every startup —
    // idempotent, cheap (ui/layout_persistence.py contract). Theme, window
    // layout and recent lists are owned by MainWindow on the same store.
    pwb::platform_services::migrate_legacy_settings();

    pwb::qgis::QgisRuntime::acquire();
    int exit_code = 0;
    if (parser.isSet(QStringLiteral("diagnostics"))) {
        std::printf("%s",
                    pwb::platform_services::environment_report_text().c_str());
    } else if (parser.isSet(QStringLiteral("self-check"))) {
        exit_code = runSelfCheck();
    } else {
        pwb::app::MainWindow window;
        window.show();
        exit_code = QApplication::exec();
    }
    pwb::qgis::QgisRuntime::release();
    return exit_code;
}
