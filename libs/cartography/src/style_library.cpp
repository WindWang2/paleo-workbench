// CONV-27 — implementation of the geological style library V1.
#include <pwb/cartography/style_library.hpp>

#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace pwb::cartography {

Json StyleEntry::to_dict() const {
    Json data = Json::object();
    data["key"] = key;
    data["category"] = category;
    data["title"] = title;
    data["style"] = style.to_dict();
    data["binding"] = binding;
    data["legend_label"] = legend_label;
    if (opacity_hint.has_value()) {
        data["opacity_hint"] = *opacity_hint;
    } else {
        data["opacity_hint"] = nullptr;
    }
    return data;
}

StyleEntry StyleEntry::from_dict(const Json& data) {
    StyleEntry entry;
    if (!data.is_object()) {
        throw std::invalid_argument("style entry payload must be an object");
    }
    entry.key = data.at("key").get<std::string>();
    entry.category = data.at("category").get<std::string>();
    entry.title = data.at("title").get<std::string>();
    auto style_it = data.find("style");
    entry.style = VectorStyle::from_dict(style_it != data.end() ? *style_it : Json());
    auto binding_it = data.find("binding");
    if (binding_it != data.end() && binding_it->is_object()) {
        entry.binding = *binding_it;
    } else {
        entry.binding = Json::object();
    }
    auto label_it = data.find("legend_label");
    if (label_it != data.end() && !label_it->is_null()) {
        entry.legend_label = label_it->get<std::string>();
    }
    auto hint_it = data.find("opacity_hint");
    if (hint_it != data.end() && hint_it->is_number()) {
        entry.opacity_hint = hint_it->get<double>();
    }
    return entry;
}

const std::vector<std::string>& style_library_categories() {
    static const std::vector<std::string> categories = {
        "well_symbols", "facies_fills", "contour", "fault", "horizon",
        "uncertainty", "boundary", "reference", "annotation",
    };
    return categories;
}

namespace {

StyleCategory style_category(const char* value, const char* fill,
                             const char* label) {
    return StyleCategory{value, fill, label};
}

// The standard V1 沉积相 palette (geological_style_library._facies_palette).
std::vector<StyleCategory> facies_palette() {
    return {
        {"泥岩", "#9aa7b5", "泥岩"},   {"砂岩", "#f2d38a", "砂岩"},
        {"河口坝", "#e8b04b", "河口坝"}, {"浅湖", "#8fc7c2", "浅湖"},
        {"半深湖", "#5f9ea0", "半深湖"}, {"深湖", "#3d6b8e", "深湖"},
        {"扇三角洲", "#d9a066", "扇三角洲"}, {"冲积扇", "#c47f4e", "冲积扇"},
    };
}

}  // namespace

