// UI-06 — resource readiness strip (resource_summary.py /
// completeness_card.py :: update_state).
//
// Both cards read state["resource_readiness"]:
//   {required_types, available_counts{type→n}, missing_types[], ready}
// resource_summary shows counts + one status line;
// completeness_card shows the same plus a per-type ready flag.
#pragma once

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

struct ReadinessRow {
    std::string type;
    std::string name_label;    // RESOURCE_LABELS[type]
    int count = 0;
    std::string count_label;   // "{count}{unit}"
    bool ready = false;        // count > 0 (completeness row tone)
    // completeness_card per-row status text: "已就绪" / "缺失".
    std::string status_label;
};

struct ResourceReadinessView {
    std::vector<ReadinessRow> rows;      // kRequiredResourceTypes order
    bool ready = false;
    // "数据完整" when ready, else "缺少: {label、label…}"
    std::string status_line;
    // tone key for the status line: "SUCCESS" when ready else "ERROR_RED"
    // (None/secondary while unbound — the cards start with a dash).
    std::string status_token = "TEXT_SECONDARY";
};

// Read the readiness slice of a dashboard_state-shaped dict.
// Missing/absent members behave like Python's .get(..., {}) defaults:
// empty counts → every required type missing → status "缺少: 全部三项".
ResourceReadinessView
format_resource_readiness(const pwb::domain::Json& state);

}  // namespace pwb::ui_pages_data
