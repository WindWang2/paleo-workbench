#include <pwb/ui_pages_preview/pdf_zoom.hpp>

#include <cmath>

namespace pwb::ui_pages_preview {

namespace {

// Python round() = round-half-to-even (banker's). std::nearbyint uses the
// default FP rounding mode, which is round-to-nearest-even.
int python_round(double value) {
    return static_cast<int>(std::nearbyint(value));
}

}  // namespace

int pdf_clamp_zoom(int percent) {
    return std::max(PDF_ZOOM_MIN, std::min(PDF_ZOOM_MAX, percent));
}

PdfZoomResult pdf_zoom_in(int percent) {
    const int next = pdf_clamp_zoom(python_round(percent * PDF_ZOOM_STEP));
    return {next, next != percent};
}

PdfZoomResult pdf_zoom_out(int percent) {
    const int next = pdf_clamp_zoom(python_round(percent / PDF_ZOOM_STEP));
    return {next, next != percent};
}

std::string pdf_page_status(int page, int page_count) {
    return std::to_string(page + 1) + " / " + std::to_string(page_count);
}

bool pdf_prev_enabled(int page) {
    return page > 0;
}

bool pdf_next_enabled(int page, int page_count) {
    return page < page_count - 1;
}

}  // namespace pwb::ui_pages_preview
