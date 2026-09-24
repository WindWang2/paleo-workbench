#include <pwb/qgis_processing/grid_io.hpp>

#include <QVariant>

#include <qgscurve.h>
#include <qgscurvepolygon.h>
#include <qgsfeature.h>
#include <qgsfeatureiterator.h>
#include <qgsfeaturesink.h>
#include <qgsfeaturesource.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgspointxy.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingutils.h>
#include <qgsrasterblock.h>
#include <qgsrasterdataprovider.h>
#include <qgsrasterfilewriter.h>
#include <qgsrasterlayer.h>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::qgis_processing {

namespace {

using pwb::mapping::Point;

[[nodiscard]] Point to_point(const QgsPointXY& p) { return Point{p.x(), p.y()}; }

// Iterates multipart/SinglePart line geometries into flat polylines.
[[nodiscard]] std::vector<std::vector<Point>> geometry_polylines(const QgsGeometry& geometry) {
    std::vector<std::vector<Point>> out;
    for (auto it = geometry.const_parts_begin(); it != geometry.const_parts_end(); ++it) {
        const QgsCurve* curve = dynamic_cast<const QgsCurve*>(*it);
        if (curve == nullptr) continue;
        QgsPointSequence sequence;
        curve->points(sequence);
        std::vector<Point> line;
        line.reserve(sequence.size());
        for (const QgsPoint& p : sequence) line.push_back(Point{p.x(), p.y()});
        if (line.size() >= 2) out.push_back(std::move(line));
    }
    return out;
}

[[nodiscard]] std::vector<std::vector<Point>> ring_rings(const QgsCurvePolygon* polygon,
                                                         bool exterior) {
    std::vector<std::vector<Point>> out;
    if (polygon == nullptr) return out;
    auto convert = [](const QgsCurve* curve) {
        std::vector<Point> ring;
        if (curve == nullptr) return ring;
        QgsPointSequence sequence;
        curve->points(sequence);
        ring.reserve(sequence.size());
        for (const QgsPoint& p : sequence) ring.push_back(Point{p.x(), p.y()});
        return ring;
    };
    if (exterior) {
        auto ring = convert(polygon->exteriorRing());
        if (ring.size() >= 3) out.push_back(std::move(ring));
    } else {
        for (int i = 0; i < polygon->numInteriorRings(); ++i) {
            auto ring = convert(polygon->interiorRing(i));
            if (ring.size() >= 3) out.push_back(std::move(ring));
        }
    }
    return out;
}

// Reads an attribute by case-insensitive field name; invalid QVariant when
// the field is absent (callers treat absent as "keep kernel default").
[[nodiscard]] QVariant attribute(const QgsFeature& feature, const QgsFields& fields,
                                 const QString& name) {
    const int index = fields.indexOf(name);
    if (index < 0) return QVariant();
    return feature.attribute(index);
}

}  // namespace

std::vector<pwb::mapping::SamplePoint> read_sample_points(
    QgsProcessingFeatureSource* source, const QString& x_field,
    const QString& y_field, const QString& value_field,
    QgsProcessingFeedback* feedback, QString& error) {
    std::vector<pwb::mapping::SamplePoint> points;
    if (source == nullptr) {
        error = QStringLiteral("input point layer is missing");
        return points;
    }
    const QgsFields fields = source->fields();
    const int x_index = fields.indexOf(x_field);
    const int y_index = fields.indexOf(y_field);
    const int value_index = fields.indexOf(value_field);
    if (x_index < 0 || y_index < 0 || value_index < 0) {
        error = QStringLiteral("point layer must provide fields '%1', '%2' and '%3'")
                    .arg(x_field, y_field, value_field);
        return points;
    }
    long long total = source->featureCount();
    if (total <= 0) total = 1;
    long long seen = 0;
    QgsFeature feature;
    QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
    while (iterator.nextFeature(feature)) {
        const QVariant x_value = feature.attribute(x_index);
        const QVariant y_value = feature.attribute(y_index);
        const QVariant v_value = feature.attribute(value_index);
        bool x_ok = false, y_ok = false, v_ok = false;
        const double x = x_value.toDouble(&x_ok);
        const double y = y_value.toDouble(&y_ok);
        const double value = v_value.toDouble(&v_ok);
        if (x_ok && y_ok && v_ok && std::isfinite(x) && std::isfinite(y) &&
            std::isfinite(value)) {
            pwb::mapping::SamplePoint point;
            point.x = x;
            point.y = y;
            point.value = value;
            const QVariant qc = attribute(feature, fields, QStringLiteral("qc_flag"));
            if (qc.isValid() && qc.canConvert<QString>()) {
                point.qc_flag = qc.toString().toStdString();
            }
            points.push_back(std::move(point));
        }
        ++seen;
        if ((seen & 0xFF) == 0) {
            if (feedback != nullptr) {
                feedback->setProgress(100.0 * static_cast<double>(seen) /
                                      static_cast<double>(total));
                if (feedback->isCanceled()) break;
            }
        }
    }
    return points;
}

