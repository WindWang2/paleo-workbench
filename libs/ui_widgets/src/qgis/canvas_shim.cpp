#include "pwb/ui_widgets/qgis/canvas_shim.hpp"

#include "pwb/ui_widgets/map_chrome.hpp"
#include "pwb/ui_widgets/qgis/mirror_snapshot.hpp"
#include "pwb/ui_widgets/qgis/qgis_widgets.hpp"
#include "pwb/ui_widgets/qgis/stack_events.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <pwb/qgis/map_session.hpp>

#include <QApplication>
#include <QEvent>
#include <QEventLoop>
#include <QFile>
#include <QKeyEvent>
#include <QLoggingCategory>
#include <QMouseEvent>
#include <QPainter>
#include <QPrinter>
#include <QResizeEvent>
#include <QShowEvent>
#include <QSvgGenerator>
#include <QTimer>
#include <QVBoxLayout>

#include <chrono>
#include <cmath>
#include <set>

#include <qgscoordinatereferencesystem.h>
#include <qgsfeature.h>
#include <qgsfeatureiterator.h>
#include <qgsfields.h>
#include <qgshighlight.h>
#include <qgslayertree.h>
#include <qgslayertreegroup.h>
#include <qgslayertreelayer.h>
#include <qgsmapcanvas.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgsmapsettings.h>
#include <qgsmaprenderercustompainterjob.h>
#include <qgspointxy.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgssnappingconfig.h>
#include <qgssnappingutils.h>
#include <qgsunittypes.h>
#include <qgsvectorlayer.h>

namespace pwb::ui_widgets::qgis {
namespace {

Q_LOGGING_CATEGORY(lcCanvasShim, "pwb.ui_widgets.canvas_shim")

// Cross-test/cross-document live-shim registry (Python _LIVE_SHIMS +
// shutdown_live_shims parity): non-display canvases mirror layers into
// their session project; hosts that skip explicit shutdown would leak
// teardown ordering — the registry gives shell teardown / tests a
// deterministic cleanup point without changing single-instance
// lifecycle semantics.
std::set<QPointer<QgisCanvasShim>>& live_shims() {
    static std::set<QPointer<QgisCanvasShim>> shims;
    return shims;
}

void prepare_chrome_widget(QWidget* widget) {
    widget->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    widget->setAttribute(Qt::WA_TranslucentBackground, true);
    widget->setAttribute(Qt::WA_NoSystemBackground, true);
    widget->setAutoFillBackground(false);
}

// Bottom-left scale bar (small widget — must not cover the map).
class ScaleChrome : public QWidget {
public:
    explicit ScaleChrome(QgisCanvasShim* host, QWidget* parent = nullptr)
        : QWidget(parent), host_(host) {
        prepare_chrome_widget(this);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        if (host_->is_shutdown()) {
            return;
        }
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        const int map_width = std::max(1, host_->chrome_map_size().first);
        paint_scale_bar(painter, host_->view_extent(), map_width,
                        height(), 1.0, kChromeInkOnLightBody);
        painter.end();
    }

private:
    QgisCanvasShim* host_;
};

// Top-left north arrow.
class NorthChrome : public QWidget {
public:
    explicit NorthChrome(QgisCanvasShim* host, QWidget* parent = nullptr)
        : QWidget(parent), host_(host) {
        prepare_chrome_widget(this);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        const QPointF center(width() / 2.0, 28.0);
        painter.setPen(QPen(kChromeInkOnLightBody, 1.5));
        painter.setBrush(kChromeInkOnDarkBody);
        painter.drawPolygon(QPolygonF({center + QPointF(0, -18),
                                       center + QPointF(-6, 10),
                                       center + QPointF(0, 5),
                                       center + QPointF(6, 10)}));
        QFont font = painter.font();
        font.setPixelSize(10);
        painter.setFont(font);
        painter.setPen(kChromeInkOnLightBody);
        painter.drawText(center + QPointF(-5, -22), "N");
        painter.end();
    }

private:
    QgisCanvasShim* host_;
};

// Bottom-right workspace legend (elements whitelist = 图例 only).
class LegendChrome : public QWidget {
public:
    explicit LegendChrome(QgisCanvasShim* host, QWidget* parent = nullptr)
        : QWidget(parent), host_(host) {
        prepare_chrome_widget(this);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        if (host_->is_shutdown()) {
            return;
        }
        const QVariantMap state = host_->overlay_state();
        QVariantMap decorations =
            state.value(QStringLiteral("decorations")).toMap();
        decorations.insert(QStringLiteral("elements"),
                           QStringList{QStringLiteral("图例")});
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        paint_map_decorations(painter, decorations, width(), height(),
                              host_->view_extent(), 1.0,
                              /*dark_chrome=*/true);
        painter.end();
    }

private:
    QgisCanvasShim* host_;
};

}  // namespace

// ------------------------------------------------------- CanvasMouseRouter

// Measure-fallback router: while the fallback measure tool is active,
// viewport mouse events are converted to map coordinates and fed to the
// host's measure tool (right button = cancel). Button events are
// consumed; MouseMove is only observed (status-bar xy stays live and
// pan never starts a drag — press was already intercepted).
class CanvasMouseRouter : public QObject {
public:
    explicit CanvasMouseRouter(QgisCanvasShim* shim) : QObject(shim), shim_(shim) {}

    void set_active(bool active) {
        active_ = active;
        QWidget* viewport = shim_->canvas_viewport();
        if (installed_on_ != nullptr && installed_on_ != viewport) {
            installed_on_->removeEventFilter(this);
            installed_on_ = nullptr;
        }
        if (active && viewport != nullptr && installed_on_ != viewport) {
            viewport->installEventFilter(this);
            installed_on_ = viewport;
        }
    }

