#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/crs_policy.hpp>

#include <algorithm>
#include <cmath>
#include <cctype>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pwb::mapping {
namespace {

constexpr double kEps = 1e-12;
constexpr double kInf = std::numeric_limits<double>::infinity();
constexpr int kKrigingNeighborhoodCap = 256;
const char* kModels[] = {"spherical", "exponential", "gaussian"};

std::string to_lower(std::string s) {
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s;
}

bool is_kriging_method(const std::string& method) {
    const std::string m = to_lower(method);
    return m == "kriging" || m == "ordinary_kriging" || m == "ok";
}

bool qc_ok(const std::string& flag) {
    return flag == "ok" || flag == "good" || flag.empty();
}

std::string join_issues(const std::vector<std::string>& issues) {
    std::string out;
    for (std::size_t i = 0; i < issues.size(); ++i) {
        if (i) out += "; ";
        out += issues[i];
    }
    return out;
}

double mean_of(const std::vector<double>& z) {
    double s = 0.0;
    for (double v : z) s += v;
    return z.empty() ? 0.0 : s / static_cast<double>(z.size());
}

double population_var(const std::vector<double>& z) {
    if (z.empty()) return 0.0;
    const double m = mean_of(z);
    double s = 0.0;
    for (double v : z) {
        const double d = v - m;
        s += d * d;
    }
    return s / static_cast<double>(z.size());
}

int digitize_right_open(double x, const std::vector<double>& edges) {
    return static_cast<int>(
        std::upper_bound(edges.begin(), edges.end(), x) - edges.begin());
}

struct Neighbor {
    double dist;
    std::size_t idx;
};

bool neighbor_less(const Neighbor& a, const Neighbor& b) {
    if (a.dist < b.dist) return true;
    if (b.dist < a.dist) return false;
    return a.idx < b.idx;
}

std::vector<Neighbor> k_nearest(double tx, double ty,
                                const std::vector<double>& xs,
                                const std::vector<double>& ys, int k,
                                std::optional<double> radius) {
    const std::size_t n = xs.size();
    std::vector<Neighbor> all(n);
    for (std::size_t j = 0; j < n; ++j) {
        const double dx = tx - xs[j];
        const double dy = ty - ys[j];
        double dist = std::sqrt(dx * dx + dy * dy);
        std::size_t idx = j;
        if (radius.has_value() && dist > *radius) {
            dist = kInf;
            idx = n;
        }
        all[j] = {dist, idx};
    }
    const int kk = std::max(1, std::min(k, static_cast<int>(n)));
    if (kk < static_cast<int>(n)) {
        std::partial_sort(all.begin(), all.begin() + kk, all.end(),
                          neighbor_less);
        all.resize(static_cast<std::size_t>(kk));
    } else {
        std::sort(all.begin(), all.end(), neighbor_less);
    }
    return all;
}

bool point_in_ring(double x, double y, const std::vector<Point>& ring) {
    const std::size_t count = ring.size();
    if (count < 3) return false;
    bool crosses = false;
    for (std::size_t index = 0; index < count; ++index) {
        const double x1 = ring[index][0];
        const double y1 = ring[index][1];
        const double x2 = ring[(index + 1) % count][0];
        const double y2 = ring[(index + 1) % count][1];
        if (y1 == y2) continue;
        if ((y1 > y) != (y2 > y)) {
            const double t = (y - y1) / (y2 - y1);
            if (x < x1 + t * (x2 - x1)) crosses = !crosses;
        }
    }
    return crosses;
}

void apply_domain_mask(FactorGrid& result, const std::vector<Point>& boundary) {
    if (boundary.empty()) return;
    if (boundary.size() < 3) {
        throw std::invalid_argument("boundary ring needs at least 3 vertices");
    }
    const std::size_t h = result.grid_y.size();
    const std::size_t w = result.grid_x.size();
    int masked = 0;
    for (std::size_t i = 0; i < h; ++i) {
        for (std::size_t j = 0; j < w; ++j) {
            const std::size_t at = i * w + j;
            if (point_in_ring(result.grid_x[j], result.grid_y[i], boundary)) {
                continue;
            }
            if (std::isfinite(result.grid_z[at])) {
                ++masked;
                result.grid_z[at] = std::numeric_limits<float>::quiet_NaN();
            }
        }
    }
    result.domain_masked_cells = masked;
}

bool solve_linear(std::vector<double> A, std::vector<double> b, int n,
                  std::vector<double>& x) {
    x.assign(static_cast<std::size_t>(n), 0.0);
    for (int col = 0; col < n; ++col) {
        int best = col;
        double best_abs = std::fabs(A[static_cast<std::size_t>(col * n + col)]);
        for (int row = col + 1; row < n; ++row) {
            const double v =
                std::fabs(A[static_cast<std::size_t>(row * n + col)]);
            if (v > best_abs) {
                best_abs = v;
                best = row;
            }
        }
        if (!(best_abs > 0.0)) return false;
        if (best != col) {
            for (int j = 0; j < n; ++j) {
                std::swap(A[static_cast<std::size_t>(col * n + j)],
                          A[static_cast<std::size_t>(best * n + j)]);
            }
            std::swap(b[static_cast<std::size_t>(col)],
                      b[static_cast<std::size_t>(best)]);
        }
        const double diag = A[static_cast<std::size_t>(col * n + col)];
        for (int row = col + 1; row < n; ++row) {
            const double f =
                A[static_cast<std::size_t>(row * n + col)] / diag;
            for (int j = col + 1; j < n; ++j) {
                A[static_cast<std::size_t>(row * n + j)] -=
                    f * A[static_cast<std::size_t>(col * n + j)];
            }
            b[static_cast<std::size_t>(row)] -=
                f * b[static_cast<std::size_t>(col)];
        }
    }
    for (int i = n - 1; i >= 0; --i) {
        double s = b[static_cast<std::size_t>(i)];
        for (int j = i + 1; j < n; ++j) {
            s -= A[static_cast<std::size_t>(i * n + j)]
                 * x[static_cast<std::size_t>(j)];
        }
        const double diag = A[static_cast<std::size_t>(i * n + i)];
        if (!(std::fabs(diag) > 0.0)) return false;
        x[static_cast<std::size_t>(i)] = s / diag;
    }
    return true;
}

bool solve_lstsq(const std::vector<double>& A, const std::vector<double>& b,
                 int n, std::vector<double>& x) {
    // Last-resort normal equations (Python: np.linalg.lstsq / SVD). Only
    // reached when both the raw and scaled-ridge OK systems are singular.
    std::vector<double> ata(static_cast<std::size_t>(n * n), 0.0);
    std::vector<double> atb(static_cast<std::size_t>(n), 0.0);
    for (int i = 0; i < n; ++i) {
        for (int k = 0; k < n; ++k) {
            atb[static_cast<std::size_t>(i)] +=
                A[static_cast<std::size_t>(k * n + i)]
                * b[static_cast<std::size_t>(k)];
            for (int j = 0; j < n; ++j) {
                ata[static_cast<std::size_t>(i * n + j)] +=
                    A[static_cast<std::size_t>(k * n + i)]
                    * A[static_cast<std::size_t>(k * n + j)];
            }
        }
    }
    return solve_linear(std::move(ata), std::move(atb), n, x);
}

std::vector<double> solve_ok_system(const std::vector<double>& K,
                                    const std::vector<double>& rhs, int n,
                                    int cov_n, double ridge) {
    std::vector<double> w;
    if (solve_linear(K, rhs, n, w)) return w;
    std::vector<double> regularized = K;
    for (int i = 0; i < cov_n; ++i) {
        regularized[static_cast<std::size_t>(i * n + i)] +=
            ridge * static_cast<double>(cov_n);
    }
    if (solve_linear(regularized, rhs, n, w)) return w;
    if (!solve_lstsq(regularized, rhs, n, w)) {
        w.assign(static_cast<std::size_t>(n), 0.0);
    }
    return w;
}

double model_sv_at(double h, double nugget, double psill, double r,
                   const std::string& model) {
    r = std::max(r, 1e-9);
    double shape = 0.0;
    if (model == "spherical") {
        double hr = h / r;
        if (hr < 0.0) hr = 0.0;
        if (hr > 1.0) hr = 1.0;
        shape = 1.5 * hr - 0.5 * hr * hr * hr;
    } else if (model == "gaussian") {
        const double t = h / r;
        shape = 1.0 - std::exp(-3.0 * t * t);
    } else {
        shape = 1.0 - std::exp(-3.0 * h / r);
    }
    return nugget + psill * shape;
}

std::string canonical_model(const std::string& model) {
    const std::string m = to_lower(model);
    for (const char* known : kModels) {
        if (m == known) return m;
    }
    return "spherical";
}

struct Empiric {
    std::vector<double> lag;
    std::vector<double> sv;
};

Empiric empirical_variogram(const std::vector<double>& h_pairs,
                            const std::vector<double>& sv_pairs,
                            double max_lag, int n_bins = 12) {
    std::vector<double> h;
    std::vector<double> sv;
    h.reserve(h_pairs.size());
    sv.reserve(sv_pairs.size());
    for (std::size_t i = 0; i < h_pairs.size(); ++i) {
        if (h_pairs[i] > 1e-12 && h_pairs[i] <= max_lag) {
            h.push_back(h_pairs[i]);
            sv.push_back(sv_pairs[i]);
        }
    }
    Empiric out;
    if (static_cast<int>(h.size()) < n_bins) return out;
    const std::vector<double> edges = linspace(0.0, max_lag, n_bins + 1);
    std::vector<double> sums(static_cast<std::size_t>(n_bins), 0.0);
    std::vector<int> counts(static_cast<std::size_t>(n_bins), 0);
    for (std::size_t i = 0; i < h.size(); ++i) {
        int idx = digitize_right_open(h[i], edges) - 1;
        if (idx < 0) idx = 0;
        if (idx > n_bins - 1) idx = n_bins - 1;
        sums[static_cast<std::size_t>(idx)] += sv[i];
        counts[static_cast<std::size_t>(idx)] += 1;
    }
    for (int i = 0; i < n_bins; ++i) {
        if (counts[static_cast<std::size_t>(i)] > 0) {
            out.lag.push_back(0.5 * (edges[static_cast<std::size_t>(i)]
                                     + edges[static_cast<std::size_t>(i + 1)]));
            out.sv.push_back(sums[static_cast<std::size_t>(i)]
                             / static_cast<double>(
                                   counts[static_cast<std::size_t>(i)]));
        }
    }
    return out;
}

struct VariogramFit {
    double nugget = 0.0;
    double psill = 0.0;
    double range = 0.0;
    int bins = 0;
};

VariogramFit fit_variogram(const std::vector<double>& dists, int n,
                           const std::vector<double>& z,
                           const std::string& model, double max_lag) {
    std::vector<double> h_pairs;
    std::vector<double> sv_pairs;
    h_pairs.reserve(static_cast<std::size_t>(n * (n - 1) / 2));
    sv_pairs.reserve(h_pairs.capacity());
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            h_pairs.push_back(dists[static_cast<std::size_t>(i * n + j)]);
            const double dz = z[static_cast<std::size_t>(i)]
                              - z[static_cast<std::size_t>(j)];
            sv_pairs.push_back(0.5 * dz * dz);
        }
    }
    const Empiric ev = empirical_variogram(h_pairs, sv_pairs, max_lag);
    const double total_sill = std::max(population_var(z), 1e-12);
    VariogramFit fit;
    fit.nugget = 0.0;
    fit.psill = total_sill;
    fit.range = std::max(max_lag, 1e-6);
    fit.bins = static_cast<int>(ev.lag.size());
    if (static_cast<int>(ev.lag.size()) < 3) return fit;

    double sv_max = ev.sv[0];
    for (double v : ev.sv) sv_max = std::max(sv_max, v);
    std::vector<double> nugget_grid =
        linspace(0.0, std::min(0.5 * sv_max, 0.9 * total_sill), 6);
    double lo = std::max(1e-3 * max_lag, 1e-6);
    double hi = max_lag;
    double best_nugget = 0.0;
    double best_psill = total_sill;
    double best_r = std::max(max_lag, 1e-6);
    double best_sse = std::numeric_limits<double>::infinity();

    for (int round = 0; round < 4; ++round) {
        const std::vector<double> ranges = linspace(lo, hi, 12);
        for (double r : ranges) {
            for (double nugget : nugget_grid) {
                double denom = 0.0;
                double numer = 0.0;
                std::vector<double> shape_sv(ev.lag.size());
                for (std::size_t i = 0; i < ev.lag.size(); ++i) {
                    const double sh =
                        model_sv_at(ev.lag[i], nugget, 1.0, r, model)
                        - nugget;
                    shape_sv[i] = sh;
                    denom += sh * sh;
                    numer += (ev.sv[i] - nugget) * sh;
                }
                if (denom < 1e-18) continue;
                double psill = numer / denom;
                if (psill < 1e-9) psill = 1e-9;
                double sse = 0.0;
                for (std::size_t i = 0; i < ev.lag.size(); ++i) {
                    const double fitted = nugget + psill * shape_sv[i];
                    const double d = ev.sv[i] - fitted;
                    sse += d * d;
                }
                if (sse < best_sse) {
                    best_sse = sse;
                    best_nugget = nugget;
                    best_psill = psill;
                    best_r = r;
                }
            }
        }
        const double r = best_r;
        const double nugget = best_nugget;
        lo = std::max(1e-6, r * 0.5);
        hi = (r < max_lag) ? std::min(max_lag, r * 1.5) : max_lag;
        const double span = std::max(hi - lo, 1e-6);
        lo = std::max(1e-6, r - span * 0.25);
        hi = std::min(max_lag, r + span * 0.25);
        nugget_grid = linspace(
            std::max(0.0, nugget - 0.1 * sv_max),
            std::min(nugget + 0.1 * sv_max, 0.9 * total_sill), 5);
    }
    fit.nugget = best_nugget;
    fit.psill = best_psill;
    fit.range = best_r;
    return fit;
}

