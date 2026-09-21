#pragma once

// MainWindow — direct C++ hosting of QgsMapCanvas + QgsLayerTreeView via
// ProjectSession (no Shiboken address bridge, no mirror copies). The shell
// wires real operations (open vector/raster, map tools, vertex editing,
// undo/redo, commit/rollback, layout export, dirty-close) onto actions that
// are governed by Pwb::ToolPolicy: menu, toolbar and shortcuts share the
// same QAction objects, so one policy verdict drives every surface.

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include <QAction>
#include <QMainWindow>

#include <pwb/application/project_session.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui/tool_actions.hpp>
#ifdef PWB_WITH_APP_SHELL
// CommandContext for the palette context buffer below — must stay OUTSIDE
// the pwb::app namespace block (a global-include, not a nested decl).
#include <pwb/ui_shell/command_registry.hpp>
#endif
#ifdef PWB_WITH_CONV_27
// CONV-27 workbench surface: stage dock, domain layer tree, edit tools,
// constraint panel, layout persistence (all in Pwb::Ui / Pwb::UiWorkbench).
#include <pwb/ui/constraint_panel.hpp>
#include <pwb/ui/edit_tool_controller.hpp>
#include <pwb/ui/layer_tree_panel.hpp>
#include <pwb/ui/stage_dock.hpp>
// BEGIN V14-QGIS-CONTROL
// Native layer control plane: domain group controller + stage policy +
// target model over the session map (docs/development/
// qgis-v14-layer-control/02-architecture.md §D). Wiring scope: open-time
// reconcile + stage switches + save-time user-edit adoption; real-time
// tree-model signal write-back is the Prompt-2 integration point
// (08-known-limitations §2).
#include <pwb/qgis/layer_tree_stack.hpp>
#include <pwb/ui_composite/layer_group_controller.hpp>
#include <pwb/ui_composite/layer_presentation.hpp>
#include <pwb/ui_composite/layer_stage_controller.hpp>
#include <pwb/ui_composite/layer_targets.hpp>
#include <pwb/workspace/mutations.hpp>
#include <pwb/workspace/state.hpp>
#include <pwb/workspace/state_ops.hpp>
// END V14-QGIS-CONTROL
#include <pwb/ui/workbench_layout.hpp>
#endif

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/application/algorithm_runner.hpp>
#endif
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/seismic_io/volume_descriptor.hpp>
#endif
#if defined(PWB_WITH_SEISMIC_SERVICE) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/seismic_service/volume_service.hpp>
#endif

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsMapTool;
class QLabel;
class QDockWidget;
class QMenu;
class QSettings;

namespace pwb::platform_services {
class ThemeService;
}

#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
namespace pwb::ui_pages_preview {
class PreviewSettingsStore;
}
#endif

namespace pwb::mapping {
struct GridStatistics;
}
#ifdef PWB_WITH_CONV_16
namespace pwb::app {
class FactorStatsDock;
}
#endif
#ifdef PWB_WITH_GEO3D_VIZ
// Defined at global scope in geo3d_dock.hpp (CONV-GEO3D wiring).
class Geo3DDock;
#endif

namespace pwb::application {
class AlgorithmRunner;
class PwbDataStore;
struct MapPipelineOutcome;
}
#ifdef PWB_WITH_CONV_30
namespace pwb::app {
class JobCenter;
}
#endif
namespace pwb::seismic_viewer {
class SeismicSliceWidget;
}
namespace pwb::ui_stageflow::qt {
class StageFlowController;
}
#ifdef PWB_WITH_UI_CONTROLLERS
namespace pwb::ui_controllers::qt {
class ViewCoordinationController;
}
#endif

namespace pwb::app {

class VertexMoveMapTool;
class AppContext;
#ifdef PWB_WITH_APP_SHELL
class AppShell;
#endif
#ifdef PWB_WITH_CONV_16
class FactorStatsDock;
#endif

// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
class VizBCrossWellDock;
#endif
// END VIZ-B

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    // Product composition: bootstrap creates the AppContext (service
    // layer: session, attribute runner, project store handle) and hands
    // it in; the window is a pure shell consumer.
    // services_settings: test seam — the QSettings backend for the platform
    // services (window layout/theme store). Null binds the production
    // (PaleoWorkbench, Workstation) store, mirroring the Python
    // LayoutPersistence optional-settings pattern.
    explicit MainWindow(AppContext& context, QWidget* parent = nullptr,
                        QSettings* services_settings = nullptr);
    // Convenience for small hosts/tests: embeds a private AppContext.
    explicit MainWindow(QWidget* parent = nullptr,
                        QSettings* services_settings = nullptr);
    ~MainWindow() override;

