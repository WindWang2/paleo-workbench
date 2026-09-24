#include <pwb/qgis/layer_factory.hpp>

#include <QString>

#include <qgsmaplayer.h>
#include <qgsprovidermetadata.h>
#include <qgsproviderregistry.h>
#include <qgsprovidersublayerdetails.h>
#include <qgsrasterlayer.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/map_session.hpp>

namespace pwb::qgis::layer_factory {

std::vector<ProposedSublayer> query_sublayers(const std::string& uri,
                                              std::string* error) {
    std::vector<ProposedSublayer> out;
    const QList<QgsProviderSublayerDetails> details =
        QgsProviderRegistry::instance()->querySublayers(
            QString::fromStdString(uri));
    if (details.isEmpty()) {
        if (error != nullptr) {
            *error = "no QGIS provider can interpret '" + uri + "'";
        }
        return out;
    }
    out.reserve(static_cast<std::size_t>(details.size()));
    for (const QgsProviderSublayerDetails& detail : details) {
        ProposedSublayer sublayer;
        sublayer.uri = detail.uri().toStdString();
        sublayer.provider_key = detail.providerKey().toStdString();
        sublayer.name = detail.name().toStdString();
        sublayer.type = detail.type();
        switch (detail.type()) {
            case Qgis::LayerType::Vector:
                sublayer.kind = "vector";
                break;
            case Qgis::LayerType::Raster:
                sublayer.kind = "raster";
                break;
            default:
                sublayer.kind = "unsupported";
                break;
        }
        out.push_back(std::move(sublayer));
    }
    return out;
}

QgsMapLayer* add_sublayer(MapSession& session,
                          const ProposedSublayer& sublayer,
                          const LayerBinding& binding, std::string* error) {
    std::unique_ptr<QgsMapLayer> layer;
    switch (sublayer.type) {
        case Qgis::LayerType::Vector:
            layer = std::make_unique<QgsVectorLayer>(
                QString::fromStdString(sublayer.uri),
                QString::fromStdString(sublayer.name),
                QString::fromStdString(sublayer.provider_key));
            break;
        case Qgis::LayerType::Raster:
            layer = std::make_unique<QgsRasterLayer>(
                QString::fromStdString(sublayer.uri),
                QString::fromStdString(sublayer.name),
                QString::fromStdString(sublayer.provider_key));
            break;
        default:
            if (error != nullptr) {
                *error = "unsupported layer type for '" + sublayer.name
                    + "' (provider '" + sublayer.provider_key
                    + "'): the map session hosts vector/raster only";
            }
            return nullptr;
    }
    return session.adopt_layer(layer.release(), binding, error);
}

namespace {

std::string filter_for(const char* provider_key,
                       Qgis::FileFilterType type) {
    QgsProviderMetadata* metadata =
        QgsProviderRegistry::instance()->providerMetadata(
            QString::fromLatin1(provider_key));
    if (metadata == nullptr) return std::string("所有文件 (*)");
    const QString filters = metadata->filters(type);
    return filters.isEmpty() ? std::string("所有文件 (*)")
                             : filters.toStdString() + ";;所有文件 (*)";
}

}  // namespace

std::string vector_file_filter() {
    return filter_for("ogr", Qgis::FileFilterType::Vector);
}

std::string raster_file_filter() {
    return filter_for("gdal", Qgis::FileFilterType::Raster);
}

}  // namespace pwb::qgis::layer_factory
