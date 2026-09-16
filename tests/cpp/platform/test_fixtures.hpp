#pragma once

// Shared runtime fixtures for the platform tests: a real GeoPackage written
// through QGIS's own QgsVectorFileWriter (provider truth, not a fake layer)
// plus the committed GeoTIFF fixture.

#include <QCoreApplication>
#include <QDir>
#include <QString>
#include <QTemporaryDir>

#include <qgscoordinatetransformcontext.h>
#include <qgsfeature.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>

namespace pwb::test_fixtures {

// Writes 3 polygons (110..116 / 30..34, EPSG:4326) into <dir>/fixture.gpkg.
// Returns the OGR URI with layername, or an empty string on failure.
inline QString make_gpkg_fixture(const QString& dir) {
    const QString uri = QStringLiteral(
        "Polygon?crs=EPSG:4326&field=id:integer&field=name:string(64)");
    QgsVectorLayer scratch(uri, QStringLiteral("scratch"),
                           QStringLiteral("memory"));
    if (!scratch.isValid() || !scratch.startEditing()) return QString();
    for (int i = 0; i < 3; ++i) {
        QgsFeature feature(scratch.fields());
        feature.setAttribute(0, i + 1);
        feature.setAttribute(1, QStringLiteral("poly-%1").arg(i));
        const double x0 = 110.0 + i * 2.0;
        const double y0 = 30.0 + i * 1.0;
        feature.setGeometry(QgsGeometry::fromWkt(QStringLiteral(
            "POLYGON((%1 %2, %3 %2, %3 %4, %1 %4, %1 %2))")
            .arg(x0).arg(y0).arg(x0 + 1.5).arg(y0 + 1.2)));
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
    if (result != QgsVectorFileWriter::NoError) return QString();
    return path + QStringLiteral("|layername=facies_boundary");
}

inline QString raster_fixture_path() {
#ifdef PWB_TEST_SRC_DIR
    return QString::fromUtf8(PWB_TEST_SRC_DIR) + QStringLiteral("/fixtures/base_raster.tif");
#else
    // Fallback: directory of the running test executable -> ../../fixtures.
    const QString exe_dir = QCoreApplication::applicationDirPath();
    QDir base(exe_dir);
    base.cdUp();
    base.cdUp();
    return base.filePath(QStringLiteral("fixtures/base_raster.tif"));
#endif
}

inline QString test_data_path(const QString& name) {
#ifdef PWB_TEST_SRC_DIR
    return QString::fromUtf8(PWB_TEST_SRC_DIR) + QStringLiteral("/") + name;
#else
    return name;
#endif
}

}  // namespace pwb::test_fixtures
