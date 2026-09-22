#include <pwb/seismic_viewer/display_core.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <functional>
#include <stdexcept>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::seismic_viewer::display {
namespace {

// numpy percentile 'linear' method over the sorted finite values:
// rank = q/100 * (n-1), interpolated between adjacent order statistics via
// numpy's _lerp — a + (b-a)*t below the midpoint, b - (b-a)*(1-t) above it
// (the two round differently, the switch is parity-critical).
double sorted_percentile(const std::vector<double>& sorted, double q) {
    const std::size_t n = sorted.size();
    if (n == 0) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    if (n == 1) {
        return sorted[0];
    }
    const double rank = (q / 100.0) * static_cast<double>(n - 1);
    const std::size_t lo = static_cast<std::size_t>(std::floor(rank));
    if (lo + 1 >= n || rank == static_cast<double>(lo)) {
        return sorted[std::min(lo, n - 1)];
    }
    const double frac = rank - static_cast<double>(lo);
    // numpy interpolates percentile samples in the INPUT dtype — float32
    // planes interpolate in float32 (the neighbors are exact float32
    // values; only the widened result differs from a float64 lerp).
    const float fa = static_cast<float>(sorted[lo]);
    const float fb = static_cast<float>(sorted[lo + 1]);
    const float fdiff = fb - fa;
    if (frac >= 0.5) {
        return static_cast<double>(fb - fdiff * static_cast<float>(1.0 - frac));
    }
    return static_cast<double>(fa + fdiff * static_cast<float>(frac));
}

// Two-tap order=1 stencil for one axis coordinate, replicating the
// map_coordinates(order=1) decode frozen in libs/ui_workers/src/stratal.cpp:
// floor coordinate, shifted back to {n-2, n-1} when it lands on the last
// node so integer coordinates still pull a zero-weight neighbour.
struct AxisTap {
    std::int64_t i0;
    std::int64_t i1;
    double f; // weight of i1
};

AxisTap axis_tap(double c, std::int64_t n) {
    std::int64_t base = static_cast<std::int64_t>(std::floor(c));
    if (n >= 2 && base >= n - 1) {
        base = n - 2;
    }
    if (base < 0) {
        base = 0;
    }
    const std::int64_t next = std::min<std::int64_t>(base + 1, std::max<std::int64_t>(n - 1, 0));
    return {base, next, c - static_cast<double>(base)};
}

} // namespace

// ---------------------------------------------------------------------------
// VD normalization
// ---------------------------------------------------------------------------

ClipRange percentile_clip_range(std::span<const float> data, double pct) {
    std::vector<double> finite;
    finite.reserve(data.size());
    double dmin = std::numeric_limits<double>::infinity();
    double dmax = -std::numeric_limits<double>::infinity();
    for (const float value : data) {
        if (std::isfinite(value)) {
            const double v = static_cast<double>(value);
            finite.push_back(v);
            dmin = std::min(dmin, v);
            dmax = std::max(dmax, v);
        }
    }
    if (finite.empty()) {
        // Python: nanmin/nanmax of an all-NaN plane are NaN and NaN == NaN
        // is False, so the slice is NOT degenerate — it normalizes through
        // a NaN range (every sample non-finite -> LUT centre).
        return {std::numeric_limits<double>::quiet_NaN(),
                std::numeric_limits<double>::quiet_NaN(), false};
    }
    if (!(dmin < dmax)) {
        // Constant finite plane: the all-zero index array (no range cached).
        return {dmin, dmax, true};
    }
    std::sort(finite.begin(), finite.end());
    double lo = sorted_percentile(finite, 100.0 - pct);
    double hi = sorted_percentile(finite, pct);
    if (!(hi > lo)) {
        hi = dmax;
        lo = dmin;
    }
    return {lo, hi, false};
}

