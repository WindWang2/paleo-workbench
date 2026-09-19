// UI-06 — new project wizard model (new_project_wizard.py).
//
// Step-1 validation returns the exact error string or "" for ok.
// Filesystem probes are injected as bools so the rule order — which IS the
// Python semantics — stays Qt-free and oracle-testable.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

// Inputs as the dialog collects them; existence probes pre-evaluated.
struct WizardStep1Input {
    std::string name;                    // _name_edit.text().strip()
    std::string data_dir_text;           // _data_dir_edit.text().strip()
    bool data_dir_exists = false;        // Path(text).exists() && is_dir()
    bool same_dir = false;               // _same_dir_check.isChecked()
    std::string intermediate_text;
    bool intermediate_exists = false;
    bool target_exists = false;          // (inter|data)/"{name}.paleo.json"
};

// Validation order (exact Python):
//  1. 请输入工程名称        — empty name
//  2. 请选择原始数据文件夹   — empty data dir text
//  3. 数据目录不存在        — !exists
//  4. 请选择中间文件目录     — !same_dir && empty intermediate text
//  5. 中间目录不存在        — !same_dir && !exists
//  6. 工程文件已存在        — target exists
// Returns "" when valid.
std::string validate_step1(const WizardStep1Input& in);

// Step-2 state machine values.
namespace wizard_state {
inline constexpr std::string_view kIdle = "idle";
inline constexpr std::string_view kRunning = "running";
inline constexpr std::string_view kSuccess = "success";
inline constexpr std::string_view kFailed = "failed";
}  // namespace wizard_state

// The analysis-finished summary + inventory + issues rendering
// (_on_analysis_finished). Report dict like the onboarding card.
struct WizardReportView {
    std::string summary;                                  // format_import_summary
    std::vector<std::pair<std::string, int>> inventory;   // by_type items
    // str(v) text per inventory row — Python renders QTableWidgetItem(str(v))
    // so a bool shows "True" where the int would lose it.
    std::vector<std::string> inventory_text;
    // issues + warnings combined, capped at 20 lines (Python [:20]).
    std::vector<std::string> issue_lines;
    bool issues_visible = false;
};
WizardReportView format_wizard_report(const pwb::domain::Json& report,
                                      int imported_fallback);

}  // namespace pwb::ui_pages_data
