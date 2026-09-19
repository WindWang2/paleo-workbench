#include "pwb/ui_workers/dtw_propagation.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::ui_workers {

namespace {

constexpr double kInf = std::numeric_limits<double>::infinity();

// np.median over a non-decreasing int list (path j's are monotone after
// the reverse) -> int() truncation toward zero, matching Python.
int median_index(const std::vector<int>& idxs) {
    const std::size_t k = idxs.size();
    if (k % 2 == 1) return idxs[k / 2];
    return static_cast<int>((static_cast<double>(idxs[k / 2 - 1]) +
                             static_cast<double>(idxs[k / 2])) /
                            2.0);
}

}  // namespace

DtwCorrelateResult dtw_engine_correlate(
    const std::vector<double>& ref_values,
    const std::vector<double>& ref_depths,
    const std::vector<double>& tgt_values,
    const std::vector<double>& tgt_depths, int band_radius,
    double ref_depth) {
    constexpr DtwCorrelateResult kInfeasible{false, 0.0, 1.0, 0.0};
    const auto all_finite = [](const std::vector<double>& v) {
        return std::all_of(v.begin(), v.end(),
                           [](double x) { return std::isfinite(x); });
    };
    const int n = static_cast<int>(ref_values.size());
    const int m = static_cast<int>(tgt_values.size());
    if (n < 2 || m < 2) return kInfeasible;
    if (!all_finite(ref_values) || !all_finite(tgt_values))
        return kInfeasible;
    if (static_cast<int>(ref_depths.size()) != n ||
        static_cast<int>(tgt_depths.size()) != m)
        return kInfeasible;
    if (!all_finite(ref_depths) || !all_finite(tgt_depths))
        return kInfeasible;
    if (std::abs(m - n) > band_radius) return kInfeasible;

    const int width = 2 * band_radius + 1;
    const auto cidx = [&](int i, int j) { return j - (i - band_radius); };
    std::vector<double> cost(static_cast<std::size_t>(n) * width, kInf);
    const auto at = [&](int i, int j) -> double& {
        return cost[static_cast<std::size_t>(i) * width + cidx(i, j)];
    };

    at(0, 0) = std::abs(ref_values[0] - tgt_values[0]);
    for (int j = 1; j < std::min(m, band_radius + 1); ++j) {
        at(0, j) = at(0, j - 1) + std::abs(ref_values[0] - tgt_values[j]);
    }

    // Min-plus prefix scan per row (NumPy vectorized in Python — same
    // arithmetic here).
    for (int i = 1; i < n; ++i) {
        const int j_start = std::max(0, i - band_radius);
        const int j_end = std::min(m, i + band_radius + 1);
        double prefix = 0.0;
        double run_min = kInf;
        for (int j = j_start; j < j_end; ++j) {
            const int c = cidx(i, j);
            const double diagonal = cost[static_cast<std::size_t>(i - 1) *
                                             width +
                                         c];
            const double vertical =
                (c + 1 < width)
                    ? cost[static_cast<std::size_t>(i - 1) * width + c + 1]
                    : kInf;
            const double base = std::min(diagonal, vertical);
            const double dist = std::abs(ref_values[i] - tgt_values[j]);
            run_min = std::min(run_min, base - prefix);
            prefix += dist;
            cost[static_cast<std::size_t>(i) * width + c] =
                prefix + run_min;
        }
    }

    // Backtrace — candidates diag, vert, horiz; Python min() keeps the
    // FIRST minimum on ties so compare strictly.
    int i = n - 1, j = m - 1;
    std::vector<std::pair<int, int>> path{{i, j}};
    double total_dist = 0.0;
    while (i > 0 || j > 0) {
        double best = kInf;
        int bi = -1, bj = -1;
        if (i > 0 && j > 0) {
            const int c = cidx(i - 1, j - 1);
            if (0 <= c && c < width) {
                const double v = cost[static_cast<std::size_t>(i - 1) *
                                          width +
                                      c];
                if (v < best) {
                    best = v;
                    bi = i - 1;
                    bj = j - 1;
                }
            }
        }
        if (i > 0) {
            const int c = cidx(i - 1, j);
            if (0 <= c && c < width) {
                const double v = cost[static_cast<std::size_t>(i - 1) *
                                          width +
                                      c];
                if (v < best) {
                    best = v;
                    bi = i - 1;
                    bj = j;
                }
            }
        }
        if (j > 0) {
            const int c = cidx(i, j - 1);
            if (0 <= c && c < width) {
                const double v =
                    cost[static_cast<std::size_t>(i) * width + c];
                if (v < best) {
                    best = v;
                    bi = i;
                    bj = j - 1;
                }
            }
        }
        if (bi < 0 || best == kInf) break;
        total_dist += std::abs(ref_values[i] - tgt_values[j]);
        i = bi;
        j = bj;
        path.emplace_back(i, j);
    }
    total_dist += std::abs(ref_values[0] - tgt_values[0]);
    std::reverse(path.begin(), path.end());

    const double normalized_cost =
        total_dist / static_cast<double>(path.size());

    int ref_idx;
    if (std::isnan(ref_depth)) {
        ref_idx = n / 2;
    } else {
        ref_idx = 0;
        double best_d = std::abs(ref_depths[0] - ref_depth);
        for (int k = 1; k < n; ++k) {
            const double d = std::abs(ref_depths[k] - ref_depth);
            if (d < best_d) {
                best_d = d;
                ref_idx = k;
            }
        }
    }

    std::vector<int> target_indices;
    for (const auto& [pi, pj] : path) {
        if (pi == ref_idx) target_indices.push_back(pj);
    }
    int matched_target_idx;
    if (!target_indices.empty()) {
        matched_target_idx = median_index(target_indices);
    } else {
        std::size_t closest = 0;
        int best_d = std::abs(path[0].first - ref_idx);
        for (std::size_t k = 1; k < path.size(); ++k) {
            const int d = std::abs(path[k].first - ref_idx);
            if (d < best_d) {
                best_d = d;
                closest = k;
            }
        }
        matched_target_idx = path[closest].second;
    }

    const double suggested = tgt_depths[matched_target_idx];
    const auto max_abs = [](const std::vector<double>& v) {
        double m_abs = 0.0;
        for (double x : v) m_abs = std::max(m_abs, std::abs(x));
        return m_abs;
    };
    const double max_diff = max_abs(ref_values) + max_abs(tgt_values);
    const double norm_cost =
        std::min(normalized_cost / std::max(1e-6, max_diff), 1.0);
    return {true, suggested, norm_cost, 1.0 - norm_cost};
}

