#include "pwb/ui_composite/constraints_sync.hpp"

#include "pwb/domain/sha256.hpp"
#include "pwb/ui_composite/roles.hpp"

#include <cmath>
#include <utility>
#include <vector>

namespace pwb::ui_composite {
namespace {

std::optional<double> finite(const Json& value) {
    double number;
    if (value.is_number()) {
        number = value.get<double>();
    } else if (value.is_string()) {
        try {
            number = std::stod(value.get<std::string>());
        } catch (const std::exception&) {
            return std::nullopt;
        }
    } else {
        return std::nullopt;
    }
    return std::isfinite(number) ? std::optional<double>{number}
                                 : std::nullopt;
}

// _vertex parity — [x, y] or invalid.
Json vertex_of(const Json& point) {
    if (!point.is_array() || point.size() < 2) return Json();
    const auto x = finite(point[0]);
    const auto y = finite(point[1]);
    if (!x || !y) return Json();
    return Json::array({*x, *y});
}

Json* field(Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it != object.end() ? &*it : nullptr;
}

const Json* field(const Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it != object.end() ? &*it : nullptr;
}

std::string str_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    if (v == nullptr || v->is_null()) return "";
    if (v->is_string()) return v->get<std::string>();
    if (v->is_boolean()) return v->get<bool>() ? "True" : "False";
    if (v->is_number_integer()) return std::to_string(v->get<long long>());
    if (v->is_number_unsigned())
        return std::to_string(v->get<unsigned long long>());
    if (v->is_number()) return std::to_string(v->get<double>());
    return "";
}

// Round to 9 decimals (Python round(float(x), 9) — round-half-even on
// the decimal representation; std::round is half-away but the 1e-9 scale
// only ever differs on exact .5 ties of the 9th decimal, which the
// Python path hits identically rarely — kept simple per the docstring).
double round9(double value) {
    return std::round(value * 1e9) / 1e9;
}

bool line_kind_of(const Json& layer) {
    const std::string kind_value = str_of(layer, "template");
    const auto kind = constraint_kind_from_value(kind_value);
    if (kind.has_value()) {
        return constraint_kind_geometry_kind(*kind) != "polygon";
    }
    return str_of(layer, "geometry_kind") != "polygon";
}

// _harvest_coordinates parity — feature geometries → sequences +
// interior-rings-skipped count.
std::pair<std::vector<Json>, int> harvest_coordinates(const Json& layer) {
    const bool is_line = line_kind_of(layer);
    std::vector<Json> sequences;
    int holes = 0;
    const Json* features = field(layer, "features");
    if (features == nullptr || !features->is_array()) {
        return {sequences, holes};
    }
    for (const Json& feature : *features) {
        const Json* geometry = field(feature, "geometry");
        if (geometry == nullptr || !geometry->is_object()) continue;
        const std::string gtype = str_of(*geometry, "type");
        const Json* coordinates = field(*geometry, "coordinates");
        if (coordinates == nullptr || coordinates->empty()
            || !coordinates->is_array())
            continue;
        if (is_line) {
            std::vector<const Json*> parts;
            if (gtype == "LineString") {
                parts.push_back(coordinates);
            } else if (gtype == "MultiLineString") {
                for (const Json& part : *coordinates) parts.push_back(&part);
            } else {
                continue;
            }
            Json merged = Json::array();
            for (const Json* part : parts) {
                if (!part->is_array()) continue;
                for (const Json& point : *part) {
                    const Json vertex = vertex_of(point);
                    if (vertex.is_null()) continue;
                    if (!merged.empty() && merged.back() == vertex) {
                        continue;  // drop duplicated joints between parts
                    }
                    merged.push_back(vertex);
                }
            }
            if (merged.size() >= 2) sequences.push_back(std::move(merged));
        } else {
            std::vector<const Json*> polys;
            if (gtype == "Polygon") {
                polys.push_back(coordinates);
            } else if (gtype == "MultiPolygon") {
                for (const Json& poly : *coordinates) polys.push_back(&poly);
            } else {
                continue;
            }
            for (const Json* poly : polys) {
                if (!poly->is_array() || poly->empty()) continue;
                int index = 0;
                for (const Json& ring : *poly) {
                    Json points = Json::array();
                    if (ring.is_array()) {
                        for (const Json& point : ring) {
                            const Json vertex = vertex_of(point);
                            if (!vertex.is_null()) points.push_back(vertex);
                        }
                    }
                    ++index;
                    if (points.size() < 3) continue;
                    if (index == 1) {
                        // Ring closure for polygon kinds (mask /
                        // exclusion): the boundary-ring consumer requires
                        // first == last.
                        if (points.front() != points.back()) {
                            points.push_back(points.front());
                        }
                        sequences.push_back(std::move(points));
                    } else {
                        ++holes;
                    }
                }
            }
        }
    }
    return {sequences, holes};
}

// _linked_lines parity — (matched line Json*, matched_by). Lines are
// located inside document["constraint_layers"][*]["lines"].
std::pair<std::vector<Json*>, std::string> linked_lines(
    Json& document, const Json& layer, const std::string& layer_id) {
    const std::string kind_value = str_of(layer, "template");
    const std::string layer_name = str_of(layer, "name");
    std::vector<Json*> by_layer_id;
    std::vector<Json*> by_kind;
    Json* groups = field(document, "constraint_layers");
    if (groups != nullptr && groups->is_array()) {
        for (Json& group : *groups) {
            Json* lines = field(group, "lines");
            if (lines == nullptr || !lines->is_array()) continue;
            for (Json& line : *lines) {
                const Json* props = field(line, "properties");
                const Json empty = Json::object();
                const Json& p = props != nullptr ? *props : empty;
                if (str_of(p, "layer_id") == layer_id) {
                    by_layer_id.push_back(&line);
                } else if (!kind_value.empty()
                           && str_of(p, "constraint_kind") == kind_value
                           && str_of(line, "name") == layer_name) {
                    const Json* coords = field(line, "coordinates");
                    if (coords == nullptr || coords->empty()) {
                        by_kind.push_back(&line);
                    }
                }
            }
        }
    }
    if (!by_layer_id.empty()) return {by_layer_id, "layer_id"};
    if (!by_kind.empty()) return {by_kind, "constraint_kind+name"};
    return {{}, ""};
}

// _target_group parity — the group containing a matched line; else the
// first group; else a created "约束层" group appended to the document.
Json* target_group(Json& document, const std::vector<Json*>& matched) {
    Json* groups = field(document, "constraint_layers");
    if (groups != nullptr && groups->is_array()) {
        if (!matched.empty()) {
            for (Json& group : *groups) {
                Json* lines = field(group, "lines");
                if (lines == nullptr || !lines->is_array()) continue;
                for (Json& line : *lines) {
                    for (Json* m : matched) {
                        if (&line == m) return &group;
                    }
                }
            }
        }
        if (!groups->empty()) return &groups->front();
    }
    if (groups == nullptr || !groups->is_array()) {
        document["constraint_layers"] = Json::array();
        groups = &document["constraint_layers"];
    }
    Json group = Json::object();
    group["name"] = "约束层";
    group["lines"] = Json::array();
    groups->push_back(std::move(group));
    return &groups->back();
}

}  // namespace

