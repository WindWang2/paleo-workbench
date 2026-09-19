#include <pwb/ui_wellseis/qgis/well_map_qgis_surface.hpp>

#include <cmath>
#include <exception>
#include <utility>

#include <QEvent>
#include <QLabel>
#include <QMouseEvent>
#include <QVBoxLayout>

#include <qgscoordinatereferencesystem.h>
#include <qgslayertree.h>
#include <qgslinesymbol.h>
#include <qgslinesymbollayer.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptopixel.h>
#include <qgsmarkersymbol.h>
#include <qgspallabeling.h>
#include <qgspointxy.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgsrenderer.h>
#include <qgssinglesymbolrenderer.h>
#include <qgssymbol.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerlabeling.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

namespace pwb::ui_wellseis::qgis {

namespace {

using pwb::domain::Json;
using qt::WellMapPoint;
using qt::WellMapRing;
using qt::WellMapScene;

// Mirrors the QPainter fallback palette (tokens.PRIMARY / WARNING /
// ACCENT / TEXT_SECONDARY / TEAL / CANVAS_CURSOR fallbacks).
const QColor kColorOk(0x2f, 0x6f, 0xd8);
const QColor kColorFlagged(0xb4, 0x6a, 0x00);
const QColor kColorSelected(0x7a, 0x3e, 0xd8);
const QColor kColorBoundary(0x6b, 0x6f, 0x76);
const QColor kColorSurvey(0x12, 0x8c, 0x7e);
const QColor kColorSpatialCursor(0xd4, 0x46, 0x7c);

constexpr double kHitTolerancePx = 8.0;
constexpr int kClickDragTolerancePx = 4;

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

Json point_feature(double x, double y, const std::string& label) {
    return Json{{"type", "Feature"},
                {"geometry",
                 Json{{"type", "Point"}, {"coordinates", Json::array({x, y})}}},
                {"properties", Json{{"label", label}}}};
}

Json line_feature(const WellMapRing& ring) {
    Json coords = Json::array();
    for (const auto& p : ring) {
        coords.push_back(Json::array({p.first, p.second}));
    }
    return Json{{"type", "Feature"},
                {"geometry",
                 Json{{"type", "LineString"}, {"coordinates", coords}}},
                {"properties", Json::object()}};
}

Json feature_collection(const Json& features) {
    return Json{{"type", "FeatureCollection"}, {"features", features}};
}

// Symbol styling for the mirrored scene (same color role as the fallback
// painter; QGIS renders symbol size in millimetres so the px radii are
// approximated — visual parity, not a second renderer authority).
void style_point_layer(QgsVectorLayer* layer, const QColor& color,
                       double size_mm) {
    if (layer == nullptr) {
        return;
    }
    auto* single =
        dynamic_cast<QgsSingleSymbolRenderer*>(layer->renderer());
    if (single == nullptr || single->symbol() == nullptr) {
        return;
    }
    QgsSymbol* symbol = single->symbol();
    symbol->setColor(color);
    if (auto* marker = dynamic_cast<QgsMarkerSymbol*>(symbol)) {
        marker->setSize(size_mm);
    }
}

void style_line_layer(QgsVectorLayer* layer, const QColor& color,
                      double width_mm, Qt::PenStyle pen_style) {
    if (layer == nullptr) {
        return;
    }
    auto* single =
        dynamic_cast<QgsSingleSymbolRenderer*>(layer->renderer());
    if (single == nullptr || single->symbol() == nullptr) {
        return;
    }
    QgsSymbol* symbol = single->symbol();
    symbol->setColor(color);
    if (auto* line = dynamic_cast<QgsLineSymbol*>(symbol)) {
        line->setWidth(width_mm);
        for (QgsSymbolLayer* symbol_layer : symbol->symbolLayers()) {
            if (auto* simple =
                    dynamic_cast<QgsSimpleLineSymbolLayer*>(symbol_layer)) {
                simple->setPenStyle(pen_style);
            }
        }
    }
}

void apply_labels(QgsVectorLayer* layer, bool enabled) {
    if (layer == nullptr) {
        return;
    }
    QgsPalLayerSettings settings;
    settings.fieldName = QStringLiteral("label");
    layer->setLabeling(new QgsVectorLayerSimpleLabeling(settings));
    layer->setLabelsEnabled(enabled);
}

}  // namespace

WellMapQgisSurface::WellMapQgisSurface(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("WellMapQgisSurface"));
    setMinimumSize(240, 180);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    if (pwb::qgis::QgisRuntime::initialized()) {
        try {
            session_ = std::make_unique<pwb::qgis::MapSession>();
        } catch (const std::exception&) {
            session_.reset();
        }
    }
    if (session_ != nullptr) {
        canvas_ = session_->createCanvas(this);
        layout->addWidget(canvas_, 1);
        canvas_->setMouseTracking(true);
        // Scene coordinates are project XY — the page supplies no CRS, so
        // the canvas stays in no-OTF raw coordinates (V10 M-B parity:
        // never inherit a stale project CRS).
        canvas_->setDestinationCrs(QgsCoordinateReferenceSystem());
        pan_tool_ = new QgsMapToolPan(canvas_);
        canvas_->setMapTool(pan_tool_);
        canvas_->installEventFilter(this);
    } else {
        // Python falls back to UnifiedMapCanvas when QGIS is unavailable;
        // the page still owns the choice — here the surface reports the
        // gap explicitly instead of painting nothing.
        placeholder_ = new QLabel(QStringLiteral("QGIS 不可用"), this);
        placeholder_->setAlignment(Qt::AlignCenter);
        layout->addWidget(placeholder_, 1);
    }
}

