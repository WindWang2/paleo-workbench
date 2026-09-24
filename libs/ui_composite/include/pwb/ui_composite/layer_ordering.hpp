#pragma once

// Scientific role-band ordering vocabulary for the layer tree.
//
// Moved here from pwb::workspace/layer_order (V14): the fractional
// order-key engine it lived beside was retired when the QGIS layer tree
// became the single runtime authority (integer child order, persisted by
// the QGIS-native tree sidecar). The bands survive because they encode
// GEOLOGICAL presentation semantics QGIS does not know: which role
// renders above which when a group's layers are first arranged. Once the
// user reorders, the real tree order is the truth — bands are only the
// initial arrangement.
//
// Qt-free.

#include <map>
#include <string>
#include <string_view>
#include <tuple>

namespace pwb::ui_composite {

// Smaller band = higher on screen (rendered on top). Coarse ordering
// between groups is carried by the system-group template declaration
// order (layer_groups.hpp); this table drives the default scientific
// order INSIDE a container and for root-level loose layers.
int role_band(std::string_view role);
const std::map<std::string, int>& role_bands();

// Factor container scientific order
// (input->grid->contour->classification->uncertainty->QC; same source as
// layer_groups::factor_child_order, O(1) rank here).
int factor_role_rank(std::string_view role);

// Default in-container sort key: band -> scientific sub-order -> stable
// id (total order, deterministic).
using BandSortKey = std::tuple<int, long long, std::string>;
BandSortKey band_sort_key(std::string_view role, long long sub_order = 0,
                          std::string node_id = "");

}  // namespace pwb::ui_composite
