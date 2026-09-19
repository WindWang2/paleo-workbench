#pragma once

// UI-11 — ai_check_advisor_dialog.py Qt-free semantics: the deterministic
// HTML report body (summary table + issue lists + rule-based suggestions).
// The dialog takes two duck-typed dicts; the core keeps the same shape as
// domain::Json:
//
//   bh_report:    {"issues": [{"type","borehole","message"}...],
//                  "checked_boreholes": int}
//   fault_report: {"issues": [{"faults": [name...],"message"}...],
//                  "checked_faults": int}
//
// Token colors are compile-time literals (ui_review/tokens.hpp) — the HTML
// is a frozen surface; theme switching re-generates it, it never restyles.

#include "pwb/domain/json.hpp"

#include <string>

namespace pwb::ui_review {

std::string build_advisor_html(const domain::Json& bh_report,
                               const domain::Json& fault_report);

}  // namespace pwb::ui_review
