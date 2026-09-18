#include <pwb/mapping/representative_facies.hpp>

#include <pwb/mapping/crs_policy.hpp>

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <iterator>
#include <stdexcept>
#include <unordered_map>

namespace pwb::mapping {
namespace {

// Python str.isspace() membership for the code point at `at` (UTF-8 decoded;
// nlohmann input is always valid UTF-8). `next` receives the following byte.
bool python_isspace_at(const std::string& text, std::size_t at,
                       std::size_t* next) {
    const auto byte = [&text](std::size_t i) {
        return static_cast<unsigned char>(text[i]);
    };
    const unsigned char lead = byte(at);
    std::size_t len = 1;
    std::uint32_t cp = lead;
    if (lead >= 0xF0) {
        len = 4;
        cp = lead & 0x07u;
    } else if (lead >= 0xE0) {
        len = 3;
        cp = lead & 0x0Fu;
    } else if (lead >= 0xC0) {
        len = 2;
        cp = lead & 0x1Fu;
    }
    for (std::size_t i = 1; i < len && at + i < text.size(); ++i) {
        cp = (cp << 6) | (byte(at + i) & 0x3Fu);
    }
    *next = at + len;
    return cp == 0x20 || (cp >= 0x09 && cp <= 0x0D) ||
           (cp >= 0x1C && cp <= 0x1F) || cp == 0x85 || cp == 0xA0 ||
           cp == 0x1680 || (cp >= 0x2000 && cp <= 0x200A) ||
           cp == 0x2028 || cp == 0x2029 || cp == 0x202F || cp == 0x205F ||
           cp == 0x3000;
}

// Python str.strip(): Unicode whitespace, including the ideographic space
// that CJK facies names actually use. Digit characters inside
// parse_python_float stay ASCII-bounded (documented in 10-decisions.md).
std::string strip(const std::string& text) {
    std::size_t begin = 0;
    while (begin < text.size()) {
        std::size_t next = begin + 1;
        if (!python_isspace_at(text, begin, &next)) break;
        begin = next;
    }
    std::size_t end = text.size();
    while (end > begin) {
        std::size_t prev = end - 1;
        while (prev > begin &&
               (static_cast<unsigned char>(text[prev]) & 0xC0) == 0x80) {
            --prev;
        }
        std::size_t next = prev + 1;
        if (!python_isspace_at(text, prev, &next)) break;
        end = prev;
    }
    return text.substr(begin, end - begin);
}

// Python truthiness for JSON scalars/containers in `or` chains.
bool python_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_unsigned()) return value.get<std::uint64_t>() != 0;
    if (value.is_number_integer()) return value.get<std::int64_t>() != 0;
    if (value.is_number_float()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    return !value.empty();
}

// str(scalar) for values picked out of a truthy chain. Non-string scalars
// and containers are outside the product's JSON domain (region records
// carry strings); their JSON dump stands in for Python's repr/str.
std::string python_str_scalar(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_unsigned()) {
        return std::to_string(value.get<std::uint64_t>());
    }
    if (value.is_number_integer()) {
        return std::to_string(value.get<std::int64_t>());
    }
    return value.dump();  // float and container values: JSON dump ≈ str()
}

