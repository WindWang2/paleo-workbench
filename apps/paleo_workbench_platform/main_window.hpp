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
#include <pwb/ui/tool_actions.hpp>

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/application/algorithm_runner.hpp>
#endif

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsMapTool;
class QLabel;
class QDockWidget;

namespace pwb::mapping {
struct GridStatistics;
}
#ifdef PWB_WITH_CONV_16
namespace pwb::app {
class FactorStatsDock;
}
#endif

namespace pwb::application {
class AlgorithmRunner;
class PwbDataStore;
}
namespace pwb::seismic_viewer {
class SeismicSliceWidget;
}

namespace pwb::app {

class VertexMoveMapTool;
#ifdef PWB_WITH_CONV_16
class FactorStatsDock;
#endif

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    // Loads a vector fixture + raster fixture, sets an active layer and
    // returns "" (or the diagnostic). Used by the app smoke entry and tests.
    QString loadFixtures(const QString& vector_uri, const QString& raster_uri);

    pwb::application::ProjectSession* session() const { return session_.get(); }

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
    QString openProject(const QString& project_file);
#ifdef PWB_WITH_DATA_INTEGRATION
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

protected:
    void closeEvent(QCloseEvent* event) override;


private:
    void buildUi();
    void buildMenusAndToolbar();
    void connectActions();

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
    void setStatusFromPolicy(
        const std::map<std::string, pwb::tool_policy::ToolAvailability>& availability);
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    void runAttributeDialog();
#endif

    std::unique_ptr<pwb::application::ProjectSession> session_;
    pwb::ui::ToolActionSet actions_;
    QgsMapCanvas* canvas_ = nullptr;
    QgsLayerTreeView* tree_ = nullptr;
    QLabel* status_label_ = nullptr;
#ifdef PWB_WITH_CONV_16
    FactorStatsDock* factor_dock_ = nullptr;
#endif
    // The B store opened by openProject (null in module-only mode); the
    // attribute runner and volume viewer resolve catalog versions here.
    std::shared_ptr<pwb::application::PwbDataStore> project_store_;
#if defined(PWB_WITH_SEISMIC_VIEWER) && defined(PWB_WITH_DATA_INTEGRATION)
    QDockWidget* seismic_dock_ = nullptr;
    pwb::seismic_viewer::SeismicSliceWidget* slice_widget_ = nullptr;
    std::uint64_t slice_revision_ = 0;
#endif
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    std::unique_ptr<pwb::application::AlgorithmRunner> attribute_runner_;
#endif

    // Map tools (canvas-owned via setMapTool; kept for re-arming).
    QgsMapTool* pan_tool_ = nullptr;
    QgsMapTool* zoom_in_tool_ = nullptr;
    QgsMapTool* zoom_out_tool_ = nullptr;
    VertexMoveMapTool* vertex_tool_ = nullptr;

    // Domain facts per registered layer id (module-only authority: layers
    // opened by this shell carry write grants here until B bindings exist).
    std::map<std::string, pwb::application::DomainLayerFacts> facts_;
    std::function<int()> dirty_close_responder_;
    std::function<int()> discard_confirm_responder_;
    std::set<std::string> wired_action_ids_;
};

}  // namespace pwb::app
