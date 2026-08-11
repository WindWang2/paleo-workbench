// scalar_grid_layer.hpp — native-owned grid payload, style, and raster cache.
//
// `LayerRegistry` owns metadata/order/visibility. This class owns only the scalar grid
// payload and colour style consumed by the native raster hot path. Keeping those roles
// separate prevents UI style changes from invoking scientific interpolation.
#pragma once

#include <cstdint>
#include <vector>

namespace pwb::grid_render {

class ScalarGridLayer {
public:
    ScalarGridLayer(int width, int height, std::vector<float> grid_z,
                    std::vector<std::uint8_t> mask = {});

    int width() const noexcept { return width_; }
    int height() const noexcept { return height_; }

    void set_grid(std::vector<float> grid_z);
    void set_mask(std::vector<std::uint8_t> mask);

    // RGBA LUT bytes, one or more colours. The input must have a length divisible by 4.
    void set_color_ramp(std::vector<std::uint8_t> rgba_lut);
    const std::vector<std::uint8_t>& color_ramp() const noexcept { return color_ramp_; }

    void set_color_range(float lo, float hi);
    float color_lo() const noexcept { return color_lo_; }
    float color_hi() const noexcept { return color_hi_; }
    void set_gamma(float gamma);
    float gamma() const noexcept { return gamma_; }

    std::uint64_t data_revision() const noexcept { return data_revision_; }
    std::uint64_t style_revision() const noexcept { return style_revision_; }
    std::uint64_t rasterize_count() const noexcept { return rasterize_count_; }

    // Lazily rasterize into a native cache and return the cached RGBA bytes.
    const std::vector<std::uint8_t>& rasterize();

private:
    void invalidate_data() noexcept { ++data_revision_; }
    void invalidate_style() noexcept { ++style_revision_; }
    void validate_grid_size(const std::vector<float>& grid_z) const;
    void validate_mask_size(const std::vector<std::uint8_t>& mask) const;

    int width_ = 0;
    int height_ = 0;
    std::vector<float> grid_z_;
    std::vector<std::uint8_t> mask_;
    std::vector<std::uint8_t> color_ramp_;
    float color_lo_ = 0.0f;
    float color_hi_ = 1.0f;
    float gamma_ = 1.0f;
    std::uint64_t data_revision_ = 1;
    std::uint64_t style_revision_ = 1;
    std::uint64_t cached_data_revision_ = 0;
    std::uint64_t cached_style_revision_ = 0;
    std::uint64_t rasterize_count_ = 0;
    std::vector<std::uint8_t> cached_rgba_;
};

}  // namespace pwb::grid_render
