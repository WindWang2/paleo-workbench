#include <pwb/ui/edit_tool_controller.hpp>

#include <qgsadvanceddigitizingdockwidget.h>
#include <qgsfeature.h>
#include <qgsmaplayer.h>
#include <qgsjsonutils.h>
#include <qgsmapcanvas.h>
#include <qgsmaptooldigitizefeature.h>
#include <qgsmaptoolselect.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_adapter.hpp>

namespace pwb::ui {

namespace {
// Capture mode per tool id (QgsMapToolCapture vocabulary).
constexpr auto kSelectToolId = "select";
constexpr auto kAddPointToolId = "add_point";
constexpr auto kAddLineToolId = "add_line";
constexpr auto kAddPolygonToolId = "add_polygon";
}  // namespace

EditToolController::EditToolController(QgsMapCanvas* canvas,
                                       pwb::application::ProjectSession* session,
                                       QObject* parent)
    : QObject(parent), canvas_(canvas), session_(session) {
    // Tools are canvas-parented (Qt ownership); MapSession teardown unsets
    // the armed tool before the canvas dies. The CAD dock must be a real
    // object (capture tools enable() it on activate); it stays hidden —
    // the workbench surfaces advanced digitizing later.
    // Parent REQUIRED: the ctor's first argument is the canvas (not a
    // QObject parent — leaving it null leaks the dock, and its
    // QgsProject::instance() snapping lambdas then dangle against the dead
    // canvas at teardown). Canvas-parented: dies before the tools it
    // enables, with the canvas's QObject tree.
    cad_dock_ = new QgsAdvancedDigitizingDockWidget(canvas_, canvas_);
    select_tool_ = new QgsMapToolSelect(canvas_);
    add_point_tool_ = new QgsMapToolDigitizeFeature(
        canvas_, cad_dock_, QgsMapToolCapture::CapturePoint);
    add_line_tool_ = new QgsMapToolDigitizeFeature(
        canvas_, cad_dock_, QgsMapToolCapture::CaptureLine);
    add_polygon_tool_ = new QgsMapToolDigitizeFeature(
        canvas_, cad_dock_, QgsMapToolCapture::CapturePolygon);

    // The QGIS tools only emit; the edit authority (EditController undoable
    // command path) applies. One write path for every surface.
    for (QgsMapToolDigitizeFeature* tool :
         {add_point_tool_, add_line_tool_, add_polygon_tool_}) {
        connect(tool, &QgsMapToolDigitizeFeature::digitizingCompleted, this,
                [this, tool](const QgsFeature& feature) {
                    on_digitized(tool, feature);
                });
    }
}

bool EditToolController::handles_tool(const std::string& tool_id) {
    return tool_id == kSelectToolId || tool_id == kAddPointToolId
        || tool_id == kAddLineToolId || tool_id == kAddPolygonToolId;
}

bool EditToolController::tool_matches_layer_kind(const std::string& tool_id,
                                                 const std::string& layer_kind) {
    // tool_availability.py _KIND_REQUIRED parity.
    if (layer_kind.empty()) return false;
    if (tool_id == kAddPointToolId) return layer_kind == "point";
    if (tool_id == kAddLineToolId) return layer_kind == "line";
    if (tool_id == kAddPolygonToolId) return layer_kind == "polygon";
    return true;   // selection is kind-agnostic
}

QgsMapToolDigitizeFeature* EditToolController::digitize_tool(
    const std::string& tool_id) const {
    if (tool_id == kAddPointToolId) return add_point_tool_;
    if (tool_id == kAddLineToolId) return add_line_tool_;
    if (tool_id == kAddPolygonToolId) return add_polygon_tool_;
    return nullptr;
}

std::string EditToolController::tool_id_of(const QgsMapTool* tool) const {
    if (tool == nullptr) return "";
    if (tool == select_tool_) return kSelectToolId;
    if (tool == add_point_tool_) return kAddPointToolId;
    if (tool == add_line_tool_) return kAddLineToolId;
    if (tool == add_polygon_tool_) return kAddPolygonToolId;
    return "";
}

void EditToolController::arm(const std::string& tool_id) {
    QgsMapTool* tool = nullptr;
    if (tool_id == kSelectToolId) tool = select_tool_;
    else if (tool_id == kAddPointToolId) tool = add_point_tool_;
    else if (tool_id == kAddLineToolId) tool = add_line_tool_;
    else if (tool_id == kAddPolygonToolId) tool = add_polygon_tool_;
    if (tool == nullptr || canvas_ == nullptr) return;
    canvas_->setMapTool(tool);
    armed_tool_ = tool_id;
}

void EditToolController::set_active_layer(const std::string& layer_id) {
    active_layer_id_ = layer_id;
    QgsMapLayer* layer =
        session_ == nullptr ? nullptr : session_->map().layerById(layer_id);
    // QgsMapToolSelect + the digitize tools resolve their target through
    // the canvas current layer — keep it pinned to the domain active layer.
    if (canvas_ != nullptr) canvas_->setCurrentLayer(layer);
    for (QgsMapToolDigitizeFeature* tool :
         {add_point_tool_, add_line_tool_, add_polygon_tool_}) {
        if (tool != nullptr) tool->setLayer(layer);
    }
}

void EditToolController::on_digitized(QgsMapToolDigitizeFeature* tool,
                                      const QgsFeature& feature) {
    (void)tool;
    if (session_ == nullptr) return;
    // Resolve the domain id through the join key (never the QGIS layer id).
    const QgsVectorLayer* layer =
        canvas_ != nullptr
            ? qobject_cast<QgsVectorLayer*>(canvas_->currentLayer())
            : nullptr;
    if (layer == nullptr) {
        emit edit_error(QObject::tr("数字化完成但没有目标图层（先激活可编辑图层）"));
        return;
    }
    const std::string layer_id =
        pwb::qgis::layer_adapter::layer_id_of(layer);
    // Serialize the captured feature to GeoJSON and hand it to the ONE
    // edit authority: EditController wraps it in an undoable command.
    const QString geojson =
        QgsJsonExporter(const_cast<QgsVectorLayer*>(layer))
            .exportFeature(feature);
    const std::string error =
        session_->edit().add_feature_geojson(layer_id, geojson.toStdString());
    if (!error.empty()) {
        emit edit_error(QString::fromStdString(error));
        return;
    }
    session_->map().refreshCanvases();
    emit feature_committed(QString::fromStdString(layer_id));
}

}  // namespace pwb::ui
