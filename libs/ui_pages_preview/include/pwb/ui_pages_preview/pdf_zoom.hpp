#pragma once

// Port of paleo_workbench/ui/pages/pdf_preview_widget.py zoom/fit/page
// semantics (UI-07) — Qt-free part.

#include <string>

namespace pwb::ui_pages_preview {

inline constexpr int PDF_ZOOM_MIN = 10;    // _ZOOM_MIN (percent)
inline constexpr int PDF_ZOOM_MAX = 800;   // _ZOOM_MAX (percent)
inline constexpr double PDF_ZOOM_STEP = 1.25;

// _clamp_zoom.
int pdf_clamp_zoom(int percent);

// _zoom_in/_zoom_out: percent *|/ 1.25 rounded with Python round()
// (banker's rounding — round(12.5)=12), then clamped. `changed=false` when
// the step lands on the current value (already at the boundary).
struct PdfZoomResult {
    int percent;
    bool changed;
};
PdfZoomResult pdf_zoom_in(int percent);
PdfZoomResult pdf_zoom_out(int percent);

// Fit-mode vocabulary ("page" | "width" | "custom"). Zooming always leaves
// the fit modes for custom — the widget sets fit_mode="custom" itself.
inline constexpr const char* PDF_FIT_PAGE = "page";
inline constexpr const char* PDF_FIT_WIDTH = "width";
inline constexpr const char* PDF_FIT_CUSTOM = "custom";

// Page-status strings and nav enablement (0-based page internally,
// 1-based display).
std::string pdf_page_status(int page, int page_count);   // "n / m"
bool pdf_prev_enabled(int page);
bool pdf_next_enabled(int page, int page_count);

// copy_all_text truncation bound (1 MiB) — "已复制（已截断）" when hit.
inline constexpr int PDF_COPY_ALL_MAX_CHARS = 1'000'000;

}  // namespace pwb::ui_pages_preview
