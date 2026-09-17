#pragma once

// MainWindow — direct C++ hosting of QgsMapCanvas + QgsLayerTreeView via
// ProjectSession (no Shiboken address bridge, no mirror copies). The shell
// wires real operations (open vector/raster, map tools, vertex editing,
// undo/redo, commit/rollback, layout export, dirty-close) onto actions that
// are governed by Pwb::ToolPolicy: menu, toolbar and shortcuts share the
// same QAction objects, so one policy verdict drives every surface.

#include <functional>
#include <map>
#include <memory>
#include <set>

#include <QAction>
#include <QMainWindow>

#include <pwb/application/project_session.hpp>
#include <pwb/ui/tool_actions.hpp>

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsMapTool;
class QLabel;

namespace pwb::app {

class VertexMoveMapTool;

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
    enum class DirtyCloseDecision { Proceed, SaveAndClose, DiscardAndClose };

    // Re-projects policy verdicts onto the actions; public because map
    // tools/external edit paths must refresh after mutating edit state.
    void refreshActionStates();

protected:
    void closeEvent(QCloseEvent* event) override;


private:
    void buildUi();
    void buildMenusAndToolbar();
    void connectActions();

    // Operation handlers (triggered by the governed actions).
    void openVectorDialog();
    void openRasterDialog();
    void openProjectDialog();
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

    std::unique_ptr<pwb::application::ProjectSession> session_;
    pwb::ui::ToolActionSet actions_;
    QgsMapCanvas* canvas_ = nullptr;
    QgsLayerTreeView* tree_ = nullptr;
    QLabel* status_label_ = nullptr;

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
