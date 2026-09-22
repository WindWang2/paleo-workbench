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



int main() {
    test_idw_keep_policy_preserves_duplicate_contract();
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
