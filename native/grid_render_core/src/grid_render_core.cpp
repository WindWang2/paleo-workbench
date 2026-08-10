// grid_render_core.cpp — implementation of the native scalar-grid rasteriser.
#include "grid_render_core.hpp"

#include <cmath>

namespace pwb::grid_render {

void render_grid_rgba(const int width, const int height,
                      const float* grid_z,
                      const std::uint8_t* mask,
                      const std::uint8_t* lut,
                      const int lut_size,
                      const float lo, const float hi,
                      float gamma,
                      std::uint8_t opacity,
                      std::uint8_t* out) noexcept {
    if (width <= 0 || height <= 0 || lut_size < 1 || !grid_z || !lut || !out) {
        return;
    }
    if (!(gamma > 0.0f)) {
        gamma = 1.0f;  // safe default; pow(0, <=0) is undefined
    }
    const float denom = hi - lo;
    const bool have_range = denom > 0.0f;
    const float inv_denom = have_range ? (1.0f / denom) : 0.0f;
    const int max_idx = lut_size - 1;

    const std::size_t n = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    for (std::size_t i = 0; i < n; ++i) {
        std::uint8_t* px = out + i * 4;
        const float v = grid_z[i];
        if (!std::isfinite(v) || (mask != nullptr && mask[i] == 0)) {
            px[0] = px[1] = px[2] = 0;
            px[3] = 0;  // nodata / masked -> fully transparent
            continue;
        }
        float t = have_range ? (v - lo) * inv_denom : 0.0f;
        if (t < 0.0f) t = 0.0f;
        else if (t > 1.0f) t = 1.0f;
        if (gamma != 1.0f) {
            t = std::pow(t, gamma);
        }
        int idx = static_cast<int>(t * static_cast<float>(max_idx));  // truncation
        if (idx < 0) idx = 0;
        else if (idx > max_idx) idx = max_idx;
        const std::uint8_t* c = lut + idx * 4;
        px[0] = c[0];
        px[1] = c[1];
        px[2] = c[2];
        px[3] = static_cast<std::uint8_t>((static_cast<int>(c[3]) * opacity) / 255);
    }
}

}  // namespace pwb::grid_render
