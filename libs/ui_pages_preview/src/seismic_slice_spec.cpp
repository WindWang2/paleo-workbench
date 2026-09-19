#include <pwb/ui_pages_preview/seismic_slice_spec.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::ui_pages_preview {

const std::vector<std::string>& seismic_axis_labels() {
    static const std::vector<std::string> labels = {
        "Inline (剖面)", "Crossline (剖面)", "Time (切片)",
    };
    return labels;
}

long long seismic_slider_max(long long axis_size) {
    return std::max<long long>(0, axis_size - 1);
}

long long seismic_slider_value(long long axis_size) {
    return std::max<long long>(0, seismic_slider_max(axis_size) / 2);
}

std::string seismic_index_label(long long value, long long max) {
    return std::to_string(value) + " / " + std::to_string(max);
}

SeismicRgba seismic_ramp(double t) {
    const double r = std::clamp(2.0 * t, 0.0, 1.0);
    const double b = std::clamp(2.0 * (1.0 - t), 0.0, 1.0);
    const double g = std::min(r, b);
    // Python int(ri * 255) — truncation toward zero, not rounding.
    return {
        static_cast<std::uint8_t>(r * 255.0),
        static_cast<std::uint8_t>(g * 255.0),
        static_cast<std::uint8_t>(b * 255.0),
        255,
    };
}

std::vector<std::uint32_t> seismic_color_table() {
    std::vector<std::uint32_t> table;
    table.reserve(256);
    for (int i = 0; i < 256; ++i) {
        // np.linspace(0,1,256): t = i/255.
        const auto c = seismic_ramp(static_cast<double>(i) / 255.0);
        table.push_back((static_cast<std::uint32_t>(c.a) << 24) |
                        (static_cast<std::uint32_t>(c.r) << 16) |
                        (static_cast<std::uint32_t>(c.g) << 8) |
                        static_cast<std::uint32_t>(c.b));
    }
    return table;
}

}  // namespace pwb::ui_pages_preview
