// Paleo mapping/grid algorithms for QGIS Processing: contour extraction,
// contour layer product, grid statistics, factor extraction, ring clip and
// ring repair. Thin adapters over the Qt-free mapping kernels.

#include <QVariant>

#include <qgsexception.h>
#include <qgsfeature.h>
#include <qgsfeatureiterator.h>
#include <qgsfeaturesink.h>
#include <qgsfields.h>
#include <qgscurve.h>
#include <qgscurvepolygon.h>
#include <qgsgeometry.h>
#include <qgspolygon.h>
#include <qgspointxy.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>
#include <qgsrasterlayer.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/grid_io.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/layer_products.hpp>
#include <pwb/mapping/ring_ops.hpp>

#include <cmath>
#include <fstream>
#include <limits>
#include <memory>
#include <vector>

namespace pwb::qgis_processing {

using pwb::mapping::Point;
using pwb::mapping::Polygon;
using pwb::mapping::Polyline;
using pwb::mapping::Ring;

namespace {

// ---- paleo:grid_contours ---------------------------------------------------

class GridContoursAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgGridContours); }
    QString displayName() const override { return QStringLiteral("Contours from grid"); }
    QString groupId() const override { return QString::fromLatin1(kGroupMapping); }
    QString group() const override { return QStringLiteral("Mapping"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Marching-squares contour lines from a raster band (Paleo kernel "
            "parity: NaN/nodata cells never seed a contour). Levels come "
            "from an explicit list, an interval, or the nice-ladder/quantile "
            "heuristics.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterRasterLayer(
            QStringLiteral("INPUT"), QStringLiteral("Input grid")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("BAND"), QStringLiteral("Band"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1, 256));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("LEVELS"), QStringLiteral("Explicit levels (comma separated)"),
            QVariant(), false, true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("INTERVAL"), QStringLiteral("Contour interval (0 = auto)"),
            Qgis::ProcessingNumberParameterType::Double, 0.0, false, 0.0));
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("LEVELING"), QStringLiteral("Auto leveling mode"),
            QStringList() << QStringLiteral("nice") << QStringLiteral("quantile")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("TARGET"), QStringLiteral("Target level count (auto modes)"),
            Qgis::ProcessingNumberParameterType::Integer, 7, false, 2, 64));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SIMPLIFY"), QStringLiteral("Simplify tolerance"),
            Qgis::ProcessingNumberParameterType::Double, 0.0, false, 0.0));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SMOOTH"), QStringLiteral("Chaikin smoothing iterations"),
            Qgis::ProcessingNumberParameterType::Integer, 0, false, 0, 16));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Contour lines"),
            Qgis::ProcessingSourceType::VectorLine));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("LEVEL_COUNT"), QStringLiteral("Emitted level count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QgsRasterLayer* layer = parameterAsRasterLayer(
            parameters, QStringLiteral("INPUT"), context);
        QString error;
        const GridBand band = read_raster_grid(
            layer, parameterAsInt(parameters, QStringLiteral("BAND"), context),
            feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        const pwb::mapping::Grid& grid = band.grid;

        double vmin = std::numeric_limits<double>::quiet_NaN();
        double vmax = std::numeric_limits<double>::quiet_NaN();
        for (const double value : grid.grid_z) {
            if (!std::isfinite(value)) continue;
            vmin = std::isnan(vmin) ? value : std::min(vmin, value);
            vmax = std::isnan(vmax) ? value : std::max(vmax, value);
        }
        std::vector<double> levels;
        const QString explicit_levels =
            parameterAsString(parameters, QStringLiteral("LEVELS"), context);
        if (!explicit_levels.isEmpty()) {
            for (const QString& token : explicit_levels.split(
                     ',', Qt::SkipEmptyParts)) {
                bool ok = false;
                const double value = token.trimmed().toDouble(&ok);
                if (ok && std::isfinite(value)) levels.push_back(value);
            }
            if (levels.empty()) {
                throw QgsProcessingException(
                    QStringLiteral("LEVELS given but no finite value parsed"));
            }
        } else if (std::isnan(vmin) || std::isnan(vmax)) {
            throw QgsProcessingException(
                QStringLiteral("input grid has no finite cells to contour"));
        } else {
            const double interval =
                parameterAsDouble(parameters, QStringLiteral("INTERVAL"), context);
            if (interval > 0.0) {
                for (double level = std::ceil(vmin / interval) * interval;
                     level <= vmax + interval * 1e-9; level += interval) {
                    levels.push_back(level);
                }
            } else if (parameterAsEnum(parameters, QStringLiteral("LEVELING"),
                                      context) == 1) {
                const int target = std::max(
                    2, parameterAsInt(parameters, QStringLiteral("TARGET"), context));
                std::vector<double> quantiles;
                quantiles.reserve(static_cast<size_t>(target));
                for (int i = 1; i <= target; ++i) {
                    quantiles.push_back(static_cast<double>(i) /
                                        static_cast<double>(target + 1));
                }
                levels = pwb::mapping::quantile_contour_levels(grid, quantiles);
            } else {
                levels = pwb::mapping::nice_contour_levels(
                    vmin, vmax,
                    parameterAsInt(parameters, QStringLiteral("TARGET"), context));
            }
        }

        QgsFields fields;
        fields.append(QgsField(QStringLiteral("level"), QMetaType::Type::Double));
        QString sink_id;
        // Caller-owned sink (QGIS core contract): destruction finalizes the
        // output file. A raw pointer here leaks the writer and leaves GPKG
        // outputs without their committed layer.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::LineString, band.crs));
        if (sink == nullptr) {
            throw QgsProcessingException(QStringLiteral("failed to create output sink"));
        }

        const double simplify =
            parameterAsDouble(parameters, QStringLiteral("SIMPLIFY"), context);
        const int smooth =
            parameterAsInt(parameters, QStringLiteral("SMOOTH"), context);
        int total_levels = static_cast<int>(levels.size());
        int done = 0;
        for (const double level : levels) {
            if (feedback != nullptr && feedback->isCanceled()) break;
            const std::vector<Polyline> polylines = pwb::mapping::marching_squares_contours(
                grid, level, simplify, smooth);
            if (!add_polyline_features(sink.get(), fields, polylines, level,
                                       /*level_field_index=*/0, error)) {
                throw QgsProcessingException(error);
            }
            ++done;
            if (feedback != nullptr) {
                feedback->setProgress(100.0 * done / static_cast<double>(total_levels));
            }
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("LEVEL_COUNT"), done);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new GridContoursAlgorithm();
    }
};

