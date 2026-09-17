// DTW well-log matcher kernel — faithful port of
// paleo_workbench/viz/dtw_log_matcher.py. Comment notes cite the Python
// issue numbers (#897 window guard, #1054 peak-preserving decimation) where
// a line only makes sense with that context.

#include <pwb/well_science/dtw.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <limits>

namespace pwb::well_science {
namespace {

// numpy's pairwise summation (numpy/_core/src/umath/loops_utils.h), replicated
// so mean/std match np.mean/np.std bit-exactly; the DP backtracker breaks ties
// with exact `==`, so bit-identical normalized curves are what makes the
// C++ path identical to Python's (see decisions D3).
double pairwise_sum(const double* a, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; ++i) res += a[i];
        return res;
    }
    constexpr std::size_t kBlockSize = 128;
    if (n <= kBlockSize) {
        double r[8] = {a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]};
        std::size_t i = 8;
        for (; i < n - (n % 8); i += 8) {
            for (std::size_t k = 0; k < 8; ++k) r[k] += a[i + k];
        }
        double res =
            ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(a, n2) + pairwise_sum(a + n2, n - n2);
}

double numpy_mean(const double* a, std::size_t n) {
    return pairwise_sum(a, n) / static_cast<double>(n);
}

// numpy argmin/argmax semantics over one bin: first extremal index wins;
// any NaN wins immediately (first NaN index). Returns an absolute index.
std::int64_t bin_argext(const std::vector<double>& curve, std::int64_t begin,
                        std::int64_t end, bool maximum) {
    std::int64_t best = begin;
    bool best_is_nan = std::isnan(curve[static_cast<std::size_t>(begin)]);
    for (std::int64_t k = begin + 1; k < end; ++k) {
        const double v = curve[static_cast<std::size_t>(k)];
        if (std::isnan(v)) {
            if (!best_is_nan) {
                best = k;
                best_is_nan = true;
            }
            continue;
        }
        if (best_is_nan) continue;
        const double best_v = curve[static_cast<std::size_t>(best)];
        if (maximum ? (v > best_v) : (v < best_v)) best = k;
    }
    return best;
}

}  // namespace

std::vector<double> normalized(const std::vector<double>& curve) {
    std::vector<double> values = curve;
    if (values.empty()) return values;

    std::vector<double> finite;
    finite.reserve(values.size());
    for (const double v : values) {
        if (std::isfinite(v)) finite.push_back(v);
    }
    // Impute LAS nulls (NaN/±inf) with the finite mean; no finite sample -> 0.
    const double fill =
        finite.empty() ? 0.0
                       : numpy_mean(finite.data(), finite.size());
    for (double& v : values) {
        if (!std::isfinite(v)) v = fill;
    }

    const std::size_t n = values.size();
    const double* data = values.data();
    std::vector<double> sq(n);
    double arrmean = numpy_mean(data, n);
    for (std::size_t i = 0; i < n; ++i) {
        const double d = data[i] - arrmean;
        sq[i] = d * d;
    }
    double std_dev = std::sqrt(numpy_mean(sq.data(), n));
    if (!std::isfinite(std_dev) || std_dev <= 0.0) std_dev = 1.0;
    for (double& v : values) v = (v - arrmean) / std_dev;
    return values;
}

Downsampling min_max_downsample(const std::vector<double>& curve,
                                std::int64_t bin_size) {
    Downsampling out;
    const std::int64_t n = static_cast<std::int64_t>(curve.size());
    if (n == 0 || bin_size <= 1) {
        out.values = curve;
        out.indices.resize(static_cast<std::size_t>(n));
        for (std::int64_t i = 0; i < n; ++i) {
            out.indices[static_cast<std::size_t>(i)] = i;
        }
        return out;
    }
    for (std::int64_t start = 0; start < n; start += bin_size) {
        const std::int64_t end = std::min(start + bin_size, n);
        const std::int64_t min_idx = bin_argext(curve, start, end, false);
        const std::int64_t max_idx = bin_argext(curve, start, end, true);
        if (min_idx < max_idx) {
            out.values.push_back(curve[static_cast<std::size_t>(min_idx)]);
            out.indices.push_back(min_idx);
            out.values.push_back(curve[static_cast<std::size_t>(max_idx)]);
            out.indices.push_back(max_idx);
        } else if (max_idx < min_idx) {
            out.values.push_back(curve[static_cast<std::size_t>(max_idx)]);
            out.indices.push_back(max_idx);
            out.values.push_back(curve[static_cast<std::size_t>(min_idx)]);
            out.indices.push_back(min_idx);
        } else {
            // Flat segment: minimum and maximum coincide.
            out.values.push_back(curve[static_cast<std::size_t>(min_idx)]);
            out.indices.push_back(min_idx);
        }
    }
    return out;
}

