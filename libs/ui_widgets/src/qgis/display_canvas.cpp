#include "pwb/ui_widgets/qgis/display_canvas.hpp"

#include "pwb/ui_widgets/map_chrome.hpp"
#include "pwb/ui_widgets/qgis/mirror_snapshot.hpp"
#include "pwb/ui_widgets/qgis/qgis_widgets.hpp"
#include "pwb/ui_widgets/qgis/stack_events.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <pwb/qgis/map_session.hpp>

#include <QEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QResizeEvent>
#include <QVBoxLayout>

#include <cmath>

#include <qgsmapcanvas.h>
#include <qgsmaptoolpan.h>
#include <qgspointxy.h>
#include <qgsproject.h>
#include <qgsrectangle.h>

namespace pwb::ui_widgets::qgis {
namespace {

// Left-click (press+release without a >6px drag) → map_click. The
// Python _ClickFilter contract, installed on canvas + viewport.
class ClickFilter : public QObject {
public:
    explicit ClickFilter(QgisDisplayCanvas* host) : QObject(host), host_(host) {}

    bool eventFilter(QObject* obj, QEvent* event) override {
        if (event->type() == QEvent::MouseButtonPress) {
            auto* mouse = static_cast<QMouseEvent*>(event);
            if (mouse->button() == Qt::LeftButton) {
                press_ = mouse->position();
            }
        } else if (event->type() == QEvent::MouseButtonRelease) {
            auto* mouse = static_cast<QMouseEvent*>(event);
            if (mouse->button() == Qt::LeftButton && press_.has_value()) {
                const QPointF press = *press_;
                press_.reset();
                if ((mouse->position() - press).manhattanLength() < 6) {
                    host_->emit_map_click(mouse->position());
                }
            }
        }
        return false;
    }

private:
    QgisDisplayCanvas* host_;
    std::optional<QPointF> press_;
};

}  // namespace

// Full-viewport decorations overlay (selection circles + map chrome).
// Transparent for mouse events; parents onto the canvas viewport.
class DisplayOverlay : public QWidget {
public:
    explicit DisplayOverlay(QgisDisplayCanvas* host) : QWidget(nullptr), host_(host) {
        setAttribute(Qt::WA_TransparentForMouseEvents, true);
        setAttribute(Qt::WA_TranslucentBackground, true);
        setAttribute(Qt::WA_NoSystemBackground, true);
        setAutoFillBackground(false);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        const QVariantMap state = host_->overlay_state();
        if (state.isEmpty()) {
            return;
        }
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        // Selected feature point circles in the canvas-selection token
        // color (Python: tokens CANVAS_SELECTION via theme palette).
        const QVariantList selected =
            state.value(QStringLiteral("selected_features")).toList();
        if (!selected.isEmpty()) {
            const QString token =
                palette_token("CANVAS_SELECTION");
            QColor pen_color(token.isEmpty() ? QStringLiteral("#2f7ed8")
                                             : token);
            painter.setPen(QPen(pen_color, 2.0));
            painter.setBrush(Qt::NoBrush);
            for (const QVariant& feature : selected) {
                const QVariantMap geom =
                    feature.toMap()
                        .value(QStringLiteral("geometry"))
                        .toMap();
                if (geom.value(QStringLiteral("type")).toString() !=
                    QLatin1String("Point")) {
                    continue;
                }
                const QVariantList coords =
                    geom.value(QStringLiteral("coordinates")).toList();
                if (coords.size() < 2) {
                    continue;
                }
                const QPointF screen = host_->map_to_screen(
                    {coords[0].toDouble(), coords[1].toDouble()});
                painter.drawEllipse(screen, 8.0, 8.0);
            }
        }
        const QVariantMap decorations = ensure_basic_map_chrome(
            state.value(QStringLiteral("decorations")).toMap());
        paint_map_decorations(painter, decorations, width(), height(),
                              host_->view_extent(), 1.0,
                              /*dark_chrome=*/true);
        painter.end();
    }

private:
    QgisDisplayCanvas* host_;
};

QgisDisplayCanvas::QgisDisplayCanvas(QWidget* parent)
    : QWidget(parent),
      session_(std::make_unique<pwb::qgis::MapSession>()),
      ledger_(std::make_unique<MirrorLedger>()) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    host_ = new QgisCanvasHost(*session_, this);
    layout->addWidget(host_);
    canvas_ = host_->canvas();

