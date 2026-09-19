#pragma once

// UI-11 — catalog_health_dialog.py Qt-free semantics: severity
// ordering/labels/foreground tokens, the two-line summary
// (stats + verdict), and the audit-run status texts.

#include "pwb/catalog/audit.hpp"

#include <string>
#include <string_view>
#include <vector>

namespace pwb::ui_review {

// _SEVERITY_LABELS / _SEVERITY_TOKENS verbatim.
std::string_view audit_severity_label(std::string_view severity);  // 高|中|低|raw
// Foreground token name for ObjectTableModel::foreground_role
// (high→ERROR_RED, medium→WARNING, else none).
const char* audit_severity_token(std::string_view severity);

// severity sort key: ("high","medium","low").index(severity) — Python
// raises on unknown severities; C++ degrades them AFTER low (stable).
int audit_severity_rank(std::string_view severity);

// sorted(report.issues, key=rank) — stable (Python sorted is stable).
std::vector<catalog::AuditIssue>
audit_issues_sorted(const std::vector<catalog::AuditIssue>& issues);

// update_report summary line:
//   "资产 {a} · 版本 {v} · 运行 {r} · 标签 {t}　|　
//    问题 {n} 项: 高 {h} / 中 {m} / 低 {l}"
// (note: 全角 space 　 between the two halves).
std::string audit_summary_line(const catalog::AuditReport& report);

// The verdict half: "✅ 目录结构健康（低级别问题仅供参考）" when ok else
// "⚠️ 发现需要处理的健康问题". Caller joins with "\n".
std::string_view audit_verdict(bool ok);

// run_audit busy texts (progress + summary label share the same line).
std::string_view audit_busy_text(bool deep);

}  // namespace pwb::ui_review
