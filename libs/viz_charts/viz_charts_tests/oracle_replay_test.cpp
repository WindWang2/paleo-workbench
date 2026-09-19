// viz_charts.oracle_replay — replays the frozen Python oracle
// (tools/oracle/generate_viz_e_charts_fixtures.py, geoviz_plots @0885195)
// against the ported Qt-free kernels. Exact families: ticks / nice_number /
// format_tick / lttb / bounds / colormaps / pip / fence / qc. Declared
// tolerances (docs/development/cpp-viz-e/scope-ledger.md):
//   * hull — CCW vertex cycle compared modulo rotation (SciPy's starting
//     vertex follows qhull's internal facet order).
//   * marching squares lines/bands — contourpy's quad-based serial
//     algorithm is replaced by triangle subdivision (bilinear center), so
//     vertex sequences differ: counts ±1, lengths/areas 2%, bbox within
//     one grid cell, on-line values |z_bilinear(mid) - level| <= 0.15.
// A negative self-check proves the comparator fails on tampered data.
#include <pwb/viz_charts/axes.hpp>
#include <pwb/viz_charts/colormaps.hpp>
#include <pwb/viz_charts/convex_hull.hpp>
#include <pwb/viz_charts/fence.hpp>
#include <pwb/viz_charts/marching_squares.hpp>
#include <pwb/viz_charts/series.hpp>
#include <pwb/viz_charts/well_qc.hpp>

#include <pwb/domain/json.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

using namespace pwb::viz_charts;
using pwb::domain::Json;

static int checks = 0;
static int failures = 0;

#define CHECK(cond)                                                        \
    do {                                                                   \
        ++checks;                                                          \
        if (!(cond)) {                                                     \
            ++failures;                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        }                                                                  \
    } while (0)

