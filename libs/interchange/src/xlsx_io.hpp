#pragma once

// Bounded OOXML (.xlsx) grid read/write for the exporters converters —
// pandas read_excel/to_excel semantic parity for the PLAIN TABLE subset:
// first worksheet, header row, typed cells (number / inline or shared
// string / bool). Styles, formulas, merged cells and multiple sheets are
// out of scope (converters never produce them; reading a workbook that
// uses them surfaces an honest error, not silent misparsing).

#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::interchange::xlsx {

// One sheet grid: header row + data rows. Cells are JSON values
// (number / string / bool / null) — the pandas value vocabulary.
struct Table {
    std::string sheet_name;
    std::vector<std::string> columns;  // mangled headers (a, a.1 dupes)
    std::vector<std::vector<domain::Json>> rows;
};

// Read the FIRST worksheet of an xlsx container. Throws std::runtime_error
// on structural failure (bad zip, missing sheet, malformed XML).
Table read_xlsx(const std::filesystem::path& file);

// Write a one-sheet workbook. `index` (when non-null) prepends an index
// column — pandas to_excel(index=True) parity: corner cell carries the
// index name (empty → blank). Column order = columns.
void write_xlsx(const std::filesystem::path& file,
                const std::vector<std::string>& columns,
                const std::vector<std::vector<domain::Json>>& rows,
                const std::optional<std::string>& index_name = std::nullopt,
                const std::optional<std::vector<domain::Json>>& index_values =
                    std::nullopt,
                const std::string& sheet_name = "Sheet1");

}  // namespace pwb::interchange::xlsx