    void detach() {
        active_ = false;
        if (installed_on_ != nullptr) {
            installed_on_->removeEventFilter(this);
            installed_on_ = nullptr;
        }
    }

protected:
    bool eventFilter(QObject* obj, QEvent* event) override {
        if (!active_ || shim_->is_shutdown()) {
            return false;
        }
        switch (event->type()) {
            case QEvent::MouseButtonPress:
            case QEvent::MouseButtonRelease:
            case QEvent::MouseButtonDblClick:
            case QEvent::MouseMove:
                break;
            default:
                return false;
        }
        return shim_->route_measure_mouse(
            static_cast<QMouseEvent*>(event));
    }

private:
    QgisCanvasShim* shim_;
    bool active_ = false;
    QPointer<QWidget> installed_on_;
};

// --------------------------------------------------------- dispatch_edit_pick

bool dispatch_edit_pick(QgisCanvasShim& shim,
                        ToolHooks* tool,
                        const QString& action,
                        const QVariantMap& payload) {
    bool ok = false;
    QString rejection;
    try {
        if (action == QLatin1String("vertex_moved") && tool != nullptr &&
            tool->commit_vertex_move) {
            const QVariantList path =
                payload.value(QStringLiteral("path")).toList();
            ok = tool->commit_vertex_move(
                payload.value(QStringLiteral("feature_id")).toString(),
                path,
                {payload.value(QStringLiteral("x")).toDouble(),
                 payload.value(QStringLiteral("y")).toDouble()});
        } else if (action == QLatin1String("feature_moved") &&
                   tool != nullptr && tool->commit_move) {
            ok = tool->commit_move(
                payload.value(QStringLiteral("feature_id")).toString(),
                payload.value(QStringLiteral("dx")).toDouble(),
                payload.value(QStringLiteral("dy")).toDouble());
        } else if (action == QLatin1String("vertex_inserted") &&
                   tool != nullptr && tool->commit_vertex_insert) {
            ok = tool->commit_vertex_insert(
                payload.value(QStringLiteral("feature_id")).toString(),
                payload.value(QStringLiteral("path")).toList(),
                {payload.value(QStringLiteral("x")).toDouble(),
                 payload.value(QStringLiteral("y")).toDouble()});
        } else if (action == QLatin1String("vertex_deleted") &&
                   tool != nullptr && tool->commit_vertex_delete) {
            ok = tool->commit_vertex_delete(
                payload.value(QStringLiteral("feature_id")).toString(),
                payload.value(QStringLiteral("path")).toList());
        } else if (action == QLatin1String("vertex_delete_rejected")) {
            rejection = QStringLiteral(
                "节点删除未生效：低于最少顶点或未悬停在可删除的顶点上");
        } else if (action == QLatin1String("snap_feedback")) {
            emit shim.snap_feedback(payload);
        }
    } catch (...) {
        ok = false;
    }
    if (ok) {
        emit shim.tool_operation(true);
        return true;
    }
    if (rejection.isEmpty() &&
        (action == QLatin1String("vertex_inserted") ||
         action == QLatin1String("vertex_deleted") ||
         action == QLatin1String("vertex_moved"))) {
        // ADV-2 receipts: a rejected vertex edit must be perceivable —
        // never a silent dead key.
        rejection = QStringLiteral(
            "节点编辑未写入：会话校验未通过（目标要素/路径已变化或低于最少顶点）");
    }
    if (!rejection.isEmpty()) {
        emit shim.commit_rejected(rejection);
        emit shim.tool_operation(false);
    }
    return false;
}

// -------------------------------------------------------------- QgisCanvasShim

QgisCanvasShim::QgisCanvasShim(QWidget* parent)
    : QWidget(parent),
      session_(std::make_unique<pwb::qgis::MapSession>()),
      ledger_(std::make_unique<MirrorLedger>()) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    host_ = new QgisCanvasHost(*session_, this);
    layout->addWidget(host_);
    canvas_ = host_->canvas();
    canvas_created_ = canvas_ != nullptr;
    canvas_destroyed_ = false;

    events_ = new StackEvents(this);
    events_->attach(canvas_);
    connect(events_, &StackEvents::extent_changed, this,
            [this](double xmin, double ymin, double xmax, double ymax) {
                on_stack_extent(xmin, ymin, xmax, ymax);
                refresh_chrome_overlay();
            });
    connect(events_, &StackEvents::map_position_changed, this,
            [this](double x, double y) {
                emit map_position_changed({x, y});
            });

    install_chrome_overlay();

    // Context-menu entry: right-click -> map coordinates (the host's
    // facies-change menu consumes map coords only).
    canvas_->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(canvas_, &QWidget::customContextMenuRequested, this,
            &QgisCanvasShim::on_canvas_context_menu);

    measure_router_ = new CanvasMouseRouter(this);

    // Default tool: pan (set_map_tool_controller forces pan on bind —
    // preserved as the initial arm).
    arm_tool(QStringLiteral("pan"));

    connect(this, &QObject::destroyed, this, [this] { mark_disposed(); });
    connect(canvas_, &QObject::destroyed, this,
            [this] { mark_disposed(); });

    CanvasExtent initial{0.0, 0.0, 1.0, 1.0};
    if (canvas_ != nullptr) {
        const QgsRectangle e = canvas_->extent();
        initial = {e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()};
    }
    extent_history_ = {initial};
    extent_history_index_ = 0;
    last_emitted_extent_ = initial;

    live_shims().insert(QPointer<QgisCanvasShim>(this));
}

QgisCanvasShim::~QgisCanvasShim() {
    shutdown();
    live_shims().erase(QPointer<QgisCanvasShim>(this));
}

int QgisCanvasShim::shutdown_live_shims() {
    int cleaned = 0;
    for (const QPointer<QgisCanvasShim>& shim : live_shims()) {
        if (shim != nullptr && !shim->shutdown_done_) {
            shim->shutdown();
            ++cleaned;
        }
    }
    return cleaned;
}

// ---- extent handling (the F2/F4 programmatic-vs-user dedup) ----------

bool QgisCanvasShim::is_fitted_compatible(const CanvasExtent& expected,
                                          const CanvasExtent& actual) const {
    if (expected == actual) return true;
    // QGIS aspect-fit expands one axis keeping center: actual must
    // contain expected with the same center.
    const double ex_cx = (expected[0] + expected[2]) * 0.5;
    const double ex_cy = (expected[1] + expected[3]) * 0.5;
    const double ac_cx = (actual[0] + actual[2]) * 0.5;
    const double ac_cy = (actual[1] + actual[3]) * 0.5;
    if (std::abs(ex_cx - ac_cx) > 1e-6 || std::abs(ex_cy - ac_cy) > 1e-6) {
        return false;
    }
    return actual[0] <= expected[0] + 1e-9 &&
           actual[2] >= expected[2] - 1e-9 &&
           actual[1] <= expected[1] + 1e-9 &&
           actual[3] >= expected[3] - 1e-9;
}

void QgisCanvasShim::on_stack_extent(double xmin, double ymin, double xmax,
                                     double ymax) {
    const CanvasExtent extent{float(xmin), float(ymin), float(xmax),
                              float(ymax)};
    // Differentiate programmatic set_extent vs user pan/zoom (native
    // tool). The expected list uses fitted-compatibility so unrelated
    // resize events do not consume pendings.
    bool is_programmatic = false;
    if (!expected_programmatic_extents_.empty()) {
        int compat_idx = -1;
        for (int idx = 0; idx < int(expected_programmatic_extents_.size());
             ++idx) {
            const CanvasExtent& exp = expected_programmatic_extents_[size_t(idx)];
            if (is_fitted_compatible(exp, extent) || exp == extent) {
                compat_idx = idx;
                break;
            }
        }
        if (compat_idx >= 0) {
            is_programmatic = true;
            expected_programmatic_extents_.erase(
                expected_programmatic_extents_.begin(),
                expected_programmatic_extents_.begin() + compat_idx + 1);
            pending_programmatic_ =
                std::max(0, pending_programmatic_ - (compat_idx + 1));
        } else if (pending_programmatic_ > 0 &&
                   expected_programmatic_extents_.front() == extent) {
            // Legacy fallback: exact equality without fitted logic.
            is_programmatic = true;
            expected_programmatic_extents_.erase(
                expected_programmatic_extents_.begin());
            pending_programmatic_ = std::max(0, pending_programmatic_ - 1);
        }
    } else if (pending_programmatic_ > 0) {
        // No expected list but pending > 0 — old path: only consume if
        // the extent matches last history/last emitted (never steal
        // user events).
        if (!extent_history_.empty()) {
            const CanvasExtent& last_hist = extent_history_.back();
            if (extent == last_hist ||
                is_fitted_compatible(last_hist, extent)) {
                is_programmatic = true;
                pending_programmatic_ =
                    std::max(0, pending_programmatic_ - 1);
            }
        }
    }

    if (is_programmatic) {
        // Programmatic path already emitted synchronously via
        // set_extent; if QGIS fitted a different extent, silently
        // correct history/last_emitted without a second signal.
        if (!extent_history_.empty() && extent_history_.back() != extent) {
            if (extent_history_index_ == int(extent_history_.size()) - 1) {
                extent_history_.back() = extent;
                last_emitted_extent_ = extent;
            } else {
                if (extent_history_index_ <
                    int(extent_history_.size()) - 1) {
                    extent_history_.resize(size_t(extent_history_index_) + 1);
                }
                extent_history_.push_back(extent);
                if (extent_history_.size() > 100) {
                    extent_history_.erase(extent_history_.begin());
                }
                // After pop-front the index must be recomputed —
                // every later subscript shifts (review P2-5).
                extent_history_index_ = int(extent_history_.size()) - 1;
                last_emitted_extent_ = extent;
            }
        }
        return;
    }

    // User-initiated (native pan/zoom) path.
    if (!extent_history_.empty() && extent_history_.back() == extent) {
        if (last_emitted_extent_ != extent) {
            emit extent_changed(extent);
            last_emitted_extent_ = extent;
            emit tool_operation(false);
        }
        return;
    }
    if (extent_history_index_ < int(extent_history_.size()) - 1) {
        extent_history_.resize(size_t(extent_history_index_) + 1);
    }
    if (extent_history_.empty() || extent_history_.back() != extent) {
        extent_history_.push_back(extent);
        if (extent_history_.size() > 100) {
            extent_history_.erase(extent_history_.begin());
        } else {
            extent_history_index_ = int(extent_history_.size()) - 1;
        }
    }
    if (last_emitted_extent_ != extent) {
        emit extent_changed(extent);
        last_emitted_extent_ = extent;
    }
    emit tool_operation(false);
}

