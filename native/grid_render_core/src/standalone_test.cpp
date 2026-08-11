// standalone_test.cpp — numeric verification of grid_render_core with plain g++.
//
// Build & run (no Python / pybind11 needed):
//   g++ -std=c++20 -O2 -Wall -Wextra grid_render_core.cpp standalone_test.cpp -o grid_render_selftest
//   ./grid_render_selftest
//
// Asserts byte-identical golden pixels for: ramp normalisation, out-of-range clamping,
// nodata transparency, mask transparency, opacity alpha multiply, gamma, and the
// hi<=lo / gamma<=0 defensive defaults. The pure-Python parity fallback must match.
#include "grid_render_core.hpp"
#include "scalar_grid_layer.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {
using pwb::grid_render::render_grid_rgba;

int g_failures = 0;

#define CHECK_EQ(actual, expected, msg)                                        \
    do {                                                                       \
        if ((actual) != (expected)) {                                          \
            std::printf("[FAIL] %s: line %d: got %d, want %d\n", (msg), __LINE__, \
                        static_cast<int>(actual), static_cast<int>(expected)); \
            ++g_failures;                                                      \
        }                                                                      \
    } while (0)

// Build a 256-entry grayscale LUT (lut[i] = i for R,G,B; A = 255).
std::vector<std::uint8_t> gray_lut(int alpha = 255) {
    std::vector<std::uint8_t> lut(256 * 4, 0);
    for (int i = 0; i < 256; ++i) {
        lut[i * 4 + 0] = static_cast<std::uint8_t>(i);
        lut[i * 4 + 1] = static_cast<std::uint8_t>(i);
        lut[i * 4 + 2] = static_cast<std::uint8_t>(i);
        lut[i * 4 + 3] = static_cast<std::uint8_t>(alpha);
    }
    return lut;
}

struct RGBA { std::uint8_t r, g, b, a; };

RGBA px(const std::vector<std::uint8_t>& buf, int x, int y, int w) {
    const int i = (y * w + x) * 4;
    return {buf[i], buf[i + 1], buf[i + 2], buf[i + 3]};
}

void test_basic_ramp_and_clamp() {
    const int w = 1, h = 5;
    const float grid[w * h] = {0.0f, 0.25f, 0.5f, 1.0f, 2.0f};  // last is above hi
    const float below = -1.0f;
    // Separate run for the below-lo case (single pixel).
    auto lut = gray_lut();
    std::vector<std::uint8_t> out(w * h * 4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, 1.0f, 255, out.data());
    CHECK_EQ(px(out, 0, 0, w).r, 0, "v=0 -> idx0 R");
    CHECK_EQ(px(out, 0, 0, w).a, 255, "v=0 alpha");
    // v=0.25 -> int(0.25*255) = 63
    CHECK_EQ(px(out, 0, 1, w).r, 63, "v=0.25 -> idx63");
    // v=0.5 -> int(0.5*255) = 127
    CHECK_EQ(px(out, 0, 2, w).r, 127, "v=0.5 -> idx127");
    // v=1.0 -> idx255 -> 255
    CHECK_EQ(px(out, 0, 3, w).r, 255, "v=1 -> idx255");
    // v=2.0 (above hi) clamps to t=1 -> idx255 -> 255
    CHECK_EQ(px(out, 0, 4, w).r, 255, "v>hi clamps to top");

    std::vector<std::uint8_t> out2(w * 1 * 4, 0);
    render_grid_rgba(w, 1, &below, nullptr, lut.data(), 256, 0.0f, 1.0f, 1.0f, 255, out2.data());
    CHECK_EQ(px(out2, 0, 0, w).r, 0, "v<lo clamps to bottom");
}

void test_nodata_and_mask() {
    const int w = 2, h = 1;
    const float nanf = std::nanf("");
    const float grid[w * h] = {nanf, 0.5f};
    const std::uint8_t mask[w * h] = {1, 0};  // second pixel masked out
    auto lut = gray_lut();
    std::vector<std::uint8_t> out(w * h * 4, 0);
    render_grid_rgba(w, h, grid, mask, lut.data(), 256, 0.0f, 1.0f, 1.0f, 255, out.data());
    // NaN -> transparent
    CHECK_EQ(px(out, 0, 0, w).a, 0, "nodata alpha 0");
    CHECK_EQ(px(out, 0, 0, w).r, 0, "nodata RGB 0");
    // masked valid pixel -> transparent
    CHECK_EQ(px(out, 1, 0, w).a, 0, "masked alpha 0");

    // nullptr mask == all valid: the 0.5 pixel must render.
    std::vector<std::uint8_t> out3(w * h * 4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, 1.0f, 255, out3.data());
    CHECK_EQ(px(out3, 1, 0, w).r, 127, "nullptr mask renders valid pixel");
    CHECK_EQ(px(out3, 1, 0, w).a, 255, "nullptr mask valid alpha");
}

