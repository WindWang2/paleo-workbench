// mapping_kernel.interpolator — C++ port vs the frozen Python oracle
// (interpolator_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_interpolator_fixtures.py).

#include <cmath>
#include <cstdio>
#include <exception>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>

using pwb::domain::Json;
using pwb::mapping::FactorGrid;
using pwb::mapping::InterpolateOptions;
using pwb::mapping::SamplePoint;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::vector<SamplePoint> points_from_json(const Json& arr) {
    std::vector<SamplePoint> out;
    for (const auto& p : arr) {
        SamplePoint s;
        s.x = p[0].get<double>();
        s.y = p[1].get<double>();
        s.value = p[2].is_null() ? std::numeric_limits<double>::quiet_NaN()
                                 : p[2].get<double>();
        out.push_back(s);
    }
    return out;
}

InterpolateOptions options_from_json(const Json& o) {
    InterpolateOptions opt;
    opt.method = o.value("method", std::string("idw"));
    opt.grid_n = o.value("grid_n", 50);
    opt.power = o.value("power", 2.0);
    opt.min_neighbors = o.value("min_neighbors", 1);
    opt.variogram_model = o.value("variogram_model", std::string("spherical"));
    if (o.contains("max_neighbors") && !o["max_neighbors"].is_null()) {
        opt.max_neighbors = o["max_neighbors"].get<int>();
    }
    if (o.contains("search_radius") && !o["search_radius"].is_null()) {
        opt.search_radius = o["search_radius"].get<double>();
    }
    if (o.contains("boundary") && o["boundary"].is_array()) {
        for (const auto& pt : o["boundary"]) {
            opt.boundary.push_back({pt[0].get<double>(), pt[1].get<double>()});
        }
    }
    return opt;
}

double max_abs_diff_f32(const std::vector<float>& got, const Json& want_rows) {
    double worst = 0.0;
    std::size_t at = 0;
    for (const auto& row : want_rows) {
        for (const auto& v : row) {
            const float a = at < got.size() ? got[at] : 0.0f;
            const bool a_fin = std::isfinite(a);
            const bool b_fin = !v.is_null() && std::isfinite(v.get<double>());
            if (!a_fin && !b_fin) {
                ++at;
                continue;
            }
            if (a_fin != b_fin) return std::numeric_limits<double>::infinity();
            worst = std::max(worst, std::fabs(static_cast<double>(a)
                                              - v.get<double>()));
            ++at;
        }
    }
    if (at != got.size()) return std::numeric_limits<double>::infinity();
    return worst;
}

double max_abs_diff_axis(const std::vector<double>& got, const Json& want) {
    if (got.size() != want.size()) {
        return std::numeric_limits<double>::infinity();
    }
    double worst = 0.0;
    for (std::size_t i = 0; i < got.size(); ++i) {
        worst = std::max(worst, std::fabs(got[i] - want[i].get<double>()));
    }
    return worst;
}

}  // namespace

void test_idw_keep_policy_preserves_duplicate_contract() {
    // D2 (revised): the kernel keeps coincident samples — the host's
    // duplicate_policy='keep' contract depends on it (the science_service
    // duplicates_keep oracle locks the frozen output). What the kernel must
    // NOT do is run away: the duplicated site reads a bounded value (the
    // shared eps clamp behaves like the merged mean), never an arbitrary
    // runaway, and never NaN.
    std::vector<pwb::mapping::SamplePoint> points = {
        {.x = 0.0, .y = 0.0, .value = 0.0, .qc_flag = "ok"},
        {.x = 0.0, .y = 0.0, .value = 10.0, .qc_flag = "ok"},
        {.x = 1e-3, .y = 1e-3, .value = 3.0, .qc_flag = "ok"},
        {.x = 1e-3, .y = 0.0, .value = 4.0, .qc_flag = "ok"},
        {.x = 0.0, .y = 1e-3, .value = 5.0, .qc_flag = "ok"},
    };
    pwb::mapping::InterpolateOptions options;
    options.method = "idw";
    options.power = 2.0;
    options.grid_n = 16;
    const auto grid = pwb::mapping::interpolate_factor(points, options);
    const double mn = grid.statistics.min;
    const double mx = grid.statistics.max;
    check(mn >= 0.0 && mx <= 10.0,
          "duplicate site stays bounded by the data range (no runaway)");
    check(std::isfinite(grid.grid_z[0]),
          "exact-site cell finite under 'keep'");
}

