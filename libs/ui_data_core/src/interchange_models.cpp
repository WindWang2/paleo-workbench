// interchange_models.py — Qt-free model data logic (see header for contract).

#include "pwb/ui_data_core/interchange_models.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// PreflightIssueModel
// ---------------------------------------------------------------------------

const std::unordered_map<std::string, std::string>& preflight_severity_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"error", "错误"},
        {"warning", "警告"},
        {"info", "提示"},
    };
    return map;
}

const std::unordered_map<std::string, int>& preflight_severity_order() {
    static const std::unordered_map<std::string, int> map = {
        {"error", 0},
        {"warning", 1},
        {"info", 2},
    };
    return map;
}

const std::array<std::string, 3>& preflight_issue_headers() {
    static const std::array<std::string, 3> headers = {"级别", "代码", "说明"};
    return headers;
}

PreflightIssueModelData preflight_issue_model_data(
    const std::vector<PreflightIssue>& issues, bool ok,
    const std::string& recommendation) {
    PreflightIssueModelData data;
    data.ok = ok;
    data.recommendation = recommendation;
    const auto& labels = preflight_severity_labels();
    const auto& order = preflight_severity_order();
    data.rows.reserve(issues.size());
    for (const auto& issue : issues) {
        const auto it = labels.find(issue.severity);
        data.rows.push_back({it != labels.end() ? it->second : issue.severity,
                             issue.code, issue.message});
    }
    // rows.sort(key=lambda r: _SEVERITY_ORDER.get(
    //     {v: k for k, v in _SEVERITY_LABELS.items()}.get(r[0], "info"), 9))
    // — the sort key walks BACK through the label map: an unlabeled
    // severity (label == raw severity text) resolves "info" → order 2, and
    // a raw severity that collides with a label (e.g. "错误") sorts as that
    // label's severity. Python sort is stable → std::stable_sort.
    static const std::unordered_map<std::string, std::string> reverse_labels = {
        {"错误", "error"},
        {"警告", "warning"},
        {"提示", "info"},
    };
    auto sort_key = [&order](const PreflightIssueRow& row) {
        const auto rit = reverse_labels.find(row[0]);
        const std::string severity =
            rit != reverse_labels.end() ? rit->second : std::string("info");
        const auto oit = order.find(severity);
        return oit != order.end() ? oit->second : 9;
    };
    std::stable_sort(data.rows.begin(), data.rows.end(),
                     [&sort_key](const PreflightIssueRow& a,
                                 const PreflightIssueRow& b) {
                         return sort_key(a) < sort_key(b);
                     });
    return data;
}

// ---------------------------------------------------------------------------
// BatchResultModel
// ---------------------------------------------------------------------------

const std::array<std::string, 6>& batch_result_headers() {
    static const std::array<std::string, 6> headers = {
        "源文件", "输出", "状态", "校验", "耗时(ms)", "说明",
    };
    return headers;
}

const std::unordered_map<std::string, std::string>& batch_status_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"converted", "已转换"},
        {"failed", "失败"},
        {"skipped", "跳过"},
        {"cancelled", "已取消"},
        {"pending", "等待"},
    };
    return map;
}

const std::array<std::string, 6>& batch_result_fields() {
    static const std::array<std::string, 6> fields = {
        "source", "target", "status", "verification_state",
        "duration_ms", "detail",
    };
    return fields;
}

namespace {

// row.get(field, "") — Json member or "" (empty string, not null).
const domain::Json* row_member_or_empty(const domain::Json& row,
                                        std::string_view field,
                                        const domain::Json*& empty_storage) {
    static const domain::Json empty_string("");
    empty_storage = &empty_string;
    if (row.is_object()) {
        const auto it = row.find(std::string(field));
        if (it != row.end()) {
            return &*it;
        }
    }
    return empty_storage;
}

}  // namespace

domain::Json batch_result_cell(const domain::Json& row, int column) {
    const auto& fields = batch_result_fields();
    if (column < 0 || column >= static_cast<int>(fields.size())) {
        return domain::Json(nullptr);
    }
    if (column == 2) {
        // _STATUS_LABELS.get(row["status"], row["status"]) — a missing key
        // raises in Python; null surfaces as the invalid cell here.
        if (!row.is_object()) {
            return domain::Json(nullptr);
        }
        const auto it = row.find("status");
        if (it == row.end()) {
            return domain::Json(nullptr);
        }
        const auto& labels = batch_status_labels();
        if (it->is_string()) {
            const auto lit = labels.find(it->get<std::string>());
            if (lit != labels.end()) {
                return domain::Json(lit->second);
            }
        }
        return *it;
    }
    if (column == 3) {
        // row.get("verification_state") or "—" — falsy → "—".
        const domain::Json* storage = nullptr;
        const domain::Json* value =
            row_member_or_empty(row, "verification_state", storage);
        return json_truthy(*value) ? *value : domain::Json("—");
    }
    const domain::Json* storage = nullptr;
    return *row_member_or_empty(row, fields[static_cast<std::size_t>(column)],
                                storage);
}

// ---------------------------------------------------------------------------
// PackagePlanModel
// ---------------------------------------------------------------------------

const std::array<std::string, 5>& package_plan_headers() {
    static const std::array<std::string, 5> headers = {
        "名称", "阶段", "状态", "大小(B)", "说明",
    };
    return headers;
}

const std::unordered_map<std::string, std::string>& package_status_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"included", "打包"},
        {"external", "外部引用"},
        {"missing", "缺失"},
        {"stale", "内容可疑"},
        {"excluded", "排除"},
    };
    return map;
}

domain::Json package_plan_cell(const PackagePlanItem& item, int column) {
    switch (column) {
        case 0:
            // Path(item.path).name — PurePosixPath basename semantics.
            return domain::Json(python_path_name(item.path));
        case 1:
            return domain::Json(item.stage);
        case 2: {
            const auto& labels = package_status_labels();
            const auto it = labels.find(item.status);
            return domain::Json(it != labels.end() ? it->second : item.status);
        }
        case 3:
            return domain::Json(item.size_bytes);
        case 4:
            return domain::Json(item.detail);
        default:
            return domain::Json(nullptr);
    }
}

}  // namespace pwb::ui_data_core
