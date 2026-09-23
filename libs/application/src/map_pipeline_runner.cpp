#include <pwb/application/map_pipeline_runner.hpp>

// CONV-QGIS-PROCESSING phase 4 note: this runner is the product-internal
// composition of the paleo Processing sequence paleo:extract_factors ->
// paleo:interpolation_idw/_kriging -> paleo:grid_contours (+
// classification/polygonization) — the SAME pwb::mapping kernels those
// algorithms wrap (mapping.cpp/interpolation.cpp in libs/qgis_processing).
// It stays a direct composition because its inputs are in-memory JSON
// records and its outputs GeoJSON features (no feature-source/raster
// staging); the self-check (checkMappingKernel) verifies the equivalent
// paleo ids are registered so the chain is never private to this file.

#include <pwb/domain/text.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <vector>

#include <pwb/mapping/class_grid.hpp>
#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/crs_policy.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/polygonization.hpp>

namespace pwb::application {
namespace {

using pwb::mapping::Grid;
using pwb::mapping::Point;
using pwb::mapping::Polygon;
using pwb::mapping::Polyline;
using pwb::mapping::SamplePoint;

// Python f"{value:g}" (6 significant digits, trailing zeros trimmed).
std::string python_g(double value) {
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%g", value);
    return buffer;
}

std::string strip(const std::string& s) {
    return domain::strip_ascii(s);  // shared impl (#1392)
}

// geometry_units.is_geographic_crs — delegated to the D5 authority; the C++
// kernel never throws for a plain token, so Python's except->False path is
// unreachable here.
bool crs_is_geographic_or_false(const std::string& crs) {
    if (crs.empty()) return false;
    const auto known = pwb::mapping::crs_is_geographic(crs);
    return known.has_value() && *known;
}

// geometry_units.area_unit_label.
std::string area_unit_label(const std::string& crs_raw) {
    const std::string crs = strip(crs_raw);
    if (crs_is_geographic_or_false(crs)) return "deg²";
    if (!crs.empty()) return crs + "-unit²";
    return "unknown-unit²";
}

// geometry_units.ring_area_with_unit for a geographic CRS: local-scale ≈m²
// scaled from the ring's mean latitude (111320 m per degree).
constexpr double kMetresPerDegreeLat = 111320.0;

double ring_approx_m2(const pwb::mapping::Ring& ring) {
    const double raw = pwb::mapping::shoelace_area(ring);
    if (ring.empty()) return 0.0;
    double lat_sum = 0.0;
    for (const Point& p : ring) lat_sum += p[1];
    const double mean_lat =
        lat_sum * (3.14159265358979323846 / 180.0)
        / static_cast<double>(ring.size());
    const double scale_x = kMetresPerDegreeLat * std::cos(mean_lat);
    return raw * scale_x * kMetresPerDegreeLat;
}

Json ring_to_json(const pwb::mapping::Ring& ring) {
    Json coords = Json::array();
    for (const Point& p : ring) {
        coords.push_back(Json::array({p[0], p[1]}));
    }
    return coords;
}

Json polyline_to_json(const Polyline& line) {
    Json coords = Json::array();
    for (const Point& p : line) {
        coords.push_back(Json::array({p[0], p[1]}));
    }
    return coords;
}

Grid grid_from_factor(const pwb::mapping::FactorGrid& factor) {
    Grid grid;
    grid.grid_x = factor.grid_x;
    grid.grid_y = factor.grid_y;
    grid.w = factor.grid_x.size();
    grid.h = factor.grid_y.size();
    // The kernel guarantees grid_z is laid out w*h row-major (frozen
    // contract), so the conversion is a straight widening copy.
    grid.grid_z.resize(grid.w * grid.h);
    for (std::size_t i = 0; i < grid.grid_z.size(); ++i) {
        grid.grid_z[i] = static_cast<double>(factor.grid_z[i]);
    }
    return grid;
}

struct ValueRange {
    std::size_t finite = 0;
    double vmin = 0.0;
    double vmax = 0.0;
};

ValueRange finite_range(const Grid& grid) {
    ValueRange range;
    bool first = true;
    for (const double z : grid.grid_z) {
        if (!std::isfinite(z)) continue;
        ++range.finite;
        if (first) {
            range.vmin = z;
            range.vmax = z;
            first = false;
        } else {
            range.vmin = std::min(range.vmin, z);
            range.vmax = std::max(range.vmax, z);
        }
    }
    return range;
}

Json contour_features_for(const Grid& grid, const std::string& factor_name,
                          const std::string& unit,
                          const std::vector<double>& levels) {
    // Python generate_contour_layer: finite.size < 2 -> empty layer.
    const ValueRange range = finite_range(grid);
    if (range.finite < 2) return Json::array();

    const std::string unit_str = unit;
    Json features = Json::array();
    for (std::size_t idx = 0; idx < levels.size(); ++idx) {
        const double level = levels[idx];
        // No interval path in the runner (Python: interval==None ->
        // is_index counts every 5th level in list order).
        const bool is_index = (idx % 5 == 0);
        std::string label_text = python_g(level);
        if (!unit_str.empty()) label_text += " " + unit_str;

        const std::vector<Polyline> polylines =
            pwb::mapping::marching_squares_contours(grid, level);
        for (const Polyline& poly : polylines) {
            if (poly.size() < 2) continue;
            const double length = pwb::mapping::polyline_length(poly);
            // math.isclose(first, last, abs_tol=1e-5): the rel_tol term
            // dominates on large-magnitude axes (UTM ≈ 5e-4).
            const auto isclose_abs = [](double a, double b, double abs_tol) {
                return std::fabs(a - b)
                    <= std::max(1e-9 * std::max(std::fabs(a), std::fabs(b)),
                                abs_tol);
            };
            const bool is_closed =
                isclose_abs(poly.front()[0], poly.back()[0], 1e-5)
                && isclose_abs(poly.front()[1], poly.back()[1], 1e-5);
            features.push_back(Json{
                {"type", "Feature"},
                {"geometry",
                 Json{{"type", "LineString"}, {"coordinates",
                                               polyline_to_json(poly)}}},
                {"properties",
                 Json{{"level", level},
                      {"label_text", label_text},
                      {"is_index_contour", is_index},
                      {"length", length},
                      {"is_closed", is_closed},
                      {"factor", factor_name},
                      {"unit", unit_str}}},
            });
        }
    }
    return features;
}

// Python generate_facies_polygon_layer default names.
std::vector<std::string> default_facies_names(
    const std::vector<double>& thresholds, const ValueRange& range) {
    if (thresholds.size() == 2) {
        return {"低值相带", "中值相带", "高值相带"};
    }
    if (thresholds.size() == 1
        && pwb::mapping::is_close(range.vmin, range.vmax)) {
        return {"均一相带"};
    }
    std::vector<std::string> names;
    names.reserve(thresholds.size() + 1);
    for (std::size_t i = 0; i <= thresholds.size(); ++i) {
        names.push_back("相带 " + std::to_string(i + 1));
    }
    return names;
}

Json polygon_features_for(const Grid& grid, const std::string& factor_name,
                          const std::string& crs,
                          const std::vector<double>& thresholds_in,
                          const std::vector<std::string>& facies_names_in) {
    const ValueRange range = finite_range(grid);
    // Python: finite.size == 0 -> empty layer.
    if (range.finite == 0 || grid.h < 1 || grid.w < 1) {
        return Json::array();
    }

    // thresholds_is_explicit tracks the QC wording; explicit lists go
    // through sorted(set(...)), defaults are the span 1/3-2/3 ladder.
    const bool thresholds_is_explicit = !thresholds_in.empty();
    std::vector<double> thresholds =
        thresholds_is_explicit
            ? pwb::mapping::unique_sorted_thresholds(thresholds_in)
            : pwb::mapping::default_class_thresholds(range.vmin, range.vmax);

    std::vector<std::string> facies_names =
        facies_names_in.empty()
            ? default_facies_names(thresholds, range)
            : facies_names_in;

    static const char* kDefaultPalette[] = {
        "#b0bec5", "#ffe082", "#d73027", "#81c784", "#4fc3f7", "#ba68c8",
    };
    const int n_classes = static_cast<int>(facies_names.size());
    const std::vector<std::int16_t> class_grid =
        pwb::mapping::classify_grid(grid, thresholds, n_classes);

    const auto xh = std::minmax_element(grid.grid_x.begin(), grid.grid_x.end());
    const auto yh = std::minmax_element(grid.grid_y.begin(), grid.grid_y.end());
    const double xmin = *xh.first;
    const double ymin = *yh.first;
    const double xmax = *xh.second;
    const double ymax = *yh.second;
    const double total_grid_area =
        std::max(1e-12, (xmax - xmin) * (ymax - ymin));
    const std::string unit_label = area_unit_label(crs);
    const bool geographic = crs_is_geographic_or_false(strip(crs));

    Json features = Json::array();
    for (int c_idx = 0; c_idx < n_classes; ++c_idx) {
        // Python skips classes without any finite cell (np.any(mask)).
        bool any = false;
        double sum = 0.0;
        int cells = 0;
        for (std::size_t at = 0; at < grid.grid_z.size(); ++at) {
            if (class_grid[at] == static_cast<std::int16_t>(c_idx)
                && std::isfinite(grid.grid_z[at])) {
                any = true;
                sum += grid.grid_z[at];
                ++cells;
            }
        }
        if (!any) continue;
        const double mean_val = sum / static_cast<double>(cells);
        const std::string facies_name = facies_names[static_cast<std::size_t>(c_idx)];
        const std::string color =
            kDefaultPalette[static_cast<std::size_t>(c_idx)
                            % (sizeof(kDefaultPalette)
                               / sizeof(kDefaultPalette[0]))];

        auto traced = pwb::mapping::polygonize_class(
            grid, class_grid, c_idx);
        for (const Polygon& polygon : traced.first) {
            double raw_area =
                pwb::mapping::shoelace_area(polygon.exterior);
            double approx_m2 = 0.0;
            if (geographic) approx_m2 += ring_approx_m2(polygon.exterior);
            for (const auto& hole : polygon.holes) {
                raw_area -= pwb::mapping::shoelace_area(hole);
                if (geographic) approx_m2 -= ring_approx_m2(hole);
            }
            raw_area = std::max(raw_area, 0.0);
            if (geographic) approx_m2 = std::max(approx_m2, 0.0);

            Json rings = Json::array();
            rings.push_back(ring_to_json(polygon.exterior));
            for (const auto& hole : polygon.holes) {
                rings.push_back(ring_to_json(hole));
            }
            Json properties = Json{
                {"facies_id", c_idx + 1},
                {"facies_name", facies_name},
                {"facies", facies_name},
                {"color", color},
                {"area", pwb::mapping::round_to(raw_area, 4)},
                {"area_unit", unit_label},
                {"area_percent",
                 pwb::mapping::round_to(raw_area / total_grid_area * 100.0,
                                        4)},
                {"mean_value", pwb::mapping::round_to(mean_val, 4)},
            };
            if (geographic) {
                properties["area_approx_m2"] =
                    pwb::mapping::round_to(approx_m2, 4);
            }
            features.push_back(Json{
                {"type", "Feature"},
                {"geometry",
                 Json{{"type", "Polygon"}, {"coordinates", rings}}},
                {"properties", std::move(properties)},
            });
        }
    }
    return features;
}

}  // namespace

MapPipelineOutcome run_map_pipeline(const Json& records,
                                    const MapPipelineRequest& request) {
    MapPipelineOutcome outcome;

    pwb::mapping::ExtractOptions extract_options;
    extract_options.target_horizon = request.target_horizon;
    extract_options.unit = request.unit;
    extract_options.crs = request.crs;
    const pwb::mapping::FactorDataset dataset =
        pwb::mapping::extract_factors(records, request.factor_name,
                                      extract_options);

    std::vector<SamplePoint> samples;
    samples.reserve(dataset.points.size());
    for (const auto& point : dataset.points) {
        samples.push_back(SamplePoint{point.x, point.y, point.value,
                                      point.qc_flag});
    }

    pwb::mapping::InterpolateOptions options;
    options.method = request.method;
    options.grid_n = request.grid_n;
    options.power = request.power;
    options.search_radius = request.search_radius;
    options.min_neighbors = request.min_neighbors;
    options.crs = request.crs;

    pwb::mapping::FactorGrid factor;
    try {
        factor = pwb::mapping::interpolate_factor(samples, options);
    } catch (const std::invalid_argument& e) {
        // Surface the kernel's validate() message verbatim (Python
        // ValueError parity — the wording is part of the contract).
        outcome.error = e.what();
        return outcome;
    }

    const Grid grid = grid_from_factor(factor);

    std::vector<double> levels = request.contour_levels;
    if (levels.empty()) {
        const ValueRange range = finite_range(grid);
        levels = range.finite >= 2
            ? pwb::mapping::nice_contour_levels(range.vmin, range.vmax, 7)
            : std::vector<double>{};
    }
    outcome.contour_features = contour_features_for(
        grid, request.factor_name, dataset.unit, levels);
    outcome.polygon_features = polygon_features_for(
        grid, request.factor_name, request.crs, request.class_thresholds,
        request.facies_names);

    Json diagnostics = Json::object();
    diagnostics["extract_metadata"] = dataset.metadata;
    diagnostics["factor_name"] = dataset.factor_name;
    diagnostics["unit"] = dataset.unit;
    diagnostics["crs"] = dataset.crs;
    diagnostics["n_extracted_points"] = dataset.points.size();
    diagnostics["method"] = factor.method;
    diagnostics["algorithm_id"] = factor.algorithm_id;
    diagnostics["grid_n"] = factor.grid_n;
    diagnostics["distance_policy"] = factor.distance_policy;
    diagnostics["distance_policy_annotation"] =
        factor.distance_policy_annotation;
    diagnostics["statistics"] = Json{
        {"min", factor.statistics.min},
        {"max", factor.statistics.max},
        {"mean", factor.statistics.mean},
        {"std", factor.statistics.std},
        {"valid_count", factor.statistics.valid_count},
        {"total_count", factor.statistics.total_count},
    };
    // The interpolated grid itself (NaN -> null): QC visibility for the
    // surface everything downstream was derived from, and the pinned stage
    // for oracle reconciliation.
    {
        Json z_rows = Json::array();
        const std::size_t w = grid.w;
        for (std::size_t i = 0; i < grid.h; ++i) {
            Json row = Json::array();
            for (std::size_t j = 0; j < w; ++j) {
                const double z = grid.grid_z[i * w + j];
                row.push_back(std::isfinite(z)
                                  ? Json(z)
                                  : Json());
            }
            z_rows.push_back(std::move(row));
        }
        diagnostics["grid"] = Json{
            {"grid_x", grid.grid_x},
            {"grid_y", grid.grid_y},
            {"grid_z", std::move(z_rows)},
            {"width", grid.w},
            {"height", grid.h},
        };
    }
    diagnostics["contour_levels"] = levels;
    outcome.diagnostics = std::move(diagnostics);
    outcome.ok = true;
    return outcome;
}

}  // namespace pwb::application
