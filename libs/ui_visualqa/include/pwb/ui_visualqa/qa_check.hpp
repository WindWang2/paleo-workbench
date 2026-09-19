#pragma once

// UI-16 — shared visual-QA check vocabulary.
//
// Port of paleo_workbench/ui/visual_qa_v6.py's CheckResult dataclass +
// checks_payload sidecar JSON — the single check currency every V6..V11
// state/scenario check returns. The harness writes the payload next to
// each screenshot (non-gating; gate assertions live in the test suites —
// D8 policy parity). Qt-free.

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_visualqa {

// One semantic check result (Python CheckResult parity: ok=False is a
// warning in the harness, a failure in the gate tests).
struct CheckResult {
    std::string name;
    bool ok = false;
    std::string detail;
};

// Python _check parity — bool() coercion of the verdict.
CheckResult make_check(std::string name, bool ok,
                       std::string detail = "");

// Python checks_payload parity: {"state_ok": all|None, "checks": [...]}.
// An empty result set freezes state_ok=null (Python `if results else None`).
pwb::domain::Json checks_payload(const std::vector<CheckResult>& results);

// all(r.ok for r in results) — false on empty (callers gate on size first).
bool all_ok(const std::vector<CheckResult>& results);

// Names of failed checks (test diagnostics parity).
std::vector<std::string> failed_names(
    const std::vector<CheckResult>& results);

}  // namespace pwb::ui_visualqa
