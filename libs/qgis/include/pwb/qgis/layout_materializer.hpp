#pragma once

// layout_materializer — the single element→native-item engine shared by
// native template instantiation and legacy Composition migration
// (docs/development/qgis-native-layout-convergence/01 §"模块落点").
//
// Both flows produce the same input shape (LayoutElementSpec — the retired
// composer's declarative element vocabulary) and both land on a real,
// persistent QgsPrintLayout. There is deliberately *no* second element
// model: after materialization the QgsLayout items themselves are the only
// geometry/state authority; Paleo semantics ride on item slots
// (layout_slots.hpp).

#include <pwb/domain/json.hpp>

#include <QList>

#include <array>
#include <functional>
#include <optional>
#include <string>
#include <vector>

class QgsMapLayer;
class QgsPrintLayout;

namespace pwb::qgis {

// The retired composer element vocabulary (element_type + mm geometry +
// z-order + properties). `element_id` keeps the legacy/document identity.
struct LayoutElementSpec {
    std::string element_type;
    std::string element_id;
    double x_mm = 0.0;
    double y_mm = 0.0;
    double width_mm = 0.0;
    double height_mm = 0.0;
    long long z_index = 0;
    bool visible = true;
    bool locked = false;
    domain::Json properties = domain::Json::object();
};

struct MaterializeContext {
    // Ordered top-first map layers (e.g. MapSession::layerIdsTopFirst
    // resolved to QgsMapLayer*). Empty → map items keep QGIS defaults.
    std::function<QList<QgsMapLayer*>()> layers_provider;
    // Map extent override [xmin, ymin, xmax, ymax] in the map CRS; when
    // absent the union of the provided layers' extents is used.
    std::optional<std::array<double, 4>> map_extent;
    std::string map_crs;  // authid override ("" = project CRS)
    std::string template_id;
    std::string template_category;
};

struct MaterializeReport {
    int items_created = 0;
    // Unknown legacy element types (each materialized as an honest
    // placeholder slot item — never silently dropped).
    std::vector<std::string> unknown_types;
    std::vector<std::string> warnings;
};

// Materializes `elements` (in z_index order) onto `layout`. The layout's
// page must already be sized. Grid elements attach to the main map item.
// Undo commands are blocked during the bulk build; the undo stack is clean
// afterwards (fresh document, nothing to undo).
MaterializeReport materialize_elements(QgsPrintLayout& layout,
                                       const std::vector<LayoutElementSpec>& elements,
                                       const MaterializeContext& context);

}  // namespace pwb::qgis
