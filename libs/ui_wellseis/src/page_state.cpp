#include <pwb/ui_wellseis/page_state.hpp>

#include <algorithm>
#include <cctype>

namespace pwb::ui_wellseis {

std::string engine_unavailable_text(const std::string& engine_label,
                                    const std::string& error) {
    return engine_label + "不可用: " + (error.empty() ? "unknown" : error);
}

std::string well_log_backend_label(const std::string& backend) {
    if (backend == kWellLogBackendEngine) {
        return "WellLogEngine";
    }
    return "Legacy (QPainter)";
}

bool well_log_engine_env_enabled(const std::string& env_value) {
    std::string value = env_value;
    for (char& c : value) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    // welllog_engine_env_enabled: default ON; _FALSEY selects Legacy.
    return !(value == "0" || value == "false" || value == "no" ||
             value == "off" || value == "legacy");
}

std::optional<std::string> well_log_export_block_reason(
    const std::string& backend, const std::string& format_label) {
    if (backend != kWellLogBackendEngine || format_label == "PNG") {
        return std::nullopt;
    }
    return std::string(
        "WellLogEngine 路径暂仅支持 PNG 抓屏导出；请切换到 Legacy 导出 "
        "SVG/PDF");
}

bool seismic_controls_enabled(bool has_task) {
    return has_task;
}

WellMapCounts well_map_counts(const std::vector<WellSlice>& wells) {
    WellMapCounts counts;
    for (const WellSlice& well : wells) {
        const std::string scope =
            well.spatial_scope.empty() ? "workarea" : well.spatial_scope;
        if (scope == "reference") {
            ++counts.reference;
        } else {
            ++counts.workarea;
        }
    }
    return counts;
}

std::string well_map_counts_text(const WellMapCounts& counts) {
    // well_map_panel.py: "N 口测区井 · M 口参考井" when reference wells
    // exist, "N 口井" otherwise, "" when the work area is empty.
    if (counts.reference > 0) {
        return std::to_string(counts.workarea) + " 口测区井 · " +
               std::to_string(counts.reference) + " 口参考井";
    }
    if (counts.workarea > 0) {
        return std::to_string(counts.workarea) + " 口井";
    }
    return "";
}

}  // namespace pwb::ui_wellseis