std::vector<pwb::mapping::constrained_idw::BarrierLine> read_barrier_lines(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error) {
    std::vector<pwb::mapping::constrained_idw::BarrierLine> barriers;
    if (source == nullptr) return barriers;  // optional input
    const QgsFields fields = source->fields();
    const long long total = std::max<long long>(source->featureCount(), 1);
    long long seen = 0;
    QgsFeature feature;
    QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
    while (iterator.nextFeature(feature)) {
        for (std::vector<Point>& line : geometry_polylines(feature.geometry())) {
            pwb::mapping::constrained_idw::BarrierLine barrier;
            const QVariant id = attribute(feature, fields, QStringLiteral("line_id"));
            barrier.line_id = id.isValid()
                                  ? id.toString().toStdString()
                                  : ("barrier_" + std::to_string(barriers.size()));
            barrier.points = std::move(line);
            const QVariant active = attribute(feature, fields, QStringLiteral("active"));
            if (active.isValid() && active.canConvert<bool>()) {
                barrier.active = active.toBool();
            }
            const QVariant mode = attribute(feature, fields, QStringLiteral("block_mode"));
            if (mode.isValid() && mode.canConvert<QString>()) {
                barrier.block_mode = mode.toString().toStdString();
            }
            const QVariant priority =
                attribute(feature, fields, QStringLiteral("priority"));
            if (priority.isValid() && priority.canConvert<int>()) {
                barrier.priority = priority.toInt();
            }
            barriers.push_back(std::move(barrier));
        }
        ++seen;
        if (feedback != nullptr && (seen & 0xF) == 0) {
            feedback->setProgress(100.0 * static_cast<double>(seen) /
                                  static_cast<double>(total));
        }
    }
    return barriers;
}

std::vector<pwb::mapping::constrained_idw::DirectionLine> read_direction_lines(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error) {
    std::vector<pwb::mapping::constrained_idw::DirectionLine> directions;
    if (source == nullptr) return directions;
    const QgsFields fields = source->fields();
    const long long total = std::max<long long>(source->featureCount(), 1);
    long long seen = 0;
    QgsFeature feature;
    auto number_override = [&fields, &feature](const char* name, double& target) {
        const QVariant value =
            attribute(feature, fields, QString::fromLatin1(name));
        if (value.isValid() && value.canConvert<double>()) target = value.toDouble();
    };
    QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
    while (iterator.nextFeature(feature)) {
        for (std::vector<Point>& line : geometry_polylines(feature.geometry())) {
            pwb::mapping::constrained_idw::DirectionLine direction;
            const QVariant id = attribute(feature, fields, QStringLiteral("line_id"));
            direction.line_id = id.isValid()
                                    ? id.toString().toStdString()
                                    : ("direction_" + std::to_string(directions.size()));
            direction.points = std::move(line);
            const QVariant active = attribute(feature, fields, QStringLiteral("active"));
            if (active.isValid() && active.canConvert<bool>()) {
                direction.active = active.toBool();
            }
            number_override("ratio", direction.ratio);
            number_override("influence_radius", direction.influence_radius);
            number_override("core_radius", direction.core_radius);
            number_override("transition", direction.transition);
            const QVariant zone = attribute(feature, fields, QStringLiteral("zone_id"));
            if (zone.isValid() && zone.canConvert<QString>()) {
                direction.zone_id = zone.toString().toStdString();
            }
            const QVariant extend =
                attribute(feature, fields, QStringLiteral("extend_mode"));
            if (extend.isValid() && extend.canConvert<QString>()) {
                direction.extend_mode = extend.toString().toStdString();
            }
            const QVariant priority =
                attribute(feature, fields, QStringLiteral("priority"));
            if (priority.isValid() && priority.canConvert<int>()) {
                direction.priority = priority.toInt();
            }
            directions.push_back(std::move(direction));
        }
        ++seen;
        if (feedback != nullptr && (seen & 0xF) == 0) {
            feedback->setProgress(100.0 * static_cast<double>(seen) /
                                  static_cast<double>(total));
        }
    }
    return directions;
}

