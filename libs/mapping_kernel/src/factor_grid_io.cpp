// pwb::mapping — FactorGridResult JSON envelope codec (task 18).
// Port of the serialization surface of
// paleo_workbench/workflow/factor_grid_result.py; see factor_grid_io.hpp
// for the frozen contract. Statistics reuse the frozen M7 kernel.

#include <pwb/mapping/factor_grid_io.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>

namespace pwb::mapping {

namespace {

constexpr float kNodata = std::numeric_limits<float>::quiet_NaN();

// Text sentinels used by parse_json_python_tolerant to carry Python's
// NaN / Infinity JSON literals through the RFC-strict nlohmann parser; the
// post-parse walk turns them back into the corresponding double values.
constexpr const char* kNanSentinel = "@@pwb_json_nan@@";
constexpr const char* kInfSentinel = "@@pwb_json_inf@@";
constexpr const char* kNinfSentinel = "@@pwb_json_ninf@@";

// Python str() of the JSON scalar kinds that can legally reach the backend /
// algorithm_id `or` chains. Real producers only write strings here.
std::string python_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_float()) {
        const double v = value.get<double>();
        if (std::isnan(v)) return "nan";
        if (std::isinf(v)) return v > 0 ? "inf" : "-inf";
        return value.dump();
    }
    return "";
}

const char* python_type_name(const Json& value) {
    if (value.is_null()) return "NoneType";
    if (value.is_boolean()) return "bool";
    if (value.is_number_integer()) return "int";
    if (value.is_number_float()) return "float";
    if (value.is_string()) return "str";
    if (value.is_array()) return "list";
    if (value.is_object()) return "dict";
    return "object";
}

// Python truthiness for the JSON kinds that reach `or` chains / option gates
// (NaN is truthy, matching `float("nan")`).
bool python_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return false;
}

// numpy numeric coercion of one scalar: bool → 1.0/0.0; null is the
// unsatisfiable case and yields NaN (callers decide between the finite
// check and the nodata normalization).
double numeric_or_nan(const Json& value) {
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_number()) return value.get<double>();
    return std::numeric_limits<double>::quiet_NaN();
}

// numpy-style shape text for the mismatch messages, e.g. "(2, 2)" / "(4,)".
std::string dims_text(const std::vector<std::size_t>& dims) {
    if (dims.empty()) return "()";
    std::string text = "(";
    for (std::size_t i = 0; i < dims.size(); ++i) {
        if (i > 0) text += ", ";
        text += std::to_string(dims[i]);
    }
    if (dims.size() == 1) text += ",";
    return text + ")";
}

std::string shape_mismatch(const std::string& shape, int height, int width) {
    return "grid_z shape " + shape + " does not match expected (" +
           std::to_string(height) + ", " + std::to_string(width) + ")";
}

// _to_float32_grid for the legacy list encodings, any nesting depth: numpy
// coerces to an N-D array and reshapes row-major into (height, width) when
// the element count matches. Non-number leaves become NaN (None / the
// NaN-Infinity sentinels / deeper arrays all normalize there; numeric
// strings would parse in numpy and are a documented deviation), exactly
// like the Python list-comprehension fallback. The leading label is always
// "grid_z" (Python hardcodes it, also for the variance grid).
void flatten_grid(const Json& value, std::vector<std::size_t>& dims,
                  std::vector<float>& out, std::size_t depth) {
    if (!value.is_array()) {
        const float v = static_cast<float>(numeric_or_nan(value));
        out.push_back(std::isfinite(v) ? v : kNodata);
        return;
    }
    if (dims.size() == depth) dims.push_back(value.size());
    if (value.empty()) return;
    const bool nested = value[0].is_array();
    const std::size_t row_width = nested ? value[0].size() : 0;
    for (const auto& item : value) {
        // Ragged nesting fails inside numpy's casts with a version-specific
        // message; ours is the documented deviation for that corrupt shape.
        if (item.is_array() != nested ||
            (nested && item.size() != row_width)) {
            throw std::invalid_argument("inhomogeneous shape");
        }
        flatten_grid(item, dims, out, depth + 1);
    }
}

