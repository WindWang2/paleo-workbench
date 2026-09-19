#pragma once

// UI-09 — inference run diagnostic + persisted-failure replay (Qt-free).
//
// Ports well_log_prediction_page.py:
//   _write_run_diagnostic — the user-copyable credential-safe log
//   _restore_latest_failed_online_run — newest failed online run for the
//     selected resource (workflow filter + resource-id membership + max
//     created_at); error defaults to "未知错误"
// Status labels passed in verbatim by callers: 推断中 / 失败 / 完成 /
// 异常中断 / 失败（历史运行）.

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// The workflow tags that count as "online well-log facies" runs.
extern const std::vector<std::string> kOnlineWellLogWorkflows;

// Newest persisted failed online run mentioning resource_id, or nullptr.
const RunSlice* latest_failed_online_run(const std::vector<RunSlice>& runs,
                                         const std::string& resource_id);

// parameters.error fallback ("未知错误").
std::string run_error_text(const RunSlice& run);

// _write_run_diagnostic parity — the assembled credential-safe log text.
// `status` is the caller-supplied label; `error` passes through
// redact_diagnostic_text. run may be nullptr (异常中断 before run creation).
std::string run_diagnostic_log(const RunSlice* run,
                               const std::string& status,
                               const std::string& error,
                               const ResourceSlice* resource);

}  // namespace pwb::ui_wellseis
