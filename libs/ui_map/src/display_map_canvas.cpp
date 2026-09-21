#include <pwb/ui_map/display_map_canvas.hpp>

#include <QEvent>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QVBoxLayout>

#include <cmath>
#include <set>

#include <qgscoordinatereferencesystem.h>
#include <qgsrenderer.h>
#include <qgsfillsymbollayer.h>
#include <qgslayertree.h>
#include <qgslinesymbol.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptopixel.h>
#include <qgsmarkersymbol.h>
#include <qgsmarkersymbollayer.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgssinglesymbolrenderer.h>
#include <qgssymbol.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_map/map_chrome_painter.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

Extent to_extent(const QgsRectangle& rect) {
    return Extent{rect.xMinimum(), rect.yMinimum(), rect.xMaximum(),
                  rect.yMaximum()};
}

// Style application for the mirror: the snapshot carries the VectorStyle
// dict ({fill, stroke, stroke_width, marker_size, opacity}); the single
// symbol renderer honors those keys. Renderer-kind dispatch (categorized /
// graduated / labels) is owned by the bridge's style codec — out of scope
// for read-only display (missing keys keep QGIS defaults, never a second
// authority).
void apply_vector_style(QgsVectorLayer* layer, const Json& style) {
    if (layer == nullptr || !style.is_object()) {
        return;
    }
    QgsFeatureRenderer* renderer = layer->renderer();
    auto* single = dynamic_cast<QgsSingleSymbolRenderer*>(renderer);
    if (single == nullptr || single->symbol() == nullptr) {
        return;
    }
    QgsSymbol* symbol = single->symbol();
    const std::string fill = field_value_str(style, "fill", "");
    const std::string stroke = field_value_str(style, "stroke", "");
    const Json stroke_width_raw =
        field_value(style, "stroke_width", Json(nullptr));
    const Json marker_size_raw =
        field_value(style, "marker_size", Json(nullptr));
    if (!fill.empty() && fill != "transparent") {
        symbol->setColor(QColor(qstr(fill)));
    } else if (!stroke.empty() && stroke != "transparent") {
        symbol->setColor(QColor(qstr(stroke)));
    }
    if (marker_size_raw.is_number() &&
        symbol->type() == Qgis::SymbolType::Marker) {
        const double size = marker_size_raw.get<double>();
        if (size > 0.0) {
            if (auto* marker = dynamic_cast<QgsMarkerSymbol*>(symbol)) {
                marker->setSize(size);
            }
        }
    }
    if (stroke_width_raw.is_number()) {
        const double width = stroke_width_raw.get<double>();
        if (width > 0.0) {
            if (auto* line = dynamic_cast<QgsLineSymbol*>(symbol)) {
                line->setWidth(width);
            } else {
                // Fill/marker symbols carry the stroke width on the symbol
                // layer, not on the symbol itself.
                for (QgsSymbolLayer* symbol_layer : symbol->symbolLayers()) {
                    if (auto* fill =
                            dynamic_cast<QgsSimpleFillSymbolLayer*>(
                                symbol_layer)) {
                        fill->setStrokeWidth(width);
                    } else if (auto* marker =
                                   dynamic_cast<QgsSimpleMarkerSymbolLayer*>(
                                       symbol_layer)) {
                        marker->setStrokeWidth(width);
                    }
                }
            }
        }
    }
}

}  // namespace

