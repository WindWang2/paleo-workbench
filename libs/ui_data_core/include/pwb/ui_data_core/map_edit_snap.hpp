// map_edit_snap.py port — MapSnapManager: snap state, candidate point
// extraction, caching, and point snapping (geoviz api.snap_point).
// The items it scans are the Qt-free models; the Qt shell passes them.
#pragma once

#include "pwb/ui_data_core/map_edit_items.hpp"

#include <functional>
#include <optional>
#include <string_view>
#include <vector>

namespace pwb::ui_data_core {

// Snap tolerance is defined in screen pixels; the scene converts it to
// scene units via the current view scale before querying candidates.
inline constexpr double kDefaultSnapTol = 8.0;

// One scene item as the snap scan sees it (the isinstance branches).
using SnapItem = std::variant<const FaciesPolygonModel*, const LineModel*,
                              const WellPointModel*, const LabelModel*>;

class MapSnapManager {
public:
    explicit MapSnapManager(double snap_tolerance = kDefaultSnapTol)
        : snap_tolerance_(snap_tolerance) {}

    bool enabled() const { return snap_enabled_; }
    void set_enabled(bool value) { snap_enabled_ = value; }

    double tolerance() const { return snap_tolerance_; }
    void set_tolerance(double value) {
        snap_tolerance_ = value < 0.0 ? 0.0 : value;
    }

    const std::vector<MapPoint>& reference_points() const {
        return reference_snap_points_;
    }
    void set_reference_points(std::vector<MapPoint> points);
    void invalidate_candidates() { snap_candidate_cache_.reset(); }
    int build_count() const { return snap_candidate_builds_; }

    // snap_xy(x, y, items, is_layer_visible_fn, draft_points).
    MapPoint snap_xy(
        double x, double y, const std::vector<SnapItem>& items,
        const std::function<bool(std::string_view)>& is_layer_visible,
        const std::vector<MapPoint>* draft_points = nullptr);

    // get_candidates — base candidates are cached; draft extras append
    // per call (never cached).
    std::vector<MapPoint> get_candidates(
        const std::vector<SnapItem>& items,
        const std::function<bool(std::string_view)>& is_layer_visible,
        const std::vector<MapPoint>* draft_points = nullptr);

private:
    bool snap_enabled_ = false;
    double snap_tolerance_;
    std::optional<std::vector<MapPoint>> snap_candidate_cache_;
    int snap_candidate_builds_ = 0;
    std::vector<MapPoint> reference_snap_points_;
};

}  // namespace pwb::ui_data_core
