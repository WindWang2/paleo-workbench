#include <pwb/mapping/layer_products.hpp>

#include <pwb/mapping/crs_policy.hpp>

#include <algorithm>
#include <cctype>
#include <cfloat>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <string>

namespace pwb::mapping {
namespace {

// Python math.isclose(a, b, rel_tol=1e-9, abs_tol=abs_tol).
bool is_close_abs(double a, double b, double abs_tol) {
    return std::fabs(a - b)
        <= std::max(1e-9 * std::max(std::fabs(a), std::fabs(b)), abs_tol);
}

// Python `%` for a positive modulus: the result lands in [0, y) even for
// negative x (C fmod keeps the dividend's sign instead).
double python_mod(double x, double y) {
    double r = std::fmod(x, y);
    if (r != 0.0 && ((r < 0.0) != (y < 0.0))) {
        r += y;
    }
    return r;
}

// Python f"{value:g}" (C99 %g: 6 significant digits, trailing zeros cut).
std::string format_g(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%g", value);
    return buf;
}

// Python str.strip() — whitespace at both ends.
std::string strip(const std::string& s) {
    const auto is_space = [](char c) {
        return std::isspace(static_cast<unsigned char>(c)) != 0;
    };
    std::size_t a = 0;
    while (a < s.size() && is_space(s[a])) ++a;
    std::size_t b = s.size();
    while (b > a && is_space(s[b - 1])) --b;
    return s.substr(a, b - a);
}

Grid grid_from_factor(const FactorGrid& g) {
    Grid out;
    out.grid_x = g.grid_x;
    out.grid_y = g.grid_y;
    out.w = g.grid_x.size();
    out.h = g.grid_y.size();
    out.grid_z.assign(out.w * out.h,
                      std::numeric_limits<double>::quiet_NaN());
    const std::size_t n = std::min(out.grid_z.size(), g.grid_z.size());
    for (std::size_t i = 0; i < n; ++i) {
        out.grid_z[i] = static_cast<double>(g.grid_z[i]);
    }
    return out;
}

std::array<double, 4> axis_extent(const Grid& grid) {
    // FactorGridResult.extent: (min(x), min(y), max(x), max(y)).
    if (grid.grid_x.empty() || grid.grid_y.empty()) {
        return {0.0, 0.0, 0.0, 0.0};
    }
    const auto xh = std::minmax_element(grid.grid_x.begin(),
                                        grid.grid_x.end());
    const auto yh = std::minmax_element(grid.grid_y.begin(),
                                        grid.grid_y.end());
    return {*xh.first, *yh.first, *xh.second, *yh.second};
}

// numpy pairwise summation over a contiguous float32 buffer (the accumulator
// behind np.mean on float32 input): sequential below 8, an 8-accumulator
// unrolled block up to 128, then recursive halving aligned to 8. The mean
// divides this sum by the count in float32 arithmetic before promotion.
float pairwise_sum_f32(const float* a, std::size_t n) {
    if (n < 8) {
        float res = 0.0f;
        for (std::size_t i = 0; i < n; ++i) res += a[i];
        return res;
    }
    if (n <= 128) {
        float r0 = a[0], r1 = a[1], r2 = a[2], r3 = a[3];
        float r4 = a[4], r5 = a[5], r6 = a[6], r7 = a[7];
        std::size_t i = 8;
        for (; i < n - (n % 8); i += 8) {
            r0 += a[i + 0];
            r1 += a[i + 1];
            r2 += a[i + 2];
            r3 += a[i + 3];
            r4 += a[i + 4];
            r5 += a[i + 5];
            r6 += a[i + 6];
            r7 += a[i + 7];
        }
        float res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum_f32(a, n2) + pairwise_sum_f32(a + n2, n - n2);
}

// float(np.mean(grid_z[c_mask])) — the masked selection iterates row-major
// (C order) and sums in float32 pairwise, divides in float32.
double mask_mean_f32(const FactorGrid& grid,
                     const std::vector<std::int16_t>& class_grid,
                     std::size_t total, std::int16_t target_class) {
    std::vector<float> picked;
    picked.reserve(total);
    for (std::size_t at = 0; at < total && at < grid.grid_z.size(); ++at) {
        if (class_grid[at] == target_class && std::isfinite(grid.grid_z[at])) {
            picked.push_back(grid.grid_z[at]);
        }
    }
    return float32_mask_mean(picked);
}

// geometry_units.ring_area_with_unit warning kind (the label is unused by
// the packing; only the warning strings reach polygon_qc).
enum class RingWarning { None, Geographic, Undeclared };

double ring_area(const Ring& ring, const std::string& crs,
                 RingWarning& warning) {
    double area = shoelace_area(ring);
    if (layer_crs_is_geographic(crs)) {
        double lat_sum = 0.0;
        for (const Point& pt : ring) lat_sum += pt[1];
        const double mean_lat =
            (ring.empty() ? 0.0 : lat_sum / static_cast<double>(ring.size()))
            * (std::numbers::pi / 180.0);
        constexpr double kMetresPerDegreeLat = 111320.0;
        area *= (kMetresPerDegreeLat * std::cos(mean_lat))
                * kMetresPerDegreeLat;
        warning = RingWarning::Geographic;
    } else if (strip(crs).empty()) {
        warning = RingWarning::Undeclared;
    } else {
        warning = RingWarning::None;
    }
    return area;
}

std::string ring_warning_message(RingWarning kind, const std::string& crs) {
    if (kind == RingWarning::Geographic) {
        // Python f-string with {crs!r}; the quoted CRS is a simple token in
        // every supported path (repr's escape rules never trigger).
        return "CRS '" + crs
            + "' is geographic: area is a local-scale approximation from "
              "the ring's mean latitude; reproject to a projected CRS for "
              "exact areas";
    }
    return "CRS undeclared: area unit is unknown (not metres)";
}

void append_ring_warning(Json& polygon_qc, const std::string& warning) {
    if (!polygon_qc.contains("area_warnings")) {
        polygon_qc["area_warnings"] = Json::array();
    }
    for (const Json& existing : polygon_qc["area_warnings"]) {
        if (existing.get<std::string>() == warning) return;
    }
    polygon_qc["area_warnings"].push_back(warning);
}

Json ring_json(const Ring& ring) {
    Json out = Json::array();
    for (const Point& pt : ring) {
        out.push_back(Json::array({pt[0], pt[1]}));
    }
    return out;
}

Json polygon_geometry_json(const Polygon& poly) {
    Json coords = Json::array();
    coords.push_back(ring_json(poly.exterior));
    for (const Ring& hole : poly.holes) {
        coords.push_back(ring_json(hole));
    }
    Json geom = Json::object();
    geom["type"] = "Polygon";
    geom["coordinates"] = std::move(coords);
    return geom;
}

// polygonization._compute_geometry_area for the identity-repair (always
// Polygon) geometries this kernel emits.
double polygon_net_area(const Polygon& poly) {
    double area = shoelace_area(poly.exterior);
    for (const Ring& hole : poly.holes) area -= shoelace_area(hole);
    return std::max(0.0, area);
}

}  // namespace

namespace {

struct DoubleLength {
    double hi;
    double lo;
};

// Algorithm 1.1: compensated summation of two doubles (precondition:
// |a| >= |b|, which vector_norm's csum >= 1.0 invariant provides).
DoubleLength dl_fast_sum(double a, double b) {
    const double x = a + b;
    const double y = (a - x) + b;
    return {x, y};
}

// Algorithm 3.5: error-free product transformation via fma.
DoubleLength dl_mul(double x, double y) {
    const double z = x * y;
    const double zz = std::fma(x, y, -z);
    return {z, zz};
}

double python_hypot(double a, double b) {
    const double fabs_a = std::fabs(a);
    const double fabs_b = std::fabs(b);
    // CPython tracks max with `if (x > max)`, so NaN never becomes max and
    // an infinity wins over a NaN — std::max(NaN, y) would return NaN.
    double max = 0.0;
    for (const double v : {fabs_a, fabs_b}) {
        if (v > max) max = v;
    }
    const bool found_nan = std::isnan(fabs_a) || std::isnan(fabs_b);
    if (std::isinf(max)) return max;
    if (found_nan) return std::numeric_limits<double>::quiet_NaN();
    if (max == 0.0) return max;

    int max_e = 0;
    std::frexp(max, &max_e);
    if (max_e < -1023) {
        // ldexp(1.0, -max_e) would overflow: lift subnormals to normals and
        // rescale the result (CPython recurses with the normalized vec).
        const double lifted_a = fabs_a / DBL_MIN;
        const double lifted_b = fabs_b / DBL_MIN;
        return DBL_MIN * python_hypot(lifted_a, lifted_b);
    }
    const double scale = std::ldexp(1.0, -max_e);

    double csum = 1.0;
    double frac1 = 0.0;
    double frac2 = 0.0;
    for (const double v : {fabs_a, fabs_b}) {
        const double x = v * scale;  // lossless power-of-two scaling
        const DoubleLength pr = dl_mul(x, x);       // lossless squaring
        const DoubleLength sm = dl_fast_sum(csum, pr.hi);
        csum = sm.hi;
        frac1 += pr.lo;
        frac2 += sm.lo;
    }
    double h = std::sqrt(csum - 1.0 + (frac1 + frac2));
    const DoubleLength pr2 = dl_mul(-h, h);
    const DoubleLength sm2 = dl_fast_sum(csum, pr2.hi);
    csum = sm2.hi;
    frac1 += pr2.lo;
    frac2 += sm2.lo;
    const double correction = csum - 1.0 + (frac1 + frac2);
    h += correction / (2.0 * h);
    return h / scale;
}

// Python calculate_polyline_length: math.hypot per segment.
double python_polyline_length(const Polyline& points) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
        total += python_hypot(points[i + 1][0] - points[i][0],
                              points[i + 1][1] - points[i][1]);
    }
    return total;
}

}  // namespace