// Transparent overlay painted on top of the canvas viewport: selected
// feature rings + map chrome (Python _Overlay parity). Declared in
// pwb::ui_map (NOT the anonymous namespace above) so the
// DisplayMapCanvas::CanvasOverlay friend declaration names this class.
class CanvasOverlay : public QWidget {
public:
    explicit CanvasOverlay(DisplayMapCanvas* host) : QWidget(host) {
        setAttribute(Qt::WA_TransparentForMouseEvents, true);
        setAttribute(Qt::WA_TranslucentBackground, true);
        setAttribute(Qt::WA_NoSystemBackground, true);
        setAutoFillBackground(false);
        host_ = host;
    }

protected:
    void paintEvent(QPaintEvent*) override {
        DisplayMapCanvas* host = host_;
        if (host == nullptr) {
            return;
        }
        // Provider returns a cached const& (#1392) — the paint path used
        // to pay a full JSON-tree copy + rebuild every frame.
        Json fallback = Json::object();
        const Json* state = &fallback;
        if (host->overlay_provider_) {
            try {
                state = &host->overlay_provider_();
            } catch (...) {
                // #1001 parity: an overlay-provider failure inside paintEvent
                // must degrade to an empty state, never abort the painter.
            }
        }
        if (!state->is_object()) {
            state = &fallback;
        }
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        const Json selected =
            field_value(*state, "selected_features", Json::array());
        if (selected.is_array() && !selected.empty()) {
            // Python uses the theme CANVAS_SELECTION token; the style
            // registry exposes it through the palette when bound — fall
            // back to the Python default accent.
            painter.setPen(QPen(QColor("#e8b339"), 2.0));
            painter.setBrush(Qt::NoBrush);
            for (const auto& feature : selected) {
                const Json geometry =
                    field_value(feature, "geometry", Json::object());
                if (!geometry.is_object() ||
                    field_value_str(geometry, "type", "") != "Point") {
                    continue;
                }
                const Json coords = field_value(geometry, "coordinates",
                                                Json::array());
                if (!coords.is_array() || coords.size() < 2) {
                    continue;
                }
                const auto screen = host->map_to_screen(
                    coords.at(0).get<double>(), coords.at(1).get<double>());
                if (!screen.has_value()) {
                    continue;
                }
                painter.drawEllipse(*screen, 8.0, 8.0);
            }
        }
        const Json decorations =
            field_value(*state, "decorations", Json::object());
        paint_map_decorations(painter, decorations, width(), height(),
                              host->view_extent(), 0.0,
                              /*dark_chrome=*/true);
        painter.end();
    }

private:
    QPointer<DisplayMapCanvas> host_;
};

DisplayMapCanvas::DisplayMapCanvas(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DisplayMapCanvas"));
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
        pan_tool_ = new QgsMapToolPan(canvas_);
        canvas_->setMapTool(pan_tool_);
        connect(canvas_, &QgsMapCanvas::extentsChanged, this,
                [this]() { on_canvas_extents_changed(); });
        connect(canvas_, &QgsMapCanvas::xyCoordinates, this,
                [this](const QgsPointXY& p) {
                    emit map_position_changed(p.x(), p.y());
                });
        canvas_->installEventFilter(this);
        overlay_ = new CanvasOverlay(this);
        install_overlay_geometry();
        overlay_->raise();
        overlay_->show();
    } else {
        // Python falls back to UnifiedMapCanvas (software renderer); the
        // C++ fallback renderer does not exist in this slice — an explicit
        // placeholder keeps the unavailable state visible, never silent.
        placeholder_ = new QLabel(QStringLiteral("QGIS 不可用"), this);
        placeholder_->setAlignment(Qt::AlignCenter);
        layout->addWidget(placeholder_, 1);
    }
}

DisplayMapCanvas::~DisplayMapCanvas() { shutdown(); }

void DisplayMapCanvas::shutdown() {
    if (shutdown_done_) {
        return;
    }
    shutdown_done_ = true;
    // MapSession::close() unsets tools, detaches canvases, drops layers —
    // the widget children die with Qt, the project dies here.
    session_.reset();
    canvas_ = nullptr;
    pan_tool_ = nullptr;
}

QString DisplayMapCanvas::backend_status() const {
    if (canvas_ == nullptr) {
        return QStringLiteral("unavailable");
    }
    if (!mirror_failures_.empty()) {
        return QStringLiteral("qgis: degraded (%1 mirror failures)")
            .arg(mirror_failures_.size());
    }
    return QStringLiteral("qgis");
}

