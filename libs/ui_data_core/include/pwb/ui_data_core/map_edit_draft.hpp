// map_edit_draft.py port — the Qt-free draft state of MapDraftManager:
// draft points + kind, the preview-path vertex spec, cancel/finish.
// The QGraphicsPathItem itself lives in the Qt shell; the shell renders
// the vertex list preview_path() returns (moveTo first, lineTo rest —
// OddEvenFill is a facies-ring concern, the preview is a plain polyline).
#pragma once

#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::ui_data_core {

// _DRAFT_MIN_DIST — appended points closer than this are dropped.
inline constexpr double kDraftMinDist = 1e-9;

class MapDraftCore {
public:
    // create_feature_fn(record) → new feature id or nullopt.
    using CreateFeatureFn =
        std::function<std::optional<std::string>(const domain::Json&)>;
    // refresh_topology_fn(feature_id).
    using RefreshTopologyFn = std::function<void(const std::string&)>;
    // new_feature_id seam — default is the uuid4-based generator.
    explicit MapDraftCore(FeatureIdFn ids = nullptr)
        : ids_(ids ? std::move(ids)
                   : [](std::string_view p) { return new_feature_id(p); }) {}

    const std::vector<MapPoint>& points() const { return draft_points_; }
    const std::optional<std::string>& kind() const { return draft_kind_; }
    int point_count() const { return static_cast<int>(draft_points_.size()); }

    // append_point — false when the point was dropped as a near-duplicate.
    // On success the caller should update the preview with
    // preview_path(x, y, kind == "facies") — the Python update_preview call
    // inlined here.
    bool append_point(double x, double y, std::string kind = "line");

    // update_preview — the preview path as an ordered vertex list
    // ([p0..pn, cursor, p0?]); empty when no draft points.
    std::vector<MapPoint> preview_path(double cursor_x, double cursor_y,
                                       bool close_preview = false) const;

    void cancel();

    // finish_line → the created feature id or nullopt.
    std::optional<std::string> finish_line(
        const CreateFeatureFn& create_feature);
    // finish_facies → id or nullopt; refresh_topology runs on success.
    std::optional<std::string> finish_facies(
        const CreateFeatureFn& create_feature,
        const RefreshTopologyFn& refresh_topology);

private:
    std::vector<MapPoint> draft_points_;
    std::optional<std::string> draft_kind_;
    FeatureIdFn ids_;
};

}  // namespace pwb::ui_data_core
