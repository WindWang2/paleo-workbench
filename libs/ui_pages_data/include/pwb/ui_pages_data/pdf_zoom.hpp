// UI-06 — PDF preview zoom model (data_detail_panel.py :: PdfPreviewPanel).
//
// Render size = base 420×560 × factor; step ×1.25; clamp [0.10, 8.00].
#pragma once

#include <string>

namespace pwb::ui_pages_data {

class PdfZoomModel {
public:
    static constexpr double kBaseWidth = 420.0;
    static constexpr double kBaseHeight = 560.0;
    static constexpr double kZoomStep = 1.25;
    static constexpr double kMinFactor = 0.10;
    static constexpr double kMaxFactor = 8.00;

    double factor() const { return factor_; }
    // Returns false when the clamped value is unchanged (Python early-
    // return re-renders only the label, not the page).
    bool set_factor(double factor);
    bool zoom_in() { return set_factor(factor_ * kZoomStep); }
    bool zoom_out() { return set_factor(factor_ / kZoomStep); }
    // Ctrl+wheel path: delta > 0 zooms in, < 0 out (Python leaves 0
    // untouched — callers guard before invoking).
    bool wheel(int delta_y) { return delta_y > 0 ? zoom_in() : zoom_out(); }

    // Page navigation (document seam: page_count supplied by QPdfDocument).
    int page_index() const { return page_index_; }
    // Returns false at the boundary (no re-render), like Python's guards.
    bool next_page(int page_count);
    bool previous_page();

    int render_width() const;    // max(1, int(round(420 × factor)))
    int render_height() const;   // max(1, int(round(560 × factor)))
    // "{int(round(factor*100))}%" — Python int(round()) = banker's rounding.
    std::string zoom_label() const;
    // "{page_index + 1} / {page_count}" — "1 / 0" when document is null.
    std::string page_label(int page_count) const;

private:
    double factor_ = 1.0;
    int page_index_ = 0;
};

}  // namespace pwb::ui_pages_data