// ---- paleo:contour_layer_product -------------------------------------------

class ContourLayerProductAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgContourLayerProduct);
    }
    QString displayName() const override {
        return QStringLiteral("Contour layer product (labeled GeoJSON parity)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupMapping); }
    QString group() const override { return QStringLiteral("Mapping"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Full contour layer product: level ladder (explicit/interval/nice/"
            "quantile), labeled features with index-contour flags and QC "
            "counters, emitted as a line layer with the kernel's attribute "
            "schema.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterRasterLayer(
            QStringLiteral("INPUT"), QStringLiteral("Input factor grid")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("BAND"), QStringLiteral("Band"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1, 256));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("FACTOR"), QStringLiteral("Factor name"),
            QStringLiteral("factor")));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("UNIT"), QStringLiteral("Value unit"), QVariant(),
            false, true));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("LEVELS"), QStringLiteral("Explicit levels (comma separated)"),
            QVariant(), false, true));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("INTERVAL"), QStringLiteral("Contour interval (0 = auto)"),
            Qgis::ProcessingNumberParameterType::Double, 0.0, false, 0.0));
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("LEVELING"), QStringLiteral("Auto leveling mode"),
            QStringList() << QStringLiteral("nice") << QStringLiteral("quantile")));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Contour layer"),
            Qgis::ProcessingSourceType::VectorLine));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("FEATURE_COUNT"), QStringLiteral("Feature count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QgsRasterLayer* layer = parameterAsRasterLayer(
            parameters, QStringLiteral("INPUT"), context);
        QString error;
        const GridBand band = read_raster_grid(
            layer, parameterAsInt(parameters, QStringLiteral("BAND"), context),
            feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);

        pwb::mapping::FactorGrid grid;
        grid.grid_x = band.grid.grid_x;
        grid.grid_y = band.grid.grid_y;
        grid.grid_z.resize(band.grid.grid_z.size());
        for (size_t i = 0; i < band.grid.grid_z.size(); ++i) {
            grid.grid_z[i] = static_cast<float>(band.grid.grid_z[i]);
        }

        pwb::mapping::LayerGridContext layer_context;
        layer_context.factor_name =
            parameterAsString(parameters, QStringLiteral("FACTOR"), context)
                .toStdString();
        layer_context.unit =
            parameterAsString(parameters, QStringLiteral("UNIT"), context)
                .toStdString();
        layer_context.crs = band.crs.isValid() ? band.crs.authid().toStdString()
                                               : std::string();

        pwb::mapping::ContourLayerOptions options;
        const QString explicit_levels =
            parameterAsString(parameters, QStringLiteral("LEVELS"), context);
        if (!explicit_levels.isEmpty()) {
            std::vector<double> levels;
            for (const QString& token : explicit_levels.split(
                     ',', Qt::SkipEmptyParts)) {
                bool ok = false;
                const double value = token.trimmed().toDouble(&ok);
                if (ok && std::isfinite(value)) levels.push_back(value);
            }
            if (!levels.empty()) options.levels = levels;
        }
        const double interval =
            parameterAsDouble(parameters, QStringLiteral("INTERVAL"), context);
        if (interval > 0.0) options.interval = interval;
        options.leveling_mode =
            parameterAsEnum(parameters, QStringLiteral("LEVELING"), context) == 1
                ? "quantile"
                : "nice";

        const pwb::mapping::ContourLayerProduct product =
            pwb::mapping::generate_contour_layer_product(grid, layer_context, options);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        // Kernel emits GeoJSON features; bridge to a QGIS sink with the same
        // attribute schema (level, label_text, is_index_contour, length,
        // is_closed, factor, unit).
        QgsFields fields;
        fields.append(QgsField(QStringLiteral("level"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("label_text"), QMetaType::Type::QString));
        fields.append(
            QgsField(QStringLiteral("is_index_contour"), QMetaType::Type::Bool));
        fields.append(QgsField(QStringLiteral("length"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("is_closed"), QMetaType::Type::Bool));
        fields.append(QgsField(QStringLiteral("factor"), QMetaType::Type::QString));
        fields.append(QgsField(QStringLiteral("unit"), QMetaType::Type::QString));
        QString sink_id;
        // Caller-owned sink: destruction finalizes the output file.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::LineString, band.crs));
        if (sink == nullptr) {
            throw QgsProcessingException(QStringLiteral("failed to create output sink"));
        }

        int feature_count = 0;
        for (const pwb::domain::Json& feature_json : product.features) {
            if (feedback != nullptr && feedback->isCanceled()) break;
            if (!feature_json.contains("geometry") ||
                !feature_json.contains("properties")) {
                continue;
            }
            const pwb::domain::Json& geometry = feature_json.at("geometry");
            const pwb::domain::Json& properties = feature_json.at("properties");
            if (geometry.value("type", std::string()) != "LineString") continue;
            QVector<QgsPointXY> points;
            for (const auto& coordinate : geometry.at("coordinates")) {
                if (!coordinate.is_array() || coordinate.size() < 2) continue;
                points.append(QgsPointXY(coordinate.at(0).get<double>(),
                                         coordinate.at(1).get<double>()));
            }
            if (points.size() < 2) continue;
            QgsFeature feature(fields);
            feature.setGeometry(QgsGeometry::fromPolylineXY(points));
            feature.setAttribute(0, QVariant(properties.value("level", 0.0)));
            feature.setAttribute(1, QVariant(QString::fromStdString(
                                             properties.value("label_text",
                                                              std::string()))));
            feature.setAttribute(2, QVariant(
                                     properties.value("is_index_contour", false)));
            feature.setAttribute(
                3, QVariant(properties.value("length", 0.0)));
            feature.setAttribute(
                4, QVariant(properties.value("is_closed", false)));
            feature.setAttribute(5, QVariant(QString::fromStdString(
                                             properties.value("factor",
                                                              std::string()))));
            feature.setAttribute(6, QVariant(QString::fromStdString(
                                             properties.value("unit",
                                                              std::string()))));
            if (sink->addFeature(feature, QgsFeatureSink::FastInsert)) {
                ++feature_count;
            }
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("FEATURE_COUNT"), feature_count);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ContourLayerProductAlgorithm();
    }
};

