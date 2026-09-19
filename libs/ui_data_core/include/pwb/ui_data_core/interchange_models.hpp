// interchange_models.py port — the Qt-free row/cell logic behind the three
// I19 table models (PreflightIssueModel / BatchResultModel /
// PackagePlanModel). Qt shells wrap these structures verbatim.
#pragma once

#include "pwb/domain/json.hpp"

#include <array>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// PreflightIssueModel — issues of one preflight report, worst first
// ---------------------------------------------------------------------------

// issue.severity / issue.code / issue.message (interchange contracts).
struct PreflightIssue {
    std::string severity;
    std::string code;
    std::string message;
};

// One DisplayRole row: (severity_label, code, message).
using PreflightIssueRow = std::array<std::string, 3>;

struct PreflightIssueModelData {
    std::vector<PreflightIssueRow> rows;
    bool ok = true;
    std::string recommendation;
};

// _SEVERITY_LABELS / _SEVERITY_ORDER / _HEADERS.
const std::unordered_map<std::string, std::string>& preflight_severity_labels();
const std::unordered_map<std::string, int>& preflight_severity_order();
const std::array<std::string, 3>& preflight_issue_headers();

// set_report: build rows (severity label → code → message), then stable-sort
// by the order recovered through the LABEL reverse map (unknown severities
// sort as "info" — the Python roundtrip is preserved verbatim).
PreflightIssueModelData preflight_issue_model_data(
    const std::vector<PreflightIssue>& issues, bool ok,
    const std::string& recommendation);

// ---------------------------------------------------------------------------
// BatchResultModel — per-item outcomes of a batch conversion
// ---------------------------------------------------------------------------

const std::array<std::string, 6>& batch_result_headers();
const std::unordered_map<std::string, std::string>& batch_status_labels();
// ("source","target","status","verification_state","duration_ms","detail")
const std::array<std::string, 6>& batch_result_fields();

struct BatchResultModelData {
    std::vector<domain::Json> rows;   // r.to_dict() per result item
    domain::Json summary = domain::Json::object();
};

// data(index, DisplayRole) — Json cell: null → QVariant-invalid upstream.
// col2 → status label; col3 → verification_state or "—" (falsy → "—");
// other cols → raw dict.get(field, "") value.
domain::Json batch_result_cell(const domain::Json& row, int column);

// ---------------------------------------------------------------------------
// PackagePlanModel — what a package build includes/excludes
// ---------------------------------------------------------------------------

const std::array<std::string, 5>& package_plan_headers();
const std::unordered_map<std::string, std::string>& package_status_labels();

// plan.items entry (interchange PackagePlan item fields).
struct PackagePlanItem {
    std::string path;
    std::string stage;
    std::string status;
    long long size_bytes = 0;
    std::string detail;
};

struct PackagePlanModelData {
    std::vector<PackagePlanItem> items;
    domain::Json summary = domain::Json::object();
};

// data(index, DisplayRole): Path(path).name | stage | status label |
// size_bytes | detail.
domain::Json package_plan_cell(const PackagePlanItem& item, int column);

}  // namespace pwb::ui_data_core
