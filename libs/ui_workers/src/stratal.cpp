#include "pwb/ui_workers/stratal.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace pwb::ui_workers {

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

inline bool finite(double v) { return std::isfinite(v); }

// numpy shape repr — "(16, 20)" like Python's tuple print.
std::string shape_str(const Grid2D& g) {
    return "(" + std::to_string(g.rows) + ", " + std::to_string(g.cols) +
           ")";
}

void require_same_shape(const Grid2D& top, const Grid2D& bottom) {
    // f"horizon shape mismatch: top {top.shape} vs bottom {bottom.shape}"
    if (top.rows != bottom.rows || top.cols != bottom.cols) {
        throw std::invalid_argument("horizon shape mismatch: top " +
                                    shape_str(top) + " vs bottom " +
                                    shape_str(bottom));
    }
}

// scipy map_coordinates(order=1, mode="constant", cval=0) on a 3-D volume
// at integer i/x coords. Per axis the 2-tap stencil is
// {floor(c), floor(c)+1}, shifted to {n-2, n-1} when c lands on the last
// node — so an integer coordinate ALWAYS pulls in a neighbor (forward,
// or backward at the top edge). IEEE nan*0 == nan means ANY NaN corner of
// the full 8-node stencil poisons the sample, including zero-weight i/x
// neighbors; the caller clips idx_safe to [0, n_s-1] before sampling, so
// coordinates never leave the volume. order=0 rounds via floor(c+0.5) on
// a single node (no stencil).
double lerp_sample(const Volume3D& v, std::size_t i, std::size_t x,
                   double s, bool order0) {
    const double c =
        std::clamp(s, 0.0, static_cast<double>(v.n_s) - 1.0);
    if (order0) {
        const long idx = static_cast<long>(std::floor(c + 0.5));
        const auto n = static_cast<long>(v.n_s);
        const long safe = std::clamp(idx, 0L, n - 1);
        return v.at(i, x, static_cast<std::size_t>(safe));
    }
    std::size_t s0 = static_cast<std::size_t>(std::floor(c));
    if (s0 >= v.n_s - 1) s0 = v.n_s >= 2 ? v.n_s - 2 : 0;
    const std::size_t s1 = std::min(s0 + 1, v.n_s - 1);
    const double f = c - static_cast<double>(s0);
    // i/x integer coords reach one in-bounds neighbor (forward; backward
    // at the last index) whose zero-weight NaN still poisons.
    const std::size_t i2 =
        v.n_i >= 2 ? (i >= v.n_i - 1 ? i - 1 : i + 1) : i;
    const std::size_t x2 =
        v.n_x >= 2 ? (x >= v.n_x - 1 ? x - 1 : x + 1) : x;
    const double v00 =
        v.at(i, x, s0) * (1.0 - f) + v.at(i, x, s1) * f;
    const double v01 =
        v.at(i, x2, s0) * (1.0 - f) + v.at(i, x2, s1) * f;
    const double v10 =
        v.at(i2, x, s0) * (1.0 - f) + v.at(i2, x, s1) * f;
    const double v11 =
        v.at(i2, x2, s0) * (1.0 - f) + v.at(i2, x2, s1) * f;
    // Neighbor tubes enter at exactly zero weight: finite corners add 0,
    // a NaN corner yields nan*0 == nan and poisons the sample.
    return v00 + v01 * 0.0 + v10 * 0.0 + v11 * 0.0;
}

// scipy map_coordinates(order=1, mode="nearest") on a 2-D grid —
// genuine bilinear with per-corner index clamping to [0, n-1].
double bilinear_nearest(const Grid2D& g, double r, double c) {
    const auto ri = static_cast<long>(g.rows) - 1;
    const auto ci = static_cast<long>(g.cols) - 1;
    const double rf = std::floor(r), cf = std::floor(c);
    const long r0l = static_cast<long>(rf), c0l = static_cast<long>(cf);
    const long r1l = r0l + 1, c1l = c0l + 1;
    const auto clamp_l = [](long v, long hi) {
        return static_cast<std::size_t>(std::clamp(v, 0L, hi));
    };
    const double fr = r - rf, fc = c - cf;
    const double v00 = g.at(clamp_l(r0l, ri), clamp_l(c0l, ci));
    const double v01 = g.at(clamp_l(r0l, ri), clamp_l(c1l, ci));
    const double v10 = g.at(clamp_l(r1l, ri), clamp_l(c0l, ci));
    const double v11 = g.at(clamp_l(r1l, ri), clamp_l(c1l, ci));
    return v00 * (1 - fr) * (1 - fc) + v01 * (1 - fr) * fc +
           v10 * fr * (1 - fc) + v11 * fr * fc;
}

}  // namespace

