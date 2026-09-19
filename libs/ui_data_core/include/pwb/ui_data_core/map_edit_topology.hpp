// map_edit_topology.py port — geometry issue collection, adjacency
// warnings, and the topology/merge/split planners that produce commands.
#pragma once

#include "pwb/ui_data_core/map_edit_commands.hpp"
#include "pwb/ui_data_core/map_edit_items.hpp"

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_data_core {

// facies_geometry_issues(item) — ring issues + whole-shape issues, as a
// JSON array of {feature_id, part_index?, ring_index?, code, message,
// severity} dicts. ``backend`` supplies the shapely half; nullptr mirrors
// the ImportError path (shape issues → []).
domain::Json facies_geometry_issues(const FaciesPolygonModel& item,
                                    MapGeometryBackend* backend);

// apply_adjacency_warnings(items, gap_tol) — adjacent items whose status
// is "ok" are flagged "warning".
void apply_adjacency_warnings(std::vector<FaciesPolygonModel*>& items,
                              double gap_tol);

// apply_coordinates callback shape (feature_id, new ring).
using ApplyCoordinatesFn =
    std::function<void(const std::string&, const MapRing&)>;

struct TopologyRebuildPlan {
    domain::Json report = domain::Json::object();  // res_report dict
    std::shared_ptr<BatchVertexEditCommand> command;  // nullable
};

// plan_topology_rebuild — forced rebuild report + batch command.
TopologyRebuildPlan plan_topology_rebuild(
    const std::vector<FaciesPolygonModel*>& facies_items, double tol,
    ApplyCoordinatesFn apply_coordinates);

// Feature-store callbacks the composite commands capture.
using AddFeatureFn = std::function<void(const domain::Json&)>;
using RemoveFeatureFn = std::function<void(const std::string&)>;
using ItemFromRecordFn =
    std::function<std::optional<FeatureModel>(const domain::Json&)>;

struct MergeFaciesPlan {
    std::optional<std::string> new_id;
    std::shared_ptr<CompositeCommand> command;  // nullable
};

// plan_merge_facies — merge two facies into one composite command.
// ``ids`` mints the new feature id (new_feature_id seam).
MergeFaciesPlan plan_merge_facies(
    const FaciesPolygonModel& a, const FaciesPolygonModel& b,
    AddFeatureFn add_feature, RemoveFeatureFn remove_feature,
    const ItemFromRecordFn& item_from_record, MapGeometryBackend* backend,
    const FeatureIdFn& ids = nullptr);

struct SplitFaciesPlan {
    std::optional<std::vector<std::string>> new_ids;
    std::shared_ptr<CompositeCommand> command;  // nullable
};

// plan_split_facies — split one facies polygon by a line item.
SplitFaciesPlan plan_split_facies(
    const FaciesPolygonModel& poly_item, const LineModel& line_item,
    AddFeatureFn add_feature, RemoveFeatureFn remove_feature,
    const ItemFromRecordFn& item_from_record, MapGeometryBackend* backend,
    const FeatureIdFn& ids = nullptr);

}  // namespace pwb::ui_data_core