bool neighborhood_requested(const InterpolateOptions& options) {
    if (options.max_neighbors.has_value() && *options.max_neighbors > 0) {
        return true;
    }
    return options.search_radius.has_value() && *options.search_radius > 0.0;
}

int effective_neighborhood_k(const std::optional<int>& max_neighbors, int n) {
    const int requested =
        max_neighbors.has_value() ? *max_neighbors : n;
    int k = requested;
    if (k < 1) k = 1;
    if (k > n) k = n;
    if (k > kKrigingNeighborhoodCap) k = kKrigingNeighborhoodCap;
    return k;
}

std::optional<double> positive_radius(const std::optional<double>& radius) {
    if (radius.has_value() && *radius > 0.0) return radius;
    return std::nullopt;
}

void idw_fill(FactorGrid& out, const std::vector<double>& xs,
              const std::vector<double>& ys, const std::vector<double>& zs,
              const InterpolateOptions& options) {
    const int n = static_cast<int>(xs.size());
    const int grid_n = out.grid_n;
    const double p = std::max(1.0, options.power);
    const double eps = kEps;
    const double eps_sq = eps * eps;
    const int min_n = std::max(1, options.min_neighbors);
    const auto radius = positive_radius(options.search_radius);
    int k = n;
    if (options.max_neighbors.has_value() && *options.max_neighbors > 0
        && *options.max_neighbors < n) {
        k = *options.max_neighbors;
    }
    const bool all_neighbors = (k >= n && !radius.has_value());
    const std::size_t m =
        static_cast<std::size_t>(grid_n) * static_cast<std::size_t>(grid_n);
    std::vector<double> z64(m, std::numeric_limits<double>::quiet_NaN());

    if (all_neighbors) {
        if (n >= min_n) {
            for (int i = 0; i < grid_n; ++i) {
                for (int j = 0; j < grid_n; ++j) {
                    const double tx = out.grid_x[static_cast<std::size_t>(j)];
                    const double ty = out.grid_y[static_cast<std::size_t>(i)];
                    double wsum = 0.0;
                    double vsum = 0.0;
                    int last_exact = -1;
                    for (int s = 0; s < n; ++s) {
                        const double dx = tx - xs[static_cast<std::size_t>(s)];
                        const double dy = ty - ys[static_cast<std::size_t>(s)];
                        double dist2 = dx * dx + dy * dy;
                        const bool exact = dist2 < eps_sq;
                        if (dist2 < eps_sq) dist2 = eps_sq;
                        double w = 0.0;
                        if (p == 2.0) {
                            w = 1.0 / dist2;
                        } else {
                            w = std::pow(dist2, -0.5 * p);
                        }
                        if (exact) w = 0.0;
                        wsum += w;
                        vsum += w * zs[static_cast<std::size_t>(s)];
                        if (exact) last_exact = s;
                    }
                    const std::size_t at =
                        static_cast<std::size_t>(i * grid_n + j);
                    if (wsum > 0.0) z64[at] = vsum / wsum;
                    if (last_exact >= 0) {
                        z64[at] = zs[static_cast<std::size_t>(last_exact)];
                    }
                }
            }
        }
    } else {
        for (int i = 0; i < grid_n; ++i) {
            for (int j = 0; j < grid_n; ++j) {
                const double tx = out.grid_x[static_cast<std::size_t>(j)];
                const double ty = out.grid_y[static_cast<std::size_t>(i)];
                const auto nb = k_nearest(tx, ty, xs, ys, k, radius);
                int neighbor_count = 0;
                double wsum = 0.0;
                double vsum = 0.0;
                int last_exact = -1;
                double last_exact_z = 0.0;
                for (const Neighbor& nbor : nb) {
                    if (!std::isfinite(nbor.dist)) continue;
                    ++neighbor_count;
                    const bool exact = nbor.dist < eps;
                    const double d = std::max(nbor.dist, eps);
                    double w = 1.0 / std::pow(d, p);
                    if (exact) w = 0.0;
                    wsum += w;
                    const double zv = zs[nbor.idx];
                    vsum += w * zv;
                    if (exact) {
                        last_exact = static_cast<int>(nbor.idx);
                        last_exact_z = zv;
                    }
                }
                const std::size_t at =
                    static_cast<std::size_t>(i * grid_n + j);
                if (neighbor_count >= min_n && wsum > 0.0) {
                    z64[at] = vsum / wsum;
                }
                if (last_exact >= 0 && neighbor_count >= min_n) {
                    z64[at] = last_exact_z;
                }
            }
        }
    }

    out.grid_z.resize(m);
    for (std::size_t t = 0; t < m; ++t) {
        out.grid_z[t] = static_cast<float>(z64[t]);
    }
    out.algorithm_id = "idw";
    out.method = "idw";
    out.power = p;
    out.n_samples = n;
    out.min_neighbors = options.min_neighbors;
    out.max_neighbors = options.max_neighbors;
    out.search_radius = options.search_radius;
}