std::vector<float> to_float32_grid(const Json& value, int height, int width) {
    std::vector<std::size_t> dims;
    std::vector<float> flat;
    flatten_grid(value, dims, flat, 0);

    const std::size_t expected =
        static_cast<std::size_t>(height) * static_cast<std::size_t>(width);
    if (flat.size() != expected) {
        // Row-major flatten is the identity for anything numpy could reshape;
        // a differing element count raises the Python message verbatim.
        throw std::invalid_argument(
            shape_mismatch(dims_text(dims), height, width));
    }
    return flat;
}

// _coerce_xy: a JSON list of numbers into float64. Booleans numericize like
// numpy (True → 1.0); a non-list is the Python TypeError branch and null is
// the unsatisfiable leaf failing the finite check with the original message.
std::vector<double> coerce_xy(const Json& value, const char* name) {
    const std::string name_str(name);
    if (value.is_array() && !value.empty() && value[0].is_array()) {
        // Deeper nesting reports only the first two dims here (documented
        // deviation for that pathological error string; the grid_z path
        // reports the full shape).
        throw std::invalid_argument(
            name_str + " must be a 1-D coordinate vector, got shape " +
            dims_text({value.size(), value[0].size()}));
    }
    if (!value.is_array()) {
        if (value.is_null() || value.is_boolean() || value.is_number()) {
            throw std::runtime_error("'" + std::string(python_type_name(value)) +
                                     "' object is not iterable");
        }
        // Strings / dicts iterate in Python and fail later inside the numeric
        // cast; that corner is documented as out of contract.
        throw std::invalid_argument(name_str +
                                    " must be a 1-D coordinate vector");
    }
    if (value.empty()) {
        throw std::invalid_argument(name_str + " must not be empty");
    }
    std::vector<double> out;
    out.reserve(value.size());
    for (const auto& item : value) {
        const double v = numeric_or_nan(item);
        if (!std::isfinite(v)) {
            throw std::invalid_argument(
                name_str + " must contain only finite coordinates");
        }
        out.push_back(v);
    }
    return out;
}

Json json_safe(const Json& value) {
    if (value.is_number_float()) {
        const double v = value.get<double>();
        if (!std::isfinite(v)) return Json(nullptr);
        return value;
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) out.push_back(json_safe(item));
        return out;
    }
    if (value.is_object()) {
        Json out = Json::object();
        for (auto it = value.begin(); it != value.end(); ++it) {
            out[it.key()] = json_safe(it.value());
        }
        return out;
    }
    return value;
}

// dict.get(key, default) — a present null wins over the default.
const Json& json_get(const Json& object, const char* key,
                     const Json& fallback) {
    if (!object.is_object()) return fallback;
    const auto it = object.find(key);
    return it == object.end() ? fallback : *it;
}

// dict.get(key) — absent → null.
Json json_get_null(const Json& object, const char* key) {
    return json_get(object, key, Json(nullptr));
}

// len(x) for the JSON kinds Python's len() accepts; used by the n_points
// branch. Returns nullopt for the types that would raise TypeError.
std::optional<int> python_len(const Json& value) {
    if (value.is_array() || value.is_object() || value.is_string()) {
        return static_cast<int>(value.size());
    }
    return std::nullopt;
}

}  // namespace

