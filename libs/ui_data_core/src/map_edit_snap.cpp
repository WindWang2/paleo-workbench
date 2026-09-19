#include "pwb/ui_data_core/map_edit_snap.hpp"

#include <type_traits>
#include <utility>

namespace pwb::ui_data_core {

void MapSnapManager::set_reference_points(std::vector<MapPoint> points) {
    reference_snap_points_ = std::move(points);
    invalidate_candidates();
}

MapPoint MapSnapManager::snap_xy(
    double x, double y, const std::vector<SnapItem>& items,
    const std::function<bool(std::string_view)>& is_layer_visible,
    const std::vector<MapPoint>* draft_points) {
    if (!snap_enabled_) {
        return {x, y};
    }
    const std::vector<MapPoint> candidates =
        get_candidates(items, is_layer_visible, draft_points);
    return snap_point(candidates, x, y, snap_tolerance_);
}

std::vector<MapPoint> MapSnapManager::get_candidates(
    const std::vector<SnapItem>& items,
    const std::function<bool(std::string_view)>& is_layer_visible,
    const std::vector<MapPoint>* draft_points) {
    std::vector<MapPoint> extra;
    if (draft_points != nullptr) {
        extra = *draft_points;
    }
    if (snap_candidate_cache_.has_value()) {
        std::vector<MapPoint> out = *snap_candidate_cache_;
        out.insert(out.end(), extra.begin(), extra.end());
        return out;
    }

    std::vector<MapPoint> pts;
    for (const SnapItem& item : items) {
        const std::string_view kind = std::visit(
            [](const auto& model) -> std::string_view {
                return model != nullptr ? std::string_view(model->kind)
                                        : std::string_view{};
            },
            item);
        if (is_layer_visible && !is_layer_visible(kind)) {
            continue;
        }
        std::visit(
            [&](const auto& model) {
                if (model == nullptr) {
                    return;
                }
                using Model = std::decay_t<decltype(*model)>;
                if constexpr (std::is_same_v<Model, FaciesPolygonModel>) {
                    for (const auto& ring : model->all_rings()) {
                        for (const auto& p : ring) {
                            pts.push_back(p);
                        }
                    }
                } else if constexpr (std::is_same_v<Model, LineModel>) {
                    for (const auto& p : model->coordinates()) {
                        pts.push_back(p);
                    }
                } else {
                    // Well / Label: rec.get("coordinates") or [0, 0].
                    pts.push_back({model->x, model->y});
                }
            },
            item);
    }
    pts.insert(pts.end(), reference_snap_points_.begin(),
               reference_snap_points_.end());
    snap_candidate_cache_ = pts;
    snap_candidate_builds_ += 1;
    std::vector<MapPoint> out = std::move(pts);
    out.insert(out.end(), extra.begin(), extra.end());
    return out;
}

}  // namespace pwb::ui_data_core
