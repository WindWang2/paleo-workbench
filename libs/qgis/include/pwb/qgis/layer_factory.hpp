#pragma once

// LayerFactory — QgsProviderRegistry-driven layer admission
// (QGIS-native data-management convergence). Generic data-source
// recognition goes through QgsProviderRegistry::querySublayers: the
// provider that can read the URI names itself (provider key, sublayer
// name, layer type) — no extension sniffing, no second self-built
// datasource classification for GIS files. Failures come back as honest
// errors from the provider, never as fabricated layers.

#include <string>
#include <vector>

#include <pwb/qgis/layer_adapter.hpp>

#include "qgis.h"

class QgsMapLayer;

namespace pwb::qgis {

class MapSession;

namespace layer_factory {

// One provider-proposed layer inside a URI (a GeoPackage yields one per
// feature table; a plain GeoJSON yields one).
struct ProposedSublayer {
    std::string uri;         // sublayer-scoped URI (provider specific)
    std::string provider_key;
    std::string name;        // provider-declared sublayer name
    std::string kind;        // domain kind ("vector" | "raster")
    Qgis::LayerType type = Qgis::LayerType::Vector;
};

// Asks the provider registry which layers live in the URI. Empty result
// + *error set = no provider could interpret the source.
std::vector<ProposedSublayer> query_sublayers(const std::string& uri,
                                              std::string* error);

// Admits one proposed sublayer into the session's QgsProject (validation
// + domain join key + canvas sync follow the MapSession contract).
// Returns nullptr + *error on provider failure. Layer types the map
// session does not host (mesh/pointcloud/…) are refused honestly.
QgsMapLayer* add_sublayer(MapSession& session,
                          const ProposedSublayer& sublayer,
                          const LayerBinding& binding, std::string* error);

// QGIS provider file filters for open-file dialogs (all extensions the
// providers declare, not a hand-maintained list). Always ends with an
// all-files entry; falls back to that entry when metadata is unavailable.
std::string vector_file_filter();
std::string raster_file_filter();

}  // namespace layer_factory
}  // namespace pwb::qgis
