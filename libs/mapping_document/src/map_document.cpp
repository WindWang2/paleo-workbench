#include <pwb/mapping_document/map_document.hpp>

#include <algorithm>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "python_compat.hpp"

namespace pwb::mapping_document {

namespace {

using detail::collect_extras;
using detail::py_int_json;
using detail::py_str;
using detail::py_truthy;

const Json* known_key(const Json& payload, const char* key) {
    return payload.contains(key) ? &payload.at(key) : nullptr;
}

std::string str_field(const Json& payload, const char* key,
                      const std::string& fallback) {
    // Read contract (D-03): a present key is used verbatim (non-strings go
    // through Python str()), an absent key fills the dataclass default.
    // No `or`-falsy collapse here — Python's to_dict always writes these
    // keys, and "" is a legitimate stored value (crs="" everywhere).
    const Json* value = known_key(payload, key);
    if (value == nullptr || value->is_null()) return fallback;
    return py_str(*value);
}

double number_field(const Json& payload, const char* key, double fallback) {
    const Json* value = known_key(payload, key);
    if (value == nullptr || value->is_null()) return fallback;
    return detail::py_float(*value);
}

long long integer_field(const Json& payload, const char* key, long long fallback) {
    const Json* value = known_key(payload, key);
    if (value == nullptr || value->is_null()) return fallback;
    return detail::py_int(*value);
}

bool bool_field(const Json& payload, const char* key, bool fallback) {
    const Json* value = known_key(payload, key);
    if (value == nullptr) return fallback;
    return py_truthy(*value);
}

std::array<double, 4> extent_field(const Json& payload) {
    const Json* value = known_key(payload, "extent");
    if (value == nullptr || value->is_null()) return kSentinelExtent;
    if (!value->is_array() || value->size() != 4) {
        throw std::invalid_argument("map_document: extent must be a 4-element list");
    }
    return {detail::py_float((*value)[0]), detail::py_float((*value)[1]),
            detail::py_float((*value)[2]), detail::py_float((*value)[3])};
}

Json object_field(const Json& payload, const char* key) {
    const Json* value = known_key(payload, key);
    if (value == nullptr || !value->is_object()) return Json::object();
    return *value;
}

const std::vector<const char*> kLayerKeys{
    "id", "name", "layer_type", "extent", "crs", "data_revision",
    "style_revision", "visible", "opacity", "scale_range", "style",
    "metadata", "source_version_id"};

const std::vector<const char*> kDocumentKeys{
    "id", "title", "crs", "extent", "layers", "metadata", "active_layer_id"};

// Vector-family routing (decision D-05): Python's to_dict key set is decided
// by the *class* (VectorMapLayer subclasses always write `features`;
// AnnotationMapLayer adds `annotations`), but a JSON payload only carries the
// layer_type string — this table is the inverse of that contract, seeded with
// the routing vocabulary of MapDocument.from_snapshot.
bool is_vector_family(const std::string& layer_type) {
    return layer_type == "vector" || layer_type == "contour"
        || layer_type == "well_point" || layer_type == "polygon"
        || layer_type == "annotation" || layer_type == "facies"
        || layer_type == "well";
}

}  // namespace

MapLayer parse_layer(const Json& payload) {
    if (!payload.is_object()) {
        throw std::invalid_argument("map_document: layer payload must be an object");
    }
    MapLayer layer;
    layer.id = str_field(payload, "id", "");
    layer.name = str_field(payload, "name", "Untitled Layer");
    layer.layer_type = str_field(payload, "layer_type", "vector");
    layer.extent = extent_field(payload);
    layer.crs = str_field(payload, "crs", "");
    layer.data_revision = integer_field(payload, "data_revision", 1);
    layer.style_revision = integer_field(payload, "style_revision", 1);
    layer.visible = bool_field(payload, "visible", true);
    layer.opacity = number_field(payload, "opacity", 1.0);
    const Json* scale = known_key(payload, "scale_range");
    if (scale != nullptr && !scale->is_null()) {
        if (!scale->is_array() || scale->size() != 2) {
            throw std::invalid_argument(
                "map_document: scale_range must be null or a 2-element list");
        }
        layer.has_scale_range = true;
        layer.scale_range_min = detail::py_float((*scale)[0]);
        layer.scale_range_max = detail::py_float((*scale)[1]);
    }
    layer.style = object_field(payload, "style");
    layer.metadata = object_field(payload, "metadata");
    layer.source_version_id = str_field(payload, "source_version_id", "");

    const bool vector_family = is_vector_family(layer.layer_type);
    const Json* features = known_key(payload, "features");
    if (vector_family) {
        layer.features = features != nullptr ? *features : Json::array();
    }
    const Json* annotations = known_key(payload, "annotations");
    if (layer.layer_type == "annotation") {
        layer.annotations = annotations != nullptr ? *annotations : Json::array();
    }

    detail::collect_extras(payload, kLayerKeys, layer.extras);
    // Family-known payload keys must not leak into extras.
    if (vector_family) layer.extras.erase("features");
    if (layer.layer_type == "annotation") layer.extras.erase("annotations");
    return layer;
}

Json dump_layer(const MapLayer& layer) {
    Json out;
    out["id"] = layer.id;
    out["name"] = layer.name;
    out["layer_type"] = layer.layer_type;
    Json extent = Json::array();
    for (double v : layer.extent) extent.push_back(v);
    out["extent"] = extent;
    out["crs"] = layer.crs;
    out["data_revision"] = py_int_json(layer.data_revision);
    out["style_revision"] = py_int_json(layer.style_revision);
    out["visible"] = layer.visible;
    out["opacity"] = layer.opacity;
    if (layer.has_scale_range) {
        Json scale = Json::array();
        scale.push_back(layer.scale_range_min);
        scale.push_back(layer.scale_range_max);
        out["scale_range"] = scale;
    } else {
        out["scale_range"] = nullptr;
    }
    out["style"] = layer.style.is_object() ? layer.style : Json::object();
    out["metadata"] = layer.metadata.is_object() ? layer.metadata : Json::object();
    out["source_version_id"] = layer.source_version_id;
    if (is_vector_family(layer.layer_type)) out["features"] = layer.features;
    if (layer.layer_type == "annotation") out["annotations"] = layer.annotations;
    for (auto it = layer.extras.begin(); it != layer.extras.end(); ++it) {
        out[it.key()] = it.value();
    }
    return out;
}

MapDocument parse_map_document(const Json& payload) {
    if (!payload.is_object()) {
        throw std::invalid_argument("map_document: document payload must be an object");
    }
    MapDocument doc;
    doc.id = str_field(payload, "id", "");
    doc.title = str_field(payload, "title", "Paleogeographic Map");
    doc.crs = str_field(payload, "crs", "EPSG:4326");
    doc.extent = extent_field(payload);
    const Json* layers = known_key(payload, "layers");
    if (layers != nullptr && !layers->is_null()) {
        if (!layers->is_array()) {
            throw std::invalid_argument("map_document: layers must be a list");
        }
        for (const auto& entry : *layers) {
            doc.layers.push_back(parse_layer(entry));
        }
    }
    doc.metadata = object_field(payload, "metadata");
    const Json* active = known_key(payload, "active_layer_id");
    if (active != nullptr && !active->is_null()) {
        doc.has_active_layer = true;
        doc.active_layer_id = py_str(*active);
    }
    detail::collect_extras(payload, kDocumentKeys, doc.extras);
    return doc;
}

Json dump_map_document(const MapDocument& doc) {
    Json out;
    out["id"] = doc.id;
    out["title"] = doc.title;
    out["crs"] = doc.crs;
    Json extent = Json::array();
    for (double v : doc.extent) extent.push_back(v);
    out["extent"] = extent;
    Json layers = Json::array();
    for (const MapLayer& layer : doc.layers) layers.push_back(dump_layer(layer));
    out["layers"] = layers;
    out["metadata"] = doc.metadata.is_object() ? doc.metadata : Json::object();
    out["active_layer_id"] = nullptr;
    if (doc.has_active_layer) out["active_layer_id"] = doc.active_layer_id;
    for (auto it = doc.extras.begin(); it != doc.extras.end(); ++it) {
        out[it.key()] = it.value();
    }
    return out;
}

MapLayer* find_layer(MapDocument& doc, const std::string& layer_id) {
    for (MapLayer& layer : doc.layers) {
        if (layer.id == layer_id) return &layer;
    }
    return nullptr;
}

void add_layer(MapDocument& doc, MapLayer layer,
               std::optional<std::size_t> position) {
    const std::string added_id = layer.id;
    if (position.has_value() && *position <= doc.layers.size()) {
        doc.layers.insert(doc.layers.begin() + static_cast<std::ptrdiff_t>(*position),
                          std::move(layer));
    } else {
        doc.layers.push_back(std::move(layer));
    }
    // Python: `if not self.active_layer_id` — both None and "" count as unset,
    // and the new layer's id becomes active.
    if (!doc.has_active_layer || doc.active_layer_id.empty()) {
        doc.has_active_layer = true;
        doc.active_layer_id = added_id;
    }
    recompute_extent(doc);
}

std::optional<MapLayer> remove_layer(MapDocument& doc,
                                     const std::string& layer_id) {
    for (auto it = doc.layers.begin(); it != doc.layers.end(); ++it) {
        if (it->id != layer_id) continue;
        MapLayer removed = std::move(*it);
        doc.layers.erase(it);
        if (doc.has_active_layer && doc.active_layer_id == layer_id) {
            if (!doc.layers.empty()) {
                doc.active_layer_id = doc.layers.front().id;
            } else {
                doc.has_active_layer = false;
                doc.active_layer_id.clear();
            }
        }
        recompute_extent(doc);
        return removed;
    }
    return std::nullopt;
}

void reorder_layers(MapDocument& doc,
                    const std::vector<std::string>& layer_ids) {
    // Python builds {lyr.id: lyr} — duplicate layer ids collapse to the LAST
    // occurrence — pops in request order (a second request for the same id is
    // a no-op, not an error), then appends the surviving dict values in
    // first-occurrence id order.
    std::unordered_map<std::string, std::size_t> last_of_id;
    for (std::size_t i = 0; i < doc.layers.size(); ++i) {
        last_of_id[doc.layers[i].id] = i;
    }
    std::vector<MapLayer> reordered;
    reordered.reserve(doc.layers.size());
    std::vector<bool> taken(doc.layers.size(), false);
    std::unordered_set<std::string> requested;
    for (const std::string& id : layer_ids) {
        if (!requested.insert(id).second) continue;
        auto found = last_of_id.find(id);
        if (found == last_of_id.end()) continue;
        taken[found->second] = true;
        reordered.push_back(std::move(doc.layers[found->second]));
    }
    std::unordered_set<std::string> emitted;
    for (std::size_t i = 0; i < doc.layers.size(); ++i) {
        const std::string& id = doc.layers[i].id;
        if (taken[i] || emitted.count(id) != 0) continue;
        if (last_of_id[id] != i) continue;  // duplicates: dict keeps the last
        emitted.insert(id);
        reordered.push_back(std::move(doc.layers[i]));
    }
    doc.layers = std::move(reordered);
}

std::array<double, 4> recompute_extent(MapDocument& doc) {
    bool any = false;
    double xmin = 0.0, ymin = 0.0, xmax = 0.0, ymax = 0.0;
    for (const MapLayer& layer : doc.layers) {
        if (!layer.visible) continue;
        if (layer.extent == kSentinelExtent) continue;
        if (!any) {
            xmin = layer.extent[0];
            ymin = layer.extent[1];
            xmax = layer.extent[2];
            ymax = layer.extent[3];
            any = true;
            continue;
        }
        xmin = std::min(xmin, layer.extent[0]);
        ymin = std::min(ymin, layer.extent[1]);
        xmax = std::max(xmax, layer.extent[2]);
        ymax = std::max(ymax, layer.extent[3]);
    }
    if (any) doc.extent = {xmin, ymin, xmax, ymax};
    return doc.extent;
}

Json input_version_ids(const MapDocument& doc) {
    // layers.py contract: the metadata["input_version_ids"] list seeds the
    // result VERBATIM (entries kept as-is, internal duplicates included);
    // only layer source_version_ids are appended first-wins ("" skipped).
    // Non-array metadata values are outside the product contract; the kernel
    // reports an empty list for them (decision D-20).
    Json ids = Json::array();
    auto contains = [&ids](const Json& value) {
        for (const auto& entry : ids) {
            if (entry == value) return true;
        }
        return false;
    };
    if (doc.metadata.is_object()
        && doc.metadata.contains("input_version_ids")) {
        const Json& declared = doc.metadata.at("input_version_ids");
        if (declared.is_array()) ids = declared;
    }
    for (const MapLayer& layer : doc.layers) {
        if (layer.source_version_id.empty()) continue;
        const Json value(layer.source_version_id);
        if (!contains(value)) ids.push_back(value);
    }
    return ids;
}

}  // namespace pwb::mapping_document
