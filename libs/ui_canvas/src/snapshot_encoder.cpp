// UI-15 — Qt-free QGIS snapshot encoder.
// Python parity: mapping/map_render_backend.py _qgis_snapshot +
// _geometry_to_wkt + _is_stale_delta_error.

#include <pwb/ui_canvas/snapshot_encoder.hpp>

#include <algorithm>
#include <cctype>
#include <cstdio>

#include <pwb/cartography/qgis_adapter.hpp>

namespace pwb::ui_canvas {

namespace {

// f"{value:.17g}" parity.
std::string fmt17(double value) {
    char buf[40];
    std::snprintf(buf, sizeof(buf), "%.17g", value);
    return buf;
}

// Python point() — "" for non-sequence / non-numeric / short coords.
std::string wkt_point(const Json& value) {
    if (!value.is_array() || value.size() < 2) {
        return "";
    }
    try {
        return fmt17(value.at(0).get<double>()) + " " +
               fmt17(value.at(1).get<double>());
    } catch (...) {
        return "";
    }
}

// Python ring() — joins the non-empty point conversions.
std::string wkt_ring(const Json& values) {
    if (!values.is_array()) {
        return "";
    }
    std::string out;
    for (const Json& value : values) {
        const std::string point = wkt_point(value);
        if (point.empty()) {
            continue;
        }
        if (!out.empty()) {
            out += ", ";
        }
        out += point;
    }
    return out;
}

std::string json_string_or_empty(const Json& object, const char* key) {
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) {
        return "";
    }
    return it->get<std::string>();
}

// feature dict → {"id","wkt","attributes"} — "" wkt skips the feature
// (Python `continue` parity). Returns nullopt when skipped.
std::optional<Json> encode_feature(const Json& feature) {
    if (!feature.is_object()) {
        return std::nullopt;
    }
    const std::string feature_id = json_string_or_empty(feature, "id");
    const Json& geometry = feature.value("geometry", Json());
    const Json& properties = feature.value("properties", Json::object());
    const std::string wkt = wkt_from_geometry(geometry);
    if (wkt.empty()) {
        return std::nullopt;
    }
    Json attributes = properties.is_object() ? properties : Json::object();
    attributes["__pwb_id"] = feature_id;
    return Json{{"id", feature_id},
                {"wkt", wkt},
                {"attributes", std::move(attributes)}};
}

// One vector layer's feature list — the cache/delta block of
// _qgis_snapshot verbatim.
Json encode_vector_features(const MapLayerSnapshot& layer,
                            SnapshotEncoderState& state,
                            std::optional<Json>& delta_payload) {
    delta_payload.reset();
    const auto cached_it = state.feature_payloads.find(layer.id);
    const bool cache_hit =
        cached_it != state.feature_payloads.end() &&
        cached_it->second.first == layer.data_revision;
    if (cache_hit) {
        ++state.feature_encoding_cache_hits;
        return cached_it->second.second;
    }

    const auto& previous_entries = state.feature_entries[layer.id];
    std::map<std::string, FeatureEntry> next_entries;
    Json encoded_features = Json::array();
    Json changed_encoded = Json::array();

    for (const Json& feature : layer.features) {
        const std::string feature_id = json_string_or_empty(feature, "id");
        const Json& geometry = feature.value("geometry", Json());
        const Json& properties = feature.value("properties", Json::object());
        const auto cached_entry = previous_entries.find(feature_id);
        Json encoded;
        if (cached_entry != previous_entries.end() &&
            cached_entry->second.geometry == geometry &&
            cached_entry->second.properties == properties) {
            encoded = cached_entry->second.encoded;
            ++state.feature_payload_reuse_hits;
        } else {
            const std::optional<Json> fresh = encode_feature(feature);
            if (!fresh) {
                continue;  // empty WKT — Python `continue` parity
            }
            encoded = *fresh;
            changed_encoded.push_back(encoded);
            ++state.feature_payload_reencode_misses;
        }
        encoded_features.push_back(encoded);
        next_entries[feature_id] = FeatureEntry{geometry, properties, encoded};
    }

    Json removed_ids = Json::array();
    for (const auto& [fid, entry] : previous_entries) {
        if (next_entries.find(fid) == next_entries.end()) {
            removed_ids.push_back(fid);
        }
    }

    // #932: ship a delta only when the bridge mirror provably holds the
    // previous revision AND the delta is smaller than a full payload.
    if (cached_it != state.feature_payloads.end() &&
        state.force_full_ids.find(layer.id) == state.force_full_ids.end()) {
        const auto shipped_it = state.shipped_revisions.find(layer.id);
        const bool mirror_holds_previous =
            shipped_it != state.shipped_revisions.end() &&
            shipped_it->second == cached_it->second.first;
        const bool has_changes =
            !changed_encoded.empty() || !removed_ids.empty();
        if (mirror_holds_previous && has_changes &&
            changed_encoded.size() + removed_ids.size() <
                encoded_features.size()) {
            delta_payload = Json{
                {"base_revision", cached_it->second.first},
                {"changed_features", std::move(changed_encoded)},
                {"removed_ids", std::move(removed_ids)},
            };
            ++state.feature_delta_ships;
        }
    }

    state.feature_payloads[layer.id] = {layer.data_revision, encoded_features};
    state.feature_entries[layer.id] = std::move(next_entries);
    ++state.feature_encoding_cache_misses;
    return encoded_features;
}

Json raster_entry(const MapLayerSnapshot& layer,
                  const std::string& project_crs,
                  const std::string& source_path,
                  const std::string& raster_renderer_xml) {
    Json entry{
        {"id", layer.id},
        {"name", layer.name},
        {"crs", layer.crs.empty() ? project_crs : layer.crs},
        {"kind", "raster"},
        {"source_path", source_path},
        {"data_revision", layer.data_revision},
        {"style_revision", layer.style_revision},
        {"visible", layer.visible},
        {"opacity", layer.opacity},
        {"features", Json::array()},
    };
    if (!raster_renderer_xml.empty()) {
        entry["raster_renderer_xml"] = raster_renderer_xml;
    }
    return entry;
}

}  // namespace

