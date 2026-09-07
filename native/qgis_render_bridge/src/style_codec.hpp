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
class QgsRasterLayer;
class QgsRasterRenderer;
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

// ---------------------------------------------------------------------------
// Raster renderer codec (v7 §5): scalar factor surfaces.
//
// The host computes classification (equal interval / quantile / natural
// breaks / explicit) and ramp items; THIS codec builds the actual QGIS
// objects (QgsSingleBandPseudoColorRenderer + QgsColorRampShader) and
// serializes them through QGIS's own writer so the persisted XML always
// matches the vendored QGIS version — never hand-rolled markup.

/// Build a single-band pseudocolor renderer XML from the scalar style JSON:
/// {"ramp_name","mode":"continuous|classified","items":[{"value","color",
/// "label"}...],"min","max","opacity","nodata_transparent","unit_label",
/// "colorbar_title","crs","labels":[...]}.  Throws std::runtime_error on a
/// malformed payload or empty item list.
std::string build_scalar_renderer_xml(const std::string& spec_json);

/// Parse a raster renderer XML payload (as produced by
/// build_scalar_renderer_xml or QgsProject saves).  Returns nullptr when the
/// payload is not a valid raster renderer element.
std::unique_ptr<QgsRasterRenderer> raster_renderer_from_xml(
    const std::string& xml, class QgsRasterInterface* input);

/// Apply a raster renderer XML payload to a live raster layer.  Returns
/// false (without mutating the layer) when the payload does not parse.
bool apply_raster_renderer_xml(QgsRasterLayer& layer, const std::string& xml);

/// Validate a raster renderer XML payload without a live layer (up-front
/// snapshot validation, mirroring validate_style_payloads for vectors).
/// Throws std::runtime_error when the payload does not parse.
void validate_raster_renderer_xml(const std::string& xml);

}  // namespace pwb::qgis_render
