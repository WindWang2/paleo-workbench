// pwb::mapping — directional-trend kernel; see directional_trend.hpp for
// the contract. Line-faithful port of
// geoviz_plots/interpolation/directional.py.

#include <pwb/mapping/directional_trend.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace pwb::mapping {
namespace {

constexpr double kEps = 1e-15;
constexpr std::size_t kPairwiseBlock = 1024;
constexpr double kPi = 3.14159265358979323846;
constexpr double kDegToRad = kPi / 180.0;

// numpy float64 pairwise summation (numpy/core umath pairwise_sum): the
// exact accumulation order np.sum applies to contiguous float64 axes —
// sequential < 8, 8-way unrolled <= 128, binary split (multiple of 8)
// beyond. Used wherever the oracle np.sum's a contiguous row.
double pairwise_sum(const double* a, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; ++i) res += a[i];
        return res;
    }
    if (n <= 128) {
        double r[8];
        for (std::size_t k = 0; k < 8; ++k) r[k] = a[k];
        std::size_t i = 8;
        for (; i < n - (n % 8); i += 8) {
            for (std::size_t k = 0; k < 8; ++k) r[k] += a[i + k];
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3]))
                     + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(a, n2) + pairwise_sum(a + n2, n - n2);
}

// Python float % 360.0: sign of the divisor, so the result lands in
// [0, 360) for any finite input.
double python_mod_360(double v) {
    double r = std::fmod(v, 360.0);
    if (r != 0.0 && r < 0.0) r += 360.0;
    if (r == 0.0) r = 0.0;  // -0.0 -> 0.0 (Python never yields -0.0 here)
    return r;
}

std::size_t argmin_first(const std::vector<double>& v) {
    // np.argmin: lowest index on ties.
    std::size_t best = 0;
    for (std::size_t i = 1; i < v.size(); ++i) {
        if (v[i] < v[best]) best = i;
    }
    return best;
}

}  // namespace

double azimuth_to_rad(double azimuth_deg) {
    return python_mod_360(azimuth_deg) * kDegToRad;
}

std::pair<double, double> rotate_to_uv(double dx, double dy,
                                       double azimuth_deg) {
    const double theta = azimuth_to_rad(azimuth_deg);
    const double cos_t = std::cos(theta);
    const double sin_t = std::sin(theta);
    return {dx * sin_t + dy * cos_t, dx * cos_t - dy * sin_t};
}

double positive_axis(double value, const char* name) {
    if (!std::isfinite(value) || value <= 0.0) {
        throw std::invalid_argument(std::string(name)
                                    + " must be a finite positive value");
    }
    return value;
}

double mean_pairwise_distance(const std::vector<double>& xs,
                              const std::vector<double>& ys) {
    const std::size_t n = xs.size();
    if (n < 2) return 0.0;
    double total = 0.0;
    std::size_t count = 0;
    // 1024-row blocks; each pair counted once (j > i), finite only, and
    // the per-block masked order (row-major, j ascending) preserved —
    // then numpy's pairwise sum over the block's extracted values.
    std::vector<double> block_values;
    for (std::size_t start = 0; start < n; start += kPairwiseBlock) {
        const std::size_t stop = std::min(start + kPairwiseBlock, n);
        block_values.clear();
        for (std::size_t i = start; i < stop; ++i) {
            for (std::size_t j = i + 1; j < n; ++j) {
                const double d =
                    std::hypot(xs[i] - xs[j], ys[i] - ys[j]);
                if (std::isfinite(d)) block_values.push_back(d);
            }
        }
        if (!block_values.empty()) {
            total += pairwise_sum(block_values.data(), block_values.size());
            count += block_values.size();
        }
    }
    return count ? total / static_cast<double>(count) : 0.0;
}

std::pair<double, double> scaled_axes(double a, double b,
                                      const std::vector<double>& xs,
                                      const std::vector<double>& ys) {
    const double span = mean_pairwise_distance(xs, ys);
    if (std::isfinite(span) && span > 0.0) {
        return {a * span, b * span};
    }
    return {a, b};
}

double directional_weight(double distance, double q, double b_i) {
    double w = std::exp(-(distance * distance)) * q * b_i;
    if (!std::isfinite(w)) w = 0.0;
    return std::max(w, 0.0);
}

