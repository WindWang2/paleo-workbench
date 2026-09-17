#pragma once

// CONV-01 — Qt-free orchestration of the frozen mapping_kernel behind the
// platform's 地质因子图 action: well records -> extract_factors ->
// interpolate_factor (IDW/kriging) -> marching-squares contours ->
// facies polygonization -> GeoJSON feature arrays. The QgsVectorLayer
// materialization lives in the MainWindow wiring layer; this file carries no
// Qt/QGIS types so the whole chain stays oracle-verifiable against the
// Python product (tests/cpp/platform/fixtures/map_pipeline_oracle.json,
// frozen by tools/oracle/generate_map_pipeline_fixtures.py).

#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::application {

using pwb::domain::Json;

struct MapPipelineRequest {
    std::string factor_name;          // e.g. "孔隙度" (alias resolution is
                                      // the extract kernel's job)
    std::string target_horizon;
    std::optional<std::string> unit;  // nullopt -> FACTOR_DEFAULTS lookup
    std::string crs;                  // "" = undeclared (honest planar path)
    std::string method = "idw";       // idw | kriging | ordinary_kriging | ok
    int grid_n = 30;
    double power = 2.0;
    int min_neighbors = 1;
    std::optional<double> search_radius;
    // Empty vectors mean "Python None" (product defaults); the Python
    // explicit-empty-list corner (sorted(set([]))) is not expressible here
    // and unreachable from the dialog.
    std::vector<double> contour_levels;    // empty -> nice ladder (target 7)
    std::vector<double> class_thresholds;  // empty -> span 1/3-2/3 defaults
    std::vector<std::string> facies_names; // empty -> Python default names
};

struct MapPipelineOutcome {
    bool ok = false;
    std::string error;  // exact kernel/validate message on failure (Python
                        // ValueError text parity)
    // GeoJSON Feature arrays with the SAME property contract as the Python
    // geological_pipeline layer builders (contour: level/label_text/
    // is_index_contour/length/is_closed/factor/unit; polygon: facies_id/
    // facies_name/facies/color/area/area_unit/area_percent/mean_value
    // [+ area_approx_m2 under a geographic CRS]).
    Json contour_features = Json::array();
    Json polygon_features = Json::array();
    // Extract diagnostics + the interpolated grid + statistics +
    // distance-policy annotation. No catalog publication here; the oracle
    // test reconciles the pinned stages through this object.
    Json diagnostics = Json::object();
};

// records: JSON array of well records in the same shape the Python service
// builds from well tables / domain wells (well_id/name/x/y + factor value
// under the factor name, "value", or aliases).
MapPipelineOutcome run_map_pipeline(const Json& records,
                                    const MapPipelineRequest& request);

}  // namespace pwb::application
