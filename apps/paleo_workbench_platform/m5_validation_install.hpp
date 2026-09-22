#pragma once

// M5 (ribbon five-workspaces, plan 00-plan.md §4-M5) — the validation
// workspace gaps install:
//
//   * ComparisonView (解释 vs 预测) into the 对比视图 tab — providers
//     bound to the LIVE project document (correlation_interpretations +
//     prediction_tasks + interpretation artifacts);
//   * ReviewDispositionPanel into the 复核记录 tab — record sink bound to
//     the closure_review document persistence (review_records ride the
//     existing quality_reports save/export path);
//   * the mode/link QAction group bound into the ribbon band
//     (set_command_action).
//
// Compiled where ClosureReview is linked (PWB_WITH_M5_VALIDATION gate);
// everywhere else the M3 placeholders stay — honest degradation.

class QMainWindow;

namespace pwb::app {

class AppShell;
class AppContext;

namespace m5_validation {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
};

// One install per window (idempotent on the shell). GUI thread only.
void install(const Install& install);

// Command availability surface (ribbon_command_include): how many real
// interpretation versions / completed-shaped prediction tasks the open
// project currently carries.
struct SourceCounts {
    int interpretations = 0;
    int predictions = 0;
};
SourceCounts source_counts(const AppContext* context);

// 时深标定 gate (F:75): true only when the document carries real
// calibration data for time-depth coupling. Integration point: the
// document "coordinate" section's "time_depth_calibrations" array — absent
// in today's product, so the link toggle stays disabled with its honest
// reason until a calibration source lands.
bool link_available(const AppContext* context);

}  // namespace m5_validation

}  // namespace pwb::app
