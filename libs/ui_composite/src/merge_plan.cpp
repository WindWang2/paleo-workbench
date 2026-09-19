#include <pwb/ui_composite/merge_plan.hpp>

#include <algorithm>
#include <cmath>
#include <set>

namespace pwb::ui_composite {
namespace {

double ring_area(const Json& ring) {
    if (!ring.is_array() || ring.size() < 4) {
        return 0.0;
    }
    double area = 0.0;
    for (size_t i = 0; i + 1 < ring.size(); ++i) {
        const Json& node = ring[i];
        const Json& next = ring[i + 1];
        if (!node.is_array() || !next.is_array() || node.size() < 2 ||
            next.size() < 2 || !node[0].is_number() ||
            !node[1].is_number() || !next[0].is_number() ||
            !next[1].is_number()) {
            continue;
        }
        area += node[0].get<double>() * next[1].get<double>() -
                next[0].get<double>() * node[1].get<double>();
    }
    return area / 2.0;
}

std::string json_identity_key(const Json& value) {
    // Stable identity for "value already seen" — matches Python's
    // `value not in values` equality on JSON scalars/containers.
    return value.dump();
}

}  // namespace

double polygon_area(const Json& geometry) {
    if (!geometry.is_object()) {
        return 0.0;
    }
    auto type_it = geometry.find("type");
    const std::string kind =
        type_it != geometry.end() && type_it->is_string()
            ? type_it->get<std::string>()
            : std::string{};
    auto coords_it = geometry.find("coordinates");
    const Json empty = Json::array();
    const Json& coords =
        coords_it != geometry.end() && coords_it->is_array() ? *coords_it
                                                             : empty;
    if (kind == "Polygon" && !coords.empty()) {
        return std::abs(ring_area(coords[0]));
    }
    if (kind == "MultiPolygon") {
        double total = 0.0;
        for (const Json& polygon : coords) {
            if (polygon.is_array() && !polygon.empty()) {
                total += std::abs(ring_area(polygon[0]));
            }
        }
        return total;
    }
    return 0.0;
}

Json plan_merge_attributes(
    const std::vector<Json>& records,
    const std::vector<std::string>& facies_fields) {
    Json facies = Json::array();
    for (const std::string& name : facies_fields) {
        facies.push_back(name);
    }
    struct Item {
        std::string id;
        double area;
        Json properties;
    };
    std::vector<Item> items;
    for (const Json& record : records) {
        if (!record.is_object()) {
            continue;
        }
        auto id_it = record.find("id");
        const std::string feature_id =
            id_it != record.end() && !id_it->is_null()
                ? (id_it->is_string() ? id_it->get<std::string>()
                                      : id_it->dump())
                : std::string{};
        if (feature_id.empty()) {
            continue;
        }
        auto geom_it = record.find("geometry");
        const Json geometry =
            geom_it != record.end() && geom_it->is_object() ? *geom_it
                                                            : Json::object();
        auto props_it = record.find("properties");
        const Json properties =
            props_it != record.end() && props_it->is_object()
                ? *props_it
                : Json::object();
        items.push_back(Item{feature_id, polygon_area(geometry),
                             properties});
    }
    if (items.empty()) {
        return {{"target_id", ""},
                {"attributes", Json::object()},
                {"conflicts", Json::object()},
                {"facies_fields", std::move(facies)}};
    }
    // Python sort key (-area, id): descending area, ascending id.
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
        if (a.area != b.area) {
            return a.area > b.area;
        }
        return a.id < b.id;
    });
    const Item& target = items.front();

    std::vector<std::string> keys;
    for (const Item& item : items) {
        for (const auto& [key, value] : item.properties.items()) {
            if (std::find(keys.begin(), keys.end(), key) == keys.end()) {
                keys.push_back(key);
            }
        }
    }
    Json conflicts = Json::object();
    for (const std::string& key : keys) {
        Json values = Json::array();
        std::set<std::string> seen;
        for (const Item& item : items) {
            auto it = item.properties.find(key);
            const Json value =
                it != item.properties.end() ? *it : Json(nullptr);
            const std::string identity = json_identity_key(value);
            if (seen.insert(identity).second) {
                values.push_back(value);
            }
        }
        if (values.size() > 1) {
            conflicts[key] = std::move(values);
        }
    }
    return {{"target_id", target.id},
            {"attributes", target.properties},
            {"conflicts", std::move(conflicts)},
            {"facies_fields", std::move(facies)}};
}

}  // namespace pwb::ui_composite
