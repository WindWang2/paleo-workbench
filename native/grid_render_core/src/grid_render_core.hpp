// grid_render_core.hpp — native scalar-grid rasterisation hot path.
//
// Pure C++ algorithm (no pybind11 / no Python). The single public function is the
// per-pixel hot path the single-factor-map renderer is required to keep out of Python:
// it maps a float32 grid through a colour ramp to an RGBA buffer in one pass, honouring
// nodata, mask and opacity. bindings.cpp wraps it for Python; the standalone_test.cpp
// harness verifies the numeric behaviour with plain g++ (no Python toolchain needed).
#pragma once

#include <cstdint>

namespace pwb::grid_render {

// Render ``grid_z`` (row-major float32, height*width) into ``out`` (row-major RGBA
// uint8, height*width*4) in a single deterministic pass.
//
//   grid_z    float32[height*width]; non-finite values (NaN/±Inf) are nodata.
//   mask      uint8 [height*width] with 1=valid, 0=masked-out; nullptr == all valid.
//   lut       uint8 RGBA[lut_size*4] colour ramp.
//   out       uint8 RGBA[height*width*4], caller-allocated.
//
// Normalisation: t = clamp((v - lo) / (hi - lo), 0, 1); gamma applied as t ^ gamma.
// Index selection truncates toward zero (idx = int(t * (lut_size - 1))) so the C++ and
// the pure-Python parity fallback produce byte-identical output. Values outside
// [lo, hi] clamp to the ramp endpoints (they are NOT transparent). Nodata / masked
// cells emit fully-transparent black (alpha = 0). Valid cells emit the LUT colour with
// alpha = lut_alpha * opacity / 255.
//
// Defensive defaults (deterministic, documented): hi <= lo  -> t = 0; gamma <= 0 ->
// gamma = 1; lut_size < 1 is treated as an error (returns, leaving `out` unmodified).
void render_grid_rgba(int width, int height,
                      const float* grid_z,
                      const std::uint8_t* mask,
                      const std::uint8_t* lut,
                      int lut_size,
                      float lo, float hi,
                      float gamma,
                      std::uint8_t opacity,
                      std::uint8_t* out) noexcept;

}  // namespace pwb::grid_render
