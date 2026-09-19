#include <pwb/seismic_viewer/view_state.hpp>

#include <fstream>
#include <utility>

#include <pwb/domain/json.hpp>

namespace pwb::seismic_viewer {
namespace {

using pwb::domain::Json;

// Typed key readers — fail closed: a missing key or a mistyped value makes
// the whole state bad_schema (a half-applied view is worse than a refusal).
bool read_string(const Json& json, const char* key, std::string& out) {
    const auto it = json.find(key);
    if (it == json.end() || !it->is_string()) {
        return false;
    }
    out = it->get<std::string>();
    return true;
}

bool read_bool(const Json& json, const char* key, bool& out) {
    const auto it = json.find(key);
    if (it == json.end() || !it->is_boolean()) {
        return false;
    }
    out = it->get<bool>();
    return true;
}

bool read_double(const Json& json, const char* key, double& out) {
    const auto it = json.find(key);
    if (it == json.end() || !it->is_number()) {
        return false;
    }
    out = it->get<double>();
    return true;
}

bool read_int64(const Json& json, const char* key, std::int64_t& out) {
    const auto it = json.find(key);
    if (it == json.end() || !it->is_number_integer()) {
        return false;
    }
    out = it->get<std::int64_t>();
    return true;
}

bool read_uint64(const Json& json, const char* key, std::uint64_t& out) {
    const auto it = json.find(key);
    if (it == json.end() || !it->is_number_unsigned()) {
        return false;
    }
    out = it->get<std::uint64_t>();
    return true;
}

} // namespace

std::string to_json_text(const SeismicViewState& state) {
    Json json;
    json["schema_version"] = state.schema_version;
    json["volume_id"] = state.volume_id;
    json["volume_version"] = state.volume_version;
    json["axis"] = state.axis;
    json["slice_index"] = state.slice_index;
    json["color_map"] = state.color_map;
    json["display_mode"] = state.display_mode;
    json["polarity_normal"] = state.polarity_normal;
    json["clip_enabled"] = state.clip_enabled;
    json["clip_percentile"] = state.clip_percentile;
    json["wiggle_gain"] = state.wiggle_gain;
    json["auto_range"] = state.auto_range;
    json["range_min"] = state.range_min;
    json["range_max"] = state.range_max;
    json["view_scale"] = state.view_scale;
    json["view_offset_x"] = state.view_offset_x;
    json["view_offset_y"] = state.view_offset_y;
    json["picking_enabled"] = state.picking_enabled;
    json["picks"] = state.picks;
    return pwb::domain::dump_json_python_compatible(json);
}

ViewStateParse from_json_text(std::string_view text, SeismicViewState& state,
                              std::string& error) {
    error.clear();
    Json json;
    try {
        json = Json::parse(text);
    } catch (const std::exception& caught) {
        error = caught.what();
        return ViewStateParse::bad_json;
    }
    if (!json.is_object()) {
        error = "view state is not a JSON object";
        return ViewStateParse::bad_schema;
    }

    SeismicViewState parsed;
    int schema_version = 0;
    {
        const auto it = json.find("schema_version");
        if (it == json.end() || !it->is_number_integer()) {
            error = "missing integer schema_version";
            return ViewStateParse::bad_schema;
        }
        schema_version = it->get<int>();
    }
    if (schema_version != kSeismicViewStateSchemaVersion) {
        error = "unsupported view-state schema_version: " +
                std::to_string(schema_version);
        return ViewStateParse::bad_schema;
    }
    if (!read_string(json, "volume_id", parsed.volume_id) ||
        !read_uint64(json, "volume_version", parsed.volume_version) ||
        !read_string(json, "axis", parsed.axis) ||
        !read_int64(json, "slice_index", parsed.slice_index) ||
        !read_string(json, "color_map", parsed.color_map) ||
        !read_string(json, "display_mode", parsed.display_mode) ||
        !read_bool(json, "polarity_normal", parsed.polarity_normal) ||
        !read_bool(json, "clip_enabled", parsed.clip_enabled) ||
        !read_double(json, "clip_percentile", parsed.clip_percentile) ||
        !read_double(json, "wiggle_gain", parsed.wiggle_gain) ||
        !read_bool(json, "auto_range", parsed.auto_range) ||
        !read_double(json, "range_min", parsed.range_min) ||
        !read_double(json, "range_max", parsed.range_max) ||
        !read_double(json, "view_scale", parsed.view_scale) ||
        !read_double(json, "view_offset_x", parsed.view_offset_x) ||
        !read_double(json, "view_offset_y", parsed.view_offset_y) ||
        !read_bool(json, "picking_enabled", parsed.picking_enabled)) {
        error = "view state is missing or mistyping a required key";
        return ViewStateParse::bad_schema;
    }
    const auto picks = json.find("picks");
    if (picks == json.end() || !picks->is_object()) {
        error = "view state picks must be an object (HorizonPickSet document)";
        return ViewStateParse::bad_schema;
    }
    parsed.picks = *picks;

    state = std::move(parsed);
    return ViewStateParse::ok;
}

} // namespace pwb::seismic_viewer