AlignmentResult match_curves(const std::vector<double>& curve_ref,
                             const std::vector<double>& curve_target,
                             std::optional<std::int64_t> window) {
    const AlignmentResult failed{std::numeric_limits<double>::infinity(), {},
                                 {}};
    const std::vector<double> c_ref = normalized(curve_ref);
    const std::vector<double> c_target = normalized(curve_target);
    const std::int64_t n_ref = static_cast<std::int64_t>(c_ref.size());
    const std::int64_t n_target = static_cast<std::int64_t>(c_target.size());

    if (n_ref == 0 || n_target == 0) return failed;

    // Each decimated segment keeps up to two samples, hence the 2x scale.
    std::int64_t stride = 1;
    if (kMaxCostCells > 0 && n_ref * n_target > kMaxCostCells) {
        const double scale =
            std::sqrt(static_cast<double>(n_ref * n_target) /
                      static_cast<double>(kMaxCostCells));
        stride = std::max<std::int64_t>(
            2, static_cast<std::int64_t>(std::ceil(scale * 2.0)));
    }

    std::vector<double> d_ref;
    std::vector<double> d_target;
    std::vector<std::int64_t> ref_indices;
    std::vector<std::int64_t> target_indices;
    if (stride > 1) {
        Downsampling ds_ref = min_max_downsample(c_ref, stride);
        Downsampling ds_target = min_max_downsample(c_target, stride);
        // Decimation redistributes the value statistics; renormalize.
        d_ref = normalized(ds_ref.values);
        d_target = normalized(ds_target.values);
        ref_indices = std::move(ds_ref.indices);
        target_indices = std::move(ds_target.indices);
    } else {
        d_ref = c_ref;
        d_target = c_target;
        ref_indices.resize(c_ref.size());
        for (std::int64_t i = 0; i < n_ref; ++i) {
            ref_indices[static_cast<std::size_t>(i)] = i;
        }
        target_indices.resize(c_target.size());
        for (std::int64_t i = 0; i < n_target; ++i) {
            target_indices[static_cast<std::size_t>(i)] = i;
        }
    }
    const std::int64_t d_n_ref = static_cast<std::int64_t>(d_ref.size());
    const std::int64_t d_n_target = static_cast<std::int64_t>(d_target.size());

    if (d_n_ref == 0 || d_n_target == 0) return failed;

    // Sakoe-Chiba band that cannot reach the DP endpoint -> empty alignment
    // instead of a fabricated path (#897).
    if (window.has_value() && std::llabs(d_n_ref - d_n_target) > *window) {
        return failed;
    }

    const std::size_t width = static_cast<std::size_t>(d_n_target) + 1;
    std::vector<double> cost_matrix((static_cast<std::size_t>(d_n_ref) + 1) *
                                        width,
                                    std::numeric_limits<double>::infinity());
    cost_matrix[0] = 0.0;
    for (std::int64_t i = 1; i <= d_n_ref; ++i) {
        for (std::int64_t j = 1; j <= d_n_target; ++j) {
            if (window.has_value() && std::llabs(i - j) > *window) continue;
            const double diff = d_ref[static_cast<std::size_t>(i - 1)] -
                                d_target[static_cast<std::size_t>(j - 1)];
            const double dist = diff * diff;
            double best = cost_matrix[static_cast<std::size_t>(i - 1) * width +
                                      static_cast<std::size_t>(j)];  // insertion
            const double deletion =
                cost_matrix[static_cast<std::size_t>(i) * width +
                            static_cast<std::size_t>(j - 1)];  // deletion
            const double match =
                cost_matrix[static_cast<std::size_t>(i - 1) * width +
                            static_cast<std::size_t>(j - 1)];  // match
            if (deletion < best) best = deletion;
            if (match < best) best = match;
            cost_matrix[static_cast<std::size_t>(i) * width +
                        static_cast<std::size_t>(j)] = dist + best;
        }
    }

    // Backtrack to (0, 0); the elif order (diag, insertion, else deletion)
    // is the Python tie-break contract and must not be reordered.
    std::int64_t i = d_n_ref;
    std::int64_t j = d_n_target;
    std::vector<std::int64_t> path_ref;
    std::vector<std::int64_t> path_target;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0) {
            path_ref.push_back(i - 1);
            path_target.push_back(j - 1);
            const double up = cost_matrix[static_cast<std::size_t>(i - 1) *
                                              width +
                                          static_cast<std::size_t>(j)];
            const double left = cost_matrix[static_cast<std::size_t>(i) *
                                                width +
                                            static_cast<std::size_t>(j - 1)];
            const double diag =
                cost_matrix[static_cast<std::size_t>(i - 1) * width +
                            static_cast<std::size_t>(j - 1)];
            const double min_val = std::min(std::min(up, left), diag);
            if (min_val == diag) {
                --i;
                --j;
            } else if (min_val == up) {
                --i;
            } else {
                --j;
            }
        } else if (i > 0) {
            path_ref.push_back(i - 1);
            path_target.push_back(0);
            --i;
        } else {
            path_ref.push_back(0);
            path_target.push_back(j - 1);
            --j;
        }
    }
    std::reverse(path_ref.begin(), path_ref.end());
    std::reverse(path_target.begin(), path_target.end());

    // Map the warping path back to original sample space (#1054); the index
    // arrays are strictly increasing, so the mapped path stays monotone.
    if (stride > 1) {
        for (auto& idx : path_ref) {
            idx = ref_indices[static_cast<std::size_t>(idx)];
        }
        for (auto& idx : path_target) {
            idx = target_indices[static_cast<std::size_t>(idx)];
        }
    }

    return AlignmentResult{
        cost_matrix[static_cast<std::size_t>(d_n_ref) * width +
                    static_cast<std::size_t>(d_n_target)],
        std::move(path_ref), std::move(path_target)};
}

std::int64_t transfer_top_index(std::int64_t ref_top_idx,
                                const std::vector<std::int64_t>& path_ref,
                                const std::vector<std::int64_t>& path_target) {
    if (path_ref.empty() || path_target.empty()) return ref_top_idx;

    std::int64_t best_idx = 0;
    // Python sentinel: min_dist starts at float("inf"), so the first pair
    // always updates.
    double min_dist = std::numeric_limits<double>::infinity();
    const std::size_t count = std::min(path_ref.size(), path_target.size());
    for (std::size_t k = 0; k < count; ++k) {
        const double dist =
            static_cast<double>(std::llabs(path_ref[k] - ref_top_idx));
        if (dist < min_dist) {
            min_dist = dist;
            best_idx = path_target[k];
        }
    }
    return best_idx;
}

}  // namespace pwb::well_science
