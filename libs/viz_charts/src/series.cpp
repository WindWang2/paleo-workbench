#include <pwb/viz_charts/series.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::viz_charts {

DownsampleResult lttb_downsample(const std::vector<double>& x_in,
                                 const std::vector<double>& y_in,
                                 int threshold) {
    // NaN filter first (Python masks ~isnan(x) & ~isnan(y)).
    std::vector<double> x, y;
    x.reserve(x_in.size());
    y.reserve(y_in.size());
    for (std::size_t i = 0; i < x_in.size() && i < y_in.size(); ++i) {
        if (!std::isnan(x_in[i]) && !std::isnan(y_in[i])) {
            x.push_back(x_in[i]);
            y.push_back(y_in[i]);
        }
    }
    DownsampleResult out;
    const std::size_t n_points = x.size();
    const auto thr = static_cast<std::size_t>(threshold);
    if (thr >= n_points || threshold <= 2) {
        out.x = std::move(x);
        out.y = std::move(y);
        return out;
    }

    const double bucket_size =
        static_cast<double>(n_points - 2) / static_cast<double>(threshold - 2);
    out.x.assign(thr, 0.0);
    out.y.assign(thr, 0.0);
    out.x.front() = x.front();
    out.y.front() = y.front();
    out.x.back() = x.back();
    out.y.back() = y.back();

    std::size_t a_idx = 0;
    for (int i = 0; i < threshold - 2; ++i) {
        const auto b_start =
            static_cast<std::size_t>(std::floor(i * bucket_size)) + 1;
        auto b_end = static_cast<std::size_t>(std::floor((i + 1) * bucket_size)) + 1;
        b_end = std::min(b_end, n_points - 1);

        if (b_start >= b_end) {
            out.x[static_cast<std::size_t>(i) + 1] = x[b_start];
            out.y[static_cast<std::size_t>(i) + 1] = y[b_start];
            a_idx = b_start;
            continue;
        }

        const auto next_b_start =
            static_cast<std::size_t>(std::floor((i + 1) * bucket_size)) + 1;
        auto next_b_end =
            static_cast<std::size_t>(std::floor((i + 2) * bucket_size)) + 1;
        next_b_end = std::min(next_b_end, n_points - 1);

        double c_x, c_y;
        if (next_b_start < next_b_end) {
            double sx = 0.0;
            double sy = 0.0;
            for (std::size_t k = next_b_start; k < next_b_end; ++k) {
                sx += x[k];
                sy += y[k];
            }
            c_x = sx / static_cast<double>(next_b_end - next_b_start);
            c_y = sy / static_cast<double>(next_b_end - next_b_start);
        } else {
            c_x = x.back();
            c_y = y.back();
        }

        const double a_x = x[a_idx];
        const double a_y = y[a_idx];

        // np.argmax semantics: strict first-max wins ties.
        double best_area = -1.0;
        std::size_t best_idx = b_start;
        for (std::size_t k = b_start; k < b_end; ++k) {
            const double area =
                std::fabs(a_x * (y[k] - c_y) + x[k] * (c_y - a_y) +
                          c_x * (a_y - y[k]));
            if (area > best_area) {
                best_area = area;
                best_idx = k;
            }
        }
        out.x[static_cast<std::size_t>(i) + 1] = x[best_idx];
        out.y[static_cast<std::size_t>(i) + 1] = y[best_idx];
        a_idx = best_idx;
    }
    return out;
}

Bounds series_bounds(const std::vector<double>& x, const std::vector<double>& y) {
    Bounds b;
    bool first = true;
    for (std::size_t i = 0; i < x.size() && i < y.size(); ++i) {
        if (!std::isfinite(x[i]) || !std::isfinite(y[i])) {
            continue;
        }
        if (first) {
            b.xmin = b.xmax = x[i];
            b.ymin = b.ymax = y[i];
            first = false;
        } else {
            b.xmin = std::min(b.xmin, x[i]);
            b.xmax = std::max(b.xmax, x[i]);
            b.ymin = std::min(b.ymin, y[i]);
            b.ymax = std::max(b.ymax, y[i]);
        }
    }
    return b;
}

}  // namespace pwb::viz_charts