std::string wkt_from_geometry(const Json& geometry) {
    if (!geometry.is_object()) {
        return "";
    }
    const std::string type = json_string_or_empty(geometry, "type");
    const Json& coordinates = geometry.value("coordinates", Json());

    if (type == "Point") {
        const std::string value = wkt_point(coordinates);
        return value.empty() ? "" : "POINT (" + value + ")";
    }
    if (type == "MultiPoint" && coordinates.is_array()) {
        std::string joined;
        for (const Json& value : coordinates) {
            const std::string point = wkt_point(value);
            if (point.empty()) {
                continue;
            }
            if (!joined.empty()) joined += ", ";
            joined += point;
        }
        return joined.empty() ? "" : "MULTIPOINT (" + joined + ")";
    }
    if (type == "LineString") {
        const std::string value = wkt_ring(coordinates);
        return value.empty() ? "" : "LINESTRING (" + value + ")";
    }
    if (type == "MultiLineString" && coordinates.is_array()) {
        std::string joined;
        for (const Json& value : coordinates) {
            const std::string ring = wkt_ring(value);
            if (ring.empty()) {
                continue;
            }
            if (!joined.empty()) joined += ", ";
            joined += "(" + ring + ")";
        }
        return joined.empty() ? "" : "MULTILINESTRING (" + joined + ")";
    }
    if (type == "Polygon" && coordinates.is_array()) {
        std::string joined;
        for (const Json& value : coordinates) {
            const std::string ring = wkt_ring(value);
            if (ring.empty()) {
                continue;
            }
            if (!joined.empty()) joined += ", ";
            joined += "(" + ring + ")";
        }
        return joined.empty() ? "" : "POLYGON (" + joined + ")";
    }
    if (type == "MultiPolygon" && coordinates.is_array()) {
        std::string joined;
        for (const Json& polygon : coordinates) {
            if (!polygon.is_array()) {
                continue;
            }
            std::string rings;
            for (const Json& value : polygon) {
                const std::string ring = wkt_ring(value);
                if (ring.empty()) {
                    continue;
                }
                if (!rings.empty()) rings += ", ";
                rings += "(" + ring + ")";
            }
            if (!rings.empty()) {
                if (!joined.empty()) joined += ", ";
                joined += "(" + rings + ")";
            }
        }
        return joined.empty() ? "" : "MULTIPOLYGON (" + joined + ")";
    }
    return "";
}

