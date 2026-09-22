#pragma once

// M5 (ribbon five-workspaces, plan 00-plan.md §4-M5) — 问题级人工复核
// 状态机 core (design F:72-80, Qt-free):
//
//   * 状态词汇: 通过 / 未通过 / 待复核 / 未执行 / 不适用 / 已过期 —
//     the original check verdict (pass/warning/error) is a DIFFERENT axis
//     and is NEVER rewritten by a review (复核 ≠ 通过);
//   * 复核备注必填 (accepting a difference without a reason is refused);
//   * records persist INSIDE the QualityReport Json (report
//     ["review_records"]) — they ride the existing document save and the
//     report export verbatim, and run_map_qc_on_document carries them
//     across its upsert so a re-run never silently drops human review
//     work (复核记录可重开和追溯);
//   * staleness: run_map_qc stamps report["input_fingerprint"] over the
//     exact inputs the rules consumed; when the current inputs hash
//     differently the report is 已过期 and the UI must prompt a re-run —
//     the old report stays until then (never auto-deleted, never
//     auto-passed).

#include <optional>
#include <string>
#include <vector>

#include "pwb/closure_review/review_qc_core.hpp"
#include "pwb/domain/json.hpp"

namespace pwb::closure_review {

enum class ReviewDisposition {
    Approved,       // 通过 — 人工结论：认可
    Rejected,       // 未通过 — 人工结论：不认可
    Pending,        // 待复核 — 尚无人工结论
    NotExecuted,    // 未执行 — 规则未评估（skipped，见 rule_status）
    NotApplicable,  // 不适用 — 人工判定该问题对本成果不适用
    Outdated,       // 已过期 — 输入版本已变化，结论仅作历史保留
};

const char* review_disposition_label(ReviewDisposition disposition);
std::optional<ReviewDisposition> review_disposition_from_string(
    const std::string& value);

struct ReviewRecord {
    std::string issue_key;     // review_issue_key(issue) — stable identity
    std::string rule;          // original rule id (snapshot)
    std::string severity;      // original check verdict snapshot — 永不改写
    ReviewDisposition disposition = ReviewDisposition::Pending;
    std::string reviewer_note;  // 必填 — accepting a difference needs a reason
    std::string author = "expert";
    std::string created_at;     // iso timestamp from the host
};

// Stable identity for one issue across report re-renders: rule plus the
// feature identity (feature_id, else ref, else message — a message fall-
// back keeps unlocated issues addressable, never dropping a review).
std::string review_issue_key(const domain::Json& issue);

// Validation problems (empty = recordable). The note is mandatory for
// every disposition that records a human conclusion.
std::vector<std::string> validate_review_record(const ReviewRecord& record);

domain::Json review_record_to_json(const ReviewRecord& record);
ReviewRecord review_record_from_json(const domain::Json& json);

// Attach into report["review_records"][issue_key]. Returns problems;
// on success the report's status/issues stay byte-identical (复核 ≠ 通过).
std::vector<std::string> attach_review_record(domain::Json& report,
                                              const ReviewRecord& record);

std::vector<ReviewRecord> review_records_of(const domain::Json& report);

// ---- staleness --------------------------------------------------------------

// Fingerprint over the exact inputs the QC collectors consume (the map
// document entry + the document sections the rules read + the extended
// inputs). Canonical (sorted-key) hashing — stable across reloads.
std::string qc_input_fingerprint(const domain::Json& root,
                                 const domain::Json& map_document,
                                 const QcInputs& inputs);

// True when the stamped fingerprint differs from the current inputs
// (input versions changed after the run). A report without a stamp
// cannot be judged — returns false, honest absence of evidence.
bool report_is_stale(const domain::Json& report,
                     const std::string& current_fingerprint);

}  // namespace pwb::closure_review