// ---- paleo:grid_statistics -------------------------------------------------

class GridStatisticsAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgGridStatistics); }
    QString displayName() const override { return QStringLiteral("Grid statistics"); }
    QString groupId() const override { return QString::fromLatin1(kGroupQuality); }
    QString group() const override { return QStringLiteral("Quality"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "min/max/mean/std and valid-cell statistics for a raster band "
            "(nodata-aware, float64 semantics — kernel parity).");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterRasterLayer(
            QStringLiteral("INPUT"), QStringLiteral("Input grid")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("BAND"), QStringLiteral("Band"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1, 256));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MIN"), QStringLiteral("Minimum")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MAX"), QStringLiteral("Maximum")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MEAN"), QStringLiteral("Mean")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("STD"), QStringLiteral("Standard deviation")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("VALID_COUNT"), QStringLiteral("Valid cell count")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("TOTAL_COUNT"), QStringLiteral("Total cell count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QgsRasterLayer* layer = parameterAsRasterLayer(
            parameters, QStringLiteral("INPUT"), context);
        QString error;
        const GridBand band = read_raster_grid(
            layer, parameterAsInt(parameters, QStringLiteral("BAND"), context),
            feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);

        std::vector<float> values(band.grid.grid_z.size());
        for (size_t i = 0; i < band.grid.grid_z.size(); ++i) {
            values[i] = static_cast<float>(band.grid.grid_z[i]);
        }
        const pwb::mapping::GridStatistics statistics =
            pwb::mapping::grid_statistics(values);

        QVariantMap results;
        results.insert(QStringLiteral("MIN"),
                       std::isnan(statistics.min) ? QVariant() : QVariant(statistics.min));
        results.insert(QStringLiteral("MAX"),
                       std::isnan(statistics.max) ? QVariant() : QVariant(statistics.max));
        results.insert(QStringLiteral("MEAN"),
                       std::isnan(statistics.mean) ? QVariant()
                                                   : QVariant(statistics.mean));
        results.insert(QStringLiteral("STD"),
                       std::isnan(statistics.std) ? QVariant() : QVariant(statistics.std));
        results.insert(QStringLiteral("VALID_COUNT"), statistics.valid_count);
        results.insert(QStringLiteral("TOTAL_COUNT"), statistics.total_count);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new GridStatisticsAlgorithm();
    }
};

