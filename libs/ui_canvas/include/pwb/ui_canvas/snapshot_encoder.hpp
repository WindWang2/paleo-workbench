// UI-15 — Qt-free QGIS snapshot encoder (mapping/map_render_backend.py
// _qgis_snapshot / _geometry_to_wkt / _is_stale_delta_error frozen
// semantics). Produces the same list[dict] wire payload the pybind layer
// ships to QgisRenderBridge.set_layer_snapshot; the QGIS target maps each
// dict onto VectorLayerSpec (bindings.cpp parse_layers parity).
//
// The encoder is pure Json in/out so it stays headless-testable; the
// stateful #932 feature-delta caches ride SnapshotEncoderState, owned by
// the QGIS backend adapter.
#pragma once

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>

namespace pwb::ui_canvas {

using Json = pwb::domain::Json;

// _geometry_to_wkt parity: GeoJSON {type, coordinates} → WKT with 17g
// float formatting; unsupported/malformed input yields "".
std::string wkt_from_geometry(const Json& geometry);

// One per-feature cache entry: (geometry, properties, encoded) — the
// Python vector_feature_entries[fid] triple verbatim. Equality on the
// first two keys decides payload reuse.
struct FeatureEntry {
    Json geometry;
    Json properties;
    Json encoded;
};

// #932 incremental channel + encoding_stats counters — the per-backend
// caches _qgis_snapshot threads through keyword arguments in Python.
struct SnapshotEncoderState {
    // layer id → (data_revision shipped, full encoded feature list).
    std::map<std::string, std::pair<std::uint64_t, Json>> feature_payloads;
    // layer id → feature id → entry (feature-level payload reuse).
    std::map<std::string, std::map<std::string, FeatureEntry>> feature_entries;
    // layer id → data_revision the bridge mirror provably holds.
    std::map<std::string, std::uint64_t> shipped_revisions;
    // Layer ids forced to a full reship (stale-delta recovery).
    std::set<std::string> force_full_ids;

    // encoding_stats parity (diagnostics only).
    std::uint64_t feature_encoding_cache_hits = 0;
    std::uint64_t feature_encoding_cache_misses = 0;
    std::uint64_t feature_payload_reuse_hits = 0;
    std::uint64_t feature_payload_reencode_misses = 0;
    std::uint64_t feature_delta_ships = 0;
};

// Encode the whole snapshot into the native wire list (Python
// _qgis_snapshot parity):
//   * scalar_grid with source_path (+optional raster_renderer_xml) and
//     raster_source with non-empty source_path emit kind:"raster" entries;
//   * scalar_grid without a source_path throws std::runtime_error — the
//     Python "requires a raster mirror cache" surface (the mirror caches
//     are a mapping-slice concern; the snapshot producer supplies the
//     resolved path);
//   * other raster-ish kinds ("grid") are skipped;
//   * vector layers encode features ({id, wkt, attributes + __pwb_id})
//     and may ship a {"delta": ...} instead of "features" when the bridge
//     mirror provably holds the previous revision and the delta is
//     smaller;
//   * empty-feature vector layers are skipped (the memory provider has
//     no geometry URI for them);
//   * style is flattened via cartography::flatten_qgis_style;
//   * scale_range ships as [min, max] or null.
Json encode_qgis_snapshot(const MapRenderSnapshot& snapshot,
                          SnapshotEncoderState& state);

// _native_snapshot parity: drop encoder cache entries for layers no
// longer present as vectors (scalar_grid/grid/raster_source never enter
// the feature caches). Runs after each encode so removed layers do not
// pin stale feature payloads.
void prune_encoder_state(SnapshotEncoderState& state,
                         const MapRenderSnapshot& snapshot);

// _is_stale_delta_error parity: true only for the bridge's stale
// feature-delta rejection (substring match, case-insensitive) — data
// errors must surface immediately, never trigger a reship.
bool is_stale_delta_error(const std::exception& exc);

}  // namespace pwb::ui_canvas
