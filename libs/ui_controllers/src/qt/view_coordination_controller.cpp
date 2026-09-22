#include <pwb/ui_controllers/qt/view_coordination_controller.hpp>

namespace pwb::ui_controllers::qt {

namespace {

double wall_clock_ms() {
    return static_cast<double>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count());
}

// QString → std::optional<std::string>; an empty string is a real empty
// string (publish calls that distinguish "" vs absent pass explicit
// optionals through the bus API instead).
std::string to_std(const QString& value) { return value.toStdString(); }

std::optional<std::string> to_opt(const QString& value) {
    return value.isEmpty() ? std::nullopt
                           : std::optional<std::string>(to_std(value));
}

}  // namespace

// ---------------------------------------------------------------------------
// QtSelectionContext
// ---------------------------------------------------------------------------

QtSelectionContext::QtSelectionContext(QObject* parent)
    : QObject(parent), bus_(wall_clock_ms) {
    // selection_changed.emit(self) parity — every bus update emits the
    // context pointer (direct connections read bus().state()).
    bus_.subscribe([this](const SelectionState&) {
        emit selection_changed(this);
    });
}

// ---------------------------------------------------------------------------
// ViewCoordinationController
// ---------------------------------------------------------------------------

ViewCoordinationController::ViewCoordinationController(
    QtSelectionContext* selection, CoordinateHubApi* hub, QObject* parent)
    : QObject(parent),
      owned_bus_(selection != nullptr
                     ? nullptr
                     : std::make_unique<SelectionBus>(wall_clock_ms)),
      core_(selection != nullptr ? selection->bus() : *owned_bus_, hub) {
    selection_ = selection;
    if (selection_ != nullptr) core_.attach_to_bus();
}

void ViewCoordinationController::attach_selection(
    QtSelectionContext* selection) {
    if (selection == selection_) return;
    selection_ = selection;
    if (selection_ != nullptr) core_.attach_to_bus();
}

void ViewCoordinationController::bind_project(
    const domain::Json& project_root, CatalogPortApi* catalog,
    const TimeDepthParseFn& parse_td) {
    core_.bind_project(project_root, catalog, parse_td);
}

void ViewCoordinationController::bind_project(
    const project::ProjectDocument& document, CatalogPortApi* catalog,
    const TimeDepthParseFn& parse_td) {
    core_.bind_project(document.root(), catalog, parse_td);
}

void ViewCoordinationController::clear_project() { core_.clear_project(); }

std::pair<std::optional<QString>, std::optional<QString>>
ViewCoordinationController::resolve_well_key(const QString& value) const {
    const auto [name, entity] = core_.resolve_well_key(to_std(value));
    return {
        name ? std::optional<QString>(QString::fromStdString(*name))
             : std::nullopt,
        entity ? std::optional<QString>(QString::fromStdString(*entity))
               : std::nullopt,
    };
}

// ---- sinks --------------------------------------------------------------

void ViewCoordinationController::set_seismic_sink(
    std::function<void(int, int, std::optional<double>)> sink) {
    core_.set_seismic_sink(std::move(sink));
}
void ViewCoordinationController::set_spatial_cursor_sink(
    std::function<void(double, double)> sink) {
    core_.set_spatial_cursor_sink(std::move(sink));
}
void ViewCoordinationController::set_seismic_focus_sink(
    std::function<void(int, int, double)> sink) {
    core_.set_seismic_focus_sink(std::move(sink));
}
void ViewCoordinationController::set_horizon_sink(
    std::function<void(std::string)> sink) {
    core_.set_horizon_sink(std::move(sink));
}
void ViewCoordinationController::set_well_dock_sink(
    std::function<void(std::string)> sink) {
    core_.set_well_dock_sink(std::move(sink));
}
void ViewCoordinationController::set_section_cursor_sink(
    std::function<void(std::string)> sink) {
    core_.set_section_cursor_sink(std::move(sink));
}
void ViewCoordinationController::set_link_cursor_sink(
    std::function<void(std::optional<std::string>, std::optional<double>)>
        sink) {
    core_.set_link_cursor_sink(std::move(sink));
}
void ViewCoordinationController::set_well_log_select_sink(
    std::function<void(std::string)> sink) {
    core_.set_well_log_select_sink(std::move(sink));
}
void ViewCoordinationController::set_geomodel_highlight_sink(
    std::function<void(std::string)> sink) {
    core_.set_geomodel_highlight_sink(std::move(sink));
}
void ViewCoordinationController::set_map_select_well_sink(
    std::function<void(std::string)> sink) {
    core_.set_map_select_well_sink(std::move(sink));
}

