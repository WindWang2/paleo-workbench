// Paleo interpolation algorithms for QGIS Processing.
//
// Thin adapters over the Qt-free mapping kernels:
//   paleo:interpolation_idw / _kriging  -> mapping::interpolate_factor
//   paleo:interpolation_constrained     -> mapping::generate_constrained_idw
//   paleo:interpolation_scipy           -> mapping::interpolate_scipy_grid
//   paleo:interpolation_directional     -> mapping::directional_trend_grid
//
// The kernels are frozen against Python oracle fixtures; this file only
// translates parameters/results, never numerics.

#include <QVariant>

#include <qgsexception.h>
#include <qgsfields.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>
#include <qgsprocessingparameters.h>

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/grid_io.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/mapping/constrained_idw.hpp>
#include <pwb/mapping/directional_trend.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/scipy_grid.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <vector>

namespace pwb::qgis_processing {

using pwb::mapping::SamplePoint;

namespace {

// interpolate_factor / kriging share one implementation body.
class InterpolationAlgorithm final : public PaleoAlgorithm {
public:
    explicit InterpolationAlgorithm(bool kriging) : kriging_(kriging) {}

    QString name() const override {
        return QString::fromLatin1(kriging_ ? kAlgInterpolationKriging
                                            : kAlgInterpolationIdw);
    }
    QString displayName() const override {
        return kriging_ ? QStringLiteral("Kriging interpolation (ordinary)")
                        : QStringLiteral("IDW interpolation");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupInterpolation); }
    QString group() const override { return QStringLiteral("Interpolation"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Interpolates sample points onto a regular factor grid using the Paleo "
            "kernel (IDW power weighting or ordinary kriging with a variogram "
            "model). Output is a float32 GeoTIFF, NaN as nodata; kriging also "
            "writes the variance grid as band 2.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        add_point_table_params(
            [this](std::unique_ptr<QgsProcessingParameterDefinition> definition) {
                addParameter(definition.release());
            });
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("GRID_N"), QStringLiteral("Grid resolution (cells per axis)"),
            Qgis::ProcessingNumberParameterType::Integer, 50, false, 8, 2048));
        if (!kriging_) {
            addParameter(new QgsProcessingParameterNumber(
                QStringLiteral("POWER"), QStringLiteral("IDW power"),
                Qgis::ProcessingNumberParameterType::Double, 2.0, false, 0.1, 20.0));
            addParameter(new QgsProcessingParameterNumber(
                QStringLiteral("MAX_NEIGHBORS"), QStringLiteral("Maximum neighbors"),
                Qgis::ProcessingNumberParameterType::Integer, QVariant(), true, 1, 10000));
            addParameter(new QgsProcessingParameterNumber(
                QStringLiteral("SEARCH_RADIUS"), QStringLiteral("Search radius"),
                Qgis::ProcessingNumberParameterType::Double, QVariant(), true, 0.0));
        } else {
            addParameter(new QgsProcessingParameterEnum(
                QStringLiteral("VARIOGRAM"), QStringLiteral("Variogram model"),
                QStringList() << QStringLiteral("spherical")
                              << QStringLiteral("exponential")
                              << QStringLiteral("gaussian")));
        }
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("VALID_COUNT"),
            QStringLiteral("Valid grid cell count")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("GRID_MIN"), QStringLiteral("Grid minimum")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("GRID_MAX"), QStringLiteral("Grid maximum")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const PointTable table = read_point_table(parameters, context, feedback);

        pwb::mapping::InterpolateOptions options;
        options.method = kriging_ ? "kriging" : "idw";
        options.grid_n = parameterAsInt(parameters, QStringLiteral("GRID_N"), context);
        options.crs = table.crs.isValid() ? table.crs.toWkt().toStdString() : std::string();
        if (!kriging_) {
            options.power = parameterAsDouble(parameters, QStringLiteral("POWER"), context);
            const QVariant max_neighbors =
                parameters.value(QStringLiteral("MAX_NEIGHBORS"));
            if (max_neighbors.isValid() && !max_neighbors.isNull()) {
                options.max_neighbors = max_neighbors.toInt();
            }
            const QVariant search_radius =
                parameters.value(QStringLiteral("SEARCH_RADIUS"));
            if (search_radius.isValid() && !search_radius.isNull() &&
                search_radius.toDouble() > 0.0) {
                options.search_radius = search_radius.toDouble();
            }
        } else {
            static const char* kVariograms[] = {"spherical", "exponential", "gaussian"};
            const int index =
                parameterAsEnum(parameters, QStringLiteral("VARIOGRAM"), context);
            options.variogram_model = kVariograms[std::clamp(index, 0, 2)];
        }

