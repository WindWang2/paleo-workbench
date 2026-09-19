#pragma once

// UI-11 — relink_dialog.py Qt-free semantics: the status-column
// vocabulary, scan summary line, and the post-relink result message
// (成功 N 个，拒绝 N 个 + ≤8 reason lines + "… 共 N 条" overflow).
// Fail-closed contract lives in catalog::relink_external_source — this
// header only renders its outcomes.

#include "pwb/catalog/sources.hpp"

#include <string>
#include <vector>

namespace pwb::ui_review {

// _entry_status: relinkable → 可重链接; managed → 需重新导入; else
// 不支持重链接.
std::string relink_entry_status(const catalog::MissingSource& entry);

// Scan summary line:
//   empty      → "共扫描 {scanned} 个版本，未发现缺失源"
//   non-empty  → "共扫描 {scanned} 个版本，缺失 {entries} 个，
//                 其中可重链接（外部 RAW）{relinkable} 个"
std::string relink_scan_summary(int scanned, int entries, int relinkable);

// One relink outcome as Python's task() produces it.
struct RelinkBatchResult {
    int ok = 0;
    std::vector<std::string> reasons;  // "{asset_name}: {error text}"
    bool cancelled = false;
};

// _on_relink_finished message: "成功重链接 {ok} 个" plus, when reasons
// exist, "，拒绝 {n} 个（身份无法证明或发生错误）\n" + ≤8 reasons +
// "\n… 共 {n} 条" when more than 8.
std::string relink_result_message(const RelinkBatchResult& result);

}  // namespace pwb::ui_review