WellMapQgisSurface::~WellMapQgisSurface() { shutdown(); }

void WellMapQgisSurface::shutdown() {
    if (shutdown_done_) {
        return;
    }
    shutdown_done_ = true;
    // MapSession::close() unsets tools, detaches canvases, drops layers —
    // in that order. The widgets themselves are parented here and die
    // with the Qt tree.
    if (session_ != nullptr) {
        session_->close();
    }
    pan_tool_ = nullptr;
    canvas_ = nullptr;
}

QString WellMapQgisSurface::backend_status() const {
    if (canvas_ != nullptr) {
        return QStringLiteral("qgis");
    }
    if (!pwb::qgis::QgisRuntime::initialized()) {
        return QStringLiteral("qgis-runtime-not-initialized");
    }
    return QStringLiteral("qgis-session-unavailable");
}

void WellMapQgisSurface::set_scene(const WellMapScene& scene) {
    scene_ = scene;
    rebuild_layers();
}

void WellMapQgisSurface::rebuild_layers() {
    if (session_ == nullptr || session_->project() == nullptr ||
        canvas_ == nullptr) {
        return;
    }
    QgsProject* project = session_->project();
    project->removeAllMapLayers();
    fit_extent_valid_ = false;

    const auto add_vector = [&](const Json& collection,
                                const std::string& layer_id,
                                const std::string& name) {
        const pwb::qgis::LayerBinding binding{layer_id, "", "", "vector"};
        std::string error;
        QgsVectorLayer* layer = session_->addVectorLayer(
            collection.dump(), name, binding, &error);
        if (layer != nullptr) {
            // Raw scene coordinates; keep OTF off per layer too.
            layer->setCrs(QgsCoordinateReferenceSystem());
        }
        return layer;
    };

    // Line overlays first — points draw on top (Python draw order).
    {
        Json features = Json::array();
        if (scene_.boundary.size() >= 2) {
            features.push_back(line_feature(scene_.boundary));
        }
        for (const auto& ring : scene_.reference_rings) {
            if (ring.size() >= 2) {
                features.push_back(line_feature(ring));
            }
        }
        QgsVectorLayer* lines = add_vector(
            feature_collection(features), "wellmap_boundary",
            "boundary+reference");
        style_line_layer(lines, kColorBoundary, 0.3, Qt::DashLine);
    }
    {
        Json features = Json::array();
        for (const auto& ring : scene_.survey_rings) {
            if (ring.size() >= 2) {
                features.push_back(line_feature(ring));
            }
        }
        QgsVectorLayer* lines = add_vector(
            feature_collection(features), "wellmap_surveys", "surveys");
        style_line_layer(lines, kColorSurvey, 0.25, Qt::DotLine);
    }
    {
        Json features = Json::array();
        for (std::size_t i = 0; i < scene_.ok_points.size(); ++i) {
            const auto& p = scene_.ok_points[i];
            if (std::isnan(p.first) || std::isnan(p.second)) {
                continue;
            }
            const std::string label =
                i < scene_.ok_labels.size() ? scene_.ok_labels[i] : "";
            features.push_back(point_feature(p.first, p.second, label));
        }
        QgsVectorLayer* points = add_vector(
            feature_collection(features), "wellmap_wells", "wells");
        style_point_layer(points, kColorOk, 2.0);
        apply_labels(points, scene_.show_labels);
    }
    {
        Json features = Json::array();
        for (std::size_t i = 0; i < scene_.flagged_points.size(); ++i) {
            const auto& p = scene_.flagged_points[i];
            if (std::isnan(p.first) || std::isnan(p.second)) {
                continue;
            }
            const std::string label =
                i < scene_.flagged_labels.size()
                    ? scene_.flagged_labels[i]
                    : "";
            features.push_back(point_feature(p.first, p.second, label));
        }
        QgsVectorLayer* points =
            add_vector(feature_collection(features), "wellmap_flagged",
                       "wells flagged");
        style_point_layer(points, kColorFlagged, 2.0);
        apply_labels(points, scene_.show_labels);
    }
    {
        Json features = Json::array();
        for (const auto& p : scene_.selected_points) {
            if (std::isnan(p.first) || std::isnan(p.second)) {
                continue;
            }
            features.push_back(point_feature(p.first, p.second, ""));
        }
        QgsVectorLayer* points =
            add_vector(feature_collection(features), "wellmap_selected",
                       "wells selected");
        style_point_layer(points, kColorSelected, 3.0);
    }
    if (scene_.spatial_cursor.has_value()) {
        Json features = Json::array();
        features.push_back(point_feature(scene_.spatial_cursor->first,
                                         scene_.spatial_cursor->second,
                                         ""));
        QgsVectorLayer* cursor = add_vector(
            feature_collection(features), "wellmap_cursor", "cursor");
        style_point_layer(cursor, kColorSpatialCursor, 3.2);
    }

    session_->refreshCanvases();
}