// float(str): surrounding whitespace, optional sign, decimal/exponent forms,
// PEP 515 digit separators ("1_000.5"). Bounded to ASCII digits (Python also
// maps Unicode decimal digits — recorded as out of domain in
// 10-decisions.md). inf/infinity/nan words are rejected here, which lands in
// the same place as Python: _finite(inf/nan) is None. ERANGE is tolerated:
// underflow returns 0.0/subnormal, overflow ±inf, exactly what Python's
// float() returns for the same text.
std::optional<double> parse_python_float(const std::string& text) {
    const std::string trimmed = strip(text);
    if (trimmed.empty()) return std::nullopt;
    std::size_t at = 0;
    if (trimmed[at] == '+' || trimmed[at] == '-') ++at;
    std::string body = trimmed.substr(at);
    const auto digit = [](char c) { return c >= '0' && c <= '9'; };
    for (std::size_t i = 0; i < body.size(); ++i) {
        if (body[i] != '_') continue;
        if (!(i > 0 && digit(body[i - 1]) && i + 1 < body.size() &&
              digit(body[i + 1]))) {
            return std::nullopt;
        }
    }
    body.erase(std::remove(body.begin(), body.end(), '_'), body.end());
    if (body.empty()) return std::nullopt;
    std::string word;
    word.reserve(body.size());
    for (const char c : body) {
        word.push_back(
            static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    bool digits = false;
    bool dot = false;
    std::size_t mantissa = 0;
    while (mantissa < word.size()) {
        const char c = word[mantissa];
        if (digit(c)) {
            digits = true;
        } else if (c == '.' && !dot) {
            dot = true;
        } else {
            break;
        }
        ++mantissa;
    }
    std::size_t end = mantissa;
    if (end < word.size() && word[end] == 'e') {
        std::size_t exp_at = end + 1;
        if (exp_at < word.size() &&
            (word[exp_at] == '+' || word[exp_at] == '-')) {
            ++exp_at;
        }
        bool exp_digits = false;
        while (exp_at < word.size() && digit(word[exp_at])) {
            exp_digits = true;
            ++exp_at;
        }
        if (exp_digits) end = exp_at;
    }
    if (!digits || end != word.size()) return std::nullopt;
    const std::string number = trimmed.substr(0, at) + body;
    errno = 0;
    char* parsed_end = nullptr;
    const double value = std::strtod(number.c_str(), &parsed_end);
    if (parsed_end != number.c_str() + number.size()) return std::nullopt;
    // errno == ERANGE is fine: strtod already returned the same value
    // Python's float() would (0.0/subnormal on underflow, ±inf on overflow).
    return value;
}

// _finite(value): float(value) when finite, else None.
std::optional<double> finite_of(const Json& value) {
    if (value.is_null()) return std::nullopt;
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_number_unsigned()) {
        return static_cast<double>(value.get<std::uint64_t>());
    }
    if (value.is_number_integer()) {
        return static_cast<double>(value.get<std::int64_t>());
    }
    if (value.is_number_float()) {
        const double number = value.get<double>();
        return std::isfinite(number) ? std::optional(number) : std::nullopt;
    }
    if (value.is_string()) {
        const auto parsed = parse_python_float(value.get<std::string>());
        if (!parsed || !std::isfinite(*parsed)) return std::nullopt;
        return parsed;
    }
    return std::nullopt;  // containers: float() raises TypeError in Python
}

// `a.get(k1) or a.get(k2) or ...` — pointer to the first truthy value.
const Json* truthy_chain(const Json& object,
                         std::initializer_list<const char*> keys) {
    if (!object.is_object()) return nullptr;
    for (const char* key : keys) {
        const auto it = object.find(key);
        if (it != object.end() && python_truthy(*it)) return &(*it);
    }
    return nullptr;
}

Json spatial_of(const Json& result_summary) {
    if (!result_summary.is_object()) return Json::object();
    const auto it = result_summary.find("spatial");
    if (it != result_summary.end() && it->is_object()) return *it;
    return Json::object();
}

Json object_list(const Json& value) {
    Json out = Json::array();
    if (value.is_array()) {
        for (const Json& item : value) {
            if (item.is_object()) out.push_back(item);
        }
    }
    return out;
}

Json ring_json(const Ring& ring) {
    Json out = Json::array();
    for (const Point& vertex : ring) {
        out.push_back(Json::array({vertex[0], vertex[1]}));
    }
    return out;
}

// geometry_units.area_unit_label for the already-stripped crs text.
std::string area_unit_label(const std::string& crs_text) {
    if (!crs_text.empty() &&
        crs_is_geographic(crs_text).value_or(false)) {
        return "deg²";
    }
    if (!crs_text.empty()) return crs_text + "-unit²";
    return "unknown-unit²";
}

// geometry_units ring_area_with_unit geographic branch (111320² scale).
// kDegToRad mirrors CPython math.degToRad (π as nearest double / 180).
double ring_area_approx_m2(const Ring& ring) {
    constexpr double kMetresPerDegreeLat = 111320.0;
    constexpr double kDegToRad = 3.141592653589793 / 180.0;
    double y_sum = 0.0;
    for (const Point& vertex : ring) y_sum += vertex[1];
    const double mean_lat =
        ring.empty()
            ? 0.0
            : (y_sum / static_cast<double>(ring.size())) * kDegToRad;
    const double scale =
        (kMetresPerDegreeLat * std::cos(mean_lat)) * kMetresPerDegreeLat;
    return shoelace_area(ring) * scale;
}

}  // namespace

