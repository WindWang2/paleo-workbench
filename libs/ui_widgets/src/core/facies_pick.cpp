#include "pwb/ui_widgets/core/facies_pick.hpp"

#include "pwb/ui_widgets/core/facies_patterns.hpp"
#include "pwb/ui_widgets/core/facies_taxonomy.hpp"
#include "pwb/ui_widgets/core/tree_sync.hpp"  // py_str / py_truthy

namespace pwb::ui_widgets::core {

namespace {

std::string attr_str(const nlohmann::ordered_json& attributes,
                     const char* key) {
    if (!attributes.is_object() || !attributes.contains(key)) return "";
    const auto& value = attributes[key];
    return py_truthy(value) ? py_str(value) : "";
}

std::string trim_copy(const std::string& s) {
    const auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

}  // namespace

std::optional<FaciesPickResult> pick_facies_at(
    double x, double y, const FaciesIdentifyFn& identify,
    const FaciesColorFn& color_of) {
    if (!identify) return std::nullopt;
    for (const nlohmann::ordered_json& hit : identify(x, y)) {
        if (!hit.is_object()) continue;
        const auto attributes =
            hit.value("attributes", nlohmann::ordered_json{});
        const std::string facies = trim_copy(attr_str(attributes, "facies"));
        if (facies.empty()) continue;  // non-facies feature: next hit
        FaciesPickResult result;
        result.facies = facies;
        result.sub_facies = attr_str(attributes, "sub_facies");
        result.micro_facies = attr_str(attributes, "micro_facies");
        result.level = FaciesTaxonomy::selection_level(
            {{"facies", result.facies},
             {"sub_facies", result.sub_facies},
             {"micro_facies", result.micro_facies}});
        result.layer_id = hit.contains("layer_id") ? py_str(hit["layer_id"]) : "";
        result.feature_id =
            hit.contains("feature_id") ? py_str(hit["feature_id"]) : "";
        result.layer_name =
            hit.contains("layer_name") ? py_str(hit["layer_name"]) : "";
        result.color = color_of ? color_of(facies) : "";
        result.pattern = pattern_id_for_facies(facies);
        return result;
    }
    return std::nullopt;
}

}  // namespace pwb::ui_widgets::core