void WellMapQgisSurface::autofit() {
    if (canvas_ == nullptr || session_ == nullptr) {
        return;
    }
    session_->zoomToFullExtent(canvas_);
    const QgsRectangle rect = canvas_->extent();
    if (!rect.isEmpty()) {
        fit_extent_[0] = rect.xMinimum();
        fit_extent_[1] = rect.yMinimum();
        fit_extent_[2] = rect.xMaximum();
        fit_extent_[3] = rect.yMaximum();
        fit_extent_valid_ = true;
    }
}

void WellMapQgisSurface::reset_view() { autofit(); }

void WellMapQgisSurface::set_view_bounds(double xmin, double xmax,
                                         double ymin, double ymax) {
    if (canvas_ == nullptr) {
        return;
    }
    canvas_->setExtent(QgsRectangle(xmin, ymin, xmax, ymax));
    canvas_->refresh();
}

void WellMapQgisSurface::focus_point(double x, double y,
                                     double zoom_factor) {
    if (canvas_ == nullptr) {
        return;
    }
    // Python plot.focus_point: center on the point at base-fit scale
    // multiplied by zoom_factor → the QGIS equivalent shrinks the
    // recorded fit extent by the same factor around the point.
    if (!fit_extent_valid_) {
        autofit();
    }
    double width = canvas_->extent().width();
    double height = canvas_->extent().height();
    if (fit_extent_valid_) {
        width = fit_extent_[2] - fit_extent_[0];
        height = fit_extent_[3] - fit_extent_[1];
    }
    const double factor = std::max(zoom_factor, 1e-6);
    const double half_w = width / (2.0 * factor);
    const double half_h = height / (2.0 * factor);
    canvas_->setExtent(QgsRectangle(x - half_w, y - half_h, x + half_w,
                                    y + half_h));
    canvas_->refresh();
}

