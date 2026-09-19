#pragma once

// UI-10 — Qt-free state core for curve_operation_dialog.py (L3 toolbox).
//
// The dialog's parameter editors are schema rows produced here; the
// kernels + registry live in well_science (curve_operations() metadata,
// missing_interval_report). Save semantics stay in the host's
// apply_curve_operation seam — this core only validates + formats.
// The RAW payload is never touched: every save produces a NEW DERIVED
// catalog version.

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/well_science/curve_ops.hpp>

namespace pwb::ui_seqviz {

// _OPERATION_LABELS verbatim (op id → Chinese label), in dict order.
const std::vector<std::pair<std::string, std::string>>& operation_labels();

// operation_combo entries: labels filtered to registered CURVE_OPERATIONS.
std::vector<std::pair<std::string, std::string>> operation_combo_entries();

// OPERATION_SCOPE lookup ("depth_axis"|"curve"|"file"|"derive"; "curve"
// default for unknown ops — Python dict.get fallback).
std::string operation_scope(const std::string& op);

// _rebuild_parameter_rows curve-edit state: file-scope ops disable the
// curve field (except derive_curve) and switch the tooltip.
struct CurveFieldState {
    bool enabled = true;
    std::string tooltip;
};
CurveFieldState curve_field_state(const std::string& op);

// ---------------------------------------------------------------------------
// Parameter row descriptors (_parameter_rows)
// ---------------------------------------------------------------------------

enum class ParamEditorKind {
    Spin,    // QDoubleSpinBox (value, decimals, min, max, suffix)
    Combo,   // QComboBox with (label, data) choices
    Line,    // QLineEdit (initial text)
    Hint,    // QLabel — skipped by _collect_parameters
};

struct ParamRowDesc {
    std::string label;
    std::string name;
    ParamEditorKind kind = ParamEditorKind::Line;
    // Spin
    double value = 0.0;
    int decimals = 3;
    double minimum = -1e6, maximum = 1e6;
    std::string suffix;
    // Combo: (label, data) pairs in order.
    std::vector<std::pair<std::string, std::string>> choices;
    // Line initial text / Hint text.
    std::string text;
};

// _parameter_rows(op) — the exact descriptor list per op (empty for
// unregistered ops). The "白名单对" hint row is included as Hint kind.
std::vector<ParamRowDesc> parameter_rows(const std::string& op);

// _collect_parameters — (name → editor value) map → Json params; "_hint"
// rows skipped. Values: double for Spin, string for Combo(currentData)/
// Line(text().strip()).
using ParamValue = std::variant<double, std::string>;
domain::Json collect_parameters(
    const std::vector<ParamRowDesc>& rows,
    const std::map<std::string, ParamValue>& values);

// ---------------------------------------------------------------------------
// Missing-interval diagnostics (_run_diagnostics)
// ---------------------------------------------------------------------------

// The LAS-read seam — returns (depth, values) for `curve` or an error
// string (Python: "曲线 {curve!r} 不在该文件中。" / "读取失败: {exc}").
struct CurveReadResult {
    bool ok = false;
    std::vector<double> depth;
    std::vector<double> values;
    std::string error;        // the dialog warning text when !ok
    std::size_t curve_count = 0;
};
using CurveReadFn =
    std::function<CurveReadResult(const std::string& version_id,
                                  const std::string& curve)>;

// The assembled information-dialog body (missing_interval_report → the
// four-line report + the "缺口区间" preview or 无 text).
std::string missing_interval_dialog_text(
    const std::string& curve,
    const well_science::MissingIntervalReport& report,
    std::size_t depth_size);

// Run the diagnostic: curve fallback "GR" when blank; read seam → report.
struct DiagnosticsOutcome {
    bool ok = false;
    std::string title;    // "缺失区间诊断"
    std::string body;     // information text or warning text
    bool is_error = false;
};
DiagnosticsOutcome run_diagnostics(const CurveReadFn& read_fn,
                                   const std::string& version_id,
                                   const std::string& curve_text);

// ---------------------------------------------------------------------------
// apply_curve_operation result formatting (run_curve_operation_dialog)
// ---------------------------------------------------------------------------

// The success information text — "已生成派生版本（{op}）\n输入版本: X…\n
// 输出版本: Y…\nRun: Z…" (18-char prefixes verbatim).
std::string derived_version_success_text(const std::string& operation,
                                         const std::string& input_version_id,
                                         const std::string& output_version_id,
                                         const std::string& run_id);

// The failure warning — "操作失败: {exc}".
std::string derived_version_failure_text(const std::string& exc_message);

}  // namespace pwb::ui_seqviz
