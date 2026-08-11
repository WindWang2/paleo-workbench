#include "scalar_grid_layer.hpp"

#include <stdexcept>
#include <utility>

#include "grid_render_core.hpp"

namespace pwb::grid_render {

namespace {
std::size_t cell_count(const int width, const int height) {
    if (width <= 0 || height <= 0) {
        throw std::invalid_argument("scalar grid dimensions must be positive");
    }
    return static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
}
}  // namespace

ScalarGridLayer::ScalarGridLayer(const int width, const int height,
                                 std::vector<float> grid_z,
                                 std::vector<std::uint8_t> mask)
    : width_(width), height_(height), grid_z_(std::move(grid_z)), mask_(std::move(mask)) {
    validate_grid_size(grid_z_);
    validate_mask_size(mask_);
}

void ScalarGridLayer::validate_grid_size(const std::vector<float>& grid_z) const {
    if (grid_z.size() != cell_count(width_, height_)) {
        throw std::invalid_argument("grid_z size must equal width * height");
    }
}

void ScalarGridLayer::validate_mask_size(const std::vector<std::uint8_t>& mask) const {
    if (!mask.empty() && mask.size() != cell_count(width_, height_)) {
        throw std::invalid_argument("mask size must equal width * height");
    }
}

void ScalarGridLayer::set_grid(std::vector<float> grid_z) {
    std::lock_guard<std::mutex> lock(mutex_);
    validate_grid_size(grid_z);
    if (grid_z_ == grid_z) return;
    grid_z_ = std::move(grid_z);
    invalidate_data();
}

void ScalarGridLayer::set_mask(std::vector<std::uint8_t> mask) {
    std::lock_guard<std::mutex> lock(mutex_);
    validate_mask_size(mask);
    if (mask_ == mask) return;
    mask_ = std::move(mask);
    invalidate_data();
}

void ScalarGridLayer::set_color_ramp(std::vector<std::uint8_t> rgba_lut) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (rgba_lut.empty() || rgba_lut.size() % 4 != 0) {
        throw std::invalid_argument("color ramp must contain one or more RGBA colours");
    }
    if (color_ramp_ == rgba_lut) return;
    color_ramp_ = std::move(rgba_lut);
    invalidate_style();
}

std::vector<std::uint8_t> ScalarGridLayer::color_ramp() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return color_ramp_;
}

void ScalarGridLayer::set_color_range(const float lo, const float hi) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (color_lo_ == lo && color_hi_ == hi) return;
    color_lo_ = lo;
    color_hi_ = hi;
    invalidate_style();
}

float ScalarGridLayer::color_lo() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return color_lo_;
}

float ScalarGridLayer::color_hi() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return color_hi_;
}

void ScalarGridLayer::set_gamma(const float gamma) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (gamma_ == gamma) return;
    gamma_ = gamma;
    invalidate_style();
}

float ScalarGridLayer::gamma() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return gamma_;
}

std::uint64_t ScalarGridLayer::data_revision() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_revision_;
}

std::uint64_t ScalarGridLayer::style_revision() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return style_revision_;
}

std::uint64_t ScalarGridLayer::rasterize_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return rasterize_count_;
}

std::vector<std::uint8_t> ScalarGridLayer::rasterize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (color_ramp_.empty()) {
        throw std::logic_error("a color ramp must be set before rasterizing a scalar grid");
    }
    if (cached_data_revision_ == data_revision_ && cached_style_revision_ == style_revision_) {
        return cached_rgba_;
    }
    cached_rgba_.resize(cell_count(width_, height_) * 4);
    render_grid_rgba(
        width_, height_, grid_z_.data(), mask_.empty() ? nullptr : mask_.data(),
        color_ramp_.data(), static_cast<int>(color_ramp_.size() / 4), color_lo_, color_hi_,
        gamma_, 255, cached_rgba_.data());
    cached_data_revision_ = data_revision_;
    cached_style_revision_ = style_revision_;
    ++rasterize_count_;
    return cached_rgba_;
}

}  // namespace pwb::grid_render