// ---- state & geometry ------------------------------------------------

QString QgisCanvasShim::backend_status() const {
    QStringList parts;
    if (!mirror_failures_.isEmpty()) {
        parts.append(QStringLiteral("degraded (%1 mirror failures)")
                         .arg(mirror_failures_.size()));
    }
    // Runtime health: the native build links real QGIS — a session that
    // failed to construct is the only degraded state (there is no
    // import-time bridge to probe).
    if (session_ == nullptr || session_->project() == nullptr) {
        parts.append(QStringLiteral("runtime degraded: no session"));
    }
    if (!parts.isEmpty()) {
        return QStringLiteral("qgis: ") + parts.join(QStringLiteral("; "));
    }
    return QStringLiteral("qgis: ready");
}

CanvasExtent QgisCanvasShim::view_extent() const {
    if (shutdown_done_) {
        if (!extent_history_.empty()) {
            return extent_history_[size_t(extent_history_index_)];
        }
        return {0.0, 0.0, 1.0, 1.0};
    }
    if (canvas_ != nullptr) {
        const QgsRectangle e = canvas_->extent();
        return {e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()};
    }
    if (!extent_history_.empty()) {
        return extent_history_[size_t(extent_history_index_)];
    }
    return {0.0, 0.0, 1.0, 1.0};
}

void QgisCanvasShim::set_extent(const CanvasExtent& extent,
                                bool record_history,
                                bool coalesce_history) {
    if (shutdown_done_) return;
    const CanvasExtent tup{extent[0], extent[1], extent[2], extent[3]};
    if (record_history) {
        if (extent_history_index_ < int(extent_history_.size()) - 1) {
            extent_history_.resize(size_t(extent_history_index_) + 1);
        }
        if (coalesce_history && !extent_history_.empty()) {
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
    // Track programmatic origin for the F2/F4 dedup (the async
    // StackEvents delivery gets suppressed).
    ++pending_programmatic_;
    expected_programmatic_extents_.push_back(tup);
    if (canvas_ != nullptr) {
        try {
            canvas_->setExtent(
                QgsRectangle(tup[0], tup[1], tup[2], tup[3]));
            canvas_->refresh();
        } catch (...) {
            pending_programmatic_ = std::max(0, pending_programmatic_ - 1);
            if (!expected_programmatic_extents_.empty() &&
                expected_programmatic_extents_.back() == tup) {
                expected_programmatic_extents_.pop_back();
            }
            throw;
        }
    }
    if (last_emitted_extent_ != tup) {
        emit extent_changed(tup);
        last_emitted_extent_ = tup;
    }
}

bool QgisCanvasShim::previous_extent() {
    if (!can_previous_extent()) return false;
    --extent_history_index_;
    set_extent(extent_history_[size_t(extent_history_index_)],
               /*record_history=*/false);
    return true;
}

bool QgisCanvasShim::next_extent() {
    if (!can_next_extent()) return false;
    ++extent_history_index_;
    set_extent(extent_history_[size_t(extent_history_index_)],
               /*record_history=*/false);
    return true;
}

void QgisCanvasShim::zoom_by(
    double factor, std::optional<std::pair<double, double>> center,
    bool coalesce_history) {
    // #1165: inf/NaN would push non-finite coordinates straight into
    // the canvas — first-line guard (same as Python).
    if (!std::isfinite(factor) || factor <= 0.0) {
        throw std::invalid_argument("zoom factor must be finite and positive");
    }
    const auto [xmin, ymin, xmax, ymax] = view_extent();
    const double cx = center ? center->first : (xmin + xmax) / 2.0;
    const double cy = center ? center->second : (ymin + ymax) / 2.0;
    set_extent({cx + (xmin - cx) * factor, cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor, cy + (ymax - cy) * factor},
               true, coalesce_history);
}

double QgisCanvasShim::map_units_per_pixel() const {
    if (canvas_ == nullptr) return 1.0;
    // F3 parity: aspect-fitted extent for uniform mupp semantics.
    const auto [xmin, ymin, xmax, ymax] = view_extent();
    const int w = std::max(1, canvas_->width() > 0 ? canvas_->width()
                                                 : width());
    const int h = std::max(1, canvas_->height() > 0 ? canvas_->height()
                                                  : height());
    if (w == 0 || h == 0) return 1.0;
    return std::max((xmax - xmin) / w, (ymax - ymin) / h);
}

std::pair<double, double> QgisCanvasShim::map_to_screen(
    std::pair<double, double> point) const {
    if (canvas_ == nullptr) return {0.0, 0.0};
    const QgsPointXY screen = canvas_->mapSettings().mapToPixel().transform(
        QgsPointXY(point.first, point.second));
    return {screen.x(), screen.y()};
}

std::pair<double, double> QgisCanvasShim::screen_to_map(
    std::pair<double, double> point) const {
    if (canvas_ == nullptr) return {0.0, 0.0};
    const QgsPointXY map =
        canvas_->getCoordinateTransform()->toMapCoordinates(
            int(point.first), int(point.second));
    return {map.x(), map.y()};
}

// ---- chrome overlay ---------------------------------------------------

void QgisCanvasShim::set_overlay_provider(
    std::function<QVariantMap()> provider) {
    overlay_provider_ = std::move(provider);
    install_chrome_overlay();
}

std::pair<int, int> QgisCanvasShim::chrome_map_size() const {
    QWidget* host = canvas_viewport();
    if (host == nullptr) host = const_cast<QgisCanvasShim*>(this);
    return {std::max(1, host->width()), std::max(1, host->height())};
}

QWidget* QgisCanvasShim::canvas_viewport() const {
    return qgis::canvas_viewport(canvas_);
}

QVariantMap QgisCanvasShim::overlay_state() const {
    return overlay_provider_ ? overlay_provider_() : QVariantMap();
}

void QgisCanvasShim::install_chrome_overlay() {
    if (!canvas_created_) {
        return;  // half-constructed remnant: no canvas, nothing to host
    }
    QWidget* host = canvas_viewport();
    if (host == nullptr) host = this;
    if (chrome_scale_ == nullptr) {
        chrome_scale_ = new ScaleChrome(this, host);
        chrome_north_ = new NorthChrome(this, host);
        chrome_legend_ = new LegendChrome(this, host);
    }
    for (QWidget* piece : {chrome_scale_, chrome_north_, chrome_legend_}) {
        if (piece->parentWidget() != host) {
            piece->setParent(host);
        }
    }
    const auto [map_w, map_h] = chrome_map_size();
    const auto spec = scale_bar_spec(view_extent(), map_w, 1.0);
    const int bar_w = int((spec ? spec->second : 120) + 40);
    chrome_scale_->setGeometry(8, std::max(0, map_h - 44),
                               std::min(bar_w, map_w - 16), 40);
    chrome_north_->setGeometry(8, 48, 48, 56);
    const QVariantMap state = overlay_state();
    const QVariantMap decorations =
        state.value(QStringLiteral("decorations")).toMap();
    const QSize legend = legend_chrome_size(decorations, 1.0);
    if (legend.width() > 0 && legend.height() > 0) {
        chrome_legend_->setGeometry(
            std::max(0, map_w - legend.width() - 8),
            std::max(0, map_h - legend.height() - 8), legend.width(),
            legend.height());
        chrome_legend_->show();
        chrome_legend_->raise();
        chrome_legend_->update();
    } else {
        chrome_legend_->hide();
    }
    for (QWidget* piece : {chrome_scale_, chrome_north_}) {
        piece->raise();
        piece->show();
        piece->update();
    }
    if (host != this && !chrome_filter_installed_) {
        host->installEventFilter(this);
        chrome_filter_installed_ = true;
    }
}

bool QgisCanvasShim::eventFilter(QObject* obj, QEvent* event) {
    if (event->type() == QEvent::Resize && obj == canvas_viewport()) {
        install_chrome_overlay();
    }
    return QWidget::eventFilter(obj, event);
}

void QgisCanvasShim::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    install_chrome_overlay();
}

void QgisCanvasShim::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    install_chrome_overlay();
}