void kriging_fill(FactorGrid& out, std::vector<double> xs,
                  std::vector<double> ys, std::vector<double> zs,
                  const InterpolateOptions& options) {
    const std::string model = canonical_model(options.variogram_model);
    DedupResult merged = deduplicate_samples(xs, ys, zs);
    xs = std::move(merged.x);
    ys = std::move(merged.y);
    zs = std::move(merged.z);
    const int n = static_cast<int>(zs.size());
    if (n == 0) {
        throw std::invalid_argument("kriging requires at least one sample");
    }
    std::vector<double> dists(static_cast<std::size_t>(n * n), 0.0);
    double dmax = 0.0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            const double dx = xs[static_cast<std::size_t>(i)]
                              - xs[static_cast<std::size_t>(j)];
            const double dy = ys[static_cast<std::size_t>(i)]
                              - ys[static_cast<std::size_t>(j)];
            const double d = std::sqrt(dx * dx + dy * dy);
            dists[static_cast<std::size_t>(i * n + j)] = d;
            if (d > dmax) dmax = d;
        }
    }
    if (n <= 1) dmax = 1.0;
    const double max_lag = std::max(0.5 * dmax, 1e-6);
    const VariogramFit fit = fit_variogram(dists, n, zs, model, max_lag);
    const double nugget = fit.nugget;
    const double psill = fit.psill;
    const double r = fit.range;
    const double sill = psill;
    const auto gamma = [&](double h) {
        return model_sv_at(h, nugget, psill, r, model);
    };
    const auto cov = [&](double h) { return (sill + nugget) - gamma(h); };

    const int grid_n = out.grid_n;
    const std::size_t m =
        static_cast<std::size_t>(grid_n) * static_cast<std::size_t>(grid_n);
    std::vector<double> z_pred(m);
    std::vector<double> variance(m);
    const double z_var = population_var(zs);

    auto fill_constant = [&]() {
        const double zc = mean_of(zs);
        const double vc = std::max(nugget, 0.0);
        for (std::size_t t = 0; t < m; ++t) {
            z_pred[t] = zc;
            variance[t] = vc;
        }
    };

    if (z_var <= 1e-12 || n == 1) {
        fill_constant();
    } else if (neighborhood_requested(options)) {
        const int min_n = std::max(1, options.min_neighbors);
        const int k_eff = effective_neighborhood_k(options.max_neighbors, n);
        const auto radius = positive_radius(options.search_radius);
        const int sys = k_eff + 1;
        const double ridge = (sill > 0.0) ? 1e-10 * sill : 1e-10;
        const double total_sill = sill + nugget;
        std::fill(z_pred.begin(), z_pred.end(),
                  std::numeric_limits<double>::quiet_NaN());
        std::fill(variance.begin(), variance.end(),
                  std::numeric_limits<double>::quiet_NaN());
        for (int row = 0; row < grid_n; ++row) {
            for (int col = 0; col < grid_n; ++col) {
                const double tx = out.grid_x[static_cast<std::size_t>(col)];
                const double ty = out.grid_y[static_cast<std::size_t>(row)];
                auto nb = k_nearest(tx, ty, xs, ys, k_eff, radius);
                int kept = 0;
                std::vector<char> keep(static_cast<std::size_t>(k_eff), 0);
                for (int t = 0; t < static_cast<int>(nb.size()); ++t) {
                    if (std::isfinite(nb[static_cast<std::size_t>(t)].dist)) {
                        keep[static_cast<std::size_t>(t)] = 1;
                        ++kept;
                    }
                }
                if (kept < min_n) continue;
                std::vector<double> K(static_cast<std::size_t>(sys * sys), 0.0);
                std::vector<double> rhs(static_cast<std::size_t>(sys), 0.0);
                std::vector<double> cov_tn(static_cast<std::size_t>(k_eff),
                                           0.0);
                std::vector<double> z_vals(static_cast<std::size_t>(k_eff),
                                           0.0);
                for (int a = 0; a < k_eff; ++a) {
                    const bool ka = keep[static_cast<std::size_t>(a)] != 0;
                    const std::size_t ia =
                        ka ? nb[static_cast<std::size_t>(a)].idx : 0;
                    if (ka) {
                        cov_tn[static_cast<std::size_t>(a)] =
                            cov(nb[static_cast<std::size_t>(a)].dist);
                        z_vals[static_cast<std::size_t>(a)] =
                            zs[ia];
                    }
                    for (int b = 0; b < k_eff; ++b) {
                        const bool kb = keep[static_cast<std::size_t>(b)] != 0;
                        double v = 0.0;
                        if (ka && kb) {
                            const std::size_t ib =
                                nb[static_cast<std::size_t>(b)].idx;
                            const double dx =
                                xs[ia] - xs[ib];
                            const double dy =
                                ys[ia] - ys[ib];
                            v = cov(std::sqrt(dx * dx + dy * dy));
                        } else if (a == b) {
                            v = 1.0;
                        }
                        K[static_cast<std::size_t>(a * sys + b)] = v;
                    }
                    K[static_cast<std::size_t>(sys * k_eff + a)] =
                        ka ? 1.0 : 0.0;
                    K[static_cast<std::size_t>(a * sys + k_eff)] =
                        ka ? 1.0 : 0.0;
                    rhs[static_cast<std::size_t>(a)] =
                        cov_tn[static_cast<std::size_t>(a)];
                }
                rhs[static_cast<std::size_t>(k_eff)] = 1.0;
                const std::vector<double> w =
                    solve_ok_system(K, rhs, sys, k_eff, ridge);
                double zhat = 0.0;
                double wcov = 0.0;
                for (int a = 0; a < k_eff; ++a) {
                    zhat += w[static_cast<std::size_t>(a)]
                            * z_vals[static_cast<std::size_t>(a)];
                    wcov += w[static_cast<std::size_t>(a)]
                            * cov_tn[static_cast<std::size_t>(a)];
                }
                const std::size_t at =
                    static_cast<std::size_t>(row * grid_n + col);
                z_pred[at] = zhat;
                variance[at] = std::max(
                    0.0, total_sill - (wcov + w[static_cast<std::size_t>(k_eff)]));
            }
        }
    } else {
        const int sys = n + 1;
        std::vector<double> K(static_cast<std::size_t>(sys * sys), 0.0);
        for (int i = 0; i < n; ++i) {
            for (int j = 0; j < n; ++j) {
                K[static_cast<std::size_t>(i * sys + j)] =
                    cov(dists[static_cast<std::size_t>(i * n + j)]);
            }
        }
        const double cov0 = K[0];
        for (int i = 0; i < n; ++i) {
            K[static_cast<std::size_t>(i * sys + i)] = cov0;
            K[static_cast<std::size_t>(i * sys + n)] = 1.0;
            K[static_cast<std::size_t>(n * sys + i)] = 1.0;
        }
        const double ridge = (cov0 > 0.0) ? 1e-10 * cov0 : 1e-10;
        const double total_sill = sill + nugget;
        for (int row = 0; row < grid_n; ++row) {
            for (int col = 0; col < grid_n; ++col) {
                const double tx = out.grid_x[static_cast<std::size_t>(col)];
                const double ty = out.grid_y[static_cast<std::size_t>(row)];
                std::vector<double> rhs(static_cast<std::size_t>(sys), 0.0);
                std::vector<double> cov_tn(static_cast<std::size_t>(n), 0.0);
                for (int s = 0; s < n; ++s) {
                    const double dx = tx - xs[static_cast<std::size_t>(s)];
                    const double dy = ty - ys[static_cast<std::size_t>(s)];
                    cov_tn[static_cast<std::size_t>(s)] =
                        cov(std::sqrt(dx * dx + dy * dy));
                    rhs[static_cast<std::size_t>(s)] =
                        cov_tn[static_cast<std::size_t>(s)];
                }
                rhs[static_cast<std::size_t>(n)] = 1.0;
                const std::vector<double> w =
                    solve_ok_system(K, rhs, sys, n, ridge);
                double zhat = 0.0;
                double wcov = 0.0;
                for (int s = 0; s < n; ++s) {
                    zhat += w[static_cast<std::size_t>(s)]
                            * zs[static_cast<std::size_t>(s)];
                    wcov += w[static_cast<std::size_t>(s)]
                            * cov_tn[static_cast<std::size_t>(s)];
                }
                const std::size_t at =
                    static_cast<std::size_t>(row * grid_n + col);
                z_pred[at] = zhat;
                variance[at] = std::max(
                    0.0, total_sill - (wcov + w[static_cast<std::size_t>(n)]));
            }
        }
    }

    out.grid_z.resize(m);
    out.variance_grid.resize(m);
    for (std::size_t t = 0; t < m; ++t) {
        out.grid_z[t] = static_cast<float>(z_pred[t]);
        out.variance_grid[t] = static_cast<float>(variance[t]);
    }
    out.algorithm_id = "kriging";
    out.method = "kriging_fallback";
    out.model = model;
    out.variogram_fit = "numpy-grid-ols";
    out.range = r;
    out.sill = sill;
    out.nugget = nugget;
    out.n_samples = n;
    out.duplicates_merged = merged.duplicates;
    out.variogram_bins = fit.bins;
    out.min_neighbors = options.min_neighbors;
    out.max_neighbors = options.max_neighbors;
    out.search_radius = options.search_radius;
}

}  // namespace

