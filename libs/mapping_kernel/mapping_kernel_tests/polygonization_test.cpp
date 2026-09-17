// mapping_kernel.polygonization — C++ port vs the frozen Python oracle
// (polygonization_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_polygonization_fixtures.py). Shapely repair is
// identity-patched in the freeze; this kernel does not call make_valid.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/polygonization.hpp>

using pwb::domain::Json;
using pwb::mapping::Grid;
using pwb::mapping::Point;
using pwb::mapping::Polygon;
using pwb::mapping::Ring;

namespace {

int g_failures = 0;
double g_max_coord_diff = 0.0;

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

Ring ring_from_json(const Json& r) {
    Ring out;
    for (const auto& pt : r) {
        out.push_back({pt[0].get<double>(), pt[1].get<double>()});
    }
    return out;
}

std::vector<Polygon> polys_from_json(const Json& arr) {
    std::vector<Polygon> out;
    for (const auto& p : arr) {
        Polygon poly;
        poly.exterior = ring_from_json(p["exterior"]);
        for (const auto& h : p["holes"]) {
            poly.holes.push_back(ring_from_json(h));
        }
        out.push_back(std::move(poly));
    }
    return out;
}

std::vector<std::int16_t> class_from_json(const Json& rows) {
    std::vector<std::int16_t> out;
    for (const auto& row : rows) {
        for (const auto& v : row) {
            out.push_back(static_cast<std::int16_t>(v.get<int>()));
        }
    }
    return out;
}

double ring_max_diff(const Ring& got, const Ring& want) {
    if (got.size() != want.size()) {
        return std::numeric_limits<double>::infinity();
    }
    double worst = 0.0;
    for (std::size_t i = 0; i < got.size(); ++i) {
        worst = std::max(worst, std::fabs(got[i][0] - want[i][0]));
        worst = std::max(worst, std::fabs(got[i][1] - want[i][1]));
    }
    return worst;
}

void check_ring(const Ring& got, const Ring& want, const std::string& what) {
    check(got.size() == want.size(),
          what + " vertex count " + std::to_string(got.size()) + " vs "
              + std::to_string(want.size()));
    const double d = ring_max_diff(got, want);
    if (std::isfinite(d)) g_max_coord_diff = std::max(g_max_coord_diff, d);
    check(d < 1e-9, what + " coords max_diff=" + std::to_string(d));
}

void check_polys(const std::vector<Polygon>& got, const Json& want_json,
                 const std::string& what) {
    const auto want = polys_from_json(want_json);
    check(got.size() == want.size(),
          what + " polygon count " + std::to_string(got.size()) + " vs "
              + std::to_string(want.size()));
    for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
        const std::string pfx = what + " p" + std::to_string(i);
        check_ring(got[i].exterior, want[i].exterior, pfx + " exterior");
        check(got[i].holes.size() == want[i].holes.size(),
              pfx + " hole count " + std::to_string(got[i].holes.size())
                  + " vs " + std::to_string(want[i].holes.size()));
        for (std::size_t h = 0; h < got[i].holes.size() && h < want[i].holes.size();
             ++h) {
            check_ring(got[i].holes[h], want[i].holes[h],
                       pfx + " hole" + std::to_string(h));
        }
    }
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_POLY_FIXTURE;
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