    events_ = new StackEvents(this);
    events_->attach(canvas_);
    connect(events_, &StackEvents::extent_changed, this,
            &QgisDisplayCanvas::on_stack_extent);
    connect(events_, &StackEvents::map_position_changed, this,
            [this](double x, double y) {
                emit map_position_changed({x, y});
            });

    overlay_ = new DisplayOverlay(this);
    click_filter_ = new ClickFilter(this);
    canvas_->installEventFilter(click_filter_);
    if (QWidget* viewport = canvas_viewport(canvas_)) {
        viewport->installEventFilter(click_filter_);
        overlay_->setParent(viewport);
    }
    install_chrome_overlay();

    // Read-only pan — the Python display canvas arms the native pan
    // tool and nothing else.
    canvas_->setMapTool(new QgsMapToolPan(canvas_));

    // Bookkeeping only during Qt destruction — no session teardown on
    // the destroyed path (a half-destroyed canvas must never re-enter
    // QGIS APIs; orderly shutdown() is the host's call).
    connect(this, &QObject::destroyed, this,
            [this] { mark_disposed(); });
}

QgisDisplayCanvas::~QgisDisplayCanvas() {
    // Session teardown is ordered: canvas/tools first, then the project
    // (MapSession::close() enforces it; the destructor covers hosts that
    // never called shutdown()).
    shutdown();
}

void QgisDisplayCanvas::record_extent(const std::array<double, 4>& tup,
                                      bool coalesce) {
    if (extent_history_index_ < int(extent_history_.size()) - 1) {
        extent_history_.resize(size_t(extent_history_index_) + 1);
    }
    if (coalesce && !extent_history_.empty()) {
        extent_history_.back() = tup;
    } else if (extent_history_.empty() ||
               extent_history_.back() != tup) {
        extent_history_.push_back(tup);
        if (extent_history_.size() > 100) {
            extent_history_.erase(extent_history_.begin());
        }
        extent_history_index_ = int(extent_history_.size()) - 1;
    }
}

void QgisDisplayCanvas::on_stack_extent(double xmin, double ymin,
                                        double xmax, double ymax) {
    const std::array<double, 4> tup{xmin, ymin, xmax, ymax};
    if (pending_programmatic_) {
        pending_programmatic_ = false;
        emit extent_changed(tup);
        overlay_->update();
        return;
    }
    record_extent(tup, false);
    emit extent_changed(tup);
    emit tool_operation(false);
    overlay_->update();
}

std::array<double, 4> QgisDisplayCanvas::view_extent() const {
    if (canvas_ != nullptr && !shutdown_done_) {
        const QgsRectangle e = canvas_->extent();
        return {e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()};
    }
    if (!extent_history_.empty()) {
        return extent_history_[size_t(extent_history_index_)];
    }
    return {0.0, 0.0, 1.0, 1.0};
}

void QgisDisplayCanvas::set_extent(const std::array<double, 4>& extent,
                                   bool record_history,
                                   bool coalesce_history) {
    if (record_history) {
        record_extent(extent, coalesce_history);
    }
    pending_programmatic_ = true;
    if (canvas_ != nullptr) {
        canvas_->setExtent(
            QgsRectangle(extent[0], extent[1], extent[2], extent[3]));
        canvas_->refresh();
    }
    emit extent_changed(extent);
    overlay_->update();
}

void QgisDisplayCanvas::zoom_by(double factor,
                                std::pair<double, double> center,
                                bool has_center,
                                bool coalesce_history) {
    if (!(factor > 0.0) || !std::isfinite(factor)) {
        throw std::invalid_argument("zoom factor must be positive");
    }
    const auto [xmin, ymin, xmax, ymax] = view_extent();
    const double cx = has_center ? center.first : (xmin + xmax) / 2.0;
    const double cy = has_center ? center.second : (ymin + ymax) / 2.0;
    set_extent({cx + (xmin - cx) * factor, cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor, cy + (ymax - cy) * factor},
               true, coalesce_history);
}

bool QgisDisplayCanvas::previous_extent() {
    if (!can_previous_extent()) return false;
    --extent_history_index_;
    set_extent(extent_history_[size_t(extent_history_index_)],
               /*record_history=*/false);
    return true;
}