const std::vector<std::pair<std::string, StyleEntry>>&
geological_style_library() {
    static const std::vector<std::pair<std::string, StyleEntry>> library = [] {
        std::vector<std::pair<std::string, StyleEntry>> entries;
        auto add = [&](StyleEntry entry) {
            entries.push_back({entry.category + "." + entry.key,
                               std::move(entry)});
        };
        // --- wells ---------------------------------------------------------
        add(StyleEntry{
            "well_standard", "well_symbols", "标准井位",
            [] {
                VectorStyle s;
                s.fill = "#22b8a7";
                s.stroke = "#182431";
                s.stroke_width = 1.0;
                s.marker = MarkerSymbol::Well;
                s.marker_size = 8.0;
                return s;
            }(),
            Json::parse(R"({"class": "well", "field": ""})"),
            "井位", std::nullopt});
        add(StyleEntry{
            "well_fenced", "well_symbols", "围栏井位",
            [] {
                VectorStyle s;
                s.fill = "#e45756";
                s.stroke = "#3a1a1a";
                s.stroke_width = 1.2;
                s.marker = MarkerSymbol::Triangle;
                s.marker_size = 9.0;
                return s;
            }(),
            Json::parse(R"({"class": "well", "field": "well_type"})"),
            "围栏井", std::nullopt});
        // --- facies ----------------------------------------------------------
        add(StyleEntry{
            "facies_v1", "facies_fills", "沉积相标准色板",
            [] {
                VectorStyle s;
                s.fill = "#b0bec5";
                s.stroke = "#26364d";
                s.stroke_width = 1.0;
                s.renderer = "categorized";
                s.field = "facies_name";
                s.categories = facies_palette();
                return s;
            }(),
            [] {
                Json binding = Json::object();
                binding["field"] = "facies_name";
                Json classes = Json::array();
                for (const StyleCategory& category : facies_palette()) {
                    classes.push_back(category.value);
                }
                binding["classes"] = std::move(classes);
                binding["source"] = "geological-style-library-v1/facies_v1";
                return binding;
            }(),
            "沉积相", std::nullopt});
        // --- contour -----------------------------------------------------------
        add(StyleEntry{
            "contour_index", "contour", "计曲线",
            [] {
                VectorStyle s;
                s.stroke = "#7a4f21";
                s.stroke_width = 1.6;
                return s;
            }(),
            Json::parse(R"({"class": "contour", "field": "is_index_contour"})"),
            "计曲线", std::nullopt});
        add(StyleEntry{
            "contour_intermediate", "contour", "首曲线",
            [] {
                VectorStyle s;
                s.stroke = "#a9763f";
                s.stroke_width = 0.8;
                return s;
            }(),
            Json::parse(R"({"class": "contour", "field": "is_index_contour"})"),
            "首曲线", std::nullopt});
        // --- fault ---------------------------------------------------------------
        add(StyleEntry{
            "fault_major", "fault", "主干断层",
            [] {
                VectorStyle s;
                s.stroke = "#c0392b";
                s.stroke_width = 2.0;
                s.line_pattern = LinePattern::Dash;
                return s;
            }(),
            Json::parse(R"({"class": "fault", "field": "fault_level"})"),
            "主干断层", std::nullopt});
        add(StyleEntry{
            "fault_secondary", "fault", "次级断层",
            [] {
                VectorStyle s;
                s.stroke = "#e67e22";
                s.stroke_width = 1.2;
                s.line_pattern = LinePattern::DashDot;
                return s;
            }(),
            Json::parse(R"({"class": "fault", "field": "fault_level"})"),
            "次级断层", std::nullopt});
        // --- horizon ---------------------------------------------------------------
        add(StyleEntry{
            "horizon_top", "horizon", "层位顶界",
            [] {
                VectorStyle s;
                s.stroke = "#2f6fab";
                s.stroke_width = 1.4;
                return s;
            }(),
            Json::parse(R"({"class": "horizon", "field": ""})"),
            "层位顶界", std::nullopt});
        // --- uncertainty -------------------------------------------------------------
        add(StyleEntry{
            "uncertainty_band", "uncertainty", "不确定度分级",
            [] {
                VectorStyle s;
                s.fill = "#808080";
                s.stroke = "#4d4d4d";
                s.stroke_width = 0.6;
                s.renderer = "graduated";
                s.field = "confidence";
                s.ranges = {
                    {0.0, 0.5, "#c9b8d8", "低置信度 (<0.5)"},
                    {0.5, 0.8, "#8fa8c8", "中等置信度"},
                    {0.8, 1.01, "#7fbf9e", "高置信度"},
                };
                return s;
            }(),
            Json::parse(
                R"json({"field": "confidence", "classes": ["低置信度 (<0.5)", "中等置信度", "高置信度"], "note": "透明度经图层 opacity 应用，样式色板保持可读"})json"),
            "置信度", std::nullopt});
        // --- boundary -------------------------------------------------------------------
        add(StyleEntry{
            "study_boundary", "boundary", "工区边界",
            [] {
                VectorStyle s;
                s.stroke = "#34495e";
                s.stroke_width = 2.2;
                s.line_pattern = LinePattern::Solid;
                return s;
            }(),
            Json::parse(R"({"class": "boundary", "field": ""})"),
            "工区边界", std::nullopt});
        // --- reference ---------------------------------------------------------------------
        add(StyleEntry{
            "reference_basemap", "reference", "参考底图",
            [] {
                VectorStyle s;
                s.fill = "#f5f2ea";
                s.stroke = "#b8b0a0";
                s.stroke_width = 0.6;
                return s;
            }(),
            Json::parse(R"({"class": "reference", "field": ""})"),
            "参考底图", 0.4});
        // --- annotation -----------------------------------------------------------------------
        add(StyleEntry{
            "annotation_text", "annotation", "图面标注",
            [] {
                VectorStyle s;
                s.stroke = "#2c3e50";
                s.stroke_width = 0.8;
                return s;
            }(),
            Json::parse(R"({"class": "annotation", "field": ""})"),
            "标注", std::nullopt});
        return entries;
    }();
    return library;
}

const StyleEntry& style_entry_lookup(const std::string& category,
                                     const std::string& key) {
    const std::string full_key = category + "." + key;
    for (const auto& entry : geological_style_library()) {
        if (entry.first == full_key) return entry.second;
    }
    // Python: available = sorted keys with the category prefix.
    std::vector<std::string> available;
    for (const auto& entry : geological_style_library()) {
        if (entry.first.rfind(category, 0) == 0) available.push_back(entry.first);
    }
    std::sort(available.begin(), available.end());
    std::string listing = "[";
    for (std::size_t i = 0; i < available.size(); ++i) {
        if (i > 0) listing += ", ";
        listing += "'" + available[i] + "'";
    }
    listing += "]";
    throw std::out_of_range("unknown style '" + full_key +
                            "'; available: " + listing);
}

void apply_style_entry(Json& style_payload, double& layer_opacity,
                       const StyleEntry& entry) {
    style_payload = entry.style.to_dict();
    style_payload["style_binding"] = entry.binding;
    if (entry.opacity_hint.has_value()) {
        layer_opacity = std::min(layer_opacity, *entry.opacity_hint);
    }
}

Json style_library_document() {
    Json payload = Json::object();
    payload["schema_version"] = kStyleLibrarySchemaVersion;
    Json styles = Json::array();
    for (const auto& keyed : geological_style_library()) {
        styles.push_back(keyed.second.to_dict());
    }
    payload["styles"] = std::move(styles);
    return payload;
}

std::vector<std::pair<std::string, StyleEntry>> parse_style_library_document(
    const Json& document) {
    if (!document.is_object()) {
        throw std::invalid_argument("style library document must be an object");
    }
    long long version = 0;
    auto version_it = document.find("schema_version");
    if (version_it != document.end() && version_it->is_number_integer()) {
        version = version_it->get<long long>();
    }
    if (version != kStyleLibrarySchemaVersion) {
        throw std::invalid_argument(
            "style library schema " + std::to_string(version) +
            " unsupported; expected " +
            std::to_string(kStyleLibrarySchemaVersion));
    }
    std::vector<std::pair<std::string, StyleEntry>> entries;
    auto styles_it = document.find("styles");
    if (styles_it != document.end() && styles_it->is_array()) {
        for (const Json& raw : *styles_it) {
            StyleEntry entry = StyleEntry::from_dict(raw);
            entries.push_back({entry.category + "." + entry.key,
                               std::move(entry)});
        }
    }
    return entries;
}

}  // namespace pwb::cartography