// ---- snapping / current layer -----------------------------------------

bool QgisCanvasShim::set_snapping_config(const QVariantMap& config) {
    // Snapping config projected onto QgsMapCanvas::snappingUtils (M3);
    // the snapping service remains the authority — this is only the
    // projection. Grid snapping is a Python-only mode with no QGIS
    // counterpart and is not pushed.
    if (shutdown_done_ || canvas_ == nullptr) {
        return false;
    }
    QgsSnappingConfig cfg(session_->project());
    cfg.setEnabled(config.value(QStringLiteral("enabled")).toBool());
    const QString mode =
        config.value(QStringLiteral("mode")).toString();
    if (mode == QLatin1String("all_layers")) {
        cfg.setMode(Qgis::SnappingMode::AllLayers);
    } else {
        cfg.setMode(Qgis::SnappingMode::ActiveLayer);
    }
    cfg.setTolerance(
        config.value(QStringLiteral("tolerance_px")).toDouble());
    cfg.setUnits(Qgis::MapToolUnit::Pixels);
    Qgis::SnappingTypes types;
    for (const QVariant& v :
         config.value(QStringLiteral("types")).toList()) {
        const QString t = v.toString();
        if (t == QLatin1String("vertex"))
            types |= Qgis::SnappingType::Vertex;
        else if (t == QLatin1String("segment"))
            types |= Qgis::SnappingType::Segment;
        else if (t == QLatin1String("centroid"))
            types |= Qgis::SnappingType::Centroid;
        else if (t == QLatin1String("middle"))
            types |= Qgis::SnappingType::MiddleOfSegment;
        else if (t == QLatin1String("area"))
            types |= Qgis::SnappingType::Area;
        else if (t == QLatin1String("extension"))
            types |= Qgis::SnappingType::LineEndpoint;
    }
    cfg.setTypeFlag(types);
    // Per-layer config: {"layers": {doc_id: {"enabled","types","tol"}}}
    const QVariantMap layers =
        config.value(QStringLiteral("layers")).toMap();
    if (!layers.isEmpty()) {
        cfg.setMode(Qgis::SnappingMode::AdvancedConfiguration);
        const QHash<QString, QgsMapLayer*> doc_index =
            build_doc_id_index(*session_->project());
        for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
            auto* vl = qobject_cast<QgsVectorLayer*>(
                doc_index.value(it.key()));
            if (vl == nullptr) continue;
            const QVariantMap lc = it.value().toMap();
            Qgis::SnappingTypes lt;
            for (const QVariant& tv :
                 lc.value(QStringLiteral("types")).toList()) {
                const QString t = tv.toString();
                if (t == QLatin1String("vertex"))
                    lt |= Qgis::SnappingType::Vertex;
                else if (t == QLatin1String("segment"))
                    lt |= Qgis::SnappingType::Segment;
                else if (t == QLatin1String("centroid"))
                    lt |= Qgis::SnappingType::Centroid;
                else if (t == QLatin1String("middle"))
                    lt |= Qgis::SnappingType::MiddleOfSegment;
                else if (t == QLatin1String("area"))
                    lt |= Qgis::SnappingType::Area;
                else if (t == QLatin1String("extension"))
                    lt |= Qgis::SnappingType::LineEndpoint;
            }
            cfg.setIndividualLayerSettings(
                vl, QgsSnappingConfig::IndividualLayerSettings(
                        lc.value(QStringLiteral("enabled")).toBool(), lt,
                        lc.value(QStringLiteral("tolerance_px")).toDouble(),
                        Qgis::MapToolUnit::Pixels));
        }
    }
    canvas_->snappingUtils()->setConfig(cfg);
    return true;
}

void QgisCanvasShim::set_vertex_edit_scope(bool /*all_layers*/) {
    // The vertex-edit scope is a property of the native vertex tool —
    // the bridge pushed it mid-flight; natively the edit stack applies
    // it when arming its tool (factory path). Stored semantics: the
    // shim has no vertex tool of its own, so this is an honest no-op.
}

void QgisCanvasShim::set_tracing_enabled(bool /*enabled*/) {
    // QgsMapCanvasTracer registration belongs to the native edit stack
    // (it owns the tool that traces); the shim exposes no tracing
    // surface of its own — honest no-op (same as the old-bridge skip).
}

void QgisCanvasShim::set_current_layer(const QString& doc_id) {
    // Canvas current layer — the target of native select/identify.
    // V10 M-G parity: an EMPTY doc_id is an explicit clear (natively
    // always supported — the old-bridge flag dance collapses).
    if (shutdown_done_ || canvas_ == nullptr) {
        return;
    }
    if (doc_id.isEmpty()) {
        canvas_->setCurrentLayer(nullptr);
        pushed_current_layer_.clear();
        return;
    }
    QgsMapLayer* found =
        find_mirror_layer(*session_->project(), doc_id);
    if (found == nullptr) {
        // Not mirrored yet / already removed: shadow keeps its old
        // value and the caller's idempotent re-push relies on that
        // (V12 M0-2b).
        return;
    }
    canvas_->setCurrentLayer(found);
    pushed_current_layer_ = doc_id;
    // Target layer in place: reset the "no edit target" warn dedup.
    vertex_no_target_warned_ = false;
}