Grid2D grid2d_filled(std::size_t rows, std::size_t cols, double v) {
    Grid2D g;
    g.rows = rows;
    g.cols = cols;
    g.data.assign(rows * cols, v);
    return g;
}

std::vector<bool> validate_horizon_pair(const Grid2D& top,
                                        const Grid2D& bottom,
                                        const std::size_t* n_samples) {
    require_same_shape(top, bottom);
    std::vector<bool> valid(top.rows * top.cols);
    for (std::size_t k = 0; k < valid.size(); ++k) {
        const double t = top.data[k], b = bottom.data[k];
        bool ok = finite(t) && finite(b) && (b >= t);
        if (ok && n_samples) {
            const double ns = static_cast<double>(*n_samples);
            ok = (t >= 0) && (t < ns) && (b >= 0) && (b < ns);
        }
        valid[k] = ok;
    }
    return valid;
}

std::vector<Grid2D> build_proportional_surfaces(
    const Grid2D& top, const Grid2D& bottom,
    const std::vector<double>& fractions) {
    require_same_shape(top, bottom);
    std::vector<Grid2D> out;
    out.reserve(fractions.size());
    for (double k_in : fractions) {
        const double k = std::clamp(k_in, 0.0, 1.0);
        Grid2D s;
        s.rows = top.rows;
        s.cols = top.cols;
        s.data.resize(top.data.size());
        for (std::size_t i = 0; i < s.data.size(); ++i) {
            const double t = top.data[i], b = bottom.data[i];
            double v = t + k * (b - t);
            // np.clip(surface, lo, hi) — NaN propagates (NaN compares
            // false so std::clamp would be UB; guard explicitly).
            const double lo = std::min(t, b), hi = std::max(t, b);
            if (finite(v)) v = std::clamp(v, lo, hi);
            s.data[i] = v;
        }
        out.push_back(std::move(s));
    }
    return out;
}

Grid2D extract_stratal_slice(const Volume3D& volume, const Grid2D& surface,
                             int window, StratalMode mode, bool order0) {
    if (surface.rows != volume.n_i || surface.cols != volume.n_x) {
        // f"surface shape {surface.shape} does not match volume "
        // f"(first two axes) {(n_i, n_x)}"
        throw std::invalid_argument(
            "surface shape " + shape_str(surface) +
            " does not match volume (first two axes) (" +
            std::to_string(volume.n_i) + ", " +
            std::to_string(volume.n_x) + ")");
    }
    Grid2D out = grid2d_filled(volume.n_i, volume.n_x, kNaN);
    const std::size_t n_i = volume.n_i, n_x = volume.n_x;
    const long ns = static_cast<long>(volume.n_s);

    if (window <= 0) {
        for (std::size_t i = 0; i < n_i; ++i) {
            for (std::size_t x = 0; x < n_x; ++x) {
                const double s = surface.at(i, x);
                if (!finite(s)) continue;
                // map_coordinates output is .astype(np.float32) before
                // it lands in out — round to f32, store as double.
                out.at(i, x) = static_cast<double>(static_cast<float>(
                    lerp_sample(volume, i, x, s, order0)));
            }
        }
        return out;
    }

    const long half = window;
    for (std::size_t i = 0; i < n_i; ++i) {
        for (std::size_t x = 0; x < n_x; ++x) {
            const double s = surface.at(i, x);
            if (!finite(s)) continue;
            // The stack is float32 and nanmean accumulates in float32 —
            // round each sample to f32 and accumulate in float (parity,
            // not extra precision).
            float acc = 0.0f;
            float acc_sq = 0.0f;
            float max_abs = 0.0f;
            std::size_t count = 0;
            for (long off = -half; off <= half; ++off) {
                const double idx = s + static_cast<double>(off);
                if (idx < 0 || idx >= static_cast<double>(ns)) continue;
                const float v = static_cast<float>(
                    lerp_sample(volume, i, x, idx, order0));
                // nanmean/nanmax SKIP NaN stack entries — a NaN volume
                // sample is absent data, not a zero.
                if (!std::isfinite(v)) continue;
                ++count;
                acc += v;
                acc_sq += v * v;
                max_abs = std::max(max_abs, std::fabs(v));
            }
            if (count == 0) continue;  // all-NaN window -> NaN
            float agg = 0.0f;
            switch (mode) {
                case StratalMode::kRms:
                    agg = std::sqrt(acc_sq / static_cast<float>(count));
                    break;
                case StratalMode::kMean:
                    agg = acc / static_cast<float>(count);
                    break;
                case StratalMode::kMax:
                    agg = max_abs;
                    break;
            }
            out.at(i, x) = static_cast<double>(agg);
        }
    }
    return out;
}

