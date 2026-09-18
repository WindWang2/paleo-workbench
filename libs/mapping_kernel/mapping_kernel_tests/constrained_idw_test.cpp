// mapping_kernel.constrained_idw — C++ port vs the frozen Python oracle
// (constrained_idw_oracle.json, generated from the REAL adapter + engine by
// tools/oracle/generate_constrained_idw_fixtures.py via a spy on
// generate_constrained_idw: the engine inputs are the exact objects the host
// adapter built, and the expectations come from the real Python run).

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/constrained_idw.hpp>

using pwb::domain::Json;
using pwb::mapping::Point;
using namespace pwb::mapping::constrained_idw;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Point point_from_json(const Json& arr) {
    return Point{arr[0].get<double>(), arr[1].get<double>()};
}

std::vector<Well> wells_from_json(const Json& arr) {
    std::vector<Well> out;
    for (const auto& w : arr) {
        Well well;
        well.well_id = w.value("well_id", std::string());
        well.x = w.value("x", 0.0);
        well.y = w.value("y", 0.0);
        well.value = w.value("value", 0.0);
        well.is_control_point = w.value("is_control_point", false);
        out.push_back(well);
    }
    return out;
}

std::vector<BoundaryPolygon> boundaries_from_json(const Json& arr) {
    std::vector<BoundaryPolygon> out;
    for (const auto& b : arr) {
        BoundaryPolygon boundary;
        for (const auto& p : b["exterior"]) {
            boundary.exterior.push_back(point_from_json(p));
        }
        if (b.contains("holes")) {
            for (const auto& hole : b["holes"]) {
                std::vector<Point> ring;
                for (const auto& p : hole) ring.push_back(point_from_json(p));
                boundary.holes.push_back(std::move(ring));
            }
        }
        out.push_back(std::move(boundary));
    }
    return out;
}

std::vector<BarrierLine> barriers_from_json(const Json& arr) {
    std::vector<BarrierLine> out;
    for (const auto& b : arr) {
        BarrierLine barrier;
        barrier.line_id = b.value("line_id", std::string());
        for (const auto& p : b["points"]) {
            barrier.points.push_back(point_from_json(p));
        }
        barrier.active = b.value("active", true);
        barrier.block_mode = b.value("block_mode", std::string("full_block"));
        barrier.priority = b.value("priority", 3);
        out.push_back(barrier);
    }
    return out;
}

std::vector<DirectionLine> directions_from_json(const Json& arr) {
    std::vector<DirectionLine> out;
    for (const auto& d : arr) {
        DirectionLine dir;
        dir.line_id = d.value("line_id", std::string());
        for (const auto& p : d["points"]) {
            dir.points.push_back(point_from_json(p));
        }
        dir.active = d.value("active", true);
        dir.ratio = d.value("ratio", 18.0);
        dir.influence_radius = d.value("influence_radius", 0.0);
        dir.priority = d.value("priority", 1);
        dir.core_radius = d.value("core_radius", 0.0);
        dir.zone_id = d.value("zone_id", std::string());
        dir.extend_mode = d.value("extend_mode", std::string("auto"));
        dir.transition = d.value("transition", 0.0);
        out.push_back(dir);
    }
    return out;
}

