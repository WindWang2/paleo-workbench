#include "pwb/ui_data_core/map_edit_draft.hpp"

#include <cmath>
#include <utility>

namespace pwb::ui_data_core {

bool MapDraftCore::append_point(double x, double y, std::string kind) {
    draft_kind_ = std::move(kind);
    if (!draft_points_.empty()) {
        const MapPoint& last = draft_points_.back();
        if (std::abs(last[0] - x) < kDraftMinDist &&
            std::abs(last[1] - y) < kDraftMinDist) {
            return false;
        }
    }
    draft_points_.push_back({x, y});
    return true;
}

std::vector<MapPoint> MapDraftCore::preview_path(double cursor_x,
                                                 double cursor_y,
                                                 bool close_preview) const {
    std::vector<MapPoint> path;
    if (draft_points_.empty()) {
        return path;
    }
    path = draft_points_;
    path.push_back({cursor_x, cursor_y});
    if (close_preview && draft_points_.size() >= 2) {
        path.push_back(draft_points_.front());
    }
    return path;
}

void MapDraftCore::cancel() {
    draft_points_.clear();
    draft_kind_.reset();
}

std::optional<std::string> MapDraftCore::finish_line(
    const CreateFeatureFn& create_feature) {
    if (draft_kind_.has_value() && *draft_kind_ != "line") {
        return std::nullopt;
    }
    const std::vector<MapPoint> points = draft_points_;
    cancel();
    if (points.size() < 2) {
        return std::nullopt;
    }
    domain::Json record = domain::Json::object();
    record["id"] = ids_("line");
    record["kind"] = "line";
    record["name"] = "";
    record["coordinates"] = ring_to_json(points);
    return create_feature(record);
}

std::optional<std::string> MapDraftCore::finish_facies(
    const CreateFeatureFn& create_feature,
    const RefreshTopologyFn& refresh_topology) {
    if (draft_kind_.has_value() && *draft_kind_ != "facies") {
        return std::nullopt;
    }
    std::vector<MapPoint> points = draft_points_;
    cancel();
    if (points.size() < 3) {
        return std::nullopt;
    }
    MapRing ring = points;
    if (ring.front() != ring.back()) {
        ring.push_back(ring.front());
    }
    domain::Json record = domain::Json::object();
    record["id"] = ids_("facies");
    record["kind"] = "facies";
    record["name"] = "新相带";
    record["coordinates"] = ring_to_json(ring);
    record["style"] = domain::Json::object();
    auto fid = create_feature(record);
    if (fid.has_value()) {
        refresh_topology(*fid);
    }
    return fid;
}

}  // namespace pwb::ui_data_core
