#pragma once

// UI-09 — WellTablePanel cell formatting + QC summary (Qt-free).
//
// Ports:
//   well_table_panel.py::_fmt         — Python "%.4g" / "%.4f"+rstrip cell text
//   _QC_TOKENS                        — qc_flag -> palette token name
//   update_from_well_table            — title parts + "N 行 · ok:n …" summary
//
// The 11-column spec (name/x/y/z/Hs/Ht/Rs/q/b/QC/z*) is the fixed schema —
// the Qt model consumes kWellTableColumns verbatim.

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// Python _fmt: None -> ""; non-numeric -> str(value);
// |f|>=1000 or 0<|f|<0.001 -> "%.4g"; else "%.4f" with trailing-zero strip.
std::string well_table_fmt(std::optional<double> value,
                           const std::string& raw_when_non_numeric = "");

// qc_flag -> foreground token name; unknown flags get no override.
// ok -> SUCCESS, outlier -> WARNING, invalid_ratio -> ERROR_RED,
// missing -> TEXT_SECONDARY.
std::optional<std::string> qc_foreground_token(const std::string& qc_flag);

// _qc_flag(row) parity: empty -> "ok".
std::string normalized_qc_flag(const std::string& qc_flag);

// "name · horizon · factor_type" (trailing parts only when non-empty).
std::string well_table_title(const WellTableSlice& table);

// "N 行" + per-flag " · flag:count" for the four known flags, in order.
std::string well_table_summary(const WellTableSlice& table);

// The 11-column schema (key, header title) — verbatim order.
struct WellTableColumn {
    const char* key;
    const char* title;
};
extern const std::vector<WellTableColumn> kWellTableColumns;

// Cell text for one column (the model's DisplayRole value).
std::string well_table_cell(const WellTableRowSlice& row,
                            const std::string& column_key);

}  // namespace pwb::ui_wellseis
