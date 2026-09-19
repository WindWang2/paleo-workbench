#pragma once

// UI-11 — prototypes/workstation_composite_prototype.py Qt-free semantics.
//
// The layer list lives as snapshot Json entries ({id,name,visible,opacity,
// ...other render fields}); mutations edit the entries in place so every
// untouched field survives verbatim — the parity of Python's
// ``dataclasses.replace(layer, visible=…)`` re-publish cycle:
//
//   * set_layer_visible — flag flip
//   * set_layer_opacity — max(0.05, opacity) floor
//   * move_layer — target = index − direction (render bottom-up: "上移"
//     moves EARLIER in the list), bounds-checked swap
//
// The publish step rebuilds the immutable snapshot envelope
// {project_crs, layers} the canvas consumes.

#include "pwb/domain/json.hpp"

#include <string>
#include <vector>

namespace pwb::ui_review {

// layers = a snapshot's "layers" array (each entry an object).
using CompositeLayers = std::vector<domain::Json>;

// index of the layer with `id`, or -1 (Python layer_by_id → None parity).
int composite_layer_index(const CompositeLayers& layers,
                          const std::string& id);

// Returns false when the id is unknown (no publish happens then).
bool composite_set_visible(CompositeLayers& layers,
                           const std::string& id, bool visible);
bool composite_set_opacity(CompositeLayers& layers,
                           const std::string& id, double opacity);
// direction: +1 = 上移 (earlier in list), -1 = 下移.
bool composite_move_layer(CompositeLayers& layers,
                          const std::string& id, int direction);

// MapRenderSnapshot(project_crs, layers=tuple(layers)) parity — the
// immutable envelope handed to canvas.set_layer_snapshot.
domain::Json composite_snapshot_json(const std::string& project_crs,
                                     const CompositeLayers& layers);

// Layer visibility/opacity reads the panel needs for sync.
bool composite_layer_visible(const domain::Json& layer);
double composite_layer_opacity(const domain::Json& layer);
std::string composite_layer_id(const domain::Json& layer);
std::string composite_layer_name(const domain::Json& layer);

}  // namespace pwb::ui_review
