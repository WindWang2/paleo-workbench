#pragma once

// Port of paleo_workbench/ui/pages/seismic_slice_preview_widget.py spec
// (UI-07) — Qt-free part: axis vocabulary, slider geometry, the
// blue→white→red indexed color ramp and the render debounce constant.

#include <cstdint>
#include <string>
#include <vector>

namespace pwb::ui_pages_preview {

inline constexpr int SEISMIC_RENDER_DEBOUNCE_MS = 16;  // QTimer interval

// Axis combo labels — ["Inline (剖面)", "Crossline (剖面)", "Time (切片)"].
// Combo index == volume axis index (0=inline, 1=crossline, 2=time/sample).
const std::vector<std::string>& seismic_axis_labels();

// _update_slider_range: maximum = max(0, axis_size − 1).
long long seismic_slider_max(long long axis_size);
// Initial value: max(0, max_val // 2) — the midpoint slice.
long long seismic_slider_value(long long axis_size);

// index label: "v / max".
std::string seismic_index_label(long long value, long long max);

// Blue → white → red ramp (white at t=0.5): r=clip(2t), b=clip(2(1−t)),
// g=min(r,b) — then ×255. Used for the 256-entry Indexed8 color table.
struct SeismicRgba {
    std::uint8_t r, g, b, a;
};
SeismicRgba seismic_ramp(double t);
// qRgba-packed table, 256 entries (matches QImage::setColorTable layout —
// 0xAARRGGBB on little-endian).
std::vector<std::uint32_t> seismic_color_table();

}  // namespace pwb::ui_pages_preview