bool QgisDisplayCanvas::next_extent() {
    if (!can_next_extent()) return false;
    ++extent_history_index_;
    set_extent(extent_history_[size_t(extent_history_index_)],
               /*record_history=*/false);
    return true;
}

QPointF QgisDisplayCanvas::map_to_screen(
    std::pair<double, double> point) const {
    if (canvas_ == nullptr) return {};
    const QgsPointXY screen = canvas_->mapSettings().mapToPixel().transform(
        QgsPointXY(point.first, point.second));
    return {screen.x(), screen.y()};
}

std::pair<double, double> QgisDisplayCanvas::screen_to_map(
    std::pair<double, double> point) const {
    if (canvas_ == nullptr) return {0.0, 0.0};
    const QgsPointXY map_pt =
        canvas_->getCoordinateTransform()->toMapCoordinates(
            int(point.first), int(point.second));
    return {map_pt.x(), map_pt.y()};
}

double QgisDisplayCanvas::map_units_per_pixel() const {
    if (canvas_ == nullptr) return 1.0;
    return canvas_->mapUnitsPerPixel();
}

void QgisDisplayCanvas::set_overlay_provider(
    std::function<QVariantMap()> provider) {
    overlay_provider_ = std::move(provider);
    overlay_->update();
}

void QgisDisplayCanvas::set_layer_snapshot(const MirrorSnapshot& snapshot) {
    if (shutdown_done_ || session_ == nullptr ||
        session_->project() == nullptr) {
        return;
    }
    MirrorOptions options;
    options.refresh_window = canvas_;
    const MirrorResult result = mirror_snapshot_to_project(
        *session_->project(), snapshot, options, *ledger_);
    mirror_failures_ = result.failures;
    // snapshot_source_version_ids parity: deduped first-seen order.
    QStringList ids;
    for (const MirrorLayerSpec& layer : snapshot.layers) {
        if (!layer.source_version_id.isEmpty() &&
            !ids.contains(layer.source_version_id)) {
            ids.append(layer.source_version_id);
        }
    }
    snapshot_version_ids_ = ids;
    overlay_->update();
    emit backend_status_changed(backend_status());
}

QString QgisDisplayCanvas::backend_status() const {
    // #1164 parity: mirror failures degrade the reported status on both
    // canvas kinds — silent divergence is not an option.
    if (!mirror_failures_.isEmpty()) {
        return QStringLiteral("qgis: degraded (%1 mirror failures)")
            .arg(mirror_failures_.size());
    }
    return QStringLiteral("qgis");
}

QStringList QgisDisplayCanvas::snapshot_source_version_ids() const {
    return snapshot_version_ids_;
}

void QgisDisplayCanvas::emit_map_click(const QPointF& pos) {
    emit map_clicked(screen_to_map({pos.x(), pos.y()}));
}

QVariantMap QgisDisplayCanvas::overlay_state() const {
    return overlay_provider_ ? overlay_provider_() : QVariantMap();
}

void QgisDisplayCanvas::install_chrome_overlay() {
    if (overlay_ == nullptr) {
        return;
    }
    QWidget* host = canvas_viewport(canvas_);
    if (host == nullptr) {
        host = this;
    }
    if (overlay_->parentWidget() != host) {
        overlay_->setParent(host);
    }
    overlay_->setGeometry(host->rect());
    overlay_->raise();
    overlay_->show();
}

void QgisDisplayCanvas::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    install_chrome_overlay();
}

void QgisDisplayCanvas::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    install_chrome_overlay();
}

void QgisDisplayCanvas::shutdown() {
    if (shutdown_done_) {
        return;
    }
    shutdown_done_ = true;
    if (session_ != nullptr) {
        session_->close();
    }
}

void QgisDisplayCanvas::mark_disposed() {
    // Bookkeeping ONLY: record disposal state. Never destroy the session
    // here — destroyed() fires while the widget tree (and the canvas
    // with it) is half-destroyed; ~MapSession() would re-enter a dead
    // canvas. The unique_ptr member is destroyed during normal member
    // teardown, which runs before QObject::~QObject deletes children —
    // the canvas is still alive at that point, so the session teardown
    // is safe there.
    shutdown_done_ = true;
    canvas_ = nullptr;
}

void QgisDisplayCanvas::closeEvent(QCloseEvent* event) {
    shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_widgets::qgis
