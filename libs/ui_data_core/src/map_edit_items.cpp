#include "pwb/ui_data_core/map_edit_items.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <stdexcept>
#include <utility>

namespace pwb::ui_data_core {
namespace {

// Python list indexing — negative indices count from the end; out of range
// throws out_of_range (IndexError parity).
int python_index(int index, std::size_t size) {
    const long long n = static_cast<long long>(size);
    long long i = index;
    if (i < 0) {
        i += n;
    }
    if (i < 0 || i >= n) {
        throw std::out_of_range("list index out of range");
    }
    return static_cast<int>(i);
}

// [float(p[0]), float(p[1])] for each point — malformed entries raise.
MapRing strict_ring(const domain::Json& coordinates) {
    if (!coordinates.is_array()) {
        throw std::invalid_argument(
            "coordinates must be a list of [x, y] points");
    }
    MapRing ring;
    for (const auto& p : coordinates) {
        if (!p.is_array() || p.size() < 2) {
            throw std::out_of_range("point must have >= 2 elements");
        }
        const auto x = json_float(p[0]);
        const auto y = json_float(p[1]);
        if (!x.has_value() || !y.has_value()) {
            throw std::invalid_argument("non-numeric point member");
        }
        ring.push_back({*x, *y});
    }
    return ring;
}

// set_property("name", value) — "" if None else str(value).
std::string name_value(const domain::Json& value) {
    return value.is_null() ? "" : python_str(value);
}

domain::Json named_property(std::string_view key, const std::string& name,
                            const std::string& topology_status) {
    if (key == "name") {
        return domain::Json(name);
    }
    if (key == "topology_status") {
        return domain::Json(topology_status);
    }
    return domain::Json(nullptr);
}

bool set_named_property(std::string_view key, const domain::Json& value,
                        std::string& name, std::string& topology_status) {
    if (key == "name") {
        name = name_value(value);
        return true;
    }
    if (key == "topology_status") {
        topology_status = json_truthy(value) ? python_str(value) : kTopologyOk;
        return true;
    }
    return false;
}

}  // namespace

void FeatureItemBase::set_topology_status(const domain::Json& status) {
    topology_status = json_truthy(status) ? python_str(status) : kTopologyOk;
}

// ---------------------------------------------------------------------------
// FaciesPolygonModel
// ---------------------------------------------------------------------------

FaciesPolygonModel::FaciesPolygonModel(
    std::string feature_id, const domain::Json& coordinates, std::string name,
    const domain::Json& style, const domain::Json& extras,
    std::string geometry_type, const domain::Json* geometry_coordinates) {
    this->feature_id = std::move(feature_id);
    kind = "facies";
    topology_status = kTopologyOk;
    this->name = std::move(name);
    this->style = style.is_object() ? style : domain::Json::object();
    this->extras = extras.is_object() ? extras : domain::Json::object();
    const domain::Json& source =
        geometry_coordinates != nullptr ? *geometry_coordinates : coordinates;
    domain::Json raw = domain::Json::object();
    raw["geometry_type"] = geometry_type;
    raw["geometry"] = domain::Json::object();
    raw["geometry"]["type"] = geometry_type;
    raw["geometry"]["coordinates"] = source;
    auto canonical = canonical_facies_geometry(raw);
    this->geometry_type = std::move(canonical.first);
    polygons = std::move(canonical.second);
}

MapRing FaciesPolygonModel::coordinates() const {
    if (polygons.empty() || polygons.front().empty()) {
        return {};
    }
    return polygons.front().front();
}

bool FaciesPolygonModel::has_complex_geometry() const {
    return geometry_type != "Polygon" || polygons.size() != 1 ||
           polygons.front().empty() || polygons.front().size() != 1;
}

domain::Json FaciesPolygonModel::geometry_coordinates() const {
    if (geometry_type == "Polygon") {
        return polygons.empty() ? domain::Json::array()
                                : polygon_to_json(polygons.front());
    }
    return multipolygon_to_json(polygons);
}

std::vector<MapRing> FaciesPolygonModel::all_rings() const {
    std::vector<MapRing> out;
    for (const auto& polygon : polygons) {
        for (const auto& ring : polygon) {
            out.push_back(ring);
        }
    }
    return out;
}

std::vector<FaciesPolygonModel::RingAddress>
FaciesPolygonModel::iter_ring_addresses() const {
    std::vector<RingAddress> out;
    for (std::size_t part = 0; part < polygons.size(); ++part) {
        for (std::size_t ring = 0; ring < polygons[part].size(); ++ring) {
            out.push_back(RingAddress{static_cast<int>(part),
                                      static_cast<int>(ring),
                                      polygons[part][ring]});
        }
    }
    return out;
}

MapRing FaciesPolygonModel::ring_coordinates(int part_index,
                                             int ring_index) const {
    // try: polygons[int(part)][int(ring)] except (IndexError, TypeError,
    // ValueError) → []
    try {
        const int part = python_index(part_index, polygons.size());
        const int ring = python_index(ring_index, polygons[part].size());
        return polygons[part][ring];
    } catch (...) {
        return {};
    }
}

void FaciesPolygonModel::set_ring_coordinates(
    int part_index, int ring_index, const domain::Json& coordinates) {
    domain::Json raw = domain::Json::object();
    raw["geometry_type"] = "Polygon";
    raw["coordinates"] = coordinates;
    auto canonical = canonical_facies_geometry(raw);
    if (canonical.second.empty()) {
        return;
    }
    const int part = python_index(part_index, polygons.size());
    const int ring = python_index(ring_index, polygons[part].size());
    polygons[part][ring] = canonical.second.front().front();
    geometry_dirty = true;  // _refresh_path + setPos(0, 0)
}

void FaciesPolygonModel::set_coordinates(const domain::Json& coordinates) {
    domain::Json raw = domain::Json::object();
    raw["geometry_type"] = "Polygon";
    raw["coordinates"] = coordinates;
    auto canonical = canonical_facies_geometry(raw);
    if (canonical.second.empty()) {
        return;
    }
    if (polygons.empty()) {
        polygons = std::move(canonical.second);
    } else if (polygons.front().empty()) {
        polygons.front() = std::move(canonical.second.front());
    } else {
        polygons.front().front() = canonical.second.front().front();
    }
    geometry_dirty = true;
}

void FaciesPolygonModel::translate_by(double dx, double dy) {
    for (auto& polygon : polygons) {
        for (auto& ring : polygon) {
            for (auto& point : ring) {
                point[0] += dx;
                point[1] += dy;
            }
        }
    }
    geometry_dirty = true;
}

domain::Json FaciesPolygonModel::get_property(std::string_view key) const {
    return named_property(key, name, topology_status);
}

void FaciesPolygonModel::set_property(std::string_view key,
                                      const domain::Json& value) {
    set_named_property(key, value, name, topology_status);
}

domain::Json FaciesPolygonModel::to_record() const {
    domain::Json rec = domain::Json::object();
    rec["id"] = feature_id;
    rec["kind"] = kind;
    rec["name"] = name;
    rec["coordinates"] = compact_facies_coordinates(geometry_type, polygons);
    rec["geometry_type"] = geometry_type;
    rec["geometry"] = domain::Json::object();
    rec["geometry"]["type"] = geometry_type;
    rec["geometry"]["coordinates"] = geometry_coordinates();
    rec["style"] = style;
    rec["topology_status"] = topology_status;
    for (const char* key : {"facies", "probability", "region_id",
                          "properties"}) {
        const auto it = extras.find(key);
        if (it != extras.end() && !it->is_null()) {
            rec[key] = *it;
        }
    }
    if (rec.find("facies") == rec.end() && !name.empty()) {
        rec["facies"] = name;
    }
    return rec;
}

// ---------------------------------------------------------------------------
// WellPointModel
// ---------------------------------------------------------------------------

WellPointModel::WellPointModel(std::string feature_id, double x, double y,
                               std::string name, double radius)
    : x(x), y(y), radius(radius), name(std::move(name)) {
    this->feature_id = std::move(feature_id);
    kind = "well";
    topology_status = kTopologyOk;
}

void WellPointModel::translate_by(double dx, double dy) {
    x += dx;
    y += dy;
    geometry_dirty = true;  // rect update + setPos(0, 0)
}

domain::Json WellPointModel::get_property(std::string_view key) const {
    return named_property(key, name, topology_status);
}

void WellPointModel::set_property(std::string_view key,
                                  const domain::Json& value) {
    set_named_property(key, value, name, topology_status);
}

domain::Json WellPointModel::to_record() const {
    domain::Json rec = domain::Json::object();
    rec["id"] = feature_id;
    rec["kind"] = kind;
    rec["name"] = name;
    rec["coordinates"] = domain::Json::array({x, y});
    rec["topology_status"] = topology_status;
    return rec;
}

// ---------------------------------------------------------------------------
// LineModel
// ---------------------------------------------------------------------------

LineModel::LineModel(std::string feature_id, MapRing coordinates,
                     std::string name)
    : points(std::move(coordinates)), name(std::move(name)) {
    this->feature_id = std::move(feature_id);
    kind = "line";
    topology_status = kTopologyOk;
}

MapRing LineModel::coordinates() const {
    return points;
}

void LineModel::set_coordinates(const domain::Json& coordinates) {
    points = strict_ring(coordinates);
    geometry_dirty = true;  // _rebuild_path + setPos(0, 0)
}

void LineModel::translate_by(double dx, double dy) {
    for (auto& p : points) {
        p[0] += dx;
        p[1] += dy;
    }
    geometry_dirty = true;
}

domain::Json LineModel::get_property(std::string_view key) const {
    return named_property(key, name, topology_status);
}

void LineModel::set_property(std::string_view key,
                             const domain::Json& value) {
    set_named_property(key, value, name, topology_status);
}

domain::Json LineModel::to_record() const {
    domain::Json rec = domain::Json::object();
    rec["id"] = feature_id;
    rec["kind"] = kind;
    rec["name"] = name;
    rec["coordinates"] = ring_to_json(points);
    rec["topology_status"] = topology_status;
    return rec;
}

// ---------------------------------------------------------------------------
// LabelModel
// ---------------------------------------------------------------------------

LabelModel::LabelModel(std::string feature_id, double x, double y,
                       std::string text, std::string name)
    : x(x), y(y) {
    this->feature_id = std::move(feature_id);
    kind = "label";
    topology_status = kTopologyOk;
    const std::string display = !text.empty() ? text : name;
    this->text = display;
    this->name = !name.empty() ? name : display;
}

void LabelModel::translate_by(double dx, double dy) {
    x += dx;
    y += dy;
    geometry_dirty = true;  // setPos(x, y)
}

domain::Json LabelModel::get_property(std::string_view key) const {
    if (key == "text") {
        return domain::Json(text);
    }
    return named_property(key, name, topology_status);
}

void LabelModel::set_property(std::string_view key,
                              const domain::Json& value) {
    if (key == "text") {
        text = name_value(value);
        return;  // setText on the shell item
    }
    set_named_property(key, value, name, topology_status);
}

domain::Json LabelModel::to_record() const {
    domain::Json rec = domain::Json::object();
    rec["id"] = feature_id;
    rec["kind"] = kind;
    rec["name"] = name;
    rec["text"] = text;
    rec["coordinates"] = domain::Json::array({x, y});
    rec["topology_status"] = topology_status;
    return rec;
}

// ---------------------------------------------------------------------------
// FeatureModel visitors
// ---------------------------------------------------------------------------

const FeatureItemBase& feature_base(const FeatureModel& model) {
    return std::visit(
        [](const auto& m) -> const FeatureItemBase& { return m; }, model);
}

FeatureItemBase& feature_base(FeatureModel& model) {
    return std::visit([](auto& m) -> FeatureItemBase& { return m; }, model);
}

domain::Json feature_to_record(const FeatureModel& model) {
    return std::visit([](const auto& m) { return m.to_record(); }, model);
}

domain::Json feature_get_property(const FeatureModel& model,
                                  std::string_view key) {
    return std::visit([key](const auto& m) { return m.get_property(key); },
                      model);
}

void feature_set_property(FeatureModel& model, std::string_view key,
                          const domain::Json& value) {
    std::visit([&](auto& m) { m.set_property(key, value); }, model);
}

void feature_translate_by(FeatureModel& model, double dx, double dy) {
    std::visit([dx, dy](auto& m) { m.translate_by(dx, dy); }, model);
}

}  // namespace pwb::ui_data_core