    const Json& units = oracle["units"];
    {
        for (const auto& e : units["shoelace"]) {
            const double got =
                pwb::mapping::shoelace_area(ring_from_json(e["ring"]));
            check(std::fabs(got - e["result"].get<double>()) < 1e-12,
                  "shoelace");
        }
    }
    {
        for (const auto& e : units["signed"]) {
            const double got =
                pwb::mapping::signed_area(ring_from_json(e["ring"]));
            check(std::fabs(got - e["result"].get<double>()) < 1e-12, "signed");
        }
    }
    {
        for (const auto& e : units["centroid"]) {
            const Point got =
                pwb::mapping::ring_centroid(ring_from_json(e["ring"]));
            const auto& want = e["result"];
            check(std::fabs(got[0] - want[0].get<double>()) < 1e-12
                      && std::fabs(got[1] - want[1].get<double>()) < 1e-12,
                  "centroid");
        }
    }
    {
        int i = 0;
        for (const auto& e : units["simplify"]) {
            const Ring got =
                pwb::mapping::simplify_collinear_ring(ring_from_json(e["ring"]));
            check_ring(got, ring_from_json(e["result"]),
                       "simplify[" + std::to_string(i++) + "]");
        }
    }
    {
        const auto& f = units["filter"];
        const auto geoms = polys_from_json(f["geoms"]);
        const auto kept = pwb::mapping::filter_small_polygons(
            geoms, f["min_area"].get<double>());
        check_polys(kept, f["kept"], "filter min_area");
        check(static_cast<int>(geoms.size() - kept.size())
                  == f["dropped"].get<int>(),
              "filter dropped");
        const auto kept0 =
            pwb::mapping::filter_small_polygons(geoms, 0.0);
        check(static_cast<int>(geoms.size() - kept0.size())
                  == f["min_area_zero_dropped"].get<int>(),
              "filter min_area=0 dropped");
        const auto equal_geoms = polys_from_json(f["equal_geoms"]);
        const auto kept_eq =
            pwb::mapping::filter_small_polygons(equal_geoms, 1.0);
        check(static_cast<int>(equal_geoms.size() - kept_eq.size())
                  == f["min_area_equal_dropped"].get<int>(),
              "filter equal dropped");
        check_polys(kept_eq, f["min_area_equal_kept"], "filter equal kept");
    }
    {
        for (const auto& e : units["default_thresholds"]) {
            const auto got = pwb::mapping::default_class_thresholds(
                e["vmin"].get<double>(), e["vmax"].get<double>());
            const auto& want = e["result"];
            check(got.size() == want.size(), "default_thresholds count");
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                check(std::fabs(got[i] - want[i].get<double>()) < 1e-12,
                      "default_thresholds value");
            }
        }
    }
    {
        const auto& u = units["unique_thresholds"];
        std::vector<double> input;
        for (const auto& v : u["input"]) input.push_back(v.get<double>());
        const auto got = pwb::mapping::unique_sorted_thresholds(input);
        const auto& want = u["result"];
        check(got.size() == want.size(), "unique_thresholds count");
        for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
            check(std::fabs(got[i] - want[i].get<double>()) < 1e-12,
                  "unique_thresholds value");
        }
    }

    int n_classify = 0;
    int n_polygonize = 0;
    int n_factor = 0;
    for (const auto& c : oracle["cases"]) {
        const std::string id = c["id"].get<std::string>();
        const std::string kind = c["kind"].get<std::string>();
        const Grid& grid = grids.at(c["grid"].get<std::string>());
        if (kind == "classify") {
            ++n_classify;
            std::vector<double> thresholds;
            if (c["thresholds_in"].is_null()) {
                thresholds = pwb::mapping::default_class_thresholds(
                    c["vmin"].get<double>(), c["vmax"].get<double>());
            } else {
                std::vector<double> raw;
                for (const auto& v : c["thresholds_in"]) {
                    raw.push_back(v.get<double>());
                }
                thresholds = pwb::mapping::unique_sorted_thresholds(raw);
            }
            const auto& want_th = c["thresholds"];
            check(thresholds.size() == want_th.size(), id + " threshold count");
            for (std::size_t i = 0; i < thresholds.size() && i < want_th.size();
                 ++i) {
                check(std::fabs(thresholds[i] - want_th[i].get<double>())
                          < 1e-12,
                      id + " threshold value");
            }
            const int n_classes = c["n_classes"].get<int>();
            const auto got =
                pwb::mapping::classify_grid(grid, thresholds, n_classes);
            const auto want = class_from_json(c["class_grid"]);
            check(got.size() == want.size(), id + " class_grid size");
            bool same = got.size() == want.size();
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                if (got[i] != want[i]) {
                    same = false;
                    break;
                }
            }
            check(same, id + " class_grid values");
        } else if (kind == "polygonize") {
            ++n_polygonize;
            const auto class_grid = class_from_json(c["class_grid"]);
            const auto traced = pwb::mapping::polygonize_class(
                grid, class_grid, c["target_class"].get<int>());
            check(traced.second.holes_promoted_to_exterior
                      == c["holes_promoted_to_exterior"].get<int>(),
                  id + " holes_promoted_to_exterior");
            check_polys(traced.first, c["polygons"], id);
        } else if (kind == "factor") {
            ++n_factor;
            std::optional<double> level;
            if (!c["level_in"].is_null()) level = c["level_in"].get<double>();
            const auto got = pwb::mapping::polygonize_factor_grid(grid, level);
            check(std::fabs(got.level - c["level"].get<double>()) < 1e-12,
                  id + " level");
            check(static_cast<int>(got.polygons.size())
                      == c["n_polygons"].get<int>(),
                  id + " n_polygons");
            check(got.qc.holes_promoted_to_exterior
                      == c["holes_promoted_to_exterior"].get<int>(),
                  id + " holes_promoted_to_exterior");
            check_polys(got.polygons, c["polygons"], id);
        } else {
            check(false, "unknown kind " + kind);
        }
    }
    check(n_classify == 7, "all 7 classify cases exercised");
    check(n_polygonize == 12, "all 12 polygonize cases exercised");
    check(n_factor == 5, "all 5 factor cases exercised");

    std::printf(
        "%s: %d failure(s) over %d classify + %d polygonize + %d factor "
        "cases (max coord diff %.3g)\n",
        g_failures == 0 ? "PASS" : "FAIL", g_failures, n_classify,
        n_polygonize, n_factor, g_max_coord_diff);
    return g_failures == 0 ? 0 : 1;
}
