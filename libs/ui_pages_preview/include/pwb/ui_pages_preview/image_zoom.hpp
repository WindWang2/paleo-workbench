#pragma once

// Port of paleo_workbench/ui/pages/image_preview_widget.py zoom/pan geometry
// (UI-07) — Qt-free part. Decode bounds and debounce timing live as
// constants for the widget.

#include <utility>

namespace pwb::ui_pages_preview {

inline constexpr int IMAGE_PREVIEW_MAX_LONG_SIDE = 2048;  // _PREVIEW_MAX_LONG_SIDE
inline constexpr int IMAGE_RESIZE_DEBOUNCE_MS = 80;       // _RESIZE_DEBOUNCE_MS
inline constexpr double IMAGE_ZOOM_STEP = 1.25;
inline constexpr double IMAGE_ZOOM_MIN = 0.1;
inline constexpr double IMAGE_ZOOM_MAX = 8.0;

// set_zoom_factor clamp: max(min(factor, MAX), MIN) then float — no rounding.
double image_zoom_clamp(double factor);

// _virtual_size: (max(1, int(w*zoom)), max(1, int(h*zoom))) — Python int()
// truncation toward zero (positive → floor).
std::pair<int, int> image_virtual_size(int pix_w, int pix_h, double zoom);

// _clamp_pan: centers when the virtual image fits the viewport, otherwise
// clamps the offset to ±(virtual − viewport)//2 per axis.
struct PanOffset {
    int x = 0;
    int y = 0;
};
PanOffset image_clamp_pan(int offset_x, int offset_y, int pix_w, int pix_h,
                          double zoom, int widget_w, int widget_h);

}  // namespace pwb::ui_pages_preview
