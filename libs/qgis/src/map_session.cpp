#include <pwb/qgis/map_session.hpp>

#include <QList>

#include <qgscoordinatetransform.h>
#include <qgsmapcanvas.h>
#include <qgsproject.h>
#include <qgsrasterlayer.h>
#include <qgsrectangle.h>
#include <qgsvectorlayer.h>
#include <qgslayertree.h>
#include <qgslayertreemapcanvasbridge.h>
#include <qgslayertreeview.h>
#include <qgslayertreemodel.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsmaplayer.h>
#include <qgsexception.h>
#include <qgserror.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

namespace pwb::qgis {

MapSession::MapSession() {
    if (!QgisRuntime::initialized()) {
        throw std::logic_error("MapSession requires QgisRuntime::acquire() first");
    }
    project_ = std::make_unique<QgsProject>();
}

MapSession::~MapSession() { close(); }

QgsMapCanvas* MapSession::createCanvas(QWidget* parent) {
    auto* canvas = new QgsMapCanvas(parent);
    canvas->setCanvasColor(Qt::white);
    canvas->enableAntiAliasing(true);
    canvas->setProject(project_.get());
    // Tree-driven canvas layer set: the bridge keeps canvas == tree == legend
    // order in sync (V11 authority decision). Bridge dies with the canvas.
    auto* bridge = new QgsLayerTreeMapCanvasBridge(project_->layerTreeRoot(),
                                                   canvas, canvas);
    bridge->setCanvasLayers();
    canvases_.push_back(QPointer<QgsMapCanvas>(canvas));
    return canvas;
}

QgsLayerTreeView* MapSession::createLayerTree(QWidget* parent) {
    auto* view = new QgsLayerTreeView(parent);
    auto* model = new QgsLayerTreeModel(project_->layerTreeRoot(), view);
    view->setModel(model);
    trees_.push_back(QPointer<QgsLayerTreeView>(view));
    return view;
}

QgsVectorLayer* MapSession::addVectorLayer(const std::string& uri,
                                           const std::string& name,
                                           const LayerBinding& binding,
                                           std::string* error) {
    auto* layer = new QgsVectorLayer(QString::fromStdString(uri),
                                     QString::fromStdString(name), "ogr");
    if (!layer->isValid()) {
        const QString detail = layer->error().message(QgsErrorMessage::Text);
        delete layer;
        if (error != nullptr) {
            *error = "vector provider failed for '" + uri + "': "
                + detail.toStdString();
        }
        return nullptr;
    }
    layer_adapter::apply(layer, binding);
    project_->addMapLayer(layer);
    syncCanvasLayers();
    return layer;
}

QgsRasterLayer* MapSession::addRasterLayer(const std::string& uri,
                                           const std::string& name,
                                           const LayerBinding& binding,
                                           std::string* error) {
    auto* layer = new QgsRasterLayer(QString::fromStdString(uri),
                                     QString::fromStdString(name));
    if (!layer->isValid()) {
        const QString detail = layer->error().message(QgsErrorMessage::Text);
        delete layer;
        if (error != nullptr) {
            *error = "raster provider failed for '" + uri + "': "
                + detail.toStdString();
        }
        return nullptr;
    }
    layer_adapter::apply(layer, binding);
    project_->addMapLayer(layer);
    syncCanvasLayers();
    return layer;
}

QgsMapLayer* MapSession::layerById(const std::string& layer_id) const {
    if (project_ == nullptr) return nullptr;   // closed session
    const auto layers = project_->mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        if (layer_adapter::layer_id_of(it.value()) == layer_id) return it.value();
    }
    return nullptr;
}

QgsVectorLayer* MapSession::vectorLayerById(const std::string& layer_id) const {
    return qobject_cast<QgsVectorLayer*>(layerById(layer_id));
}

std::vector<std::string> MapSession::layerIdsTopFirst() const {
    std::vector<std::string> order;
    if (project_ == nullptr) return order;   // closed session
    const QList<QgsMapLayer*> layers = project_->layerTreeRoot()->layerOrder();
    for (QgsMapLayer* layer : layers) {
        if (layer == nullptr || !layer->isSpatial()) continue;
        order.push_back(layer_adapter::layer_id_of(layer));
    }
    return order;
}

