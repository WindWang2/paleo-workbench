#pragma once

// UI-14 — Qt shells for the selection bus + view coordination
// (viz/selection_context.py + view_coordination.py QObject parity).
//
// QtSelectionContext is the QObject face of the shared SelectionBus:
// publishers call publish_* exactly like Python's SelectionContext and
// subscribers connect to selection_changed (emitted with the context —
// Python `selection_changed.emit(self)` parity).
//
// ViewCoordinationController owns ViewCoordinationCore, subscribes it to
// the context, and exposes the publish_* + sink API as Qt slots/methods.
// The page/shell objects the Python controller touches are bound as the
// core's callable sinks — the integration adapter sets them when the
// pages exist; until then the routing logic runs fully off them being
// unset (the getattr(..., None) contract).

#include <QObject>
#include <QString>

#include <chrono>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include <pwb/project/document.hpp>

#include <pwb/ui_controllers/view_coordination.hpp>

namespace pwb::ui_controllers::qt {

class QtSelectionContext : public QObject {
    Q_OBJECT
public:
    explicit QtSelectionContext(QObject* parent = nullptr);

    SelectionBus& bus() { return bus_; }
    const SelectionBus& bus() const { return bus_; }

    // SelectionContext.update / snapshot / clear parity.
    void update(SelectionPatch patch,
                const std::optional<std::optional<std::string>>&
                    source_widget_id = std::nullopt) {
        bus_.update(std::move(patch), source_widget_id);
    }
    SelectionState snapshot() const { return bus_.snapshot(); }
    void clear() { bus_.clear(); }

    // Convenience publishers (SelectionContext.publish_* parity).
    void publish_well_selection(
        const std::optional<std::string>& active_well_id,
        const std::set<std::string>& selected_well_ids,
        const std::optional<std::string>& source = std::nullopt) {
        bus_.publish_well_selection(active_well_id, selected_well_ids,
                                    source);
    }
    void publish_seismic_cursor(
        const std::optional<SeismicCursorState>& cursor,
        const std::optional<std::string>& source = std::nullopt) {
        bus_.publish_seismic_cursor(cursor, source);
    }
    void publish_spatial_cursor(
        const std::optional<SpatialCursorState>& cursor,
        const std::optional<std::string>& source = std::nullopt) {
        bus_.publish_spatial_cursor(cursor, source);
    }
    void publish_depth_cursor(
        const std::optional<std::pair<std::string, double>>& cursor,
        const std::optional<std::string>& source = std::nullopt) {
        bus_.publish_depth_cursor(cursor, source);
    }
    void publish_map_extent(
        const MapExtentState& extent,
        const std::optional<std::string>& source = std::nullopt) {
        bus_.publish_map_extent(extent, source);
    }

signals:
    // Python emits the context itself; receivers read bus().state().
    void selection_changed(QtSelectionContext* context);

private:
    SelectionBus bus_;
};

class ViewCoordinationController : public QObject {
    Q_OBJECT
public:
    // selection may be nullptr (unbound bus — the controller still works
    // for direct publish_* calls; attach_selection wires routing later).
    explicit ViewCoordinationController(
        QtSelectionContext* selection = nullptr,
        CoordinateHubApi* hub = nullptr, QObject* parent = nullptr);

    ViewCoordinationCore& core() { return core_; }
    QtSelectionContext* selection() const { return selection_; }

    // Late bus binding (attach_app_shell installs the context before the
    // pages exist).
    void attach_selection(QtSelectionContext* selection);

    // bind_project(project)/clear_project parity — full replacement.
    void bind_project(const domain::Json& project_root,
                      CatalogPortApi* catalog = nullptr,
                      const TimeDepthParseFn& parse_td = nullptr);
    void bind_project(const project::ProjectDocument& document,
                      CatalogPortApi* catalog = nullptr,
                      const TimeDepthParseFn& parse_td = nullptr);
    void clear_project();

    std::pair<std::optional<QString>, std::optional<QString>>
    resolve_well_key(const QString& value) const;

    // ---- sinks (set_*_sink parity; the Qt adapters land here) ----------
    void set_seismic_sink(
        std::function<void(int, int, std::optional<double>)> sink);
    void set_spatial_cursor_sink(std::function<void(double, double)> sink);
    void set_seismic_focus_sink(
        std::function<void(int, int, double)> sink);
    void set_horizon_sink(std::function<void(std::string)> sink);
    void set_well_dock_sink(std::function<void(std::string)> sink);
    void set_section_cursor_sink(std::function<void(std::string)> sink);
    void set_link_cursor_sink(
        std::function<void(std::optional<std::string>,
                           std::optional<double>)> sink);
    void set_well_log_select_sink(std::function<void(std::string)> sink);
    void set_geomodel_highlight_sink(std::function<void(std::string)> sink);
    void set_map_select_well_sink(std::function<void(std::string)> sink);

public slots:
    // publish_* parity — the slots pages call through the shell.
    void publish_well_selection(const QString& well_id,
                                const QString& source);
    void publish_seismic_cursor(int il, int xl, double twt);
    void publish_horizon_selection(const QString& horizon_id,
                                   const QString& source);
    void publish_fault_selection(const QString& fault_id,
                                 const QString& source);
    void publish_interpretation_selection(const QString& interpretation_id,
                                          const QString& source);
    void publish_layer_selection(const QString& layer_id,
                                 const QString& source);
    void publish_active_layer(const QString& layer_id,
                              const QString& source);
    void publish_edit_target(const QString& layer_id,
                             const QString& source);
    void publish_asset_selection(const QString& asset_id,
                                 const QString& version_id,
                                 const QString& source);
    void publish_survey_selection(const QString& survey_id,
                                  const QString& source);
    void publish_task_selection(const QString& task_id,
                                const QString& source);
    void publish_stage(const QString& stage, const QString& source);
    bool publish_depth_cursor(const QString& well_id, double md,
                              const QString& source);
    void publish_section_cursor(const QString& well_name,
                                const QString& source);

    // Producer hooks (panel signals forward here).
    void on_well_log_task_selected(const QString& well_name);
    void on_well_depth_cursor(const QString& well_name, double md);
    void on_dock_depth_cursor(const QString& well_name, double md);

private:
    // Bus for the unbound (selection == nullptr) case; owned so it is
    // released with the controller instead of leaked (F-08: was *new).
    std::unique_ptr<SelectionBus> owned_bus_;
    ViewCoordinationCore core_;
    QtSelectionContext* selection_ = nullptr;
};

}  // namespace pwb::ui_controllers::qt
