#pragma once

// V14 layer order utilities — the NAMED direction conversions of the
// single layer-order contract (contracts 03 §1).
//
// The public contract is TOP-FIRST everywhere (index 0 = top of the
// legend/tree = drawn on top). QGIS consumes two conventions at its
// boundaries:
//   * QgsMapCanvas::setLayers / QgsMapSettings::setLayers — top-first
//     (first layer drawn last / on top): pass the canonical order
//     straight through;
//   * QgsLayoutItemMap::setLayers — BOTTOM-FIRST draw order: the ONLY
//     place a reversal is legal, and only through this named helper.
// Any other silent reverse() of a layer order list is a contract
// violation.

#include <algorithm>
#include <string>
#include <vector>

namespace pwb::qgis::layer_order {

// Canonical top-first -> bottom-first draw order for QgsLayoutItemMap.
// Inverse of top_first_canvas_order; keep both names explicit so call
// sites state their direction (grep-able contract).
template <typename T>
std::vector<T> bottom_first_for_layout_item(
    const std::vector<T>& top_first) {
    std::vector<T> out(top_first.rbegin(), top_first.rend());
    return out;
}

// Bottom-first layout draw order -> canonical top-first (diagnostics /
// round-trip checks on layout layer sets).
template <typename T>
std::vector<T> top_first_from_layout_item(
    const std::vector<T>& bottom_first) {
    std::vector<T> out(bottom_first.rbegin(), bottom_first.rend());
    return out;
}

}  // namespace pwb::qgis::layer_order
