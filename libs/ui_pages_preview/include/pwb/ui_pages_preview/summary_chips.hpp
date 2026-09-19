#pragma once

// Port of the stat-chip update semantics in
// summary_table_preview_widget.py (UI-07) — Qt-free part.

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_pages_preview {

// Python f"{int(v):,}" — comma-grouped thousands ("1,234,567").
std::string thousands_grouped(long long value);

// Summary rows → chip values. Keys/values are .strip()ed (row_map parity).
// Chips are sticky: Python writes a chip only when its key appears in the
// rows, so each field is std::nullopt when the key is absent — callers
// must leave the existing label untouched in that case.
struct SummaryChipValues {
    std::optional<std::string> well;     // "井名" → raw value
    std::optional<std::string> curves;   // "曲线数" → "<v> 条"
    std::optional<std::string> samples;  // "采样点" → "<v or grouped int> 点"
};
SummaryChipValues summary_chip_values(
    const std::vector<std::pair<std::string, std::string>>& summary_rows);

}  // namespace pwb::ui_pages_preview
