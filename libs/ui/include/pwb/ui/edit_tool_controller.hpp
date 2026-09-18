#pragma once

// CONV-27 — EditToolController: lifecycle owner for the QGIS-native editing
// map tools (selection + digitizing) on the platform canvas. Tools are
// QGIS gui classes; every completed capture is routed through the ONE
// edit authority (ProjectSession -> EditController undoable commands) —
// this class never writes geometry itself and keeps no mirrored state.
//
// Enablement is NOT decided here: ToolPolicy evaluates the snapshot and
// the host's ToolActionSet reflects the verdicts; this controller only
// arms what the host asks it to arm.

#include <QObject>
#include <QString>
#include <string>

#include <pwb/application/project_session.hpp>

class QgsAdvancedDigitizingDockWidget;
class QgsFeature;
class QgsMapCanvas;
class QgsMapTool;
class QgsMapToolDigitizeFeature;
class QgsMapToolSelect;
class QgsVectorLayer;

namespace pwb::ui {

class EditToolController : public QObject {
    Q_OBJECT
public:
    EditToolController(QgsMapCanvas* canvas,
                       pwb::application::ProjectSession* session,
                       QObject* parent = nullptr);

    // Tool ids this controller owns (anything else returns false).
    static bool handles_tool(const std::string& tool_id);
    // Arms the tool (canvas takes it). Unknown/unhandled ids are ignored.
    void arm(const std::string& tool_id);
    // Currently armed tool id (policy vocabulary; "" when another surface
    // owns the canvas tool).
    std::string armed_tool() const { return armed_tool_; }
    // Policy id of a canvas tool owned here ("" when foreign).
    std::string tool_id_of(const QgsMapTool* tool) const;
    // Automation surface (tests drive the same signal the canvas tool
    // emits; no parallel code path).
    QgsMapToolDigitizeFeature* digitize_tool(const std::string& tool_id) const;

    // Active layer changed: digitize tools retarget, canvas currentLayer
    // (selection tool authority) follows.
    void set_active_layer(const std::string& layer_id);

signals:
    // A digitized feature went through the edit authority; hosts refresh
    // action states / repaint.
    void feature_committed(const QString& layer_id);
    void edit_error(const QString& message);

private:
    void on_digitized(QgsMapToolDigitizeFeature* tool,
                      const QgsFeature& feature);

    QgsMapCanvas* canvas_ = nullptr;
    pwb::application::ProjectSession* session_ = nullptr;
    // QGIS capture tools dereference their CAD dock on activate(); the
    // controller owns one (hidden — advanced digitizing stays optional for
    // the user, the pointer is merely required to be valid).
    QgsAdvancedDigitizingDockWidget* cad_dock_ = nullptr;
    QgsMapToolSelect* select_tool_ = nullptr;
    QgsMapToolDigitizeFeature* add_point_tool_ = nullptr;
    QgsMapToolDigitizeFeature* add_line_tool_ = nullptr;
    QgsMapToolDigitizeFeature* add_polygon_tool_ = nullptr;
    std::string armed_tool_;
    std::string active_layer_id_;
};

}  // namespace pwb::ui