std::vector<double> linspace(double start, double stop, int num) {
    if (num <= 0) return {};
    std::vector<double> y(static_cast<std::size_t>(num));
    if (num == 1) {
        y[0] = start;
        return y;
    }
    const double step = (stop - start) / static_cast<double>(num - 1);
    for (int i = 0; i < num; ++i) {
        y[static_cast<std::size_t>(i)] =
            static_cast<double>(i) * step + start;
    }
    y[static_cast<std::size_t>(num - 1)] = stop;
    return y;
}

std::array<double, 4> dataset_extent(const std::vector<SamplePoint>& points) {
    if (points.empty()) return {0.0, 0.0, 1.0, 1.0};
    double xmin = points[0].x, xmax = points[0].x;
    double ymin = points[0].y, ymax = points[0].y;
    for (const SamplePoint& p : points) {
        xmin = std::min(xmin, p.x);
        xmax = std::max(xmax, p.x);
        ymin = std::min(ymin, p.y);
        ymax = std::max(ymax, p.y);
    }
    const double pad_x = !is_close(xmin, xmax)
        ? std::max(0.01, (xmax - xmin) * 0.1)
        : 0.05;
    const double pad_y = !is_close(ymin, ymax)
        ? std::max(0.01, (ymax - ymin) * 0.1)
        : 0.05;
    return {xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y};
}

