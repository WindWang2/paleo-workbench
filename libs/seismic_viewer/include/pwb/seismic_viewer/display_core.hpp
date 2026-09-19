#pragma once

// VIZ-D display core — Qt-free numeric/display semantics ported from the
// frozen geoviz oracle (geo-viz-engine@08851951):
//   * profile_vd._renormalize / ColormapManager._normalize_and_clip —
//     asymmetric percentile clip (P(100-pct)..P(pct)) with min/max fallback
//     and the NaN-to-centre index mapping (false-amplitude fix #119);
//   * profile_wiggle.viewport_decimation + the paintEvent per-trace
//     geometry (deflection polyline + positive fill lobes with
//     zero-crossing interpolation) in pure double math;
//   * gpu_ops.sample_polyline_slice — CPU parity of
//     scipy.ndimage.map_coordinates(order=1, mode="constant", cval=0)
//     along an IL/XL polyline (the GPU path itself stays descoped).
//
// All functions are deterministic and thread-compatible; nothing here
// touches Qt, I/O or the volume lifecycle.

#include <cstdint>
#include <span>
#include <utility>
#include <vector>

namespace pwb::seismic_viewer::display {

// ---------------------------------------------------------------------------
// VD normalization (profile_vd.py parity)
// ---------------------------------------------------------------------------

struct ClipRange {
    double lo{0.0};
    double hi{0.0};
    bool degenerate{false}; // no finite samples, or finite extent collapsed
};

// Python: lo = nanpercentile(data, 100 - pct), hi = nanpercentile(data, pct)
// computed on the RAW slice (polarity is applied later, display-only);
// fallback to nanmin/nanmax when hi <= lo. numpy percentile 'linear'
// interpolation over the sorted finite values: rank = q/100 * (n-1).
// Callers clamp pct into [1, 99] (set_clip_percentile contract).
[[nodiscard]] ClipRange percentile_clip_range(std::span<const float> data, double pct);

// ColormapManager._normalize_and_clip parity for a fixed (lo, hi) range:
// norm = (data - lo) / (hi - lo), index = trunc(norm * (lut_size - 1))
// clamped to [0, lut_size - 1]; non-finite samples map to lut_size / 2
// (256-entry LUTs => 128, the neutral centre) instead of index 0.
[[nodiscard]] std::vector<std::uint8_t>
normalize_to_index(std::span<const float> data, double lo, double hi,
                   std::size_t lut_size = 256);

// ---------------------------------------------------------------------------
// Wiggle geometry (profile_wiggle.py parity)
// ---------------------------------------------------------------------------

// Decimate traces/samples so at most one drawn sample lands per viewport
// pixel; sample indices always include the last sample so the time axis is
// closed. Mirrors viewport_decimation(n_traces, n_samples, width, height,
// trace_step) including the (n + step - 1) // step ceil steps.
struct Decimation {
    std::int64_t trace_step{1};
    std::vector<std::int64_t> sample_indices;
};
[[nodiscard]] Decimation viewport_decimation(std::int64_t n_traces,
                                             std::int64_t n_samples, int width,
                                             int height,
                                             std::int64_t trace_step = 1);

struct WiggleLobe {
    std::vector<double> xs;
    std::vector<double> ys;
};

struct WiggleTrace {
    double centre_x{0.0};
    std::vector<double> xs; // deflection polyline, one x per decimated sample
    std::vector<double> ys; // matching y coordinates
    std::vector<WiggleLobe> lobes; // positive fill polygons incl. crossings
};

struct WiggleGeometry {
    std::vector<WiggleTrace> traces;
    double amax{1.0}; // global |max| actually used (guarded to 1.0 when 0)
};

// Pure-double reproduction of ProfileWiggle::paintEvent geometry for a
// (n_samples, n_traces) plane (data[sample * n_traces + trace], i.e. the
// canonical C-order layout of the numpy source). polarity is +1/-1
// (display-only), gain > 0 (source default 2.0), (width, height) the widget
// pixel size. Arithmetic parity: v is computed in float32 (the numpy source
// divides the float32 slice by the float32 global amax) and then widened to
// float64 for the deflection math.
[[nodiscard]] WiggleGeometry
wiggle_geometry(std::span<const float> data, std::int64_t n_samples,
                std::int64_t n_traces, int polarity, double gain, int width,
                int height, std::int64_t trace_step = 1);

// ---------------------------------------------------------------------------
// Arbitrary-line / polyline sampling (gpu_ops.sample_polyline_slice parity)
// ---------------------------------------------------------------------------

struct PolylineSample {
    // (n_samples, n_points) row-major: section[sample * n_points + point],
    // the same shape the numpy source returns.
    std::vector<float> section;
    std::vector<double> distances; // cumulative path distance per point
    std::int64_t n_samples{0};
    std::int64_t n_points{0};
};

// scipy.ndimage.map_coordinates(volume, coords, order=1, mode="constant",
// cval=0.0) along (inline, xline) waypoints — fractional indices allowed —
// with the per-axis rule already decoded for this repo in
// libs/ui_workers/src/stratal.cpp (two-tap stencil, shifted back at the last
// node so an integer coordinate still pulls a zero-weight neighbour; IEEE
// nan*0 == nan zero-weight poisoning). Waypoint segments shorter than 0.01
// are skipped; each segment is resampled at `samples_per_unit` horizontal
// samples per voxel unit (>= 2 points, last segment endpoint-inclusive).
// Fewer than 2 waypoints (or no resampled points) yields a single zero
// column, matching the numpy source.
[[nodiscard]] PolylineSample
sample_polyline_slice(std::span<const float> volume, std::int64_t n_i,
                      std::int64_t n_x, std::int64_t n_s,
                      std::span<const std::pair<double, double>> points,
                      double samples_per_unit = 1.0);

} // namespace pwb::seismic_viewer::display