Json parse_json_python_tolerant(const std::string& text) {
    std::string sanitized;
    sanitized.reserve(text.size());
    bool in_string = false;
    bool escaped = false;
    for (std::size_t i = 0; i < text.size();) {
        const char ch = text[i];
        if (in_string) {
            sanitized.push_back(ch);
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            ++i;
            continue;
        }
        if (ch == '"') {
            in_string = true;
            sanitized.push_back(ch);
            ++i;
            continue;
        }
        if (text.compare(i, 3, "NaN") == 0) {
            sanitized += '"' + std::string(kNanSentinel) + '"';
            i += 3;
            continue;
        }
        const std::size_t token = (ch == '-') ? i + 1 : i;
        const bool negative = ch == '-';
        if (text.compare(token, 8, "Infinity") == 0) {
            sanitized += '"';
            sanitized += negative ? kNinfSentinel : kInfSentinel;
            sanitized += '"';
            i = token + 8;
            continue;
        }
        sanitized.push_back(ch);
        ++i;
    }
    Json parsed = Json::parse(sanitized);
    // Recursive rewrite: turn the string sentinels back into real doubles.
    const std::function<Json(const Json&)> rewrite =
        [&](const Json& node) -> Json {
        if (node.is_array()) {
            Json out = Json::array();
            for (const auto& item : node) out.push_back(rewrite(item));
            return out;
        }
        if (node.is_object()) {
            Json out = Json::object();
            for (auto it = node.begin(); it != node.end(); ++it) {
                out[it.key()] = rewrite(it.value());
            }
            return out;
        }
        if (node.is_string()) {
            const std::string& s = node.get_ref<const std::string&>();
            if (s == kNanSentinel) {
                return Json(std::numeric_limits<double>::quiet_NaN());
            }
            if (s == kInfSentinel) {
                return Json(std::numeric_limits<double>::infinity());
            }
            if (s == kNinfSentinel) {
                return Json(-std::numeric_limits<double>::infinity());
            }
        }
        return node;
    };
    return rewrite(parsed);
}