double float32_mask_mean(const std::vector<float>& values) {
    if (values.empty()) return 0.0;
    const float sum = pairwise_sum_f32(values.data(), values.size());
    return static_cast<double>(sum / static_cast<float>(values.size()));
}

bool layer_crs_is_geographic(const std::string& crs) {
    // geometry_units.is_geographic_crs strips first, then asks the D5
    // authority; unknown ids (nullopt, no pyproj) and empties are not
    // geographic.
    const std::string trimmed = strip(crs);
    if (trimmed.empty()) return false;
    return crs_is_geographic(trimmed).value_or(false);
}

std::string area_unit_label(const std::string& crs) {
    if (layer_crs_is_geographic(crs)) return "deg²";
    const std::string trimmed = strip(crs);
    if (!trimmed.empty()) return trimmed + "-unit²";
    return "unknown-unit²";
}

ContourLayerProduct generate_contour_layer_product(
    const FactorGrid& grid, const LayerGridContext& ctx,
    const ContourLayerOptions& options) {
    ContourLayerProduct out;
    out.contour_qc = Json::object();
    out.contour_qc["clipped_to_domain"] = 0;
    out.contour_qc["empty_after_clip"] = 0;

    const Grid g = grid_from_factor(grid);

    std::size_t finite_count = 0;
    for (const double z : g.grid_z) {
        if (std::isfinite(z)) ++finite_count;
    }
    if (finite_count < 2) {
        // Python early return: levels stay empty and contour_interval is NOT
        // carried into the empty layer even when an interval was requested.
        return out;
    }

    double vmin = std::numeric_limits<double>::infinity();
    double vmax = -std::numeric_limits<double>::infinity();
    for (const double z : g.grid_z) {
        if (!std::isfinite(z)) continue;
        vmin = std::min(vmin, z);
        vmax = std::max(vmax, z);
    }

    const bool use_interval =
        options.interval.has_value() && *options.interval > 0.0;
    if (options.levels.has_value()) {
        out.levels = *options.levels;
    } else if (use_interval) {
        const double interval = *options.interval;
        // Python math.ceil returns an int, so 0 * interval is +0.0; C++
        // std::ceil keeps -0.0 for ratios in (-1, 0). Normalize so labels
        // print "0", not "-0".
        double curr = std::ceil(vmin / interval) * interval;
        if (curr == 0.0) curr = 0.0;
        while (curr <= vmax) {
            out.levels.push_back(round_to(curr, 6));
            curr += interval;
        }
    } else if (options.leveling_mode == "quantile") {
        out.levels = quantile_contour_levels(g);
    } else {
        out.levels = nice_contour_levels(vmin, vmax, 7);
    }
    out.contour_interval = options.interval;

    std::size_t level_index = 0;
    for (const double flevel : out.levels) {
        const auto polylines = marching_squares_contours(
            g, flevel, options.simplify_tolerance, options.smooth_iterations);

        bool is_index = false;
        if (use_interval) {
            const double mod = python_mod(flevel, 5.0 * *options.interval);
            is_index = is_close_abs(mod, 0.0, 1e-5)
                       || is_close_abs(mod, 5.0 * *options.interval, 1e-5);
        } else {
            is_index = level_index % 5 == 0;
        }
        ++level_index;

        std::string label = format_g(flevel);
        if (!ctx.unit.empty()) label = strip(label + " " + ctx.unit);

        for (const Polyline& poly : polylines) {
            if (poly.size() < 2) continue;  // no clip path in this slice
            const double length = python_polyline_length(poly);
            const bool is_closed =
                is_close_abs(poly.front()[0], poly.back()[0], 1e-5)
                && is_close_abs(poly.front()[1], poly.back()[1], 1e-5);

            Json properties = Json::object();
            properties["level"] = flevel;
            properties["label_text"] = label;
            properties["is_index_contour"] = is_index;
            properties["length"] = length;
            properties["is_closed"] = is_closed;
            properties["factor"] = ctx.factor_name;
            properties["unit"] = ctx.unit;

            Json geometry = Json::object();
            geometry["type"] = "LineString";
            geometry["coordinates"] = ring_json(poly);

            Json feature = Json::object();
            feature["type"] = "Feature";
            feature["geometry"] = std::move(geometry);
            feature["properties"] = std::move(properties);
            out.features.push_back(std::move(feature));
        }
    }
    return out;
}

