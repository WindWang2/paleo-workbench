#pragma once

// UI-14 — ViewCoordinationController Qt-free core
// (view_coordination.py parity).
//
// Routes SelectionBus updates into the live views. The Python page/shell
// objects become optional callable sinks the Qt shell binds — a missing
// sink is a no-op, a throwing sink logs at debug and stays non-fatal,
// exactly like the Python getattr/try discipline. All cross-view echo
// guards (source tags, changed-field-only routing, duplicate-publish
// drops, emit=False map highlight) live here.

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

#include <pwb/ui_controllers/catalog_api.hpp>
#include <pwb/ui_controllers/coordinate_hub_api.hpp>
#include <pwb/ui_controllers/selection_bus.hpp>

namespace pwb::ui_controllers {

// viz.joint_well_parsers.parse_td_table parity — returns (md_m, twt_ms)
// pairs, or nullopt when the file is unusable. A seam because the parser
// is unported; bind_project keeps the skip-on-failure contract.
using TimeDepthParseFn =
    std::function<std::optional<std::vector<std::pair<double, double>>>(
        const std::filesystem::path& table_path, const std::string& well_name)>;

class ViewCoordinationCore {
public:
    // Source tags (ViewCoordinationController.SOURCE_* parity).
    static constexpr const char* SOURCE_MAP = "project_well_map";
    static constexpr const char* SOURCE_3D = "geomodel_3d";
    static constexpr const char* SOURCE_WELL_LOG = "well_log_prediction";
    static constexpr const char* SOURCE_SEISMIC = "seismic_cursor";
    static constexpr const char* SOURCE_WORKSTATION = "workstation_explorer";
    static constexpr const char* SOURCE_DATA_PAGE = "data_page";
    static constexpr const char* SOURCE_INSPECTOR = "inspector";
    static constexpr const char* SOURCE_SEISMIC_PANEL = "seismic_panel";
    static constexpr const char* SOURCE_TASK = "task_panel";
    static constexpr const char* SOURCE_STAGE = "mapping_stage";

    // monotonic_ms: the 30 ms link-cursor throttle + 120 ms dock depth
    // gate clock (injectable — tests drive time deterministically).
    explicit ViewCoordinationCore(SelectionBus& bus, CoordinateHubApi* hub,
                                  std::function<double()> monotonic_ms = nullptr);

    SelectionBus& bus() const { return bus_; }

    // ---- routing subscription ---------------------------------------------
    // The Qt shell connects the bus (or a QObject adapter) to this. Every
    // SelectionBus update calls through — changed-field-only routing lives
    // inside (SelectionContext.selection_changed parity).
    void on_selection_changed(const SelectionState& selection);
    void attach_to_bus();   // subscribes on_selection_changed to the bus

    // ---- scenario sinks (all optional; set_*_sink parity) ------------------
    void set_seismic_sink(
        std::function<void(int il, int xl, std::optional<double> twt)> sink);
    void set_spatial_cursor_sink(std::function<void(double x, double y)> sink);
    void set_seismic_focus_sink(
        std::function<void(int il, int xl, double twt)> sink);
    void set_horizon_sink(std::function<void(std::string horizon_id)> sink);
    void set_well_dock_sink(std::function<void(std::string well_name)> sink);
    void set_section_cursor_sink(std::function<void(std::string well_name)> sink);
    void set_link_cursor_sink(
        std::function<void(std::optional<std::string> well_name,
                           std::optional<double> md_m)> sink);
    // Page-side sinks the Qt shell binds to the live pages:
    //   well_log_page.set_selected_well / geomodel_page.highlight_well /
    //   map_page.select_well(emit=False).
    void set_well_log_select_sink(
        std::function<void(std::string well_name)> sink);
    void set_geomodel_highlight_sink(
        std::function<void(std::string well_id)> sink);
    void set_map_select_well_sink(
        std::function<void(std::string well_id)> sink);

    // ---- project lifecycle -------------------------------------------------
    // bind_project(project_root): registers wells (name↔id index, surface
    // coords, KB/TD, optional metadata.survey_stations), pushes the first
    // parseable survey's bin grid, and parses time_depth assets into hub
    // calibrations via parse_td (nullptr → calibration step skipped).
    // catalog may be nullptr — entity-linked resolution then degrades to
    // legacy resources only.
    void bind_project(const domain::Json& project_root,
                      CatalogPortApi* catalog = nullptr,
                      const TimeDepthParseFn& parse_td = nullptr);
    void clear_project();

