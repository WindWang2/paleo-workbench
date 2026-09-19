#include "pwb/ui_data_qt/map_edit_draft_item.hpp"

#include <QColor>
#include <QPen>

namespace pwb::ui_data_qt {
namespace {

QPen draft_pen() {
    QPen p(QColor(QStringLiteral("#a65313")), 0);  // tokens.ACCENT
    p.setCosmetic(true);
    p.setWidth(1);
    p.setStyle(Qt::PenStyle::DashLine);
    return p;
}

}  // namespace

MapDraftManager::MapDraftManager(QGraphicsScene* scene) : scene_(scene) {}

void MapDraftManager::append_point(double x, double y, std::string kind) {
    if (!core_.append_point(x, y, std::move(kind))) return;
    update_preview(x, y, core_.kind() && *core_.kind() == "facies");
}

void MapDraftManager::update_preview(double cursor_x, double cursor_y,
                                     bool close_preview) {
    if (draft_preview_ == nullptr) {
        draft_preview_ = new QGraphicsPathItem();
        draft_preview_->setPen(draft_pen());
        draft_preview_->setZValue(50);
        scene_->addItem(draft_preview_);
    }
    QPainterPath path;
    const auto pts = core_.preview_path(cursor_x, cursor_y, close_preview);
    if (!pts.empty()) {
        path.moveTo(pts[0][0], pts[0][1]);
        for (std::size_t i = 1; i < pts.size(); ++i)
            path.lineTo(pts[i][0], pts[i][1]);
    }
    draft_preview_->setPath(path);
}

void MapDraftManager::cancel() {
    core_.cancel();
    if (draft_preview_ != nullptr) {
        scene_->removeItem(draft_preview_);
        delete draft_preview_;
        draft_preview_ = nullptr;
    }
}

std::optional<std::string> MapDraftManager::finish_line(
    const pwb::ui_data_core::MapDraftCore::CreateFeatureFn& create_feature) {
    auto result = core_.finish_line(create_feature);
    cancel();
    return result;
}

std::optional<std::string> MapDraftManager::finish_facies(
    const pwb::ui_data_core::MapDraftCore::CreateFeatureFn& create_feature,
    const pwb::ui_data_core::MapDraftCore::RefreshTopologyFn&
        refresh_topology) {
    auto result = core_.finish_facies(create_feature, refresh_topology);
    cancel();
    return result;
}

}  // namespace pwb::ui_data_qt
