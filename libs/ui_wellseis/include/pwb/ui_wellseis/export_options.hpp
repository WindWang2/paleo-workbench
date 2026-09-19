#pragma once

// UI-09 — CrossWellExportDialog option model (Qt-free).
//
// Port of cross_well_export_dialog.py: format/dpi/width/page-size
// enablement rules and the resolved option dict:
//   dpi enabled        -> fmt in {png, pdf}
//   page_size enabled  -> fmt == "pdf"
//   width enabled      -> not (fmt == "pdf" and page_size is set)
//   options(): page_size only when fmt=="pdf"; page_size set -> width None.

#include <optional>
#include <string>

namespace pwb::ui_wellseis {

struct CrossWellExportOptions {
    std::string fmt = "svg";             // svg | png | pdf
    int dpi = 150;                       // 96 | 150 | 300 (combo order)
    int width_px = 0;                    // 0 = 自然宽度
    std::optional<std::string> page_size;  // A4 | LETTER | nullopt(内容尺寸)
};

struct CrossWellExportEnabled {
    bool dpi = false;
    bool width = false;
    bool page_size = false;
};

// _update_enabled parity.
CrossWellExportEnabled export_enabled(const CrossWellExportOptions& options);

// options() parity: resolved fmt/dpi/width_px/page_size — a set page size
// clears the width, and width 0 resolves to "natural" (nullopt).
struct ResolvedExportOptions {
    std::string fmt;
    int dpi = 150;
    std::optional<int> width_px;
    std::optional<std::string> page_size;
};
ResolvedExportOptions resolve_export_options(
    const CrossWellExportOptions& options);

}  // namespace pwb::ui_wellseis