pwb::mapping::constrained_idw::BoundaryPolygon read_boundary_polygon(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error) {
    pwb::mapping::constrained_idw::BoundaryPolygon boundary;
    if (source == nullptr) return boundary;
    QgsFeature feature;
    QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
    while (iterator.nextFeature(feature)) {
        const QgsGeometry geometry = feature.geometry();
        for (auto it = geometry.const_parts_begin(); it != geometry.const_parts_end();
             ++it) {
            if (const QgsCurvePolygon* polygon = dynamic_cast<const QgsCurvePolygon*>(*it)) {
                for (std::vector<Point>& ring : ring_rings(polygon, true)) {
                    boundary.exterior = std::move(ring);
                }
                for (std::vector<Point>& ring : ring_rings(polygon, false)) {
                    boundary.holes.push_back(std::move(ring));
                }
            }
        }
        if (!boundary.exterior.empty()) break;  // first polygon wins
    }
    if (boundary.exterior.empty()) {
        error = QStringLiteral("boundary layer contains no polygon geometry");
    }
    return boundary;
}

GridBand read_raster_grid(QgsRasterLayer* layer, int band, QgsProcessingFeedback* feedback,
                          QString& error) {
    GridBand result;
    if (layer == nullptr || layer->dataProvider() == nullptr) {
        error = QStringLiteral("input raster layer is missing");
        return result;
    }
    QgsRasterDataProvider* provider = layer->dataProvider();
    if (band < 1 || band > provider->bandCount()) {
        error = QStringLiteral("band %1 out of range (layer has %2 band(s))")
                    .arg(band)
                    .arg(provider->bandCount());
        return result;
    }
    const int width = static_cast<int>(provider->xSize());
    const int height = static_cast<int>(provider->ySize());
    if (width <= 0 || height <= 0) {
        error = QStringLiteral("input raster has invalid dimensions");
        return result;
    }
    const QgsRectangle extent = layer->extent();
    std::unique_ptr<QgsRasterBlock> block(
        provider->block(band, extent, width, height));
    if (block == nullptr || !block->isValid()) {
        error = QStringLiteral("failed to read raster block for band %1").arg(band);
        return result;
    }
    pwb::mapping::Grid& grid = result.grid;
    grid.w = width;
    grid.h = height;
    grid.grid_x.reserve(static_cast<size_t>(width));
    grid.grid_y.reserve(static_cast<size_t>(height));
    grid.grid_z.resize(static_cast<size_t>(width) * static_cast<size_t>(height));
    const double dx = width > 1 ? extent.width() / static_cast<double>(width) : 1.0;
    const double dy = height > 1 ? extent.height() / static_cast<double>(height) : 1.0;
    const double x0 = extent.xMinimum() + 0.5 * dx;
    // grid_y ascending: raster row 0 is the northern edge, so the axis is
    // built from the southern edge upward (r=0 is the southernmost row,
    // matching the z row flip below).
    const double y0 = extent.yMinimum() + 0.5 * dy;
    for (int c = 0; c < width; ++c) {
        grid.grid_x.push_back(x0 + dx * static_cast<double>(c));
    }
    for (int r = 0; r < height; ++r) {
        grid.grid_y.push_back(y0 + dy * static_cast<double>(r));
    }
    const double no_data = provider->sourceNoDataValue(band);
    for (int r = 0; r < height; ++r) {
        const int source_row = height - 1 - r;  // flip to ascending y
        for (int c = 0; c < width; ++c) {
            const double value = block->value(source_row, c);
            const bool is_no_data =
                block->isNoData(source_row, c) ||
                (!std::isnan(no_data) && value == no_data) || !std::isfinite(value);
            grid.grid_z[static_cast<size_t>(r) * static_cast<size_t>(width) +
                        static_cast<size_t>(c)] =
                is_no_data ? std::numeric_limits<double>::quiet_NaN() : value;
        }
    }
    result.extent = extent;
    result.crs = layer->crs();
    return result;
}

