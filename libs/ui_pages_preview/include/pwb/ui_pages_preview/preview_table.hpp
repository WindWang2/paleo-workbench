#pragma once

// Port of paleo_workbench/ui/pages/table_preview_widget.py semantics (UI-07)
// — Qt-free part: number detection, depth/curve-def column classification,
// cell-truncation math and the TSV export contract. The QTableView/model
// shell lives in qt/table_preview_*.

#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_pages_preview {

// MAX_PREVIEW_CELLS parity — defensive bound only (the virtualized model
// removed per-cell allocation; the cap guards pathological parser output).
inline constexpr long long MAX_PREVIEW_CELLS = 1'000'000;

// _AUTO_FIT_SAMPLE_ROWS parity — column auto-fit samples only this many
// leading rows (Qt's resizeColumnsToContents would walk every row).
inline constexpr int AUTO_FIT_SAMPLE_ROWS = 400;

// _is_number: "NaN" or Python float()-parseable. Python grammar differences
// from strtod are handled inside (underscore digit separators allowed;
// hex/bin/oct prefixes rejected; ASCII whitespace stripped).
bool is_number(const std::string& value);

// str(raw).strip() parity — both data() and row_text() strip cell text
// (ASCII whitespace: space \t \n \r \f \v).
std::string table_cell_text(const std::string& raw);

// _DEPTH_HEADERS = {"DEPT", "DEPTH", "深度"} matched on header.upper().
// Returns the first matching column index, or -1.
int depth_column(const std::vector<std::string>& headers);

// Curve-definition table: >= 3 headers and headers[0] in {"曲线","Mnemonic"}.
bool is_curve_definition(const std::vector<std::string>& headers);

// load_table truncation math: visible rows kept + the truncation message.
struct TableTruncation {
    std::size_t keep_rows = 0;
    bool truncated = false;
    std::string message;  // "" when !truncated
};
TableTruncation table_truncation(std::size_t rows, std::size_t cols);

// copy_all() TSV: header line + one line per row, \t-joined cells, \n-joined
// lines. Rows are padded to the header count with "" (row_text parity).
std::string table_to_tsv(const std::vector<std::string>& headers,
                         const std::vector<std::vector<std::string>>& rows);

// data() role-branch order compressed to a single classification — the Qt
// model maps each kind to font/alignment/foreground/background answers.
enum class CellKind {
    depth,       // mono-bold + themed fg/bg + right
    curve_tag,   // mono-bold + teal fg + bg + center  (curve-def col 0)
    curve_unit,  // mono + secondary fg + center       (curve-def col 1)
    nan_number,  // mono + disabled fg + right
    number,      // mono + right
    plain,
};
CellKind cell_kind(const std::string& text, int column, int depth_col,
                   bool curve_def);

}  // namespace pwb::ui_pages_preview
