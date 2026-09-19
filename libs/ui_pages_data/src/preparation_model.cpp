// UI-06 — preparation_page display-table resolution + summary labels.
#include <pwb/ui_pages_data/preparation_model.hpp>

namespace pwb::ui_pages_data {

DisplayTableChoice
resolve_display_well_table(bool has_project_tables,
                           const std::vector<PrepTaskView>& tasks) {
    // Python: tables = project.well_tables or []; if tables → tables[0];
    // else first task whose parameters.sample_points is non-empty.
    if (has_project_tables) return {DisplayTableChoice::Kind::Project, -1};
    for (int i = 0; i < static_cast<int>(tasks.size()); ++i) {
        if (tasks[i].has_sample_points)
            return {DisplayTableChoice::Kind::Task, i};
    }
    return {};
}

std::string prepare_start_label(int task_count, int generation) {
    return "制备中… 任务 " + std::to_string(task_count) + " · 生成代 " +
           std::to_string(generation);
}

std::string prepare_progress_label(int clean, int dirty, int completed,
                                   int total, const std::string& message) {
    std::string label = "制备中：复用 " + std::to_string(clean) +
                        " · 需计算 " + std::to_string(dirty) +
                        " · 已完成 " + std::to_string(completed) + "/" +
                        std::to_string(total);
    if (!message.empty()) label += " · " + message;
    return label;
}

std::string prepare_done_label(int complete, int total, int clean,
                               int executed, int discarded) {
    std::string label = "已制备 " + std::to_string(complete) + " / " +
                        std::to_string(total) + " 个单因素图" +
                        " · 复用 " + std::to_string(clean) + " · 计算 " +
                        std::to_string(executed);
    if (discarded) label += " · 丢弃过期 " + std::to_string(discarded);
    return label;
}

std::string prepare_failed_label(const std::string& message) {
    return "单因素图生成失败：" + message;
}

std::string contour_done_label(int draft_count) {
    return "等值线初稿：已生成 " + std::to_string(draft_count) +
           " 份并推送到编图。";
}

std::string contour_failed_label(const std::string& message) {
    return "等值线初稿失败：" + message;
}

std::string contour_empty_label() {
    return "等值线初稿：没有可提取的单因素网格，请先「批量生成单因素图」。";
}

std::string well_qc_message(int ok, int outlier, int invalid_ratio,
                            int missing, bool linked_any) {
    std::string msg = "完成：ok=" + std::to_string(ok) +
                      " outlier=" + std::to_string(outlier) +
                      " invalid_ratio=" + std::to_string(invalid_ratio) +
                      " missing=" + std::to_string(missing);
    if (!linked_any) {
        msg += "\n注意：没有绑定该井表的任务，清洗结果未写回任何任务。";
    }
    return msg;
}

}  // namespace pwb::ui_pages_data