// #1460: one sample with a NaN x (first in the vector — the position that
// used to poison dataset_extent's min/max seed). Every neighbourhood mode
// must produce EXACTLY the grid of the dataset without that sample.
void test_nonfinite_coord_policy_is_consistent_across_paths() {
    constexpr double nan = std::numeric_limits<double>::quiet_NaN();
    constexpr double inf = std::numeric_limits<double>::infinity();
    std::vector<pwb::mapping::SamplePoint> clean = {
        {0.0, 0.0, 1.0}, {2.0, 0.0, 2.0}, {0.0, 2.0, 3.0},
        {2.0, 2.0, 4.0}, {1.0, 1.0, 2.5},
    };
    std::vector<pwb::mapping::SamplePoint> poisoned = clean;
    poisoned.insert(poisoned.begin(), {nan, 1.0, 100.0});
    poisoned.push_back({inf, 0.5, -100.0});

    auto options_for = [](const char* method) {
        InterpolateOptions opt;
        opt.method = method;
        opt.grid_n = 12;
        return opt;
    };
    struct Mode {
        const char* name;
        InterpolateOptions opt;
    };
    std::vector<Mode> modes;
    {
        InterpolateOptions o = options_for("idw");
        modes.push_back({"idw all-neighbours", o});
    }
    {
        InterpolateOptions o = options_for("idw");
        o.max_neighbors = 3;
        modes.push_back({"idw kNN", o});
    }
    {
        InterpolateOptions o = options_for("idw");
        o.search_radius = 1.5;
        modes.push_back({"idw radius", o});
    }
    {
        InterpolateOptions o = options_for("kriging");
        modes.push_back({"kriging global", o});
    }
    {
        InterpolateOptions o = options_for("kriging");
        o.max_neighbors = 4;
        modes.push_back({"kriging neighbourhood", o});
    }
    for (const Mode& mode : modes) {
        const FactorGrid base = pwb::mapping::interpolate_factor(clean,
                                                                 mode.opt);
        const FactorGrid got = pwb::mapping::interpolate_factor(poisoned,
                                                                mode.opt);
        check(base.grid_z.size() == got.grid_z.size(),
              std::string(mode.name) + ": grid size matches clean run");
        bool identical = base.grid_z.size() == got.grid_z.size();
        for (std::size_t i = 0; identical && i < got.grid_z.size(); ++i) {
            if (std::isnan(base.grid_z[i]) != std::isnan(got.grid_z[i])
                || (!std::isnan(base.grid_z[i])
                    && base.grid_z[i] != got.grid_z[i])) {
                identical = false;
            }
        }
        check(identical,
              std::string(mode.name)
                  + ": non-finite-coordinate samples change nothing");
        check(got.statistics.valid_count == static_cast<int>(
              got.grid_z.size()),
              std::string(mode.name) + ": no NaN-poisoned cells remain");
    }

    // Non-finite value AND non-finite coordinate: both drop.
    std::vector<pwb::mapping::SamplePoint> value_nan = clean;
    value_nan.push_back({3.0, 3.0, nan});
    const FactorGrid value_nan_grid = pwb::mapping::interpolate_factor(
        value_nan, options_for("idw"));
    const FactorGrid clean_grid = pwb::mapping::interpolate_factor(
        clean, options_for("idw"));
    check(value_nan_grid.statistics.valid_count
              == clean_grid.statistics.valid_count,
          "non-finite value sample drops like a non-finite coordinate");
}

