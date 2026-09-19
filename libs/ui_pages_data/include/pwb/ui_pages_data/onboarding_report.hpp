// UI-06 — onboarding report card model (onboarding_report_card.py).
//
// The card renders a dict-shaped report (analyze_data_folder's report).
// Input stays Json to mirror the Python duck-typed dict exactly.
#pragma once

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

// One rendered label: text + visibility (the card hides empty sections).
struct ReportLabel {
    std::string text;
    bool visible = false;
};

// Frozen view of OnboardingReportCard.set_report(report).
struct OnboardingReportView {
    bool card_visible = false;
    ReportLabel source;          // "来源目录：{folder}"
    ReportLabel summary;         // "导入 N 项 · 井 N 口（N 有坐标） · 地震 N 个 · 地质实体 N 个"
    ReportLabel by_type;         // "{type} {n} · ..." sorted by count desc
    ReportLabel extent;          // "范围：[x,x] · [y,y]" or "无坐标井位范围"
    // issues + warnings combined, capped at 5 lines, warning tone.
    ReportLabel issues;
};

// Python semantics:
//  - falsy report → card hidden
//  - source = source_folder | intermediate_folder | ""
//  - by_type: "{k} {v}" joined by " · ", sorted by count desc
//  - extent: 4-numeric list → "[xmin, xmax] · [ymin, ymax]" at .1f,
//    anything else (incl. non-numeric) → "无坐标井位范围"
//  - issues+warnings: first 5 combined lines; hidden when empty
OnboardingReportView format_onboarding_report(const pwb::domain::Json& report);

// Shared summary line — the wizard's step-2 summary uses the identical
// f-string (new_project_wizard._on_analysis_finished).
std::string format_import_summary(int imported, int wells_total,
                                  int wells_with_coords, int surveys,
                                  int entities);

}  // namespace pwb::ui_pages_data