std::vector<SamplePoint> valid_points(const std::vector<SamplePoint>& points) {
    std::vector<SamplePoint> out;
    for (const SamplePoint& p : points) {
        if (std::isfinite(p.value) && qc_ok(p.qc_flag)) out.push_back(p);
    }
    return out;
}

std::vector<std::string> validate_dataset(
    const std::vector<SamplePoint>& points) {
    const auto valid = valid_points(points);
    std::vector<std::string> issues;
    if (valid.size() < 2) {
        issues.push_back(
            "Insufficient sample points (" + std::to_string(valid.size())
            + "); at least 2 valid points required for spatial interpolation.");
        return issues;
    }
    double xmin = valid[0].x, xmax = valid[0].x;
    double ymin = valid[0].y, ymax = valid[0].y;
    for (const SamplePoint& p : valid) {
        xmin = std::min(xmin, p.x);
        xmax = std::max(xmax, p.x);
        ymin = std::min(ymin, p.y);
        ymax = std::max(ymax, p.y);
    }
    if (is_close(xmin, xmax) && is_close(ymin, ymax)) {
        issues.push_back("All points are collocated at the same coordinate.");
    }
    return issues;
}

DedupResult deduplicate_samples(const std::vector<double>& x,
                                const std::vector<double>& y,
                                const std::vector<double>& z, double tol) {
    const std::size_t n = z.size();
    std::vector<std::size_t> order(n);
    for (std::size_t i = 0; i < n; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        if (x[a] < x[b]) return true;
        if (x[b] < x[a]) return false;
        return y[a] < y[b];
    });
    DedupResult out;
    std::size_t i = 0;
    while (i < n) {
        std::size_t j = i + 1;
        double total = z[order[i]];
        while (j < n
               && std::fabs(x[order[j]] - x[order[i]]) <= tol
               && std::fabs(y[order[j]] - y[order[i]]) <= tol) {
            total += z[order[j]];
            ++j;
        }
        out.x.push_back(x[order[i]]);
        out.y.push_back(y[order[i]]);
        out.z.push_back(total / static_cast<double>(j - i));
        i = j;
    }
    out.duplicates = static_cast<int>(n - out.x.size());
    return out;
}