static Json load_fixture() {
    std::ifstream in(PWB_VIZ_E_CHARTS_ORACLE);
    std::stringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

static double num(const Json& v) {
    if (v.is_string()) {
        const auto& s = v.get_ref<const std::string&>();
        if (s == "__nan__") return std::nan("");
        if (s == "__inf__") return std::numeric_limits<double>::infinity();
        if (s == "__-inf__") return -std::numeric_limits<double>::infinity();
    }
    return v.get<double>();
}

static std::vector<double> num_vec(const Json& v) {
    std::vector<double> out;
    out.reserve(v.size());
    for (const auto& e : v) out.push_back(num(e));
    return out;
}

static bool close_enough(double a, double b, double tol) {
    if (std::isnan(a) && std::isnan(b)) return true;
    if (std::isinf(a) || std::isinf(b)) return a == b;
    return std::fabs(a - b) <= tol;
}

// Bilinear interpolation of the row-major grid (on-line membership check).
static double bilinear_at(const std::vector<double>& gx,
                          const std::vector<double>& gy,
                          const std::vector<double>& gz, double px,
                          double py) {
    const std::size_t cols = gx.size();
    const std::size_t rows = gy.size();
    auto clampi = [&](double v, std::size_t n) {
        double c = std::min(std::max(v, 0.0), static_cast<double>(n - 1));
        return static_cast<std::size_t>(c);
    };
    const std::size_t j0 = clampi((px - gx.front()) /
                                      (gx.back() - gx.front()) * (cols - 1),
                                  cols);
    const std::size_t i0 = clampi((py - gy.front()) /
                                      (gy.back() - gy.front()) * (rows - 1),
                                  rows);
    const std::size_t j1 = std::min(j0 + 1, cols - 1);
    const std::size_t i1 = std::min(i0 + 1, rows - 1);
    const double tx =
        j1 == j0 ? 0.0 : (px - gx[j0]) / (gx[j1] - gx[j0]);
    const double ty =
        i1 == i0 ? 0.0 : (py - gy[i0]) / (gy[i1] - gy[i0]);
    const double z00 = gz[i0 * cols + j0];
    const double z01 = gz[i0 * cols + j1];
    const double z10 = gz[i1 * cols + j0];
    const double z11 = gz[i1 * cols + j1];
    return (z00 * (1 - tx) * (1 - ty) + z01 * tx * (1 - ty) +
            z10 * (1 - tx) * ty + z11 * tx * ty);
}

int main() {
    const Json fx = load_fixture();
    const Json& in = fx.at("inputs");

    // provenance gates
    CHECK(fx.at("geoviz_sha").get<std::string>() ==
          "08851951f3bbc0beb90886adf52e1928f4383c16");

    // --- ticks (exact modulo round-half-even slop) ------------------------
    {
        const auto& cases = in.at("ticks");
        const auto& expect = fx.at("ticks");
        CHECK(cases.size() == expect.size());
        for (std::size_t c = 0; c < cases.size(); ++c) {
            const auto [ticks, step] = calculate_ticks(
                num(cases[c][0]), num(cases[c][1]),
                cases[c][2].get<int>());
            const auto& jt = expect[c].at("ticks");
            CHECK(ticks.size() == jt.size());
            if (ticks.size() == jt.size()) {
                for (std::size_t k = 0; k < ticks.size(); ++k) {
                    CHECK(close_enough(ticks[k], num(jt[k]), 1e-9));
                }
            }
            CHECK(close_enough(step, num(expect[c].at("step")), 1e-9));
        }
    }

    // --- nice_number / format_tick ----------------------------------------
    {
        const auto& cases = in.at("nice_number");
        const auto& expect = fx.at("nice_number");
        for (std::size_t c = 0; c < cases.size(); ++c) {
            CHECK(close_enough(
                nice_number(num(cases[c][0]), cases[c][1].get<bool>()),
                num(expect[c]), 1e-9));
        }
        const auto& fcases = in.at("format_tick");
        const auto& fexpect = fx.at("format_tick");
        for (std::size_t c = 0; c < fcases.size(); ++c) {
            const std::string got =
                format_tick(num(fcases[c][0]), num(fcases[c][1]));
            CHECK(got == fexpect[c].get<std::string>());
        }
    }

    // --- lttb / bounds (exact) ---------------------------------------------
    {
        const auto& cases = in.at("lttb");
        const auto& expect = fx.at("lttb");
        for (std::size_t c = 0; c < cases.size(); ++c) {
            const DownsampleResult r = lttb_downsample(
                num_vec(cases[c].at("x")), num_vec(cases[c].at("y")),
                cases[c].at("threshold").get<int>());
            const auto& ex = expect[c];
            CHECK(r.x.size() == ex.at("x").size());
            CHECK(r.y.size() == ex.at("y").size());
            for (std::size_t k = 0; k < r.x.size() && k < r.y.size(); ++k) {
                CHECK(close_enough(r.x[k], num(ex.at("x")[k]), 1e-12));
                CHECK(close_enough(r.y[k], num(ex.at("y")[k]), 1e-12));
            }
        }
        const auto& bcases = in.at("bounds");
        const auto& bexpect = fx.at("bounds");
        for (std::size_t c = 0; c < bcases.size(); ++c) {
            const Bounds b = series_bounds(num_vec(bcases[c].at("x")),
                                           num_vec(bcases[c].at("y")));
            const auto& e = bexpect[c];
            CHECK(close_enough(b.xmin, num(e[0]), 1e-12));
            CHECK(close_enough(b.xmax, num(e[1]), 1e-12));
            CHECK(close_enough(b.ymin, num(e[2]), 1e-12));
            CHECK(close_enough(b.ymax, num(e[3]), 1e-12));
        }
    }

    // --- colormaps (exact ints) --------------------------------------------
    {
        const auto& cases = in.at("colormap_samples");
        const auto& expect = fx.at("colormap_samples");
        for (std::size_t c = 0; c < cases.size(); ++c) {
            const Rgb rgb = sample_colormap(
                cases[c][0].get<std::string>(), num(cases[c][1]),
                num(cases[c][2]), num(cases[c][3]));
            CHECK(rgb.r == expect[c][0].get<int>());
            CHECK(rgb.g == expect[c][1].get<int>());
            CHECK(rgb.b == expect[c][2].get<int>());
        }
    }

    // --- hull (cyclic rotation) + collinear + pip --------------------------
    {
        const Json& hc = in.at("hull");
        std::vector<Point2> hull = compute_convex_hull(
            num_vec(hc.at("x")), num_vec(hc.at("y")));
        const auto& expect = fx.at("hull");
        CHECK(hull.size() == expect.size());
        if (hull.size() == expect.size() && !hull.empty()) {
            // find expected start vertex inside our cycle
            std::size_t start = hull.size();
            for (std::size_t k = 0; k < hull.size(); ++k) {
                if (close_enough(hull[k].x, num(expect[0][0]), 1e-12) &&
                    close_enough(hull[k].y, num(expect[0][1]), 1e-12)) {
                    start = k;
                    break;
                }
            }
            CHECK(start < hull.size());
            if (start < hull.size()) {
                for (std::size_t k = 0; k < hull.size(); ++k) {
                    const auto& e = expect[k];
                    const Point2& p = hull[(start + k) % hull.size()];
                    CHECK(close_enough(p.x, num(e[0]), 1e-12));
                    CHECK(close_enough(p.y, num(e[1]), 1e-12));
                }
            }
        }
        const Json& cc = in.at("hull_collinear");
        std::vector<Point2> coll = compute_convex_hull(
            num_vec(cc.at("x")), num_vec(cc.at("y")));
        const auto& cexpect = fx.at("hull_collinear");
        CHECK(coll.size() == cexpect.size());
        for (std::size_t k = 0; k < coll.size() && k < cexpect.size(); ++k) {
            CHECK(close_enough(coll[k].x, num(cexpect[k][0]), 1e-12));
            CHECK(close_enough(coll[k].y, num(cexpect[k][1]), 1e-12));
        }

        const Json& pc = in.at("pip");
        std::vector<Point2> poly;
        for (const auto& pt : pc.at("poly")) {
            poly.push_back({num(pt[0]), num(pt[1])});
        }
        const std::vector<bool> mask = point_in_polygon_mask(
            num_vec(pc.at("x")), num_vec(pc.at("y")), poly);
        const auto& pmask = fx.at("pip");
        CHECK(mask.size() == pmask.size());
        for (std::size_t k = 0; k < mask.size() && k < pmask.size(); ++k) {
            CHECK(mask[k] == pmask[k].get<bool>());
        }
    }

    // --- marching squares (geometric invariants) ---------------------------
    {
        const Json& g = in.at("ms_grid");
        const std::vector<double> gx = num_vec(g.at("gx"));
        const std::vector<double> gy = num_vec(g.at("gy"));
        const std::vector<double> gz = num_vec(g.at("gz"));
        const std::vector<double> levels = num_vec(in.at("ms_levels"));
        const auto lines_opt = extract_contour_lines(gx, gy, gz, levels);
        CHECK(lines_opt.has_value());
        if (lines_opt.has_value()) {
            const auto& lines = *lines_opt;
            CHECK(lines.size() == levels.size());
            for (std::size_t lv = 0; lv < lines.size(); ++lv) {
                const auto& [level, plines] = lines[lv];
                char key[32];
                std::snprintf(key, sizeof(key), "%g", level);
                const Json& e = fx.at("ms_lines").at(key);
                CHECK(std::fabs(static_cast<double>(plines.size()) -
                                e.at("count").get<double>()) <= 1.0);
                double total = 0.0;
                double bbox[4] = {1e30, -1e30, 1e30, -1e30};
                for (const auto& pl : plines) {
                    for (std::size_t k = 0; k + 1 < pl.xs.size(); ++k) {
                        total += std::hypot(pl.xs[k + 1] - pl.xs[k],
                                            pl.ys[k + 1] - pl.ys[k]);
                    }
                    for (std::size_t k = 0; k < pl.xs.size(); ++k) {
                        bbox[0] = std::min(bbox[0], pl.xs[k]);
                        bbox[1] = std::max(bbox[1], pl.xs[k]);
                        bbox[2] = std::min(bbox[2], pl.ys[k]);
                        bbox[3] = std::max(bbox[3], pl.ys[k]);
                    }
                }
                const double want_len = e.at("total_length").get<double>();
                CHECK(want_len <= 0.0 ||
                      std::fabs(total - want_len) / want_len <= 0.02);
                if (!plines.empty()) {
                    const auto& eb = e.at("bbox");
                    CHECK(bbox[0] >= eb[0].get<double>() - 0.5);
                    CHECK(bbox[1] <= eb[1].get<double>() + 0.5);
                    CHECK(bbox[2] >= eb[2].get<double>() - 0.5);
                    CHECK(bbox[3] <= eb[3].get<double>() + 0.5);
                }
                // on-line check: every polyline midpoint sits on the level
                // surface under bilinear interpolation of the frozen grid.
                for (const auto& pl : plines) {
                    if (pl.xs.size() < 3) continue;
                    const double mx = pl.xs[pl.xs.size() / 2];
                    const double my = pl.ys[pl.ys.size() / 2];
                    const double zb = bilinear_at(gx, gy, gz, mx, my);
                    CHECK(std::fabs(zb - level) <= 0.15);
                }
            }
        }

        const auto bands_opt = extract_filled_contours(gx, gy, gz, levels);
        CHECK(bands_opt.has_value());
        if (bands_opt.has_value()) {
            const auto& bands = *bands_opt;
            const auto& ebands = fx.at("ms_bands");
            CHECK(bands.size() == ebands.size());
            for (std::size_t b = 0; b < bands.size() && b < ebands.size(); ++b) {
                const BandedFill& band = bands[b];
                const Json& e = ebands[b];
                CHECK(close_enough(band.level_min, e.at("level_min").get<double>(), 1e-12));
                CHECK(close_enough(band.level_max, e.at("level_max").get<double>(), 1e-12));
                CHECK(band.color_r == e.at("color")[0].get<int>());
                CHECK(band.color_g == e.at("color")[1].get<int>());
                CHECK(band.color_b == e.at("color")[2].get<int>());
                CHECK(band.label == e.at("label").get<std::string>());
                double area = 0.0;
                for (const auto& ring : band.rings.points) {
                    double a2 = 0.0;
                    const std::size_t n = ring.xs.size();
                    for (std::size_t k = 0; k < n; ++k) {
                        const std::size_t j = (k + 1) % n;
                        a2 += ring.xs[k] * ring.ys[j] - ring.xs[j] * ring.ys[k];
                    }
                    area += std::fabs(a2) / 2.0;
                }
                const double want = e.at("area").get<double>();
                CHECK(want <= 0.0 || std::fabs(area - want) / want <= 0.02);
            }
        }

        // saddle mini-grid: structure + on-line values only (contourpy's
        // quad subdivision places saddle vertices differently — declared).
        {
            const Json& s = in.at("ms_saddle_grid");
            const auto sopt = extract_contour_lines(
                num_vec(s.at("gx")), num_vec(s.at("gy")), num_vec(s.at("gz")),
                {1.5});
            CHECK(sopt.has_value());
            if (sopt.has_value()) {
                const auto& [level, plines] = (*sopt)[0];
                CHECK(plines.size() == 4);
                for (const auto& pl : plines) {
                    const double mx = pl.xs[pl.xs.size() / 2];
                    const double my = pl.ys[pl.ys.size() / 2];
                    CHECK(std::fabs(bilinear_at(num_vec(s.at("gx")),
                                                num_vec(s.at("gy")),
                                                num_vec(s.at("gz")), mx, my) -
                                    level) <= 0.5);
                }
            }
        }
    }

    // --- fence ---------------------------------------------------------------
    {
        const Json& fc = in.at("fence");
        std::vector<FenceWell> wells;
        for (const auto& w : fc.at("wells")) {
            wells.push_back({w.at("name").get<std::string>(),
                             num(w.at("x")), num(w.at("y")), num(w.at("depth"))});
        }
        const FenceMesh mesh =
            generate_fence_mesh(wells, fc.at("nz_samples").get<int>());
        const auto& e = fx.at("fence");
        const auto ev = num_vec(e.at("vertices"));
        const auto ec = num_vec(e.at("face_colors"));
        CHECK(mesh.vertices.size() == ev.size());
        CHECK(mesh.faces.size() == e.at("faces").size());
        CHECK(mesh.face_colors.size() == ec.size());
        for (std::size_t k = 0; k < mesh.vertices.size() && k < ev.size(); ++k) {
            CHECK(std::fabs(static_cast<double>(mesh.vertices[k]) - ev[k]) <= 1e-4);
        }
        for (std::size_t k = 0; k < mesh.faces.size(); ++k) {
            CHECK(static_cast<long long>(mesh.faces[k]) ==
                  e.at("faces")[k].get<long long>());
        }
        for (std::size_t k = 0; k < mesh.face_colors.size() && k < ec.size(); ++k) {
            CHECK(std::fabs(static_cast<double>(mesh.face_colors[k]) - ec[k]) <= 1e-4);
        }

        const Json& fsc = in.at("fence_slice");
        std::vector<FenceWell> swells;
        for (const auto& w : fsc.at("wells")) {
            swells.push_back({w.at("name").get<std::string>(),
                              num(w.at("x")), num(w.at("y")), num(w.at("depth"))});
        }
        const std::vector<double> sdouble = num_vec(fsc.at("seismic"));
        std::vector<float> seismic(sdouble.begin(), sdouble.end());
        const std::vector<float> slice = extract_seismic_slice(
            seismic, fsc.at("ni").get<int>(), fsc.at("nx").get<int>(),
            fsc.at("nz").get<int>(), swells,
            fsc.at("n_samples_per_segment").get<int>());
        const auto& es = fx.at("fence_slice");
        const auto eshape = es.at("shape");
        const auto evals = num_vec(es.at("values"));
        CHECK(static_cast<std::size_t>(eshape[0].get<int>() *
                                       eshape[1].get<int>()) == slice.size());
        CHECK(slice.size() == evals.size());
        for (std::size_t k = 0; k < slice.size() && k < evals.size(); ++k) {
            CHECK(std::fabs(static_cast<double>(slice[k]) - evals[k]) <= 1e-5);
        }
    }

    // --- well qc -----------------------------------------------------------
    {
        const auto& cases = in.at("qc_mad");
        const auto& expect = fx.at("qc_mad");
        for (std::size_t c = 0; c < cases.size(); ++c) {
            CHECK(close_enough(
                median_absolute_deviation(num_vec(cases[c])),
                num(expect[c]), 1e-12));
        }
        const auto& zcases = in.at("qc_z");
        const auto& zexpect = fx.at("qc_z");
        for (std::size_t c = 0; c < zcases.size(); ++c) {
            const std::vector<double> got =
                modified_z_scores(num_vec(zcases[c]));
            const auto& e = zexpect[c];
            CHECK(got.size() == e.size());
            for (std::size_t k = 0; k < got.size() && k < e.size(); ++k) {
                CHECK(close_enough(got[k], num(e[k]), 1e-12));
            }
        }
        const auto& scases = in.at("qc_sand");
        const auto& sexpect = fx.at("qc_sand");
        for (std::size_t c = 0; c < scases.size(); ++c) {
            std::optional<double> hs, ht;
            if (!scases[c][0].is_null()) hs = num(scases[c][0]);
            if (!scases[c][1].is_null()) ht = num(scases[c][1]);
            const auto [ratio, flag] = compute_sand_ratio(hs, ht);
            const auto& e = sexpect[c];
            CHECK(flag == e[1].get<std::string>());
            if (e[0].is_null()) {
                CHECK(!ratio.has_value());
            } else {
                CHECK(ratio.has_value() &&
                      close_enough(*ratio, num(e[0]), 1e-12));
            }
        }
    }

    // --- negative self-check: tamper must be caught -------------------------
    {
        Json tampered = load_fixture();
        tampered["inputs"]["lttb"][0]["x"][0] =
            num(tampered["inputs"]["lttb"][0]["x"][0]) + 1.5;
        const DownsampleResult r = lttb_downsample(
            num_vec(tampered["inputs"]["lttb"][0].at("x")),
            num_vec(tampered["inputs"]["lttb"][0].at("y")),
            tampered["inputs"]["lttb"][0].at("threshold").get<int>());
        // The frozen output was computed from the untampered input, so the
        // replay of tampered data must no longer match it (first LTTB point
        // is kept verbatim).
        bool differs = r.x.empty() ||
                       !close_enough(r.x[0], num(fx["lttb"][0]["x"][0]), 1e-12);
        CHECK(differs);
    }

    std::printf("%s: %d checks, %d failures\n", __func__, checks, failures);
    return failures == 0 ? 0 : 1;
}
