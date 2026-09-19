// map_edit_draft.py Qt shell — MapDraftManager: MapDraftCore state +
// the scene-owned QGraphicsPathItem preview (dash pen, z=50).
#pragma once

#include "pwb/ui_data_core/map_edit_draft.hpp"

#include <QGraphicsPathItem>
#include <QGraphicsScene>

namespace pwb::ui_data_qt {

class MapDraftManager {
public:
    explicit MapDraftManager(QGraphicsScene* scene);

    const std::vector<pwb::ui_data_core::MapPoint>& points() const {
        return core_.points();
    }
    const std::optional<std::string>& kind() const { return core_.kind(); }
    int point_count() const { return core_.point_count(); }

    void append_point(double x, double y, std::string kind = "line");
    void update_preview(double cursor_x, double cursor_y,
                        bool close_preview = false);
    void cancel();

    std::optional<std::string> finish_line(
        const pwb::ui_data_core::MapDraftCore::CreateFeatureFn&
            create_feature);
    std::optional<std::string> finish_facies(
        const pwb::ui_data_core::MapDraftCore::CreateFeatureFn&
            create_feature,
        const pwb::ui_data_core::MapDraftCore::RefreshTopologyFn&
            refresh_topology);

    // Test/inspection seam (Python _draft_preview attribute parity).
    QGraphicsPathItem* preview_item() const { return draft_preview_; }

private:
    QGraphicsScene* scene_;
    pwb::ui_data_core::MapDraftCore core_;
    QGraphicsPathItem* draft_preview_ = nullptr;  // scene-owned
};

}  // namespace pwb::ui_data_qt