Config config_from_json(const Json& o) {
    Config c;  // defaults mirror the Python dataclass
    c.grid_resolution = o.value("grid_resolution", 160);
    c.power = o.value("power", 2.0);
    c.search_radius = o.value("search_radius", 10000.0);
    c.interpolation_mask_radius = o.value("interpolation_mask_radius", 0.0);
    c.interpolation_mask_use_control_points =
        o.value("interpolation_mask_use_control_points", false);
    c.grid_smoothing_iterations = o.value("grid_smoothing_iterations", 2);
    c.smooth_across_barriers = o.value("smooth_across_barriers", false);
    c.use_extended_search = o.value("use_extended_search", true);
    c.barrier_blank_cells = o.value("barrier_blank_cells", 0.0);
    c.barrier_buffer_distance = o.value("barrier_buffer_distance", 0.0);
    c.barrier_buffer_applies_to_surface =
        o.value("barrier_buffer_applies_to_surface", true);
    c.barrier_buffer_auto = o.value("barrier_buffer_auto", true);
    c.barrier_partition_extension_cells =
        o.value("barrier_partition_extension_cells", 0.0);
    c.barrier_extend_to_boundary = o.value("barrier_extend_to_boundary", false);
    c.well_anchor_enabled = o.value("well_anchor_enabled", true);
    c.well_anchor_radius = o.value("well_anchor_radius", 0.0);
    c.well_anchor_max_residual_fraction =
        o.value("well_anchor_max_residual_fraction", 0.16);
    c.well_anchor_preserve_anisotropy =
        o.value("well_anchor_preserve_anisotropy", true);
    c.direction_taper_plateau = o.value("direction_taper_plateau", 0.85);
    c.direction_smoothing_strength =
        o.value("direction_smoothing_strength", 1.8);
    c.direction_perpendicular_strength =
        o.value("direction_perpendicular_strength", 1.0);
    c.direction_corridor_strength =
        o.value("direction_corridor_strength", 1.0);
    c.along_track_blend_strength =
        o.value("along_track_blend_strength", 0.0);
    c.along_track_min_cell_g = o.value("along_track_min_cell_g", 0.05);
    c.along_track_exp_k = o.value("along_track_exp_k", 6.0);
    c.anisotropic_fill = o.value("anisotropic_fill", true);
    c.use_curve_direction_distance =
        o.value("use_curve_direction_distance", true);
    c.decluster_radius = o.value("decluster_radius", 6500.0);
    c.decluster_strength = o.value("decluster_strength", 2.0);
    c.gap_fill_iterations = o.value("gap_fill_iterations", 8);
    c.limit_interpolation_to_search_radius =
        o.value("limit_interpolation_to_search_radius", true);
    c.min_points = o.value("min_points", 3);
    c.max_points = o.value("max_points", 12);
    // Python dataclass defaults are 0.0/1.0; JSON null means None.
    c.value_min =
        (o.contains("value_min") && o["value_min"].is_null())
            ? std::nullopt
            : std::optional<double>(o.value("value_min", 0.0));
    c.value_max =
        (o.contains("value_max") && o["value_max"].is_null())
            ? std::nullopt
            : std::optional<double>(o.value("value_max", 1.0));
    c.endpoint_tolerance = o.value("endpoint_tolerance", 1e-7);
    c.boundary_margin_ratio = o.value("boundary_margin_ratio", 0.02);
    c.data_hull_buffer_meters = o.value("data_hull_buffer_meters", 0.0);
    return c;
}

// Grid comparison: NaN/finite positions must match exactly; every finite
// cell within max(abs_tol, rel_tol*|want|) (D5). Returns the worst
// diff/allowed ratio (infinity on any NaN-pattern or size mismatch), so the
// caller can enforce the documented tolerance, not just the NaN pattern.
double compare_grid(const std::vector<double>& got, const Json& want_rows,
                    double abs_tol, double rel_tol, double& worst_abs,
                    std::size_t& worst_row, std::size_t& worst_col) {
    std::size_t at = 0;
    worst_abs = 0.0;
    double worst_ratio = 0.0;
    worst_row = 0;
    worst_col = 0;
    const double kInf = std::numeric_limits<double>::infinity();
    const double kNaN = std::numeric_limits<double>::quiet_NaN();
    for (std::size_t row = 0; row < want_rows.size(); ++row) {
        std::size_t col = 0;
        for (const auto& v : want_rows[row]) {
            const double want = v.is_null() ? kNaN : v.get<double>();
            const double have = at < got.size() ? got[at] : kNaN;
            const bool want_fin = std::isfinite(want);
            const bool have_fin = std::isfinite(have);
            if (want_fin != have_fin) return kInf;
            if (want_fin) {
                const double diff = std::fabs(have - want);
                const double allowed =
                    std::max(abs_tol, rel_tol * std::fabs(want));
                if (diff > worst_abs) {
                    worst_abs = diff;
                    worst_row = row;
                    worst_col = col;
                }
                worst_ratio = std::max(worst_ratio, diff / allowed);
            }
            ++at;
            ++col;
        }
    }
    if (at != got.size()) return kInf;
    return worst_ratio;
}