    // resolve_well_key(value) -> (canonical_name | nullopt, entity_id | nullopt).
    std::pair<std::optional<std::string>, std::optional<std::string>>
    resolve_well_key(const std::string& value) const;

    // ---- publishing --------------------------------------------------------
    void publish_well_selection(const std::string& well_id,
                                const std::string& source);
    void publish_seismic_cursor(int il, int xl, double twt);
    void publish_horizon_selection(const std::string& horizon_id,
                                   const std::string& source);
    void publish_fault_selection(const std::string& fault_id,
                                 const std::string& source);
    void publish_interpretation_selection(const std::string& interpretation_id,
                                          const std::string& source);
    void publish_layer_selection(const std::string& layer_id,
                                 const std::string& source);
    void publish_active_layer(const std::optional<std::string>& layer_id,
                              const std::string& source);
    void publish_edit_target(const std::optional<std::string>& layer_id,
                             const std::string& source);
    void publish_asset_selection(
        const std::optional<std::string>& asset_id,
        const std::optional<std::string>& version_id,
        const std::string& source);
    void publish_survey_selection(const std::optional<std::string>& survey_id,
                                  const std::string& source);
    void publish_task_selection(const std::optional<std::string>& task_id,
                                const std::string& source);
    void publish_stage(const std::optional<std::string>& stage,
                       const std::string& source);
    // Calibration-gated well-log depth cursor (scenario C). Returns false
    // when no time-depth authority covers the depth — never guesses.
    bool publish_depth_cursor(const std::string& well_id, double md,
                              const std::string& source);
    // Map-cursor → correlation-section well indicator; "" clears once.
    void publish_section_cursor(const std::string& well_name,
                              const std::string& source);

    // ---- producer hooks (Qt shell forwards panel signals) ------------------
    void on_well_log_task_selected(const std::string& well_name);
    void on_well_depth_cursor(const std::string& well_name, double md);
    // attach_well_dock_panel parity — the 120 ms republish gate lives here.
    void on_dock_depth_cursor(const std::string& well_name, double md);

    // Test/introspection surface.
    const std::set<std::string>& bound_well_ids() const {
        return bound_well_ids_;
    }

private:
    void route_well_selection_(const std::string& well_id,
                               const std::optional<std::string>& source);
    void route_seismic_cursor_(const SeismicCursorState& cursor);
    void route_horizon_selection_(const std::string& horizon_id,
                                  const std::optional<std::string>& source);
    bool locate_well_in_seismic_(const std::string& well_id);
    void throttled_link_cursor_write_(const std::string& well_id, double md);
    void clear_link_cursor_once_(
        const std::optional<std::string>& well_id = std::nullopt);
    int register_time_depth_calibrations_(const domain::Json& project_root,
                                          CatalogPortApi* catalog,
                                          const TimeDepthParseFn& parse_td);
    void update_bus_custom_attributes_(
        const std::map<std::string, domain::Json>& attrs);
    double now_ms_() const;

    SelectionBus& bus_;
    CoordinateHubApi* hub_;
    std::function<double()> monotonic_ms_;

    SelectionState last_snapshot_;
    std::set<std::string> bound_well_ids_;
    std::map<std::string, std::string> well_name_by_id_;
    std::map<std::string, std::string> well_id_by_name_;

    std::function<void(int, int, std::optional<double>)> seismic_sink_;
    std::function<void(double, double)> spatial_cursor_sink_;
    std::function<void(int, int, double)> seismic_focus_sink_;
    std::function<void(std::string)> horizon_sink_;
    std::function<void(std::string)> well_dock_sink_;
    std::function<void(std::string)> section_cursor_sink_;
    std::function<void(std::optional<std::string>, std::optional<double>)>
        link_cursor_sink_;
    std::function<void(std::string)> well_log_select_sink_;
    std::function<void(std::string)> geomodel_highlight_sink_;
    std::function<void(std::string)> map_select_well_sink_;

    bool link_cursor_set_ = false;
    bool section_cursor_set_ = false;
    std::string section_cursor_last_;
    std::optional<double> link_cursor_last_write_ms_;
    std::optional<double> dock_depth_last_pub_ms_;
};

}  // namespace pwb::ui_controllers
