// UI-06 — data reader panel dispatch model (data_reader_panel.py).
//
// The mode→handler table and the _commit_result flag math are the panel's
// Qt-free substance. Preview widgets stay in the Qt shell / other slices.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// Preview mode vocabulary (PreviewResult.mode + the panel's own "loading").
// Handlers exist for exactly this set; anything else → "message" fallback
// (Python dict .get(mode) → default _render_message).
inline constexpr const char* kPreviewModes[] = {
    "empty",       "message", "text",   "table",  "well_log",
    "seismic",     "image",   "pdf",    "rich_text",
    "web_document","json_tree","geotiff","media",
};
// "geoviz" is handled OUTSIDE the dispatch table (LazyVisualizationTabs
// seam); "loading" is a panel-local mode. Both map to no widget here.
inline constexpr std::string_view kModeGeoviz = "geoviz";
inline constexpr std::string_view kModeLoading = "loading";

// The widget a mode commits to. Modes whose widgets are other slices'
// files map to their registered handler name — the Qt shell resolves
// names → widgets through the provider registry (native impls for
// empty/message/text/table/image; others → "message" fallback widget,
// matching Python's dict-.get default).
std::string_view preview_target(const std::string& mode);

// _commit_result flag math (Python verbatim):
//  - table toolbar visible ⇔ target is table_preview
//  - image toolbar visible ⇔ target is image_preview_widget
//  - warning merges table truncation when target is table_preview
struct CommitFlags {
    std::string target;        // resolved target name (preview_target)
    bool show_table_toolbar = false;
    bool show_image_toolbar = false;
};
CommitFlags preview_commit_flags(const std::string& mode);

// "正在生成预览…"/"加载中… {name}" title logic for show_loading:
// asset names are pre-resolved by the caller (ResourceItem→name,
// ExportArtifact→basename(output_path), none→"加载中…").
inline std::string loading_title(const std::string& resolved_name) {
    return resolved_name.empty() ? "加载中…" : "加载中… " + resolved_name;
}

// _merge_warning(existing, added): " · ".join(non-empty parts).
std::string merge_warning(const std::string& existing,
                          const std::string& added);

// _meta_text(result): " · ".join(non-empty of type_label, format,
// status, path).
std::string preview_meta_text(const std::string& type_label,
                              const std::string& format,
                              const std::string& status,
                              const std::string& path);

// visualization_available gating (render):
//   viz entry only when result.visualization_available AND mode ∉
//   {geoviz, seismic} — seismic renders through its own widget.
bool viz_entry_shown(bool visualization_available,
                     const std::string& mode);

}  // namespace pwb::ui_pages_data