        const pwb::mapping::FactorGrid grid =
            pwb::mapping::interpolate_factor(table.points, options);
        if (feedback != nullptr && feedback->isCanceled()) {
            return {};
        }

        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        QString error;
        if (!write_factor_grid_raster(grid, table.crs, output_path,
                                      /*include_variance=*/kriging_, error)) {
            throw QgsProcessingException(error);
        }
        context.addLayerToLoadOnCompletion(
            output_path, QgsProcessingContext::LayerDetails(
                             displayName(), context.project(), QStringLiteral("OUTPUT")));

        const pwb::mapping::GridStatistics statistics =
            pwb::mapping::grid_statistics(grid.grid_z);
        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("VALID_COUNT"), statistics.valid_count);
        results.insert(QStringLiteral("GRID_MIN"),
                       std::isnan(statistics.min) ? QVariant() : QVariant(statistics.min));
        results.insert(QStringLiteral("GRID_MAX"),
                       std::isnan(statistics.max) ? QVariant() : QVariant(statistics.max));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new InterpolationAlgorithm(kriging_);
    }

private:
    bool kriging_;
};

// Constrained IDW (Haiyou engine): points + barriers/directions/boundary.
// Registered only when the kernel carries the CONV-05 engine.
#ifdef PWB_MAPPING_HAS_CONSTRAINED_IDW
class ConstrainedInterpolationAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgInterpolationConstrained);
    }
    QString displayName() const override {
        return QStringLiteral("Constrained IDW interpolation (faults / directions)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupInterpolation); }
    QString group() const override { return QStringLiteral("Interpolation"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Interpolates well control points with the constrained IDW engine: "
            "barrier lines (faults) block interpolation, direction lines guide "
            "trends, an optional boundary polygon clips the domain. Optionally "
            "emits the engine's contour polylines as a line layer.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        add_point_table_params(
            [this](std::unique_ptr<QgsProcessingParameterDefinition> definition) {
                addParameter(definition.release());
            });
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("BARRIERS"), QStringLiteral("Barrier lines (faults)"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorLine),
            QVariant(), true));
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("DIRECTIONS"), QStringLiteral("Direction lines"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorLine),
            QVariant(), true));
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("BOUNDARY"), QStringLiteral("Boundary polygon"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorPolygon),
            QVariant(), true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("GRID_RESOLUTION"), QStringLiteral("Grid resolution"),
            Qgis::ProcessingNumberParameterType::Integer, 160, false, 16, 1024));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("POWER"), QStringLiteral("IDW power"),
            Qgis::ProcessingNumberParameterType::Double, 2.0, false, 0.1, 20.0));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SEARCH_RADIUS"), QStringLiteral("Search radius"),
            Qgis::ProcessingNumberParameterType::Double, 10000.0, false, 0.0));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("DECLUSTER_RADIUS"), QStringLiteral("Decluster radius"),
            Qgis::ProcessingNumberParameterType::Double, 6500.0, false, 0.0));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("VALUE_MIN"), QStringLiteral("Value clamp minimum"),
            Qgis::ProcessingNumberParameterType::Double, QVariant(), true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("VALUE_MAX"), QStringLiteral("Value clamp maximum"),
            Qgis::ProcessingNumberParameterType::Double, QVariant(), true));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("CONTOURS"), QStringLiteral("Contour lines"),
            Qgis::ProcessingSourceType::VectorLine, QVariant(), true));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("DIAGNOSTIC_COUNT"), QStringLiteral("Diagnostic count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const PointTable table = read_point_table(parameters, context, feedback);

        std::vector<pwb::mapping::constrained_idw::Well> wells;
        wells.reserve(table.points.size());
        for (const SamplePoint& point : table.points) {
            wells.push_back(pwb::mapping::constrained_idw::Well{.x = point.x,
                                               .y = point.y,
                                               .value = point.value,
                                               .is_control_point = false});
        }

        QString error;
        std::vector<pwb::mapping::constrained_idw::BarrierLine> barriers;
        if (std::unique_ptr<QgsProcessingFeatureSource> source = std::unique_ptr<
                QgsProcessingFeatureSource>(parameterAsSource(
                parameters, QStringLiteral("BARRIERS"), context))) {
            barriers = read_barrier_lines(source.get(), feedback, error);
            if (!error.isEmpty()) throw QgsProcessingException(error);
        }
        std::vector<pwb::mapping::constrained_idw::DirectionLine> directions;
        if (std::unique_ptr<QgsProcessingFeatureSource> source = std::unique_ptr<
                QgsProcessingFeatureSource>(parameterAsSource(
                parameters, QStringLiteral("DIRECTIONS"), context))) {
            directions = read_direction_lines(source.get(), feedback, error);
            if (!error.isEmpty()) throw QgsProcessingException(error);
        }
        std::vector<pwb::mapping::constrained_idw::BoundaryPolygon> boundaries;
        if (std::unique_ptr<QgsProcessingFeatureSource> source = std::unique_ptr<
                QgsProcessingFeatureSource>(parameterAsSource(
                parameters, QStringLiteral("BOUNDARY"), context))) {
            pwb::mapping::constrained_idw::BoundaryPolygon boundary =
                read_boundary_polygon(source.get(), feedback, error);
            if (!error.isEmpty()) throw QgsProcessingException(error);
            boundaries.push_back(std::move(boundary));
        }

        pwb::mapping::constrained_idw::Config config;
        config.grid_resolution =
            parameterAsInt(parameters, QStringLiteral("GRID_RESOLUTION"), context);
        config.power = parameterAsDouble(parameters, QStringLiteral("POWER"), context);
        config.search_radius =
            parameterAsDouble(parameters, QStringLiteral("SEARCH_RADIUS"), context);
        config.decluster_radius =
            parameterAsDouble(parameters, QStringLiteral("DECLUSTER_RADIUS"), context);
        const QVariant value_min = parameters.value(QStringLiteral("VALUE_MIN"));
        config.value_min = (value_min.isValid() && !value_min.isNull())
                               ? std::optional<double>(value_min.toDouble())
                               : std::nullopt;
        const QVariant value_max = parameters.value(QStringLiteral("VALUE_MAX"));
        config.value_max = (value_max.isValid() && !value_max.isNull())
                               ? std::optional<double>(value_max.toDouble())
                               : std::nullopt;

        const pwb::mapping::constrained_idw::Result result = pwb::mapping::constrained_idw::generate_constrained_idw(
            wells, boundaries, barriers, directions, config);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        // Kernel result uses double grids; bridge to FactorGrid for output.
        pwb::mapping::FactorGrid grid;
        grid.grid_x = result.grid_x;
        grid.grid_y = result.grid_y;
        grid.grid_z.reserve(result.grid_z.size());
        for (const double value : result.grid_z) {
            grid.grid_z.push_back(static_cast<float>(value));
        }
        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        if (!write_factor_grid_raster(grid, table.crs, output_path, false, error)) {
            throw QgsProcessingException(error);
        }
        context.addLayerToLoadOnCompletion(
            output_path, QgsProcessingContext::LayerDetails(
                             displayName(), context.project(), QStringLiteral("OUTPUT")));

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("DIAGNOSTIC_COUNT"),
                       static_cast<qlonglong>(result.diagnostics.size()));

        // Optional contour output (level-attributed line layer).
        const QVariant contours_param = parameters.value(QStringLiteral("CONTOURS"));
        if (contours_param.isValid() && !contours_param.isNull()) {
            QgsFields fields;
            fields.append(QgsField(QStringLiteral("level"), QMetaType::Type::Double));
            QString sink_id;
            // Caller-owned sink (QGIS core contract): destruction finalizes
            // the output file. A raw pointer here leaks the writer and
            // leaves file sinks without their committed layer.
            std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
                parameters, QStringLiteral("CONTOURS"), context, sink_id, fields,
                Qgis::WkbType::LineString, table.crs));
            if (sink == nullptr) {
                throw QgsProcessingException(
                    QStringLiteral("failed to create contour output sink"));
            }
            for (const auto& [level, polylines] : result.contours) {
                if (!add_polyline_features(sink.get(), fields, polylines, level,
                                           /*level_field_index=*/0, error)) {
                    throw QgsProcessingException(error);
                }
                if (feedback != nullptr && feedback->isCanceled()) break;
            }
            results.insert(QStringLiteral("CONTOURS"), sink_id);
        }
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ConstrainedInterpolationAlgorithm();
    }
};