std::vector<Grid2D> stratal_slice_volume(
    const Volume3D& volume, const Grid2D& top, const Grid2D& bottom,
    const std::vector<double>& fractions, int window, StratalMode mode,
    bool order0, std::vector<Grid2D>* surfaces_out) {
    if (top.rows != volume.n_i || top.cols != volume.n_x ||
        bottom.rows != volume.n_i || bottom.cols != volume.n_x) {
        // f"horizon grids {top.shape}/{bottom.shape} must match volume "
        // f"first-two-axes {volume.shape[:2]}"
        const std::string vshape = "(" + std::to_string(volume.n_i) +
                                   ", " + std::to_string(volume.n_x) + ")";
        throw std::invalid_argument(
            "horizon grids " + shape_str(top) + "/" + shape_str(bottom) +
            " must match volume first-two-axes " + vshape);
    }
    const auto good = validate_horizon_pair(top, bottom, &volume.n_s);
    Grid2D top_c = top, bot_c = bottom;
    for (std::size_t k = 0; k < good.size(); ++k) {
        if (!good[k]) {
            top_c.data[k] = kNaN;
            bot_c.data[k] = kNaN;
        }
    }
    auto surfaces = build_proportional_surfaces(top_c, bot_c, fractions);
    std::vector<Grid2D> maps;
    maps.reserve(surfaces.size());
    for (const auto& s : surfaces) {
        maps.push_back(extract_stratal_slice(volume, s, window, mode,
                                           order0));
    }
    if (surfaces_out) *surfaces_out = std::move(surfaces);
    return maps;
}

Grid2D ms_to_preview_sample_index(const Grid2D& ms, double dt_ms,
                                  double t0_ms, int sample_stride) {
    const double dt = (dt_ms > 0) ? dt_ms : 1.0;
    const double stride = static_cast<double>(std::max(1, sample_stride));
    Grid2D out;
    out.rows = ms.rows;
    out.cols = ms.cols;
    out.data.resize(ms.data.size());
    for (std::size_t k = 0; k < out.data.size(); ++k) {
        out.data[k] = (ms.data[k] - t0_ms) / dt / stride;
    }
    return out;
}

std::pair<Grid2D, Grid2D> ms_grids_to_preview_sample_indices(
    const Grid2D& top_ms, const Grid2D& bot_ms, std::size_t n_i_prev,
    std::size_t n_x_prev, double stride_i, double stride_x, double dt_ms,
    double t0_ms, int sample_stride) {
    const auto to_prev = [&](const Grid2D& g) {
        Grid2D ms;
        ms.rows = n_i_prev;
        ms.cols = n_x_prev;
        ms.data.resize(n_i_prev * n_x_prev);
        for (std::size_t i = 0; i < n_i_prev; ++i) {
            for (std::size_t x = 0; x < n_x_prev; ++x) {
                ms.at(i, x) = bilinear_nearest(
                    g, static_cast<double>(i) * stride_i,
                    static_cast<double>(x) * stride_x);
            }
        }
        return ms_to_preview_sample_index(ms, dt_ms, t0_ms, sample_stride);
    };
    return {to_prev(top_ms), to_prev(bot_ms)};
}