std::optional<QPointF> WellMapQgisSurface::map_to_screen(
    double x, double y) const {
    if (canvas_ == nullptr) {
        return std::nullopt;
    }
    const QgsMapToPixel* transform = canvas_->getCoordinateTransform();
    if (transform == nullptr || !transform->isValid()) {
        return std::nullopt;
    }
    const QgsPointXY screen = transform->transform(QgsPointXY(x, y));
    if (!std::isfinite(screen.x()) || !std::isfinite(screen.y())) {
        return std::nullopt;
    }
    return screen.toQPointF();
}

std::optional<WellMapPoint> WellMapQgisSurface::screen_to_map(
    const QPointF& pos) const {
    if (canvas_ == nullptr) {
        return std::nullopt;
    }
    const QgsMapToPixel* transform = canvas_->getCoordinateTransform();
    if (transform == nullptr || !transform->isValid()) {
        return std::nullopt;
    }
    const QgsPointXY map = transform->toMapCoordinates(pos.toPoint());
    if (!std::isfinite(map.x()) || !std::isfinite(map.y())) {
        return std::nullopt;
    }
    return WellMapPoint{map.x(), map.y()};
}

bool WellMapQgisSurface::hit_test(const QPointF& pos, std::string* series,
                                  int* index, WellMapPoint* point) const {
    // Same contract as the QPainter fallback: nearest point within 8 px,
    // "wells" probed before "wells_flagged".
    double best = kHitTolerancePx;
    bool found = false;
    const auto probe = [&](const std::vector<WellMapPoint>& points,
                           const std::string& name) {
        for (std::size_t i = 0; i < points.size(); ++i) {
            const auto screen = map_to_screen(points[i].first,
                                              points[i].second);
            if (!screen.has_value()) {
                continue;
            }
            const double distance = std::hypot(screen->x() - pos.x(),
                                               screen->y() - pos.y());
            if (distance <= best) {
                best = distance;
                *series = name;
                *index = static_cast<int>(i);
                *point = points[i];
                found = true;
            }
        }
    };
    probe(scene_.ok_points, "wells");
    probe(scene_.flagged_points, "wells_flagged");
    return found;
}

bool WellMapQgisSurface::eventFilter(QObject* watched, QEvent* event) {
    if (canvas_ != nullptr && watched == canvas_) {
        if (event->type() == QEvent::MouseButtonPress) {
            auto* mouse = static_cast<QMouseEvent*>(event);
            if (mouse->button() == Qt::LeftButton) {
                pressed_ = true;
                press_pos_ = mouse->position();
            }
        } else if (event->type() == QEvent::MouseButtonRelease) {
            auto* mouse = static_cast<QMouseEvent*>(event);
            if (mouse->button() == Qt::LeftButton && pressed_) {
                pressed_ = false;
                const QPointF delta = mouse->position() - press_pos_;
                if (delta.manhattanLength() < kClickDragTolerancePx) {
                    std::string series;
                    int index = -1;
                    WellMapPoint point{0.0, 0.0};
                    if (hit_test(mouse->position(), &series, &index,
                                 &point) &&
                        on_point_clicked) {
                        on_point_clicked(series, index, point.first,
                                         point.second);
                    }
                }
            }
        } else if (event->type() == QEvent::MouseMove) {
            auto* mouse = static_cast<QMouseEvent*>(event);
            std::string series;
            int index = -1;
            WellMapPoint point{0.0, 0.0};
            if (hit_test(mouse->position(), &series, &index, &point) &&
                on_point_hovered) {
                on_point_hovered(series, index, point.first,
                                 point.second);
            }
        }
    }
    return QWidget::eventFilter(watched, event);
}

void WellMapQgisSurface::closeEvent(QCloseEvent* event) {
    shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_wellseis::qgis
