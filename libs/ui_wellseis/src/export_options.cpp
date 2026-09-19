#include <pwb/ui_wellseis/export_options.hpp>

namespace pwb::ui_wellseis {

CrossWellExportEnabled export_enabled(const CrossWellExportOptions& options) {
    const bool is_pdf = options.fmt == "pdf";
    const bool is_png = options.fmt == "png";
    CrossWellExportEnabled enabled;
    enabled.dpi = is_pdf || is_png;
    enabled.page_size = is_pdf;
    enabled.width = !(is_pdf && options.page_size.has_value());
    return enabled;
}

ResolvedExportOptions resolve_export_options(
    const CrossWellExportOptions& options) {
    ResolvedExportOptions resolved;
    resolved.fmt = options.fmt;
    resolved.dpi = options.dpi;
    if (options.fmt == "pdf" && options.page_size.has_value()) {
        resolved.page_size = options.page_size;
    }
    if (resolved.page_size.has_value() || options.width_px <= 0) {
        resolved.width_px = std::nullopt;
    } else {
        resolved.width_px = options.width_px;
    }
    return resolved;
}

}  // namespace pwb::ui_wellseis
