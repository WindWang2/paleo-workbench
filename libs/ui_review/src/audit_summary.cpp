#include "pwb/ui_review/audit_summary.hpp"

#include <algorithm>

namespace pwb::ui_review {

std::string_view audit_severity_label(std::string_view severity) {
    if (severity == "high") return "高";
    if (severity == "medium") return "中";
    if (severity == "low") return "低";
    return severity;  // Python falls back to the raw severity string
}

const char* audit_severity_token(std::string_view severity) {
    if (severity == "high") return "ERROR_RED";
    if (severity == "medium") return "WARNING";
    return nullptr;
}

int audit_severity_rank(std::string_view severity) {
    if (severity == "high") return 0;
    if (severity == "medium") return 1;
    if (severity == "low") return 2;
    return 3;  // unknown → after low (Python would raise; UI degrades)
}

std::vector<catalog::AuditIssue>
audit_issues_sorted(const std::vector<catalog::AuditIssue>& issues) {
    std::vector<catalog::AuditIssue> sorted = issues;
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const catalog::AuditIssue& a,
                        const catalog::AuditIssue& b) {
                         return audit_severity_rank(a.severity) <
                                audit_severity_rank(b.severity);
                     });
    return sorted;
}

namespace {

int stat_at(const std::map<std::string, int>& map, const char* key) {
    const auto it = map.find(key);
    return it != map.end() ? it->second : 0;
}

}  // namespace

std::string audit_summary_line(const catalog::AuditReport& report) {
    const auto stats = report.statistics();
    return "资产 " + std::to_string(stat_at(report.checked, "assets")) +
           " · 版本 " + std::to_string(stat_at(report.checked, "versions")) +
           " · 运行 " + std::to_string(stat_at(report.checked, "runs")) +
           " · 标签 " + std::to_string(stat_at(report.checked, "tags")) +
           "　|　问题 " + std::to_string(report.issues.size()) + " 项: 高 " +
           std::to_string(stats.issues_high) + " / 中 " +
           std::to_string(stats.issues_medium) + " / 低 " +
           std::to_string(stats.issues_low);
}

std::string_view audit_verdict(bool ok) {
    return ok ? "✅ 目录结构健康（低级别问题仅供参考）"
              : "⚠️ 发现需要处理的健康问题";
}

std::string_view audit_busy_text(bool deep) {
    return deep ? "正在深度检查全部数据校验和..."
                : "正在检查目录结构与数据完整性...";
}

}  // namespace pwb::ui_review
