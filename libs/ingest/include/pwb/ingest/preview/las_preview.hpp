// LAS well-log preview core — the WLE-backed replacement for the frozen
// Python las_preview branch (resources/preview_parsers/well_log_parsers.py).
// The preview assembly (header scan classification, summary rows, curve
// table, data table formatting, warning composition) is Qt-free and
// SDK-free; the parsed LAS facts arrive through an injectable provider so
// builds without the WLE SDK degrade to an honest capability-unavailable
// message instead of a fabricated Python dependency error.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

// Parsed LAS facts the preview core consumes, mirroring
// geoviz_well_log.las_preview.LASPreviewHeader plus the sampled data rows.
struct LasPreviewData {
    enum class Status {
        ok,                 // header + data parsed
        no_curve_headers,   // Python ValueError("LAS contains no curve headers")
        parse_error,        // structural failure (WLE invalid_document etc.)
    };

    Status status = Status::ok;
    // Python exception-class label for parse_error results
    // ("LAS 预览失败: <label>" message parity).
    std::string parse_error_class;

    std::string well_name;  // ~W WELL. value; empty when absent
    bool wrapped = false;   // diagnostics only (data table is pre-resolved)

    struct Curve {
        std::string mnemonic;
        std::string unit;
        std::string description;
    };
    // ~C order, depth channel included (the Python curve table lists every
    // declared channel; the curve-count summary counts this list too).
    std::vector<Curve> curves;

    long long row_count = 0;  // accepted data rows (full file)

    // Data table source: the first kLasPreviewDataRows accepted rows in file
    // order, row-major, curves.size() columns; nulls already NaN. The depth
    // channel sits at its original ~C position like any other column.
    std::vector<double> values;
};

// Python well_log_parsers.las_preview caps the data table at 100 rows.
inline constexpr std::size_t kLasPreviewDataRows = 100;

// Parse provider: turns raw LAS bytes + path into LasPreviewData. Installed
// by the WLE bridge (production) or tests. A returned nullopt means the
// provider declined (unparseable input class) — the result is the
// parse-error message, uncached; "no provider installed" is handled
// separately by las_preview_result's capability-unavailable branch.
using LasPreviewProvider =
    std::function<std::optional<LasPreviewData>(const std::string& bytes,
                                                const std::string& path)>;

// Installs (or with nullptr clears) the process-wide parse provider. Not
// thread-safe against concurrent installs; call once during startup.
void set_las_preview_provider(LasPreviewProvider provider);

// True when a provider is installed (LAS preview capability available).
bool las_preview_provider_installed();

// Builds the .las preview result (mode="well_log"). With no provider the
// result is an honest capability-unavailable message. Mirrors
// well_log_parsers.las_preview: header-scan classification, summary rows
// (井名/曲线数/采样点), curve table truncated at settings.table_max_rows,
// data table (first kLasPreviewDataRows rows, "%.4f" trailing-zero
// trimming, NaN display), and warning composition.
PreviewResult las_preview_result(const ResourceRef& asset,
                                 const std::string& bytes,
                                 const PreviewSettings& settings);

// Formats one data-table cell the way the Python preview does: NaN -> "NaN",
// otherwise "%.4f" with trailing zeros (and a trailing dot) stripped.
std::string las_format_value(double value);

}  // namespace pwb::ingest::preview