std::optional<RepresentativeFacies> representative_facies(
    const Json& regions, const std::string& horizon) {
    std::vector<const Json*> items;
    if (regions.is_array()) {
        for (const Json& record : regions) {
            if (record.is_object()) items.push_back(&record);
        }
    }
    const std::string horizon_text = strip(horizon);
    if (!horizon_text.empty()) {
        std::vector<const Json*> matched;
        for (const Json* record : items) {
            const Json* unit = truthy_chain(
                *record, {"stratigraphic_unit", "horizon"});
            const std::string text =
                unit ? python_str_scalar(*unit) : std::string();
            if (text.find(horizon_text) != std::string::npos) {
                matched.push_back(record);
            }
        }
        if (!matched.empty()) items = std::move(matched);
    }

    struct Total {
        std::string facies;
        double thickness = 0.0;
        double mass = 0.0;
        double weight = 0.0;
    };
    std::vector<Total> totals;
    std::unordered_map<std::string, std::size_t> index_of;
    for (const Json* record : items) {
        const Json* facies_value =
            truthy_chain(*record, {"facies", "label", "name"});
        const std::string facies =
            strip(facies_value ? python_str_scalar(*facies_value) : "");
        if (facies.empty()) continue;
        const auto top_it = record->find("top");
        const auto bottom_it = record->find("bottom");
        const auto top = top_it != record->end() ? finite_of(*top_it)
                                                 : std::nullopt;
        const auto bottom = bottom_it != record->end()
                                ? finite_of(*bottom_it)
                                : std::nullopt;
        const double thickness =
            top && bottom ? std::fabs(*bottom - *top) : 0.0;
        const Json* probability_value =
            truthy_chain(*record, {"probability", "confidence"});
        const auto probability =
            probability_value ? finite_of(*probability_value) : std::nullopt;

        const auto it = index_of.find(facies);
        std::size_t at;
        if (it == index_of.end()) {
            at = totals.size();
            index_of.emplace(facies, at);
            totals.push_back({facies, 0.0, 0.0, 0.0});
        } else {
            at = it->second;
        }
        Total& total = totals[at];
        total.thickness += thickness;
        if (probability) {
            const double sample_weight = thickness > 0.0 ? thickness : 1.0;
            total.mass += *probability * sample_weight;
            total.weight += sample_weight;
        }
    }
    if (totals.empty()) return std::nullopt;

    // max(items, key=(thickness, mean)) — Python keeps the FIRST maximum,
    // so strict greater-than preserves insertion order on full ties.
    const Total* best = &totals.front();
    double best_mean =
        best->weight != 0.0 ? best->mass / best->weight : 0.0;
    for (std::size_t at = 1; at < totals.size(); ++at) {
        const Total& total = totals[at];
        const double mean =
            total.weight != 0.0 ? total.mass / total.weight : 0.0;
        if (total.thickness > best->thickness ||
            (total.thickness == best->thickness && mean > best_mean)) {
            best = &total;
            best_mean = mean;
        }
    }

    RepresentativeFacies picked;
    picked.facies = best->facies;
    picked.thickness = best->thickness;
    if (best->weight != 0.0) picked.mean_probability = best->mass / best->weight;
    return picked;
}

Json task_regions(const Json& result_summary) {
    const Json spatial = spatial_of(result_summary);
    const auto intervals = spatial.find("intervals");
    const auto well_intervals = spatial.find("well_intervals");
    const Json* chosen = nullptr;
    if (intervals != spatial.end() && python_truthy(*intervals)) {
        chosen = &(*intervals);
    } else if (well_intervals != spatial.end() &&
               python_truthy(*well_intervals)) {
        chosen = &(*well_intervals);
    }
    // Python: `isinstance(intervals, list) and intervals` — a truthy
    // non-list value (string/dict) skips straight to predicted_regions.
    if (chosen && chosen->is_array()) return object_list(*chosen);
    if (!result_summary.is_object()) return Json::array();
    const auto regions = result_summary.find("predicted_regions");
    if (regions != result_summary.end() && python_truthy(*regions)) {
        return object_list(*regions);
    }
    return Json::array();
}

