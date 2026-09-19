#include <pwb/viz/well_tie/tie_evaluator.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::viz::well_tie {

namespace {

double np_std(const std::vector<double>& values) {
    double sum = 0.0;
    for (double v : values) sum += v;
    const double mean = sum / static_cast<double>(values.size());
    double acc = 0.0;
    for (double v : values) acc += (v - mean) * (v - mean);
    return std::sqrt(acc / static_cast<double>(values.size()));
}

double np_nan_to_num(double v) {
    if (std::isnan(v)) return 0.0;
    if (v == std::numeric_limits<double>::infinity())
        return std::numeric_limits<double>::max();
    if (v == -std::numeric_limits<double>::infinity())
        return -std::numeric_limits<double>::max();
    return v;
}

}  // namespace

CrossCorrelation compute_cross_correlation(const std::vector<double>& s1,
                                           const std::vector<double>& s2) {
    std::vector<double> a;
    std::vector<double> b_raw;
    a.reserve(s1.size());
    b_raw.reserve(s2.size());
    for (double v : s1) a.push_back(np_nan_to_num(v));
    for (double v : s2) b_raw.push_back(np_nan_to_num(v));

    const std::size_t n = std::min(a.size(), b_raw.size());
    if (n == 0) return {0.0, 0};
    a.resize(n);
    std::vector<double> b(b_raw.begin(), b_raw.begin() + static_cast<long>(n));

    double mean_a = 0.0;
    double mean_b = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        mean_a += a[i];
        mean_b += b[i];
    }
    mean_a /= static_cast<double>(n);
    mean_b /= static_cast<double>(n);
    const double std_a = np_std(a);
    const double std_b = np_std(b);
    if (std_a == 0.0 || std_b == 0.0) return {0.0, 0};

    // corr = np.correlate(a - mean_a, b - mean_b, "full"); normalized by
    // max(1e-6, n * std_a * std_b); lag = -(argmax - (n-1)).
    const double norm = std::max(1e-6, static_cast<double>(n) * std_a * std_b);
    double best = -std::numeric_limits<double>::infinity();
    std::size_t best_k = 0;
    const double ac = mean_a;
    const double bc = mean_b;
    for (long long k = 0; k < static_cast<long long>(2 * n - 1); ++k) {
        // c[k] = sum_i (a[i]-ac) * (b[i-k+n-1]-bc) over valid i.
        double acc = 0.0;
        for (long long i = 0; i < static_cast<long long>(n); ++i) {
            const long long j = i - k + static_cast<long long>(n - 1);
            if (j < 0 || j >= static_cast<long long>(n)) continue;
            acc += (a[static_cast<std::size_t>(i)] - ac) *
                   (b[static_cast<std::size_t>(j)] - bc);
        }
        const double value = acc / norm;
        if (value > best) {
            best = value;
            best_k = static_cast<std::size_t>(k);
        }
    }
    const int lag = -static_cast<int>(
        static_cast<long long>(best_k) - static_cast<long long>(n - 1));
    return {best, lag};
}

TieQuality evaluate_tie_quality(const std::vector<double>& synthetic,
                                const std::vector<double>& seismic) {
    const CrossCorrelation cc =
        compute_cross_correlation(synthetic, seismic);
    TieQuality out;
    out.r = cc.max_r;
    out.lag = cc.lag;
    const long long n_syn = static_cast<long long>(synthetic.size());
    const long long n_seis = static_cast<long long>(seismic.size());
    if (n_syn == 0 || n_seis == 0) return out;

    const long long begin = std::max(0LL, -static_cast<long long>(out.lag));
    const long long end = std::min(n_syn, n_seis - out.lag);
    for (long long i = begin; i < end; ++i) {
        out.residual.push_back(
            std::abs(synthetic[static_cast<std::size_t>(i)] -
                     seismic[static_cast<std::size_t>(i + out.lag)]));
    }
    return out;
}

}  // namespace pwb::viz::well_tie
