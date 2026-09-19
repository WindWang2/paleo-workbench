#pragma once

// UI-13 — QGIS engine adapter for the composite editor.
//
// Native port of the Python geometry_service / geometry_operations
// engine chain: the bridge facade in Python routes merge/split/reshape/
// validate through qgis_render_bridge (vendored QgsGeometry); here the
// same kernels are compiled into pwb_ui_composite_qgis
// (native/qgis_render_bridge/src/geometry_service.cpp — GeoJSON string
// in → GeoJSON string out, QgsGeometry::asJson wire).
//
// Install on a live controller via install_geometry_engine():
//   * ICompositeGeometryOps  — merge/split/valid/multipart/trim/extend/
//     reverse/simplify/smooth/offset/rotate/scale/centroid/reshape/
//     part ops (absent seam = the "no engine" honest rejection).
//   * TopologyService validator seams — GeometryValidateFn/Many (the
//     bridge geometry.validate / validate_many equivalents; entries
//     carry "message" per Python validate_records consumption).
//   * qgis_repair_geometry — GeometryRepairFn backend for
//     repair_invalid_geometry (QgsGeometry::makeValid).
//
// Link dependency: QtCore/QtGui via the QGIS SDK (QgsGeometry). The TU
// is QWidget-free — it may be used from non-UI paths.

#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/topology_service.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite::qgis {

using pwb::domain::Json;

// ---------------------------------------------------------------------------
// QgisCompositeGeometryOps
// ---------------------------------------------------------------------------

// QgsGeometry-backed ICompositeGeometryOps. Input validation/error
// messages are byte-faithful to vector_operations /
// geometry_service (ValueError → std::invalid_argument).
class QgisCompositeGeometryOps final : public ICompositeGeometryOps {
public:
    // vector_operations.merge_selected_polygons(session, ids) → new id.
    std::string merge_selected_polygons(
        VectorEditSession& session,
        const std::vector<std::string>& sorted_ids) override;
    // vector_operations.split_polygon_by_line(session, id, line) → ids.
    std::vector<std::string> split_polygon_by_line(
        VectorEditSession& session, const std::string& polygon_id,
        const VectorFeature& line_feature) override;
    // geometry_service.make_geometry_valid — Polygon/MultiPolygon only;
    // other types pass through unchanged (Python dict-in/dict-out).
    Json make_geometry_valid(const Json& geometry) override;
    // geometry_operations.multipart_to_singlepart / singlepart_to_…
    std::vector<Json> multipart_to_singlepart(
        const Json& geometry) override;
    Json singlepart_to_multipart(
        const std::vector<Json>& geometries) override;
    // geometry_operations.trim_line (intersection; ``keep`` is accepted
    // for signature parity — the Python kernel ignores it).
    Json trim_line(const Json& geometry, const Json& boundary,
                   const std::string& keep) override;
    // geometry_operations.extend_line_to_boundary — endpoint rays to the
    // boundary's first hit within max_extend; no hit keeps the tip.
    Json extend_line_to_boundary(const Json& geometry,
                                 const Json& boundary,
                                 double max_extend) override;
    // geometry_operations.reverse_geometry — pure coordinate reversal
    // (closed rings stay closed); no engine needed, kept on the seam so
    // the "no engine" gate covers it like Python's dispatch does.
    Json reverse_geometry(const Json& geometry) override;
    Json simplify(const Json& geometry, double tolerance) override;
    Json smooth(const Json& geometry, int iterations,
                double offset) override;
    Json offset_curve(const Json& geometry, double distance) override;
    // shapely affinity rotate/scale around a center (pure coordinate
    // math — degrees CCW for rotate).
    Json rotate(const Json& geometry, double angle_degrees,
                const MapPoint& origin) override;
    Json scale(const Json& geometry, double xfact, double yfact,
               const MapPoint& origin) override;
    // transform_selection center: union of geometries → centroid.
    MapPoint union_centroid(const std::vector<Json>& geoms) override;
    // native.geometry.reshape / add_part / delete_part — failure maps to
    // nullopt (the Python native-surface returns None on rejection).
    std::optional<Json> reshape(const Json& target,
                                const Json& line) override;
    std::optional<Json> add_part(const Json& target,
                                 const Json& part) override;
    std::optional<Json> delete_part(const Json& geometry,
                                    int part_index) override;
};

// ---------------------------------------------------------------------------
// TopologyService validator seams
// ---------------------------------------------------------------------------

// GeometryValidateFn: GeoJSON geometry → validity message list
// ([] = valid). Parse failure contributes one message — the Python
// bridge path surfaces invalid input as an error entry, never a throw.
std::vector<std::string> qgis_validate_geometry(const Json& geometry);
// GeometryValidateManyFn: batch form, one message list per input.
std::vector<std::vector<std::string>> qgis_validate_geometries(
    const std::vector<Json>& geometries);

// GeometryRepairFn backend: QgsGeometry::makeValid over polygonal
// input; non-polygonal / unparseable input returns unchanged (the
// repair_invalid_geometry contract).
Json qgis_repair_geometry(const Json& geometry);

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------

// composite_document bridge wiring parity: installs the geometry ops +
// both topology validator seams on a live controller. The checker
// run/fix seams stay host-injected (they consume the mirror-layer
// check service, not free-standing QgsGeometry calls).
void install_geometry_engine(CompositeEditController& controller);

}  // namespace pwb::ui_composite::qgis