std::vector<std::uint8_t> normalize_to_index(std::span<const float> data, double lo,
                                             double hi, std::size_t lut_size) {
    const std::size_t mid = lut_size / 2;
    std::vector<std::uint8_t> out(data.size(), 0);
    if (!(hi > lo)) {
        // Degenerate range: zeros, NaN still maps to the neutral centre
        // (colormap.py lines 85-93 parity).
        for (std::size_t i = 0; i < data.size(); ++i) {
            if (!std::isfinite(data[i])) {
                out[i] = static_cast<std::uint8_t>(mid);
            }
        }
        return out;
    }
    // The numpy chain is float32 end to end ((data - dmin) / (dmax - dmin)
    // with weak Python-float scalars stays float32; NEP 50), then
    // astype(int32) truncates. Mirror the dtype so truncation boundaries
    // land identically.
    const float lo32 = static_cast<float>(lo);
    const float span32 = static_cast<float>(hi) - lo32;
    const float scale32 = static_cast<float>(lut_size - 1);
    for (std::size_t i = 0; i < data.size(); ++i) {
        const float value = data[i];
        if (!std::isfinite(value)) {
            out[i] = static_cast<std::uint8_t>(mid);
            continue;
        }
        const float norm = (value - lo32) / span32;
        float scaled = norm * scale32;
        scaled = std::trunc(scaled);
        scaled = std::clamp(scaled, 0.0f, scale32);
        out[i] = static_cast<std::uint8_t>(scaled);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Wiggle geometry
// ---------------------------------------------------------------------------

Decimation viewport_decimation(std::int64_t n_traces, std::int64_t n_samples, int width,
                               int height, std::int64_t trace_step) {
    Decimation out;
    std::int64_t ts = std::max<std::int64_t>(trace_step, 1);
    if (width >= 2 && n_traces > 0 &&
        (n_traces + ts - 1) / ts > static_cast<std::int64_t>(width)) {
        ts = std::max<std::int64_t>(ts, (n_traces + width - 1) / width);
    }
    std::int64_t ss = 1;
    if (height >= 2 && n_samples > 1 &&
        (n_samples + ss - 1) / ss > static_cast<std::int64_t>(height)) {
        ss = std::max<std::int64_t>(ss, (n_samples + height - 1) / height);
    }
    out.trace_step = ts;
    if (n_samples <= 0) {
        return out;
    }
    for (std::int64_t s = 0; s < n_samples; s += ss) {
        out.sample_indices.push_back(s);
    }
    const std::int64_t last = n_samples - 1;
    if (out.sample_indices.empty() || out.sample_indices.back() != last) {
        out.sample_indices.push_back(last);
    }
    return out;
}

WiggleGeometry wiggle_geometry(std::span<const float> data, std::int64_t n_samples,
                               std::int64_t n_traces, int polarity, double gain, int width,
                               int height, std::int64_t trace_step) {
    WiggleGeometry geometry;
    if (data.size() != static_cast<std::size_t>(n_samples * n_traces) || n_samples <= 0 ||
        n_traces <= 0 || width < 2 || height < 2) {
        return geometry;
    }
    // Global |max| over finite samples, computed in float32 like
    // np.nanmax(np.abs(float32 slice)); all-NaN propagates NaN (nothing
    // drawable), a zero plane is guarded to 1.0.
    float amax = -std::numeric_limits<float>::infinity();
    bool have_finite = false;
    for (const float value : data) {
        if (std::isfinite(value)) {
            amax = std::max(amax, std::abs(value));
            have_finite = true;
        }
    }
    if (!have_finite) {
        amax = std::numeric_limits<float>::quiet_NaN();
    } else if (amax == 0.0f) {
        amax = 1.0f;
    }
    geometry.amax = static_cast<double>(amax);

    const Decimation dec =
        viewport_decimation(n_traces, n_samples, width, height, trace_step);
    const std::size_t n_draw = dec.sample_indices.size();
    const double x_scale = static_cast<double>(width) / static_cast<double>(std::max<std::int64_t>(n_traces, 1));
    const double y_scale =
        static_cast<double>(height) / static_cast<double>(std::max<std::int64_t>(n_samples - 1, 1));
    const double wiggle_gain = x_scale * static_cast<double>(dec.trace_step) * gain;

    std::vector<double> y_coords(n_draw);
    for (std::size_t k = 0; k < n_draw; ++k) {
        y_coords[k] = static_cast<double>(dec.sample_indices[k]) * y_scale;
    }

    for (std::int64_t t = 0; t < n_traces; t += dec.trace_step) {
        WiggleTrace trace;
        trace.centre_x = static_cast<double>(t) * x_scale + x_scale / 2.0;
        trace.xs.resize(n_draw);
        trace.ys = y_coords;
        std::vector<double> v(n_draw);
        std::vector<char> pos(n_draw);
        for (std::size_t k = 0; k < n_draw; ++k) {
            const float sample = data[static_cast<std::size_t>(dec.sample_indices[k]) *
                                         static_cast<std::size_t>(n_traces) +
                                     static_cast<std::size_t>(t)];
            // float32 division, then widened — the numpy source divides the
            // float32 slice by the float32 amax before .astype(float64).
            const float v32 =
                (static_cast<float>(polarity) * sample) / amax;
            v[k] = static_cast<double>(v32);
            trace.xs[k] = trace.centre_x + v[k] * wiggle_gain;
            pos[k] = v[k] >= 0.0 ? 1 : 0; // NaN compares false (IEEE)
        }
        // Positive runs bounded by zero-crossings; boundary runs close on
        // the first/last decimated sample.
        std::vector<std::size_t> starts;
        std::vector<std::size_t> ends;
        for (std::size_t k = 0; k + 1 < n_draw; ++k) {
            if (pos[k + 1] > pos[k]) {
                starts.push_back(k + 1);
            } else if (pos[k + 1] < pos[k]) {
                ends.push_back(k + 1);
            }
        }
        if (pos[0]) {
            starts.insert(starts.begin(), 0);
        }
        if (!pos.empty() && pos[n_draw - 1]) {
            ends.push_back(n_draw);
        }
        const std::size_t m = starts.size();
        if (m != 0 && m == ends.size()) {
            trace.lobes.resize(m);
            for (std::size_t lobe = 0; lobe < m; ++lobe) {
                const std::size_t s = starts[lobe];
                const std::size_t e = ends[lobe];
                double yc_in = y_coords[0];
                if (s != 0) {
                    const double frac_in =
                        -v[s - 1] / (v[s] - v[s - 1]);
                    yc_in = y_coords[s - 1] +
                            frac_in * (y_coords[s] - y_coords[s - 1]);
                }
                double yc_out = y_coords[n_draw - 1];
                if (e != n_draw) {
                    const double frac_out =
                        v[e - 1] / (v[e - 1] - v[e]);
                    yc_out = y_coords[e - 1] +
                             frac_out * (y_coords[e] - y_coords[e - 1]);
                }
                auto& polygon = trace.lobes[lobe];
                polygon.xs.push_back(trace.centre_x);
                polygon.ys.push_back(yc_in);
                for (std::size_t k = s; k < e; ++k) {
                    if (pos[k]) {
                        polygon.xs.push_back(trace.xs[k]);
                        polygon.ys.push_back(trace.ys[k]);
                    }
                }
                polygon.xs.push_back(trace.centre_x);
                polygon.ys.push_back(yc_out);
            }
        }
        geometry.traces.push_back(std::move(trace));
    }
    return geometry;
}

// ---------------------------------------------------------------------------
// Polyline sampling
// ---------------------------------------------------------------------------

static PolylineSample sample_polyline_impl(
    std::int64_t n_i, std::int64_t n_x, std::int64_t n_s,
    std::span<const std::pair<double, double>> points, double samples_per_unit,
    const std::function<double(std::int64_t, std::int64_t, std::int64_t)>& at,
    const std::function<bool()>& cancelled) {
    PolylineSample out;
    const auto zero_result = [&]() {
        out.n_samples = std::max<std::int64_t>(n_s, 0);
        out.n_points = 1;
        out.section.assign(static_cast<std::size_t>(out.n_samples), 0.0f);
        out.distances.assign(1, 0.0);
        return out;
    };
    if (n_i <= 0 || n_x <= 0 || n_s <= 0) {
        return zero_result();
    }
    if (!std::isfinite(samples_per_unit) || samples_per_unit <= 0)
        throw std::invalid_argument("polyline sampling density must be positive and finite");
    for (const auto& point : points) {
        if (!std::isfinite(point.first) || !std::isfinite(point.second))
            throw std::invalid_argument("polyline coordinates must be finite");
    }
    // Dense waypoints along the polyline: per segment n_pts =
    // max(2, int(seg_len * samples_per_unit)) samples on linspace(0, 1),
    // endpoint excluded on every segment but the last; segments shorter than
    // 0.01 are skipped (numpy source control flow).
    std::vector<double> ils;
    std::vector<double> xls;
    std::vector<double> dists;
    double cum_dist = 0.0;
    for (std::size_t seg = 0; seg + 1 < points.size(); ++seg) {
        const auto [i0, x0] = points[seg];
        const auto [i1, x1] = points[seg + 1];
        const double seg_len = std::hypot(i1 - i0, x1 - x0);
        if (seg_len < 0.01) {
            continue;
        }
        if (!std::isfinite(seg_len) || seg_len * samples_per_unit > 10000000.0)
            throw std::length_error("polyline segment exceeds ten million traces");
        const std::int64_t n_pts =
            std::max<std::int64_t>(2, static_cast<std::int64_t>(seg_len * samples_per_unit));
        const bool last_seg = seg + 2 == points.size();
        for (std::int64_t p = 0; p < n_pts; ++p) {
            // linspace(0, 1, n_pts, endpoint=last_seg): endpoint=False
            // rounds as p * (1/n) (t == 1 never emitted); endpoint=True
            // rounds as p * (1/(n-1)) and forces the last t to exactly 1.
            double t;
            if (last_seg) {
                t = p + 1 == n_pts
                        ? 1.0
                        : static_cast<double>(p) * (1.0 / static_cast<double>(n_pts - 1));
            } else {
                t = static_cast<double>(p) * (1.0 / static_cast<double>(n_pts));
            }
            // gpu_ops quantizes the waypoint coordinates to float32 before
            // sampling (np.array(..., dtype=np.float32)); mirror it or the
            // interpolation weights diverge on large surveys.
            ils.push_back(static_cast<double>(
                static_cast<float>(i0 + t * (i1 - i0))));
            xls.push_back(static_cast<double>(
                static_cast<float>(x0 + t * (x1 - x0))));
            dists.push_back(cum_dist + t * seg_len);
        }
        cum_dist += seg_len;
    }
    if (ils.empty()) {
        return zero_result();
    }

    out.n_samples = n_s;
    out.n_points = static_cast<std::int64_t>(ils.size());
    out.distances = dists;
    out.section.assign(static_cast<std::size_t>(n_s * out.n_points), 0.0f);
    for (std::int64_t h = 0; h < out.n_points; ++h) {
        if (cancelled && cancelled()) throw std::runtime_error("polyline extraction cancelled");
        const double fi = ils[static_cast<std::size_t>(h)];
        const double fj = xls[static_cast<std::size_t>(h)];
        // mode="constant", cval=0: coordinates outside a axis domain drop
        // the whole sample to cval (no interpolation across the edge).
        if (fi < 0.0 || fi > static_cast<double>(n_i - 1) || fj < 0.0 ||
            fj > static_cast<double>(n_x - 1)) {
            continue; // column stays cval (0)
        }
        const AxisTap ti = axis_tap(fi, n_i);
        const AxisTap tx = axis_tap(fj, n_x);
        for (std::int64_t s = 0; s < n_s; ++s) {
            const AxisTap ts = axis_tap(static_cast<double>(s), n_s);
            // Plain IEEE sum over all 8 taps: zero-weight corners still
            // contribute v * 0, so a NaN corner poisons (nan * 0 == nan) —
            // the scipy zero-weight NaN-neighbour quirk.
            double sum = 0.0;
            for (int a = 0; a < 2; ++a) {
                const double wi = a == 0 ? 1.0 - ti.f : ti.f;
                const std::int64_t ii = a == 0 ? ti.i0 : ti.i1;
                for (int b = 0; b < 2; ++b) {
                    const double wj = b == 0 ? 1.0 - tx.f : tx.f;
                    const std::int64_t xx = b == 0 ? tx.i0 : tx.i1;
                    for (int c = 0; c < 2; ++c) {
                        const double wt = c == 0 ? 1.0 - ts.f : ts.f;
                        const std::int64_t ss = c == 0 ? ts.i0 : ts.i1;
                        sum += at(ii, xx, ss) * (wi * wj * wt);
                    }
                }
            }
            out.section[static_cast<std::size_t>(s * out.n_points + h)] =
                static_cast<float>(sum);
        }
    }
    return out;
}

PolylineSample sample_polyline_slice(std::span<const float> volume, std::int64_t n_i,
    std::int64_t n_x, std::int64_t n_s,
    std::span<const std::pair<double, double>> points, double samples_per_unit) {
    if (n_i <= 0 || n_x <= 0 || n_s <= 0 ||
        volume.size() / static_cast<std::size_t>(n_s) / static_cast<std::size_t>(n_x) != static_cast<std::size_t>(n_i) ||
        volume.size() != static_cast<std::size_t>(n_i) * n_x * n_s) {
        PolylineSample empty;
        empty.n_samples = std::max<std::int64_t>(n_s, 0);
        empty.n_points = 1;
        empty.section.assign(static_cast<std::size_t>(empty.n_samples), 0.0f);
        empty.distances = {0.0};
        return empty;
    }
    return sample_polyline_impl(n_i, n_x, n_s, points, samples_per_unit,
        [&](std::int64_t i, std::int64_t x, std::int64_t t) {
            return static_cast<double>(volume[(i * n_x + x) * n_s + t]);
        }, {});
}

PolylineSample sample_polyline_slice(pwb::viz::ISeismicVolume& source,
    std::span<const std::pair<double, double>> points, double samples_per_unit,
    const std::function<bool()>& cancelled) {
    const auto geometry = source.geometry();
    const auto [ni, nx, ns] = geometry.shape;
    if (ni <= 0 || nx <= 0 || ns <= 0) throw std::invalid_argument("empty source volume");
    // Two inline planes suffice for the interpolation stencil. This bounds
    // memory independently of survey inline count and supports chunked readers.
    std::array<std::vector<float>, 2> planes;
    std::array<std::int64_t, 2> indices{-1, -1};
    std::size_t next = 0;
    return sample_polyline_impl(ni, nx, ns, points, samples_per_unit,
        [&](std::int64_t i, std::int64_t x, std::int64_t t) {
            std::size_t slot = indices[0] == i ? 0 : (indices[1] == i ? 1 : 2);
            if (slot == 2) {
                if (cancelled && cancelled()) throw std::runtime_error("polyline extraction cancelled");
                slot = next;
                next = 1 - next;
                planes[slot].resize(static_cast<std::size_t>(nx) * ns);
                if (source.read_slice(pwb::viz::VolumeAxis::inline_, i, planes[slot]) != planes[slot].size())
                    throw std::runtime_error("polyline inline read failed");
                indices[slot] = i;
            }
            return static_cast<double>(planes[slot][static_cast<std::size_t>(x) * ns + t]);
        }, cancelled);
}

} // namespace pwb::seismic_viewer::display
