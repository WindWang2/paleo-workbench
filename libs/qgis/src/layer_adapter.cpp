#include <pwb/qgis/layer_adapter.hpp>

#include <QString>

#include <qgsmaplayer.h>

namespace pwb::qgis::layer_adapter {

void apply(QgsMapLayer* layer, const LayerBinding& binding) {
    if (layer == nullptr) return;
    layer->setCustomProperty(QString::fromUtf8(kLayerIdProp),
                             QString::fromStdString(binding.layer_id));
    layer->setCustomProperty(QString::fromUtf8(kAssetIdProp),
                             QString::fromStdString(binding.asset_id));
    layer->setCustomProperty(QString::fromUtf8(kVersionIdProp),
                             QString::fromStdString(binding.version_id));
    layer->setCustomProperty(QString::fromUtf8(kKindProp),
                             QString::fromStdString(binding.kind));
}

std::string layer_id_of(const QgsMapLayer* layer, std::string* legacy_doc_id) {
    if (legacy_doc_id != nullptr) {
        const QVariant legacy =
            layer->customProperty(QString::fromUtf8(kLegacyDocIdProp));
        *legacy_doc_id = legacy.toString().toStdString();
    }
    if (layer == nullptr) return std::string();
    const QVariant value =
        layer->customProperty(QString::fromUtf8(kLayerIdProp));
    return value.toString().toStdString();
}

}  // namespace pwb::qgis::layer_adapter
