// viz_c_time_map.cpp — 2D ActiveTimeSlice map (time_map_2d.py port).
#include "viz_c_time_map.hpp"

#include <QFont>
#include <QImage>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QPixmap>

#include <cmath>
#include <limits>
#include <map>

#include <pwb/geo3d_viz/joint/color_scales.hpp>

namespace pwb::app::viz_c {

using pwb::geo3d_viz::joint::VerticalDomain;
using pwb::geo3d_viz::joint::WellSeismicScene;

namespace {
const char* kEmptyText =
    "Time 平面：加载地震体后，将在此显示当前 Time 切片、井点和井名。\n"
    "点击井点连线；右侧显示井间剖面。";
}  // namespace

VizCTimeSliceMap::VizCTimeSliceMap(QWidget* parent) : QWidget(parent) {
    setMinimumHeight(160);
    setMinimumWidth(180);
    setStyleSheet("background: #0f172a;");
}

void VizCTimeSliceMap::set_scene(WellSeismicScene* scene) {
    scene_ = scene;
    refresh();
}

void VizCTimeSliceMap::refresh() {
    hits_.clear();
    pierces_.clear();
    path_ids_.clear();
    caption_.clear();
    if (scene_ == nullptr) {
        // Unbound (host teardown): the honest empty state, never a
        // dangling dereference.
        delete image_;
        image_ = nullptr;
        image_sample_ = -1;
        image_pending_ = false;
        update();
        return;
    }
    if (scene_->vertical_domain() != VerticalDomain::Time) {
        caption_ = tr("Time 平面仅在 Time 域可用");
        update();
        return;
    }
    const auto render_state = scene_->orthogonal_slice_render_state();
    if (!render_state.has_value()) {
        caption_ = tr(kEmptyText);
        update();
        return;
    }
    const auto [il, xl, times, active, opacity] = *render_state;
    (void)il;
    (void)xl;
    (void)times;
    (void)opacity;
    // 06: no volume read here (the worker prepares the plane). An image
    // from an older sample is replaced by the honest pending note until
    // the host applies the fresh payload.
    if (image_ != nullptr && image_sample_ != active) {
        delete image_;
        image_ = nullptr;
        image_sample_ = -1;
    }
    image_pending_ = image_ == nullptr;
    const auto active_ms = scene_->orthogonal_slice_state().active_time_ms;
    caption_ = active_ms.has_value()
                   ? tr("Time 平面  %1 ms").arg(
                         std::llround(*active_ms))
                   : tr("Time 平面");
    pierces_ = scene_->pierce_points_on_active_time();
    for (const auto& id : scene_->fence_well_ids()) {
        path_ids_.push_back(QString::fromStdString(id));
    }
    recompute_hits();
    update();
}

void VizCTimeSliceMap::set_prepared_slice(
    const std::vector<unsigned char>& rgba, std::int64_t n_inline,
    std::int64_t n_crossline, std::int64_t sample_index) {
    delete image_;
    image_ = nullptr;
    image_sample_ = -1;
    image_pending_ = false;
    if (rgba.empty() || n_inline <= 0 || n_crossline <= 0 ||
        rgba.size() != static_cast<std::size_t>(n_inline * n_crossline) * 4) {
        update();
        return;
    }
    QImage raw(reinterpret_cast<const unsigned char*>(rgba.data()),
               static_cast<int>(n_crossline), static_cast<int>(n_inline),
               static_cast<int>(n_crossline) * 4,
               QImage::Format_RGBA8888);
    image_ = new QImage(raw.copy());
    image_sample_ = sample_index;
    // Drop the pending note right away if the payload already matches.
    if (scene_ != nullptr) {
        if (const auto render_state = scene_->orthogonal_slice_render_state();
            render_state.has_value() &&
            std::get<3>(*render_state) == sample_index) {
            image_pending_ = false;
        }
    }
    update();
}

void VizCTimeSliceMap::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    recompute_hits();
    update();
}

namespace {
QRect plot_rect(const QWidget* w) {
    return w->rect().adjusted(8, 22, -8, -8);
}
}  // namespace

