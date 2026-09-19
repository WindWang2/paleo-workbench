// UI-06 — project overview panel model (project_overview_panel.py).
//
// 8 stat blocks + identity header + hints. counts=nullptr / integrity
// unknown ⇒ "—" placeholders — never fabricated zeros (C-P0-1).
#pragma once

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/filter_query.hpp>

namespace pwb::ui_pages_data {

// Duck-typed project seam (members the panel reads).
struct OverviewProject {
    std::string workarea_name;
    std::string meta_name;
    std::string region;
    std::string workarea_crs;                 // workarea.project_crs
    std::string coordinate_crs;               // coordinate.project_crs fallback
    std::vector<std::vector<double>> boundary;  // [[x,y],...]
    struct Well {
        std::string coordinate_status;
        std::optional<double> project_x;
        std::optional<double> project_y;
    };
    std::vector<Well> wells;
    int survey_count = 0;
    int unresolved_links = 0;
    struct Run {
        std::string name;
        std::string updated_at;   // string-compare like Python's max(key=updated_at)
    };
    std::vector<Run> compilation_runs;
};

struct OverviewView {
    std::string title;                       // "工区 · {name}"
    std::string meta;                        // "CRS: {crs|未设置}[　区域: {region}]"
    // Ordered stat blocks (Python `specs` order).
    std::vector<std::pair<std::string, std::string>> values;  // (key, display)
    std::vector<std::string> hints;
};

// counts_present mirrors ``counts is not None``; integrity_known mirrors
// ``counts.integrity_known`` (SQL aggregates lack integrity probing).
OverviewView compute_project_overview(
    const OverviewProject* project,          // nullptr → "未打开工程" meta
    const CatalogCounts* counts);            // nullptr → stage/issue stats "—"

}  // namespace pwb::ui_pages_data
