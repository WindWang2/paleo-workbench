#include "map_stack_service.hpp"

#include <algorithm>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include <QColor>
#include <QCoreApplication>
#include <QObject>
#include <QPointer>
#include <QString>
#include <QWidget>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsjsonutils.h>
#include <qgslayertree.h>
#include <qgslayertreelayer.h>
#include <qgslayertreemapcanvasbridge.h>
#include <qgsmapcanvas.h>
#include <qgsmaptool.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgspointxy.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgsvectorlayer.h>

namespace pwb::qgis_render {

#ifdef PALEO_QGIS_PREFIX_PATH
#undef PALEO_QGIS_PREFIX_PATH
#endif
extern const std::string PALEO_QGIS_PREFIX_PATH;
extern std::mutex g_qgis_lifecycle_mutex;

struct QgisMapStack::Impl {
  bool initialized = false;
  std::unordered_map<std::uintptr_t, std::unique_ptr<QgsLayerTreeMapCanvasBridge>>
      tree_bridges;
  std::unordered_set<std::string> owned_layers;
  std::unordered_map<std::uintptr_t, std::unique_ptr<QgsMapTool>> tools;
  std::unordered_map<std::uintptr_t, ExtentCallback> extent_callbacks;
  std::unordered_map<std::uintptr_t, PointCallback> xy_callbacks;
  std::unordered_map<std::uintptr_t, QPointer<QgsMapCanvas>> canvas_refs;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> extent_connections;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> xy_connections;
};

QgisMapStack::QgisMapStack() : impl_(std::make_unique<Impl>()) {}
QgisMapStack::~QgisMapStack() {
  if (!impl_) return;
  for (auto& kv : impl_->extent_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->extent_connections.clear();
  for (auto& kv : impl_->xy_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->xy_connections.clear();
  for (auto& kv : impl_->tools) {
    auto it = impl_->canvas_refs.find(kv.first);
    bool canvasAlive = (it != impl_->canvas_refs.end() && !it->second.isNull());
    if (!canvasAlive && kv.second) {
      kv.second.release();
    }
  }
}

void QgisMapStack::initialize() {
  if (impl_->initialized) return;
  if (QCoreApplication::instance() == nullptr) {
    throw std::runtime_error("QgisMapStack requires an existing Qt application");
  }
  if (PALEO_QGIS_PREFIX_PATH.empty()) {
    throw std::runtime_error("vendored QGIS prefix is not configured");
  }
  std::lock_guard<std::mutex> lock(g_qgis_lifecycle_mutex);
  QgsApplication::setPrefixPath(
      QString::fromStdString(PALEO_QGIS_PREFIX_PATH), true);
  QgsApplication::init();
  QgsApplication::initQgis();
  impl_->initialized = true;
}

bool QgisMapStack::initialized() const noexcept { return impl_->initialized; }

int QgisMapStack::projectLayerCount() const {
  return static_cast<int>(QgsProject::instance()->count());
}

void QgisMapStack::shutdown() {
  for (auto& kv : impl_->extent_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->extent_connections.clear();
  for (auto& kv : impl_->xy_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->xy_connections.clear();
  for (const auto& id : impl_->owned_layers) {
    QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(id));
    if (layer != nullptr) {
      QgsProject::instance()->removeMapLayer(layer);
    }
  }
  impl_->owned_layers.clear();
  impl_->tree_bridges.clear();
  for (auto& kv : impl_->tools) {
    auto it = impl_->canvas_refs.find(kv.first);
    bool canvasAlive = (it != impl_->canvas_refs.end() && !it->second.isNull());
    if (!canvasAlive && kv.second) {
      kv.second.release();
    }
  }
  impl_->tools.clear();
  impl_->canvas_refs.clear();
  impl_->extent_callbacks.clear();
  impl_->xy_callbacks.clear();
  impl_->initialized = false;
}

QgsMapCanvas* QgisMapStack::canvasOrThrow(std::uintptr_t address) const {
  if (address == 0) throw std::invalid_argument("null canvas address");
  auto it = impl_->canvas_refs.find(address);
  if (it != impl_->canvas_refs.end() && it->second.isNull()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto* canvas = reinterpret_cast<QgsMapCanvas*>(address);
  if (canvas == nullptr) throw std::invalid_argument("null canvas address");
  return canvas;
}

void QgisMapStack::ensureNotStale(std::uintptr_t canvas_addr) {
  auto it = impl_->canvas_refs.find(canvas_addr);
  if (it != impl_->canvas_refs.end() && it->second.isNull()) {
    auto toolIt = impl_->tools.find(canvas_addr);
    if (toolIt != impl_->tools.end() && toolIt->second) {
      toolIt->second.release();
    }
    impl_->tools.erase(canvas_addr);
    auto ecIt = impl_->extent_connections.find(canvas_addr);
    if (ecIt != impl_->extent_connections.end()) {
      QObject::disconnect(ecIt->second);
      impl_->extent_connections.erase(ecIt);
    }
    auto xcIt = impl_->xy_connections.find(canvas_addr);
    if (xcIt != impl_->xy_connections.end()) {
      QObject::disconnect(xcIt->second);
      impl_->xy_connections.erase(xcIt);
    }
    impl_->extent_callbacks.erase(canvas_addr);
    impl_->xy_callbacks.erase(canvas_addr);
    impl_->tree_bridges.erase(canvas_addr);
    throw std::invalid_argument("canvas address no longer valid");
  }
}

std::uintptr_t QgisMapStack::createCanvas() {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  auto* canvas = new QgsMapCanvas();
  canvas->setCanvasColor(Qt::white);
  canvas->enableAntiAliasing(true);
  auto tree_bridge = std::make_unique<QgsLayerTreeMapCanvasBridge>(
      QgsProject::instance()->layerTreeRoot(), canvas);
  tree_bridge->setCanvasLayers();
  std::uintptr_t addr = reinterpret_cast<std::uintptr_t>(canvas);
  impl_->tree_bridges.emplace(addr, std::move(tree_bridge));
  impl_->canvas_refs[addr] = canvas;
  return addr;
}

void QgisMapStack::setCanvasWhiteBackground(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->setCanvasColor(Qt::white);
}

void QgisMapStack::setDestinationCrs(std::uintptr_t canvas, const std::string& crs) {
  canvasOrThrow(canvas)->setDestinationCrs(
      QgsCoordinateReferenceSystem(QString::fromStdString(crs)));
}

void QgisMapStack::setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                                   double xmax, double ymax) {
  canvasOrThrow(canvas)->setExtent(QgsRectangle(xmin, ymin, xmax, ymax));
}

std::vector<double> QgisMapStack::canvasExtent(std::uintptr_t canvas) const {
  const QgsRectangle r = canvasOrThrow(canvas)->extent();
  return {r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()};
}

void QgisMapStack::zoomToFullExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToFullExtent();
}
void QgisMapStack::zoomToPreviousExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToPreviousExtent();
}
void QgisMapStack::zoomToNextExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToNextExtent();
}
void QgisMapStack::refreshCanvas(std::uintptr_t canvas) {
  QgsMapCanvas* c = canvasOrThrow(canvas);
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  c->refresh();
  c->waitWhileRendering();
  QCoreApplication::processEvents();
}

std::vector<double> QgisMapStack::screenToMap(std::uintptr_t canvas, double x, double y) const {
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->toMapCoordinates(
      static_cast<int>(x), static_cast<int>(y));
  return {p.x(), p.y()};
}

std::vector<double> QgisMapStack::mapToScreen(std::uintptr_t canvas, double x, double y) const {
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->transform(
      QgsPointXY(x, y));
  return {p.x(), p.y()};
}

std::string QgisMapStack::addVectorLayerGeoJson(
    const std::string& name, const std::string& geometry_type,
    const std::string& crs_auth_id, const std::string& geojson) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  const QString uri = QStringLiteral("%1?crs=%2")
      .arg(QString::fromStdString(geometry_type), QString::fromStdString(crs_auth_id));
  auto layer = std::make_unique<QgsVectorLayer>(
      uri, QString::fromStdString(name), QStringLiteral("memory"));
  if (!layer->isValid()) throw std::runtime_error("memory layer creation failed: " + name);

  QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
      QString::fromStdString(geojson));
  if (!features.isEmpty()) {
    layer->dataProvider()->addFeatures(features);
    layer->updateExtents();
  }
  const std::string id = layer->id().toStdString();
  QgsProject::instance()->addMapLayer(layer.release());
  impl_->owned_layers.insert(id);
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  return id;
}

bool QgisMapStack::removeLayer(const std::string& layer_id) {
  auto it = impl_->owned_layers.find(layer_id);
  if (it == impl_->owned_layers.end()) return false;
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(
      QString::fromStdString(layer_id));
  if (layer == nullptr) {
    impl_->owned_layers.erase(it);
    return false;
  }
  QgsProject::instance()->removeMapLayer(layer);
  impl_->owned_layers.erase(it);
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  return true;
}

void QgisMapStack::setLayerVisibility(const std::string& layer_id, bool visible) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(layer);
  if (node != nullptr) node->setItemVisibilityChecked(visible);
}

void QgisMapStack::setLayerOpacity(const std::string& layer_id, double opacity) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
}

void QgisMapStack::clearProjectLayers() {
  auto owned_copy = impl_->owned_layers;
  for (const auto& id : owned_copy) {
    QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(id));
    if (layer != nullptr) {
      QgsProject::instance()->removeMapLayer(layer);
    }
    impl_->owned_layers.erase(id);
  }
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
}