#endif  // PWB_MAPPING_HAS_CONSTRAINED_IDW

// Shared body for scipy-grid and directional-trend interpolation: caller
// supplies the grid fill.
class AxisGridAlgorithm : public PaleoAlgorithm {
protected:
    // Axes from optional EXTENT (padded axes come from the caller's extent
    // directly — no extra padding here) or from the point bounding box.
    [[nodiscard]] std::pair<std::vector<double>, std::vector<double>> grid_axes(
        const QVariantMap& parameters, QgsProcessingContext& context,
        const std::vector<SamplePoint>& points, int grid_n) const {
        QgsRectangle extent = parameterAsExtent(parameters, QStringLiteral("EXTENT"),
                                                context);
        if (!extent.isEmpty()) {
            return {pwb::mapping::linspace(extent.xMinimum(), extent.xMaximum(), grid_n),
                    pwb::mapping::linspace(extent.yMinimum(), extent.yMaximum(), grid_n)};
        }
        if (points.empty()) {
            throw QgsProcessingException(
                QStringLiteral("no extent given and no points to derive one"));
        }
        const std::array<double, 4> bounds = pwb::mapping::dataset_extent(points);
        return {pwb::mapping::linspace(bounds[0], bounds[2], grid_n),
                pwb::mapping::linspace(bounds[1], bounds[3], grid_n)};
    }

