// UI-06 — home page pure helpers (home_page.py).
//
// Well picking + start-guide visibility. Map snapshot/canvas types are
// injected seams (mapping.workarea_map_snapshot is unported).
#pragma once

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

// Layer ids owned by the home map snapshot (workarea_map_snapshot.py).
inline constexpr std::string_view kWellsLayerId = "home_workarea:wells";
inline constexpr std::string_view kWellsFlaggedLayerId =
    "home_workarea:wells_flagged";

// 命中半径（屏幕像素）— HomePage._WELL_PICK_RADIUS_PX.
inline constexpr double kWellPickRadiusPx = 16.0;

// One well feature projected to screen space (the Qt side converts map
// coords via the canvas; the core only sees screen coords).
struct WellPickPoint {
    double x = 0, y = 0;
    std::string well_id;
};

// _on_map_clicked: nearest well point within `radius` of `click`
// (dist <= best_dist wins; ties keep the LATER point — Python's
// `if dist <= best_dist` overwrites). Returns "" when none qualifies.
// Python iterates WELLS then WELLS_FLAGGED layers — callers pass the
// merged point list in that same order.
std::string pick_well(const std::vector<WellPickPoint>& points,
                      double click_x, double click_y,
                      double radius = kWellPickRadiusPx);

// Start-guide visibility rule (update_state):
// show = (total_resources == 0 && !has_report).
bool start_guide_visible(long long total_resources, bool has_report);

// Side column visibility = guide_visible || report_visible.
inline bool side_column_visible(bool guide_visible, bool report_visible) {
    return guide_visible || report_visible;
}

// Sum a {type → count} dict like Python's
// `sum(int(v) for v in resource_counts.values())` wrapped in try/except:
// ANY non-integer-coercible value → total 0.
long long sum_resource_counts(const pwb::domain::Json& resource_counts);

}  // namespace pwb::ui_pages_data
