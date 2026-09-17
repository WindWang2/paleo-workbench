// mapping_kernel.class_grid — C++ port vs the frozen Python oracle.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <exception>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/class_grid.hpp>

using pwb::domain::Json;
using pwb::mapping::ClassGrid;
using pwb::mapping::FaciesPoint;
using pwb::mapping::Point;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::vector<FaciesPoint> points_from_json(const Json& arr) {
    std::vector<FaciesPoint> out;
    for (const auto& p : arr) {
        FaciesPoint s;
        s.x = p[0].get<double>();
        s.y = p[1].get<double>();
        s.facies = p[2].get<std::string>();
        out.push_back(s);
    }
    return out;
}

std::vector<Point> ring_from_json(const Json& arr) {
    std::vector<Point> out;
    if (!arr.is_array()) return out;
    for (const auto& pt : arr) {
        out.push_back({pt[0].get<double>(), pt[1].get<double>()});
    }
    return out;
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

double max_class_diff(const std::vector<float>& got, const Json& want_rows) {
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
            worst = std::max(
                worst, std::fabs(static_cast<double>(a) - v.get<double>()));
            ++at;
        }
    }
    if (at != got.size()) return std::numeric_limits<double>::infinity();
    return worst;
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CLASS_GRID_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    {
        const auto& pip = oracle["pip"];
        const auto ring = ring_from_json(pip["ring"]);
        const double x = pip["edge_point"][0].get<double>();
        const double y = pip["edge_point"][1].get<double>();
        check(pwb::mapping::point_in_ring_inclusive(x, y, ring)
                  == pip["inclusive"].get<bool>(),
              "inclusive PIP on square edge");
        check(pip["inclusive"].get<bool>() != pip["even_odd"].get<bool>(),
              "inclusive vs even-odd disagree on edge");
    }

    try {
        pwb::mapping::nearest_neighbor_class_grid(
            {}, {0.0, 0.0, 1.0, 1.0}, 8);
        check(false, "empty points should throw");
    } catch (const std::invalid_argument& ex) {
        check(std::string(ex.what()) == oracle["empty_error"].get<std::string>(),
              "empty error message");
    }

    int n_cases = 0;
    for (const auto& c : oracle["cases"]) {
        ++n_cases;
        const std::string id = c["id"].get<std::string>();
        const auto pts = points_from_json(c["points"]);
        const auto& ext = c["extent"];
        const std::array<double, 4> extent{
            ext[0].get<double>(), ext[1].get<double>(),
            ext[2].get<double>(), ext[3].get<double>()};
        std::vector<Point> clip;
        if (c.contains("clip_ring") && c["clip_ring"].is_array()) {
            clip = ring_from_json(c["clip_ring"]);
        }
        ClassGrid got;
        try {
            got = pwb::mapping::nearest_neighbor_class_grid(
                pts, extent, c["grid_n"].get<int>(), clip);
        } catch (const std::exception& ex) {
            check(false, id + " threw: " + ex.what());
            continue;
        }
        const auto& names = c["facies_names"];
        check(got.facies_names.size() == names.size(), id + " name count");
        for (std::size_t i = 0; i < got.facies_names.size() && i < names.size();
             ++i) {
            check(got.facies_names[i] == names[i].get<std::string>(),
                  id + " facies name");
        }
        const double dx = max_abs_diff_axis(got.grid_x, c["grid_x"]);
        const double dy = max_abs_diff_axis(got.grid_y, c["grid_y"]);
        check(dx < 1e-12, id + " grid_x max_diff=" + std::to_string(dx));
        check(dy < 1e-12, id + " grid_y max_diff=" + std::to_string(dy));
        const double dz = max_class_diff(got.grid_z, c["grid_z"]);
        check(dz == 0.0, id + " grid_z max_diff=" + std::to_string(dz));
    }
    check(n_cases == 10, "all 10 class-grid cases exercised");

    std::printf("%s: %d failure(s) over %d class-grid cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n_cases);
    return g_failures == 0 ? 0 : 1;
}
