#include <pwb/mapping_document/map_document_snapshot.hpp>

#include <pwb/domain/json.hpp>

namespace pwb::mapping_document {

Json snapshot_provenance(const MapDocument& doc) {
    Json out = Json::object();
    out["run_id"] = nullptr;
    if (doc.metadata.is_object()) {
        if (doc.metadata.contains("run_id") && !doc.metadata.at("run_id").is_null()) {
            out["run_id"] = doc.metadata.at("run_id");
        }
        if (doc.metadata.contains("provenance")) {
            out["provenance"] = doc.metadata.at("provenance");
        }
    }
    return out;
}

MapDocumentSnapshot capture_map_document_snapshot(const MapDocument& doc,
                                                  long long revision) {
    MapDocumentSnapshot snap;
    snap.document_id = doc.id;
    snap.revision = revision;
    snap.title = doc.title;
    snap.crs = doc.crs;
    snap.extent = doc.extent;
    snap.has_active_layer = doc.has_active_layer;
    snap.active_layer_id = doc.active_layer_id;
    snap.input_version_ids = input_version_ids(doc);
    snap.provenance = snapshot_provenance(doc);
    snap.layers.reserve(doc.layers.size());
    for (const MapLayer& layer : doc.layers) {
        SnapshotLayer entry;
        entry.id = layer.id;
        entry.name = layer.name;
        entry.layer_type = layer.layer_type;
        entry.extent = layer.extent;
        entry.crs = layer.crs;
        entry.data_revision = layer.data_revision;
        entry.style_revision = layer.style_revision;
        entry.visible = layer.visible;
        entry.opacity = layer.opacity;
        entry.source_version_id = layer.source_version_id;
        entry.style = layer.style;          // deep copies: later document
        entry.metadata = layer.metadata;    // mutations never alias into the
        entry.features = layer.features;    // captured snapshot
        entry.annotations = layer.annotations;
        entry.extras = layer.extras;
        snap.layers.push_back(std::move(entry));
    }
    return snap;
}

bool snapshots_equal(const MapDocumentSnapshot& left,
                     const MapDocumentSnapshot& right) {
    if (left.document_id != right.document_id || left.revision != right.revision
        || left.title != right.title || left.crs != right.crs
        || left.extent != right.extent
        || left.has_active_layer != right.has_active_layer
        || left.active_layer_id != right.active_layer_id
        || left.layers.size() != right.layers.size()) {
        return false;
    }
    const auto json_equal = [](const Json& a, const Json& b) {
        return pwb::domain::json_semantic_diff(a, b).equal;
    };
    if (!json_equal(left.input_version_ids, right.input_version_ids)) return false;
    if (!json_equal(left.provenance, right.provenance)) return false;
    for (std::size_t i = 0; i < left.layers.size(); ++i) {
        const SnapshotLayer& a = left.layers[i];
        const SnapshotLayer& b = right.layers[i];
        if (a.id != b.id || a.name != b.name || a.layer_type != b.layer_type
            || a.extent != b.extent || a.crs != b.crs
            || a.data_revision != b.data_revision
            || a.style_revision != b.style_revision || a.visible != b.visible
            || a.opacity != b.opacity
            || a.source_version_id != b.source_version_id) {
            return false;
        }
        if (!json_equal(a.style, b.style) || !json_equal(a.metadata, b.metadata)
            || !json_equal(a.features, b.features)
            || !json_equal(a.annotations, b.annotations)
            || !json_equal(a.extras, b.extras)) {
            return false;
        }
    }
    return true;
}

}  // namespace pwb::mapping_document