// #1460 unit surface: valid_points / dataset_extent on non-finite coords.
void test_valid_points_and_extent_skip_nonfinite_coordinates() {
    constexpr double nan = std::numeric_limits<double>::quiet_NaN();
    std::vector<pwb::mapping::SamplePoint> points = {
        {nan, 0.0, 5.0},   // NaN x — dropped
        {0.0, nan, 5.0},   // NaN y — dropped
        {1.0, 1.0, 7.0},
        {3.0, 1.0, 8.0},
        {2.0, 4.0, 9.0},
    };
    const auto valid = pwb::mapping::valid_points(points);
    check(valid.size() == 3, "valid_points drops non-finite x/y");
    // Extent ignores non-finite coordinates but keeps invalid-VALUE
    // samples with finite coordinates (the ALL-points contract).
    std::vector<pwb::mapping::SamplePoint> extent_probe = {
        {nan, nan, 1.0}, {0.0, 0.0, nan}, {4.0, 0.0, 2.0}, {0.0, 4.0, 3.0}};
    const auto extent = pwb::mapping::dataset_extent(extent_probe);
    check(std::fabs(extent[0] - (-0.4)) < 1e-12
              && std::fabs(extent[1] - (-0.4)) < 1e-12
              && std::fabs(extent[2] - 4.4) < 1e-12
              && std::fabs(extent[3] - 4.4) < 1e-12,
          "dataset_extent skips non-finite coords, keeps invalid values");
    const auto all_nonfinite = pwb::mapping::dataset_extent(
        {{nan, 0.0, 1.0}, {0.0, nan, 1.0}});
    check(all_nonfinite[0] == 0.0 && all_nonfinite[2] == 1.0,
          "dataset_extent of only-nonfinite coords falls back to unit box");
}

