#pragma once

// VIZ-D attribute / RGB-fusion display core — Qt-free port of the frozen
// geoviz oracle fuse_rgb (geo-viz-engine@08851951,
// geoviz_seismic/attributes.py:223 fuse_rgb):
//
//   def _normalize(a):
//       lo = np.nanpercentile(a, 100.0 - clip_pct)
//       hi = np.nanpercentile(a, clip_pct)
//       if hi <= lo:                       # NaN compares False — an all-NaN
//           hi = np.nanmax(a)              # channel falls through to clip()
//           lo = np.nanmin(a)              # of NaN and casts to 0 below
//       if hi <= lo:
//           return np.zeros_like(a)
//       return np.clip((a - lo) / (hi - lo), 0.0, 1.0)
//   channel = (_normalize(a) * 255).astype(np.uint8)   # truncate toward zero
//
// The per-channel range logic reuses display::percentile_clip_range (already
// oracle-parity tested against the committed numpy fixtures): P(100-pct)..P(pct)
// with the nanmin/nanmax fallback, float32 interpolation. One declared C++
// deviation, forced by the NaN comparison above: a non-finite sample or an
// all-NaN channel maps to 0 (the numpy astype(uint8) cast of NaN is 0 on the
// reference platform, with a RuntimeWarning) instead of undefined behaviour.
//
// Constant channel: Python takes the zeros branch (both hi<=lo checks true
// after the min/max fallback fails) -> channel of 0. blend_rgba (min-max +
// constant alpha, the pyqtgraph.opengl path) is intentionally NOT ported:
// it belongs to the 3-D engine, not the 2-D display layer.
//
// All functions are deterministic and thread-compatible; nothing here
// touches Qt, I/O or the volume lifecycle.

#include <cstdint>
#include <span>
#include <vector>

namespace pwb::seismic_viewer::fusion {

// Normalization plan for one channel (fuse_rgb._normalize parity).
struct ChannelPlan {
    double lo{0.0};
    double hi{0.0};
    bool zero_channel{false}; // constant / all-NaN channel -> output zeros
};

// Percentile range for one channel: P(100-pct)..P(pct) over the finite
// samples with the nanmin/nanmax fallback; zero_channel when the finite
// extent collapsed (constant plane) or no finite sample exists.
[[nodiscard]] ChannelPlan channel_plan(std::span<const float> data, double clip_pct);

// Fuse three (rows x cols) channel planes (canonical row-major, one value per
// plane cell) into a rows*cols*3 byte RGB image. Each channel is normalized
// independently by channel_plan(data, clip_pct) and quantized to uint8 with
// the numpy float32 chain: clip((v-lo)/(hi-lo), 0, 1) * 255, truncated.
// Layout: out[(row * cols + col) * 3 + channel].
[[nodiscard]] std::vector<std::uint8_t> fuse_rgb(std::span<const float> attr_r,
                                                 std::span<const float> attr_g,
                                                 std::span<const float> attr_b,
                                                 std::int64_t rows, std::int64_t cols,
                                                 double clip_pct = 99.0);

} // namespace pwb::seismic_viewer::fusion