std::vector<WellFaciesPoint> spatial_point_features(
    const Json& result_summary, const std::string& task_id) {
    std::vector<WellFaciesPoint> points;
    const Json spatial = spatial_of(result_summary);
    const auto raw = spatial.find("features");
    if (raw == spatial.end() || !raw->is_array()) return points;
    for (const Json& record : *raw) {
        if (!record.is_object()) continue;
        const auto geometry = record.find("geometry");
        if (geometry == record.end() || !geometry->is_object()) continue;
        const auto type = geometry->find("type");
        if (type == geometry->end() || !type->is_string() ||
            type->get<std::string>() != "Point") {
            continue;
        }
        const auto coordinates = geometry->find("coordinates");
        if (coordinates == geometry->end() || !coordinates->is_array() ||
            coordinates->size() < 2) {
            continue;
        }
        const auto x = finite_of((*coordinates)[0]);
        const auto y = finite_of((*coordinates)[1]);
        if (!x || !y) continue;
        const Json properties = [&record]() {
            const auto props = record.find("properties");
            if (props != record.end() && props->is_object()) return *props;
            return Json::object();
        }();
        const Json* facies_value =
            truthy_chain(properties, {"facies", "label", "name"});
        const std::string facies =
            strip(facies_value ? python_str_scalar(*facies_value) : "");
        if (facies.empty()) continue;

        WellFaciesPoint point;
        point.x = *x;
        point.y = *y;
        point.facies = facies;
        const Json* well_id_value = truthy_chain(properties, {"well_id"});
        if (well_id_value) point.well_id = python_str_scalar(*well_id_value);
        const Json* well_name_value =
            truthy_chain(properties, {"well_name", "well"});
        if (well_name_value) {
            point.well_name = python_str_scalar(*well_name_value);
        }
        const Json* probability_value =
            truthy_chain(properties, {"probability", "confidence"});
        if (probability_value) {
            point.probability = finite_of(*probability_value);
        }
        point.task_id = task_id;
        points.push_back(std::move(point));
    }
    return points;
}

std::vector<std::pair<Json, Json>> point_features(
    const std::vector<WellFaciesPoint>& points) {
    std::vector<std::pair<Json, Json>> features;
    features.reserve(points.size());
    for (const WellFaciesPoint& point : points) {
        Json properties = Json::object();
        properties["facies"] = point.facies;
        properties["well_id"] = point.well_id;
        properties["well_name"] = point.well_name;
        properties["prediction_task_id"] = point.task_id;
        if (point.probability) properties["probability"] = *point.probability;
        if (point.thickness) properties["thickness"] = *point.thickness;
        Json geometry = Json::object();
        geometry["type"] = "Point";
        geometry["coordinates"] = Json::array({point.x, point.y});
        features.emplace_back(std::move(geometry), std::move(properties));
    }
    return features;
}

std::optional<std::array<double, 4>> extent_from_workarea_boundary(
    const std::vector<Point>& boundary) {
    std::vector<double> xs;
    std::vector<double> ys;
    xs.reserve(boundary.size());
    ys.reserve(boundary.size());
    for (const Point& vertex : boundary) {
        if (std::isfinite(vertex[0]) && std::isfinite(vertex[1])) {
            xs.push_back(vertex[0]);
            ys.push_back(vertex[1]);
        }
    }
    if (xs.size() < 3) return std::nullopt;
    const auto bounds = [](const std::vector<double>& values) {
        const auto pair = std::minmax_element(values.begin(), values.end());
        return std::array<double, 2>{*pair.first, *pair.second};
    };
    const auto x = bounds(xs);
    const auto y = bounds(ys);
    return std::array<double, 4>{x[0], y[0], x[1], y[1]};
}

std::array<double, 4> extent_from_points(
    const std::vector<WellFaciesPoint>& points) {
    if (points.empty()) {
        throw std::invalid_argument(
            "extent_from_points needs at least one well facies point");
    }
    double xmin = points.front().x;
    double xmax = xmin;
    double ymin = points.front().y;
    double ymax = ymin;
    for (const WellFaciesPoint& point : points) {
        xmin = std::min(xmin, point.x);
        xmax = std::max(xmax, point.x);
        ymin = std::min(ymin, point.y);
        ymax = std::max(ymax, point.y);
    }
    const double span_x = std::max(xmax - xmin, 1.0);
    const double span_y = std::max(ymax - ymin, 1.0);
    const double pad_x = span_x * 0.1;
    const double pad_y = span_y * 0.1;
    return {xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y};
}

std::vector<Point> clip_ring_from_boundary(const std::vector<Point>& boundary) {
    std::vector<Point> cleaned;
    cleaned.reserve(boundary.size());
    for (const Point& vertex : boundary) {
        if (std::isfinite(vertex[0]) && std::isfinite(vertex[1])) {
            cleaned.push_back({vertex[0], vertex[1]});
        }
    }
    if (cleaned.size() < 4) return {};
    return cleaned;
}

