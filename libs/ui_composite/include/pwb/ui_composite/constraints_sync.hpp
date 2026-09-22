#pragma once

// Port of paleo_workbench/mapping_workspace/constraints_sync.py —
// constraint geometry sync-back (goal §11, audit P0-3).
//
// ``create_constraint`` registers an editable vector layer plus a
// ``ConstraintLine`` whose ``coordinates`` are EMPTY — geometry is
// digitized into the layer, and the engine-side line used by
// interpolation could silently diverge.  This module harvests the
// digitized features back into the linked ``ConstraintLine`` entries and
// stamps a content fingerprint so downstream freshness evaluation has a
// comparison baseline (``constraints:current``).
//
// Matching rule (conservative, machine-readable signals only):
//   1. primary — ``line.properties["layer_id"] == layer_id``;
//   2. fallback — same ``constraint_kind`` AND the line name equals the
//      layer name AND the line still has empty coordinates (legacy
//      layers created before the ``layer_id`` stamp existed).
//
// Harvest semantics (Python verbatim):
//   * line-kind layers — one coordinate sequence per feature
//     (MultiLineString parts joined, dropping duplicated joint vertices);
//   * polygon kinds (mask / exclusion area) — the exterior ring of each
//     polygon part, CLOSED (the interpolation ring consumer requires
//     first == last); interior rings counted but never harvested;
//   * a layer with multiple features syncs one ConstraintLine per
//     feature (the first matched line keeps its identity; stale extras
//     replaced, never accumulated);
//   * every synced line's properties gains "content_fingerprint".
//
// Pure document-Json transform — no Qt (same discipline as Python:
// stage_save calls it after flush committed the layers into
// document["user_vector_layers"]).

#include <pwb/domain/json.hpp>

#include <string>

namespace pwb::ui_composite {

using pwb::domain::Json;

// constraint_content_fingerprint parity — sha256 over the canonical
// encoding of the coordinate sequence (each vertex rounded to 9
// decimals; json.dumps sort_keys + compact separators).
[[nodiscard]] std::string constraint_content_fingerprint(
    const Json& coordinates);

// sync_constraint_geometry parity — harvest a constraint
// user_vector_layers entry's features into the linked
// constraint_layers[].lines[].coordinates (+ content fingerprint).
// `document` is the project root Json, mutated in place.
// Returns the Python report dict: {"ok", "reason"?,"layer_id",
// "constraint_kind"?, "matched_by"?, "lines_synced"?,
// "features_harvested"?, "interior_rings_skipped"?, "coordinates_total"?,
// "content_fingerprint"?}.
[[nodiscard]] Json sync_constraint_geometry(Json& document,
                                            const std::string& layer_id);

}  // namespace pwb::ui_composite