    AppContext& context() const { return context_; }

    // Loads a vector fixture + raster fixture, sets an active layer and
    // returns "" (or the diagnostic). Used by the app smoke entry and tests.
    QString loadFixtures(const QString& vector_uri, const QString& raster_uri);

    // The map/edit session owned by the context (out-of-line: AppContext is
    // forward-declared here).
    pwb::application::ProjectSession* session() const;
#ifdef PWB_WITH_APP_SHELL
    // The page-navigation shell (W5/UI-17): workstation frame + composite
    // document hosting the session canvas + hub page stack. Null when the
    // UI slice targets are not in the build closure.
    AppShell* appShell() const { return app_shell_; }
#endif

    // Test/automation entry points for the wired operations (same code the
    // actions trigger; no parallel logic).
    QString openVectorLayer(const QString& path);
    QString openRasterLayer(const QString& path);
    // Opens a .paleo project session through B: real store (refuses
    // unreadable/read-only), startup journal recovery, then every bound
    // GeoJSON layer is materialized as an EXPLICIT WORKING COPY under
    // <project>/.pwb-working/ — catalog payloads are never edited in
    // place. Returns "" on success; the store stays attached so save_edits
    // goes through the real catalog transaction.
    // V14-THREE-STAGE-UX: the definition compiles only in the
    // data-integration closure (PwbDataStore/recovery types), so the
    // declaration is gated to match — a reduced configure keeps the
    // honest no-store surface instead of a link error.
#ifdef PWB_WITH_DATA_INTEGRATION
    QString openProject(const QString& project_file);
    // Creates a fresh project (B's document factory + empty catalog + one
    // bootstrap boundary asset via B's run lifecycle) and opens it.
    QString newProject(const QString& dir_path, const QString& name);
#endif
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
    // Imports one post-stack SEG-Y file as a new Raw seismic_volume asset
    // version (PWBVOL1 payload) through B's run lifecycle; returns the
    // new version id or "" + *error. The version is immediately usable as
    // an attribute input and viewable in the seismic dock.
    std::string importSegy(const QString& path, std::string* error);
#endif
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
    // CONV-30 — the import body with phase safe points (read → payload →
    // register → publish): the sync entry passes inert callbacks, the job
    // path (CONV_30) threads the token/progress through. Declared under
    // the feature guard ONLY (not under CONV_30) so the CONV_30=OFF
    // configuration — where importSegy delegates here — still compiles.
    std::string importSegyProgressed(
        const QString& path, std::string* error,
        const std::function<bool()>& cancelled,
        const std::function<void(double, const QString&)>& progress);
    // Cancelable variant: same staging + publication as importSegy, but
    // the SEG-Y read polls `cancel` between traces (threaded import dialog).
    std::string importSegy(const QString& path, std::string* error,
                           pwb::seismic_io::CancelFlag cancel);
#endif
#ifdef PWB_WITH_CONV_30
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
    // Non-modal import (collect/compute/apply, #1380): the job reads and
    // stages the PWBVOL1 payload off the GUI thread; catalog publication
    // runs in the GUI finished callback against the store captured at
    // submit (window-close and app-quit safe; cancel keeps partial
    // artifacts on disk).
    void submitSegyJob(const QString& path);
#endif
#endif
    QString commitActiveLayer(const std::filesystem::path& staged_dir);
    bool anyDirtyEditSession() const;

