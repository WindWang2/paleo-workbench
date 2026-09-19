#pragma once

// UI-14 — Qt-free SelectionContext port (viz_engine/selection_context.py).
//
// The shared publish/subscribe selection bus the ViewCoordination
// controller routes through: publishers call publish_* (or update with a
// patch); subscribers are plain callbacks. `source_widget_id` tracking +
// `was_published_by` give the echo-suppression ViewCoordination relies on
// (a sink skips the event it itself published).
//
// SelectionState/SelectionPatch carry every published field; unset
// optionals in a patch mean "leave unchanged", set optionals assign —
// including an explicit null (e.g. seismic_cursor = nullopt clears the
// previous cursor, per _on_seismic_cursor_changed's no-authority branch).

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_controllers {

// viz_engine.selection_context.SeismicCursor parity.
struct SeismicCursorState {
    double inline_coord = 0.0;
    double crossline_coord = 0.0;
    double time_depth = 0.0;

    bool operator==(const SeismicCursorState&) const = default;
};

// viz_engine.selection_context.SpatialCursor parity.
struct SpatialCursorState {
    double x = 0.0, y = 0.0;
    std::optional<std::string> crs;

    bool operator==(const SpatialCursorState&) const = default;
};

// viz_engine.selection_context.MapExtent parity.
struct MapExtentState {
    double xmin = 0.0, ymin = 0.0, xmax = 0.0, ymax = 0.0;
    std::optional<std::string> crs;

    bool operator==(const MapExtentState&) const = default;
};

struct SelectionState {
    std::optional<std::string> active_well_id;
    std::set<std::string> selected_well_ids;
    std::optional<std::pair<double, double>> depth_range;
    std::optional<SeismicCursorState> seismic_cursor;
    std::optional<std::string> active_horizon_id;
    std::optional<std::string> active_fault_id;
    std::optional<std::string> active_interpretation_id;
    std::optional<SpatialCursorState> spatial_cursor;
    // publish_depth_cursor parity: (well_name, md_m) — the well names the
    // crosshair, the bus's cross-view key stays the well name (#1029).
    std::optional<std::pair<std::string, double>> depth_cursor;
    std::optional<std::string> selected_layer_id;
    std::optional<std::string> active_layer_id;
    std::optional<std::string> edit_target_layer_id;
    std::optional<std::string> selected_asset_id;
    std::optional<std::string> selected_version_id;
    std::optional<std::string> active_survey_id;
    std::optional<std::string> active_task_id;
    std::optional<std::string> workflow_stage;
    std::optional<MapExtentState> map_extent;
    std::optional<std::string> source_widget_id;
    double timestamp = 0.0;
    std::map<std::string, domain::Json> custom_attributes;
};

// update(**kwargs) parity — only the fields a publisher sets are touched.
struct SelectionPatch {
    std::optional<std::optional<std::string>> active_well_id;
    std::optional<std::set<std::string>> selected_well_ids;
    std::optional<std::optional<std::pair<double, double>>> depth_range;
    std::optional<std::optional<SeismicCursorState>> seismic_cursor;
    std::optional<std::optional<std::string>> active_horizon_id;
    std::optional<std::optional<std::string>> active_fault_id;
    std::optional<std::optional<std::string>> active_interpretation_id;
    std::optional<std::optional<SpatialCursorState>> spatial_cursor;
    std::optional<std::optional<std::pair<std::string, double>>> depth_cursor;
    std::optional<std::optional<std::string>> selected_layer_id;
    std::optional<std::optional<std::string>> active_layer_id;
    std::optional<std::optional<std::string>> edit_target_layer_id;
    std::optional<std::optional<std::string>> selected_asset_id;
    std::optional<std::optional<std::string>> selected_version_id;
    std::optional<std::optional<std::string>> active_survey_id;
    std::optional<std::optional<std::string>> active_task_id;
    std::optional<std::optional<std::string>> workflow_stage;
    std::optional<std::optional<MapExtentState>> map_extent;
    std::optional<std::optional<std::string>> source_widget_id;
    std::optional<std::map<std::string, domain::Json>> custom_attributes;
};

using SelectionHandler = std::function<void(const SelectionState&)>;

class SelectionBus {
public:
    explicit SelectionBus(std::function<double()> clock);
    SelectionBus();

    const SelectionState& state() const { return state_; }
    std::optional<std::string> source_widget_id() const {
        return state_.source_widget_id;
    }
    bool was_published_by(const std::string& widget_id) const;
    double timestamp() const { return state_.timestamp; }

    void subscribe(SelectionHandler handler);
    void unsubscribe_all();

    // SelectionContext.snapshot() parity (a snapshot is the state copy the
    // router diffs against). clear() resets every published field — the
    // cross-project bleed guard (clear_project).
    SelectionState snapshot() const { return state_; }
    void clear();

    // update(**kwargs) parity — only the fields a publisher sets are
    // touched. The source tag follows the Python _UNSET sentinel: it is
    // applied only when the caller passes one explicitly (here or via
    // patch.source_widget_id); an internal update (e.g. the seismic
    // custom-attribute write) leaves the tag alone.
    void update(SelectionPatch patch,
                const std::optional<std::optional<std::string>>&
                    source_widget_id = std::nullopt);

    // Convenience publishers — SelectionContext.publish_* parity.
    void publish_well_selection(
        const std::optional<std::string>& active_well_id,
        const std::set<std::string>& selected_well_ids,
        const std::optional<std::string>& source = {});
    void publish_seismic_cursor(
        const std::optional<SeismicCursorState>& cursor,
        const std::optional<std::string>& source = {});
    void publish_spatial_cursor(
        const std::optional<SpatialCursorState>& cursor,
        const std::optional<std::string>& source = {});
    // depth_cursor is the (well_key, md_m) pair — there is no scalar-depth
    // convenience publisher in Python (the coordinator writes the pair
    // through update()); this wrapper mirrors that shape exactly.
    void publish_depth_cursor(
        const std::optional<std::pair<std::string, double>>& cursor,
        const std::optional<std::string>& source = {});
    void publish_map_extent(const MapExtentState& extent,
                            const std::optional<std::string>& source = {});
    void publish_layer_selection(
        const std::optional<std::string>& layer_id,
        const std::optional<std::string>& source = {});
    void publish_task_selection(
        const std::optional<std::string>& task_id,
        const std::optional<std::string>& source = {});

private:
    SelectionState state_;
    std::vector<SelectionHandler> handlers_;
    std::function<double()> clock_;
};

}  // namespace pwb::ui_controllers