std::vector<double> model_semivariance(const std::vector<double>& h,
                                       double nugget, double psill, double r,
                                       const std::string& model) {
    const std::string m = canonical_model(model);
    std::vector<double> out(h.size());
    for (std::size_t i = 0; i < h.size(); ++i) {
        out[i] = model_sv_at(h[i], nugget, psill, r, m);
    }
    return out;
}

FactorGrid interpolate_factor(const std::vector<SamplePoint>& points,
                              const InterpolateOptions& options) {
    const auto issues = validate_dataset(points);
    if (!issues.empty()) {
        throw std::invalid_argument(join_issues(issues));
    }
    const auto valid = valid_points(points);
    const auto extent = dataset_extent(points);
    const int grid_n = std::max(10, options.grid_n);
    FactorGrid out;
    out.grid_n = grid_n;
    out.grid_x = linspace(extent[0], extent[2], grid_n);
    out.grid_y = linspace(extent[1], extent[3], grid_n);
    std::vector<double> xs, ys, zs;
    xs.reserve(valid.size());
    ys.reserve(valid.size());
    zs.reserve(valid.size());
    for (const SamplePoint& p : valid) {
        xs.push_back(p.x);
        ys.push_back(p.y);
        zs.push_back(p.value);
    }
    if (is_kriging_method(options.method)) {
        kriging_fill(out, std::move(xs), std::move(ys), std::move(zs), options);
    } else {
        idw_fill(out, xs, ys, zs, options);
    }
    apply_domain_mask(out, options.boundary);
    std::optional<std::string> crs;
    if (!options.crs.empty()) crs = options.crs;
    std::optional<std::string> declared;
    if (!options.distance_policy.empty()) declared = options.distance_policy;
    const DistancePolicy policy = resolve_distance_policy(crs, declared);
    out.distance_policy = policy.policy;
    out.distance_policy_annotation = policy.annotation;
    out.statistics = grid_statistics(out.grid_z);
    return out;
}

GridStatistics grid_statistics(const std::vector<float>& grid_z) {
    GridStatistics s;
    s.total_count = static_cast<int>(grid_z.size());
    double sum = 0.0;
    double mn = std::numeric_limits<double>::infinity();
    double mx = -std::numeric_limits<double>::infinity();
    int n = 0;
    for (float v : grid_z) {
        if (!std::isfinite(v)) continue;
        const double d = static_cast<double>(v);
        ++n;
        sum += d;
        mn = std::min(mn, d);
        mx = std::max(mx, d);
    }
    s.valid_count = n;
    if (n == 0) return s;
    s.min = mn;
    s.max = mx;
    s.mean = sum / static_cast<double>(n);
    double acc = 0.0;
    for (float v : grid_z) {
        if (!std::isfinite(v)) continue;
        const double d = static_cast<double>(v) - s.mean;
        acc += d * d;
    }
    s.std = std::sqrt(acc / static_cast<double>(n));
    return s;
}

}  // namespace pwb::mapping
