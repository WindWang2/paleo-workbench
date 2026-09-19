// UI-06 — recent activity card model (activity_card.py :: update_state).
//
// Entries: non-pending steps → ("刚刚", "{STEP_LABEL}： {STATUS_TEXT}");
// when that yields nothing, an evidence fallback scans six counters.
// "暂无活动" shows when the final list is empty.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

// One step from home_workflow_steps: only step_type + status are read.
struct ActivityStep {
    std::string step_type;
    std::string status;
};

struct ActivityEntry {
    std::string when;          // "刚刚" for steps, "工程" for fallback
    std::string description;
};

// state = dashboard_state-shaped dict; steps = ordered step list.
// Fallback counters (in order): 数据资源/resource_counts (dict → sum, "N 项"),
// 单因素图/factor_map_count, 预测任务/prediction_count, 古地理图/map_document_count,
// 质检问题/qc_issue_count, 导出成果/export_count — int>0 each.
std::vector<ActivityEntry>
compute_activity_entries(const pwb::domain::Json& state,
                         const std::vector<ActivityStep>& steps);

}  // namespace pwb::ui_pages_data