QString QgisCanvasShim::current_layer_doc_id() const {
    // Authoritative read-back (the new-bridge path): layers that were
    // removed/rebuilt drift any local shadow — the canvas is truth.
    if (shutdown_done_ || canvas_ == nullptr) {
        return {};
    }
    QgsMapLayer* current = canvas_->currentLayer();
    if (current == nullptr) {
        return {};
    }
    return current->customProperty(QString::fromLatin1(kDocIdProperty))
        .toString();
}

bool QgisCanvasShim::native_tool_busy() const {
    // Esc semantics owner probe (M3 Task 5): the host reports a
    // digitize/drag in progress; absent a probe the honest answer is
    // "not busy".
    if (shutdown_done_ || canvas_ == nullptr || !busy_probe_) {
        return false;
    }
    return busy_probe_();
}

void QgisCanvasShim::set_busy_probe(std::function<bool()> probe) {
    busy_probe_ = std::move(probe);
}

void QgisCanvasShim::cancel_native_tool() {
    // Dispatch Esc to the canvas (postEvent): capture tools cancel the
    // in-progress capture; vertex/move drags cancel the drag — the tool
    // itself stays armed.
    if (shutdown_done_ || canvas_ == nullptr) {
        return;
    }
    QApplication::postEvent(
        canvas_, new QKeyEvent(QEvent::KeyPress, Qt::Key_Escape,
                               Qt::NoModifier));
}

// ---- tools --------------------------------------------------------------

void QgisCanvasShim::set_tool_factory(
    std::function<QgsMapTool*(const QString&, QgsMapCanvas*)> factory) {
    tool_factory_ = std::move(factory);
}

void QgisCanvasShim::set_native_measure_supported(bool supported) {
    native_measure_supported_ = supported;
}

void QgisCanvasShim::set_controller_hooks(ControllerHooks hooks) {
    controller_ = std::move(hooks);
}

QString QgisCanvasShim::active_map_tool_id() const {
    // Checked-state consistency read surface: the toolbar checked state
    // must match this value (especially after an activation-failure
    // fallback). Dead canvas -> nullopt equivalent (empty).
    if (!canvas_created_ || canvas_destroyed_) {
        return {};
    }
    return last_native_tool_.first;
}

void QgisCanvasShim::arm_tool(const QString& tool_id_in) {
    if (shutdown_done_ || canvas_ == nullptr) {
        return;
    }
    const QString tool_id =
        tool_id_in.isEmpty() ? QStringLiteral("pan") : tool_id_in;
    // Kind vocabulary (the Python dict + special cases, verbatim):
    const bool measure_active = tool_id == QLatin1String("measure_distance");
    const bool native_measure = measure_active && native_measure_supported_;
    QString kind;
    static const std::map<QString, QString> kKindMap = {
        {"zoom_in", "zoomIn"},       {"zoom_out", "zoomOut"},
        {"add_point", "addPoint"},   {"add_line", "addLine"},
        {"add_polygon", "addPolygon"}, {"vertex", "vertex"},
        {"move_feature", "move"},    {"select", "select"},
        {"select_rectangle", "select"}, {"identify", "identify"},
        {"pan", "pan"},
    };
    const auto it = kKindMap.find(tool_id);
    kind = it != kKindMap.end() ? it->second : QStringLiteral("pan");
    ToolHooks* active =
        controller_.active_tool ? controller_.active_tool() : nullptr;
    if (native_measure) {
        kind = QStringLiteral("measure");
    } else if (tool_id == QLatin1String("reshape")) {
        kind = QStringLiteral("addLine");
    } else if (tool_id == QLatin1String("add_ring")) {
        kind = QStringLiteral("addPolygon");
    } else if (tool_id == QLatin1String("add_part") ||
               tool_id == QLatin1String("fault_cut") ||
               tool_id == QLatin1String("boundary_reshape")) {
        kind = (active != nullptr &&
                !active->native_digitize_kind.isEmpty())
                   ? active->native_digitize_kind
                   : QStringLiteral("pan");
    }

    QgsMapTool* tool = nullptr;
    std::unique_ptr<QgsMapTool> owned;
    bool supported_builtin = true;
    if (kind == QLatin1String("pan")) {
        owned = std::make_unique<QgsMapToolPan>(canvas_);
    } else if (kind == QLatin1String("zoomIn")) {
        owned = std::make_unique<QgsMapToolZoom>(canvas_, false);
    } else if (kind == QLatin1String("zoomOut")) {
        owned = std::make_unique<QgsMapToolZoom>(canvas_, true);
    } else {
        supported_builtin = false;
        if (tool_factory_) {
            tool = tool_factory_(kind, canvas_);
        }
    }
    if (owned) tool = owned.get();

    if (tool == nullptr) {
        // ADV-1: activation failure must be visible — a checked toolbar
        // button with the canvas still on the old tool is the
        // "clicked but nothing happened" UX defect.
        const QString reason =
            supported_builtin
                ? QStringLiteral("tool construction failed")
                : QStringLiteral("no native tool registered for kind '%1'")
                      .arg(kind);
        qCWarning(lcCanvasShim)
            << "native tool activation failed" << tool_id << "->" << kind;
        emit backend_status_changed(
            QStringLiteral("qgis: 工具切换失败（%1）").arg(tool_id));
        emit native_tool_activation_failed(tool_id, reason);
    } else {
        canvas_->setMapTool(tool, /*clean=*/false);
        owned_tool_ = std::move(owned);  // shim owns pan/zoom; factory
                                         // tools stay host-owned
        // Record the last SUCCESSFUL activation — the checked-state
        // read surface (consistency must be detectable).
        last_native_tool_ = {tool_id, kind};
    }

    // Viewport routing only while "measure active AND no native
    // measure tool" (the fallback path).
    const bool route = measure_active && !native_measure;
    measure_router_->set_active(route);
    if (!measure_active) {
        last_measure_emit_.reset();
    } else if (!native_measure && !measure_degrade_warned_) {
        // Same honesty as the snapping endpoint/intersection degrade
        // (review-2 P1-1): the fallback path measures planar distance —
        // no ellipsoidal correction on geographic CRSs.
        measure_degrade_warned_ = true;
        qCWarning(lcCanvasShim)
            << "native measure tool unavailable; measure falls back to "
               "planar computation without ellipsoidal correction on "
               "geographic CRSs";
    }
    setFocus();
}

// ---- canvas facts --------------------------------------------------------

double QgisCanvasShim::map_scale() const {
    // Authoritative canvas scale denominator; 0.0 = unknown (dead
    // canvas) — never estimated by the host.
    if (!canvas_created_ || canvas_destroyed_ || canvas_ == nullptr) {
        return 0.0;
    }
    const double value = canvas_->scale();
    return value > 0.0 && std::isfinite(value) ? value : 0.0;
}

QString QgisCanvasShim::destination_crs() const {
    if (!canvas_created_ || canvas_destroyed_ || canvas_ == nullptr) {
        return {};
    }
    return canvas_->mapSettings().destinationCrs().authid();
}

