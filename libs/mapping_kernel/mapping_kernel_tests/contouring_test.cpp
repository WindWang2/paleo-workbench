// mapping_kernel.contouring — the C++ port vs the frozen Python oracle
// (contouring_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_contour_fixtures.py). Every contour case compares
// polyline count, per-polyline point count and coordinates (1e-9); the
// unit oracles cover DP/Chaikin/length/level ladders exactly.

#include <cmath>
#include <cstdio>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/contouring.hpp>

using pwb::domain::Json;
using pwb::mapping::Grid;
using pwb::mapping::Point;
using pwb::mapping::Polyline;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Grid grid_from_json(const Json& g) {
    Grid grid;
    for (const auto& x : g["x"]) grid.grid_x.push_back(x.get<double>());
    for (const auto& y : g["y"]) grid.grid_y.push_back(y.get<double>());
    grid.w = grid.grid_x.size();
    grid.h = grid.grid_y.size();
    grid.grid_z.reserve(grid.w * grid.h);
    for (const auto& row : g["z"]) {
        for (const auto& v : row) {
            grid.grid_z.push_back(v.is_null() ? std::nan("")
                                              : v.get<double>());
        }
    }
    return grid;
}

Polyline poly_from_json(const Json& p) {
    Polyline out;
    for (const auto& pt : p) {
        out.push_back({pt[0].get<double>(), pt[1].get<double>()});
    }
    return out;
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_MAPPING_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    std::map<std::string, Grid> grids;
    for (auto it = oracle["grids"].begin(); it != oracle["grids"].end(); ++it) {
        grids[it.key()] = grid_from_json(it.value());
    }
    check(grids.size() == 5, "five grids");

    int contour_cases = 0;
    for (const auto& c : oracle["cases"]) {
        const Grid& grid = grids.at(c["grid"].get<std::string>());
        if (c.contains("polylines")) {
            ++contour_cases;
            const auto got = pwb::mapping::marching_squares_contours(
                grid, c["level"].get<double>(),
                c["simplify_tol"].get<double>(),
                c["smooth_iterations"].get<int>());
            const auto& want = c["polylines"];
            check(got.size() == want.size(),
                  c["grid"].get<std::string>() + " level="
                      + std::to_string(c["level"].get<double>())
                      + " tol="
                      + std::to_string(c["simplify_tol"].get<double>())
                      + " iters="
                      + std::to_string(c["smooth_iterations"].get<int>())
                      + ": polyline count " + std::to_string(got.size())
                      + " vs " + std::to_string(want.size()));
            double max_diff = 0.0;
            bool shape_ok = true;
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                if (got[i].size() != poly_from_json(want[i]).size()) {
                    shape_ok = false;
                    break;
                }
                const Polyline expected = poly_from_json(want[i]);
                for (std::size_t k = 0; k < got[i].size(); ++k) {
                    max_diff = std::max(
                        max_diff,
                        std::max(std::fabs(got[i][k][0] - expected[k][0]),
                                 std::fabs(got[i][k][1] - expected[k][1])));
                }
            }
            check(shape_ok, "per-polyline point counts match");
            check(max_diff < 1e-9,
                  "coordinates match (max_diff="
                      + std::to_string(max_diff) + ")");
        } else if (c.contains("nice_levels")) {
            const auto got = pwb::mapping::nice_contour_levels(
                c["vmin"].get<double>(), c["vmax"].get<double>(), 7);
            const auto& want = c["nice_levels"];
            check(got.size() == want.size(), "nice level count");
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                check(std::fabs(got[i] - want[i].get<double>()) < 1e-12,
                      "nice level value");
            }
            const auto quant = pwb::mapping::quantile_contour_levels(grid);
            const auto& want_q = c["quantile_levels"];
            check(quant.size() == want_q.size(), "quantile level count");
            for (std::size_t i = 0; i < quant.size() && i < want_q.size();
                 ++i) {
                check(std::fabs(quant[i] - want_q[i].get<double>()) < 1e-12,
                      "quantile level value");
            }
        }
    }
    check(contour_cases == 168, "all 168 contour cases exercised");

    const Json& units = oracle["units"];
    {
        const Polyline got = pwb::mapping::douglas_peucker(
            poly_from_json(units["dp"]["points"]),
            units["dp"]["tolerance"].get<double>());
        const Polyline want = poly_from_json(units["dp"]["result"]);
        check(got.size() == want.size(), "dp point count");
        for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
            check(std::fabs(got[i][0] - want[i][0]) < 1e-12
                      && std::fabs(got[i][1] - want[i][1]) < 1e-12,
                  "dp point");
        }
    }
    {
        const Polyline got = pwb::mapping::chaikin_smooth(
            poly_from_json(units["chaikin_open"]["points"]),
            units["chaikin_open"]["iterations"].get<int>());
        const Polyline want = poly_from_json(units["chaikin_open"]["result"]);
        check(got.size() == want.size(), "chaikin open count");
        for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
            check(std::fabs(got[i][0] - want[i][0]) < 1e-12
                      && std::fabs(got[i][1] - want[i][1]) < 1e-12,
                  "chaikin open point");
        }
        const Polyline got_closed = pwb::mapping::chaikin_smooth(
            poly_from_json(units["chaikin_closed"]["points"]),
            units["chaikin_closed"]["iterations"].get<int>());
        const Polyline want_closed =
            poly_from_json(units["chaikin_closed"]["result"]);
        check(got_closed.size() == want_closed.size(), "chaikin closed count");
        for (std::size_t i = 0; i < got_closed.size()
             && i < want_closed.size(); ++i) {
            check(std::fabs(got_closed[i][0] - want_closed[i][0]) < 1e-12
                      && std::fabs(got_closed[i][1] - want_closed[i][1])
                             < 1e-12,
                  "chaikin closed point");
        }
    }
    {
        const double got = pwb::mapping::polyline_length(
            poly_from_json(units["length"]["points"]));
        check(std::fabs(got - units["length"]["result"].get<double>())
                  < 1e-12, "polyline length");
    }
    {
        const auto got = pwb::mapping::nice_contour_levels(
            units["nice_edge"]["vmin"].get<double>(),
            units["nice_edge"]["vmax"].get<double>(), 7);
        const auto& want = units["nice_edge"]["result"];
        check(got.size() == want.size(), "nice edge count");
        for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
            check(std::fabs(got[i] - want[i].get<double>()) < 1e-12,
                  "nice edge value");
        }
        check(pwb::mapping::nice_contour_levels(2.0, 2.0, 7).empty(),
              "nice degenerate empty");
    }

    std::printf("%s: %d failure(s) over %d contour cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, contour_cases);
    return g_failures == 0 ? 0 : 1;
}
