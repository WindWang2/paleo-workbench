#pragma once

// LayerAdapter — domain ID ↔ QgsMapLayer custom-property join key.
// Keys are frozen by V11-V13 + the CPP-A contract: pwb/layer_id,
// pwb/version_id, pwb/asset_id, pwb/kind (legacy pwb/doc_id read-compat).
// Runtime QGIS layer pointers/ids never enter domain state.

#include <string>

class QgsMapLayer;

namespace pwb::qgis {

struct LayerBinding {
    std::string layer_id;    // domain layer id (join key)
    std::string asset_id;
    std::string version_id;
    std::string kind;        // e.g. "vector"|"raster" (domain kind)
};

namespace layer_adapter {

inline constexpr const char* kLayerIdProp = "pwb/layer_id";
inline constexpr const char* kAssetIdProp = "pwb/asset_id";
inline constexpr const char* kVersionIdProp = "pwb/version_id";
inline constexpr const char* kKindProp = "pwb/kind";
inline constexpr const char* kLegacyDocIdProp = "pwb/doc_id";

void apply(QgsMapLayer* layer, const LayerBinding& binding);

// Reads the join key; "" when the layer carries none (or legacy doc_id only
// — reported through the legacy out-param for compatibility audits).
std::string layer_id_of(const QgsMapLayer* layer, std::string* legacy_doc_id = nullptr);

}  // namespace layer_adapter
}  // namespace pwb::qgis
