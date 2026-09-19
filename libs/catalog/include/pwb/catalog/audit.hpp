// Lightweight catalog audit (conv-31; catalog/audit.py parity).
//
// Structural consistency checks over the canonical document + storage
// layout — detection ONLY, nothing is auto-repaired (the verify_integrity /
// plan_gc policy). Covers the 17 detection classes of audit.py with the
// same severities and detail texts; deep mode adds payload re-hashing
// (integrity_mismatch). The cooperative cancel contract (#1056) stops the
// audit between payload checks and reports cancelled=true with a PARTIAL
// issue list.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"

#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

namespace fs = std::filesystem;

inline constexpr std::string_view kSeverityHigh = "high";
inline constexpr std::string_view kSeverityMedium = "medium";
inline constexpr std::string_view kSeverityLow = "low";

// A run still "running" after this window is almost certainly a crashed
// producer (STALE_RUN_AFTER_SECONDS = 24h).
inline constexpr int kStaleRunAfterSeconds = 24 * 3600;

struct AuditIssue {
    std::string kind;
    std::string severity;
    std::string ref_id;
    std::string detail;
};

struct AuditStats {
    std::map<std::string, int> checked;
    int issues_high = 0;
    int issues_medium = 0;
    int issues_low = 0;
    std::map<std::string, int> by_kind;
};

struct AuditReport {
    std::vector<AuditIssue> issues;
    std::map<std::string, int> checked;
    bool cancelled = false;

    std::vector<AuditIssue> by_kind(std::string_view kind) const;
    std::vector<AuditIssue> by_severity(std::string_view severity) const;
    std::map<std::string, int> counts_by_kind() const;
    AuditStats statistics() const;
    bool ok() const;  // no high/medium issues (low = informational)
};

// Payload resolution seam: Python went through service.resolve_path (the
// full relocation ladder); the audit only stats the result. Defaults to
// the first rung (project-join / absolute / naive join).
struct AuditContext {
    const CatalogDocument* document = nullptr;
    const DocumentIndex* index = nullptr;
    fs::path project_path;  // the .paleo.json file
    std::function<std::filesystem::path(const DataVersion&)> resolve_path;
};

AuditReport audit_catalog(const AuditContext& context, bool deep = false,
                          std::optional<int> stale_run_after_seconds = std::nullopt,
                          const std::function<bool()>& cancel = nullptr);

}  // namespace pwb::catalog
