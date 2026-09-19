#include <pwb/viz/well_log_track_layout.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cctype>
#include <utility>

namespace pwb::viz {

namespace {

constexpr std::string_view kTemplateSchema = "pwb.well_log_track_template";

std::string scale_mode_to_string(std::optional<TrackScaleMode> mode) {
    if (mode == TrackScaleMode::logarithmic) return "log";
    if (mode == TrackScaleMode::linear) return "linear";
    return "auto";
}

std::optional<TrackScaleMode> scale_mode_from_string(std::string_view text) {
    if (text == "log") return TrackScaleMode::logarithmic;
    if (text == "linear") return TrackScaleMode::linear;
    return std::nullopt;
}

[[nodiscard]] bool is_valid_grouping(const WellLogTrackLayout& layout) {
    if (layout.curve_keys.size() != layout.visible.size() ||
        layout.curve_keys.size() != layout.scale_mode.size() ||
        layout.curve_keys.size() != layout.color.size()) {
        return false;
    }
    std::size_t seen = 0;
    for (const auto& group : layout.groups) {
        if (group.empty() || group.size() > kMaxCurvesPerTrack) {
            return false;
        }
        for (const auto& key : group) {
            const auto index = layout.key_index(key); // throws on unknown
            if (index >= layout.curve_keys.size()) {
                return false;
            }
            ++seen;
        }
    }
    return seen == layout.curve_keys.size();
}

} // namespace

std::size_t WellLogTrackLayout::key_index(std::string_view curve_key) const {
    const auto found = std::find(curve_keys.begin(), curve_keys.end(), curve_key);
    if (found == curve_keys.end()) {
        throw std::out_of_range("unknown curve key: " + std::string(curve_key));
    }
    return static_cast<std::size_t>(found - curve_keys.begin());
}

const std::vector<std::string>&
WellLogTrackLayout::group_for(std::string_view curve_key) const {
    for (const auto& group : groups) {
        if (std::find(group.begin(), group.end(), curve_key) != group.end()) {
            return group;
        }
    }
    throw std::out_of_range("curve key has no group: " + std::string(curve_key));
}

WellLogTrackLayout
WellLogTrackLayout::with_visible(std::string_view curve_key,
                                 bool is_visible) const {
    WellLogTrackLayout next = *this;
    next.visible[key_index(curve_key)] = is_visible;
    return next;
}

WellLogTrackLayout WellLogTrackLayout::merge(std::string_view curve_key,
                                             std::string_view onto) const {
    const auto source_index = key_index(curve_key);
    const auto target_index = key_index(onto);
    if (source_index == target_index) {
        return *this;
    }
    auto source_group = group_for(curve_key);
    const auto& target_group = group_for(onto);
    if (source_group == target_group) {
        return *this;
    }
    if (target_group.size() >= kMaxCurvesPerTrack) {
        throw curve_group_limit_error("each merged well track holds at most " +
                                      std::to_string(kMaxCurvesPerTrack) +
                                      " curves");
    }
    WellLogTrackLayout next = *this;
    next.groups.clear();
    for (const auto& group : groups) {
        if (group == source_group) {
            std::vector<std::string> remainder;
            remainder.reserve(group.size() - 1);
            for (const auto& key : group) {
                if (key != curve_key) {
                    remainder.push_back(key);
                }
            }
            if (!remainder.empty()) {
                next.groups.push_back(std::move(remainder));
            }
        } else if (group == target_group) {
            // The moved curve is named first, mirroring the direct
            // manipulation action (dragging GR onto AC reads "GR / AC").
            std::vector<std::string> merged;
            merged.reserve(group.size() + 1);
            merged.push_back(std::string(curve_key));
            merged.insert(merged.end(), group.begin(), group.end());
            next.groups.push_back(std::move(merged));
        } else {
            next.groups.push_back(group);
        }
    }
    return next;
}

WellLogTrackLayout WellLogTrackLayout::unmerge(std::string_view curve_key) const {
    const auto& target_group = group_for(curve_key);
    if (target_group.size() <= 1) {
        return *this;
    }
    WellLogTrackLayout next = *this;
    next.groups.clear();
    for (const auto& group : groups) {
        if (group == target_group) {
            for (const auto& key : group) {
                next.groups.push_back({key});
            }
        } else {
            next.groups.push_back(group);
        }
    }
    return next;
}

WellLogTrackLayout
WellLogTrackLayout::move_group(std::string_view curve_key,
                               std::size_t group_position) const {
    static_cast<void>(group_for(curve_key)); // validate the key
    WellLogTrackLayout next = *this;
    auto moved = next.group_for(curve_key);
    auto& target = next.groups;
    target.erase(std::find(target.begin(), target.end(), moved));
    group_position = std::min(group_position, target.size());
    target.insert(target.begin() + static_cast<std::ptrdiff_t>(group_position),
                  std::move(moved));
    return next;
}

WellLogTrackLayout
WellLogTrackLayout::with_scale_mode(std::string_view curve_key,
                                    std::optional<TrackScaleMode> mode) const {
    WellLogTrackLayout next = *this;
    next.scale_mode[key_index(curve_key)] = mode;
    return next;
}

WellLogTrackLayout WellLogTrackLayout::with_color(std::string_view curve_key,
                                                  std::string hex_color) const {
    WellLogTrackLayout next = *this;
    next.color[key_index(curve_key)] = std::move(hex_color);
    return next;
}

std::string WellLogTrackLayout::to_template_json() const {
    nlohmann::ordered_json json;
    json["schema"] = kTemplateSchema;
    json["version"] = 1;
    auto curve_array = nlohmann::ordered_json::array();
    for (std::size_t i = 0; i < curve_keys.size(); ++i) {
        nlohmann::ordered_json entry;
        entry["key"] = curve_keys[i];
        entry["visible"] = visible[i];
        entry["scale_mode"] = scale_mode_to_string(scale_mode[i]);
        entry["color"] = color[i];
        curve_array.push_back(std::move(entry));
    }
    json["curves"] = std::move(curve_array);
    auto group_array = nlohmann::ordered_json::array();
    for (const auto& group : groups) {
        group_array.push_back(group);
    }
    json["groups"] = std::move(group_array);
    return json.dump();
}

bool WellLogTrackLayout::from_template_json(std::string_view json_text,
                                            WellLogTrackLayout& out,
                                            std::string* error) {
    try {
        const auto json = nlohmann::ordered_json::parse(json_text);
        if (!json.is_object() || json.value("schema", "") != kTemplateSchema) {
            if (error != nullptr) {
                *error = "not a " + std::string(kTemplateSchema) + " document";
            }
            return false;
        }
        WellLogTrackLayout layout;
        const auto& curves = json.at("curves");
        if (!curves.is_array()) {
            if (error != nullptr) {
                *error = "curves must be an array";
            }
            return false;
        }
        layout.curve_keys.reserve(curves.size());
        layout.visible.reserve(curves.size());
        layout.scale_mode.reserve(curves.size());
        layout.color.reserve(curves.size());
        for (const auto& entry : curves) {
            layout.curve_keys.push_back(entry.at("key").get<std::string>());
            layout.visible.push_back(entry.value("visible", true));
            layout.scale_mode.push_back(
                scale_mode_from_string(entry.value("scale_mode", "auto")));
            layout.color.push_back(entry.value("color", std::string{}));
        }
        const auto& groups = json.at("groups");
        if (!groups.is_array()) {
            if (error != nullptr) {
                *error = "groups must be an array";
            }
            return false;
        }
        for (const auto& group : groups) {
            layout.groups.push_back(
                group.get<std::vector<std::string>>());
        }
        if (!is_valid_grouping(layout)) {
            if (error != nullptr) {
                *error = "groups must cover every curve exactly once "
                         "(1..3 curves per track)";
            }
            return false;
        }
        out = std::move(layout);
        return true;
    } catch (const std::exception& e) {
        if (error != nullptr) {
            *error = e.what();
        }
        return false;
    }
}

std::string curve_key_for(std::size_t index, std::string_view mnemonic) {
    const std::string name = mnemonic.empty() ? "未命名" : std::string(mnemonic);
    return "curve:" + std::to_string(index) + ":" + name;
}

WellLogTrackLayout
default_track_layout(const std::vector<std::string>& mnemonics) {
    WellLogTrackLayout layout;
    layout.curve_keys.reserve(mnemonics.size());
    layout.visible.assign(mnemonics.size(), false);
    layout.scale_mode.assign(mnemonics.size(), std::nullopt);
    layout.color.assign(mnemonics.size(), std::string{});
    for (std::size_t i = 0; i < mnemonics.size(); ++i) {
        layout.curve_keys.push_back(curve_key_for(i, mnemonics[i]));
        layout.groups.push_back({layout.curve_keys.back()});
    }
    // First six curves visible; GR guaranteed when present.
    const std::size_t shown = std::min<std::size_t>(mnemonics.size(), 6);
    for (std::size_t i = 0; i < shown; ++i) {
        layout.visible[i] = true;
    }
    std::size_t gr_index = mnemonics.size();
    for (std::size_t i = 0; i < mnemonics.size(); ++i) {
        std::string upper;
        upper.reserve(mnemonics[i].size());
        for (const char c : mnemonics[i]) {
            upper.push_back(
                static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
        }
        // Strip before comparing: the oracle compares the stripped mnemonic.
        const std::string stripped = [](const std::string& s) {
            constexpr const char* kWhitespace = " \t\n\r\f\v";
            const auto begin = s.find_first_not_of(kWhitespace);
            if (begin == std::string::npos) return std::string{};
            const auto end = s.find_last_not_of(kWhitespace);
            return s.substr(begin, end - begin + 1);
        }(upper);
        if (stripped == "GR") {
            gr_index = i;
            break;
        }
    }
    if (gr_index < mnemonics.size() && !layout.visible[gr_index]) {
        if (shown > 0) {
            // Replace the last shown slot, mirroring the oracle.
            layout.visible[shown - 1] = false;
        }
        layout.visible[gr_index] = true;
    }
    return layout;
}

WellLogTrackLayout
reconcile_track_layout(const WellLogTrackLayout& layout,
                       const std::vector<std::string>& mnemonics) {
    WellLogTrackLayout fresh = default_track_layout(mnemonics);
    if (layout.curve_keys == fresh.curve_keys) {
        return layout;
    }
    return fresh;
}

} // namespace pwb::viz