    void publish_grid(const std::vector<double>& grid_z, const std::vector<double>& grid_x,
                      const std::vector<double>& grid_y,
                      const QgsCoordinateReferenceSystem& crs,
                      const QVariantMap& parameters, QgsProcessingContext& context,
                      QgsProcessingFeedback* feedback, QVariantMap& results) const {
        pwb::mapping::FactorGrid grid;
        grid.grid_x = grid_x;
        grid.grid_y = grid_y;
        grid.grid_z.reserve(grid_z.size());
        for (const double value : grid_z) {
            grid.grid_z.push_back(static_cast<float>(value));
        }
        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        QString error;
        if (!write_factor_grid_raster(grid, crs, output_path, false, error)) {
            throw QgsProcessingException(error);
        }
        context.addLayerToLoadOnCompletion(
            output_path, QgsProcessingContext::LayerDetails(
                             displayName(), context.project(), QStringLiteral("OUTPUT")));
        results.insert(QStringLiteral("OUTPUT"), output_path);
        if (feedback != nullptr) feedback->setProgress(100.0);
    }
};

class ScipyInterpolationAlgorithm final : public AxisGridAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgInterpolationScipy);
    }
    QString displayName() const override {
        return QStringLiteral("Grid interpolation (linear / nearest / RBF)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupInterpolation); }
    QString group() const override { return QStringLiteral("Interpolation"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Delaunay linear / nearest / CloughTocher-RBF scattered interpolation "
            "onto a regular grid (scipy griddata parity). Cells outside the "
            "convex hull are nodata unless masking is disabled.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        add_point_table_params(
            [this](std::unique_ptr<QgsProcessingParameterDefinition> definition) {
                addParameter(definition.release());
            });
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("METHOD"), QStringLiteral("Method"),
            QStringList() << QStringLiteral("linear") << QStringLiteral("nearest")
                          << QStringLiteral("rbf")));
        addParameter(new QgsProcessingParameterExtent(
            QStringLiteral("EXTENT"), QStringLiteral("Grid extent (optional)"),
            QVariant(), true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("GRID_N"), QStringLiteral("Grid resolution"),
            Qgis::ProcessingNumberParameterType::Integer, 50, false, 8, 2048));
        addParameter(new QgsProcessingParameterBoolean(
            QStringLiteral("MASK_CONVEX_HULL"), QStringLiteral("Mask outside convex hull"),
            true));
        addOutput(new QgsProcessingOutputString(
            QStringLiteral("FALLBACK"), QStringLiteral("Fallback method (if any)")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const PointTable table = read_point_table(parameters, context, feedback);
        static const char* kMethods[] = {"linear", "nearest", "rbf"};
        const int method_index =
            parameterAsEnum(parameters, QStringLiteral("METHOD"), context);
        const int grid_n = parameterAsInt(parameters, QStringLiteral("GRID_N"), context);
        const auto [grid_x, grid_y] =
            grid_axes(parameters, context, table.points, grid_n);

        std::vector<double> xs, ys, zs;
        xs.reserve(table.points.size());
        ys.reserve(table.points.size());
        zs.reserve(table.points.size());
        for (const SamplePoint& point : table.points) {
            xs.push_back(point.x);
            ys.push_back(point.y);
            zs.push_back(point.value);
        }
        const pwb::mapping::ScipyGridResult result = pwb::mapping::interpolate_scipy_grid(
            xs, ys, zs, grid_x, grid_y, kMethods[std::clamp(method_index, 0, 2)],
            parameterAsBool(parameters, QStringLiteral("MASK_CONVEX_HULL"), context));
        if (feedback != nullptr && feedback->isCanceled()) return {};

        QVariantMap results;
        publish_grid(result.grid_z, grid_x, grid_y, table.crs, parameters, context,
                     feedback, results);
        results.insert(QStringLiteral("FALLBACK"),
                       QString::fromStdString(result.fallback));
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ScipyInterpolationAlgorithm();
    }
};

class DirectionalTrendAlgorithm final : public AxisGridAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgInterpolationDirectional);
    }
    QString displayName() const override {
        return QStringLiteral("Directional trend surface");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupInterpolation); }
    QString group() const override { return QStringLiteral("Interpolation"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Anisotropic directional trend surface (azimuth, range ratio a/b, "
            "weights) over scattered samples.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        add_point_table_params(
            [this](std::unique_ptr<QgsProcessingParameterDefinition> definition) {
                addParameter(definition.release());
            });
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("AZIMUTH"), QStringLiteral("Azimuth (degrees)"),
            Qgis::ProcessingNumberParameterType::Double, 0.0, false, -360.0, 360.0));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("A"), QStringLiteral("Major range a"),
            Qgis::ProcessingNumberParameterType::Double, 1.0, false, 1e-9));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("B"), QStringLiteral("Minor range ratio b"),
            Qgis::ProcessingNumberParameterType::Double, 0.4, false, 1e-9, 1.0));
        addParameter(new QgsProcessingParameterExtent(
            QStringLiteral("EXTENT"), QStringLiteral("Grid extent (optional)"),
            QVariant(), true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("GRID_N"), QStringLiteral("Grid resolution"),
            Qgis::ProcessingNumberParameterType::Integer, 50, false, 8, 2048));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const PointTable table = read_point_table(parameters, context, feedback);
        const int grid_n = parameterAsInt(parameters, QStringLiteral("GRID_N"), context);
        const auto [grid_x, grid_y] =
            grid_axes(parameters, context, table.points, grid_n);

        std::vector<double> xs, ys, zs;
        xs.reserve(table.points.size());
        ys.reserve(table.points.size());
        zs.reserve(table.points.size());
        for (const SamplePoint& point : table.points) {
            xs.push_back(point.x);
            ys.push_back(point.y);
            zs.push_back(point.value);
        }
        const std::vector<double> grid_z = pwb::mapping::directional_trend_grid(
            xs, ys, zs, grid_x, grid_y,
            parameterAsDouble(parameters, QStringLiteral("AZIMUTH"), context),
            parameterAsDouble(parameters, QStringLiteral("A"), context),
            parameterAsDouble(parameters, QStringLiteral("B"), context));
        if (feedback != nullptr && feedback->isCanceled()) return {};

        QVariantMap results;
        publish_grid(grid_z, grid_x, grid_y, table.crs, parameters, context, feedback,
                     results);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new DirectionalTrendAlgorithm();
    }
};

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_interpolation_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new InterpolationAlgorithm(/*kriging=*/false));
    algorithms.push_back(new InterpolationAlgorithm(/*kriging=*/true));
#ifdef PWB_MAPPING_HAS_CONSTRAINED_IDW
    algorithms.push_back(new ConstrainedInterpolationAlgorithm());
#endif
    algorithms.push_back(new ScipyInterpolationAlgorithm());
    algorithms.push_back(new DirectionalTrendAlgorithm());
    return algorithms;
}

}  // namespace pwb::qgis_processing