// #1465: with a fitted nugget > 0 the OK system must use one covariance
// contract — C(0) = nugget + psill on the diagonal, C(h>0) = total_sill -
// gamma(h), variance measured against the same total sill. The in-test
// oracle re-solves the (n+1) system with the kernel's OWN fitted
// parameters and the documented contract; the old code (diagonal without
// the nugget) fails this comparison.
void test_kriging_nugget_covariance_contract() {
    // Deterministic three-cluster field (values 40/0/40 plus fixed noise):
    // within-cluster lags see only the noise variance, cluster-to-cluster
    // lags (inside max_lag = dmax/2) see the value contrast — the classic
    // identifiable-nugget geometry. Verified: this dataset fits a nugget
    // around ~112 (stable, deterministic).
    std::vector<pwb::mapping::SamplePoint> points;
    {
        const double noise[12] = {14, -14, 10, -10, 14, -14,
                                  10, -10, 14, -14, 10, -10};
        const double base[3] = {40.0, 0.0, 40.0};
        const double cx[3] = {0.0, 5.0, 10.0};
        const double off[4][2] = {{0, 0}, {0.3, 0.1}, {0.1, 0.3},
                                  {0.2, 0.2}};
        int k = 0;
        for (int c = 0; c < 3; ++c) {
            for (int p = 0; p < 4; ++p, ++k) {
                points.push_back({cx[c] + off[p][0], off[p][1],
                                  base[c] + noise[k]});
            }
        }
    }
    InterpolateOptions options;
    options.method = "kriging";
    options.grid_n = 10;
    const FactorGrid got = pwb::mapping::interpolate_factor(points, options);
    check(got.nugget > 0.0,
          "noisy dataset fits a positive nugget (fixture premise)");
    if (!(got.nugget > 0.0)) return;

    // Mirror the kernel: dedup, then distances.
    std::vector<double> xs, ys, zs;
    for (const auto& p : pwb::mapping::valid_points(points)) {
        xs.push_back(p.x);
        ys.push_back(p.y);
        zs.push_back(p.value);
    }
    const auto merged = pwb::mapping::deduplicate_samples(xs, ys, zs);
    const int n = static_cast<int>(merged.z.size());
    const double nugget = got.nugget;
    const double sill = got.sill;  // partial sill
    const double total_sill = sill + nugget;
    const std::string model = got.model;
    const double range = got.range;
    auto gamma = [&](double h) {
        return pwb::mapping::model_semivariance({h}, nugget, sill, range,
                                                model)[0];
    };
    auto cov = [&](double h) {
        return h <= 0.0 ? total_sill : total_sill - gamma(h);
    };

    // Augmented OK matrix with the documented contract.
    const int sys = n + 1;
    std::vector<double> K(static_cast<std::size_t>(sys * sys), 0.0);
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            const double dx = merged.x[static_cast<std::size_t>(i)]
                              - merged.x[static_cast<std::size_t>(j)];
            const double dy = merged.y[static_cast<std::size_t>(i)]
                              - merged.y[static_cast<std::size_t>(j)];
            K[static_cast<std::size_t>(i * sys + j)] =
                cov(std::sqrt(dx * dx + dy * dy));
        }
        K[static_cast<std::size_t>(i * sys + n)] = 1.0;
        K[static_cast<std::size_t>(n * sys + i)] = 1.0;
    }

    // Tiny Gaussian elimination with partial pivoting (test-side oracle).
    auto solve = [&](std::vector<double> a, std::vector<double> b) {
        std::vector<double> x(static_cast<std::size_t>(sys), 0.0);
        for (int col = 0; col < sys; ++col) {
            int best = col;
            for (int row = col + 1; row < sys; ++row) {
                if (std::fabs(a[static_cast<std::size_t>(row * sys + col)])
                    > std::fabs(
                        a[static_cast<std::size_t>(best * sys + col)])) {
                    best = row;
                }
            }
            for (int j = 0; j < sys; ++j) {
                std::swap(a[static_cast<std::size_t>(col * sys + j)],
                          a[static_cast<std::size_t>(best * sys + j)]);
            }
            std::swap(b[static_cast<std::size_t>(col)],
                      b[static_cast<std::size_t>(best)]);
            const double diag =
                a[static_cast<std::size_t>(col * sys + col)];
            if (!(std::fabs(diag) > 0.0)) return x;
            for (int row = col + 1; row < sys; ++row) {
                const double f =
                    a[static_cast<std::size_t>(row * sys + col)] / diag;
                for (int j = col; j < sys; ++j) {
                    a[static_cast<std::size_t>(row * sys + j)] -=
                        f * a[static_cast<std::size_t>(col * sys + j)];
                }
                b[static_cast<std::size_t>(row)] -=
                    f * b[static_cast<std::size_t>(col)];
            }
        }
        for (int i = sys - 1; i >= 0; --i) {
            double s = b[static_cast<std::size_t>(i)];
            for (int j = i + 1; j < sys; ++j) {
                s -= a[static_cast<std::size_t>(i * sys + j)]
                     * x[static_cast<std::size_t>(j)];
            }
            x[static_cast<std::size_t>(i)] =
                s / a[static_cast<std::size_t>(i * sys + i)];
        }
        return x;
    };

    // Re-solve at every grid node and compare with the kernel's output.
    double worst_z = 0.0;
    double worst_var = 0.0;
    for (int row = 0; row < got.grid_n; ++row) {
        for (int col = 0; col < got.grid_n; ++col) {
            const double tx = got.grid_x[static_cast<std::size_t>(col)];
            const double ty = got.grid_y[static_cast<std::size_t>(row)];
            std::vector<double> rhs(static_cast<std::size_t>(sys), 0.0);
            for (int s = 0; s < n; ++s) {
                const double dx =
                    tx - merged.x[static_cast<std::size_t>(s)];
                const double dy =
                    ty - merged.y[static_cast<std::size_t>(s)];
                rhs[static_cast<std::size_t>(s)] =
                    cov(std::sqrt(dx * dx + dy * dy));
            }
            rhs[static_cast<std::size_t>(n)] = 1.0;
            const auto w = solve(K, rhs);
            double zhat = 0.0;
            double wcov = 0.0;
            for (int s = 0; s < n; ++s) {
                zhat += w[static_cast<std::size_t>(s)]
                        * merged.z[static_cast<std::size_t>(s)];
                wcov += w[static_cast<std::size_t>(s)]
                        * rhs[static_cast<std::size_t>(s)];
            }
            const double variance =
                std::max(0.0,
                         total_sill - (wcov + w[static_cast<std::size_t>(n)]));
            const std::size_t at = static_cast<std::size_t>(
                row * got.grid_n + col);
            worst_z = std::max(worst_z,
                               std::fabs(zhat
                                         - static_cast<double>(
                                             got.grid_z[at])));
            worst_var = std::max(
                worst_var,
                std::fabs(variance
                          - static_cast<double>(got.variance_grid[at])));
            check(got.variance_grid[at] >= 0.0f,
                  "kriging variance non-negative");
            // NOTE: an OK variance may legitimately exceed C(0) — negative
            // weights (screen effect) push total_sill - (wcov + mu) above
            // the total sill — so only non-negativity and the oracle match
            // above are asserted.
        }
    }
    check(worst_z < 1e-4,
          "nugget>0 estimate matches the C(0)=total-sill oracle ("
              + std::to_string(worst_z) + ")");
    check(worst_var < 1e-4,
          "nugget>0 variance matches the C(0)=total-sill oracle ("
              + std::to_string(worst_var) + ")");

    // Review R1 coverage gap: the neighbourhood path's #1465 diagonal needs
    // its own oracle. With k_eff == n (and no radius) the neighbourhood
    // system is EXACTLY the global system — same cov, same Lagrange row —
    // so both paths must produce the same estimate and variance grids.
    InterpolateOptions neighborhood = options;
    neighborhood.max_neighbors = n;  // 12 samples -> k_eff == n
    const FactorGrid moving = pwb::mapping::interpolate_factor(points,
                                                               neighborhood);
    double worst_moving = 0.0;
    double worst_moving_var = 0.0;
    for (std::size_t i = 0; i < got.grid_z.size(); ++i) {
        worst_moving = std::max(
            worst_moving,
            std::fabs(static_cast<double>(moving.grid_z[i] - got.grid_z[i])));
        worst_moving_var = std::max(
            worst_moving_var,
            std::fabs(static_cast<double>(moving.variance_grid[i]
                                          - got.variance_grid[i])));
    }
    check(worst_moving < 1e-4,
          "nugget>0 neighbourhood (k=n) equals global estimate ("
              + std::to_string(worst_moving) + ")");
    check(worst_moving_var < 1e-4,
          "nugget>0 neighbourhood (k=n) equals global variance ("
              + std::to_string(worst_moving_var) + ")");
}