// ---- publish_* slots ------------------------------------------------------

void ViewCoordinationController::publish_well_selection(
    const QString& well_id, const QString& source) {
    core_.publish_well_selection(to_std(well_id), to_std(source));
}

void ViewCoordinationController::publish_seismic_cursor(int il, int xl,
                                                        double twt) {
    core_.publish_seismic_cursor(il, xl, twt);
}

void ViewCoordinationController::publish_horizon_selection(
    const QString& horizon_id, const QString& source) {
    core_.publish_horizon_selection(to_std(horizon_id), to_std(source));
}

void ViewCoordinationController::publish_fault_selection(
    const QString& fault_id, const QString& source) {
    core_.publish_fault_selection(to_std(fault_id), to_std(source));
}

void ViewCoordinationController::publish_interpretation_selection(
    const QString& interpretation_id, const QString& source) {
    core_.publish_interpretation_selection(to_std(interpretation_id),
                                           to_std(source));
}

void ViewCoordinationController::publish_layer_selection(
    const QString& layer_id, const QString& source) {
    core_.publish_layer_selection(to_std(layer_id), to_std(source));
}

void ViewCoordinationController::publish_active_layer(
    const QString& layer_id, const QString& source) {
    core_.publish_active_layer(to_opt(layer_id), to_std(source));
}

void ViewCoordinationController::publish_edit_target(
    const QString& layer_id, const QString& source) {
    core_.publish_edit_target(to_opt(layer_id), to_std(source));
}

void ViewCoordinationController::publish_asset_selection(
    const QString& asset_id, const QString& version_id,
    const QString& source) {
    core_.publish_asset_selection(to_opt(asset_id), to_opt(version_id),
                                  to_std(source));
}

void ViewCoordinationController::publish_survey_selection(
    const QString& survey_id, const QString& source) {
    core_.publish_survey_selection(to_opt(survey_id), to_std(source));
}

void ViewCoordinationController::publish_task_selection(
    const QString& task_id, const QString& source) {
    core_.publish_task_selection(to_opt(task_id), to_std(source));
}

void ViewCoordinationController::publish_stage(const QString& stage,
                                               const QString& source) {
    core_.publish_stage(to_opt(stage), to_std(source));
}

bool ViewCoordinationController::publish_depth_cursor(
    const QString& well_id, double md, const QString& source) {
    return core_.publish_depth_cursor(to_std(well_id), md, to_std(source));
}

void ViewCoordinationController::publish_section_cursor(
    const QString& well_name, const QString& source) {
    core_.publish_section_cursor(to_std(well_name), to_std(source));
}

// ---- producer hooks --------------------------------------------------------

void ViewCoordinationController::on_well_log_task_selected(
    const QString& well_name) {
    core_.on_well_log_task_selected(to_std(well_name));
}

void ViewCoordinationController::on_well_depth_cursor(
    const QString& well_name, double md) {
    core_.on_well_depth_cursor(to_std(well_name), md);
}

void ViewCoordinationController::on_dock_depth_cursor(
    const QString& well_name, double md) {
    core_.on_dock_depth_cursor(to_std(well_name), md);
}

}  // namespace pwb::ui_controllers::qt