FactorGridEnvelope from_legacy_task_parameters(
    const Json& parameters, const std::string& factor_name,
    const std::optional<std::string>& crs, const std::optional<std::string>& unit,
    const Json& metadata) {
    if (!parameters.is_object()) {
        throw std::invalid_argument("parameters must be a JSON object");
    }
    const Json descriptor =
        metadata.is_object() ? metadata : Json::object();

    // backend = str(interp_backend or backend or "")
    std::string backend;
    const auto interp = parameters.find("interp_backend");
    if (interp != parameters.end() && python_truthy(*interp)) {
        backend = python_str(*interp);
    } else {
        const auto alt = parameters.find("backend");
        if (alt != parameters.end() && python_truthy(*alt)) {
            backend = python_str(*alt);
        }
    }
    // algorithm_id = str(descriptor.algorithm_id or backend or "unknown")
    std::string algorithm_id;
    const auto meta_algo = descriptor.find("algorithm_id");
    if (meta_algo != descriptor.end() && python_truthy(*meta_algo)) {
        algorithm_id = python_str(*meta_algo);
    } else if (!backend.empty()) {
        algorithm_id = backend;
    } else {
        algorithm_id = "unknown";
    }

    const auto require_axis = [&](const char* key) {
        const auto it = parameters.find(key);
        if (it == parameters.end()) {
            throw std::out_of_range(std::string("'") + key + "'");
        }
        return coerce_xy(*it, key);
    };
    FactorGridEnvelope result;
    result.grid_x = require_axis("grid_x");
    result.grid_y = require_axis("grid_y");
    const auto grid_z_it = parameters.find("grid_z");
    if (grid_z_it == parameters.end()) {
        throw std::out_of_range("'grid_z'");
    }
    result.width = static_cast<int>(result.grid_x.size());
    result.height = static_cast<int>(result.grid_y.size());
    result.grid_z = to_float32_grid(*grid_z_it, result.height, result.width);

    Json params = Json::object();
    if (descriptor.contains("algorithm_parameters")) {
        const Json& raw = descriptor["algorithm_parameters"];
        if (raw.is_string()) {
            // dict("abc") fails in Python with the update-sequence message.
            throw std::invalid_argument("dictionary update sequence element "
                                        "#0 has length 1; 2 is required");
        }
        // Other non-object truthy values (int/list/pair-list) are a
        // documented deviation: Python raises TypeError or accepts
        // pair-lists there; we fall back to empty parameters.
        if (raw.is_object()) params = raw;
    }
    // Fixed update set, Python dict.update semantics: existing keys keep
    // their position, new keys append in update-literal order.
    params["r_squared"] = json_get_null(params, "r_squared");
    params["grid_label"] = json_get(parameters, "grid",
                                    json_get_null(params, "grid_label"));
    Json n_points = Json(nullptr);
    const auto sample_points = parameters.find("sample_points");
    if (sample_points != parameters.end() && !sample_points->is_null()) {
        // len(sample_points or []): empty/falsy → params fallback; anything
        // len()-able (list/dict/str) contributes its length. A truthy scalar
        // (Python: TypeError on len()) is a documented deviation and also
        // falls back.
        const std::optional<int> length = python_len(*sample_points);
        if (length.has_value() && *length > 0) n_points = *length;
    }
    if (n_points.is_null()) n_points = json_get_null(params, "n_points");
    params["n_points"] = std::move(n_points);
    params["power"] = json_get(parameters, "power",
                               json_get_null(params, "power"));
    params["n_break_lines"] = json_get(
        parameters, "n_break_lines", json_get(params, "n_break_lines", Json(0)));

    if (parameters.contains("grid_var") && !parameters["grid_var"].is_null()) {
        result.variance_grid =
            to_float32_grid(parameters["grid_var"], result.height, result.width);
        params["variance_min"] = json_get_null(parameters, "variance_min");
        params["variance_max"] = json_get_null(parameters, "variance_max");
    }
    if (parameters.contains("azimuth_deg") &&
        !parameters["azimuth_deg"].is_null()) {
        params["azimuth_deg"] = parameters["azimuth_deg"];
        params["semi_major"] = json_get_null(parameters, "semi_major");
        params["semi_minor"] = json_get_null(parameters, "semi_minor");
    }
    result.factor_name = factor_name;
    result.algorithm_id = algorithm_id;
    result.algorithm_parameters = std::move(params);

    const auto boundary_it = parameters.find("grid_boundary");
    // A truthy non-array grid_boundary iterates in Python and dies in the
    // float() casts (documented deviation: we treat it as absent).
    if (boundary_it != parameters.end() && boundary_it->is_array() &&
        !boundary_it->empty()) {
        std::vector<std::pair<double, double>> ring;
        ring.reserve(boundary_it->size());
        for (const auto& point : *boundary_it) {
            const auto xy = [&](std::size_t index) {
                if (!point.is_array() || point.size() <= index) {
                    // Python unpacking fails for non-pairs; the finite check
                    // below keeps a single honest failure point (documented
                    // deviation from the unpack ValueError text).
                    return std::numeric_limits<double>::quiet_NaN();
                }
                return numeric_or_nan(point[index]);
            };
            ring.emplace_back(xy(0), xy(1));
        }
        // _finalise: boundary must contain only finite coordinates. This is
        // where Python's ±Infinity ring literals fail.
        for (const auto& [x, y] : ring) {
            if (!std::isfinite(x) || !std::isfinite(y)) {
                throw std::invalid_argument(
                    "boundary must contain only finite coordinates");
            }
        }
        result.boundary = std::move(ring);
    }

    // crs / unit: the explicit argument wins unless it is None; otherwise the
    // metadata descriptor. An empty string is explicit and never guessed.
    // Values pass through verbatim (a non-string descriptor value stays what
    // it is, exactly like Python's raw dict access).
    result.crs = crs.has_value() ? Json(*crs) : json_get_null(descriptor, "crs");
    result.unit = unit.has_value() ? Json(*unit) : json_get_null(descriptor, "unit");
    result.generator_version = json_get_null(descriptor, "generator_version");
    result.run_ref = json_get_null(descriptor, "run_ref");
    result.created_at = json_get_null(descriptor, "created_at");
    if (descriptor.contains("source_refs") &&
        descriptor["source_refs"].is_array()) {
        result.source_refs = descriptor["source_refs"];
    }

    result.statistics = grid_statistics(result.grid_z);
    return result;
}