std::string constraint_content_fingerprint(const Json& coordinates) {
    Json canonical = Json::array();
    if (coordinates.is_array()) {
        for (const Json& point : coordinates) {
            const Json vertex = vertex_of(point);
            if (vertex.is_null()) continue;
            canonical.push_back(
                Json::array({round9(vertex[0].get<double>()),
                             round9(vertex[1].get<double>())}));
        }
    }
    // json.dumps(canonical, sort_keys=True, separators=(",", ":")) —
    // arrays of numbers are key-free so ordering is already canonical.
    return domain::Sha256::of_bytes(canonical.dump());
}

Json sync_constraint_geometry(Json& document, const std::string& layer_id) {
    Json report = Json::object();
    report["ok"] = false;
    report["layer_id"] = layer_id;

    // Locate the vector layer inside user_vector_layers.
    Json* layer = nullptr;
    Json* layers = field(document, "user_vector_layers");
    if (layers != nullptr && layers->is_array()) {
        for (Json& candidate : *layers) {
            if (str_of(candidate, "id") == layer_id) {
                layer = &candidate;
                break;
            }
        }
    }
    if (layer == nullptr) {
        report["reason"] = "layer_not_found";
        return report;
    }
    const std::string kind_value = str_of(*layer, "template");
    const auto kind = constraint_kind_from_value(kind_value);
    if (!kind.has_value()) {
        report["reason"] = "not_a_constraint_layer";
        return report;
    }
    report["constraint_kind"] = *kind;

    auto [sequences, holes] = harvest_coordinates(*layer);
    if (sequences.empty()) {
        // Never wipe previously synced geometry based on an empty
        // transient state (digitizing may still be in progress).
        report["reason"] = "layer_empty";
        return report;
    }

    auto [matched, matched_by] = linked_lines(document, *layer, layer_id);
    Json* group = target_group(document, matched);
    if (group == nullptr) {
        report["reason"] = "no_constraint_group";
        return report;
    }

    Json* template_line = matched.empty() ? nullptr : matched.front();
    // Replace semantics: stale extra lines from a previous sync are
    // dropped (never accumulated), then one line per harvested sequence
    // is appended.
    Json* lines = field(*group, "lines");
    if (lines == nullptr || !lines->is_array()) {
        (*group)["lines"] = Json::array();
        lines = field(*group, "lines");
    }
    // Python keeps the matched OBJECTS alive (list identity), so stash
    // the template's payload BEFORE the replace drops the stale entries.
    Json template_copy;
    if (template_line != nullptr) template_copy = *template_line;
    Json kept = Json::array();
    for (Json& line : *lines) {
        bool stale = false;
        for (Json* m : matched) {
            if (&line == m) {
                stale = true;
                break;
            }
        }
        if (!stale) kept.push_back(line);
    }
    *lines = std::move(kept);

    const std::string layer_name = str_of(*layer, "name");
    const std::string group_horizon = str_of(*group, "target_horizon");
    const std::string kind_label =
        kind.has_value() ? constraint_kind_label(*kind) : layer_name;
    int index = 0;
    std::size_t coordinates_total = 0;
    Json all_points = Json::array();
    for (const Json& coordinates : sequences) {
        const std::string fingerprint =
            constraint_content_fingerprint(coordinates);
        Json line;
        if (index == 0 && template_line != nullptr) {
            line = template_copy;
            line["coordinates"] = coordinates;
        } else {
            line = Json::object();
            line["name"] =
                layer_name.empty() ? kind_label : layer_name;
            line["role"] =
                template_line != nullptr
                    ? str_of(template_copy, "role")
                    : std::string(
                          constraint_interpolation_role(*kind)
                              .value_or("boundary"));
            line["target_horizon"] =
                template_line != nullptr
                    ? str_of(template_copy, "target_horizon")
                    : group_horizon;
            Json props = Json::object();
            props["layer_id"] = layer_id;
            props["constraint_kind"] = *kind;
            props["feature_index"] = index;
            line["properties"] = std::move(props);
            line["coordinates"] = coordinates;
        }
        Json* props = field(line, "properties");
        if (props == nullptr || !props->is_object()) {
            line["properties"] = Json::object();
            props = field(line, "properties");
        }
        (*props)["layer_id"] = layer_id;
        (*props)["constraint_kind"] = *kind;
        (*props)["content_fingerprint"] = fingerprint;
        lines->push_back(std::move(line));
        for (const Json& point : coordinates) all_points.push_back(point);
        coordinates_total += coordinates.size();
        ++index;
    }

    report["ok"] = true;
    report["matched_by"] =
        matched_by.empty() ? "created_new_line" : matched_by;
    report["lines_synced"] = static_cast<int>(sequences.size());
    report["features_harvested"] = static_cast<int>(sequences.size());
    report["interior_rings_skipped"] = holes;
    report["coordinates_total"] = static_cast<int>(coordinates_total);
    report["content_fingerprint"] =
        constraint_content_fingerprint(all_points);
    return report;
}

}  // namespace pwb::ui_composite
