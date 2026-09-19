#include "pwb/ui_pages_mapedit/map_edit_view.hpp"

#include "pwb/ui_pages_mapedit/map_edit_scene.hpp"
#include "pwb/ui_shell/style_registry.hpp"

#include <QKeyEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QTimer>
#include <QWheelEvent>

#include <cmath>

namespace pwb::ui_pages_mapedit {
namespace {

// _view_qss(): QGraphicsView#MapEditView themed sheet.
QString view_qss() {
    const auto& p = ui_shell::style_palette();
    const auto get = [&p](const char* k) {
        const auto it = p.find(k);
        return it != p.end() ? QString::fromStdString(it->second) : QString();
    };
    return QStringLiteral(
               "QGraphicsView#MapEditView { background: %1;"
               " border: 1px solid %2; border-radius: %3px; }")
        .arg(get("BG_SEARCH"), get("BORDER"), get("RADIUS_CARD"));
}

// _same_view_state — integer scrollbars round the center, so equality is
// tolerant (abs 1.5 on center, rel 1e-9 on scale).
bool same_view_state(const QVariantMap& a, const QVariantMap& b) {
    const auto center_of = [](const QVariantMap& m) {
        const QVariant c = m.value(QStringLiteral("center"));
        const auto l = c.toList();
        return l.size() >= 2
                   ? std::pair{l[0].toDouble(), l[1].toDouble()}
                   : std::pair{0.0, 0.0};
    };
    const auto [ax, ay] = center_of(a);
    const auto [bx, by] = center_of(b);
    const auto isclose = [](double x, double y, double abs_tol) {
        return std::fabs(x - y) <= abs_tol;
    };
    const double as = a.value(QStringLiteral("scale"), 1.0).toDouble();
    const double bs = b.value(QStringLiteral("scale"), 1.0).toDouble();
    // math.isclose(rel_tol=1e-9, abs_tol=0): tol scales with the larger
    // magnitude — no absolute floor.
    const double scale_tol =
        1e-9 * std::max(std::fabs(as), std::fabs(bs));
    return isclose(ax, bx, 1.5) && isclose(ay, by, 1.5) &&
           std::fabs(as - bs) <= scale_tol;
}

}  // namespace

MapEditView::MapEditView(QWidget* parent) : QGraphicsView(parent) {
    setObjectName(QStringLiteral("MapEditView"));
    // E1：动态注册（style.bind）——主题切换时按当前 palette 重渲染。
    ui_shell::style_bind(this, &view_qss);
    setRenderHint(QPainter::Antialiasing, true);
    setDragMode(QGraphicsView::NoDrag);
    setTransformationAnchor(QGraphicsView::AnchorUnderMouse);
    setResizeAnchor(QGraphicsView::AnchorUnderMouse);
    setViewportUpdateMode(QGraphicsView::SmartViewportUpdate);
    setFocusPolicy(Qt::StrongFocus);
    setMouseTracking(true);
    shared_view_state_ = {
        {QStringLiteral("center"), QVariantList{0.0, 0.0}},
        {QStringLiteral("scale"), 1.0},
    };
    // Navigation display LOD state (display-only; restored after idle).
    nav_lod_timer_ = new QTimer(this);
    nav_lod_timer_->setSingleShot(true);
    nav_lod_timer_->setInterval(kNavLodIdleMs);
    connect(nav_lod_timer_, &QTimer::timeout, this,
            [this]() { end_navigation_lod(); });

    setScene(new MapEditScene(this));
}

MapEditScene* MapEditView::edit_scene() const {
    return dynamic_cast<MapEditScene*>(scene());
}

// --- navigation display LOD -------------------------------------------------

void MapEditView::begin_navigation_lod() {
    // Enter low-detail mode for wheel/pan; an idle timer restores detail.
    if (!nav_lod_active_) {
        nav_lod_active_ = true;
        setRenderHint(QPainter::Antialiasing, false);
        setOptimizationFlags(QGraphicsView::DontAdjustForAntialiasing |
                             QGraphicsView::DontSavePainterState);
        if (auto* edit = edit_scene()) {
            edit->set_navigation_lod(true);
        }
    }
    nav_lod_timer_->start();  // restart the idle countdown
}

void MapEditView::end_navigation_lod() {
    if (!nav_lod_active_) {
        return;
    }
    nav_lod_active_ = false;
    nav_lod_timer_->stop();
    setRenderHint(QPainter::Antialiasing, true);
    setOptimizationFlags(QGraphicsView::OptimizationFlags());
    if (auto* edit = edit_scene()) {
        edit->set_navigation_lod(false);
    }
    viewport()->update();
    // Pan only reaches the view state here (wheel emits directly in
    // wheelEvent). Publish the settled state, but skip when unchanged so
    // apply_view_state(emit=false) and idle LOD cycles never echo.
    const QVariantMap new_state = read_view_state();
    if (!same_view_state(new_state, shared_view_state_)) {
        shared_view_state_ = new_state;
        emit view_state_changed(view_state());
    }
}

// --- events -----------------------------------------------------------------

void MapEditView::wheelEvent(QWheelEvent* event) {
    // Zoom with mouse wheel (no geometry change); low-detail while scrolling.
    const int delta = event->angleDelta().y();
    if (delta == 0) {
        event->ignore();
        return;
    }
    begin_navigation_lod();
    const double factor = delta > 0 ? 1.15 : 1.0 / 1.15;
    scale(factor, factor);
    shared_view_state_ = read_view_state();
    emit view_state_changed(view_state());
    event->accept();
}

void MapEditView::mouseMoveEvent(QMouseEvent* event) {
    // Publish the cursor in scene coordinates (project CRS).
    const QPointF pos = mapToScene(event->position().toPoint());
    emit cursor_position_changed(pos.x(), pos.y());
    QGraphicsView::mouseMoveEvent(event);
}

void MapEditView::scrollContentsBy(int dx, int dy) {
    // Any pan (scrollbars, keyboard, centerOn) engages navigation LOD.
    if (dx || dy) {
        begin_navigation_lod();
    }
    QGraphicsView::scrollContentsBy(dx, dy);
}

QVariantMap MapEditView::read_view_state() const {
    const QPointF center = mapToScene(viewport()->rect().center());
    return {
        {QStringLiteral("center"),
         QVariantList{center.x(), center.y()}},
        {QStringLiteral("scale"), transform().m11()},
    };
}

void MapEditView::apply_view_state(const QVariantMap& state,
                                   bool emit_change) {
    const QVariant c = state.value(QStringLiteral("center"));
    const auto l = c.toList();
    const double cx = l.size() >= 1 ? l[0].toDouble() : 0.0;
    const double cy = l.size() >= 2 ? l[1].toDouble() : 0.0;
    const double s = state.value(QStringLiteral("scale"), 1.0).toDouble();
    resetTransform();
    scale(s, s);
    centerOn(cx, cy);
    shared_view_state_ = {
        {QStringLiteral("center"), QVariantList{cx, cy}},
        {QStringLiteral("scale"), s},
    };
    if (emit_change) {
        emit view_state_changed(view_state());
    }
}

void MapEditView::reset_view() {
    resetTransform();
    if (scene() != nullptr) {
        fitInView(scene()->sceneRect(), Qt::KeepAspectRatio);
    }
}

void MapEditView::keyPressEvent(QKeyEvent* event) {
    if (auto* edit = edit_scene()) {
        edit->key_press(event);
        if (event->isAccepted()) {
            return;
        }
    }
    QGraphicsView::keyPressEvent(event);
}

}  // namespace pwb::ui_pages_mapedit
