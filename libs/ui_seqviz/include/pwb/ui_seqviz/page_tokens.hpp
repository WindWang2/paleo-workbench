#pragma once

// UI-10 — tokens.py constants the sequence/factor/viz pages consume.
// Metric values are frozen tokens.py numbers; the method/scheme tables are
// the registry-derived UI vocabulary (algorithm_registry ui_interpolation_
// methods + INTERPOLATION_METHOD_TOOLTIPS verbatim).

#include <map>
#include <string>
#include <vector>

namespace pwb::ui_seqviz::tokens {

// --- spacing / radius (tokens.py) -------------------------------------------
inline constexpr int SPACE_1 = 4;
inline constexpr int SPACE_2 = 8;
inline constexpr int SPACE_3 = 12;
inline constexpr int SPACE_4 = 20;
inline constexpr int PAGE_MARGIN = 16;
inline constexpr int PANEL_PADDING = 12;
inline constexpr int RADIUS_BUTTON = 4;

// --- sequence page (tokens.py) ----------------------------------------------
inline const std::vector<std::string>& sequence_schemes() {
    static const std::vector<std::string> schemes = {
        "三级层序格架（推荐）", "四级高频层序", "体系域二分方案"};
    return schemes;
}

inline const std::vector<std::string>& systems_tract_labels() {
    static const std::vector<std::string> labels = {"LST", "TST", "HST"};
    return labels;
}

// --- interpolation method vocabulary (registry-derived; order frozen) -------
inline const std::vector<std::string>& interpolation_methods() {
    static const std::vector<std::string> methods = {
        "克里金", "IDW", "约束IDW", "样条", "方向趋势"};
    return methods;
}

inline const std::map<std::string, std::string>&
interpolation_method_tooltips() {
    static const std::map<std::string, std::string> tooltips = {
        {"克里金",
         "真实普通克里金：经验变差函数拟合 + 克里金求解（含克里金方差）"},
        {"IDW", "反距离加权；支持断层屏障 fault_polylines"},
        {"约束IDW",
         "约束反距离加权：断层/屏障区域分割 + 方向走廊各向异性 + 井点锚定"
         "（来自 haiyou-visualization）"},
        {"样条", "SciPy cubic 样条插值"},
        {"方向趋势", "各向异性方向加权趋势面（ISS-ALG-02）"},
    };
    return tooltips;
}

}  // namespace pwb::ui_seqviz::tokens
