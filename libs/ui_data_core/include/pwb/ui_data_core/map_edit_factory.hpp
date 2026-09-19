// map_edit_factory.py port — record dict → feature item models. Returns
// nullopt exactly where the Python returns None (bad geometry, missing id,
// flagged coordinate_status, unknown kind).
#pragma once

#include "pwb/ui_data_core/map_edit_items.hpp"

#include <optional>

namespace pwb::ui_data_core {

// item_from_record(record) → model or nullopt.
std::optional<FeatureModel> item_from_record(const domain::Json& record);

std::optional<FaciesPolygonModel> make_facies(const domain::Json& record);
std::optional<WellPointModel> make_well(const domain::Json& record);
std::optional<LineModel> make_line(const domain::Json& record);
std::optional<LabelModel> make_label(const domain::Json& record);

}  // namespace pwb::ui_data_core
