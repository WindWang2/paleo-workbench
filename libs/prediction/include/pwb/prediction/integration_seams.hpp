// Integration seams for the prediction runtime.
//
// This branch does NOT implement the Catalog's persistence, the Workflow
// scheduler or the QGIS UI. It returns explicit descriptors those branches
// seam into:
//   - PredictionOutputVersion — what a catalog result asset should record
//     (outputs, provenance, summary, version metadata);
//   - MapLayerDescriptor — class/probability layers a map publication can
//     compile into QGIS layers (no QGIS types here);
//   - IPredictionTaskSink — the callback contract a workflow task wraps
//     around PredictionTaskRuntime.

#pragma once

#include <array>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/prediction_pipeline.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

inline constexpr const char* kPredictionOutputVersionKind =
    "pwb-prediction-result";

struct MapLayerDescriptor {
    std::string name;
    std::string kind;  // "classmap" | "probmap"
    std::string uri;
    std::string crs;
    int classes = 0;
    Json class_names = Json::array();
    // Georeferencing for a QGIS/GDAL consumer of the headerless raw raster:
    // shape, geotransform (GDAL order), dtype and byte order let a map
    // publication build a VRT without re-reading the descriptor.
    Tile3 shape{};
    std::array<double, 6> geotransform{};
    bool has_geotransform = false;
    std::string dtype;
    std::string byte_order = "little";
    Json style_hints = Json::object();

    Json to_json() const;
};

// Class map + (when persisted) probability map layers, from a
// PredictionOutputDescriptor::to_json() object. Empty paths produce no
// descriptor: an unwritten artifact is never advertised.
//
// The artifacts are headerless raw rasters; the descriptor carries shape,
// geotransform, dtype and byte order so a map publication can build a
// GDAL/QGIS-readable VRT. Note that the frozen CONV-21
// spatial_result::is_map_compilable() predicate only accepts
// VECTOR_POLYGONS — a CLASSIFIED_RASTER is published through these layer
// descriptors, not through that predicate.
std::vector<MapLayerDescriptor> prediction_map_layers(
    const Json& output_descriptor);

// Catalog/workspace seam: the version record a derived prediction result
// wants persisted. `asset_name` is the catalog-side name (e.g.
// "<input>-facies-prediction").
struct PredictionOutputVersion {
    std::string kind = kPredictionOutputVersionKind;
    std::string asset_name;
    std::string stage = "derived";
    Json outputs = Json::object();
    Json provenance = Json::object();
    Json summary = Json::object();
    Json map_layers = Json::array();

    Json to_json() const;
};

PredictionOutputVersion build_prediction_output_version(
    const std::string& asset_name, const Json& output_descriptor,
    const Json& provenance, const Json& summary);

// Workflow task callback seam. Implemented by the Workflow branch; the
// prediction runtime only invokes it. All payloads are the same JSON
// descriptors PredictionTaskRuntime produces, so no shared ABI is needed.
class IPredictionTaskSink {
public:
    virtual ~IPredictionTaskSink() = default;
    virtual void on_started(const Json& task_descriptor) = 0;
    virtual void on_progress(const Json& progress) = 0;
    virtual void on_finished(const Json& result_descriptor) = 0;
    virtual void on_failed(const Json& failure) = 0;
};

// Dispatches one terminal/result descriptor to the right callback.
void notify_prediction_sink(const Json& result_descriptor,
                            IPredictionTaskSink* sink);

}  // namespace pwb::prediction
