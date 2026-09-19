// map_edit_items.py port — the Qt-free state of the feature graphics
// items (FeatureItemMixin surface: identity, properties, topology status,
// to_record, geometry access/mutation). QGraphicsItem painting stays in
// the Qt shell; these models hold exactly the data the shells render.
#pragma once

#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace pwb::ui_data_core {

// Default well marker radius / vertex handle half-size (scene units).
inline constexpr double kWellRadius = 0.4;
inline constexpr double kVertexHandleHalf = 0.35;

inline constexpr const char* kTopologyOk = "ok";
inline constexpr const char* kTopologyWarning = "warning";

// FeatureItemMixin — shared identity / export surface.
struct FeatureItemBase {
    std::string feature_id;
    std::string kind;
    std::string topology_status = kTopologyOk;

    // set_topology_status(status) — str(status or "ok").
    void set_topology_status(const domain::Json& status);
    void set_topology_status(std::string_view status) {
        topology_status = status.empty() ? kTopologyOk : std::string(status);
    }
    // path-rebuild marker the Qt shells mirror (translate/setPos(0,0)).
    bool geometry_dirty = false;  // set by every geometry mutation
};

// FaciesPolygonItem state — canonical polygons + style/extras.
struct FaciesPolygonModel : FeatureItemBase {
    // Mirrors the Python ctor: canonicalizes
    // {"geometry_type": geometry_type,
    //  "geometry": {"type": geometry_type,
    //              "coordinates": geometry_coordinates or coordinates}}.
    FaciesPolygonModel(std::string feature_id,
                       const domain::Json& coordinates,
                       std::string name = "",
                       const domain::Json& style = domain::Json(nullptr),
                       const domain::Json& extras = domain::Json(nullptr),
                       std::string geometry_type = "Polygon",
                       const domain::Json* geometry_coordinates = nullptr);

    std::string name;
    domain::Json style = domain::Json::object();
    domain::Json extras = domain::Json::object();
    std::string geometry_type = "Polygon";
    MapMultiPolygon polygons;

    MapRing coordinates() const;           // _polygons[0][0] or []
    bool has_complex_geometry() const;
    // geometry_coordinates() — Polygon → rings of polygon 0; else polygons.
    domain::Json geometry_coordinates() const;
    std::vector<MapRing> all_rings() const;

    struct RingAddress {
        int part_index;
        int ring_index;
        MapRing points;
    };
    std::vector<RingAddress> iter_ring_addresses() const;
    MapRing ring_coordinates(int part_index, int ring_index) const;
    void set_ring_coordinates(int part_index, int ring_index,
                              const domain::Json& coordinates);
    // Replace the editable first outer ring while preserving other rings.
    void set_coordinates(const domain::Json& coordinates);
    void translate_by(double dx, double dy);

    // get_property(key) → Json (name|topology_status; else null).
    domain::Json get_property(std::string_view key) const;
    void set_property(std::string_view key, const domain::Json& value);
    domain::Json to_record() const;
};

// WellPointItem state — center + radius.
struct WellPointModel : FeatureItemBase {
    WellPointModel(std::string feature_id, double x, double y,
                   std::string name = "", double radius = kWellRadius);

    double x = 0.0;
    double y = 0.0;
    double radius = kWellRadius;
    std::string name;

    void translate_by(double dx, double dy);
    domain::Json get_property(std::string_view key) const;
    void set_property(std::string_view key, const domain::Json& value);
    domain::Json to_record() const;
};

// LineItem state — polyline points.
struct LineModel : FeatureItemBase {
    LineModel(std::string feature_id, MapRing coordinates,
              std::string name = "");

    MapRing points;
    std::string name;

    MapRing coordinates() const;
    void set_coordinates(const domain::Json& coordinates);
    void translate_by(double dx, double dy);
    domain::Json get_property(std::string_view key) const;
    void set_property(std::string_view key, const domain::Json& value);
    domain::Json to_record() const;
};

// LabelItem state — anchored text.
struct LabelModel : FeatureItemBase {
    LabelModel(std::string feature_id, double x, double y,
               std::string text = "", std::string name = "");

    double x = 0.0;
    double y = 0.0;
    std::string text;
    std::string name;

    void translate_by(double dx, double dy);
    domain::Json get_property(std::string_view key) const;
    void set_property(std::string_view key, const domain::Json& value);
    domain::Json to_record() const;
};

// One feature item model (the FeatureItemMixin sum type).
using FeatureModel = std::variant<FaciesPolygonModel, WellPointModel,
                                  LineModel, LabelModel>;

const FeatureItemBase& feature_base(const FeatureModel& model);
FeatureItemBase& feature_base(FeatureModel& model);
domain::Json feature_to_record(const FeatureModel& model);
domain::Json feature_get_property(const FeatureModel& model,
                                  std::string_view key);
void feature_set_property(FeatureModel& model, std::string_view key,
                          const domain::Json& value);
void feature_translate_by(FeatureModel& model, double dx, double dy);

}  // namespace pwb::ui_data_core