    // Dirty-close three-way decision (Save/Discard/Cancel). Production
    // answers with a QMessageBox; tests inject a scripted responder so the
    // close semantics stay verifiable offscreen.
    void setDirtyCloseResponder(std::function<int()> responder) {
        dirty_close_responder_ = std::move(responder);
    }
    // Yes/No confirmation for discarding edits (rollback, stop-with-dirty).
    void setDiscardConfirmResponder(std::function<int()> responder) {
        discard_confirm_responder_ = std::move(responder);
    }
    // cpp-close-12 — the 工程属性 surface (AppShell properties_requested).
    // Production answers with a QMessageBox; tests capture the text via a
    // scripted responder (same pattern as the dirty-close responder).
    void setPropertiesResponder(
        std::function<void(const QString&)> responder) {
        properties_responder_ = std::move(responder);
    }
    // Registers domain facts for a layer added outside the open/new flows
    // (the sample-project bootstrap; openProject parity for facts_).
    void noteDomainLayerFacts(
        const pwb::application::DomainLayerFacts& facts);
#ifdef PWB_WITH_DATA_INTEGRATION
    // cpp-close-12 — AppShell deferred request surfaces, now production
    // handlers; public per the "test/automation entry points" convention
    // (the signals connect to these exact bodies).
    void saveProjectRequested();
    void openSampleProjectRequested();
    void showProjectProperties();
#endif
    // cpp-close-12 — shared preview-settings dialog (preview-only
    // preferences on the unified platform settings store; window-modal
    // non-blocking open hosting the UI-07 settings panel). The preview
    // settings request surface exists only in the AppShell build
    // (PWB_WITH_APP_SHELL), the body only when the UI-07 Qt slice is in
    // the closure (PWB_WITH_UI_PAGES_PREVIEW_QT); both defined by the
    // root-CMake assembly block.
    void showPreviewSettingsRequested();
    // True when the action id has a real handler connected (wiring audit).
    bool actionWired(const QString& tool_id) const {
        return wired_action_ids_.count(tool_id.toStdString()) > 0;
    }
    // The governed QAction for a tool id (the shared object menus and the
    // toolbar consume; nullptr when the policy vocabulary lacks the id).
    QAction* governedAction(const QString& tool_id) const {
        return actions_.action(tool_id.toStdString());
    }
#ifdef PWB_WITH_WELL_LOG
    // Loads a LAS into the well-log dock (C's WLE-backed widget). Returns
    // "" on success; "unavailable" when built without the viewer.
    QString loadLasIntoDock(const QString& las_path);
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    // PWBVOL1 catalog version ids of the open project (attribute inputs /
    // viewable volumes).
    std::vector<std::string> volumeVersionIds() const;
    // Displays one PWBVOL1 catalog version in the seismic dock. Returns ""
    // on success.
    QString openVolumeVersion(const std::string& version_id);
#endif
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    // Submits one attribute run over a PWBVOL1 version into the real B
    // store (register -> payload -> publish). Returns the request id or ""
    // + *error.
    std::string runAttribute(
        const std::string& algorithm_id,
        const std::map<std::string, std::string>& params,
        const std::string& input_version_id, std::string* error);
    // Polls a runAttribute request ("" status = unknown id).
    pwb::application::AlgorithmRunner::Outcome attributeOutcome(
        const std::string& request_id);
#endif
#ifdef PWB_WITH_CONV_01
    // CONV-01 地质因子图: runs the frozen mapping_kernel pipeline over the
    // well records of point layer `layer_id` (or the reserved id
    // "builtin.sample_wells": the frozen 8-well porosity fixture) and adds
    // the contour + facies memory layers to the canvas. Returns "" on
    // success; a non-empty QString is the error text (the kernel's
    // validate() wording verbatim on the failure branch).
    QString runGeologicalFactorMap(const QString& layer_id,
                                   const std::string& factor_name,
                                   const std::string& method, int grid_n,
                                   const std::string& target_horizon);
    // CONV-30 split: collection (GUI thread, QgsVectorLayer iteration) and
    // layer application (GUI thread) are separable from the Qt-free
    // compute so the dialog can run the pipeline as a job.
    QString collectFactorMapInputs(const QString& layer_id,
                                   const std::string& factor_name,
                                   pwb::domain::Json* records,
                                   std::string* crs);
    QString applyFactorMapOutcome(
        const pwb::application::MapPipelineOutcome& outcome,
        const std::string& factor_name, const std::string& crs);
#endif
#ifdef PWB_WITH_CONV_27
    // ---- CONV-27 workbench surface (test/automation entry points; the
    // actions below drive the same code paths) ----------------------------
    // Applies a stage switch through the authoritative session stage.
    void applyStageValue(const std::string& value);
    pwb::ui::StageDock* stageDock() const { return stage_dock_; }
    pwb::ui::LayerTreePanel* layerPanel() const { return layer_panel_; }
    pwb::ui::EditToolController* editTools() const { return edit_tools_; }
    pwb::ui::ConstraintPanel* constraintPanel() const {
        return constraint_dock_;
    }
    // Layout persistence (menu actions call the same methods).
    void saveLayoutState();
    void resetLayoutState();
#endif

