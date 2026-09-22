#pragma once

// UI-11 — qc_issue_table.py Qt-free semantics: the 4-column row spec
// (检查项目 / 检查说明 / 结果说明 / 定位) built from one QC report.
//
// Result text/color reuse the UI-03 port
// ``pwb::ui_data_core::derive_rule_result`` — no second copy of the
// severity table. spatial_issues is the trivial geometry/centroid filter
// (workflow.qc parity — 5 lines of predicate, not the QC engine).

#include "pwb/domain/json.hpp"

#include <map>
#include <string>
#include <vector>

namespace pwb::ui_review {

struct QcIssueRow {
    std::string rule;          // col 0 — 检查项目
    std::string description;   // col 1 — 检查说明 (RULE_DESCRIPTIONS fallback rule)
    std::string severity;      // pass | warning | error
    std::string result_text;   // col 2 — 结果说明
    std::string result_color;  // col 2 foreground hex
    std::string location;      // col 3 — 定位 (feature_id/ref/(+N)/可定位/—)
};

// workflow.qc.spatial_issues parity: issues carrying geometry or centroid
// (truthy) — locatable on a map.
std::vector<domain::Json>
spatial_issues_of(const domain::Json& issues);

// The _spatial_by_rule grouping Python builds per report.
std::map<std::string, std::vector<domain::Json>>
spatial_issues_by_rule(const domain::Json& issues);

// Rows for one report: ``rules`` (report.rules array of strings) ×
// ``issues`` (report.issues array of objects). The loc column reads the
// rule's first spatial issue (feature_id else ref else 可定位, with
// "(+N-1)" when more spatial rows exist); rules without spatial issues → "—".
std::vector<QcIssueRow> qc_issue_rows(const domain::Json& rules,
                                      const domain::Json& issues);

// M5 stable review identity for one issue: rule + feature identity
// (feature_id, else ref, else message). Canonical definition — both the
// closure_review persistence (review_disposition::review_issue_key) and
// the validation page build the key through here so a review record can
// never drift from the issue it addresses.
std::string qc_issue_key(const domain::Json& issue);

}  // namespace pwb::ui_review
