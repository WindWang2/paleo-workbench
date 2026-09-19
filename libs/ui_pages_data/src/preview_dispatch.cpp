// UI-06 — data_reader_panel dispatch/commit helpers.
#include <pwb/ui_pages_data/preview_dispatch.hpp>

namespace pwb::ui_pages_data {

std::string_view preview_target(const std::string& mode) {
    // _mode_handlers → the widget each renderer returns. Unknown modes
    // take the dict-.get default (_render_message → message_label).
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"empty", "empty_label"},
        {"message", "message_label"},
        {"text", "text_preview"},
        {"table", "table_preview"},
        {"well_log", "well_log_preview"},
        {"seismic", "seismic_preview"},
        {"image", "image_preview_widget"},
        {"pdf", "pdf_preview_widget"},
        {"rich_text", "rich_text_preview"},
        {"web_document", "web_document_preview"},
        {"json_tree", "json_tree_preview"},
        {"geotiff", "geotiff_preview"},
        {"media", "media_preview"},
        // BEGIN VIZ-E — chart/surface preview modes (plan V6): the targets
        // are the viz_charts hosts registered by the viz_e assembly.
        {"xy_scatter", "xy_scatter_chart"},
        {"surface", "surface_chart"},
        // END VIZ-E
    };
    for (const auto& [k, v] : kMap)
        if (k == mode) return v;
    return "message_label";
}

CommitFlags preview_commit_flags(const std::string& mode) {
    CommitFlags flags;
    flags.target = std::string(preview_target(mode));
    flags.show_table_toolbar = flags.target == "table_preview";
    flags.show_image_toolbar = flags.target == "image_preview_widget";
    return flags;
}

std::string merge_warning(const std::string& existing,
                          const std::string& added) {
    // " · ".join(part for part in (existing, added) if part).
    if (existing.empty()) return added;
    if (added.empty()) return existing;
    return existing + " · " + added;
}

std::string preview_meta_text(const std::string& type_label,
                              const std::string& format,
                              const std::string& status,
                              const std::string& path) {
    std::string out;
    for (const auto* part : {&type_label, &format, &status, &path}) {
        if (part->empty()) continue;
        if (!out.empty()) out += " · ";
        out += *part;
    }
    return out;
}

bool viz_entry_shown(bool visualization_available,
                     const std::string& mode) {
    // `result.visualization_available and result.mode != "geoviz" and
    // result.mode != "seismic"`.
    return visualization_available && mode != "geoviz" && mode != "seismic";
}

}  // namespace pwb::ui_pages_data