    enum class DirtyCloseDecision { Proceed, SaveAndClose, DiscardAndClose };

    // Re-projects policy verdicts onto the actions; public because map
    // tools/external edit paths must refresh after mutating edit state.
    void refreshActionStates();

#ifdef PWB_WITH_CONV_16
    // conv-16: the read-only factor statistics HUD dock (FactorGrid.
    // statistics via pwb::mapping::grid_statistics). Entry point for the
    // interpolation flow once the mapping pipeline hosts results here.
    void showFactorStatistics(const QString& factor_name,
                              const pwb::mapping::GridStatistics& stats);
#endif

// BEGIN PWB-V14-THREE-STAGE (V14-THREE-STAGE-UX: three-stage workbench —
// stage bar mount, StageFlowController seams, production command set,
// task-center providers, selection/focus bus. Body in
// stage_flow_install.cpp.)
#ifdef PWB_WITH_STAGE_FLOW
public:
    // One-shot install (idempotent). Called from buildUi after the app
    // shell exists; test entry point as well.
    void installStageFlow();
    // Restore the mapping stage from the opened project document
    // (mapping_workspace.current_stage, lenient fallback). Called on the
    // openProject success path.
    void restoreStageFromProject();
    pwb::ui_stageflow::qt::StageFlowController* stageFlow() const {
        return stage_flow_;
    }
    // Registered production command count (test assertion surface).
    int stageFlowCommandCount() const { return stage_flow_command_count_; }

private:
    void applyStageVisibility(const std::map<std::string, bool>& visibility);
    pwb::ui_stageflow::qt::StageFlowController* stage_flow_ = nullptr;
    int stage_flow_command_count_ = 0;
    // Registered production command ids (unregistered in the destructor:
    // the registry is process-global while the callbacks capture this
    // window — a closed window must not leave dangling closures for the
    // next window's palette to invoke).
    std::vector<std::string> stage_flow_command_ids_;
    // Well-log dock captured for the selection-bus sink (local in buildUi
    // under PWB_WITH_WELL_LOG).
    QDockWidget* stage_flow_well_log_dock_ = nullptr;
#ifdef PWB_WITH_UI_CONTROLLERS
    pwb::ui_controllers::qt::ViewCoordinationController*
        stage_flow_coordination_ = nullptr;
#endif
#endif
// END PWB-V14-THREE-STAGE

protected:
    void closeEvent(QCloseEvent* event) override;


private:
    void init_shell(QSettings* services_settings = nullptr);
    void buildUi();
    void buildMenusAndToolbar();
    void connectActions();
#ifdef PWB_WITH_APP_SHELL
    // W5/UI-17 — AppShell signal wiring (project actions, theme/density
    // requests, status messages) onto the window-level handlers.
    void wire_app_shell();
#endif

    // CONV-PS platform services: settings/theme/recent/diagnostics wiring
    // (设置 menu + 帮助 menu + File/recent-projects MRU + close-time layout
    // save on the unified (PaleoWorkbench, Workstation) QSettings store).
    void buildPlatformMenus();
    void refreshRecentProjects();
    void openRecentProject(const QString& project_file);
    void showAboutDialog();
    void showDiagnosticsDialog();
    void syncThemeMenuChecks();

    // Operation handlers (triggered by the governed actions).
    void openVectorDialog();
    void openRasterDialog();
#ifdef PWB_WITH_DATA_INTEGRATION
    void openProjectDialog();
    void newProjectDialog();
#endif
#if defined(PWB_WITH_SEISMIC_IO) && defined(PWB_WITH_DATA_INTEGRATION)
    void importSegyDialog();
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    void openVolumeDialog();
#endif
    void exportLayoutDialog();
    void armPan();
    void armZoomIn();
    void armZoomOut();
    void zoomFullExtent();
    void refreshMap();
    void toggleEditing();
    void saveEdits();
    void rollBackEdits();
    void undoEdition();
    void redoEdition();
    void armVertexTool();

