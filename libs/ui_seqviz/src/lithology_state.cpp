#include <pwb/ui_seqviz/lithology_state.hpp>

#include <cstdio>
#include <utility>

#include <pwb/ui_data_core/json_util.hpp>

namespace pwb::ui_seqviz {

namespace {

// _LITHO_EVAL_COLORS verbatim (domain-semantic reservoir palette).
const std::map<std::string, std::pair<std::string, std::string>>& eval_map() {
    static const std::map<std::string, std::pair<std::string, std::string>>
        table = {
            {"砂岩", {"#059669", "优质储层 (Sand)"}},
            {"泥岩", {"#dc2626", "盖层/隔层 (Shale)"}},
            {"石灰岩", {"#2563eb", "致密/碳酸盐岩 (Limestone)"}},
            {"花岗岩", {"#d97706", "基底结晶岩 (Granite)"}},
        };
    return table;
}

std::string escape_html(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (const char c : text) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"': out += "&quot;"; break;
            case '\'': out += "&#x27;"; break;
            default: out += c;
        }
    }
    return out;
}

}  // namespace

LithologyAnalysisSlice lithology_analysis_slice(const domain::Json& result) {
    LithologyAnalysisSlice slice;
    if (!result.is_object()) {
        return slice;
    }
    const auto clusters_it = result.find("clusters");
    if (clusters_it != result.end() && clusters_it->is_object()) {
        for (const auto& [lith, stats] : clusters_it->items()) {
            LithologyClusterStats row;
            row.count =
                ui_data_core::json_get_opt_int(stats, "count").value_or(0);
            row.mean_gr =
                ui_data_core::json_get_opt_double(stats, "mean_gr")
                    .value_or(0.0);
            row.std_gr = ui_data_core::json_get_opt_double(stats, "std_gr")
                             .value_or(0.0);
            row.mean_ai =
                ui_data_core::json_get_opt_double(stats, "mean_ai")
                    .value_or(0.0);
            row.std_ai = ui_data_core::json_get_opt_double(stats, "std_ai")
                             .value_or(0.0);
            slice.clusters.emplace_back(lith, row);
        }
    }
    const auto points_it = result.find("points");
    if (points_it != result.end() && points_it->is_array()) {
        slice.total_points = points_it->size();
    }
    return slice;
}

LithologyEval lithology_eval(const std::string& lithology,
                             const std::string& text_secondary) {
    const auto it = eval_map().find(lithology);
    if (it != eval_map().end()) {
        return {it->second.first, it->second.second};
    }
    return {text_secondary, "未分类"};
}

std::string lithology_report_html(const LithologyAnalysisSlice& slice,
                                  const LithologyPalette& palette) {
    std::string html;
    char buf[512];
    std::snprintf(
        buf, sizeof(buf),
        "<p style='color: %s; font-size: 12px; margin-bottom: 12px;'>"
        "基于钻孔分层测井数据计算得到 %zu 组有效采样点。下表展示了不同岩性"
        "在“自然伽马 (GR)”与“声波波阻抗 (AI)”空间的聚类中心与离散度特征。"
        "</p>"
        "<h3 style='color: %s; border-bottom: 1px solid %s; padding-bottom: "
        "4px;'>▤ 岩性聚类特征统计 (Lithology Cluster Statistics)</h3>"
        "<table style='width: 100%%; border-collapse: collapse; margin-top: "
        "8px; margin-bottom: 16px;'>"
        "<tr style='background: %s; color: %s;'>"
        "<th style='padding: 8px; text-align: left;'>岩性 (Lithology)</th>"
        "<th style='padding: 8px; text-align: center;'>采样点数</th>"
        "<th style='padding: 8px; text-align: center;'>均值 GR (API)</th>"
        "<th style='padding: 8px; text-align: center;'>均值 AI "
        "(m/s·g/cm³)</th>"
        "<th style='padding: 8px; text-align: center;'>储层评价</th></tr>",
        palette.text_secondary.c_str(), slice.total_points,
        palette.primary.c_str(), palette.border.c_str(),
        palette.bg_search.c_str(), palette.text_primary.c_str());
    html += buf;

    for (const auto& [lith, stats] : slice.clusters) {
        const LithologyEval eval =
            lithology_eval(lith, palette.text_secondary);
        std::snprintf(
            buf, sizeof(buf),
            "<tr><td style='padding: 8px; border-bottom: 1px solid %s; "
            "font-weight: bold;'>%s</td>"
            "<td style='padding: 8px; text-align: center; border-bottom: 1px "
            "solid %s;'>%lld</td>"
            "<td style='padding: 8px; text-align: center; border-bottom: 1px "
            "solid %s;'>%.1f ± %.1f</td>"
            "<td style='padding: 8px; text-align: center; border-bottom: 1px "
            "solid %s;'>%.0f ± %.0f</td>"
            "<td style='padding: 8px; text-align: center; border-bottom: 1px "
            "solid %s;'><span style='color: %s; font-weight: "
            "bold;'>%s</span></td></tr>",
            palette.border.c_str(), escape_html(lith).c_str(),
            palette.border.c_str(), stats.count, palette.border.c_str(),
            stats.mean_gr, stats.std_gr, palette.border.c_str(),
            stats.mean_ai, stats.std_ai, palette.border.c_str(),
            eval.color.c_str(), escape_html(eval.label).c_str());
        html += buf;
    }

    std::snprintf(
        buf, sizeof(buf),
        "</table>"
        "<h3 style='color: %s; border-bottom: 1px solid %s; padding-bottom: "
        "4px;'>✦ 储层识别与推断结论</h3>"
        "<div style='background: %s; border-left: 4px solid %s; padding: "
        "12px; border-radius: 6px; margin-top: 8px;'>"
        "<ul style='margin: 0; padding-left: 20px; color: %s; line-height: "
        "1.6;'>"
        "<li><b>岩性聚类</b>: 上表统计基于本井 GR/AI 分布；岩性聚类边界应"
        "结合实际数据范围（见上方表格）解读，而非固定的 GR/AI 数值门限。</li>"
        "<li><b>储层 / 盖层辨识</b>: 建议以本井砂岩与泥岩的 GR/AI 中位值作"
        "为相对参考，结合区域地质认识综合判断。</li>"
        "<li><b>流体替代敏感性</b>: 必要时可结合 RGB 频率融合切片等补充资"
        "料进一步区分含流体砂岩与致密泥岩。</li>"
        "</ul></div>",
        palette.primary.c_str(), palette.border.c_str(),
        palette.bg_search.c_str(), palette.primary.c_str(),
        palette.text_secondary.c_str());
    html += buf;
    return html;
}

}  // namespace pwb::ui_seqviz