// np.mean over the finite cells in row-major order: the full numpy pairwise
// summation tree (recursion above the 128-element block), matching
// np.add.reduce exactly.
double numpy_pairwise(const double* a, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; ++i) res += a[i];
        return res;
    }
    if (n <= 128) {
        double r[8];
        for (std::size_t i = 0; i < 8; ++i) r[i] = a[i];
        std::size_t i = 8;
        for (; i < n - (n % 8); i += 8) {
            r[0] += a[i + 0];
            r[1] += a[i + 1];
            r[2] += a[i + 2];
            r[3] += a[i + 3];
            r[4] += a[i + 4];
            r[5] += a[i + 5];
            r[6] += a[i + 6];
            r[7] += a[i + 7];
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3])) +
                     ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return numpy_pairwise(a, n2) + numpy_pairwise(a + n2, n - n2);
}

double finite_mean(const std::vector<double>& grid) {
    std::vector<double> finite;
    for (double v : grid) {
        if (std::isfinite(v)) finite.push_back(v);
    }
    if (finite.empty()) return std::numeric_limits<double>::quiet_NaN();
    return numpy_pairwise(finite.data(), finite.size()) /
           static_cast<double>(finite.size());
}

void run_numeric_case(const Json& engine_inputs, const Json& expected,
                      const std::string& name) {
    const std::vector<Well> wells = wells_from_json(engine_inputs["wells"]);
    const std::vector<BoundaryPolygon> boundaries =
        boundaries_from_json(engine_inputs["boundaries"]);
    const std::vector<BarrierLine> barriers =
        barriers_from_json(engine_inputs["barriers"]);
    const std::vector<DirectionLine> directions =
        directions_from_json(engine_inputs["directions"]);
    const Config config = config_from_json(engine_inputs["config"]);

    const Result result =
        generate_constrained_idw(wells, boundaries, barriers, directions,
                                 config);

    const Json& want_x = expected["grid_x"];
    const Json& want_y = expected["grid_y"];
    check(result.grid_x.size() == want_x.size(),
          name + ": grid_x length " +
              std::to_string(result.grid_x.size()) + " vs " +
              std::to_string(want_x.size()));
    double axis_worst = 0.0;
    for (std::size_t i = 0; i < std::min(result.grid_x.size(),
                                         static_cast<std::size_t>(want_x.size()));
         ++i) {
        axis_worst =
            std::max(axis_worst, std::fabs(result.grid_x[i] -
                                           want_x[i].get<double>()));
    }
    for (std::size_t i = 0; i < std::min(result.grid_y.size(),
                                         static_cast<std::size_t>(want_y.size()));
         ++i) {
        axis_worst =
            std::max(axis_worst, std::fabs(result.grid_y[i] -
                                           want_y[i].get<double>()));
    }
    check(axis_worst <= 1e-12,
          name + ": grid axes worst " + std::to_string(axis_worst));

    double worst_abs = 0.0;
    std::size_t worst_row = 0, worst_col = 0;
    const double worst_ratio =
        compare_grid(result.grid_z, expected["grid_z"], 1e-8, 1e-9, worst_abs,
                     worst_row, worst_col);
    std::ostringstream msg;
    msg << name << ": grid_z NaN pattern, size or tolerance (worst abs "
        << worst_abs << " at [" << worst_row << "," << worst_col
        << "], tol ratio " << worst_ratio << ")";
    check(std::isfinite(worst_ratio) && worst_ratio <= 1.0, msg.str());

    // Diagnostics: every frozen surface key must match exactly.
    if (engine_inputs.contains("diagnostics")) {
        for (auto it = engine_inputs["diagnostics"].begin();
             it != engine_inputs["diagnostics"].end(); ++it) {
            const std::string& key = it.key();
            const double want = it.value().get<double>();
            const auto found = result.diagnostics.find(key);
            if (found == result.diagnostics.end()) {
                check(false, name + ": missing diagnostic " + key);
                continue;
            }
            const double allowed = 1e-9 * std::max(1.0, std::fabs(want));
            check(std::fabs(found->second - want) <= allowed,
                  name + ": diagnostic " + key + " got " +
                      std::to_string(found->second) + " want " +
                      std::to_string(want));
        }
    }

    // Adapter-contract statistics recomputed from the C++ grid.
    if (expected.contains("min")) {
        double lo = std::numeric_limits<double>::infinity();
        double hi = -std::numeric_limits<double>::infinity();
        for (double v : result.grid_z) {
            if (std::isfinite(v)) {
                lo = std::min(lo, v);
                hi = std::max(hi, v);
            }
        }
        const double mean = finite_mean(result.grid_z);
        const double tol = 1e-9;
        check(std::fabs(lo - expected["min"].get<double>()) <=
                  tol * std::max(1.0, std::fabs(lo)),
              name + ": min");
        check(std::fabs(hi - expected["max"].get<double>()) <=
                  tol * std::max(1.0, std::fabs(hi)),
              name + ": max");
        check(std::fabs(mean - expected["mean"].get<double>()) <=
                  tol * std::max(1.0, std::fabs(mean)),
              name + ": mean got " + std::to_string(mean) + " want " +
                  std::to_string(expected["mean"].get<double>()));
        check(result.grid_z.size() ==
                  static_cast<std::size_t>(want_x.size()) * want_x.size(),
              name + ": grid size");
        // Adapter-contract scalars cross-checked against the engine inputs
        // (the C++ engine consumes the same resolved values).
        check(result.diagnostics.at("有效打断线数") ==
                  static_cast<double>(expected["n_break_lines"].get<int>()),
              name + ": n_break_lines");
        check(result.diagnostics.at("有效方向线数") ==
                  static_cast<double>(expected["n_direction_lines"].get<int>()),
              name + ": n_direction_lines");
        check(config.search_radius == expected["search_radius"].get<double>(),
              name + ": search_radius");
        // With direction lines the adapter zeroes the CONFIG decluster radius
        // while the result dict still reports the derived value.
        if (expected["n_direction_lines"].get<int>() == 0) {
            check(config.decluster_radius ==
                      expected["decluster_radius"].get<double>(),
                  name + ": decluster_radius");
        } else {
            check(config.decluster_radius == 0.0,
                  name + ": decluster_radius zeroed with directions");
        }
    }
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CIDW_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    Result fault_grid;
    Result surface_only_grid;
    bool have_fault = false;
    bool have_surface_only = false;
    for (const auto& case_json : oracle["cases"]) {
        const std::string name = case_json.value("name", std::string(""));
        const std::string kind = case_json.value("kind", std::string(""));
        if (kind == "engine_error") {
            // Replay the frozen engine inputs; expect the exact Python error.
            const Json& engine_inputs = case_json["engine_inputs"];
            bool raised = false;
            std::string message;
            try {
                generate_constrained_idw(
                    wells_from_json(engine_inputs["wells"]),
                    boundaries_from_json(engine_inputs["boundaries"]),
                    barriers_from_json(engine_inputs["barriers"]),
                    directions_from_json(engine_inputs["directions"]),
                    config_from_json(engine_inputs["config"]));
            } catch (const std::invalid_argument& exc) {
                raised = true;
                message = exc.what();
            }
            check(raised, name + ": expected std::invalid_argument");
            check(message == case_json["expected_error"].get<std::string>(),
                  name + ": error text <" + message + "> vs <" +
                      case_json["expected_error"].get<std::string>() + ">");
            continue;
        }
        const Json& engine_inputs = case_json["engine_inputs"];
        const Json& expected = case_json["expected"];
        const Result result = generate_constrained_idw(
            wells_from_json(engine_inputs["wells"]),
            boundaries_from_json(engine_inputs["boundaries"]),
            barriers_from_json(engine_inputs["barriers"]),
            directions_from_json(engine_inputs["directions"]),
            config_from_json(engine_inputs["config"]));
        // Engine-direct cases freeze only the grid (no adapter scalars).
        run_numeric_case(engine_inputs, expected, name);
        if (kind == "adapter") {
            const auto wells_diag = result.diagnostics.find("参与井点数");
            const int want_points = expected["n_points"].get<int>();
            check(wells_diag != result.diagnostics.end() &&
                      wells_diag->second == static_cast<double>(want_points),
                  name + ": n_points got " +
                      (wells_diag != result.diagnostics.end()
                           ? std::to_string(wells_diag->second)
                           : std::string("<missing>")) +
                      " want " + std::to_string(want_points));
        }
    }

    std::printf("checks=%d failures=%d\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
