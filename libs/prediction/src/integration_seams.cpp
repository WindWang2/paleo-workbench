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
    out["shape"] = shape;
    out["geotransform"] = geotransform;
    out["has_geotransform"] = has_geotransform;
    out["dtype"] = dtype;
    out["byte_order"] = byte_order;
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
    Tile3 shape{};
    if (output.contains("shape") && output["shape"].is_array()
        && output["shape"].size() == 3) {
        shape = Tile3{output["shape"][0].get<int>(),
                      output["shape"][1].get<int>(),
                      output["shape"][2].get<int>()};
    }
    std::array<double, 6> geotransform{};
    bool has_geotransform = false;
    if (output.contains("geotransform") && output["geotransform"].is_array()
        && output["geotransform"].size() == 6) {
        for (std::size_t i = 0; i < 6; ++i) {
            geotransform[i] = output["geotransform"][i].get<double>();
        }
        has_geotransform = output.value("has_geotransform", true);
    }
    const auto fill = [&](MapLayerDescriptor* layer, const char* name,
                          const char* kind, const std::string& uri,
                          const char* dtype) {
        layer->name = name;
        layer->kind = kind;
        layer->uri = uri;
        layer->crs = crs;
        layer->classes = classes;
        layer->class_names = class_names;
        layer->shape = shape;
        layer->geotransform = geotransform;
        layer->has_geotransform = has_geotransform;
        layer->dtype = dtype;
    };
    if (!classmap_path.empty()) {
        MapLayerDescriptor classmap;
        fill(&classmap, "facies class map", "classmap", classmap_path,
             "uint8");
        classmap.style_hints["palette"] = "facies";
        classmap.style_hints["renderer"] = "categorical";
        layers.push_back(std::move(classmap));
    }
    if (!probmap_path.empty()) {
        MapLayerDescriptor probmap;
        fill(&probmap, "facies probability map", "probmap", probmap_path,
             "float16");
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