Json encode_qgis_snapshot(const MapRenderSnapshot& snapshot,
                          SnapshotEncoderState& state) {
    Json layers = Json::array();
    for (const MapLayerSnapshot& layer : snapshot.layers) {
        if (layer.layer_type == "scalar_grid") {
            // v7 §5: the DATA path ships source_path + raster_renderer_xml;
            // the RGBA mirror ships source_path only. The producer resolves
            // both (mirror caches stay a mapping-slice concern).
            if (layer.source_path.empty()) {
                throw std::runtime_error(
                    "QGIS scalar-grid rendering requires a raster mirror "
                    "cache");
            }
            layers.push_back(raster_entry(layer, snapshot.project_crs,
                                          layer.source_path,
                                          layer.raster_renderer_xml));
            continue;
        }
        if (layer.layer_type == "raster_source") {
            if (layer.source_path.empty()) {
                continue;  // Python `continue` parity — silent skip
            }
            layers.push_back(raster_entry(layer, snapshot.project_crs,
                                          layer.source_path, ""));
            continue;
        }
        if (layer.layer_type == "grid") {
            continue;
        }
        std::optional<Json> delta_payload;
        const Json features = encode_vector_features(layer, state,
                                                     delta_payload);
        // Empty host categories keep no render mirror (the memory provider
        // has no geometry URI for them) — Python `continue` parity.
        if (features.empty()) {
            continue;
        }
        Json entry{
            {"id", layer.id},
            {"name", layer.name},
            {"crs", layer.crs.empty() ? snapshot.project_crs : layer.crs},
            {"data_revision", layer.data_revision},
            {"style_revision", layer.style_revision},
            {"visible", layer.visible},
            {"opacity", layer.opacity},
            {"scale_range",
             layer.scale_range
                 ? Json::array({layer.scale_range->first,
                                layer.scale_range->second})
                 : Json()},
            {"style", pwb::cartography::flatten_qgis_style(layer.style)},
            // #932: a delta ship replaces the feature list — the bridge
            // updates the existing mirror in place (host ids ride
            // __pwb_id); a full ship re-parses every WKT.
            {"features", delta_payload ? Json::array() : features},
        };
        if (delta_payload) {
            entry["delta"] = *delta_payload;
        }
        layers.push_back(std::move(entry));
    }
    return layers;
}

void prune_encoder_state(SnapshotEncoderState& state,
                         const MapRenderSnapshot& snapshot) {
    std::set<std::string> active_vector_ids;
    for (const MapLayerSnapshot& layer : snapshot.layers) {
        if (layer.layer_type != "scalar_grid" &&
            layer.layer_type != "grid" &&
            layer.layer_type != "raster_source") {
            active_vector_ids.insert(layer.id);
        }
    }
    for (auto it = state.feature_payloads.begin();
         it != state.feature_payloads.end();) {
        if (active_vector_ids.find(it->first) == active_vector_ids.end()) {
            it = state.feature_payloads.erase(it);
        } else {
            ++it;
        }
    }
    for (auto it = state.feature_entries.begin();
         it != state.feature_entries.end();) {
        if (active_vector_ids.find(it->first) == active_vector_ids.end()) {
            it = state.feature_entries.erase(it);
        } else {
            ++it;
        }
    }
    for (auto it = state.shipped_revisions.begin();
         it != state.shipped_revisions.end();) {
        if (active_vector_ids.find(it->first) ==
            active_vector_ids.end()) {
            it = state.shipped_revisions.erase(it);
        } else {
            ++it;
        }
    }
}

bool is_stale_delta_error(const std::exception& exc) {
    std::string message = exc.what();
    std::transform(message.begin(), message.end(), message.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return message.find("stale mirror for feature delta") !=
           std::string::npos;
}

}  // namespace pwb::ui_canvas
