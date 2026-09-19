#include "pwb/ui_widgets/core/facies_patterns.hpp"

#include <filesystem>
#include <map>

namespace pwb::ui_widgets::core {

namespace {

std::string trim_copy(const std::string& s) {
    const auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

// Facies name -> pattern id table (FACIES_PATTERN_MAP parity; comments in
// the Python source carry the geological rationale per approximate match).
const std::map<std::string, std::string>& pattern_map() {
    static const std::map<std::string, std::string> map = {
        {"alluvial_fan", "alluvial_fan"},   {"fluvial", "fluvial"},
        {"lacustrine", "lacustrine"},       {"delta", "delta"},
        {"shallow_marine", "shallow_marine"}, {"deep_marine", "deep_marine"},
        {"shoreline", "shoreface"},
        {"扇三角洲", "delta"},           {"三角洲前缘", "delta"},
        {"滨浅湖", "lacustrine"},         {"湖相泥", "lacustrine"},
        {"冲积扇", "alluvial_fan"},       {"河流", "fluvial"},
        {"湖泊", "lacustrine"},           {"三角洲", "delta"},
        {"岸线带", "shoreface"},          {"浅海", "shallow_marine"},
        {"深海", "deep_marine"},
        {"深水盆地", "abyssal"},          {"滨岸", "shoreface"},
        {"潟湖", "lagoon"},               {"潮坪", "tidal_flat"},
        {"碳酸盐台地", "carbonate_platform"}, {"陆棚", "shelf"},
    };
    return map;
}

// _FACIES_FALLBACK_PALETTE (stage_actions) — stable hash fallback palette.
const std::vector<std::string>& fallback_palette() {
    static const std::vector<std::string> palette = {
        "#c47f4e", "#e8c46b", "#8fc7c2", "#d9a066",
        "#eae2b0", "#6fb3b8", "#3d6b8e", "#9b6b9e",
    };
    return palette;
}

}  // namespace

std::optional<std::string> pattern_id_for_facies(const std::string& name) {
    const auto it = pattern_map().find(trim_copy(name));
    if (it == pattern_map().end()) return std::nullopt;
    return it->second;
}

std::optional<std::string> pattern_path_for_facies(
    const std::string& name, const std::string& pattern_dir) {
    const auto pattern_id = pattern_id_for_facies(name);
    if (!pattern_id) return std::nullopt;
    const std::filesystem::path path =
        std::filesystem::path(pattern_dir) / (*pattern_id + ".svg");
    std::error_code ec;
    if (!std::filesystem::is_regular_file(path, ec)) return std::nullopt;
    return path.string();
}

const std::vector<std::pair<std::string, std::string>>& facies_class_fills() {
    // geological_symbols._FACIES_CLASSES (value, fill) — domain order.
    static const std::vector<std::pair<std::string, std::string>> fills = {
        {"alluvial_fan", "#c47f4e"}, {"fluvial", "#e8c46b"},
        {"lacustrine", "#8fc7c2"},   {"delta", "#d9a066"},
        {"shoreline", "#eae2b0"},    {"shallow_marine", "#6fb3b8"},
        {"deep_marine", "#3d6b8e"},  {"volcanic", "#9b6b9e"},
        {"other", "#b0bec5"},
    };
    return fills;
}

std::string facies_category_color(
    const std::string& name, const std::string& feature_color,
    const std::function<std::string(const std::string&)>& md5_hex) {
    const std::string trimmed = trim_copy(feature_color);
    if (!trimmed.empty()) return trimmed;
    for (const auto& [value, fill] : facies_class_fills()) {
        if (value == name) return fill;
    }
    // Python: int(hashlib.md5(name.encode()).hexdigest(), 16) % len(palette).
    // Equivalent mod-8 without bignum: hex md5 mod 8 depends only on the
    // last hex digit (16 ≡ 0 mod 8 for every place ≥ 1).
    const std::string hex = md5_hex(name);
    if (hex.empty()) return fallback_palette().front();
    const char last = hex.back();
    const int digit = (last >= '0' && last <= '9')   ? last - '0'
                      : (last >= 'a' && last <= 'f') ? last - 'a' + 10
                      : (last >= 'A' && last <= 'F') ? last - 'A' + 10
                                                     : 0;
    return fallback_palette()[static_cast<std::size_t>(digit % 8) %
                            fallback_palette().size()];
}

}  // namespace pwb::ui_widgets::core