FaciesLayerProduct generate_facies_polygon_layer_product(
    const FactorGrid& grid, const LayerGridContext& ctx,
    const FaciesLayerOptions& options) {
    if (options.colors.has_value() && options.colors->empty()) {
        // Python would crash with ZeroDivisionError on colors[c % 0]; fail
        // closed instead of invoking UB.
        throw std::invalid_argument(
            "colors must not be empty when provided");
    }

    FaciesLayerProduct out;
    Json& qc = out.polygon_qc;
    qc = Json::object();

    const Grid g = grid_from_factor(grid);
    const std::size_t h = g.h;
    const std::size_t w = g.w;

    std::size_t finite_count = 0;
    for (const double z : g.grid_z) {
        if (std::isfinite(z)) ++finite_count;
    }
    if (finite_count == 0 || h < 1 || w < 1) {
        // Python early return: exactly five QC keys, no thresholds block;
        // small_polygon_threshold echoes the caller's min_area verbatim.
        qc["small_polygon_threshold"] =
            options.min_area.has_value() ? Json(*options.min_area) : Json();
        qc["small_polygons_dropped"] = 0;
        qc["clipped_to_domain"] = 0;
        qc["empty_after_clip"] = 0;
        qc["holes_promoted_to_exterior"] = 0;
        return out;
    }

    double vmin = std::numeric_limits<double>::infinity();
    double vmax = -std::numeric_limits<double>::infinity();
    for (const double z : g.grid_z) {
        if (!std::isfinite(z)) continue;
        vmin = std::min(vmin, z);
        vmax = std::max(vmax, z);
    }

    std::vector<double> thresholds;
    if (options.thresholds.has_value()) {
        thresholds = unique_sorted_thresholds(*options.thresholds);
    } else {
        thresholds = default_class_thresholds(vmin, vmax);
    }

    std::vector<std::string> names;
    if (options.facies_names.has_value()) {
        names = *options.facies_names;
    } else if (thresholds.size() == 2) {
        names = {"低值相带", "中值相带", "高值相带"};
    } else if (thresholds.size() == 1 && is_close(vmin, vmax)) {
        names = {"均一相带"};
    } else {
        for (std::size_t i = 0; i < thresholds.size() + 1; ++i) {
            names.push_back("相带 " + std::to_string(i + 1));
        }
    }

    std::vector<std::string> colors;
    if (options.colors.has_value()) {
        colors = *options.colors;
    } else {
        static const char* kPalette[] = {"#b0bec5", "#ffe082", "#d73027",
                                         "#81c784", "#4fc3f7", "#ba68c8"};
        for (std::size_t i = 0; i < names.size(); ++i) {
            colors.emplace_back(kPalette[i % 6]);
        }
    }

    const std::vector<std::int16_t> class_grid =
        classify_grid(g, thresholds, static_cast<int>(names.size()));

    qc["small_polygon_threshold"] =
        options.min_area.has_value() ? Json(*options.min_area) : Json();
    qc["small_polygons_dropped"] = 0;
    qc["clipped_to_domain"] = 0;
    qc["empty_after_clip"] = 0;
    qc["thresholds"] = thresholds;
    qc["thresholds_source"] = options.thresholds.has_value()
                                  ? "explicit"
                                  : "data_derived_default";
    std::size_t nodata = 0;
    for (const double z : g.grid_z) {
        if (!std::isfinite(z)) ++nodata;
    }
    qc["nodata_cells"] = static_cast<int>(nodata);
    qc["total_cells"] = static_cast<int>(g.grid_z.size());
    qc["area_unit"] = area_unit_label(ctx.crs);

    const bool geographic = layer_crs_is_geographic(ctx.crs);
    if (geographic) {
        qc["area_warnings"] = Json::array(
            {Json("geographic CRS: per-feature areas are local-scale "
                  "approximations")});
    } else if (strip(ctx.crs).empty()) {
        qc["area_warnings"] = Json::array(
            {Json("CRS undeclared: area unit unknown (not metres)")});
    }

    const auto [xmin, ymin, xmax, ymax] = axis_extent(g);
    const double total_grid_area =
        std::max(1e-12, (xmax - xmin) * (ymax - ymin));
    const std::string unit_label = area_unit_label(ctx.crs);
    const std::size_t total = w * h;

    for (std::size_t c_idx = 0; c_idx < names.size(); ++c_idx) {
        bool any = false;
        for (std::size_t at = 0; at < total && at < g.grid_z.size(); ++at) {
            if (class_grid[at] == static_cast<std::int16_t>(c_idx)
                && std::isfinite(g.grid_z[at])) {
                any = true;
                break;
            }
        }
        if (!any) continue;

        const double mean_val =
            mask_mean_f32(grid, class_grid, total,
                          static_cast<std::int16_t>(c_idx));

        auto traced = polygonize_class(g, class_grid,
                                       static_cast<int>(c_idx));
        qc["holes_promoted_to_exterior"] =
            qc.value("holes_promoted_to_exterior", 0)
            + traced.second.holes_promoted_to_exterior;

        if (options.min_area.has_value() && *options.min_area > 0.0) {
            const std::size_t before = traced.first.size();
            traced.first =
                filter_small_polygons(traced.first, *options.min_area);
            qc["small_polygons_dropped"] =
                qc.value("small_polygons_dropped", 0)
                + static_cast<int>(before - traced.first.size());
        }

        const std::string& facies_name = names[c_idx];
        const std::string& color = colors[c_idx % colors.size()];

        for (const Polygon& geom : traced.first) {
            const double raw_area = polygon_net_area(geom);

            double geom_area = 0.0;
            RingWarning warning = RingWarning::None;
            geom_area += ring_area(geom.exterior, ctx.crs, warning);
            if (warning != RingWarning::None) {
                append_ring_warning(qc, ring_warning_message(warning, ctx.crs));
            }
            for (const Ring& hole : geom.holes) {
                RingWarning hole_warning = RingWarning::None;
                geom_area -= ring_area(hole, ctx.crs, hole_warning);
            }
            geom_area = std::max(geom_area, 0.0);

            const double area_pct = raw_area / total_grid_area * 100.0;

            Json properties = Json::object();
            properties["facies_id"] = static_cast<int>(c_idx + 1);
            properties["facies_name"] = facies_name;
            properties["facies"] = facies_name;
            properties["color"] = color;
            properties["area"] = round_to(raw_area, 4);
            properties["area_unit"] = unit_label;
            properties["area_percent"] = round_to(area_pct, 4);
            properties["mean_value"] = round_to(mean_val, 4);
            if (geographic) {
                properties["area_approx_m2"] = round_to(geom_area, 4);
            }

            Json feature = Json::object();
            feature["type"] = "Feature";
            feature["geometry"] = polygon_geometry_json(geom);
            feature["properties"] = std::move(properties);
            out.features.push_back(std::move(feature));
        }
    }
    return out;
}

}  // namespace pwb::mapping
