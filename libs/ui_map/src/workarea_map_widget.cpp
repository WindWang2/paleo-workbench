#include <pwb/ui_map/workarea_map_widget.hpp>

#include <cmath>
#include <utility>

#include <QPointF>
#include <QVBoxLayout>

#include <pwb/ui_map/display_map_canvas.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

WorkAreaMapWidget::WorkAreaMapWidget(QWidget* parent, std::string title,
                                     bool show_legend)
    : QWidget(parent), title_(std::move(title)), show_legend_(show_legend) {
    setObjectName(QStringLiteral("WorkAreaMapWidget"));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    map_canvas_ = new DisplayMapCanvas(this);
    map_canvas_->set_overlay_provider([this] { return overlay_state(); });
    connect(map_canvas_, &DisplayMapCanvas::map_clicked, this,
            [this](double x, double y) { on_map_clicked(x, y); });
    layout->addWidget(map_canvas_, 1);
}

void WorkAreaMapWidget::shutdown() { map_canvas_->shutdown(); }

// ---------------------------------------------------------------------------
// data
// ---------------------------------------------------------------------------

void WorkAreaMapWidget::set_project(
    const Json& project,
    const std::function<Json(const Json&)>& snapshot_builder) {
    if (project.is_null()) {
        snapshot_ = Json(nullptr);
        signature_ = Json(nullptr);
        return;
    }
    const Json signature = domain_signature(project);
    if (!signature_.is_null() && signature == signature_) {
        return;
    }
    signature_ = signature;
    Json snapshot =
        snapshot_builder ? snapshot_builder(project) : Json(nullptr);
    snapshot_ = snapshot;
    map_canvas_->set_layer_snapshot(snapshot);
    const std::optional<Extent> extent = workarea_view_extent(snapshot);
    if (extent.has_value()) {
        map_canvas_->set_extent(*extent);
    }
}

void WorkAreaMapWidget::zoom_to_all() {
    if (snapshot_.is_null()) {
        return;
    }
    const std::optional<Extent> extent = workarea_view_extent(snapshot_);
    if (extent.has_value()) {
        map_canvas_->set_extent(*extent);
    }
}

// ---------------------------------------------------------------------------
// selection
// ---------------------------------------------------------------------------

void WorkAreaMapWidget::select_well(const std::string& well_id, bool zoom,
                                    bool emit_signal) {
    selected_well_id_ = well_id;
    const Json feature = well_feature(well_id);
    if (zoom && feature.is_object()) {
        const Json coords = field_value(
            field_value(feature, "geometry", Json::object()),
            "coordinates", Json::array());
        if (coords.is_array() && coords.size() >= 2) {
            try {
                const double x = coords.at(0).get<double>();
                const double y = coords.at(1).get<double>();
                const double half = current_half_span() * 0.2;
                map_canvas_->set_extent(
                    Extent{x - half, y - half, x + half, y + half});
            } catch (const Json::exception&) {
                // Non-numeric coordinates — Python float() would raise and
                // the page lets it propagate; the widget stays put.
            }
        }
    }
    map_canvas_->update();
    if (emit_signal && !well_id.empty()) {
        emit well_selected(qstr(well_id));
    }
}

// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

Json WorkAreaMapWidget::overlay_state() const {
    return workarea_overlay_state(title_, show_legend_,
                                  well_feature(selected_well_id_));
}

Json WorkAreaMapWidget::well_feature(const std::string& well_id) const {
    if (well_id.empty() || snapshot_.is_null()) {
        return Json(nullptr);
    }
    return well_feature_by_id(snapshot_, well_id);
}

double WorkAreaMapWidget::current_half_span() const {
    const Extent extent = map_canvas_->view_extent();
    return std::max({(extent[2] - extent[0]) / 2.0,
                     (extent[3] - extent[1]) / 2.0, 1.0});
}

void WorkAreaMapWidget::on_map_clicked(double x, double y) {
    // Left-click: pick the nearest well within the screen tolerance.
    if (snapshot_.is_null()) {
        return;
    }
    const std::optional<QPointF> click_screen =
        map_canvas_->map_to_screen(x, y);
    if (!click_screen.has_value()) {
        // Python catches ArithmeticError here (#1166: a degenerate extent
        // used to leak a ZeroDivisionError through this path).
        return;
    }
    std::vector<WellPickCandidate> candidates;
    for (const WellFeature& well : well_candidates_from_snapshot(snapshot_)) {
        const std::optional<QPointF> screen =
            map_canvas_->map_to_screen(well.x, well.y);
        if (!screen.has_value()) {
            continue;
        }
        candidates.push_back(
            WellPickCandidate{well.well_id, screen->x(), screen->y()});
    }
    const std::string best = pick_well_id(
        {click_screen->x(), click_screen->y()}, candidates,
        kWellPickRadiusPx);
    if (!best.empty()) {
        select_well(best);
        emit well_selected(qstr(best));
        emit well_activated(qstr(best));
    }
}

}  // namespace pwb::ui_map