void QgisMapStack::setMapTool(std::uintptr_t canvas_addr, const std::string& kind) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  if (kind == "pan") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolPan>(canvas);
  } else if (kind == "zoomIn") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, false);
  } else if (kind == "zoomOut") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, true);
  } else {
    throw std::invalid_argument("unknown map tool kind: " + kind);
  }
  canvas->setMapTool(impl_->tools[canvas_addr].get());
}

void QgisMapStack::setExtentCallback(std::uintptr_t canvas_addr, ExtentCallback callback) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  auto ecIt = impl_->extent_connections.find(canvas_addr);
  if (ecIt != impl_->extent_connections.end()) {
    QObject::disconnect(ecIt->second);
    impl_->extent_connections.erase(ecIt);
  }
  impl_->extent_callbacks[canvas_addr] = std::move(callback);
  QMetaObject::Connection conn = QObject::connect(canvas, &QgsMapCanvas::extentsChanged, canvas, [this, canvas_addr]() {
    auto cbIt = impl_->extent_callbacks.find(canvas_addr);
    if (cbIt == impl_->extent_callbacks.end() || !cbIt->second) return;
    QgsMapCanvas* c = canvasOrThrow(canvas_addr);
    const QgsRectangle r = c->extent();
    cbIt->second(r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum());
  });
  impl_->extent_connections[canvas_addr] = conn;
}

void QgisMapStack::setXyCallback(std::uintptr_t canvas_addr, PointCallback callback) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  auto xcIt = impl_->xy_connections.find(canvas_addr);
  if (xcIt != impl_->xy_connections.end()) {
    QObject::disconnect(xcIt->second);
    impl_->xy_connections.erase(xcIt);
  }
  impl_->xy_callbacks[canvas_addr] = std::move(callback);
  QMetaObject::Connection conn = QObject::connect(canvas, &QgsMapCanvas::xyCoordinates, canvas,
                   [this, canvas_addr](const QgsPointXY& p) {
    auto cbIt = impl_->xy_callbacks.find(canvas_addr);
    if (cbIt == impl_->xy_callbacks.end() || !cbIt->second) return;
    cbIt->second(p.x(), p.y());
  });
  impl_->xy_connections[canvas_addr] = conn;
}

}  // namespace pwb::qgis_render