void DisplayMapCanvas::set_layer_snapshot(const Json& snapshot) {
    if (shutdown_done_) {
        return;
    }
    snapshot_ = snapshot.is_object() ? snapshot : Json::object();
    mirror_failures_.clear();
    if (canvas_ == nullptr || session_ == nullptr ||
        session_->project() == nullptr) {
        emit backend_status_changed(backend_status());
        return;
    }
    QgsProject* project = session_->project();
    const std::string project_crs =
        field_value_str(snapshot_, "project_crs", "");

    // V10 M-E (R4) duplicate-id guard: reject the second occurrence.
    std::set<std::string> seen_ids;
    std::set<std::string> duplicates;
    const Json layers = field_value(snapshot_, "layers", Json::array());
    if (layers.is_array()) {
        for (const auto& layer : layers) {
            const std::string id = field_value_str(layer, "id", "");
            if (!id.empty() && !seen_ids.insert(id).second) {
                duplicates.insert(id);
            }
        }
    }
    for (const std::string& dup : duplicates) {
        mirror_failures_.push_back(
            "layer " + dup + ": duplicate layer id in snapshot");
    }
    seen_ids.clear();

    project->removeAllMapLayers();
    if (layers.is_array()) {
        for (const auto& layer : layers) {
            const std::string id = field_value_str(layer, "id", "");
            // Publish the first occurrence only; later occurrences of the
            // same id were already diagnosed as duplicates above.
            if (!id.empty() && !seen_ids.insert(id).second) {
                continue;
            }
            const std::string layer_type =
                field_value_str(layer, "layer_type", "vector");
            if (layer_type != "vector") {
                // Raster/scalar mirror is bridge-owned; read-only display
                // reports the gap as a mirror failure (never silently
                // dropped — #1164).
                mirror_failures_.push_back(
                    "layer " + id + ": non-vector mirror unavailable");
                continue;
            }
            const Json features =
                field_value(layer, "features", Json::array());
            const Json feature_collection = Json{
                {"type", "FeatureCollection"},
                {"features",
                 features.is_array() ? features : Json::array()}};
            const std::string name =
                field_value_str(layer, "name", id);
            const pwb::qgis::LayerBinding binding{id, "", "", "vector"};
            std::string error;
            QgsVectorLayer* vector_layer = session_->addVectorLayer(
                feature_collection.dump(), name, binding, &error);
            if (vector_layer == nullptr) {
                mirror_failures_.push_back("layer " + id + ": " + error);
                continue;
            }
            const std::string layer_crs =
                field_value_str(layer, "crs", "");
            const std::string effective_crs =
                layer_crs.empty() ? project_crs : layer_crs;
            if (!effective_crs.empty()) {
                vector_layer->setCrs(
                    QgsCoordinateReferenceSystem::fromOgcWmsCrs(
                        qstr(effective_crs)));
            }
            apply_vector_style(vector_layer,
                               field_value(layer, "style", Json::object()));
            const Json opacity =
                field_value(layer, "opacity", Json(nullptr));
            if (opacity.is_number()) {
                vector_layer->setOpacity(opacity.get<double>());
            }
            const bool visible =
                !field_value(layer, "visible", Json(true)).is_boolean() ||
                field_value(layer, "visible", Json(true)).get<bool>();
            QgsLayerTreeLayer* node =
                project->layerTreeRoot()->findLayer(vector_layer->id());
            if (node != nullptr) {
                node->setItemVisibilityChecked(visible);
            }
        }
    }

    // V10 M-B parity: an empty snapshot CRS still resets the canvas to
    // no-OTF (raw coordinates) — never leave the previous project's CRS.
    if (project_crs.empty()) {
        canvas_->setDestinationCrs(QgsCoordinateReferenceSystem());
    } else {
        std::string crs_error;
        session_->setDestinationCrs(project_crs, &crs_error);
        if (!crs_error.empty()) {
            mirror_failures_.push_back("crs '" + project_crs +
                                       "': " + crs_error);
        }
    }
    session_->refreshCanvases();
    if (overlay_ != nullptr) {
        overlay_->update();
    }
    emit backend_status_changed(backend_status());
}

Extent DisplayMapCanvas::view_extent() const {
    if (canvas_ != nullptr) {
        return to_extent(canvas_->extent());
    }
    return history_.current();
}

void DisplayMapCanvas::set_extent(const Extent& extent, bool record_history,
                                  bool coalesce_history) {
    if (record_history) {
        history_.record(extent, coalesce_history);
    }
    pending_programmatic_ = true;
    if (canvas_ != nullptr) {
        canvas_->setExtent(QgsRectangle(extent[0], extent[1], extent[2],
                                        extent[3]));
        canvas_->refresh();
    }
    emit extent_changed(extent);
    if (overlay_ != nullptr) {
        overlay_->update();
    }
}