std::string MapSession::canvas_state_json() const {
    pwb::domain::Json state = pwb::domain::Json::object();
    if (project_ == nullptr) return state.dump();

    const QgsCoordinateReferenceSystem project_crs = project_->crs();
    state["crs"] = project_crs.authid().toStdString();

    // Extent: first live canvas, else the visible spatial-layer union
    // transformed into the project CRS; null when neither exists.
    QgsRectangle extent;
    bool has_extent = false;
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas == nullptr) continue;
        extent = canvas->extent();
        has_extent = !extent.isEmpty();
        break;
    }
    if (!has_extent) {
        for (QgsMapLayer* layer : project_->layerTreeRoot()->layerOrder()) {
            if (layer == nullptr || !layer->isSpatial()) continue;
            QgsLayerTreeLayer* node =
                project_->layerTreeRoot()->findLayer(layer);
            if (node == nullptr || !node->isVisible()) continue;
            QgsRectangle box = layer->extent();
            if (box.isEmpty()) continue;
            if (layer->crs() != project_crs && layer->crs().isValid()
                && project_crs.isValid()) {
                QgsCoordinateTransform transform(
                    layer->crs(), project_crs, project_->transformContext());
                try {
                    box = transform.transformBoundingBox(box);
                } catch (const QgsCsException&) {
                    continue;  // untransformable layer: honest extent gap
                }
            }
            if (has_extent) {
                extent.combineExtentWith(box);
            } else {
                extent = box;
                has_extent = true;
            }
        }
    }
    if (has_extent) {
        state["extent"] = pwb::domain::Json::array(
            {extent.xMinimum(), extent.yMinimum(), extent.xMaximum(),
             extent.yMaximum()});
    } else {
        state["extent"] = nullptr;
    }

    pwb::domain::Json layers = pwb::domain::Json::array();
    for (QgsMapLayer* layer : project_->layerTreeRoot()->layerOrder()) {
        if (layer == nullptr || !layer->isSpatial()) continue;
        QgsLayerTreeLayer* node = project_->layerTreeRoot()->findLayer(layer);
        const std::string id = layer_adapter::layer_id_of(layer);
        layers.push_back(pwb::domain::Json::object(
            {{"id", id.empty() ? layer->id().toStdString() : id},
             {"visible", node != nullptr && node->isVisible()}}));
    }
    state["layers"] = layers;
    // The plain QgsMapCanvas draws no grid overlay; the layer tree panel is
    // the on-screen legend equivalent.
    state["grid"] = false;
    state["legend"] = !trees_.empty();
    return state.dump();
}

void MapSession::setDestinationCrs(const std::string& auth_id, std::string* error) {
    const QgsCoordinateReferenceSystem crs =
        QgsCoordinateReferenceSystem::fromOgcWmsCrs(QString::fromStdString(auth_id));
    if (!crs.isValid()) {
        if (error != nullptr) *error = "invalid destination CRS: " + auth_id;
        return;
    }
    project_->setCrs(crs);
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas != nullptr) canvas->setDestinationCrs(crs);
    }
}

void MapSession::refreshCanvases() {
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas != nullptr) canvas->refresh();
    }
}

// BEGIN V14-QGIS-CONTROL
std::vector<QgsMapCanvas*> MapSession::canvases() const {
    std::vector<QgsMapCanvas*> out;
    out.reserve(canvases_.size());
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas != nullptr) out.push_back(canvas.data());
    }
    return out;
}
// END V14-QGIS-CONTROL

void MapSession::zoomToFullExtent(QgsMapCanvas* canvas) {
    if (canvas != nullptr) canvas->zoomToFullExtent();
}

void MapSession::syncCanvasLayers() {
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas == nullptr) continue;
        // The per-canvas bridge follows the tree; a canvas without its
        // bridge still gets an explicit layer set from the tree order.
        QList<QgsMapLayer*> layers;
        const QList<QgsMapLayer*> order = project_->layerTreeRoot()->layerOrder();
        for (QgsMapLayer* layer : order) {
            if (layer == nullptr || !layer->isSpatial()) continue;
            QgsLayerTreeLayer* node = project_->layerTreeRoot()->findLayer(layer);
            if (node == nullptr || !node->isVisible()) continue;
            layers.append(layer);
        }
        canvas->setLayers(layers);
        canvas->refresh();
    }
}

void MapSession::close() {
    if (closed_ || !project_) return;
    closed_ = true;
    // Contract order: unset tools, detach canvases, drop layers, then the
    // project. Widgets themselves belong to their Qt parents.
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas == nullptr) continue;
        if (QgsMapTool* tool = canvas->mapTool()) canvas->unsetMapTool(tool);
        canvas->setLayers(QList<QgsMapLayer*>());
        canvas->setProject(nullptr);
    }
    canvases_.clear();
    trees_.clear();
    project_->removeAllMapLayers();
    project_.reset();
}

}  // namespace pwb::qgis
