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

#include <QPointer>
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
    // order in sync (V11 authority decision). Bridge dies with the canvas;
    // the session tracks it for the project-read window (see
    // attach/detach_canvas_bridges).
// R2-14: a closed session must refuse, not deref a null project_.
    if (project_ == nullptr) {
    throw std::runtime_error("MapSession::createCanvas after close()");
}
    auto* bridge = new QgsLayerTreeMapCanvasBridge(project_->layerTreeRoot(),
                                                   canvas, canvas);
    bridge->setCanvasLayers();
    // The vendored bridge subscribes layersAdded on QgsProject::instance()
    // (the app singleton), not on this session's project — admission must
    // nudge it explicitly (see syncBridges). Tree-side signals are wired
    // to the real root and work natively.
    bridges_.push_back(QPointer<QgsLayerTreeMapCanvasBridge>(bridge));
    canvases_.push_back(QPointer<QgsMapCanvas>(canvas));
    return canvas;
}

void MapSession::detach_canvas_bridges() {
    for (const QPointer<QgsLayerTreeMapCanvasBridge>& bridge : bridges_) {
        delete bridge.data();  // synchronous: no deferred callback survives
    }
    bridges_.clear();
}

void MapSession::attach_canvas_bridges() {
    if (project_ == nullptr) return;
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas == nullptr) continue;
        auto* bridge = new QgsLayerTreeMapCanvasBridge(project_->layerTreeRoot(),
                                                       canvas, canvas);
        bridge->setCanvasLayers();
        bridges_.push_back(QPointer<QgsLayerTreeMapCanvasBridge>(bridge));
    }
}

QgsLayerTreeView* MapSession::createLayerTree(QWidget* parent) {
    auto* view = new QgsLayerTreeView(parent);
    auto* model = new QgsLayerTreeModel(project_->layerTreeRoot(), view);
    model->setFlags(
        QgsLayerTreeModel::ShowLegend |
        QgsLayerTreeModel::ShowLegendAsTree |
        QgsLayerTreeModel::DeferredLegendInvalidation |
        QgsLayerTreeModel::UseTextFormatting |
        QgsLayerTreeModel::AllowNodeReorder |
        QgsLayerTreeModel::AllowNodeRename |
        QgsLayerTreeModel::AllowNodeChangeVisibility |
        QgsLayerTreeModel::AllowLegendChangeState |
        QgsLayerTreeModel::ActionHierarchical);
    view->setModel(model);
    trees_.push_back(QPointer<QgsLayerTreeView>(view));
    return view;
}

QgsMapLayer* MapSession::adopt_layer(QgsMapLayer* layer,
                                     const LayerBinding& binding,
                                     std::string* error) {
    std::unique_ptr<QgsMapLayer> owned(layer);
    if (owned == nullptr) {
        if (error != nullptr) *error = "null layer passed to adopt_layer";
        return nullptr;
    }
    if (project_ == nullptr) {
        throw std::runtime_error("MapSession::adopt_layer after close()");
    }
    if (!owned->isValid()) {
        const QString detail =
            owned->error().message(QgsErrorMessage::Text);
        if (error != nullptr) {
            *error = "provider failed for '" + owned->source().toStdString()
                + "': " + detail.toStdString();
        }
        return nullptr;  // unique_ptr deletes the invalid layer
    }
    layer_adapter::apply(owned.get(), binding);
    QgsMapLayer* admitted = owned.release();
    assignDeterministicLayerId(admitted, binding);
    // The registry bridge inserts the node; the canvas layer set follows
    // through QgsLayerTreeMapCanvasBridge (the single canvas writer —
    // nudged here because the vendored bridge listens for layersAdded on
    // the project singleton, not on this session's project).
    project_->addMapLayer(admitted);
    syncBridges();
    return admitted;
}

QgsVectorLayer* MapSession::addVectorLayer(const std::string& uri,
                                           const std::string& name,
                                           const LayerBinding& binding,
                                           std::string* error) {
    auto* layer = new QgsVectorLayer(QString::fromStdString(uri),
                                     QString::fromStdString(name), "ogr");
    return qobject_cast<QgsVectorLayer*>(adopt_layer(layer, binding, error));
}

QgsRasterLayer* MapSession::addRasterLayer(const std::string& uri,
                                           const std::string& name,
                                           const LayerBinding& binding,
                                           std::string* error) {
    auto* layer = new QgsRasterLayer(QString::fromStdString(uri),
                                     QString::fromStdString(name));
    return qobject_cast<QgsRasterLayer*>(adopt_layer(layer, binding, error));
}

QgsMapLayer* MapSession::layerById(const std::string& layer_id) const {
    if (project_ == nullptr) return nullptr;   // closed session
    // Fast path: admitted layers carry the domain id as their QGIS id
    // (assignDeterministicLayerId), so the project registry resolves in
    // O(1).
    if (QgsMapLayer* direct = project_->mapLayer(
            QString::fromStdString(layer_id))) {
        return direct;
    }
    // Fallback for layers admitted outside the deterministic-id policy
    // (id kept random on a collision): resolve through the pwb/layer_id
    // custom property instead.
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
// R2-14: a closed session must refuse, not deref a null project_.
    if (project_ == nullptr) {
    throw std::runtime_error("MapSession::setDestinationCrs after close()");
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

void MapSession::syncBridges() {
    // Route every post-admission canvas update through the tree bridge
    // (the single canvas-layer-set writer). No parallel setLayers path.
    for (const QPointer<QgsLayerTreeMapCanvasBridge>& bridge : bridges_) {
        if (bridge != nullptr) bridge->setCanvasLayers();
    }
}

void MapSession::assignDeterministicLayerId(QgsMapLayer* layer,
                                            const LayerBinding& binding) {
    // The domain join key doubles as the QGIS layer id: the project
    // registry resolves layerById in O(1) and the tree sidecar's layer
    // references (QgsLayerTree::writeXml stores layer ids) survive
    // across sessions without an id remap. setId only works before the
    // layer joins a project/store; collisions (id already taken) keep
    // the random id — the custom-property join still resolves.
    if (layer == nullptr || binding.layer_id.empty()) return;
    const QString id = QString::fromStdString(binding.layer_id);
    if (id == layer->id()) return;
    if (project_->mapLayer(id) != nullptr) return;  // taken: keep random id
    layer->setId(id);
}

void MapSession::close() {
    if (closed_ || !project_) return;
    closed_ = true;
    // Contract order: unset tools, detach canvases, drop layers, then the
    // project. Widgets themselves belong to their Qt parents.
    detach_canvas_bridges();
    for (const QPointer<QgsMapCanvas>& canvas : canvases_) {
        if (canvas == nullptr) continue;
        if (QgsMapTool* tool = canvas->mapTool()) canvas->unsetMapTool(tool);
        canvas->setLayers(QList<QgsMapLayer*>());
        canvas->setProject(nullptr);
    }
    canvases_.clear();
    bridges_.clear();
    trees_.clear();
    project_->removeAllMapLayers();
    project_.reset();
}

}  // namespace pwb::qgis