void DisplayMapCanvas::zoom_by(
    double factor, std::optional<std::pair<double, double>> center,
    bool coalesce_history) {
    const Extent target =
        ui_map::zoom_by(view_extent(), factor, std::move(center));
    set_extent(target, true, coalesce_history);
}

bool DisplayMapCanvas::previous_extent() {
    const auto extent = history_.previous();
    if (!extent.has_value()) {
        return false;
    }
    set_extent(*extent, false);
    return true;
}

bool DisplayMapCanvas::next_extent() {
    const auto extent = history_.next();
    if (!extent.has_value()) {
        return false;
    }
    set_extent(*extent, false);
    return true;
}

std::optional<QPointF> DisplayMapCanvas::map_to_screen(double x,
                                                     double y) const {
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

std::pair<double, double> DisplayMapCanvas::screen_to_map(
    const QPointF& point) const {
    if (canvas_ == nullptr) {
        return {0.0, 0.0};
    }
    const QgsMapToPixel* transform = canvas_->getCoordinateTransform();
    if (transform == nullptr || !transform->isValid()) {
        return {0.0, 0.0};
    }
    const QgsPointXY map = transform->toMapCoordinates(point.toPoint());
    if (!std::isfinite(map.x()) || !std::isfinite(map.y())) {
        return {0.0, 0.0};
    }
    return {map.x(), map.y()};
}

double DisplayMapCanvas::map_units_per_pixel() const {
    const int width =
        canvas_ != nullptr ? std::max(1, canvas_->width()) : 1;
    const int height =
        canvas_ != nullptr ? std::max(1, canvas_->height()) : 1;
    return ui_map::map_units_per_pixel(view_extent(), width, height);
}

std::vector<std::string> DisplayMapCanvas::snapshot_source_version_ids()
    const {
    return ui_map::snapshot_source_version_ids(snapshot_);
}

void DisplayMapCanvas::set_overlay_provider(
    std::function<const Json&()> provider) {
    overlay_provider_ = std::move(provider);
    if (overlay_ != nullptr) {
        overlay_->update();
    }
}

void DisplayMapCanvas::set_layer_visible(const std::string& layer_id,
                                         bool visible) {
    if (session_ == nullptr || session_->project() == nullptr) {
        return;
    }
    QgsMapLayer* layer = session_->layerById(layer_id);
    if (layer == nullptr) {
        return;
    }
    QgsLayerTreeLayer* node =
        session_->project()->layerTreeRoot()->findLayer(layer->id());
    if (node != nullptr) {
        node->setItemVisibilityChecked(visible);
    }
    session_->refreshCanvases();
}

void DisplayMapCanvas::on_canvas_extents_changed() {
    if (canvas_ == nullptr) {
        return;
    }
    const Extent extent = to_extent(canvas_->extent());
    if (pending_programmatic_) {
        pending_programmatic_ = false;
        emit extent_changed(extent);
        if (overlay_ != nullptr) {
            overlay_->update();
        }
        return;
    }
    history_.record(extent);
    emit extent_changed(extent);
    emit tool_operation(false);
    if (overlay_ != nullptr) {
        overlay_->update();
    }
}

void DisplayMapCanvas::install_overlay_geometry() {
    if (overlay_ == nullptr) {
        return;
    }
    QWidget* host = canvas_ != nullptr ? static_cast<QWidget*>(canvas_)
                                       : static_cast<QWidget*>(this);
    if (overlay_->parentWidget() != host) {
        overlay_->setParent(host);
    }
    overlay_->setGeometry(host->rect());
    overlay_->raise();
    overlay_->show();
}

void DisplayMapCanvas::emit_click(const QPointF& pos) {
    const auto point = screen_to_map(pos);
    emit map_clicked(point.first, point.second);
}

bool DisplayMapCanvas::eventFilter(QObject* watched, QEvent* event) {
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
                if (delta.manhattanLength() < kMapClickDragTolerance) {
                    emit_click(mouse->position());
                }
            }
        }
    }
    return QWidget::eventFilter(watched, event);
}

void DisplayMapCanvas::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    install_overlay_geometry();
}

void DisplayMapCanvas::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    install_overlay_geometry();
}

void DisplayMapCanvas::closeEvent(QCloseEvent* event) {
    shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_map