Json grid_statistics_to_json(const GridStatistics& stats) {
    const auto num = [](double v) {
        return std::isfinite(v) ? Json(v) : Json(nullptr);
    };
    Json out = Json::object();
    out["min"] = num(stats.min);
    out["max"] = num(stats.max);
    out["mean"] = num(stats.mean);
    out["std"] = num(stats.std);
    out["valid_count"] = stats.valid_count;
    out["total_count"] = stats.total_count;
    return out;
}

Json encode_legacy_grid_lists(const std::vector<float>& grid_z, int height,
                              int width) {
    Json rows = Json::array();
    for (int i = 0; i < height; ++i) {
        Json row = Json::array();
        for (int j = 0; j < width; ++j) {
            const float v = grid_z[static_cast<std::size_t>(i) * width + j];
            row.push_back(std::isfinite(v) ? Json(static_cast<double>(v))
                                           : Json(nullptr));
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

Json encode_legacy_axis_list(const std::vector<double>& axis) {
    Json out = Json::array();
    for (const double v : axis) out.push_back(v);
    return out;
}

Json to_descriptor(const FactorGridEnvelope& result) {
    const double xmin = *std::min_element(result.grid_x.begin(),
                                          result.grid_x.end());
    const double xmax = *std::max_element(result.grid_x.begin(),
                                          result.grid_x.end());
    const double ymin = *std::min_element(result.grid_y.begin(),
                                          result.grid_y.end());
    const double ymax = *std::max_element(result.grid_y.begin(),
                                          result.grid_y.end());

    Json payload = Json::object();
    payload["factor_name"] = result.factor_name;
    payload["algorithm_id"] = result.algorithm_id;
    payload["algorithm_parameters"] = result.algorithm_parameters;
    payload["crs"] = result.crs;
    payload["crs_is_known"] = !result.crs.is_null();
    payload["unit"] = result.unit;
    payload["width"] = result.width;
    payload["height"] = result.height;
    payload["extent"] = Json::array({xmin, ymin, xmax, ymax});
    payload["generator_version"] = result.generator_version;
    payload["source_refs"] = result.source_refs;
    payload["input_version_ids"] = result.source_refs;
    payload["run_ref"] = result.run_ref;
    payload["run_id"] = result.run_ref;
    payload["created_at"] = result.created_at;
    payload["has_variance_grid"] = !result.variance_grid.empty();
    payload["has_boundary"] = result.boundary.has_value();
    payload["statistics"] = grid_statistics_to_json(result.statistics);
    // Engine-refined contours ride the descriptor only when present; the
    // from_legacy read path cannot produce them, so the key stays absent.
    return json_safe(std::move(payload));
}

Json to_legacy_dict(const FactorGridEnvelope& result) {
    const Json stats = grid_statistics_to_json(result.statistics);
    Json out = Json::object();
    out["grid_x"] = encode_legacy_axis_list(result.grid_x);
    out["grid_y"] = encode_legacy_axis_list(result.grid_y);
    out["grid_z"] =
        encode_legacy_grid_lists(result.grid_z, result.height, result.width);
    out["backend"] = result.algorithm_id;
    out["min"] = stats["min"];
    out["max"] = stats["max"];
    out["mean"] = stats["mean"];
    out["r_squared"] = json_get_null(result.algorithm_parameters, "r_squared");
    if (!result.variance_grid.empty()) {
        out["grid_var"] = encode_legacy_grid_lists(
            result.variance_grid, result.height, result.width);
        out["variance_min"] =
            json_get_null(result.algorithm_parameters, "variance_min");
        out["variance_max"] =
            json_get_null(result.algorithm_parameters, "variance_max");
    }
    if (result.boundary.has_value()) {
        Json ring = Json::array();
        for (const auto& [x, y] : *result.boundary) {
            ring.push_back(Json::array({x, y}));
        }
        out["boundary"] = std::move(ring);
    }
    return out;
}

}  // namespace pwb::mapping