DirectionalSamples directional_sample_arrays(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>* q,
    const std::vector<double>* b_i) {
    const std::size_t n = zs.size();
    if (!(xs.size() == n && ys.size() == n)) {
        throw std::invalid_argument("xs, ys and zs must have equal lengths");
    }
    std::vector<double> q_arr(n, 1.0);
    std::vector<double> b_arr(n, 1.0);
    if (q != nullptr) {
        if (q->size() != n) {
            throw std::invalid_argument(
                "q and b_i must match sample count");
        }
        q_arr = *q;
    }
    if (b_i != nullptr) {
        if (b_i->size() != n) {
            throw std::invalid_argument(
                "q and b_i must match sample count");
        }
        b_arr = *b_i;
    }
    DirectionalSamples out;
    for (std::size_t i = 0; i < n; ++i) {
        if (std::isfinite(xs[i]) && std::isfinite(ys[i])
            && std::isfinite(zs[i])) {
            out.x.push_back(xs[i]);
            out.y.push_back(ys[i]);
            out.z.push_back(zs[i]);
            out.q.push_back(q_arr[i]);
            out.b_i.push_back(b_arr[i]);
        }
    }
    return out;
}

double trend_value_at(double x0, double y0, const std::vector<double>& xs,
                      const std::vector<double>& ys,
                      const std::vector<double>& zs, double azimuth_deg,
                      double a, double b, const std::vector<double>* q,
                      const std::vector<double>* b_i) {
    const DirectionalSamples s =
        directional_sample_arrays(xs, ys, zs, q, b_i);
    const std::size_t n = s.z.size();
    if (n == 0) return std::numeric_limits<double>::quiet_NaN();
    const auto [a_eff, b_eff] = scaled_axes(a, b, s.x, s.y);
    // directional_distance validates the effective axes.
    const double aa = positive_axis(a_eff, "a");
    const double bb = positive_axis(b_eff, "b");
    const double theta = azimuth_to_rad(azimuth_deg);
    const double cos_t = std::cos(theta);
    const double sin_t = std::sin(theta);
    std::vector<double> distance(n), weights(n), weighted(n);
    for (std::size_t i = 0; i < n; ++i) {
        const double dx = s.x[i] - x0;
        const double dy = s.y[i] - y0;
        const double u = dx * sin_t + dy * cos_t;
        const double v = dx * cos_t - dy * sin_t;
        distance[i] = std::hypot(u / aa, v / bb);
        weights[i] = directional_weight(distance[i], s.q[i], s.b_i[i]);
        weighted[i] = weights[i] * s.z[i];
    }
    const double total = pairwise_sum(weights.data(), n);
    if (total <= kEps) {
        return s.z[argmin_first(distance)];
    }
    return pairwise_sum(weighted.data(), n) / total;
}

std::vector<double> directional_trend_grid(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, double azimuth_deg, double a,
    double b, const std::vector<double>* q, const std::vector<double>* b_i,
    int max_cells_per_chunk) {
    const DirectionalSamples s =
        directional_sample_arrays(xs, ys, zs, q, b_i);
    positive_axis(a, "a");
    positive_axis(b, "b");
    const auto [a_eff_pre, b_eff_pre] = scaled_axes(a, b, s.x, s.y);
    const int chunk_size = max_cells_per_chunk;
    if (chunk_size <= 0) {
        throw std::invalid_argument("max_cells_per_chunk must be positive");
    }
    const std::size_t height = grid_y.size();
    const std::size_t width = grid_x.size();
    const std::size_t n_cells = height * width;
    if (s.z.empty() || height == 0 || width == 0) {
        return std::vector<double>(
            n_cells, std::numeric_limits<double>::quiet_NaN());
    }
    // directional_distance's own axis validation on the scaled pair.
    const double aa = positive_axis(a_eff_pre, "a");
    const double bb = positive_axis(b_eff_pre, "b");
    const std::size_t n = s.z.size();
    const double theta = azimuth_to_rad(azimuth_deg);
    const double cos_t = std::cos(theta);
    const double sin_t = std::sin(theta);

    std::vector<double> out(n_cells,
                            std::numeric_limits<double>::quiet_NaN());
    std::vector<double> distance(n), weights(n), weighted(n);
    for (std::size_t start = 0; start < n_cells;
         start += static_cast<std::size_t>(chunk_size)) {
        const std::size_t stop =
            std::min(start + static_cast<std::size_t>(chunk_size), n_cells);
        for (std::size_t cell = start; cell < stop; ++cell) {
            const double cx = grid_x[cell % width];
            const double cy = grid_y[cell / width];
            for (std::size_t j = 0; j < n; ++j) {
                const double dx = cx - s.x[j];
                const double dy = cy - s.y[j];
                const double u = dx * sin_t + dy * cos_t;
                const double v = dx * cos_t - dy * sin_t;
                distance[j] = std::hypot(u / aa, v / bb);
                weights[j] =
                    directional_weight(distance[j], s.q[j], s.b_i[j]);
                weighted[j] = weights[j] * s.z[j];
            }
            const double total = pairwise_sum(weights.data(), n);
            if (total > kEps) {
                out[cell] = pairwise_sum(weighted.data(), n) / total;
            } else {
                out[cell] = s.z[argmin_first(distance)];
            }
        }
    }
    return out;
}

}  // namespace pwb::mapping
