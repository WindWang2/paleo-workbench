// Immutable map-document snapshot (CONV-27).
//
// The frozen capture contract: a snapshot is a deep, self-contained value —
// active layer, extent, CRS, per-layer payloads (style/features/annotations
// as verbatim JSON), input_version_ids and provenance refs. Mutating the
// document after capture never changes a captured snapshot (all JSON
// payloads are deep copies), and snapshots compare by structural JSON
// equality. Used by hosts as the cheap staleness/rollback input and by
// workflow provenance records.
#pragma once

#include <pwb/mapping_document/map_document.hpp>

#include <array>
#include <functional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

struct SnapshotLayer {
    std::string id;
    std::string name;
    std::string layer_type;
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
    std::string crs;
    long long data_revision = 1;
    long long style_revision = 1;
    bool visible = true;
    double opacity = 1.0;
    std::string source_version_id;
    Json style;      // deep copy, verbatim
    Json metadata;   // deep copy, verbatim
    Json features;   // deep copy, verbatim
    Json annotations;
    Json extras;
};

struct MapDocumentSnapshot {
    std::string document_id;
    long long revision = 0;  // session revision at capture time (host-supplied)
    std::string title;
    std::string crs;
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
    bool has_active_layer = false;
    std::string active_layer_id;
    Json input_version_ids;  // array, verbatim (kernel input_version_ids())
    Json provenance;         // {"run_id": ..., "provenance": ...} refs, verbatim
    std::vector<SnapshotLayer> layers;
};

// Deep capture. `revision` is the staleness key the host pins (e.g. the
// owning session's revision counter).
MapDocumentSnapshot capture_map_document_snapshot(const MapDocument& doc,
                                                  long long revision);

// layers.py run_id/provenance contract: metadata["run_id"] (null when
// absent) plus any metadata["provenance"] payload verbatim.
Json snapshot_provenance(const MapDocument& doc);

// Structural equality (pwb::domain::json_semantic_diff on every JSON
// payload + scalar fields, order-sensitive for layer lists).
bool snapshots_equal(const MapDocumentSnapshot& left,
                     const MapDocumentSnapshot& right);

}  // namespace pwb::mapping_document