// ---- paleo:extract_factors --------------------------------------------------

class ExtractFactorsAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgExtractFactors); }
    QString displayName() const override { return QStringLiteral("Extract factor samples"); }
    QString groupId() const override { return QString::fromLatin1(kGroupFactor); }
    QString group() const override { return QStringLiteral("Factor"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Extracts one factor's sample points from a well-record JSON array "
            "(coordinate-key families, value aliases and derived factors are "
            "kernel parity). Emits a point layer ready for interpolation.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("RECORDS"), QStringLiteral("Well records (JSON array)"),
            Qgis::ProcessingFileParameterBehavior::File, QStringLiteral("json")));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("FACTOR"), QStringLiteral("Factor name")));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Factor samples"),
            Qgis::ProcessingSourceType::VectorPoint));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("POINT_COUNT"), QStringLiteral("Sample count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const QString records_path =
            parameterAsFile(parameters, QStringLiteral("RECORDS"), context);
        std::ifstream input(records_path.toStdString(), std::ios::binary);
        if (!input) {
            throw QgsProcessingException(
                QStringLiteral("cannot open RECORDS file %1").arg(records_path));
        }
        pwb::domain::Json records;
        try {
            input >> records;
        } catch (const std::exception& parse_error) {
            throw QgsProcessingException(
                QStringLiteral("RECORDS is not valid JSON: %1")
                    .arg(QString::fromStdString(parse_error.what())));
        }

        const std::string factor =
            parameterAsString(parameters, QStringLiteral("FACTOR"), context)
                .toStdString();
        const pwb::mapping::FactorDataset dataset =
            pwb::mapping::extract_factors(records, factor);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        QgsFields fields;
        fields.append(QgsField(QStringLiteral("x"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("y"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("value"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("well_name"), QMetaType::Type::QString));
        fields.append(QgsField(QStringLiteral("unit"), QMetaType::Type::QString));
        QString sink_id;
        // Caller-owned sink: destruction finalizes the output file.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::Point, QgsCoordinateReferenceSystem()));
        if (sink == nullptr) {
            throw QgsProcessingException(QStringLiteral("failed to create output sink"));
        }

        for (const pwb::mapping::FactorPoint& point : dataset.points) {
            QgsFeature feature(fields);
            feature.setGeometry(
                QgsGeometry::fromPointXY(QgsPointXY(point.x, point.y)));
            feature.setAttribute(0, QVariant(point.x));
            feature.setAttribute(1, QVariant(point.y));
            feature.setAttribute(2, QVariant(point.value));
            feature.setAttribute(
                3, QVariant(QString::fromStdString(point.well_name)));
            feature.setAttribute(4, QVariant(QString::fromStdString(point.unit)));
            sink->addFeature(feature, QgsFeatureSink::FastInsert);
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("POINT_COUNT"),
                       static_cast<qlonglong>(dataset.points.size()));
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ExtractFactorsAlgorithm();
    }
};

// ---- paleo:clip_to_ring / paleo:repair_ring ---------------------------------
// Registered only when the kernel carries the CONV-04 ring ops (fail-closed
// for configurations built without them).
#ifdef PWB_MAPPING_HAS_RING_OPS

// Reads polygon parts (exterior + holes) from a feature source.
[[nodiscard]] std::vector<std::vector<Ring>> source_polygon_parts(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error) {
    std::vector<std::vector<Ring>> parts;
    if (source == nullptr) {
        error = QStringLiteral("input layer is missing");
        return parts;
    }
    QgsFeature feature;
    QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
    while (iterator.nextFeature(feature)) {
        std::vector<Ring> part;
        const QgsGeometry geometry = feature.geometry();
        for (auto it = geometry.const_parts_begin(); it != geometry.const_parts_end();
             ++it) {
            if (const QgsCurvePolygon* polygon =
                    dynamic_cast<const QgsCurvePolygon*>(*it)) {
                auto convert_ring = [](const QgsCurve* curve) {
                    Ring ring;
                    if (curve == nullptr) return ring;
                    QgsPointSequence sequence;
                    curve->points(sequence);
                    ring.reserve(sequence.size());
                    for (const QgsPoint& p : sequence) {
                        ring.push_back(Point{p.x(), p.y()});
                    }
                    return ring;
                };
                Ring exterior = convert_ring(polygon->exteriorRing());
                if (exterior.size() >= 3) part.push_back(std::move(exterior));
                for (int h = 0; h < polygon->numInteriorRings(); ++h) {
                    Ring hole = convert_ring(polygon->interiorRing(h));
                    if (hole.size() >= 3) part.push_back(std::move(hole));
                }
            }
        }
        if (!part.empty()) parts.push_back(std::move(part));
        if (feedback != nullptr && feedback->isCanceled()) break;
    }
    return parts;
}

void add_polygons_to_sink(QgsFeatureSink* sink, const QgsFields& fields,
                          const std::vector<Polygon>& polygons,
                          const QgsCoordinateReferenceSystem& crs,
                          qlonglong& added) {
    for (const Polygon& polygon : polygons) {
        QgsPolygonXY rings;
        auto convert = [](const Ring& ring) {
            QgsPolylineXY line;
            line.reserve(ring.size());
            for (const Point& p : ring) line.append(QgsPointXY(p[0], p[1]));
            return line;
        };
        rings.append(convert(polygon.exterior));
        for (const Ring& hole : polygon.holes) rings.append(convert(hole));
        QgsFeature feature(fields);
        feature.setGeometry(QgsGeometry::fromPolygonXY(rings));
        if (sink->addFeature(feature, QgsFeatureSink::FastInsert)) ++added;
    }
}

class ClipToRingAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgClipToRing); }
    QString displayName() const override {
        return QStringLiteral("Clip polygon to ring (bounded overlay)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupMapping); }
    QString group() const override { return QStringLiteral("Mapping"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Bounded polygon-vs-ring clip (boundary-arc overlay, split at "
            "transversal intersections). Inputs outside the bounded contract "
            "fail with an explicit unsupported reason instead of guessing.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("INPUT"), QStringLiteral("Subject polygons"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorPolygon)));
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("RING"), QStringLiteral("Clip ring (polygon)"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorPolygon)));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Clipped polygons"),
            Qgis::ProcessingSourceType::VectorPolygon));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("PART_COUNT"), QStringLiteral("Output part count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        std::unique_ptr<QgsProcessingFeatureSource> input(parameterAsSource(
            parameters, QStringLiteral("INPUT"), context));
        std::unique_ptr<QgsProcessingFeatureSource> ring_source(parameterAsSource(
            parameters, QStringLiteral("RING"), context));
        QString error;
        const std::vector<std::vector<Ring>> subject =
            source_polygon_parts(input.get(), feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        const std::vector<std::vector<Ring>> clip_parts =
            source_polygon_parts(ring_source.get(), feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        if (clip_parts.empty() || clip_parts.front().empty()) {
            throw QgsProcessingException(
                QStringLiteral("RING layer has no usable polygon ring"));
        }

        pwb::mapping::RingClipInput clip;
        clip.subject_is_multi = subject.size() > 1;
        clip.subject = subject;
        clip.clip_ring = clip_parts.front().front();
        const pwb::mapping::RingOpsResult result =
            pwb::mapping::clip_polygon_to_ring_bounded(clip);
        if (result.status != pwb::mapping::RingOpsStatus::ok) {
            throw QgsProcessingException(
                QStringLiteral("clip unsupported: %1")
                    .arg(QString::fromStdString(result.reason)));
        }

        QgsFields fields;  // geometry-only output
        QString sink_id;
        // Caller-owned sink: destruction finalizes the output file.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::Polygon, ring_source->sourceCrs()));
        qlonglong added = 0;
        add_polygons_to_sink(sink.get(), fields, result.polygons, ring_source->sourceCrs(),
                             added);

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("PART_COUNT"), added);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ClipToRingAlgorithm();
    }
};

class RepairRingAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgRepairRing); }
    QString displayName() const override {
        return QStringLiteral("Repair polygon rings (bounded)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupMapping); }
    QString group() const override { return QStringLiteral("Mapping"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Bounded ring repair (closure, orientation, single-intersection "
            "bowtie splits) with explicit unsupported failures.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("INPUT"), QStringLiteral("Polygons to repair"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorPolygon)));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Repaired polygons"),
            Qgis::ProcessingSourceType::VectorPolygon));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("PART_COUNT"), QStringLiteral("Output part count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        std::unique_ptr<QgsProcessingFeatureSource> input(parameterAsSource(
            parameters, QStringLiteral("INPUT"), context));
        QString error;
        const std::vector<std::vector<Ring>> parts =
            source_polygon_parts(input.get(), feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);

        pwb::mapping::RepairInput repair;
        repair.is_multi = parts.size() > 1;
        repair.parts = parts;
        const pwb::mapping::RingOpsResult result = pwb::mapping::repair_bounded(repair);
        if (result.status != pwb::mapping::RingOpsStatus::ok) {
            throw QgsProcessingException(
                QStringLiteral("repair unsupported: %1")
                    .arg(QString::fromStdString(result.reason)));
        }

        QgsFields fields;
        QString sink_id;
        // Caller-owned sink: destruction finalizes the output file.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::Polygon, input->sourceCrs()));
        qlonglong added = 0;
        add_polygons_to_sink(sink.get(), fields, result.polygons, input->sourceCrs(), added);

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("PART_COUNT"), added);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new RepairRingAlgorithm();
    }
};

#endif  // PWB_MAPPING_HAS_RING_OPS

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_mapping_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new GridContoursAlgorithm());
    algorithms.push_back(new ContourLayerProductAlgorithm());
    algorithms.push_back(new GridStatisticsAlgorithm());
    algorithms.push_back(new ExtractFactorsAlgorithm());
#ifdef PWB_MAPPING_HAS_RING_OPS
    algorithms.push_back(new ClipToRingAlgorithm());
    algorithms.push_back(new RepairRingAlgorithm());
#endif
    return algorithms;
}

}  // namespace pwb::qgis_processing
