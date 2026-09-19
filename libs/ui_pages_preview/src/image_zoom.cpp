#include <pwb/ui_pages_preview/image_zoom.hpp>

#include <algorithm>

namespace pwb::ui_pages_preview {

double image_zoom_clamp(double factor) {
    return std::max(IMAGE_ZOOM_MIN, std::min(IMAGE_ZOOM_MAX, factor));
}

std::pair<int, int> image_virtual_size(int pix_w, int pix_h, double zoom) {
    // Null pixmap → Python returns (0, 0) before the max(1, ...) clamps.
    if (pix_w <= 0 || pix_h <= 0) return {0, 0};
    const int pw = std::max(1, static_cast<int>(pix_w * zoom));
    const int ph = std::max(1, static_cast<int>(pix_h * zoom));
    return {pw, ph};
}

PanOffset image_clamp_pan(int offset_x, int offset_y, int pix_w, int pix_h,
                          double zoom, int widget_w, int widget_h) {
    const auto [pw, ph] = image_virtual_size(pix_w, pix_h, zoom);
    if (pw <= 0) return {0, 0};  // Python early-returns QPoint(0, 0)
    int ww = widget_w <= 0 ? 240 : widget_w;  // Python fallback before layout
    int wh = widget_h <= 0 ? 180 : widget_h;
    PanOffset out;
    if (pw <= ww) {
        out.x = 0;
    } else {
        const int max_off = (pw - ww) / 2;
        out.x = std::max(-max_off, std::min(max_off, offset_x));
    }
    if (ph <= wh) {
        out.y = 0;
    } else {
        const int max_off = (ph - wh) / 2;
        out.y = std::max(-max_off, std::min(max_off, offset_y));
    }
    return out;
}

}  // namespace pwb::ui_pages_preview
