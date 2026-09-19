#include <pwb/viz/cross_well/qt/formation_tops_preview.hpp>

#include <QColor>
#include <QEvent>
#include <QMouseEvent>
#include <QPaintEvent>
#include <QPainter>
#include <QPen>
#include <QPointF>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

namespace pwb::viz::cross_well::qt {

using pwb::viz::cross_well::FormationTop;
using pwb::viz::cross_well::PreviewLayout;
using pwb::viz::cross_well::PreviewVisiblePoint;

FormationTopsPreview::FormationTopsPreview(QWidget* parent)
    : QWidget(parent) {
    setMouseTracking(true);
    setMinimumSize(320, 220);
    layout_.full_min_depth = 0.0;
    layout_.full_max_depth = 1.0;
    layout_.view_min_depth = 0.0;
    layout_.view_max_depth = 1.0;
}

void FormationTopsPreview::set_tops(const std::vector<FormationTop>& tops) {
    tops_ = tops;
    // Sorted unique well names (set_tops semantics).
    std::set<std::string> names;
    for (const FormationTop& top : tops_) names.insert(top.well_name);
    well_names_.assign(names.begin(), names.end());
    rebuild();
}

void FormationTopsPreview::clear() {
    tops_.clear();
    well_names_.clear();
    tops_per_well_.clear();
    visible_points_.clear();
    layout_.full_min_depth = 0.0;
    layout_.full_max_depth = 1.0;
    layout_.view_min_depth = 0.0;
    layout_.view_max_depth = 1.0;
    hover_key_.clear();
    update();
}

void FormationTopsPreview::rebuild() {
    tops_per_well_.clear();
    for (const std::string& well : well_names_) {
        std::vector<FormationTop> per_well;
        for (const FormationTop& top : tops_) {
            if (top.well_name == well) per_well.push_back(top);
        }
        tops_per_well_.push_back(std::move(per_well));
    }
    const auto full = pwb::viz::cross_well::preview_full_range(tops_per_well_);
    full_range_ = full;
    layout_.full_min_depth = full.first;
    layout_.full_max_depth = full.second;
    layout_.view_min_depth = full.first;
    layout_.view_max_depth = full.second;
    layout_.width_px = static_cast<double>(width());
    layout_.height_px = static_cast<double>(height());
    hover_key_.clear();
    update();
}

void FormationTopsPreview::paintEvent(QPaintEvent*) {
    QPainter painter(this);
    painter.fillRect(rect(), palette().base());
    layout_.width_px = static_cast<double>(width());
    layout_.height_px = static_cast<double>(height());
    visible_points_.clear();
    if (well_names_.empty()) {
        painter.setPen(QPen(palette().text().color(), 1.0));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("No formation tops"));
        return;
    }
    const std::vector<double> xs =
        pwb::viz::cross_well::preview_well_x_positions(
            well_names_.size(), static_cast<double>(width()));
    const auto connections =
        pwb::viz::cross_well::build_preview_connections(tops_per_well_);
    // Well axes + names.
    QFont small = painter.font();
    small.setPointSize(8);
    painter.setFont(small);
    for (std::size_t i = 0; i < well_names_.size(); ++i) {
        painter.setPen(QPen(QColor(0xa0, 0xae, 0xc0), 1.0));
        painter.drawLine(QPointF(xs[i], pwb::viz::cross_well::kPreviewMarginTopPx),
                         QPointF(xs[i],
                                 static_cast<double>(height()) -
                                     pwb::viz::cross_well::kPreviewMarginBottomPx));
        painter.setPen(QPen(QColor(0x1a, 0x20, 0x2c), 1.0));
        painter.drawText(
            QRectF(xs[i] - 55.0, 8.0, 110.0, 18.0), Qt::AlignCenter,
            QString::fromStdString(well_names_[i]));
    }
    // Depth range labels.
    painter.setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
    painter.drawText(QPointF(4.0, pwb::viz::cross_well::kPreviewMarginTopPx + 10.0),
                     QString("%1 m").arg(layout_.view_min_depth, 0, 'g'));
    painter.drawText(
        QPointF(4.0, static_cast<double>(height()) -
                         pwb::viz::cross_well::kPreviewMarginBottomPx - 4.0),
        QString("%1 m").arg(layout_.view_max_depth, 0, 'g'));
    // Connections first (under the points).
    painter.setRenderHint(QPainter::Antialiasing, true);
    for (const auto& connection : connections) {
        const double y1 = pwb::viz::cross_well::preview_depth_to_y(
            layout_, connection.from_top.depth_m);
        const double y2 = pwb::viz::cross_well::preview_depth_to_y(
            layout_, connection.to_top.depth_m);
        QColor color(QString::fromStdString(
            connection.from_top.resolved_color()));
        painter.setPen(QPen(color, 1.4));
        painter.drawLine(QPointF(xs[connection.from_index], y1),
                         QPointF(xs[connection.to_index], y2));
    }
    // Top points + labels.
    for (std::size_t w = 0; w < tops_per_well_.size(); ++w) {
        for (const FormationTop& top : tops_per_well_[w]) {
            const double y =
                pwb::viz::cross_well::preview_depth_to_y(layout_, top.depth_m);
            if (y < pwb::viz::cross_well::kPreviewMarginTopPx ||
                y > static_cast<double>(height()) -
                        pwb::viz::cross_well::kPreviewMarginBottomPx) {
                continue;
            }
            QColor color(QString::fromStdString(top.resolved_color()));
            painter.setPen(QPen(color.darker(120), 1.0));
            painter.setBrush(color);
            painter.drawEllipse(QPointF(xs[w], y), 4.0, 4.0);
            painter.setPen(QPen(color.darker(130), 1.0));
            painter.drawText(QPointF(xs[w] + 7.0, y - 4.0),
                              QString::fromStdString(top.formation_name));
            visible_points_.push_back(
                PreviewVisiblePoint{xs[w], y, top.well_name,
                                    top.formation_name, top.depth_m});
        }
    }
}

