#pragma once

// UI-02 — facies eyedropper pick logic, ported from the pure half of
// paleo_workbench/ui/components/facies_eyedropper.py (Qt-free).
//
// Contract: hits arrive in layer-stack order (topmost first); the FIRST
// hit carrying a non-empty `facies` attribute wins — no guessing, no
// dialog on a miss (nullopt).

#include <nlohmann/json.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_widgets::core {

// Pick result: facies selection + level + provenance + rendered color and
// pattern id (pattern nullopt when unmapped — no fabrication).
struct FaciesPickResult {
    std::string facies;
    std::string sub_facies;
    std::string micro_facies;
    std::string level;       // FaciesTaxonomy::selection_level
    std::string layer_id;
    std::string feature_id;
    std::string layer_name;
    std::string color;
    std::optional<std::string> pattern;
};

using FaciesColorFn = std::function<std::string(const std::string&)>;

// map point -> identify hits (each a dict with attributes/layer_id/
// feature_id/layer_name), in identify_all order.
using FaciesIdentifyFn =
    std::function<std::vector<nlohmann::ordered_json>(double x, double y)>;

// First hit with non-empty `facies` attribute -> pick result; nullopt on
// no facies hit (honest miss — never guess).
[[nodiscard]] std::optional<FaciesPickResult> pick_facies_at(
    double x, double y, const FaciesIdentifyFn& identify,
    const FaciesColorFn& color_of);

}  // namespace pwb::ui_widgets::core
