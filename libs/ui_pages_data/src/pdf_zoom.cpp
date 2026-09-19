// UI-06 — PdfPreviewPanel zoom/page model (data_detail_panel.py).
#include <pwb/ui_pages_data/pdf_zoom.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::ui_pages_data {
namespace {

// Python's int(round(x)): round() is banker's rounding (round-half-even);
// std::nearbyint with the default FP rounding mode matches.
long long py_round(double x) {
    return static_cast<long long>(std::nearbyint(x));
}

}  // namespace

bool PdfZoomModel::set_factor(double factor) {
    const double clamped =
        std::max(kMinFactor, std::min(kMaxFactor, factor));
    // Python: abs(clamped - factor) < 1e-9 → label refresh only.
    if (std::abs(clamped - factor_) < 1e-9) return false;
    factor_ = clamped;
    return true;
}

bool PdfZoomModel::next_page(int page_count) {
    if (page_index_ < page_count - 1) {
        ++page_index_;
        return true;
    }
    return false;
}

bool PdfZoomModel::previous_page() {
    if (page_index_ > 0) {
        --page_index_;
        return true;
    }
    return false;
}

int PdfZoomModel::render_width() const {
    return std::max(1, static_cast<int>(py_round(kBaseWidth * factor_)));
}

int PdfZoomModel::render_height() const {
    return std::max(1, static_cast<int>(py_round(kBaseHeight * factor_)));
}

std::string PdfZoomModel::zoom_label() const {
    const long long percent = py_round(factor_ * 100.0);
    return std::to_string(percent) + "%";
}

std::string PdfZoomModel::page_label(int page_count) const {
    return std::to_string(page_index_ + 1) + " / " +
           std::to_string(page_count);
}

}  // namespace pwb::ui_pages_data