QString QgisCanvasShim::map_units() const {
    // QGIS unit vocabulary ("meters"/"degrees"/…) — honest unknown ""
    // on a dead canvas; never estimated.
    if (!canvas_created_ || canvas_destroyed_ || canvas_ == nullptr) {
        return {};
    }
    return QgsUnitTypes::toString(canvas_->mapSettings().mapUnits());
}

double QgisCanvasShim::output_dpi() const {
    if (!canvas_created_ || canvas_destroyed_ || canvas_ == nullptr) {
        return 0.0;
    }
    const double value = canvas_->mapSettings().outputDpi();
    return value > 0.0 && std::isfinite(value) ? value : 0.0;
}

QVariantMap QgisCanvasShim::mirror_provider_facts(
    const QString& doc_id) const {
    // Mirror-layer provider facts (V10 M-H): the native equivalent of
    // the bridge introspection surface — exists/is_valid are the same
    // ledger-health probes the mirror consumes.
    if (shutdown_done_ || session_ == nullptr ||
        session_->project() == nullptr) {
        return {};
    }
    QVariantMap facts;
    QgsMapLayer* found =
        find_mirror_layer(*session_->project(), doc_id);
    facts.insert(QStringLiteral("exists"), found != nullptr);
    facts.insert(QStringLiteral("is_valid"),
                 found != nullptr && found->isValid());
    if (found != nullptr) {
        facts.insert(QStringLiteral("qgis_layer_id"), found->id());
        facts.insert(QStringLiteral("provider"),
                     found->providerType());
    }
    return facts;
}

QVariantMap QgisCanvasShim::crs_chain_facts(
    const QString& storage_crs) const {
    // CrsChainFacts projection (V10 M-B): project/canvas/storage CRS
    // plus runtime capability — natively the QGIS runtime IS linked so
    // crs-capable is true by construction.
    QVariantMap facts;
    facts.insert(QStringLiteral("project_crs"), project_crs_hint_);
    facts.insert(QStringLiteral("canvas_crs"), destination_crs());
    facts.insert(QStringLiteral("storage_crs"), storage_crs);
    facts.insert(QStringLiteral("runtime_crs_capable"), true);
    return facts;
}

// ---- context menu ---------------------------------------------------------

void QgisCanvasShim::on_canvas_context_menu(const QPoint& pos) {
    // Right-click -> map coordinates (V12 task 3: facies-change entry;
    // the coordinate math is done here so consumers get map coords).
    if (shutdown_done_) return;
    QWidget* vp = canvas_viewport();
    const auto [xmin, ymin, xmax, ymax] = view_extent();
    if (vp == nullptr) return;
    const double width = vp->width();
    const double height = vp->height();
    if (width <= 0.0 || height <= 0.0 || xmax <= xmin || ymax <= ymin) {
        return;
    }
    const double x_map = xmin + (double(pos.x()) / width) * (xmax - xmin);
    const double y_map = ymax - (double(pos.y()) / height) * (ymax - ymin);
    const QPoint global_pos = vp->mapToGlobal(pos);
    emit canvas_context_menu({x_map, y_map}, global_pos);
}

// ---- measure fallback routing ---------------------------------------------

bool QgisCanvasShim::route_measure_mouse(QMouseEvent* event) {
    // Feed viewport mouse events to the host's fallback measure tool;
    // returns true when the event was consumed (button events never
    // reach the native pan tool).
    ToolHooks* tool =
        controller_.active_tool ? controller_.active_tool() : nullptr;
    if (tool == nullptr ||
        tool->tool_id != QLatin1String("measure_distance")) {
        return false;
    }
    const QEvent::Type type = event->type();
    if (type == QEvent::MouseMove) {
        // Observe only: the canvas still gets the move (status-bar xy
        // stays live; pan never starts — press was intercepted).
        emit_measure_preview(tool);
        return false;
    }
    QString btn;
    switch (event->button()) {
        case Qt::LeftButton:
            btn = QStringLiteral("left");
            break;
        case Qt::RightButton:
            btn = QStringLiteral("right");
            break;
        default:
            btn = QStringLiteral("middle");
            break;
    }
    QStringList mods;
    if (event->modifiers() & Qt::ControlModifier) {
        mods.append(QStringLiteral("ctrl"));
    }
    if (event->modifiers() & Qt::ShiftModifier) {
        mods.append(QStringLiteral("shift"));
    }
    const QPointF pos = event->position();
    const auto [mx, my] = screen_to_map({pos.x(), pos.y()});
    const std::pair<double, double> point{mx, my};
    if (type == QEvent::MouseButtonPress && tool->mouse_press) {
        tool->mouse_press(point, btn, mods);
    } else if (type == QEvent::MouseButtonRelease &&
               tool->mouse_release) {
        tool->mouse_release(point, btn, mods);
    } else if (type == QEvent::MouseButtonDblClick &&
               tool->double_click) {
        tool->double_click(point, mods);
    }
    const std::optional<double> distance =
        tool->last_distance ? tool->last_distance() : std::nullopt;
    if (distance != last_measure_emit_) {
        last_measure_emit_ = distance;
        if (distance.has_value()) {
            emit measure_segment(*distance);
        }
    }
    return true;
}

void QgisCanvasShim::emit_measure_preview(ToolHooks* tool) {
    if (tool == nullptr || !tool->start_point || !tool->current_point) {
        return;
    }
    const auto start = tool->start_point();
    const auto current = tool->current_point();
    if (!start.has_value() || !current.has_value()) {
        return;
    }
    const double dx = current->first - start->first;
    const double dy = current->second - start->second;
    emit measure_preview(std::hypot(dx, dy));
}

void QgisCanvasShim::warn_vertex_without_target() {
    if (vertex_no_target_warned_) {
        return;
    }
    vertex_no_target_warned_ = true;
    emit commit_rejected(QStringLiteral(
        "节点编辑没有编辑目标：请在图层树选中该图层并「开始编辑」"));
}

// ---- bridge-callback entry points -----------------------------------------
// Same payload vocabulary + dispatch order as the Python bridge
// callbacks; the native edit stack drives these from its QgsMapTool
// signals.

void QgisCanvasShim::on_digitize(const QString& status,
                                 const QVariantMap& geom) {
    if (shutdown_done_) return;
    if (status == QLatin1String("digitizing")) {
        // Capture-progress feedback (info-only — does not drive tool
        // operation counts).
        emit capture_progress(geom);
        return;
    }
    if (status != QLatin1String("completed")) {
        // canceled (Esc / right-click empty cancel): toolbar state
        // flows back, the tool stays armed — only THIS capture dies.
        emit tool_operation(false);
        if (controller_.cancel_native_capture) {
            controller_.cancel_native_capture();
        }
        return;
    }
    // Native routing first, before the active tool's commit_geometry:
    // split cuts arrive on addLine without activating the kind-bound
    // Python add-line tool, so active_tool may lack commit_geometry —
    // returning early would lose the cut forever.
    if (controller_.commit_native_capture) {
        try {
            if (controller_.commit_native_capture(geom)) {
                emit tool_operation(true);
                return;
            }
        } catch (...) {
            // Routing failure falls through to the tool commit.
        }
    }
    ToolHooks* tool =
        controller_.active_tool ? controller_.active_tool() : nullptr;
    if (tool == nullptr || !tool->commit_geometry) {
        return;
    }
    // ADV-2: a rejected commit must be perceivable — never swallow a
    // completed capture silently.
    bool ok = false;
    try {
        ok = tool->commit_geometry(geom);
    } catch (const std::exception& exc) {
        qCDebug(lcCanvasShim) << "digitize commit rejected:" << exc.what();
        emit commit_rejected(
            QStringLiteral("要素未写入：%1").arg(QString::fromUtf8(exc.what())));
        emit tool_operation(false);
        return;
    } catch (...) {
        emit commit_rejected(QStringLiteral("要素未写入：几何校验未通过"));
        emit tool_operation(false);
        return;
    }
    if (ok) {
        emit tool_operation(true);
    } else {
        emit commit_rejected(QStringLiteral("要素未写入：几何校验未通过"));
        emit tool_operation(false);
    }
}