void test_opacity_alpha_multiply() {
    const int w = 1, h = 1;
    const float grid[1] = {1.0f};
    auto lut = gray_lut();  // alpha 255
    std::vector<std::uint8_t> out(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, 1.0f, 128, out.data());
    CHECK_EQ(out[3], 128, "opacity 128 -> alpha 128 (255*128/255)");

    // LUT alpha 51, opacity 5 -> (51*5)/255 = 255/255 = 1 (integer division)
    auto lut2 = gray_lut(51);
    std::vector<std::uint8_t> out2(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut2.data(), 256, 0.0f, 1.0f, 1.0f, 5, out2.data());
    CHECK_EQ(out2[3], 1, "alpha 51 * opacity 5 / 255 = 1");
}

void test_gamma() {
    const int w = 1, h = 1;
    const float grid[1] = {0.5f};
    auto lut = gray_lut();
    // gamma 2: t=0.5 -> 0.25 -> int(0.25*255) = 63
    std::vector<std::uint8_t> out(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, 2.0f, 255, out.data());
    CHECK_EQ(out[0], 63, "gamma=2 v=0.5 -> 63");

    // gamma 0.5: t=0.5 -> sqrt(0.5)=0.7071 -> int(0.7071*255)=180
    std::vector<std::uint8_t> out2(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, 0.5f, 255, out2.data());
    CHECK_EQ(out2[0], 180, "gamma=0.5 v=0.5 -> 180");

    // gamma <= 0 falls back to 1.0: v=0.5 -> idx 127
    std::vector<std::uint8_t> out3(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 0.0f, 1.0f, -1.0f, 255, out3.data());
    CHECK_EQ(out3[0], 127, "gamma<=0 treated as 1.0");
}

void test_degenerate_range() {
    const int w = 1, h = 1;
    const float grid[1] = {5.0f};
    auto lut = gray_lut();
    // hi == lo -> t = 0 -> idx 0 -> black
    std::vector<std::uint8_t> out(4, 0);
    render_grid_rgba(w, h, grid, nullptr, lut.data(), 256, 5.0f, 5.0f, 1.0f, 255, out.data());
    CHECK_EQ(out[0], 0, "hi==lo -> idx0");
    CHECK_EQ(out[3], 255, "hi==lo still opaque for valid pixel");
}

void test_scalar_grid_layer_cache_and_revisions() {
    const std::vector<float> grid = {0.0f, 1.0f};
    pwb::grid_render::ScalarGridLayer layer(2, 1, grid);
    const std::vector<std::uint8_t> ramp = {
        0, 0, 0, 255,
        255, 255, 255, 255,
    };
    layer.set_color_ramp(ramp);
    const auto data0 = layer.data_revision();
    const auto style0 = layer.style_revision();
    const auto& first = layer.rasterize();
    CHECK_EQ(first.size(), 8u, "scalar layer produces RGBA bytes");
    CHECK_EQ(layer.rasterize_count(), 1u, "first scalar rasterization runs once");
    std::vector<std::uint8_t> copied(first.size());
    layer.rasterize_into(copied.data(), copied.size());
    CHECK_EQ(std::memcmp(first.data(), copied.data(), first.size()), 0,
             "scalar layer copies its cached RGBA snapshot");
    CHECK_EQ(layer.rasterize_count(), 1u, "copying cached scalar bytes does not rerasterize");
    layer.rasterize();
    CHECK_EQ(layer.rasterize_count(), 1u, "unchanged scalar layer uses cache");

    layer.set_gamma(2.0f);
    CHECK_EQ(layer.data_revision(), data0, "gamma is a style-only change");
    CHECK_EQ(layer.style_revision() > style0, true, "gamma bumps style revision");
    layer.rasterize();
    CHECK_EQ(layer.rasterize_count(), 2u, "style change rerasterizes without data change");

    layer.set_mask({1, 0});
    CHECK_EQ(layer.data_revision() > data0, true, "mask is a data change");
    const auto& masked = layer.rasterize();
    CHECK_EQ(masked[7], 0u, "masked grid cell is transparent");
    CHECK_EQ(layer.rasterize_count(), 3u, "data change rerasterizes once");
}

}  // namespace

int main() {
    test_basic_ramp_and_clamp();
    test_nodata_and_mask();
    test_opacity_alpha_multiply();
    test_gamma();
    test_degenerate_range();
    test_scalar_grid_layer_cache_and_revisions();
    if (g_failures == 0) {
        std::printf("ALL GRID_RENDER_CORE SELFTESTS PASSED\n");
        return 0;
    }
    std::printf("%d FAILURE(S)\n", g_failures);
    return 1;
}
