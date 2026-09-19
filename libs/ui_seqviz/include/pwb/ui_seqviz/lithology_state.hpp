#pragma once

// UI-10 — Qt-free state core for lithology_crossplot_dialog.py.
//
// The dialog renders an HTML statistical report; this core owns the
// analysis_result → (cluster rows, HTML) mapping. Palette colors are
// injected (the Qt shell reads style.palette()/tokens) — no theme
// dependency here.

#include <map>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_seqviz {

// One cluster's statistics (analysis_result["clusters"][lith]).
struct LithologyClusterStats {
    long long count = 0;
    double mean_gr = 0.0;
    double std_gr = 0.0;
    double mean_ai = 0.0;
    double std_ai = 0.0;
};

// analysis_result slice.
struct LithologyAnalysisSlice {
    // Ordered cluster map (Python dict iteration order — the caller
    // preserves it; std::map would reorder, so a vector of pairs).
    std::vector<std::pair<std::string, LithologyClusterStats>> clusters;
    std::size_t total_points = 0;
};

// Parse analysis_result Json → slice (clusters object iteration order
// preserved; len(points) → total_points).
LithologyAnalysisSlice lithology_analysis_slice(const domain::Json& result);

// The 储层评价 evaluation map — lithology → (css color, label) with the
// "未分类" fallback color. Colors are the frozen domain-semantic palette
// (_LITHO_EVAL_COLORS verbatim); the fallback uses the injected
// text_secondary token.
struct LithologyEval {
    std::string color;
    std::string label;
};
LithologyEval lithology_eval(const std::string& lithology,
                             const std::string& text_secondary);

// The full HTML body — verbatim template; theme colors are injected.
struct LithologyPalette {
    std::string text_secondary;
    std::string primary;
    std::string border;
    std::string bg_search;
    std::string text_primary;
};
std::string lithology_report_html(const LithologyAnalysisSlice& slice,
                                  const LithologyPalette& palette);

}  // namespace pwb::ui_seqviz
