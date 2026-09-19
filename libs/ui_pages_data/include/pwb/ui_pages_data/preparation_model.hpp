// UI-06 — preparation page model (preparation_page.py).
//
// The display-table resolution and the summary/status strings are the
// page's Qt-free substance; panels and scientific backends are seams.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// Duck-typed task seam (factor_map_tasks items): only `parameters` is
// read — specifically whether it carries a non-empty "sample_points".
struct PrepTaskView {
    bool has_sample_points = false;
};

// _resolve_display_well_table: prefer project.well_tables[0]; else the
// first factor task that carries sample_points (its index; the backend
// converts it via well_table_from_factor_task). Kind::None → no table.
struct DisplayTableChoice {
    enum class Kind { None, Project, Task } kind = Kind::None;
    int task_index = -1;
};
// has_project_tables mirrors `bool(project.well_tables)`; tasks carry
// their position implicitly (vector order = task list order).
DisplayTableChoice
resolve_display_well_table(bool has_project_tables,
                           const std::vector<PrepTaskView>& tasks);

// Summary strings (task_panel.summary_label text), verbatim:
//  - progress: "制备中：复用 {clean} · 需计算 {dirty} · 已完成 {completed}/{total}"[+ " · {msg}"]
//  - done:     "已制备 {complete} / {total} 个单因素图 · 复用 {clean} · 计算 {executed}"[+ " · 丢弃过期 {discarded}"]
//  - starting: "制备中… 任务 {n} · 生成代 {generation}"
//  - failed:   "单因素图生成失败：{message}"
//  - cancelled:"单因素图生成已取消"
//  - contour empty: "等值线初稿：没有可提取的单因素网格，请先「批量生成单因素图」。"
//  - contour done:  "等值线初稿：已生成 {n} 份并推送到编图。"
//  - contour fail:  "等值线初稿失败：{message}"
std::string prepare_start_label(int task_count, int generation);
std::string prepare_progress_label(int clean, int dirty, int completed,
                                   int total, const std::string& message);
std::string prepare_done_label(int complete, int total, int clean,
                               int executed, int discarded);
std::string prepare_failed_label(const std::string& message);
// _on_prepare_cancelled summary text — a constant in Python.
inline constexpr std::string_view kPrepareCancelledLabel =
    "单因素图生成已取消";
std::string contour_done_label(int draft_count);
std::string contour_failed_label(const std::string& message);
std::string contour_empty_label();

// QC completion message (QMessageBox.information text):
// "完成：ok={ok} outlier={outlier} invalid_ratio={invalid_ratio} missing={missing}"
// [+ "\n注意：没有绑定该井表的任务，清洗结果未写回任何任务。" when linked==0]
std::string well_qc_message(int ok, int outlier, int invalid_ratio,
                            int missing, bool linked_any);

}  // namespace pwb::ui_pages_data
