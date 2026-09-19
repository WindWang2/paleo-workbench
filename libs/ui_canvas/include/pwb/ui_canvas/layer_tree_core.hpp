// UI-15 — Qt-free layer-tree semantics (native_layer_tree.py frozen math).
//
// The Qt model (pwb_ui_canvas_qt) resolves every request against the
// authoritative LayerRegistry — no shadow hierarchy. These helpers carry the
// two pieces of tree math worth testing headless:
//
//   display_children — the panel's top row shows the layer drawn last
//     (reversed registry z-order, filtered to one parent).
//   resolve_drop — the sibling-insertion → absolute z-order conversion used
//     by dropMimeData, including the "not a group → reparent to ITS parent"
//     rule and the "drop below last row → z index 0" bottom rule.
#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <vector>

#include "layer_model.hpp"

namespace pwb::ui_canvas {

// Children of `parent_id` ("" = root) in DISPLAY order: reversed registry
// z-order — panel top row = highest z (drawn last), matching mainstream GIS
// panels. The registry stays authoritative; this only reorders the view.
std::vector<const pwb::layer_model::MapLayer*> display_children(
    const pwb::layer_model::LayerRegistry& registry,
    const std::string& parent_id);

// Result of resolving one drag-drop against the registry.
struct DropResolution {
    // Group the layer should be reparented under ("" = root). nullopt =
    // reject the drop (missing dragged layer, non-group target resolution
    // failed).
    std::optional<std::string> parent_id;
    // Absolute z-position for registry.move_layer (0 = bottom).
    std::size_t absolute_index = 0;
};

// Resolve one drop: `dragged_id` onto `drop_parent_id` ("" or the layer the
// drop landed on) at sibling `row` (< 0 = onto the item itself).
//
// Mirrors dropMimeData verbatim:
//   * a non-group drop target resolves to ITS parent (sibling drop);
//   * siblings are read BEFORE the reparent (display order);
//   * row < 0 → append (len(siblings)); row clamps to [0, len];
//   * row >= len(siblings) → absolute 0 (very bottom);
//   * otherwise absolute = index_of(siblings[row]) — the dropped layer
//     takes the z-slot of the layer it lands on;
//   * empty sibling list → absolute = size - 1 (top of the registry).
std::optional<DropResolution> resolve_drop(
    const pwb::layer_model::LayerRegistry& registry,
    const std::string& dragged_id, const std::string& drop_parent_id,
    int row);

}  // namespace pwb::ui_canvas
