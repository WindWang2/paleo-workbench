#pragma once

// UI-13 — composite QGIS canvas binding.
//
// Port of composite_document's native-stack wiring (the parts of
// _create_canvas / controller hook installation that need the real
// QGIS objects): a QgisCanvasShim — session-owned QgsMapCanvas via
// pwb::qgis::MapSession — bound to a CompositeEditController.
//
//   * CompositeCanvasHooks ← shim methods: zoom / current-layer push /
//    snapping-config projection / native toggles / busy+cancel /
//    canvas_address. attach_canvas() installs them on the controller.
//   * ControllerHooks/ToolHooks ← controller/tool entry points:
//    commit_native_capture / cancel_native_capture /
//    record_native_gesture / join_native_layers, and per-call
//    dynamic_cast probing of the active MapTool's commit_* surface
//    (the Python getattr duck made explicit).
//   * publish_layers() — MapLayerSnapshot vector → MirrorSnapshot →
//     shim.set_layer_snapshot (the mirror reconcile handles doc-id
//     joins, CRS push and failure surfacing).
//
// The shim is a QWidget the host parents into CompositeDocument via
// set_canvas(widget, /*uses_native_stack=*/true).

#include <memory>
#include <string>
#include <vector>

#include <QObject>
#include <QPointer>

#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/map_snapshot.hpp>
#include <pwb/ui_widgets/qgis/canvas_shim.hpp>

class QWidget;

namespace pwb::ui_composite::qgis {

class CompositeQgisCanvas : public QObject {
    Q_OBJECT
public:
    // controller is non-owning and must outlive this binding (the
    // document owns it). Installs the canvas hooks immediately.
    explicit CompositeQgisCanvas(CompositeEditController* controller,
                                 QWidget* parent = nullptr);
    ~CompositeQgisCanvas() override;

    ui_widgets::qgis::QgisCanvasShim* shim() const { return shim_; }
    QWidget* widget() const { return shim_; }

    // Push the controller layer snapshots into the session-project
    // mirror (composite_document._publish parity — display state is
    // already folded into the snapshots).
    void publish_layers(const std::vector<MapLayerSnapshot>& layers,
                        const std::string& project_crs);

    // Ordered teardown (Python shutdown() parity): detaches the canvas
    // hooks, then shuts the shim down before the widget tree dies.
    void shutdown();

private:
    void install_canvas_hooks();
    void install_controller_hooks();
    ui_widgets::qgis::ToolHooks make_tool_hooks() const;

    CompositeEditController* controller_;  // non-owning
    QPointer<ui_widgets::qgis::QgisCanvasShim> shim_;
    // Stable storage the ControllerHooks.active_tool() pointer targets;
    // rebuilt per call, lambdas re-resolve the live MapTool.
    ui_widgets::qgis::ToolHooks tool_hooks_;
    bool hooks_installed_ = false;
};

}  // namespace pwb::ui_composite::qgis
