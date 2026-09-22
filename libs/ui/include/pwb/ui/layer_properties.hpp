#pragma once

// CONV-27 — Layer properties / symbology surface. Zero home-grown style
// editors: the dialogs are QGIS's complete QgsVectorLayerProperties and
// QgsRasterLayerProperties surfaces (source, symbology, labels, fields,
// forms, joins, diagrams, metadata, rendering and temporal settings), with
// QGIS QML serialization. Styles live as .qml sidecars next to the layer's
// own data file, so the style follows the layer instead of the window.

#include <QString>

class QgsMapCanvas;
class QgsMapLayer;
class QgsVectorLayer;
class QWidget;

namespace pwb::ui {
namespace layer_style {

// Modal native vector/raster layer properties dialog. Returns true when the
// user accepted and QGIS applied the layer settings.
bool open_layer_properties(QgsMapLayer* layer, QgsMapCanvas* canvas,
                           QWidget* parent);

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