std::optional<std::pair<std::vector<Grid2D>, std::array<Grid2D, 2>>>
build_stratal_surfaces(const Grid2D& top_sidx, const Grid2D& bot_sidx,
                       std::size_t n_samples,
                       const std::vector<double>& fractions) {
    const auto good = validate_horizon_pair(top_sidx, bot_sidx, &n_samples);
    if (std::none_of(good.begin(), good.end(), [](bool b) { return b; })) {
        return std::nullopt;
    }
    Grid2D top_c = top_sidx, bot_c = bot_sidx;
    for (std::size_t k = 0; k < good.size(); ++k) {
        if (!good[k]) {
            top_c.data[k] = kNaN;
            bot_c.data[k] = kNaN;
        }
    }
    auto surfaces = build_proportional_surfaces(top_c, bot_c, fractions);
    return std::make_pair(std::move(surfaces),
                          std::array<Grid2D, 2>{top_c, bot_c});
}

Volume3D make_synthetic_demo_volume(std::size_t n_i, std::size_t n_x,
                                    std::size_t n_t, int n_reflectors,
                                    const DemoNoiseFn& noise_fn) {
    Volume3D vol;
    vol.n_i = n_i;
    vol.n_x = n_x;
    vol.n_s = n_t;
    vol.data.assign(n_i * n_x * n_t, 0.0f);
    // Dipping planar reflectors — exact numpy math:
    //   dip = (ii - ni/2)*0.20 + (xx - nx/2)*0.15
    //   center = t0 + dip ; amp = exp(-(t - center)^2 / 2)
    for (int r = 0; r < n_reflectors; ++r) {
        const double t0 = (r + 1) * static_cast<double>(n_t) /
                          (n_reflectors + 1);
        const double sign = (r % 2 == 0) ? 1.0 : -1.0;
        for (std::size_t i = 0; i < n_i; ++i) {
            for (std::size_t x = 0; x < n_x; ++x) {
                const double dip =
                    (static_cast<double>(i) - n_i / 2.0) * 0.20 +
                    (static_cast<double>(x) - n_x / 2.0) * 0.15;
                const double center = t0 + dip;
                for (std::size_t t = 0; t < n_t; ++t) {
                    const double d = static_cast<double>(t) - center;
                    vol.data[(i * n_x + x) * n_t + t] += static_cast<float>(
                        sign * std::exp(-(d * d) / 2.0));
                }
            }
        }
    }
    if (noise_fn) {
        std::vector<double> noise;
        noise_fn(noise);
        for (std::size_t k = 0; k < vol.data.size() && k < noise.size();
             ++k) {
            // (rng.standard_normal(shape) * 0.05).astype(np.float32) —
            // the product is float64 BEFORE the cast, then f32 += f32.
            vol.data[k] += static_cast<float>(noise[k] * 0.05);
        }
    }
    return vol;
}

std::tuple<Volume3D, Grid2D, Grid2D> make_demo_stratal_grids(
    std::size_t n_i, std::size_t n_x, std::size_t n_t,
    const DemoNoiseFn& noise_fn) {
    Volume3D vol = make_synthetic_demo_volume(n_i, n_x, n_t, 3, noise_fn);
    Grid2D top, bot;
    top.rows = bot.rows = n_i;
    top.cols = bot.cols = n_x;
    top.data.resize(n_i * n_x);
    bot.data.resize(n_i * n_x);
    for (std::size_t i = 0; i < n_i; ++i) {
        for (std::size_t x = 0; x < n_x; ++x) {
            const double dip =
                (static_cast<double>(i) - n_i / 2.0) * 0.20 +
                (static_cast<double>(x) - n_x / 2.0) * 0.15;
            const double mid = n_t / 2.0 + dip;
            const double lo = 0.5, hi = static_cast<double>(n_t) - 1.5;
            top.at(i, x) = std::clamp(mid - 4.0, lo, hi);
            bot.at(i, x) = std::clamp(mid + 4.0, lo, hi);
        }
    }
    return {std::move(vol), std::move(top), std::move(bot)};
}

}  // namespace pwb::ui_workers
