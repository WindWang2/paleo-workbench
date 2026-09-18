#include <pwb/prediction/integration_seams.hpp>

#include <utility>

namespace pwb::prediction {

Json MapLayerDescriptor::to_json() const {
    Json out = Json::object();
    out["name"] = name;
    out["kind"] = kind;
    out["uri"] = uri;
    out["crs"] = crs;
    out["classes"] = classes;
    out["class_names"] = class_names;
    out["style_hints"] = style_hints;
    return out;
}

std::vector<MapLayerDescriptor> prediction_map_layers(
    const Json& output) {
    std::vector<MapLayerDescriptor> layers;
    if (!output.is_object()) return layers;
    const std::string crs = output.value("crs", std::string());
    const int classes = output.value("classes", 0);
    const Json class_names =
        output.contains("class_names") ? output["class_names"] : Json::array();
    const std::string classmap_path =
        output.value("classmap_path", std::string());
    const std::string probmap_path =
        output.value("probmap_path", std::string());
    if (!classmap_path.empty()) {
        MapLayerDescriptor classmap;
        classmap.name = "facies class map";
        classmap.kind = "classmap";
        classmap.uri = classmap_path;
        classmap.crs = crs;
        classmap.classes = classes;
        classmap.class_names = class_names;
        classmap.style_hints["palette"] = "facies";
        classmap.style_hints["renderer"] = "categorical";
        classmap.style_hints["nodata_value"] = 255;
        layers.push_back(std::move(classmap));
    }
    if (!probmap_path.empty()) {
        MapLayerDescriptor probmap;
        probmap.name = "facies probability map";
        probmap.kind = "probmap";
        probmap.uri = probmap_path;
        probmap.crs = crs;
        probmap.classes = classes;
        probmap.class_names = class_names;
        probmap.style_hints["palette"] = "confidence";
        probmap.style_hints["renderer"] = "continuous";
        probmap.style_hints["range"] = Json::array({0.0, 1.0});
        layers.push_back(std::move(probmap));
    }
    return layers;
}

Json PredictionOutputVersion::to_json() const {
    Json out = Json::object();
    out["kind"] = kind;
    out["asset_name"] = asset_name;
    out["stage"] = stage;
    out["outputs"] = outputs;
    out["provenance"] = provenance;
    out["summary"] = summary;
    out["map_layers"] = map_layers;
    return out;
}

PredictionOutputVersion build_prediction_output_version(
    const std::string& asset_name, const Json& output_descriptor,
    const Json& provenance, const Json& summary) {
    PredictionOutputVersion version;
    version.asset_name = asset_name;
    version.outputs = output_descriptor;
    version.provenance = provenance;
    version.summary = summary;
    Json layers = Json::array();
    for (const MapLayerDescriptor& layer :
         prediction_map_layers(output_descriptor)) {
        layers.push_back(layer.to_json());
    }
    version.map_layers = std::move(layers);
    return version;
}

void notify_prediction_sink(const Json& result_descriptor,
                            IPredictionTaskSink* sink) {
    if (sink == nullptr) return;
    const std::string status =
        result_descriptor.value("status", std::string("failed"));
    if (status == "succeeded" || status == "cancelled") {
        sink->on_finished(result_descriptor);
    } else if (status == "failed") {
        sink->on_failed(result_descriptor);
    } else {
        sink->on_progress(result_descriptor);
    }
}

}  // namespace pwb::prediction
