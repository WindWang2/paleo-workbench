#pragma once

// UI-14 — CoordinateTransformHub seam.
//
// Python resolves the process-global hub via
// viz.coordinate_transform_hub.get_coordinate_hub(). There is no C++ hub
// yet (viz_engine is unported), so ViewCoordinationCore takes the exact
// surface the controller calls as an abstract seam; the real adapter
// lands with the viz-engine slice. Every method Python calls into a
// try/except(Exception → log-and-continue) throws std::exception here —
// the controller keeps the same non-fatal discipline.

#include <optional>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_controllers {

// viz.coordinate_hub.TimeDepthCalibration parity (producer-side record).
// pairs are (md_m, twt_ms); the hub rejects non-monotonic inputs itself.
struct TimeDepthCalibrationSlice {
    std::string well_name;
    std::vector<std::pair<double, double>> pairs;  // (md_m, twt_ms)
    std::string provenance;                        // e.g. "td-table:foo.txt"
    std::optional<std::string> version_id;
    std::optional<std::string> fingerprint;
    domain::Json metadata = domain::Json::object();
};

// Calibration readback (cal.twt_to_md(twt) + cal.provenance parity).
struct CalibratedMd {
    double md = 0.0;
    std::string provenance;
};

// A registered well's optional deviated-trajectory stations (MD, inc, az).
using WellStations = std::vector<std::tuple<double, double, double>>;

class CoordinateHubApi {
public:
    virtual ~CoordinateHubApi() = default;

    // ---- bind_project / clear_project -------------------------------------
    virtual void register_well(
        const std::string& well_id, double x, double y, double elevation,
        double total_depth_m,
        const std::optional<WellStations>& stations) = 0;
    virtual int clear_all_wells() = 0;
    virtual void reset_seismic_grid() = 0;
    virtual void configure_seismic_grid(
        std::pair<double, double> origin,
        std::pair<double, double> il_step,
        std::pair<double, double> xl_step,
        int il_min, int xl_min) = 0;
    virtual void set_time_depth_calibration(
        const TimeDepthCalibrationSlice& calibration) = 0;

    // ---- transforms (all may throw — non-fatal like the Python callers) ---
    // seismic_to_well(il, xl, twt) -> (well_id, md | None); empty well_id
    // means no registered well within radius.
    virtual std::pair<std::string, std::optional<double>> seismic_to_well(
        int il, int xl, double twt) = 0;
    // time_depth_calibration(well).twt_to_md(twt) + provenance; nullopt
    // when the well has no calibration or twt is outside its range.
    virtual std::optional<CalibratedMd> calibrated_md(
        const std::string& well_id, double twt) = 0;
    virtual double velocity_assumption() const = 0;
    // well_depth_to_map(well, md) -> (x, y, tvd).
    virtual std::tuple<double, double, double> well_depth_to_map(
        const std::string& well_id, double md) = 0;
    // map_to_seismic_xy(x, y) -> (il, xl).
    virtual std::pair<double, double> map_to_seismic_xy(
        double x, double y) = 0;
    // seismic_to_map_xy(il, xl) -> (x, y).
    virtual std::pair<double, double> seismic_to_map_xy(int il, int xl) = 0;
    // well_md_to_seismic_cursor(well, md) -> (il, xl, twt); nullopt when no
    // valid time-depth calibration covers the depth (the refusal case).
    virtual std::optional<std::tuple<double, double, double>>
    well_md_to_seismic_cursor(const std::string& well_id, double md) = 0;
};

}  // namespace pwb::ui_controllers