int bounded_dtw_band(int n_samples, std::optional<int> band_radius) {
    const int n = std::max(1, n_samples);
    const int requested = band_radius.value_or(std::max(20, n / 4));
    const int cap =
        std::max(20, static_cast<int>((kMaxDtwCells / n - 1) / 2));
    return std::min(std::max(1, requested), cap);
}

std::vector<std::pair<std::string, double>> compute_dtw_propagation(
    const DtwSceneSlice& scene, const std::string& ref_well, double ref_depth,
    int band_radius, const DtwCorrelateFn& correlate_fn,
    const std::function<void(int, int)>& progress_callback) {
    const auto ref_it =
        std::find_if(scene.wells.begin(), scene.wells.end(),
                     [&](const DtwWellSlice& w) { return w.name == ref_well; });
    if (ref_it == scene.wells.end()) return {};
    if (!ref_it->depths || !ref_it->values) return {};
    const std::size_t ref_idx =
        static_cast<std::size_t>(ref_it - scene.wells.begin());

    // targets = every well except the reference INDEX (Python i != ref_idx
    // — a later duplicate name is still a target).
    const int total = static_cast<int>(scene.wells.size()) - 1;
    std::vector<std::pair<std::string, double>> pairs;
    int step = 0;
    for (std::size_t i = 0; i < scene.wells.size(); ++i) {
        if (i == ref_idx) continue;
        const auto& well = scene.wells[i];
        ++step;
        if (!well.depths || !well.values) {
            if (progress_callback) progress_callback(step, total);
            continue;
        }
        if (!correlate_fn) {
            throw KernelUnavailable("geoviz DTWEngine.correlate");
        }
        const DtwCorrelateResult result =
            correlate_fn(*ref_it->values, *ref_it->depths, *well.values,
                         *well.depths, band_radius, ref_depth);
        // An infeasible alignment must not fabricate a ghost pick (#539).
        if (!result.feasible) {
            if (progress_callback) progress_callback(step, total);
            continue;
        }
        pairs.emplace_back(well.name, result.suggested_depth);
        if (progress_callback) progress_callback(step, total);
    }
    return pairs;
}

DtwPropagationResult run_dtw_propagation(const DtwPropagationInput& input,
                                         job::JobContext& ctx) {
    return with_py_errors([&]() -> DtwPropagationResult {
        // recommendation first — failure degrades to nullopt, emitted either
        // way when recommend_fn was supplied (recommendation_ready parity).
        if (input.recommend_fn) {
            std::any recommendation;
            try {
                recommendation = input.recommend_fn();
            } catch (const std::exception&) {
                recommendation = std::any{};
            }
            if (input.on_recommendation) {
                input.on_recommendation(recommendation);
            }
        }
        ctx.check_cancelled();
        const int band = bounded_dtw_band(input.n_samples, input.band_radius);
        const auto on_progress = [&](int done, int total) {
            // The Python progress callback raises JobCancelled on the flag.
            ctx.check_cancelled();
            if (input.on_progress) input.on_progress(done, total);
            ctx.report_progress(static_cast<double>(done),
                                static_cast<double>(total));
        };
        std::vector<std::pair<std::string, double>> pairs;
        if (input.compute_fn) {
            pairs = input.compute_fn(input.ref_well, input.ref_depth, band,
                                     on_progress);
        } else {
            pairs = compute_dtw_propagation(input.scene, input.ref_well,
                                            input.ref_depth, band,
                                            input.correlate_fn, on_progress);
        }
        return {std::move(pairs)};
    });
}

job::JobSpec make_dtw_propagation_job_spec(
    DtwPropagationInput input,
    std::function<void(const DtwPropagationResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "compute.dtw_propagation";
    spec.title = "DTW 拾取传播";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_dtw_propagation(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const DtwPropagationResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
