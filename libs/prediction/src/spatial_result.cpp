#include "pwb/prediction/spatial_result.hpp"

#include <algorithm>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/prediction/errors.hpp"
#include "python_compat.hpp"

namespace pwb::prediction {

namespace {

using detail::py_float_raw;
using detail::py_isclose;
using detail::py_or;
using detail::py_repr;
using detail::py_str;
using detail::py_strip;
using detail::py_truthy;

const Json kNull;

const Json& get(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNull;
    const auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

// `v or {}` followed by attribute access: falsy -> {}, dict -> copy,
// truthy non-dict -> AttributeError like the Python `.get` call.
Json dict_or_empty(const Json& v) {
    if (!py_truthy(v)) return Json::object();
    if (!v.is_object()) {
        throw AttributeError("'" + detail::py_type_name(v) +
                             "' object has no attribute 'get'");
    }
    return v;
}

// float(pt[i]) without the isfinite filter — only NaN is rejected by the
// ring check; infinities pass (Python `x != x` quirk).
std::optional<double> float_or_throw(const Json& v) {
    const auto r = py_float_raw(v);
    return r;  // nullopt -> TypeError/ValueError -> caught -> false
}

// Subscript helper for ring/point access: array index or single-codepoint
// string index (strings are subscriptable in Python). nullopt mirrors a
// caught TypeError/IndexError; dict[i] would raise KeyError (outside the
// caught set) but converges here since callers only need "not a ring".
std::optional<Json> subscript(const Json& container, size_t index) {
    if (container.is_array()) {
        if (index < container.size()) return container[index];
        return std::nullopt;
    }
    if (container.is_string()) {
        const auto& s = container.get_ref<const std::string&>();
        size_t i = 0, n = 0;
        while (i < s.size()) {
            auto cp = pwb::ingest::detail::utf8_code_point(s, i);
            const size_t size = cp ? cp->size : 1;
            if (n == index) return Json(s.substr(i, size));
            ++n;
            i += size;
        }
    }
    return std::nullopt;
}

size_t py_len(const Json& v) {
    if (v.is_array() || v.is_object()) return v.size();
    if (v.is_string()) {
        const auto& s = v.get_ref<const std::string&>();
        size_t n = 0;
        for (size_t i = 0; i < s.size();) {
            auto cp = pwb::ingest::detail::utf8_code_point(s, i);
            i += cp ? cp->size : 1;
            ++n;
        }
        return n;
    }
    return 0;  // len() on non-sized values is a caught TypeError
}

// ring = coords[0]; if ring and isinstance(ring[0][0], (list,tuple)):
// ring = ring[0]. Shared by _has_finite_ring / _looks_like_demo_square.
// Returns nullopt on the IndexError/TypeError paths.
std::optional<Json> first_ring(const Json& coords) {
    auto ring = subscript(coords, 0);
    if (!ring) return std::nullopt;
    if (py_truthy(*ring)) {
        const auto r0 = subscript(*ring, 0);
        if (!r0) return std::nullopt;
        const auto r00 = subscript(*r0, 0);
        if (!r00) return std::nullopt;
        if (r00->is_array()) ring = r0;
    }
    return ring;
}

// _has_finite_ring(coords): Polygon [ring,...] / MultiPolygon [[ring,...]].
bool has_finite_ring(const Json& coords) {
    if (!py_truthy(coords)) return false;
    const auto ring = first_ring(coords);
    if (!ring) return false;
    // len(ring) < 4; len() on non-sized values is a caught TypeError.
    if (!ring->is_array() && !ring->is_string() && !ring->is_object()) {
        return false;
    }
    if (py_len(*ring) < 4) return false;
    for (size_t i = 0; i < py_len(*ring); ++i) {
        const auto pt = subscript(*ring, i);
        if (!pt) return false;
        const auto px = subscript(*pt, 0);
        const auto py = subscript(*pt, 1);
        if (!px || !py) return false;
        const auto x = float_or_throw(*px);
        const auto y = float_or_throw(*py);
        if (!x || !y) return false;
        if (*x != *x || *y != *y) return false;  // NaN only (Python x != x)
    }
    return true;
}

// _looks_like_demo_square(coords): fixed demo square at (114.0, 22.5)
// with 0.04 spans. No pre-check — IndexError/TypeError -> false.
bool looks_like_demo_square(const Json& coords) {
    const auto ring = first_ring(coords);
    if (!ring || !ring->is_array() || ring->empty()) return false;
    std::vector<double> xs, ys;
    xs.reserve(ring->size());
    ys.reserve(ring->size());
    for (const auto& p : *ring) {
        const auto px = subscript(p, 0);
        const auto py = subscript(p, 1);
        if (!px || !py) return false;
        const auto x = py_float_raw(*px);
        const auto y = py_float_raw(*py);
        if (!x || !y) return false;
        xs.push_back(*x);
        ys.push_back(*y);
    }
    const auto [xmin, xmax] = std::minmax_element(xs.begin(), xs.end());
    const auto [ymin, ymax] = std::minmax_element(ys.begin(), ys.end());
    return py_isclose(*xmin, 114.0, 1e-6) && py_isclose(*ymin, 22.5, 1e-6) &&
           py_isclose(*xmax - *xmin, 0.04, 1e-6) &&
           py_isclose(*ymax - *ymin, 0.04, 1e-6);
}

}  // namespace

std::string spatial_type_of(const Json& payload) {
    const Json obj = dict_or_empty(payload);
    const Json summary = dict_or_empty(get(obj, "result_summary"));
    const Json sources[4] = {obj, summary,
                             dict_or_empty(get(obj, "output_schema")),
                             dict_or_empty(get(summary, "spatial"))};
    for (const Json& src : sources) {
        const std::string t =
            py_strip(py_str(py_or(get(src, "spatial_output_type"), Json(""))));
        if (!t.empty()) return t;
    }
    const Json spatial =
        py_or(get(summary, "spatial"), py_or(get(obj, "spatial"), Json()));
    if (spatial.is_object()) {
        const std::string t = py_strip(py_str(py_or(
            py_or(get(spatial, "type"), get(spatial, "spatial_output_type")),
            Json(""))));
        if (!t.empty()) return t;
        if (py_truthy(get(spatial, "features")) ||
            py_truthy(get(spatial, "polygons"))) {
            return std::string(kSpatialVectorPolygons);
        }
        if (py_truthy(get(spatial, "intervals")) ||
            py_truthy(get(spatial, "well_intervals"))) {
            return std::string(kSpatialWellIntervals);
        }
        if (!get(spatial, "grid").is_null() ||
            !get(spatial, "classes").is_null()) {
            return std::string(kSpatialClassifiedRaster);
        }
    }
    return std::string(kSpatialNone);
}

Json extract_polygon_features(const Json& payload) {
    const Json obj = dict_or_empty(payload);
    const Json summary = dict_or_empty(get(obj, "result_summary"));
    const Json spatial = py_or(
        py_or(get(summary, "spatial"), get(obj, "spatial")), Json::object());
    if (!spatial.is_object()) return Json::array();
    const Json features = py_or(
        py_or(get(spatial, "features"), get(spatial, "polygons")), Json::array());
    if (!features.is_array()) return Json::array();
    Json out = Json::array();
    for (const auto& feat : features) {
        if (!feat.is_object()) continue;
        const Json& geom = get(feat, "geometry");
        if (!geom.is_object()) continue;
        const Json& gtype = get(geom, "type");
        if (!gtype.is_string() ||
            (gtype.get_ref<const std::string&>() != "Polygon" &&
             gtype.get_ref<const std::string&>() != "MultiPolygon")) {
            continue;
        }
        if (!py_truthy(get(geom, "coordinates"))) continue;
        out.push_back(feat);
    }
    return out;
}

Json validate_spatial_result(const Json& payload, const Json& expected_type,
                             bool require_scientific) {
    if (!payload.is_object()) {
        // payload.get in the Python source -> AttributeError.
        throw AttributeError("'" + detail::py_type_name(payload) +
                             "' object has no attribute 'get'");
    }
    Json errors = Json::array();
    const Json summary = dict_or_empty(get(payload, "result_summary"));
    const Json stype_v = py_truthy(expected_type)
        ? expected_type : Json(spatial_type_of(payload));
    const bool known = stype_v.is_string() &&
        kKnownSpatialTypes.count(stype_v.get_ref<const std::string&>());
    if (!known) {
        errors.push_back("unknown spatial_output_type: " + py_repr(stype_v));
        return errors;
    }
    const std::string stype = stype_v.get_ref<const std::string&>();

    if (require_scientific &&
        !py_truthy(get(summary, "final_scientific_prediction"))) {
        errors.push_back("result is not marked final_scientific_prediction");
    }

    if (stype.empty() || stype == kSpatialNone) return errors;

    if (stype == kSpatialVectorPolygons) {
        const Json features = extract_polygon_features(payload);
        if (features.empty()) {
            errors.push_back(
                "VECTOR_POLYGONS result has no valid polygon features");
        } else {
            for (size_t i = 0; i < features.size(); ++i) {
                const Json& geom = get(features[i], "geometry");
                const Json& coords = get(geom, "coordinates");
                if (!has_finite_ring(coords)) {
                    errors.push_back("feature[" + std::to_string(i) +
                                     "] has non-finite or empty coordinates");
                }
                if (looks_like_demo_square(coords)) {
                    errors.push_back("feature[" + std::to_string(i) +
                                     "] matches demo fixed-square geometry (114/22.5)");
                }
            }
        }
        const Json spatial = dict_or_empty(py_or(
            py_or(get(summary, "spatial"), get(payload, "spatial")), Json()));
        if (!py_truthy(get(spatial, "crs"))) {
            errors.push_back("VECTOR_POLYGONS missing crs");
        }
    } else if (stype == kSpatialWellIntervals) {
        const Json spatial = dict_or_empty(py_or(
            py_or(get(summary, "spatial"), get(payload, "spatial")), Json()));
        const Json intervals = py_or(
            py_or(get(spatial, "intervals"), get(spatial, "well_intervals")),
            Json::array());
        if (!py_truthy(intervals)) {
            const Json regions =
                py_or(get(summary, "predicted_regions"), Json::array());
            bool any_bounds = false;
            if (regions.is_array()) {
                for (const auto& r : regions) {
                    if (r.is_object() &&
                        (r.contains("top") || r.contains("bottom"))) {
                        any_bounds = true;
                        break;
                    }
                }
            }
            if (!any_bounds) {
                errors.push_back("WELL_INTERVALS result has no intervals");
            }
        }
    } else if (stype == kSpatialClassifiedRaster) {
        const Json spatial = dict_or_empty(py_or(
            py_or(get(summary, "spatial"), get(payload, "spatial")), Json()));
        const bool has_artifact = py_truthy(get(spatial, "artifact_path"));
        if (get(spatial, "grid").is_null() && !has_artifact) {
            errors.push_back("CLASSIFIED_RASTER missing grid or artifact_path");
        }
        if (!py_truthy(get(spatial, "crs"))) {
            errors.push_back("CLASSIFIED_RASTER missing crs");
        }
        const Json& gt = get(spatial, "geotransform");
        if (!has_artifact && (!gt.is_array() || gt.size() != 6)) {
            errors.push_back(
                "CLASSIFIED_RASTER missing 6-element geotransform or artifact_path");
        }
    }
    return errors;
}

Json bounded_result_summary(const Json& payload) {
    if (!payload.is_object()) {
        throw AttributeError("'" + detail::py_type_name(payload) +
                             "' object has no attribute 'get'");
    }
    const Json& summary_v = get(payload, "result_summary");
    Json summary = py_truthy(summary_v) ? summary_v : Json::object();
    if (!summary.is_object()) {
        // dict(non-mapping) is a ValueError/TypeError in Python, not an
        // AttributeError — keep the class distinct.
        throw TypeError(
            "cannot convert '" + detail::py_type_name(summary_v) +
            "' object to dict");
    }
    const Json& spatial_v = get(summary, "spatial");
    if (spatial_v.is_object() && !get(spatial_v, "grid").is_null()) {
        Json spatial = spatial_v;
        const Json grid = spatial["grid"];
        spatial.erase("grid");
        if (grid.is_array()) {
            Json shape = Json::array();
            shape.push_back(static_cast<long long>(grid.size()));
            long long inner = 0;
            if (!grid.empty()) {
                const Json& g0 = grid[0];
                if (g0.is_array() || g0.is_object()) {
                    inner = static_cast<long long>(g0.size());
                } else if (g0.is_string()) {
                    const auto& s = g0.get_ref<const std::string&>();
                    for (size_t i = 0; i < s.size();) {
                        auto cp = pwb::ingest::detail::utf8_code_point(s, i);
                        i += cp ? cp->size : 1;
                        ++inner;
                    }
                } else {
                    throw TypeError(
                        "object of type '" + detail::py_type_name(g0) +
                        "' has no len()");
                }
            }
            shape.push_back(inner);
            spatial["grid_shape"] = std::move(shape);
        }
        // JSON cannot carry numpy arrays — the hasattr(shape) branch is
        // unreachable from the ported domain (21-decisions.md D8).
        spatial["grid_omitted"] = true;
        summary["spatial"] = std::move(spatial);
    }
    return summary;
}

bool is_map_compilable(const Json& payload) {
    if (!py_truthy(payload)) return false;
    if (spatial_type_of(payload) != kSpatialVectorPolygons) return false;
    const Json features = extract_polygon_features(payload);
    if (features.empty()) return false;
    for (const auto& feat : features) {
        if (looks_like_demo_square(get(get(feat, "geometry"), "coordinates"))) {
            return false;
        }
    }
    return true;
}

}  // namespace pwb::prediction
