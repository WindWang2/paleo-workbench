#pragma once

// UI-02 — sedimentary-facies -> SVG pattern data contract, ported from
// paleo_workbench/mapping/facies_patterns.py (Qt-free data layer).
//
// The pattern id is the SVG file stem; the render side resolves it to
// <pattern_dir>/<id>.svg. Unmapped names (volcanic/other/火山岩/其他) are
// deliberately absent — lookups return nullopt.

#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_widgets::core {

// Facies name -> pattern id (SVG stem); nullopt when unmapped.
// Pure table lookup, no filesystem access.
[[nodiscard]] std::optional<std::string> pattern_id_for_facies(
    const std::string& name);

// Facies name -> existing SVG path under `pattern_dir`; nullopt when the
// name has no mapping or the mapped file is missing.
[[nodiscard]] std::optional<std::string> pattern_path_for_facies(
    const std::string& name, const std::string& pattern_dir);

// Facies name -> classified fill color, ported from
// stage_actions.facies_category_color: feature color > known class fill >
// stable md5-hash fallback palette (input-order independent).
// `feature_color` wins when non-empty. md5_hex is injected so the Qt-free
// core stays free of crypto deps (Qt side binds QCryptographicHash::Md5).
[[nodiscard]] std::string facies_category_color(
    const std::string& name, const std::string& feature_color,
    const std::function<std::string(const std::string&)>& md5_hex);

// Known class -> printable fill table (geological_symbols._FACIES_CLASSES).
[[nodiscard]] const std::vector<std::pair<std::string, std::string>>&
facies_class_fills();

}  // namespace pwb::ui_widgets::core