void FormationTopsPreview::wheelEvent(QWheelEvent* event) {
    const int delta = event->angleDelta().y();
    if (delta == 0) return;
    const auto view = pwb::viz::cross_well::preview_zoomed_view(
        layout_, event->position().y(), delta > 0);
    layout_.view_min_depth = view.first;
    layout_.view_max_depth = view.second;
    hover_key_.clear();
    visible_points_.clear();
    update();
    event->accept();
}

void FormationTopsPreview::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        dragging_ = true;
        drag_start_y_ = event->position().y();
        setCursor(Qt::ClosedHandCursor);
        event->accept();
    }
}

void FormationTopsPreview::mouseMoveEvent(QMouseEvent* event) {
    if (dragging_) {
        const double dy = event->position().y() - drag_start_y_;
        const auto view =
            pwb::viz::cross_well::preview_paned_view(layout_, dy);
        layout_.view_min_depth = view.first;
        layout_.view_max_depth = view.second;
        update();
        return;
    }
    const auto hit = pwb::viz::cross_well::preview_hover_hit(
        visible_points_, event->position().x(), event->position().y());
    const std::string key =
        hit.has_value()
            ? hit->well + "|" + hit->formation + "|" +
                  std::to_string(hit->depth)
            : std::string();
    if (key != hover_key_) {
        hover_key_ = key;
        if (hit.has_value()) {
            emit hovered_top_changed(QString::fromStdString(hit->well),
                                     QString::fromStdString(hit->formation),
                                     hit->depth);
        } else {
            emit hovered_top_changed(
                QString(), QString(),
                std::numeric_limits<double>::quiet_NaN());
        }
    }
}

void FormationTopsPreview::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton && dragging_) {
        dragging_ = false;
        setCursor(Qt::ArrowCursor);
        event->accept();
    }
}

void FormationTopsPreview::leaveEvent(QEvent*) {
    hover_key_.clear();
    emit hovered_top_changed(QString(), QString(),
                             std::numeric_limits<double>::quiet_NaN());
}

}  // namespace pwb::viz::cross_well::qt