// grid_n ceiling (#1460 hardening family): a hostile grid_n must be
// refused with a clean invalid_argument, not overflow int cell math or
// thrash the allocator.
void test_grid_n_ceiling_rejects_hostile_requests() {
    std::vector<pwb::mapping::SamplePoint> points = {
        {0.0, 0.0, 1.0}, {1.0, 0.0, 2.0}, {0.0, 1.0, 3.0},
    };
    InterpolateOptions options;
    options.method = "idw";
    options.grid_n = 10001;  // one over the cap
    bool threw = false;
    try {
        static_cast<void>(pwb::mapping::interpolate_factor(points, options));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    check(threw, "hostile grid_n refused with invalid_argument");
}



int main() {
    test_idw_keep_policy_preserves_duplicate_contract();
    test_nonfinite_coord_policy_is_consistent_across_paths();
    test_valid_points_and_extent_skip_nonfinite_coordinates();
    test_kriging_nugget_covariance_contract();
    test_grid_n_ceiling_rejects_hostile_requests();
    const std::string fixture_path = PWB_INTERP_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    std::map<std::string, std::vector<SamplePoint>> datasets;
    for (auto it = oracle["datasets"].begin(); it != oracle["datasets"].end();
         ++it) {
        datasets[it.key()] = points_from_json(it.value()["points"]);
    }

    const Json& units = oracle["units"];
    {
        for (const auto& e : units["extent"]) {
            const auto pts = points_from_json(e["points"]);
            const auto got = pwb::mapping::dataset_extent(pts);
            const auto& want = e["result"];
            check(std::fabs(got[0] - want[0].get<double>()) < 1e-12
                      && std::fabs(got[1] - want[1].get<double>()) < 1e-12
                      && std::fabs(got[2] - want[2].get<double>()) < 1e-12
                      && std::fabs(got[3] - want[3].get<double>()) < 1e-12,
                  "extent");
        }
    }
    {
        for (const auto& e : units["validate"]) {
            const auto pts = points_from_json(e["points"]);
            const auto got = pwb::mapping::validate_dataset(pts);
            const auto& want = e["issues"];
            check(got.size() == want.size(), "validate count");
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                check(got[i] == want[i].get<std::string>(),
                      "validate message: " + got[i]);
            }
        }
    }
    {
        const auto& ls = units["linspace"];
        const auto got = pwb::mapping::linspace(
            ls["start"].get<double>(), ls["stop"].get<double>(),
            ls["num"].get<int>());
        const auto& want = ls["result"];
        check(got.size() == want.size(), "linspace count");
        for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
            check(got[i] == want[i].get<double>(), "linspace bit-identical");
        }
    }
    {
        const auto& sv = units["semivariance"];
        std::vector<double> h;
        for (const auto& v : sv["h"]) h.push_back(v.get<double>());
        for (const char* model : {"spherical", "exponential", "gaussian"}) {
            const auto got = pwb::mapping::model_semivariance(
                h, sv["nugget"].get<double>(), sv["psill"].get<double>(),
                sv["range"].get<double>(), model);
            const auto& want = sv[model];
            check(got.size() == want.size(), std::string(model) + " sv count");
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                check(std::fabs(got[i] - want[i].get<double>()) < 1e-12,
                      std::string(model) + " sv value");
            }
        }
    }
    {
        const auto& d = units["dedup"];
        // Reconstruct the generator's input: (0,0,1), (0,0,3), (1,1,5),
        // (1+1e-12, 1, 7) — the last two merge (tol 1e-9 on y, x within 1e-9).
        const std::vector<double> x{0.0, 0.0, 1.0, 1.0 + 1e-12};
        const std::vector<double> y{0.0, 0.0, 1.0, 1.0};
        const std::vector<double> z{1.0, 3.0, 5.0, 7.0};
        const auto got = pwb::mapping::deduplicate_samples(x, y, z);
        check(got.duplicates == d["duplicates"].get<int>(), "dedup count");
        check(got.x.size() == d["x"].size(), "dedup n");
        for (std::size_t i = 0; i < got.x.size() && i < d["x"].size(); ++i) {
            check(std::fabs(got.x[i] - d["x"][i].get<double>()) < 1e-15
                      && std::fabs(got.y[i] - d["y"][i].get<double>()) < 1e-15
                      && std::fabs(got.z[i] - d["z"][i].get<double>()) < 1e-15,
                  "dedup values");
        }
    }
    {
        const auto& qc = units["qc_filter"];
        auto pts = points_from_json(qc["points"]);
        const auto& flags = qc["qc"];
        for (std::size_t i = 0; i < pts.size() && i < flags.size(); ++i) {
            pts[i].qc_flag = flags[i].get<std::string>();
        }
        const auto valid = pwb::mapping::valid_points(pts);
        check(static_cast<int>(valid.size())
                  == qc["valid_count"].get<int>(),
              "qc valid_count");
        const auto issues = pwb::mapping::validate_dataset(pts);
        check(issues.size() == qc["issues"].size(), "qc issues count");
        if (!issues.empty() && !qc["issues"].empty()) {
            check(issues[0] == qc["issues"][0].get<std::string>(),
                  "qc issue text");
        }
    }

    int n_cases = 0;
    for (const auto& c : oracle["cases"]) {
        ++n_cases;
        const std::string id = c["id"].get<std::string>();
        const auto& pts = datasets.at(c["dataset"].get<std::string>());
        const InterpolateOptions opt = options_from_json(c["options"]);
        FactorGrid got;
        try {
            got = pwb::mapping::interpolate_factor(pts, opt);
        } catch (const std::exception& ex) {
            check(false, id + " threw: " + ex.what());
            continue;
        }
        check(got.algorithm_id == c["algorithm_id"].get<std::string>(),
              id + " algorithm_id");
        const double dx = max_abs_diff_axis(got.grid_x, c["grid_x"]);
        const double dy = max_abs_diff_axis(got.grid_y, c["grid_y"]);
        check(dx < 1e-12, id + " grid_x max_diff=" + std::to_string(dx));
        check(dy < 1e-12, id + " grid_y max_diff=" + std::to_string(dy));
        const bool kriging = opt.method == "kriging"
                             || opt.method == "ordinary_kriging"
                             || opt.method == "ok";
        const double ztol = kriging ? 1e-4 : 1e-6;
        const double dz = max_abs_diff_f32(got.grid_z, c["grid_z"]);
        check(dz <= ztol, id + " grid_z max_diff=" + std::to_string(dz));
        if (c.contains("variance")) {
            const double dv =
                max_abs_diff_f32(got.variance_grid, c["variance"]);
            check(dv <= ztol,
                  id + " variance max_diff=" + std::to_string(dv));
        }
        const auto& params = c["params"];
        if (params.contains("domain_masked_cells")) {
            check(got.domain_masked_cells
                      == params["domain_masked_cells"].get<int>(),
                  id + " domain_masked_cells");
        }
        if (kriging && params.contains("range")) {
            check(std::fabs(got.range - params["range"].get<double>()) < 1e-9,
                  id + " range");
            check(std::fabs(got.sill - params["sill"].get<double>()) < 1e-9,
                  id + " sill");
            check(std::fabs(got.nugget - params["nugget"].get<double>())
                      < 1e-9,
                  id + " nugget");
            check(got.duplicates_merged
                      == params["duplicates_merged"].get<int>(),
                  id + " duplicates_merged");
            check(got.model == params["model"].get<std::string>(),
                  id + " model");
            check(got.n_samples == params["n_samples"].get<int>(),
                  id + " n_samples");
        }
        if (!kriging && params.contains("power")) {
            check(std::fabs(got.power - params["power"].get<double>()) < 1e-12,
                  id + " power");
            check(got.n_samples == params["n_samples"].get<int>(),
                  id + " n_samples");
        }
    }
    check(n_cases == 19, "all 19 interpolation cases exercised");

    {
        std::vector<SamplePoint> two{{0.0, 0.0, 1.0}, {1.0, 0.0, 2.0}};
        InterpolateOptions opt;
        opt.method = "idw";
        opt.grid_n = 10;
        const FactorGrid undeclared =
            pwb::mapping::interpolate_factor(two, opt);
        check(undeclared.distance_policy == "planar",
              "undeclared crs → planar");
        check(undeclared.distance_policy_annotation
                  == "distance_policy=planar; CRS undeclared — planar "
                     "assumption unverified",
              "undeclared annotation");
        opt.crs = "EPSG:4326";
        const FactorGrid geo = pwb::mapping::interpolate_factor(two, opt);
        check(geo.distance_policy == "planar_degrees",
              "EPSG:4326 default → planar_degrees");
        check(geo.distance_policy_annotation.find("EPSG:4326")
                  != std::string::npos,
              "4326 annotation names CRS");
        opt.crs = "EPSG:3857";
        const FactorGrid proj = pwb::mapping::interpolate_factor(two, opt);
        check(proj.distance_policy == "planar", "EPSG:3857 → planar");
        check(proj.distance_policy_annotation.find("projected")
                  != std::string::npos,
              "3857 annotation projected");
        opt.crs = "EPSG:4326";
        opt.distance_policy = "projected";
        const FactorGrid override_pol =
            pwb::mapping::interpolate_factor(two, opt);
        check(override_pol.distance_policy == "projected",
              "explicit projected honoured on geographic CRS");
    }

    std::printf("%s: %d failure(s) over %d interpolation cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n_cases);
    return g_failures == 0 ? 0 : 1;
}
