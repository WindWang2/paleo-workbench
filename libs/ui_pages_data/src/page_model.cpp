// UI-06 — data_page pure helpers.
#include <pwb/ui_pages_data/page_model.hpp>

namespace pwb::ui_pages_data {
namespace {

// pathlib.Path(output_path).name — strips trailing slashes, last part.
std::string path_name(const std::string& path) {
    std::size_t end = path.size();
    while (end > 1 && path[end - 1] == '/') --end;
    const std::size_t slash = path.rfind('/', end - 1);
    if (slash == std::string::npos) return path.substr(0, end);
    return path.substr(slash + 1, end - slash - 1);
}

}  // namespace

DataContext build_data_context(int resource_count, int artifact_count,
                               int issue_count,
                               const PageSelection& selection,
                               const std::string& reader_mode) {
    DataContext ctx;
    ctx.resource_count = resource_count;
    ctx.artifact_count = artifact_count;
    ctx.issue_count = issue_count;
    ctx.reader_mode = reader_mode;
    switch (selection.kind) {
        case PageSelection::Kind::Resource:
            ctx.selected_name = selection.name;
            ctx.selected_type = selection.type;
            ctx.selected_format = selection.format;
            break;
        case PageSelection::Kind::Artifact:
            ctx.selected_name = path_name(selection.path);
            ctx.selected_type = "成果";
            ctx.selected_format = selection.format;
            break;
        default:
            break;  // "未选择" / "" defaults
    }
    return ctx;
}

SelectionActionState selection_action_state(bool has_resource,
                                            bool has_asset,
                                            bool selected_trashed,
                                            bool import_in_progress) {
    SelectionActionState state;
    state.rescan_enabled =
        has_resource && !selected_trashed && !import_in_progress;
    state.remove_enabled = has_asset && !selected_trashed;
    state.open_folder_enabled = has_asset;
    return state;
}

std::string import_status_line(int added, int skipped, int warnings,
                               int registration_failures) {
    std::string line = "已归档 " + std::to_string(added) + " · 重复路径 " +
                       std::to_string(skipped) + " · 警告 " +
                       std::to_string(warnings);
    if (registration_failures) {
        line += " · 目录登记失败 " + std::to_string(registration_failures);
    }
    return line;
}

}  // namespace pwb::ui_pages_data
