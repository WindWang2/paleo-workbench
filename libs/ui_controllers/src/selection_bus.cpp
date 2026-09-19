#include <pwb/ui_controllers/selection_bus.hpp>

#include <chrono>

namespace pwb::ui_controllers {

namespace {

double wall_seconds() {
    return std::chrono::duration<double>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

}  // namespace

SelectionBus::SelectionBus(std::function<double()> clock)
    : clock_(std::move(clock)) {
    if (!clock_) clock_ = &wall_seconds;
}

SelectionBus::SelectionBus() : SelectionBus(nullptr) {}

bool SelectionBus::was_published_by(const std::string& widget_id) const {
    return state_.source_widget_id && *state_.source_widget_id == widget_id;
}

void SelectionBus::subscribe(SelectionHandler handler) {
    handlers_.push_back(std::move(handler));
}

void SelectionBus::unsubscribe_all() { handlers_.clear(); }

void SelectionBus::clear() {
    // clear() parity: full reset AND the source tag cleared (the Python
    // call passes source_widget_id=None explicitly).
    state_ = SelectionState{};
    state_.timestamp = clock_();
    const auto handlers = handlers_;
    for (const auto& handler : handlers) handler(state_);
}

void SelectionBus::update(
    SelectionPatch patch,
    const std::optional<std::optional<std::string>>& source_widget_id) {
    if (source_widget_id) patch.source_widget_id = *source_widget_id;
    if (patch.active_well_id) state_.active_well_id = *patch.active_well_id;
    if (patch.selected_well_ids)
        state_.selected_well_ids = *patch.selected_well_ids;
    if (patch.depth_range) state_.depth_range = *patch.depth_range;
    if (patch.seismic_cursor) state_.seismic_cursor = *patch.seismic_cursor;
    if (patch.active_horizon_id)
        state_.active_horizon_id = *patch.active_horizon_id;
    if (patch.active_fault_id) state_.active_fault_id = *patch.active_fault_id;
    if (patch.active_interpretation_id)
        state_.active_interpretation_id = *patch.active_interpretation_id;
    if (patch.spatial_cursor) state_.spatial_cursor = *patch.spatial_cursor;
    if (patch.depth_cursor) state_.depth_cursor = *patch.depth_cursor;
    if (patch.selected_layer_id)
        state_.selected_layer_id = *patch.selected_layer_id;
    if (patch.active_layer_id) state_.active_layer_id = *patch.active_layer_id;
    if (patch.edit_target_layer_id)
        state_.edit_target_layer_id = *patch.edit_target_layer_id;
    if (patch.selected_asset_id)
        state_.selected_asset_id = *patch.selected_asset_id;
    if (patch.selected_version_id)
        state_.selected_version_id = *patch.selected_version_id;
    if (patch.active_survey_id)
        state_.active_survey_id = *patch.active_survey_id;
    if (patch.active_task_id) state_.active_task_id = *patch.active_task_id;
    if (patch.workflow_stage) state_.workflow_stage = *patch.workflow_stage;
    if (patch.map_extent) state_.map_extent = *patch.map_extent;
    if (patch.custom_attributes)
        state_.custom_attributes = *patch.custom_attributes;
    if (patch.source_widget_id)
        state_.source_widget_id = *patch.source_widget_id;
    state_.timestamp = clock_();

    // Copy the handler list before dispatch: a handler may subscribe or
    // unsubscribe while routing (SelectionContext parity — the Python
    // emitter iterates a live list but the sinks here are allowed to add).
    const auto handlers = handlers_;
    for (const auto& handler : handlers) handler(state_);
}

void SelectionBus::publish_well_selection(
    const std::optional<std::string>& active_well_id,
    const std::set<std::string>& selected_well_ids,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.active_well_id = active_well_id;
    patch.selected_well_ids = selected_well_ids;
    update(patch, source);
}

void SelectionBus::publish_seismic_cursor(
    const std::optional<SeismicCursorState>& cursor,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.seismic_cursor = cursor;
    update(patch, source);
}

void SelectionBus::publish_spatial_cursor(
    const std::optional<SpatialCursorState>& cursor,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.spatial_cursor = cursor;
    update(patch, source);
}

void SelectionBus::publish_depth_cursor(
    const std::optional<std::pair<std::string, double>>& cursor,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.depth_cursor = cursor;
    update(patch, source);
}

void SelectionBus::publish_map_extent(
    const MapExtentState& extent, const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.map_extent = extent;
    update(patch, source);
}

void SelectionBus::publish_layer_selection(
    const std::optional<std::string>& layer_id,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.selected_layer_id = layer_id;
    update(patch, source);
}

void SelectionBus::publish_task_selection(
    const std::optional<std::string>& task_id,
    const std::optional<std::string>& source) {
    SelectionPatch patch;
    patch.active_task_id = task_id;
    update(patch, source);
}

}  // namespace pwb::ui_controllers
