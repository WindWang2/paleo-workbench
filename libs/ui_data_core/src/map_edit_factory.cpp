#include "pwb/ui_data_core/map_edit_factory.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <utility>

namespace pwb::ui_data_core {
namespace {

// record.get(key) → pointer or nullptr (missing/null → nullptr).
const domain::Json* get_member(const domain::Json& object,
                               std::string_view key) {
    if (!object.is_object()) {
        return nullptr;
    }
    const auto it = object.find(std::string(key));
    return it == object.end() ? nullptr : &*it;
}

// str(record.get(key) or fallback) — the Python `or` chain.
std::string str_or(const domain::Json* value, std::string_view fallback = "") {
    if (value == nullptr || !json_truthy(*value)) {
        return std::string(fallback);
    }
    return python_str(*value);
}

// float(point[i]) with the (TypeError, ValueError) → reject contract.
std::optional<double> coord_at(const domain::Json& coords, std::size_t i) {
    if (!coords.is_array() || coords.size() <= i) {
        return std::nullopt;
    }
    return json_float(coords[i]);
}

}  // namespace

std::optional<FeatureModel> item_from_record(const domain::Json& record) {
    const domain::Json* kind = get_member(record, "kind");
    const domain::Json* feature_id = get_member(record, "id");
    if (feature_id == nullptr || !json_truthy(*feature_id)) {
        return std::nullopt;
    }
    const std::string kind_str =
        kind != nullptr && kind->is_string() ? kind->get<std::string>() : "";
    if (kind_str == "facies") {
        if (auto model = make_facies(record)) {
            return FeatureModel{std::move(*model)};
        }
    } else if (kind_str == "well") {
        if (auto model = make_well(record)) {
            return FeatureModel{std::move(*model)};
        }
    } else if (kind_str == "line") {
        if (auto model = make_line(record)) {
            return FeatureModel{std::move(*model)};
        }
    } else if (kind_str == "label") {
        if (auto model = make_label(record)) {
            return FeatureModel{std::move(*model)};
        }
    }
    return std::nullopt;
}

std::optional<FaciesPolygonModel> make_facies(const domain::Json& record) {
    auto [geometry_type, polygons] = canonical_facies_geometry(record);
    if (polygons.empty() || polygons.front().empty() ||
        polygons.front().front().size() < 4) {
        return std::nullopt;
    }
    for (const auto& polygon : polygons) {
        for (const auto& ring : polygon) {
            if (ring.size() < 4) {
                return std::nullopt;
            }
        }
    }
    // geometry_coordinates = polygons[0] if Polygon else polygons.
    domain::Json geometry_coordinates =
        geometry_type == "Polygon" ? polygon_to_json(polygons.front())
                                   : multipolygon_to_json(polygons);
    domain::Json extras = domain::Json::object();
    for (const char* key :
         {"facies", "probability", "region_id", "properties"}) {
        const domain::Json* value = get_member(record, key);
        if (value != nullptr && !value->is_null()) {
            extras[key] = *value;
        }
    }
    const domain::Json* style = get_member(record, "style");
    return FaciesPolygonModel(
        /*feature_id=*/python_str(*get_member(record, "id")),
        /*coordinates=*/ring_to_json(polygons.front().front()),
        /*name=*/str_or(get_member(record, "name")),
        /*style=*/json_truthy(style != nullptr ? *style
                                              : domain::Json(nullptr))
            ? *style
            : domain::Json::object(),
        /*extras=*/extras,
        /*geometry_type=*/geometry_type,
        /*geometry_coordinates=*/&geometry_coordinates);
}

std::optional<WellPointModel> make_well(const domain::Json& record) {
    // coordinate_status flagged → skip like other bad-geometry records
    // (audit #1162: never draw the fabricated placeholder position).
    const std::string status =
        str_or(get_member(record, "coordinate_status"), "ok");
    if (coordinate_status_is_flagged(status)) {
        return std::nullopt;
    }
    const domain::Json* coords = get_member(record, "coordinates");
    const domain::Json fallback = domain::Json::array({0, 0});
    const domain::Json& source =
        (coords != nullptr && json_truthy(*coords)) ? *coords : fallback;
    if (!source.is_array() || source.size() < 2) {
        return std::nullopt;
    }
    const auto x = json_float(source[0]);
    const auto y = json_float(source[1]);
    if (!x.has_value() || !y.has_value()) {
        return std::nullopt;
    }
    return WellPointModel(
        /*feature_id=*/python_str(*get_member(record, "id")), *x, *y,
        /*name=*/str_or(get_member(record, "name")));
}

std::optional<LineModel> make_line(const domain::Json& record) {
    const domain::Json* coords = get_member(record, "coordinates");
    const domain::Json empty = domain::Json::array();
    const domain::Json& source =
        (coords != nullptr && json_truthy(*coords)) ? *coords : empty;
    if (!source.is_array() || source.size() < 2) {
        return std::nullopt;
    }
    MapRing points;
    for (const auto& p : source) {
        if (!p.is_array() || p.size() < 2) {
            return std::nullopt;
        }
        const auto x = json_float(p[0]);
        const auto y = json_float(p[1]);
        if (!x.has_value() || !y.has_value()) {
            return std::nullopt;
        }
        points.push_back({*x, *y});
    }
    return LineModel(
        /*feature_id=*/python_str(*get_member(record, "id")),
        std::move(points),
        /*name=*/str_or(get_member(record, "name")));
}

std::optional<LabelModel> make_label(const domain::Json& record) {
    const domain::Json* coords = get_member(record, "coordinates");
    const domain::Json fallback = domain::Json::array({0, 0});
    const domain::Json& source =
        (coords != nullptr && json_truthy(*coords)) ? *coords : fallback;
    if (!source.is_array() || source.size() < 2) {
        return std::nullopt;
    }
    const auto x = json_float(source[0]);
    const auto y = json_float(source[1]);
    if (!x.has_value() || !y.has_value()) {
        return std::nullopt;
    }
    const domain::Json* text_value = get_member(record, "text");
    if (text_value == nullptr || !json_truthy(*text_value)) {
        text_value = get_member(record, "name");
    }
    const std::string text = str_or(text_value);
    const std::string name = [&] {
        const domain::Json* name_value = get_member(record, "name");
        return name_value != nullptr && json_truthy(*name_value)
                   ? python_str(*name_value)
                   : text;
    }();
    return LabelModel(
        /*feature_id=*/python_str(*get_member(record, "id")), *x, *y, text,
        name);
}

}  // namespace pwb::ui_data_core
