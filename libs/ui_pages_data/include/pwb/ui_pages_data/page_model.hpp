// UI-06 — data page pure helpers (data_page.py).
//
// The page is a 3154-line orchestrator; its Qt-free substance is the
// selection/context payload, status strings and enablement flags.
#pragma once

#include <string>
#include <vector>

#include <pwb/ui_pages_data/filter_query.hpp>

namespace pwb::ui_pages_data {

// _emit_data_context payload (data_context_changed dict).
struct DataContext {
    int resource_count = 0;
    int artifact_count = 0;
    int issue_count = 0;
    std::string selected_name = "未选择";
    std::string selected_type;
    std::string selected_format;
    std::string reader_mode;
};

// Issue statuses counted by the payload (verbatim set).
inline constexpr const char* kIssueStatuses[] = {
    "missing", "warning", "failed", "error"};

// Selection shape for the payload: kind + resolved display fields.
struct PageSelection {
    enum class Kind { None, Resource, Artifact, Other };
    Kind kind = Kind::None;
    std::string name;        // resource.name | basename(artifact.output_path)
    std::string type;        // resource.type | "成果"
    std::string format;
    std::string path;        // raw path for artifact basename resolution
};

// data_context_changed dict semantics:
//   selected_name: ResourceItem→name, ExportArtifact→basename(path), else "未选择"
//   selected_type: ResourceItem→type, ExportArtifact→"成果", else ""
//   selected_format: →format, else ""
DataContext build_data_context(int resource_count, int artifact_count,
                               int issue_count,
                               const PageSelection& selection,
                               const std::string& reader_mode);

// _update_selection_action_state enablement (verbatim):
//   rescan ⇐ has_resource && !selected_trashed && !import_in_progress
//   remove ⇐ has_asset && !selected_trashed      (has_asset = primary OR multi)
//   open_folder ⇐ has_asset
struct SelectionActionState {
    bool rescan_enabled = false;
    bool remove_enabled = false;
    bool open_folder_enabled = false;
};
SelectionActionState selection_action_state(bool has_resource, bool has_asset,
                                            bool selected_trashed,
                                            bool import_in_progress);

// Import status line (_set_import_status):
// "已归档 {added} · 重复路径 {skipped} · 警告 {warnings}"[+ " · 目录登记失败 {failures}"]
std::string import_status_line(int added, int skipped, int warnings,
                               int registration_failures);

// filter_index._parse_legacy_category (replicated leaf — UI-03's file,
// same dedup contract as qc_helpers.derive_rule_result; only vocab this
// library already owns is read). The page feeds it to the table's
// set_category seam — kept Qt-free so the oracle pins every branch:
//   ""|"全部"            → node_type "all"
//   "回收站"|"trash"|"Trash" → node_type "trash"
//   stage value|label|zh alias|UPPER → node_type "stage", value canonical
//   "tag:x"|"#x"        → node_type "tag" (split(":",1)[-1].lstrip("#"))
//   anything else       → node_type "legacy_category"
FilterQuery parse_legacy_category(const std::string& category,
                                  const std::string& search_text);

}  // namespace pwb::ui_pages_data
