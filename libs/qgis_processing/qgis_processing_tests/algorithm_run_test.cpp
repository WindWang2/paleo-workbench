// qgis_processing.run — real algorithm execution battery: interpolation
// (IDW) over a memory point layer, grid statistics, contours,
// classification and factor extraction over the produced artifacts.
// Everything runs through run_paleo_algorithm (the unified entrance).

#include <QFile>
#include <QTemporaryDir>
#include <QTextStream>
#include <QVariantMap>

#include <qgsapplication.h>
#include <qgsfeature.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgspointxy.h>
#include <qgsprocessingfeedback.h>
#include <qgsrasterblock.h>
#include <qgsrasterdataprovider.h>
#include <qgsrasterlayer.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/grid_io.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/runner.hpp>

#include "test_framework.hpp"

#include <cmath>
#include <memory>

namespace {

using namespace pwb::qgis_processing;

QgsVectorLayer* make_sample_layer() {
    auto* layer = new QgsVectorLayer(
        QStringLiteral("Point?crs=EPSG:32650"), QStringLiteral("samples"),
        QStringLiteral("memory"));
    QList<QgsField> fields;
    fields << QgsField(QStringLiteral("x"), QMetaType::Type::Double)
           << QgsField(QStringLiteral("y"), QMetaType::Type::Double)
           << QgsField(QStringLiteral("value"), QMetaType::Type::Double);
    layer->dataProvider()->addAttributes(fields);
    layer->updateFields();
    // 4x4 grid, value = i + j (range 0..3).
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            QgsFeature feature(layer->fields());
            feature.setGeometry(QgsGeometry::fromPointXY(
                QgsPointXY(1000.0 + 100.0 * i, 2000.0 + 100.0 * j)));
            feature.setAttribute(QStringLiteral("x"), 1000.0 + 100.0 * i);
            feature.setAttribute(QStringLiteral("y"), 2000.0 + 100.0 * j);
            feature.setAttribute(QStringLiteral("value"), i + j);
            layer->dataProvider()->addFeature(feature);
        }
    }
    layer->updateExtents();
    return layer;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    PWB_CHECK(install_paleo_provider());

    QTemporaryDir temp_dir;
    PWB_CHECK(temp_dir.isValid());
    QgsVectorLayer* samples = make_sample_layer();
    PWB_CHECK(samples->isValid());
    PWB_CHECK(samples->featureCount() == 16);

    const QString idw_id = paleo_id(kAlgInterpolationIdw);

    // --- IDW run -----------------------------------------------------------
    QgsProcessingFeedback feedback;
    QVariantMap idw_params;
    idw_params.insert(QStringLiteral("INPUT"),
                      QVariant::fromValue<QgsMapLayer*>(samples));
    idw_params.insert(QStringLiteral("XFIELD"), QStringLiteral("x"));
    idw_params.insert(QStringLiteral("YFIELD"), QStringLiteral("y"));
    idw_params.insert(QStringLiteral("VALUEFIELD"), QStringLiteral("value"));
    idw_params.insert(QStringLiteral("GRID_N"), 16);
    idw_params.insert(QStringLiteral("CRS"), QStringLiteral("EPSG:32650"));
    const QString idw_path =
        temp_dir.path() + QStringLiteral("/idw.tif");
    idw_params.insert(QStringLiteral("OUTPUT"), idw_path);

    QVariantMap idw_results;
    QString error;
    bool cancelled = true;
    const bool idw_ok = run_paleo_algorithm(
        idw_id, idw_params, /*project=*/nullptr, &feedback, idw_results,
        error, &cancelled);
    PWB_CHECK_MSG(idw_ok, error.toStdString());
    PWB_CHECK(!cancelled);
    PWB_CHECK(QFile::exists(idw_results.value(QStringLiteral("OUTPUT")).toString()));
    // VALID_COUNT is the kernel's valid grid-cell count (the interpolation
    // adapters report grid statistics, like paleo:grid_statistics): a 16x16
    // IDW grid over the sample extent is fully valid.
    PWB_CHECK(idw_results.value(QStringLiteral("VALID_COUNT")).toInt() == 256);
    const double grid_min =
        idw_results.value(QStringLiteral("GRID_MIN")).toDouble();
    const double grid_max =
        idw_results.value(QStringLiteral("GRID_MAX")).toDouble();
    PWB_CHECK(grid_min <= grid_max);
    // IDW is a convex weighting: the grid stays inside the sample range.
    PWB_CHECK(grid_min >= 0.0 && grid_max <= 6.0);

    // --- output loads as a raster with the requested resolution -----------
    QgsRasterLayer raster(idw_path, QStringLiteral("idw_out"));
    PWB_CHECK_MSG(raster.isValid(), "idw output raster is not valid");
    PWB_CHECK(raster.width() == 16);
    PWB_CHECK(raster.height() == 16);

    // --- grid statistics over the produced tif ------------------------------
    QVariantMap stats_params;
    stats_params.insert(QStringLiteral("INPUT"), idw_path);
    stats_params.insert(QStringLiteral("BAND"), 1);
    QVariantMap stats_results;
    PWB_CHECK_MSG(run_paleo_algorithm(paleo_id(kAlgGridStatistics),
                                      stats_params, nullptr, nullptr,
                                      stats_results, error),
                  error.toStdString());
    PWB_CHECK(stats_results.value(QStringLiteral("TOTAL_COUNT")).toInt() ==
              256);
    PWB_CHECK(stats_results.value(QStringLiteral("VALID_COUNT")).toInt() > 0);

    // --- contours over the produced tif --------------------------------------
    QVariantMap contour_params;
    contour_params.insert(QStringLiteral("INPUT"), idw_path);
    contour_params.insert(QStringLiteral("LEVELS"),
                          QStringLiteral("0.5,1.5"));
    const QString contour_path =
        temp_dir.path() + QStringLiteral("/contours.gpkg");
    contour_params.insert(QStringLiteral("OUTPUT"), contour_path);
    QVariantMap contour_results;
    PWB_CHECK_MSG(run_paleo_algorithm(paleo_id(kAlgGridContours),
                                      contour_params, nullptr, nullptr,
                                      contour_results, error),
                  error.toStdString());
    PWB_CHECK(contour_results.value(QStringLiteral("LEVEL_COUNT")).toInt() ==
              2);
    const QString contour_uri =
        contour_results.value(QStringLiteral("OUTPUT")).toString();
    QgsVectorLayer contours(contour_uri, QStringLiteral("contours"));
    PWB_CHECK_MSG(contours.isValid(),
                  ("contour layer not loadable: " + contour_uri).toStdString());
    PWB_CHECK(contours.featureCount() > 0);

    // --- invalid input fails honestly ----------------------------------------
    QVariantMap bad_params = idw_params;
    bad_params.insert(QStringLiteral("XFIELD"), QStringLiteral("nope"));
    bad_params.insert(QStringLiteral("OUTPUT"),
                      temp_dir.path() + QStringLiteral("/bad.tif"));
    QVariantMap bad_results;
    PWB_CHECK(!run_paleo_algorithm(idw_id, bad_params, nullptr, nullptr,
                                   bad_results, error));
    PWB_CHECK(!error.isEmpty());

    // --- unknown algorithm fails honestly ------------------------------------
    QVariantMap unknown_results;
    PWB_CHECK(!run_paleo_algorithm(QStringLiteral("paleo:nope"), idw_params,
                                   nullptr, nullptr, unknown_results, error));
    PWB_CHECK(!error.isEmpty());

    // --- determinism: two identical runs agree on the grid extremes ----------
    QVariantMap rerun_params = idw_params;
    rerun_params.insert(QStringLiteral("OUTPUT"),
                        temp_dir.path() + QStringLiteral("/idw2.tif"));
    QVariantMap rerun_results;
    PWB_CHECK_MSG(run_paleo_algorithm(idw_id, rerun_params, nullptr, nullptr,
                                      rerun_results, error),
                  error.toStdString());
    PWB_CHECK(rerun_results.value(QStringLiteral("GRID_MIN")).toDouble() ==
              grid_min);
    PWB_CHECK(rerun_results.value(QStringLiteral("GRID_MAX")).toDouble() ==
              grid_max);
    PWB_CHECK(rerun_results.value(QStringLiteral("VALID_COUNT")).toInt() ==
              256);

    // --- scalar classification over the produced tif ---------------------------
    QVariantMap class_params;
    class_params.insert(QStringLiteral("INPUT"), idw_path);
    class_params.insert(QStringLiteral("CLASSES"), 4);
    QVariantMap class_results;
    PWB_CHECK_MSG(run_paleo_algorithm(paleo_id(kAlgScalarClassification),
                                      class_params, nullptr, nullptr,
                                      class_results, error),
                  error.toStdString());
    PWB_CHECK(!class_results.value(QStringLiteral("BREAKS")).toString().isEmpty());
    PWB_CHECK(class_results.value(QStringLiteral("CLASS_COUNT")).toInt() >=
              1);

    // --- factor extraction from a well-record JSON array -----------------------
    // Kernel coordinate-key family "xy" (x/y) + factor alias "sand_ratio"
    // (libs/mapping_kernel/src/extract.cpp kCoordFamilies / alias groups).
    QTemporaryDir records_dir;
    const QString records_path =
        records_dir.path() + QStringLiteral("/records.json");
    {
        QFile records(records_path);
        PWB_CHECK(records.open(QIODevice::WriteOnly | QIODevice::Text));
        QTextStream stream(&records);
        stream << "[\n";
        for (int i = 0; i < 5; ++i) {
            stream << QStringLiteral("{\"x\": %1, \"y\": %2, "
                                     "\"sand_ratio\": %3, \"well_name\": "
                                     "\"W%4\"}%5\n")
                          .arg(100.0 + 10.0 * i)
                          .arg(200.0 + 10.0 * i)
                          .arg(0.1 * (i + 1), 0, 'f', 2)
                          .arg(i)
                          .arg(i < 4 ? QStringLiteral(",")
                                     : QString());
        }
        stream << "]\n";
    }
    QVariantMap extract_params;
    extract_params.insert(QStringLiteral("RECORDS"), records_path);
    extract_params.insert(QStringLiteral("FACTOR"),
                          QStringLiteral("sand_ratio"));
    extract_params.insert(QStringLiteral("OUTPUT"),
                          temp_dir.path() + QStringLiteral("/factors.gpkg"));
    QVariantMap extract_results;
    PWB_CHECK_MSG(run_paleo_algorithm(paleo_id(kAlgExtractFactors),
                                      extract_params, nullptr, nullptr,
                                      extract_results, error),
                  error.toStdString());
    PWB_CHECK(extract_results.value(QStringLiteral("POINT_COUNT")).toInt() ==
              5);

    // --- raster axis roundtrip: grid_y ascending, row 0 = southern row ------
    // Regression: read_raster_grid used to build grid_y descending (from
    // yMaximum) while flipping the z rows, so every value landed on the
    // wrong row. Non-square 2-col x 3-row grid so an x/y mix-up cannot
    // cancel out; z = 10*row + col distinguishes rows from columns.
    {
        constexpr int kCols = 2;
        constexpr int kRows = 3;
        pwb::mapping::FactorGrid grid;
        grid.grid_x = {10.0, 20.0};
        grid.grid_y = {100.0, 200.0, 300.0};  // ascending: south -> north
        grid.grid_z.resize(static_cast<size_t>(kCols) * kRows);
        for (int r = 0; r < kRows; ++r) {
            for (int c = 0; c < kCols; ++c) {
                grid.grid_z[static_cast<size_t>(r) * kCols + c] =
                    10.0 * r + c;
            }
        }
        const QString axis_path =
            temp_dir.path() + QStringLiteral("/axis.tif");
        QString axis_error;
        PWB_CHECK_MSG(write_factor_grid_raster(
                          grid, QgsCoordinateReferenceSystem(
                                    QStringLiteral("EPSG:32650")),
                          axis_path, /*include_variance=*/false, axis_error),
                      axis_error.toStdString());

        // Ground truth against QGIS north-up convention: raster block row
        // 0 is the NORTHERN row, so it carries the y=300 row's values.
        {
            QgsRasterLayer written(axis_path, QStringLiteral("axis"));
            PWB_CHECK_MSG(written.isValid(), "axis raster is not valid");
            std::unique_ptr<QgsRasterBlock> block(
                written.dataProvider()->block(1, written.extent(),
                                              written.width(),
                                              written.height()));
            PWB_CHECK(block != nullptr && block->isValid());
            PWB_CHECK(std::abs(block->value(0, 0) - 20.0) < 1e-4);  // 10*2+0
            PWB_CHECK(std::abs(block->value(kRows - 1, 0) - 0.0) < 1e-4);
        }

        // Read back through the bridge: y axis ascending, row 0 southern.
        QgsRasterLayer axis_layer(axis_path, QStringLiteral("axis-read"));
        PWB_CHECK(axis_layer.isValid());
        QString read_error;
        const GridBand axis_band =
            read_raster_grid(&axis_layer, 1, nullptr, read_error);
        PWB_CHECK_MSG(read_error.isEmpty(), read_error.toStdString());
        PWB_CHECK(axis_band.grid.grid_x.size() == kCols);
        PWB_CHECK(axis_band.grid.grid_y.size() == kRows);
        PWB_CHECK(axis_band.grid.grid_y.front() <
                  axis_band.grid.grid_y.back());
        PWB_CHECK(axis_band.grid.grid_x.front() <
                  axis_band.grid.grid_x.back());
        PWB_CHECK(axis_band.grid.grid_z.size() ==
                  static_cast<size_t>(kCols) * kRows);
        PWB_CHECK(std::abs(axis_band.grid.grid_z[0] - 0.0) < 1e-4);
        PWB_CHECK(std::abs(
                      axis_band.grid.grid_z[static_cast<size_t>(kRows - 1) *
                                               kCols] -
                      (10.0 * (kRows - 1))) < 1e-4);
        PWB_CHECK(std::abs(
                      axis_band.grid.grid_z.back() -
                      (10.0 * (kRows - 1) + (kCols - 1))) < 1e-4);
    }

    delete samples;
    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("qgis_processing.run");
}