    void onActiveLayerChanged();
    void onCanvasMapToolChanged();
#ifdef PWB_WITH_CONV_27
    void install_conv27_surface();
    void onActiveLayerIdChanged(const QString& layer_id);
    void deleteSelectedFeatures();
    void openActiveLayerProperties();
    pwb::ui::ReadinessInputs readiness_inputs() const;
    void refresh_readiness();
    void refresh_constraint_panel();
#endif
    void setStatusFromPolicy(
        const std::map<std::string, pwb::tool_policy::ToolAvailability>& availability);
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    void runAttributeDialog();
#endif
#if defined(PWB_WITH_CONV_30) && defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    // CONV-30 — non-modal supervision of one attribute run: polls the
    // runner outcome on a scheduler job, reports progress to the dialog
    // and propagates cooperative cancel into the run.
    void superviseAttributeRun(const std::string& request_id);
#endif
#ifdef PWB_WITH_CONV_01
    void geologicalFactorMapDialog();
#endif
#ifdef PWB_WITH_CONV_01
#ifdef PWB_WITH_CONV_30
    // CONV-30 — non-modal factor map: the kernel compute runs as a job on
    // the scheduler; layer application stays on the GUI thread.
    void submitFactorMapJob(
        const QString& layer_id, const std::string& factor_name,
        const std::string& method, int grid_n,
        const std::string& target_horizon);
#endif
#endif

    // The composition root's service layer. When the window embeds its own
    // context (tests/small hosts), owned_context_ must be declared BEFORE
    // the reference so member-init order builds it first; it is then
    // destroyed after the UI members but still before the Qt widget
    // children tear down (canvas dies in the QObject base destructor) —
    // session close must run while the canvas is still alive, which the
    // destructor body guarantees explicitly.
    std::unique_ptr<AppContext> owned_context_;
    AppContext& context_;
    pwb::ui::ToolActionSet actions_;
    QgsMapCanvas* canvas_ = nullptr;
#ifdef PWB_WITH_APP_SHELL
    // Central shell: owns the composite document that reparents canvas_.
    // The session's attachCanvas pointer stays valid across the reparent.
    AppShell* app_shell_ = nullptr;
    // cpp-close-12 — the palette context provider's refresh buffer (the
    // returned pointer must stay valid for the duration of the call only;
    // GUI-thread only).
    pwb::ui_shell::CommandContext palette_context_;
#endif
    QgsLayerTreeView* tree_ = nullptr;
    QLabel* status_label_ = nullptr;
#ifdef PWB_WITH_CONV_27
    pwb::ui::StageDock* stage_dock_ = nullptr;
    pwb::ui::LayerTreePanel* layer_panel_ = nullptr;
    pwb::ui::EditToolController* edit_tools_ = nullptr;
    pwb::ui::ConstraintPanel* constraint_dock_ = nullptr;
    std::unique_ptr<pwb::ui::WorkbenchLayout> layout_store_;
    // Set by 重置布局: the next close skips the layout save so the reset
    // actually survives into the next launch (defaults restore).
    bool layout_reset_pending_ = false;
#endif
#ifdef PWB_WITH_WELL_LOG
    // Live depth readout from the well-log view crosshair (cursor linkage).
    QLabel* cursor_label_ = nullptr;
#endif
#ifdef PWB_WITH_CONV_16
    FactorStatsDock* factor_dock_ = nullptr;
#endif
#ifdef PWB_WITH_GEO3D_VIZ
    Geo3DDock* geo3d_dock_ = nullptr;
#endif
// BEGIN VIZ-B
#ifdef PWB_WITH_VIZ_B
    VizBCrossWellDock* viz_b_dock_ = nullptr;
#endif
// END VIZ-B
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    QDockWidget* seismic_dock_ = nullptr;
    pwb::seismic_viewer::SeismicSliceWidget* slice_widget_ = nullptr;
    std::uint64_t slice_revision_ = 0;
    // BEGIN VIZ-D — advanced-display host alias for the menu install.
    pwb::seismic_viewer::SeismicSliceWidget* viz_d_seismic_host_ = nullptr;
    // END VIZ-D
#endif
#if defined(PWB_WITH_SEISMIC_SERVICE) && defined(PWB_WITH_DATA_INTEGRATION)
    // Native tiled volume service: catalog PWBVOL1 versions open through
    // the tile cache (never a full-volume copy). Budget honours
    // PWB_SEISMIC_TILE_CACHE_BYTES.
    std::unique_ptr<pwb::seismic_service::SeismicVolumeService>
        seismic_volume_service_;
#endif