void QgisCanvasShim::on_edit_pick(const QString& action,
                                  const QVariantMap& payload) {
    if (shutdown_done_) return;
    if (action == QLatin1String("pick_miss")) {
        // An ordinary click on empty space is not an error (the vertex
        // tool allows empty drags for rubber-band select) — no prompt.
        // Only "tool armed but the canvas has NO edit target" prompts:
        // that is exactly the D-B field shape where users think the
        // feature is broken while current layer is simply empty.
        if (last_native_tool_.first == QLatin1String("vertex") &&
            current_layer_doc_id().isEmpty()) {
            warn_vertex_without_target();
        }
        return;
    }
    if (action == QLatin1String("vertex_no_move")) {
        // Click (not drag) hit a vertex — semantics suppressed, but say
        // so (honest presentation, M2-4).
        emit status_hint(
            QStringLiteral("单击不移动节点：拖动以编辑顶点位置"));
        return;
    }
    if (action == QLatin1String("join_requested")) {
        // All-layers scope gesture touched neighbor layers — the host
        // re-checks admission for the joined set.
        if (controller_.join_native_layers) {
            try {
                controller_.join_native_layers(
                    payload.value(QStringLiteral("layer_doc_ids"))
                        .toStringList());
            } catch (const std::exception& exc) {
                qCWarning(lcCanvasShim)
                    << "native layer join failed:" << exc.what();
            }
        }
        return;
    }
    if (action == QLatin1String("edit_gesture")) {
        // Native gesture bookkeeping (the edit happened on the mirror
        // buffer — the data callback carries the gesture fact only).
        if (controller_.record_native_gesture) {
            try {
                if (controller_.record_native_gesture(payload)) {
                    emit tool_operation(true);
                }
            } catch (const std::exception& exc) {
                // A missed gesture desyncs the undo plan from the edit
                // stack — diagnosable, never silent.
                qCWarning(lcCanvasShim)
                    << "native edit gesture recording failed:" << exc.what();
            }
        }
        return;
    }
    ToolHooks* tool =
        controller_.active_tool ? controller_.active_tool() : nullptr;
    if (tool == nullptr) {
        return;
    }
    dispatch_edit_pick(*this, tool, action, payload);
}

void QgisCanvasShim::on_selection(const QString& action,
                                  const QVariantMap& payload) {
    if (shutdown_done_) return;
    if (action == QLatin1String("identify")) {
        // Native identify result -> the single forwarding entry; the
        // feature-query panel remains the authority.
        emit native_identified(payload);
        return;
    }
    if (action != QLatin1String("selection")) {
        return;
    }
    ToolHooks* tool =
        controller_.active_tool ? controller_.active_tool() : nullptr;
    if (tool == nullptr || !tool->commit_selection) {
        return;
    }
    bool ok = false;
    try {
        ok = tool->commit_selection(
            payload.value(QStringLiteral("feature_ids")).toList(),
            payload.value(QStringLiteral("modifiers")).toList());
    } catch (...) {
        ok = false;
    }
    if (!ok) {
        return;
    }
    // Highlight projection: the selection authority is the host's; the
    // canvas highlight is a visual projection only. Fid mapping is the
    // edit stack's domain — it supplies doc_id + feature ids.
    if (tool->highlight_layer_doc_id && tool->highlight_feature_ids) {
        const QString doc_id = tool->highlight_layer_doc_id();
        const QStringList selection = tool->highlight_feature_ids();
        if (!doc_id.isEmpty()) {
            apply_highlight(doc_id, selection);
        }
    }
    emit tool_operation(false);
}

void QgisCanvasShim::on_measure(const QString& action,
                                const QVariantMap& payload) {
    if (shutdown_done_) return;
    if (action == QLatin1String("measure_canceled")) {
        emit measure_canceled();
        return;
    }
    emit measure_updated(payload);
}

// ---- layer mirror -----------------------------------------------------------

void QgisCanvasShim::set_edit_frozen_layer_ids(std::set<QString> ids) {
    edit_frozen_ids_ = std::move(ids);
}

void QgisCanvasShim::set_layer_snapshot(const MirrorSnapshot& snapshot,
                                        bool /*changed_hints*/) {
    if (shutdown_done_) return;
    // V10 M-B: record the project CRS for the crs_chain_facts
    // projection (normalized like crs_contract; undeclared = "").
    project_crs_hint_ = snapshot.project_crs;

    MirrorOptions options;
    options.groups = layer_groups_enabled;
    options.edit_frozen_ids = edit_frozen_ids_;
    options.refresh_window = canvas_;
    const MirrorResult result = mirror_snapshot_to_project(
        *session_->project(), snapshot, options, *ledger_);

    // #1164: mirror failures land in the public diagnostics list and
    // the backend status — a mirror out of sync with the document is
    // perceivable, never silently stale.
    mirror_failures_ = result.failures;
    mirrored_layers_ = result.mirrored_qgis_ids;
    mirrored_doc_ids_ = result.seen_doc_ids;
    last_snapshot_ = std::make_unique<MirrorSnapshot>(snapshot);
    emit backend_status_changed(backend_status());
}

// ---- export -----------------------------------------------------------------

QStringList QgisCanvasShim::export_capabilities() const {
    // Honest capability declaration: PNG always; SVG/PDF need a
    // published snapshot (same contract as Python).
    QStringList caps{QStringLiteral("PNG")};
    if (last_snapshot_ != nullptr) {
        caps.append({QStringLiteral("SVG"), QStringLiteral("PDF")});
    }
    return caps;
}

QString QgisCanvasShim::export_png(const QString& path) {
    // Real frame export: wait for in-flight renders to finish before
    // grabbing the canvas frame (a never-rendered canvas still yields
    // its first frame); failures are honest errors, never half-rendered
    // frames passed off as product.
    if (shutdown_done_ || canvas_ == nullptr) {
        return QStringLiteral("QGIS 画布已关闭，无法导出");
    }
    canvas_->refresh();
    if (exporting_) {
        return QStringLiteral("导出已在进行中");
    }
    exporting_ = true;
    bool timed_out = false;
    try {
        const auto deadline =
            std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!shutdown_done_ && canvas_ != nullptr &&
               canvas_->isDrawing()) {
            if (std::chrono::steady_clock::now() > deadline) {
                timed_out = true;
                break;
            }
            QEventLoop loop;
            QTimer::singleShot(20, &loop, &QEventLoop::quit);
            loop.exec(QEventLoop::ExcludeUserInputEvents);
        }
    } catch (...) {
    }
    exporting_ = false;
    if (shutdown_done_ || canvas_ == nullptr) {
        return QStringLiteral("QGIS 画布在导出期间被关闭");
    }
    if (timed_out) {
        return QStringLiteral("QGIS 画布渲染未在时限内完成，取消导出");
    }
    const QPixmap pixmap = canvas_->grab();
    if (pixmap.isNull()) {
        return QStringLiteral("QGIS 画布无可用帧，无法导出 PNG");
    }
    if (!pixmap.save(path, "PNG")) {
        return QStringLiteral("PNG 保存失败");
    }
    return {};
}

