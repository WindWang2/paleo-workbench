#pragma once

// QGIS layer/raster <-> Paleo kernel type bridge.
//
// Reading: feature sources -> SamplePoint vectors, constraint geometry
// (barriers / directions / boundaries); raster layers -> mapping::Grid.
// Writing: FactorGrid -> single- or dual-band float32 GeoTIFF via
// QgsRasterFileWriter (public core API), feature sinks from kernel
// polylines/polygons.
//
// Axis convention: Paleo grids store ascending axis vectors as cell-center
// coordinates (numpy meshgrid parity). The raster bridge converts centers
// <-> edges on IO; a single-cell axis keeps a unit step.

#include <QString>
#include <QStringList>
#include <vector>

#include <qgscoordinatereferencesystem.h>
#include <qgsfields.h>
#include <qgsrectangle.h>

#include <pwb/mapping/constrained_idw.hpp>
#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/interpolator.hpp>

class QgsFeatureSink;
class QgsProcessingFeedback;
class QgsProcessingFeatureSource;
class QgsRasterLayer;

namespace pwb::qgis_processing {

// ---- reading: vector ------------------------------------------------------

[[nodiscard]] std::vector<pwb::mapping::SamplePoint> read_sample_points(
    QgsProcessingFeatureSource* source, const QString& x_field,
    const QString& y_field, const QString& value_field,
    QgsProcessingFeedback* feedback, QString& error);

// Line layer -> barrier geometry. Attribute overrides when present:
// "block_mode" (full_block|partial|none), "priority" (int), "active" (bool).
[[nodiscard]] std::vector<pwb::mapping::constrained_idw::BarrierLine> read_barrier_lines(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error);

// Line layer -> direction geometry. Attribute overrides when present:
// "ratio", "influence_radius", "core_radius", "transition", "zone_id",
// "extend_mode", "priority", "active".
[[nodiscard]] std::vector<pwb::mapping::constrained_idw::DirectionLine> read_direction_lines(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error);

// Polygon layer(s) -> boundary rings (first polygon's exterior + holes;
// extra layers append as additional boundaries is NOT supported by the
// kernel — the caller passes one layer).
[[nodiscard]] pwb::mapping::constrained_idw::BoundaryPolygon read_boundary_polygon(
    QgsProcessingFeatureSource* source, QgsProcessingFeedback* feedback,
    QString& error);

// ---- reading: raster ------------------------------------------------------

struct GridBand {
    pwb::mapping::Grid grid;               // ascending axes, NaN-safe values
    QgsRectangle extent;                   // edge extent in layer CRS
    QgsCoordinateReferenceSystem crs;
};

[[nodiscard]] GridBand read_raster_grid(QgsRasterLayer* layer, int band,
                                        QgsProcessingFeedback* feedback,
                                        QString& error);

// ---- writing: raster ------------------------------------------------------

// Writes grid_z (band 1) and, when non-empty and requested, variance_grid
// (band 2) as Float32 GTiff. Returns false with `error` set on failure.
[[nodiscard]] bool write_factor_grid_raster(const pwb::mapping::FactorGrid& grid,
                                            const QgsCoordinateReferenceSystem& crs,
                                            const QString& output_path,
                                            bool include_variance, QString& error);

// ---- writing: vector ------------------------------------------------------

// Adds polyline features to a sink prepared by the caller. `fields` must be
// the schema the sink was created with; the level value lands in
// `level_field_index`.
[[nodiscard]] bool add_polyline_features(QgsFeatureSink* sink, const QgsFields& fields,
                                         const std::vector<pwb::mapping::Polyline>& polylines,
                                         double level_value, int level_field_index,
                                         QString& error);

// ---- shared helpers -------------------------------------------------------

// Field names of a source (for parameter defaults / validation).
[[nodiscard]] QStringList source_field_names(QgsProcessingFeatureSource* source);

}  // namespace pwb::qgis_processing