bool write_factor_grid_raster(const pwb::mapping::FactorGrid& grid,
                              const QgsCoordinateReferenceSystem& crs,
                              const QString& output_path, bool include_variance,
                              QString& error) {
    const int width = static_cast<int>(grid.grid_x.size());
    const int height = static_cast<int>(grid.grid_y.size());
    if (width <= 0 || height <= 0 ||
        grid.grid_z.size() != static_cast<size_t>(width) * static_cast<size_t>(height)) {
        error = QStringLiteral("grid has invalid shape");
        return false;
    }
    if (include_variance &&
        grid.variance_grid.size() != grid.grid_z.size()) {
        include_variance = false;  // IDW: no variance, single band is honest
    }
    const double dx = width > 1 ? grid.grid_x[1] - grid.grid_x[0] : 1.0;
    const double dy = height > 1 ? grid.grid_y[1] - grid.grid_y[0] : 1.0;
    const double x_min = grid.grid_x.front() - 0.5 * std::abs(dx);
    const double x_max = grid.grid_x.back() + 0.5 * std::abs(dx);
    const double y_min = grid.grid_y.front() - 0.5 * std::abs(dy);
    const double y_max = grid.grid_y.back() + 0.5 * std::abs(dy);
    const QgsRectangle extent(x_min, y_min, x_max, y_max);
    const int bands = include_variance ? 2 : 1;

    QgsRasterFileWriter writer(output_path);
    writer.setOutputFormat(QStringLiteral("GTiff"));
    QgsRasterDataProvider* provider =
        bands == 2
            ? writer.createMultiBandRaster(Qgis::DataType::Float32, width, height,
                                           extent, crs, 2)
            : writer.createOneBandRaster(Qgis::DataType::Float32, width, height,
                                         extent, crs);
    if (provider == nullptr) {
        error = QStringLiteral("failed to create raster output %1").arg(output_path);
        return false;
    }
    std::unique_ptr<QgsRasterDataProvider> provider_guard(provider);
    const double nan_no_data = std::numeric_limits<double>::quiet_NaN();
    provider->setNoDataValue(1, nan_no_data);
    if (bands == 2) provider->setNoDataValue(2, nan_no_data);  // kriging variance
    auto write_band = [&](int band, const std::vector<float>& values) {
        QgsRasterBlock block(Qgis::DataType::Float32, width, height);
        for (int r = 0; r < height; ++r) {
            const int target_row = height - 1 - r;  // ascending y -> north-up
            for (int c = 0; c < width; ++c) {
                const double value =
                    values[static_cast<size_t>(r) * static_cast<size_t>(width) +
                           static_cast<size_t>(c)];
                block.setValue(target_row, c, value);
            }
        }
        if (!provider->writeBlock(&block, band)) {
            error = QStringLiteral("failed to write band %1 of %2").arg(band).arg(output_path);
            return false;
        }
        return true;
    };
    if (!write_band(1, grid.grid_z)) return false;
    if (include_variance && !write_band(2, grid.variance_grid)) return false;
    return true;
}

bool add_polyline_features(QgsFeatureSink* sink, const QgsFields& fields,
                           const std::vector<pwb::mapping::Polyline>& polylines,
                           double level_value, int level_field_index, QString& error) {
    if (sink == nullptr) {
        error = QStringLiteral("output sink is missing");
        return false;
    }
    for (const pwb::mapping::Polyline& polyline : polylines) {
        if (polyline.size() < 2) continue;
        QgsFeature feature(fields);
        QVector<QgsPointXY> points;
        points.reserve(static_cast<int>(polyline.size()));
        for (const Point& p : polyline) points.append(QgsPointXY(p[0], p[1]));
        feature.setGeometry(QgsGeometry::fromPolylineXY(points));
        if (level_field_index >= 0) {
            feature.setAttribute(level_field_index, QVariant(level_value));
        }
        if (!sink->addFeature(feature, QgsFeatureSink::FastInsert)) {
            error = QStringLiteral("failed to add contour feature");
            return false;
        }
    }
    return true;
}

QStringList source_field_names(QgsProcessingFeatureSource* source) {
    QStringList names;
    if (source == nullptr) return names;
    const QgsFields fields = source->fields();
    for (const QgsField& field : fields) names << field.name();
    return names;
}

}  // namespace pwb::qgis_processing