QString QgisCanvasShim::export_svg(const QString& path) {
    return export_vector(path, QStringLiteral("svg"));
}

QString QgisCanvasShim::export_pdf(const QString& path) {
    return export_vector(path, QStringLiteral("pdf"));
}

QString QgisCanvasShim::export_vector(const QString& path,
                                      const QString& fmt) {
    // True vector export: offscreen render of the session project's
    // mirror layers at the current extent (the Python path renders the
    // retained snapshot through a second backend — natively the
    // session project already holds exactly those layers).
    if (shutdown_done_) {
        return QStringLiteral("QGIS 画布已关闭，无法导出");
    }
    if (last_snapshot_ == nullptr) {
        return QStringLiteral(
            "QGIS 画布尚无图层快照，无法矢量导出；请使用 PNG");
    }
    if (session_ == nullptr || session_->project() == nullptr) {
        return QStringLiteral("QGIS 渲染不可用，无法矢量导出；请使用 PNG");
    }
    const auto [xmin, ymin, xmax, ymax] = view_extent();
    if (xmax <= xmin || ymax <= ymin) {
        return QStringLiteral("QGIS 画布范围为空，无法矢量导出");
    }
    const int width = std::max(64, canvas_ ? canvas_->width() : 800);
    const int height = std::max(64, canvas_ ? canvas_->height() : 600);

    QgsMapSettings settings;
    settings.setDestinationCrs(session_->project()->crs());
    // BEGIN V14-QGIS-CONTROL (export order contract 03 §1)
    // The export layer set must follow the TREE order (top-first — the
    // same list the canvas draws), restricted to the document mirrors.
    // project->mapLayers() is a QMap keyed by QGIS layer id: using it
    // directly produced an id-sorted z-order that could disagree with
    // the screen and with the layout exporter's explicit reversal.
    // Join key: pwb/layer_id (V14 open path) with legacy pwb/doc_id
    // read-compat (mirror flow) — layer_adapter::layer_id_of reports the
    // legacy key through the out-param.
    QList<QgsMapLayer*> export_layers;
    const QList<QgsMapLayer*> tree_order =
        session_->project()->layerTreeRoot()->layerOrder();
    for (QgsMapLayer* layer : tree_order) {
        if (layer == nullptr) continue;
        std::string legacy_doc_id;
        const std::string domain_id =
            pwb::qgis::layer_adapter::layer_id_of(layer, &legacy_doc_id);
        if (!domain_id.empty() || !legacy_doc_id.empty()) {
            export_layers.append(layer);
        }
    }
    if (export_layers.isEmpty()) {
        return QStringLiteral(
            "树中无可导出的镜像图层，矢量导出中止（请使用 PNG）");
    }
    // END V14-QGIS-CONTROL
    settings.setLayers(export_layers);
    settings.setExtent(QgsRectangle(xmin, ymin, xmax, ymax));
    settings.setOutputSize(QSize(width, height));
    settings.setOutputDpi(96.0);
    settings.setFlag(Qgis::MapSettingsFlag::Antialiasing, true);

    if (fmt == QLatin1String("svg")) {
        QSvgGenerator generator;
        generator.setFileName(path);
        generator.setSize(QSize(width, height));
        generator.setViewBox(QRect(0, 0, width, height));
        generator.setResolution(96);
        QPainter painter(&generator);
        QgsMapRendererCustomPainterJob job(settings, &painter);
        job.start();
        job.waitForFinished();
        painter.end();
    } else {
        QPrinter printer(QPrinter::HighResolution);
        printer.setOutputFormat(QPrinter::PdfFormat);
        printer.setOutputFileName(path);
        printer.setPageSize(QPageSize(QSizeF(width, height),
                                      QPageSize::Point));
        printer.setResolution(96);
        QPainter painter(&printer);
        QgsMapRendererCustomPainterJob job(settings, &painter);
        job.start();
        job.waitForFinished();
        painter.end();
    }
    QFile out(path);
    if (!out.exists() || out.size() == 0) {
        return QStringLiteral("QGIS 矢量导出失败（%1）；请使用 PNG")
            .arg(fmt.toUpper());
    }
    return {};
}

// ---- lifecycle --------------------------------------------------------------

void QgisCanvasShim::apply_highlight(const QString& doc_id,
                                     const QStringList& feature_ids) {
    // Highlight projection via canvas QgsHighlight: the doc feature id
    // resolves through the mirror's __pwb_fid attribute (the bridge fid
    // map's native equivalent).
    clear_highlights();
    if (feature_ids.isEmpty()) {
        return;
    }
    auto* vl = qobject_cast<QgsVectorLayer*>(
        find_mirror_layer(*session_->project(), doc_id));
    if (vl == nullptr) return;
    const int fid_idx =
        vl->fields().indexOf(QString::fromLatin1(kPwbFidField));
    if (fid_idx < 0) return;
    const QSet<QString> wanted(feature_ids.begin(), feature_ids.end());
    QgsFeatureIterator it = vl->getFeatures();
    QgsFeature feature;
    while (it.nextFeature(feature)) {
        if (!wanted.contains(feature.attribute(fid_idx).toString())) {
            continue;
        }
        auto* highlight = new QgsHighlight(canvas_, feature.geometry(), vl);
        QColor color = QColor(QStringLiteral("#ff0000"));
        color.setAlphaF(0.3);
        highlight->setColor(color);
        highlight->setFillColor(color);
        highlight->show();
        highlights_.push_back(highlight);
    }
}

void QgisCanvasShim::clear_highlights() {
    for (QgsHighlight* highlight : highlights_) {
        delete highlight;
    }
    highlights_.clear();
}

void QgisCanvasShim::shutdown() {
    if (shutdown_done_) {
        return;
    }
    shutdown_done_ = true;
    if (measure_router_ != nullptr) {
        measure_router_->detach();
    }
    disconnect(events_, &StackEvents::extent_changed, this, nullptr);
    disconnect(events_, &StackEvents::map_position_changed, this,
               nullptr);
    clear_highlights();
    if (session_ != nullptr) {
        // Ordered teardown (MapSession owns the order): tool -> canvas
        // layers cleared -> canvas detached -> layers removed ->
        // project. Mirrored groups/layers die with the session project.
        session_->close();
    }
}

void QgisCanvasShim::mark_disposed() {
    // Qt-tree destruction bookkeeping ONLY — no session/QGIS calls on a
    // half-destroyed canvas (the Python _mark_disposed contract). The
    // session must NOT be destroyed here: destroyed() fires while the
    // canvas child is already dead/dying and ~MapSession() would
    // re-enter it. The unique_ptr member is destroyed during normal
    // member teardown, which runs before QObject::~QObject deletes
    // children — the canvas is still alive at that point.
    shutdown_done_ = true;
    canvas_destroyed_ = true;
    canvas_ = nullptr;
}

void QgisCanvasShim::closeEvent(QCloseEvent* event) {
    shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_widgets::qgis
