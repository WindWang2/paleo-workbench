#pragma once

/// QGIS renderer/symbol serialization and construction.
///
/// The authoritative cartographic style model is a QgsFeatureRenderer (owning
/// a full QgsSymbol/QgsSymbolLayer tree).  This codec owns:
///   - the XML round-trip used to persist styles inside Paleo map documents;
///   - building renderers from the legacy flat VectorLayerSpec fields, where
///     ``createSimple`` remains only a legacy-import/fallback path.

#include <memory>
#include <string>
#include <vector>

#include <qgis.h>
#include <qstring.h>

class QgsFeatureRenderer;
class QgsVectorLayer;

namespace pwb::qgis_render {

struct VectorLayerSpec;

/// Serialize a renderer (with its complete symbol-layer tree) to QGIS symbology
/// XML.  The result is the payload stored in Paleo project documents.
std::string renderer_to_xml(const QgsFeatureRenderer& renderer);

/// Parse QGIS symbology XML produced by renderer_to_xml (or QGIS Desktop).
/// Returns nullptr when the payload is not valid renderer XML.
std::unique_ptr<QgsFeatureRenderer> renderer_from_xml(const std::string& xml);

/// Build a renderer from the legacy flat spec fields.  Supports single,
/// categorized, graduated and rule-based kinds; every symbol is built through
/// the createSimple compatibility path (legacy import only).
std::unique_ptr<QgsFeatureRenderer> build_renderer_from_spec(
    Qgis::GeometryType geometry_type, const VectorLayerSpec& spec
);

/// Build an empty memory vector layer with the given fields so GUI dialogs can
/// resolve expressions/classifications without touching host data.
std::unique_ptr<QgsVectorLayer> make_dialog_layer(
    const std::string& geometry_type, const std::string& crs,
    const std::vector<std::pair<std::string, std::string>>& fields
);

/// Shared style helpers (used by both QgisRenderBridge and QgisMapStack) —
// extracted from the formerly file-static implementations in
// qgis_render_bridge.cpp so map_stack_service.cpp can reuse them without
// duplicating logic.
void validate_style_payloads(const VectorLayerSpec& spec);
void apply_renderer_style(QgsVectorLayer& layer, const VectorLayerSpec& spec);
void apply_label_style(QgsVectorLayer& layer, const VectorLayerSpec& spec);

}  // namespace pwb::qgis_render