void VizCTimeSliceMap::recompute_hits() {
    hits_.clear();
    if (scene_ == nullptr || image_ == nullptr) return;
    const pwb::geo3d_viz::joint::VolumeRegistration* registration =
        scene_->registration();
    if (registration == nullptr) return;
    const QRect rect = plot_rect(this);
    if (rect.width() < 8 || rect.height() < 8) return;
    const std::int64_t ni = image_->height();
    const std::int64_t nx = image_->width();
    for (const auto& pierce : pierces_) {
        const auto [vi, vx] =
            registration->xy_to_volume_idx(pierce.x, pierce.y);
        const double px =
            rect.left() + (vx + 0.5) / static_cast<double>(std::max<std::int64_t>(nx, 1)) *
                              (rect.width() - 1);
        const double py =
            rect.top() + (vi + 0.5) / static_cast<double>(std::max<std::int64_t>(ni, 1)) *
                              (rect.height() - 1);
        hits_.push_back({px, py});
    }
}

void VizCTimeSliceMap::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.fillRect(rect(), QColor(15, 23, 42));
    painter.setPen(QColor(226, 232, 240));
    painter.setFont(QFont("Sans Serif", 10, QFont::DemiBold));
    painter.drawText(8, 16, caption_.isEmpty() ? tr("Time 平面") : caption_);
    const QRect rect = plot_rect(this);
    if (image_ == nullptr) {
        painter.setPen(QColor(148, 163, 184));
        painter.setFont(QFont("Sans Serif", 10));
        // Distinguish "nothing loaded" from "worker read in flight" —
        // both are honest, but the pending state must not read as empty.
        const bool pending = image_pending_ && scene_ != nullptr &&
                             scene_->orthogonal_slice_render_state()
                                 .has_value() &&
                             scene_->vertical_domain() ==
                                 VerticalDomain::Time;
        painter.drawText(rect,
                         int(Qt::AlignmentFlag::AlignCenter |
                             Qt::TextFlag::TextWordWrap),
                         pending ? tr("正在后台读取 Time 切片…")
                                 : tr(kEmptyText));
        return;
    }
    const QPixmap scaled =
        QPixmap::fromImage(*image_).scaled(
            rect.size(), Qt::AspectRatioMode::IgnoreAspectRatio,
            Qt::TransformationMode::SmoothTransformation);
    painter.drawPixmap(rect.topLeft(), scaled);
    std::map<QString, std::array<double, 2>> by_id;
    for (std::size_t i = 0; i < pierces_.size() && i < hits_.size(); ++i) {
        const auto& pierce = pierces_[i];
        const double px = hits_[i][0];
        const double py = hits_[i][1];
        by_id.emplace(QString::fromStdString(pierce.well_id),
                      std::array<double, 2>{px, py});
        painter.setPen(QPen(QColor(15, 23, 42), 3));
        painter.setBrush(QColor(250, 204, 21));
        painter.drawEllipse(int(px) - 5, int(py) - 5, 10, 10);
        painter.setPen(QPen(QColor(250, 204, 21), 1));
        painter.drawEllipse(int(px) - 5, int(py) - 5, 10, 10);
        painter.setFont(QFont("Sans Serif", 9, QFont::Bold));
        painter.setPen(QColor(15, 23, 42));
        painter.drawText(int(px) + 8, int(py) + 1,
                         QString::fromStdString(pierce.display_name));
        painter.setPen(QColor(254, 240, 138));
        painter.drawText(int(px) + 7, int(py),
                         QString::fromStdString(pierce.display_name));
    }
    std::vector<std::array<double, 2>> pts;
    for (const QString& id : path_ids_) {
        const auto it = by_id.find(id);
        if (it != by_id.end()) pts.push_back(it->second);
    }
    if (pts.size() >= 2) {
        painter.setPen(QPen(QColor(34, 211, 238), 2));
        for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
            painter.drawLine(int(pts[i][0]), int(pts[i][1]),
                             int(pts[i + 1][0]), int(pts[i + 1][1]));
        }
    }
}

void VizCTimeSliceMap::mousePressEvent(QMouseEvent* event) {
    if (event->button() != Qt::LeftButton || hits_.empty()) return;
    const QPointF pos = event->position();
    int best = -1;
    double best_dist = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < hits_.size() && i < pierces_.size(); ++i) {
        const double dx = hits_[i][0] - pos.x();
        const double dy = hits_[i][1] - pos.y();
        const double dist = dx * dx + dy * dy;
        if (dist <= 18.0 * 18.0 &&
            (best < 0 || dist < best_dist)) {
            best = static_cast<int>(i);
            best_dist = dist;
        }
    }
    if (best >= 0) {
        emit well_clicked(
            QString::fromStdString(pierces_[static_cast<std::size_t>(best)].well_id));
    }
}

}  // namespace pwb::app::viz_c
