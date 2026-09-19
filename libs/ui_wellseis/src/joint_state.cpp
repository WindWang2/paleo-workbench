#include <pwb/ui_wellseis/joint_state.hpp>

#include <algorithm>

#include <pwb/ui_wellseis/json_helpers.hpp>

namespace pwb::ui_wellseis {

namespace {

Json str_bool_map_to_json(const std::map<std::string, bool>& map) {
    Json out = Json::object();
    for (const auto& [key, value] : map) {
        out[key] = value;
    }
    return out;
}

Json str_str_map_to_json(const std::map<std::string, std::string>& map) {
    Json out = Json::object();
    for (const auto& [key, value] : map) {
        out[key] = value;
    }
    return out;
}

std::map<std::string, bool> str_bool_map_from_json(const Json& payload) {
    std::map<std::string, bool> out;
    if (!payload.is_object()) {
        return out;
    }
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        if (it.value().is_boolean()) {
            out[it.key()] = it.value().get<bool>();
        }
    }
    return out;
}

std::map<std::string, std::string> str_str_map_from_json(const Json& payload) {
    std::map<std::string, std::string> out;
    if (!payload.is_object()) {
        return out;
    }
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        if (it.value().is_string()) {
            out[it.key()] = it.value().get<std::string>();
        }
    }
    return out;
}

template <typename T>
Json opt_to_json(const std::optional<T>& value) {
    return value.has_value() ? Json(*value) : Json(nullptr);
}

std::optional<int> opt_int(const Json& source, std::string_view key) {
    const Json& v = json_field(source, key);
    if (v.is_number_integer() || v.is_number_unsigned()) {
        return static_cast<int>(v.get<long long>());
    }
    return std::nullopt;
}

std::optional<double> opt_double(const Json& source, std::string_view key) {
    const Json& v = json_field(source, key);
    if (v.is_number()) {
        return v.get<double>();
    }
    return std::nullopt;
}

std::optional<std::string> opt_str(const Json& source, std::string_view key) {
    const Json& v = json_field(source, key);
    if (v.is_string()) {
        return v.get<std::string>();
    }
    return std::nullopt;
}

int clamp_int(int value, int low, int high) {
    return std::max(low, std::min(value, high));
}

int json_int(const Json& source, std::string_view key, int fallback) {
    const Json& v = json_field(source, key);
    if (v.is_number_integer() || v.is_number_unsigned()) {
        return static_cast<int>(v.get<long long>());
    }
    if (v.is_number_float()) {
        return static_cast<int>(v.get<double>());
    }
    return fallback;
}

}  // namespace

Json joint_state_to_json(const JointAnalysisSlice& state) {
    Json out = Json::object();
    out["tree_checks"] = str_bool_map_to_json(state.tree_checks);
    out["well_visibility"] = str_bool_map_to_json(state.well_visibility);
    out["well_identity_asset_id"] =
        state.well_identity_asset_id.empty() ? Json(nullptr)
                                             : Json(state.well_identity_asset_id);
    out["well_identity_map"] = str_str_map_to_json(state.well_identity_map);
    out["seismic_color_scale"] = state.seismic_color_scale;
    out["gr_color_scale"] = state.gr_color_scale;
    out["well_width_px"] = state.well_width_px;
    out["orthogonal_inline_index"] = opt_to_json(state.orthogonal_inline_index);
    out["orthogonal_crossline_index"] =
        opt_to_json(state.orthogonal_crossline_index);
    out["orthogonal_inline_number"] =
        opt_to_json(state.orthogonal_inline_number);
    out["orthogonal_crossline_number"] =
        opt_to_json(state.orthogonal_crossline_number);
    Json slices = Json::array();
    for (const JointTimeSliceState& slice : state.time_slices) {
        Json entry = Json::object();
        entry["time_ms"] = slice.time_ms;
        entry["visible"] = slice.visible;
        slices.push_back(std::move(entry));
    }
    out["time_slices"] = std::move(slices);
    out["active_time_slice_ms"] = opt_to_json(state.active_time_slice_ms);
    out["time_slice_opacity"] = state.time_slice_opacity;
    out["vertical_domain"] = state.vertical_domain;
    out["active_fence_wells"] = state.active_fence_wells;
    out["active_fence_name"] = opt_to_json(state.active_fence_name);
    out["path_hints"] = str_str_map_to_json(state.path_hints);
    return out;
}

JointAnalysisSlice joint_state_from_json(const Json& payload) {
    JointAnalysisSlice state;
    if (!payload.is_object()) {
        return state;
    }
    state.tree_checks = str_bool_map_from_json(json_field(payload, "tree_checks"));
    state.well_visibility =
        str_bool_map_from_json(json_field(payload, "well_visibility"));
    state.well_identity_asset_id =
        opt_str(payload, "well_identity_asset_id").value_or("");
    state.well_identity_map =
        str_str_map_from_json(json_field(payload, "well_identity_map"));
    state.seismic_color_scale =
        json_str(payload, "seismic_color_scale", "blue-white-red");
    state.gr_color_scale = json_str(payload, "gr_color_scale", "viridis");
    state.well_width_px = clamp_int(json_int(payload, "well_width_px", 5),
                                    kJointWellWidthMin, kJointWellWidthMax);
    state.orthogonal_inline_index = opt_int(payload, "orthogonal_inline_index");
    state.orthogonal_crossline_index =
        opt_int(payload, "orthogonal_crossline_index");
    state.orthogonal_inline_number =
        opt_double(payload, "orthogonal_inline_number");
    state.orthogonal_crossline_number =
        opt_double(payload, "orthogonal_crossline_number");
    const Json& slices = json_array(payload, "time_slices");
    state.time_slices.clear();
    for (const Json& entry : slices) {
        if (state.time_slices.size() >= kJointMaxTimeSlices) {
            break;
        }
        if (!entry.is_object()) {
            continue;
        }
        JointTimeSliceState slice;
        slice.time_ms = opt_double(entry, "time_ms").value_or(0.0);
        slice.visible = json_bool(entry, "visible", true);
        state.time_slices.push_back(slice);
    }
    state.active_time_slice_ms = opt_double(payload, "active_time_slice_ms");
    state.time_slice_opacity =
        clamp_int(json_int(payload, "time_slice_opacity", 80),
                  kJointOpacityMin, kJointOpacityMax);
    state.vertical_domain = json_str(payload, "vertical_domain", "Time");
    state.active_fence_wells.clear();
    for (const Json& entry : json_array(payload, "active_fence_wells")) {
        if (entry.is_string()) {
            state.active_fence_wells.push_back(entry.get<std::string>());
        }
    }
    state.active_fence_name = opt_str(payload, "active_fence_name");
    state.path_hints = str_str_map_from_json(json_field(payload, "path_hints"));
    return state;
}

}  // namespace pwb::ui_wellseis
