#include <pwb/viz/well_tie/auto_tie.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::viz::well_tie {

namespace {

double np_std(const std::vector<double>& values) {
    // ddof=0 population std, numpy pairwise summation effects are below
    // the comparison threshold for the constant-trace early exit.
    double sum = 0.0;
    for (double v : values) sum += v;
    const double mean = sum / static_cast<double>(values.size());
    double acc = 0.0;
    for (double v : values) acc += (v - mean) * (v - mean);
    return std::sqrt(acc / static_cast<double>(values.size()));
}

}  // namespace

AutoTieResult correlate_synthetic_to_trace(
    const std::vector<double>& synthetic,
    const std::vector<double>& seismic_trace) {
    const long long n_s = static_cast<long long>(synthetic.size());
    const long long n_t = static_cast<long long>(seismic_trace.size());
    if (n_s == 0 || n_t == 0) return {0, 0.0};

    if (np_std(synthetic) < 1e-10 || np_std(seismic_trace) < 1e-10) {
        return {0, 0.0};
    }

    const long long n_lags = n_s + n_t - 1;
    // Overlap window on the synthetic axis per lag j (lag = j - (n_s-1)).
    const long long min_overlap =
        std::max(2LL, std::min(n_s, n_t) / 4);

    // Prefix sums for O(1) window moments.
    std::vector<double> cs(n_s + 1, 0.0), cs2(n_s + 1, 0.0);
    std::vector<double> ct(n_t + 1, 0.0), ct2(n_t + 1, 0.0);
    for (long long i = 0; i < n_s; ++i) {
        cs[i + 1] = cs[i] + synthetic[static_cast<std::size_t>(i)];
        cs2[i + 1] =
            cs2[i] + synthetic[static_cast<std::size_t>(i)] * synthetic[static_cast<std::size_t>(i)];
    }
    for (long long i = 0; i < n_t; ++i) {
        ct[i + 1] = ct[i] + seismic_trace[static_cast<std::size_t>(i)];
        ct2[i + 1] =
            ct2[i] + seismic_trace[static_cast<std::size_t>(i)] * seismic_trace[static_cast<std::size_t>(i)];
    }

    // np.correlate(seismic, synthetic, "full")[j] = sum_i synthetic[i] *
    // seismic[i + lag_j]; direct O(n_s) per lag (full scan is the
    // numerical definition; prefix sums only cover the moments).
    auto sum_st = [&](long long lag, long long start_s, long long end_s) {
        double acc = 0.0;
        for (long long i = start_s; i < end_s; ++i) {
            acc += synthetic[static_cast<std::size_t>(i)] *
                   seismic_trace[static_cast<std::size_t>(i + lag)];
        }
        return acc;
    };

    bool any_feasible = false;
    long long best_j = 0;
    double best_r = -std::numeric_limits<double>::infinity();
    for (long long j = 0; j < n_lags; ++j) {
        const long long lag = j - (n_s - 1);
        const long long start_s = std::max(0LL, -lag);
        const long long end_s = std::min(n_s, n_t - lag);
        const long long n_overlap = end_s - start_s;
        if (n_overlap < min_overlap) continue;
        any_feasible = true;

        const double sum_s = cs[static_cast<std::size_t>(end_s)] -
                             cs[static_cast<std::size_t>(start_s)];
        const double sum_s2 = cs2[static_cast<std::size_t>(end_s)] -
                              cs2[static_cast<std::size_t>(start_s)];
        const long long start_t = start_s + lag;
        const long long end_t = end_s + lag;
        const double sum_t = ct[static_cast<std::size_t>(end_t)] -
                             ct[static_cast<std::size_t>(start_t)];
        const double sum_t2 = ct2[static_cast<std::size_t>(end_t)] -
                              ct2[static_cast<std::size_t>(start_t)];

        const double l = static_cast<double>(n_overlap);
        const double mean_s = sum_s / l;
        const double mean_t = sum_t / l;
        const double var_s = std::max(sum_s2 / l - mean_s * mean_s, 0.0);
        const double var_t = std::max(sum_t2 / l - mean_t * mean_t, 0.0);
        const double st = sum_st(lag, start_s, end_s);
        const double cov = st / l - mean_s * mean_t;
        const double denom = std::sqrt(var_s * var_t);
        double r = 0.0;
        if (denom > 0.0) r = cov / denom;
        // Strictly-greater keeps the FIRST maximum (numpy argmax parity).
        if (r > best_r) {
            best_r = r;
            best_j = j;
        }
    }
    if (!any_feasible) return {0, 0.0};
    const long long shift = best_j - (n_s - 1);
    return {static_cast<int>(shift), std::min(best_r, 1.0)};
}

}  // namespace pwb::viz::well_tie