std::vector<std::pair<Json, Json>> point_to_surface_features(
    const std::vector<WellFaciesPoint>& points,
    const std::array<double, 4>& extent,
    int grid_n,
    const std::vector<Point>& clip_ring,
    const std::string& crs) {
    // Python: `if len(points) < 1: return []`.
    if (points.empty()) return {};

    std::vector<FaciesPoint> grid_points;
    grid_points.reserve(points.size());
    for (const WellFaciesPoint& point : points) {
        grid_points.push_back({point.x, point.y, point.facies});
    }
    const ClassGrid class_grid_z =
        nearest_neighbor_class_grid(grid_points, extent, grid_n, clip_ring);

    Grid grid;  // contouring double grid for the polygonize kernels
    grid.w = class_grid_z.grid_x.size();
    grid.h = class_grid_z.grid_y.size();
    grid.grid_x = class_grid_z.grid_x;
    grid.grid_y = class_grid_z.grid_y;
    grid.grid_z.reserve(class_grid_z.grid_z.size());
    for (float value : class_grid_z.grid_z) {
        grid.grid_z.push_back(static_cast<double>(value));
    }

    std::vector<std::pair<Json, Json>> features;
    const bool any_finite = std::any_of(
        grid.grid_z.begin(), grid.grid_z.end(),
        [](double value) { return std::isfinite(value); });
    if (!any_finite) return features;

    const int n_class = static_cast<int>(class_grid_z.facies_names.size());
    std::vector<double> thresholds;
    if (n_class == 1) {
        thresholds.push_back(0.0);
    } else {
        for (int i = 0; i + 1 < n_class; ++i) thresholds.push_back(i + 0.5);
    }
    const std::vector<double> sorted_thresholds =
        unique_sorted_thresholds(thresholds);
    const std::vector<std::int16_t> classes =
        classify_grid(grid, sorted_thresholds, n_class);

    const std::string crs_text = strip(crs);
    const std::string unit_label = area_unit_label(crs_text);
    const bool geographic =
        !crs_text.empty() && crs_is_geographic(crs_text).value_or(false);
    static constexpr const char* kDefaultPalette[] = {
        "#b0bec5", "#ffe082", "#d73027", "#81c784", "#4fc3f7", "#ba68c8"};
    const double total_grid_area =
        std::max(1e-12, (extent[2] - extent[0]) * (extent[3] - extent[1]));

    for (int c_idx = 0; c_idx < n_class; ++c_idx) {
        double sum = 0.0;
        std::size_t count = 0;
        for (std::size_t at = 0; at < classes.size(); ++at) {
            if (classes[at] == static_cast<std::int16_t>(c_idx) &&
                std::isfinite(grid.grid_z[at])) {
                sum += grid.grid_z[at];
                ++count;
            }
        }
        if (count == 0) continue;
        // Python np.mean over a float32 mask → float32 result. Class-id
        // sums are exact integers on both sides, so only the division can
        // round: double-then-cast differs from numpy's float32 division by
        // at most 1 float32 ulp, absorbed by the round-to-4 below.
        const double mean_value = static_cast<double>(
            static_cast<float>(sum / static_cast<double>(count)));

        const auto traced = polygonize_class(grid, classes, c_idx);
        for (const Polygon& polygon : traced.first) {
            // Python polygonization.py:531-541 accumulation order: exterior
            // first, then each hole subtracted in ring order.
            const double ext_area = shoelace_area(polygon.exterior);
            double holes_area = 0.0;
            double approx_area =
                geographic ? ring_area_approx_m2(polygon.exterior) : 0.0;
            for (const Ring& hole : polygon.holes) {
                holes_area += shoelace_area(hole);
                if (geographic) approx_area -= ring_area_approx_m2(hole);
            }
            const double raw_area = std::max(0.0, ext_area - holes_area);
            if (geographic) approx_area = std::max(0.0, approx_area);

            Json properties = Json::object();
            properties["facies_id"] = c_idx + 1;
            properties["facies_name"] = class_grid_z.facies_names[c_idx];
            properties["facies"] = class_grid_z.facies_names[c_idx];
            properties["color"] = kDefaultPalette[
                static_cast<std::size_t>(c_idx) % std::size(kDefaultPalette)];
            properties["area"] = round_to(raw_area, 4);
            properties["area_unit"] = unit_label;
            properties["area_percent"] =
                round_to(raw_area / total_grid_area * 100.0, 4);
            properties["mean_value"] = round_to(mean_value, 4);
            if (geographic) {
                properties["area_approx_m2"] = round_to(approx_area, 4);
            }
            // point_to_surface_features post-set (setdefault no-op: "facies"
            // is always present from the assembly above).
            properties["source"] = "well_point_to_surface";

            Json geometry = Json::object();
            geometry["type"] = "Polygon";
            Json coordinates = Json::array();
            coordinates.push_back(ring_json(polygon.exterior));
            for (const Ring& hole : polygon.holes) {
                coordinates.push_back(ring_json(hole));
            }
            geometry["coordinates"] = coordinates;
            features.emplace_back(std::move(geometry), std::move(properties));
        }
    }
    return features;
}

}  // namespace pwb::mapping
