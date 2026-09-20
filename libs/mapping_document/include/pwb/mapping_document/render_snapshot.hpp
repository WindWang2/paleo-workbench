// Renderer-neutral render snapshot adapter for legacy documents (CONV-27d).
//
// Port of paleo_workbench/mapping/map_document_snapshot.py — deliberately an
// ADAPTER, not a second document or layer registry: it turns the persisted
// PaleoMapDocument record shape into immutable render inputs until those
// records migrate to authoritative vector layers / edit sessions.
//
// The Qt value types of map_render_backend (MapLayerSnapshot /
// MapRenderSnapshot) are projected here as Qt-free value structs carrying
// exactly the fields the adapter produces (the Python constructor arguments
// are the contract; renderer_payload / scale_range / metadata are never
// emitted by this adapter — the Python defaults are empty).
//
// Contracts frozen here (see ledgers/27d-decisions.md D-27d-07):
//   * one vector layer per compatibility kind (facies/well/line/label),
//     id = "<document_id>:<kind>";
//   * a single grouped pass over the records buckets only the needed kinds
//     and accumulates each bucket's coordinate bounds inline (no second
//     coordinate walk for extents);
//   * degenerate extents are padded positively (pad = max(1, |coord|)·1e-9);
//     an empty/unusable bucket falls back to (0, 0, 1, 1);
//   * revision-keyed feature reuse: an unchanged host-provided revision
//     (or a layer_revisions alias hit) reuses cached feature tuples/extents
//     without re-walking the records — the bounded owner-scoped LRU never
//     mixes entries across owners (identity-checked, 24 entries);
//   * without a host revision the data revision falls back to a DETERMINISTIC
//     content digest (the Python small-collection path used the process-local
//     hash(); the C++ digest is stable across processes — C++ contract);
//   * style = registry default (provider seam) ⊕ document.facies_style
//     (facies only) ⊕ the layer_state vector_layers entry for the kind
//     (labels nested under style["labels"]).
//
// Single-threaded by contract (render-host synchronization applies).
#pragma once

#include <pwb/domain/json.hpp>

#include <array>
#include <cstddef>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

using Json = pwb::domain::Json;

using Extent = std::array<double, 4>;  // {xmin, ymin, xmax, ymax}

// The renderer-relevant projection of map_render_backend.MapLayerSnapshot.
struct RenderLayerSnapshot {
    std::string id;
    std::string name;
    std::string layer_type = "vector";
    Extent extent{0.0, 0.0, 1.0, 1.0};
    std::string crs;
    long long data_revision = 0;
    long long style_revision = 0;
    std::vector<Json> features;  // GeoJSON-compatible feature objects
    Json style;                  // object payload
    bool visible = true;
    double opacity = 1.0;
};

struct RenderSnapshot {
    std::string project_crs;
    std::vector<RenderLayerSnapshot> layers;
};

// map_styles.default_style_for(kind).to_dict() seam: registry/style defaults
// are host data (CONV-02 D-10 lineage), never baked into the kernel.
using StyleDefaultProvider = std::function<Json(const std::string& kind)>;

struct RenderSnapshotOptions {
    std::string project_crs;
    // kind → visible (missing kind = visible, Python default true).
    std::map<std::string, bool> visibility;
    // Unsaved scene records: render WITHOUT touching the document (features
    // come from here instead of features_from_document).
    std::optional<Json> records;
    // Authoritative per-kind content revisions (authoring document).
    std::map<std::string, long long> data_revisions;
    // map-perf #461 alias: keys "<document_id>:<kind>" bridged down to kind.
    std::map<std::string, long long> layer_revisions;
    // Revision-keyed caching owner (identity only). Revisions without an
    // owner are honored without caching (no cross-call reuse).
    const void* cache_owner = nullptr;
    // Already-held previous snapshot: unchanged revisions reuse its
    // features/extents directly (same reuse the owner LRU provides).
    const RenderSnapshot* previous_layers = nullptr;
};

// Content-stable revision of arbitrary JSON (deterministic across processes;
// C++ contract replacing the Python process-local hash()).
long long stable_content_revision(const Json& value);

// Positive-extent fold: zero-area extents pad by max(1, |coord|)·1e-9.
Extent positive_extent(const Extent& extent);

// The adapter proper. `paleo_doc` is the legacy PaleoMapDocument record
// shape as JSON (facies_polygons / well_overlays / line_features /
// label_features + facies_style + layer_state + id); a null document yields
// an empty snapshot with the project CRS.
RenderSnapshot document_render_snapshot(
    const Json& paleo_doc, const RenderSnapshotOptions& options,
    const StyleDefaultProvider& default_style_for);

// Non-degenerate full extent across all populated composition layers;
// (0, 0, 1, 1) when nothing is populated.
Extent extent_for_snapshot(const RenderSnapshot& snapshot);

}  // namespace pwb::mapping_document
