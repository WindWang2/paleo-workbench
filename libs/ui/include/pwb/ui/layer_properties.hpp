#pragma once

// CONV-27 — Layer properties / symbology surface. Zero home-grown style
// editors: the dialog is QGIS's own QgsRendererPropertiesDialog (native
// classification/labels/opacity widgets), persistence is QGIS QML
// serialization. Styles live as .qml sidecars next to the layer's own
// data file (the QGIS convention), so the style follows the layer, not
// the window.

#include <QString>

class QgsMapCanvas;
class QgsMapLayer;
class QgsVectorLayer;
class QWidget;

namespace pwb::ui {
namespace layer_style {

// Modal native renderer dialog for a vector layer. Returns true when the
// user accepted (the layer then carries the configured renderer — QGIS
// applies on OK). Raster layers return false with no dialog (the raster
// surface stays QGIS-project-native for now).
bool open_renderer_properties(QgsVectorLayer* layer, QgsMapCanvas* canvas,
                              QWidget* parent);

// QML sidecar path for a layer data file: <uri>.qml.
QString sidecar_path(const QString& layer_uri);

// Saves the layer's current style to the sidecar (true on success).
bool save_style_sidecar(QgsMapLayer* layer, const QString& layer_uri);

// Applies the sidecar style when one exists (true when applied, false
// when no sidecar / load failed — caller keeps the default style).
bool apply_style_sidecar(QgsMapLayer* layer, const QString& layer_uri);

}  // namespace layer_style
}  // namespace pwb::ui
