// mapping/vector_lod.py — screen-space adaptive vector LOD (dataset-level
// Visvalingam-Whyatt with morphology anchors). Bit-identical operation
// order with the frozen Python (the perf-bench cross-verifies both
// implementations; the docstring's map_edit_core twin never landed).
#pragma once

#include <cstddef>
#include <vector>

namespace pwb::ui_canvas::vector_lod {

// Per-vertex pixel tolerance (0.75 px: sub-pixel vertices contribute
// nothing to the screen).
inline constexpr double kDefaultPixelTolerance = 0.75;

// Layers below this vertex count skip dataset-level simplification (the
// frame-level pixel quantisation already covers them).
inline constexpr std::size_t kMinVertexCount = 4000;

// Quantise map-units-per-pixel onto a power-of-two bucket (cache-key
// stability). Non-positive/non-finite → 0.
double scale_bucket_mupp(double mupp);

// Effective-area tolerance in map units (squared). mupp <= 0 → 0.
double tolerance_area(double mupp,
                      double pixel_tolerance = kDefaultPixelTolerance);

// Batch Visvalingam-Whyatt over a flat concatenated vertex array:
// xs/ys hold all vertices; starts[i] begins part i (the last part runs to
// xs.size()); is_ring[i] marks closed rings. Returns a keep-mask the same
// length as xs. tolerance <= 0 → all-true (identity).
//
// Anchored (never dropped): part endpoints, visible inflections (cross-sign
// flips with |cross| >= 2*tolerance on both adjacent turns), and x/y
// coordinate extrema (first occurrence on ties). Iterative elimination:
// each round evaluates effective triangle area against the vertex's current
// surviving neighbours; only strict local minima of consecutive-below runs
// are removed per round (equal-area tie bands thin every other vertex).
std::vector<bool> visvalingam_keep_mask(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<std::size_t>& starts,
    const std::vector<bool>& is_ring, double tolerance);

}  // namespace pwb::ui_canvas::vector_lod