    // Map tools (canvas-owned via setMapTool; kept for re-arming).
    QgsMapTool* pan_tool_ = nullptr;
    QgsMapTool* zoom_in_tool_ = nullptr;
    QgsMapTool* zoom_out_tool_ = nullptr;
    VertexMoveMapTool* vertex_tool_ = nullptr;

    // Domain facts per registered layer id (module-only authority: layers
    // opened by this shell carry write grants here until B bindings exist).
    std::map<std::string, pwb::application::DomainLayerFacts> facts_;

    // BEGIN V14-QGIS-CONTROL
#ifdef PWB_WITH_CONV_27
public:
    // Persist the live layer-control workspace state into the project
    // document's mapping_workspace section (called by the save path
    // before ProjectManager::prepare_save).
    void syncLayerControlOnSave();

private:
    // Build/attach the control plane over the freshly opened project's
    // live workspace state + session map, reconcile the desired tree and
    // restore the stage view (openProject success path).
    void applyLayerControlForOpen();
    pwb::qgis::QgsLayerTreeStack* layerTreeStackForTest() {
        return layer_tree_stack_.get();
    }
    std::unique_ptr<pwb::workspace::MappingWorkspaceState> layer_workspace_;
    std::unique_ptr<pwb::qgis::QgsLayerTreeStack> layer_tree_stack_;
    std::unique_ptr<pwb::ui_composite::LayerGroupController> layer_groups_;
    std::unique_ptr<pwb::ui_composite::LayerStageController> layer_stage_;
    std::unique_ptr<pwb::ui_composite::LayerTargets> layer_targets_;
    // Last composition snapshots (drives the save-time re-reconcile that
    // persists adopted user tree edits).
    std::vector<pwb::ui_composite::LayerSnapshotInput> layer_snapshots_;
#endif
    // END V14-QGIS-CONTROL
    std::function<int()> dirty_close_responder_;
    std::function<int()> discard_confirm_responder_;
    std::function<void(const QString&)> properties_responder_;
    std::set<std::string> wired_action_ids_;

    // Platform services state (null until the constructor built them).
    QSettings* services_settings_ = nullptr;  // never owned here
    std::unique_ptr<QSettings> owned_services_settings_;  // owns when self-created
    std::unique_ptr<pwb::platform_services::ThemeService> theme_service_;
    QMenu* recent_projects_menu_ = nullptr;
    QAction* theme_actions_[3] = {nullptr, nullptr, nullptr};
    QAction* density_action_ = nullptr;
#ifdef PWB_WITH_CONV_30
    // CONV-30 — product job runtime: bounded scheduler + page ownership
    // (close protocol) + app-quit drain. Declared last so it is
    // DESTROYED FIRST (reverse member order): its owner vector frees the
    // QObject-child JobOwners while the surfaces above are still alive.
    std::unique_ptr<JobCenter> job_center_;
#endif
#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
    // cpp-close-12 — the shared preview-settings store, cached on the
    // window (Python controller caches the dialog; the store outlives the
    // recreated dialogs). Complete type in main_window.cpp.
    std::unique_ptr<pwb::ui_pages_preview::PreviewSettingsStore>
        preview_settings_store_;
#endif

    // BEGIN VIZ-E — the mounted data-page dock (plan P-A).
#if defined(PWB_WITH_VIZ_E) && defined(PWB_WITH_CONV_30)
    QDockWidget* viz_e_data_dock_ = nullptr;
#endif
    // END VIZ-E
};

}  // namespace pwb::app
