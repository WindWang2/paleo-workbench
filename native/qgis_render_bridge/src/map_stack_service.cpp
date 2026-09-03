#include "map_stack_service.hpp"

#include <algorithm>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include <QColor>
#include <QCoreApplication>
#include <QDomDocument>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
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
#include <qgslayertreemodel.h>
#include <qgslayertreeregistrybridge.h>
#include <qgslayertreeview.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsmaptool.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgspointxy.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgsvectorlayer.h>

#include "qgis_render_bridge.hpp"
#include "style_codec.hpp"

namespace pwb::qgis_render {

#ifdef PALEO_QGIS_PREFIX_PATH
#undef PALEO_QGIS_PREFIX_PATH
#endif
extern const std::string PALEO_QGIS_PREFIX_PATH;
extern std::mutex g_qgis_lifecycle_mutex;

namespace {

std::string qjsonValueToString(const QJsonValue& v) {
    if (v.isString()) return v.toString().toStdString();
    if (v.isDouble()) {
        double d = v.toDouble();
        if (std::floor(d) == d) return std::to_string(static_cast<long long>(d));
        return QString::number(d, 'g', 12).toStdString();
    }
    if (v.isBool()) return v.toBool() ? "true" : "false";
    return {};
}

static bool legacy_style_empty(const std::string& s) {
    if (s.empty()) return true;
    QByteArray bytes = QByteArray::fromStdString(s).trimmed();
    if (bytes.isEmpty()) return true;
    if (bytes == "null" || bytes == "{}" || bytes == "[]") return true;
    QJsonParseError err;
    QJsonDocument doc = QJsonDocument::fromJson(bytes, &err);
    if (err.error != QJsonParseError::NoError) return true;
    if (doc.isNull()) return true;
    if (doc.isObject() && doc.object().isEmpty()) return true;
    if (doc.isArray() && doc.array().isEmpty()) return true;
    return false;
}

VectorLayerSpec buildSpecFromLegacyJson(const std::string& rendererXml,
                                        const std::string& labelingXml,
                                        const std::string& legacyJson,
                                        const std::string& layerId) {
    VectorLayerSpec spec;
    spec.id = layerId;
    spec.renderer_xml = rendererXml;
    spec.labeling_xml = labelingXml;
    if (legacyJson.empty()) return spec;
    QJsonDocument doc = QJsonDocument::fromJson(QByteArray::fromStdString(legacyJson));
    if (!doc.isObject()) return spec;
    QJsonObject obj = doc.object();
    if (obj.isEmpty()) return spec;
    if (obj.contains("fill") && obj["fill"].isString())
        spec.fill = obj["fill"].toString().toStdString();
    if (obj.contains("stroke") && obj["stroke"].isString())
        spec.stroke = obj["stroke"].toString().toStdString();
    if (obj.contains("stroke_width")) {
        QJsonValue v = obj["stroke_width"];
        if (v.isDouble()) spec.stroke_width = v.toDouble();
        else if (v.isString()) spec.stroke_width = v.toString().toDouble();
    }
    if (obj.contains("marker_size")) {
        QJsonValue v = obj["marker_size"];
        if (v.isDouble()) spec.marker_size = v.toDouble();
        else if (v.isString()) spec.marker_size = v.toString().toDouble();
    }
    if (obj.contains("marker") && obj["marker"].isString())
        spec.marker = obj["marker"].toString().toStdString();
    if (obj.contains("line_pattern") && obj["line_pattern"].isString())
        spec.line_pattern = obj["line_pattern"].toString().toStdString();
    if (obj.contains("renderer") && obj["renderer"].isString())
        spec.renderer_kind = obj["renderer"].toString().toStdString();
    if (obj.contains("field") && obj["field"].isString())
        spec.classification_field = obj["field"].toString().toStdString();
    if (obj.contains("renderer_xml") && obj["renderer_xml"].isString() && spec.renderer_xml.empty())
        spec.renderer_xml = obj["renderer_xml"].toString().toStdString();
    if (obj.contains("labeling_xml") && obj["labeling_xml"].isString() && spec.labeling_xml.empty())
        spec.labeling_xml = obj["labeling_xml"].toString().toStdString();
    if (obj.contains("categories")) {
        QJsonValue cv = obj["categories"];
        if (cv.isObject()) {
            QJsonObject catObj = cv.toObject();
            for (auto it = catObj.begin(); it != catObj.end(); ++it) {
                std::string value = it.key().toStdString();
                std::string color = it.value().toString().toStdString();
                spec.categories.push_back({value, color, value});
            }
        } else if (cv.isArray()) {
            QJsonArray arr = cv.toArray();
            for (const QJsonValue& entryVal : arr) {
                if (entryVal.isArray()) {
                    QJsonArray entry = entryVal.toArray();
                    if (entry.size() >= 2) {
                        std::string v = qjsonValueToString(entry[0]);
                        std::string c = qjsonValueToString(entry[1]);
                        std::string lbl = entry.size() > 2 ? qjsonValueToString(entry[2]) : v;
                        spec.categories.push_back({v, c, lbl});
                    }
                } else if (entryVal.isObject()) {
                    QJsonObject entry = entryVal.toObject();
                    std::string v = entry.contains("value") ? qjsonValueToString(entry["value"]) : "";
                    std::string c = entry.contains("color") ? qjsonValueToString(entry["color"])
                                  : entry.contains("fill") ? qjsonValueToString(entry["fill"]) : "";
                    std::string lbl = entry.contains("label") ? qjsonValueToString(entry["label"]) : v;
                    if (!v.empty() || !c.empty()) spec.categories.push_back({v, c, lbl});
                }
            }
        }
    }
    if (obj.contains("ranges")) {
        QJsonValue rv = obj["ranges"];
        if (rv.isArray()) {
            QJsonArray arr = rv.toArray();
            for (const QJsonValue& entryVal : arr) {
                if (entryVal.isArray()) {
                    QJsonArray entry = entryVal.toArray();
                    if (entry.size() >= 3) {
                        double lo = entry[0].toDouble();
                        double hi = entry[1].toDouble();
                        std::string color = qjsonValueToString(entry[2]);
                        std::string label = entry.size() > 3 ? qjsonValueToString(entry[3]) : "";
                        spec.ranges.push_back({lo, hi, color, label});
                    }
                } else if (entryVal.isObject()) {
                    QJsonObject entry = entryVal.toObject();
                    double lo = 0, hi = 0;
                    if (entry.contains("lower")) lo = entry["lower"].toDouble();
                    else if (entry.contains("lo")) lo = entry["lo"].toDouble();
                    else if (entry.contains("min")) lo = entry["min"].toDouble();
                    if (entry.contains("upper")) hi = entry["upper"].toDouble();
                    else if (entry.contains("hi")) hi = entry["hi"].toDouble();
                    else if (entry.contains("max")) hi = entry["max"].toDouble();
                    std::string color;
                    if (entry.contains("color")) color = qjsonValueToString(entry["color"]);
                    else if (entry.contains("fill")) color = qjsonValueToString(entry["fill"]);
                    std::string label = entry.contains("label") ? qjsonValueToString(entry["label"]) : "";
                    spec.ranges.push_back({lo, hi, color, label});
                }
            }
        }
    }
    if (obj.contains("rules") && obj["rules"].isArray()) {
        QJsonArray arr = obj["rules"].toArray();
        for (const QJsonValue& entryVal : arr) {
            if (!entryVal.isObject()) continue;
            QJsonObject entry = entryVal.toObject();
            RuleSpec rule;
            if (entry.contains("name")) rule.name = qjsonValueToString(entry["name"]);
            if (entry.contains("expression")) rule.expression = qjsonValueToString(entry["expression"]);
            if (entry.contains("label")) rule.label = qjsonValueToString(entry["label"]);
            else if (entry.contains("name") && rule.label.empty()) rule.label = rule.name;
            if (entry.contains("fill")) rule.fill = qjsonValueToString(entry["fill"]);
            if (entry.contains("stroke")) rule.stroke = qjsonValueToString(entry["stroke"]);
            if (entry.contains("stroke_width")) {
                QJsonValue v = entry["stroke_width"];
                if (v.isDouble()) rule.stroke_width = v.toDouble();
                else if (v.isString()) rule.stroke_width = v.toString().toDouble();
            }
            if (entry.contains("marker_size")) {
                QJsonValue v = entry["marker_size"];
                if (v.isDouble()) rule.marker_size = v.toDouble();
                else if (v.isString()) rule.marker_size = v.toString().toDouble();
            }
            spec.rules.push_back(std::move(rule));
        }
    }
    if (obj.contains("labels") && obj["labels"].isObject()) {
        QJsonObject labels = obj["labels"].toObject();
        bool visible = true;
        if (labels.contains("visible")) {
            QJsonValue vv = labels["visible"];
            if (vv.isBool()) visible = vv.toBool();
            else if (vv.isString()) visible = vv.toString().toLower() != "false" && vv.toString() != "0";
        }
        std::string field;
        if (labels.contains("field") && labels["field"].isString())
            field = labels["field"].toString().toStdString();
        spec.labels_enabled = visible && !field.empty();
        if (labels.contains("field") && labels["field"].isString())
            spec.label_field = field;
        if (labels.contains("font_family") && labels["font_family"].isString())
            spec.label_font_family = labels["font_family"].toString().toStdString();
        if (labels.contains("size")) {
            QJsonValue v = labels["size"];
            if (v.isDouble()) spec.label_size = v.toDouble();
            else if (v.isString()) spec.label_size = v.toString().toDouble();
        }
        if (labels.contains("bold")) {
            QJsonValue v = labels["bold"];
            if (v.isBool()) spec.label_bold = v.toBool();
            else if (v.isString()) spec.label_bold = v.toString().toLower() == "true" || v.toString() == "1";
        }
        if (labels.contains("color") && labels["color"].isString())
            spec.label_color = labels["color"].toString().toStdString();
        if (labels.contains("buffer")) {
            QJsonValue v = labels["buffer"];
            if (v.isDouble()) spec.label_buffer_size = v.toDouble();
            else if (v.isString()) spec.label_buffer_size = v.toString().toDouble();
        } else if (labels.contains("halo_width")) {
            QJsonValue v = labels["halo_width"];
            if (v.isDouble()) spec.label_buffer_size = v.toDouble();
            else if (v.isString()) spec.label_buffer_size = v.toString().toDouble();
        }
        if (labels.contains("buffer_color") && labels["buffer_color"].isString())
            spec.label_buffer_color = labels["buffer_color"].toString().toStdString();
        else if (labels.contains("halo_color") && labels["halo_color"].isString())
            spec.label_buffer_color = labels["halo_color"].toString().toStdString();
        if (labels.contains("rotation_field") && labels["rotation_field"].isString())
            spec.label_rotation_field = labels["rotation_field"].toString().toStdString();
        if (labels.contains("size_field") && labels["size_field"].isString())
            spec.label_size_field = labels["size_field"].toString().toStdString();
        if (labels.contains("color_field") && labels["color_field"].isString())
            spec.label_color_field = labels["color_field"].toString().toStdString();
    }
    return spec;
}

void applyStyleToLayer(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    validate_style_payloads(spec);
    apply_renderer_style(layer, spec);
    apply_label_style(layer, spec);
}

static std::string makeStyleSig(const std::string& renderer_xml,
                                const std::string& labeling_xml,
                                const std::string& legacy_json) {
    std::string sig;
    sig.reserve(renderer_xml.size() + labeling_xml.size() + legacy_json.size() + 2);
    sig.append(renderer_xml);
    sig.push_back('\x1e');
    sig.append(labeling_xml);
    sig.push_back('\x1e');
    sig.append(legacy_json);
    return sig;
}

}  // namespace

static QgsVectorLayer* findMirrorByDocId(QgsProject* project, const std::string& doc_id) {
    if (!project || doc_id.empty()) return nullptr;
    const QString key = QStringLiteral("pwb/doc_id");
    const QString target = QString::fromStdString(doc_id);
    for (auto* layer : project->mapLayers().values()) {
        if (layer->customProperty(key).toString() == target)
            return qobject_cast<QgsVectorLayer*>(layer);
    }
    return nullptr;
}

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
  // I1: retain rejection after erasing the QPointer tombstone — otherwise the
  // next call would miss in canvas_refs and canvasOrThrow would reinterpret a
  // freed pointer (UAF). The set is bounded by the number of distinct dead
  // addresses not yet reused (cleared on createCanvas reuse and shutdown).
  std::unordered_set<std::uintptr_t> dead_canvas_addrs;
  std::unordered_map<std::uintptr_t, QPointer<QgsLayerTreeView>> tree_views;
  std::unordered_map<std::uintptr_t, std::function<void(const std::string&)>> tree_sel_callbacks;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> tree_sel_connections;
  std::unordered_map<std::string, std::string> mirror_by_doc;
  std::unordered_map<std::string, std::string> mirror_style_sig;
  int suppress_tree_callbacks = 0;

  void eraseMirrorByQgisId(const std::string& qgis_id) {
    for (auto it = mirror_by_doc.begin(); it != mirror_by_doc.end(); ) {
      if (it->second == qgis_id) {
        auto sit = mirror_style_sig.find(it->first);
        if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
        it = mirror_by_doc.erase(it);
      } else {
        ++it;
      }
    }
  }

  void eraseMirrorByDocId(const std::string& doc_id) {
    auto dit = mirror_by_doc.find(doc_id);
    if (dit != mirror_by_doc.end()) mirror_by_doc.erase(dit);
    auto sit = mirror_style_sig.find(doc_id);
    if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
  }

  void eraseMirrorByDocIdIfQgisMatches(const std::string& doc_id,
                                       const std::string& qgis_id) {
    auto dit = mirror_by_doc.find(doc_id);
    if (dit != mirror_by_doc.end() && dit->second == qgis_id) {
      mirror_by_doc.erase(dit);
      auto sit = mirror_style_sig.find(doc_id);
      if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
    }
  }
};

namespace {
struct SuppressGuard {
    int* counter = nullptr;
    explicit SuppressGuard(int* c) : counter(c) { if (counter) ++(*counter); }
    ~SuppressGuard() { if (counter) --(*counter); }
    SuppressGuard(const SuppressGuard&) = delete;
    SuppressGuard& operator=(const SuppressGuard&) = delete;
};
}

void QgisMapStack::eraseMirrorByQgisId(const std::string& qgis_id) {
  if (impl_) impl_->eraseMirrorByQgisId(qgis_id);
}

void QgisMapStack::eraseMirrorByDocId(const std::string& doc_id) {
  if (impl_) impl_->eraseMirrorByDocId(doc_id);
}

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
  for (auto& kv : impl_->tree_sel_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->tree_sel_connections.clear();
  impl_->tree_sel_callbacks.clear();
  impl_->tree_views.clear();
  for (auto& kv : impl_->tools) {
    auto it = impl_->canvas_refs.find(kv.first);
    bool canvasAlive = (it != impl_->canvas_refs.end() && !it->second.isNull());
    if (canvasAlive && kv.second) {
      QgsMapCanvas* c = it->second;
      if (c && c->mapTool() == kv.second.get()) {
        c->unsetMapTool(kv.second.get());
      }
    }
    if (kv.second) kv.second.release();
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
  for (auto& kv : impl_->tree_sel_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->tree_sel_connections.clear();
  impl_->tree_sel_callbacks.clear();
  impl_->tree_views.clear();
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    for (const auto& id : impl_->owned_layers) {
      QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(id));
      if (layer != nullptr) {
        QgsProject::instance()->removeMapLayer(layer);
      }
    }
  }
  impl_->owned_layers.clear();
  impl_->mirror_by_doc.clear();
  impl_->mirror_style_sig.clear();
  impl_->suppress_tree_callbacks = 0;
  impl_->tree_bridges.clear();
  for (auto& kv : impl_->tools) {
    auto it = impl_->canvas_refs.find(kv.first);
    bool canvasAlive = (it != impl_->canvas_refs.end() && !it->second.isNull());
    if (canvasAlive && kv.second) {
      QgsMapCanvas* c = it->second;
      if (c && c->mapTool() == kv.second.get()) {
        c->unsetMapTool(kv.second.get());
      }
    }
    if (kv.second) kv.second.release();
  }
  impl_->tools.clear();
  impl_->canvas_refs.clear();
  impl_->dead_canvas_addrs.clear();
  impl_->extent_callbacks.clear();
  impl_->xy_callbacks.clear();
  impl_->initialized = false;
}

QgsMapCanvas* QgisMapStack::canvasOrThrow(std::uintptr_t address) const {
  if (address == 0) throw std::invalid_argument("null canvas address");
  if (impl_->dead_canvas_addrs.find(address) != impl_->dead_canvas_addrs.end()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto it = impl_->canvas_refs.find(address);
  if (it != impl_->canvas_refs.end() && it->second.isNull()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto* canvas = reinterpret_cast<QgsMapCanvas*>(address);
  if (canvas == nullptr) throw std::invalid_argument("null canvas address");
  return canvas;
}

void QgisMapStack::ensureNotStale(std::uintptr_t canvas_addr) {
  if (impl_->dead_canvas_addrs.find(canvas_addr) != impl_->dead_canvas_addrs.end()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
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
    // I1: erase the QPointer tombstone to prevent unbounded growth; retain
    // rejection via dead_canvas_addrs so a subsequent call with the same
    // freed address cannot be reinterpreted (UAF). The alternative of simply
    // erasing without dead-set would make the next canvasOrThrow miss and
    // reinterpret a dangling pointer.
    impl_->canvas_refs.erase(it);
    impl_->dead_canvas_addrs.insert(canvas_addr);
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
  // I1: address reuse — a freshly allocated canvas may reuse a previously
  // dead address; clear the dead-set so the new live entry is not rejected.
  impl_->dead_canvas_addrs.erase(addr);
  return addr;
}

void QgisMapStack::destroyCanvas(std::uintptr_t canvas_addr) {
  auto it = impl_->canvas_refs.find(canvas_addr);
  if (it == impl_->canvas_refs.end()) return;
  // Disconnect callbacks
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
  // Remove tool (Qt parent owns it — always release, never delete via unique_ptr)
  auto toolIt = impl_->tools.find(canvas_addr);
  if (toolIt != impl_->tools.end() && toolIt->second) {
    bool canvasAlive = !it->second.isNull();
    if (canvasAlive) {
      QgsMapCanvas* c = it->second;
      if (c && c->mapTool() == toolIt->second.get()) {
        c->unsetMapTool(toolIt->second.get());
      }
    }
    toolIt->second.release();
    impl_->tools.erase(toolIt);
  } else if (toolIt != impl_->tools.end()) {
    impl_->tools.erase(toolIt);
  }
  // Remove bridge; canvas lifetime is owned by Qt parent hierarchy,
  // so we do not delete the QWidget here (avoids double-free with
  // QgisCanvasHost layout). The QPointer will become null when Qt
  // deletes the widget.
  impl_->tree_bridges.erase(canvas_addr);
  impl_->canvas_refs.erase(it);
  impl_->dead_canvas_addrs.erase(canvas_addr);
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
    const std::string& crs_auth_id, const std::string& geojson,
    const std::string& renderer_xml, const std::string& labeling_xml,
    const std::string& legacy_style_json) {
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
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
    VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, name);
    spec.id = layer->id().toStdString();
    if (spec.id.empty()) spec.id = name;
    applyStyleToLayer(*layer, spec);
  }
  const std::string id = layer->id().toStdString();
  QgsProject::instance()->addMapLayer(layer.release());
  impl_->owned_layers.insert(id);
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  return id;
}

void QgisMapStack::setLayerStyle(const std::string& layer_id,
                                 const std::string& renderer_xml,
                                 const std::string& labeling_xml,
                                 const std::string& legacy_style_json) {
  QgsMapLayer* base = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (base == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  auto* layer = dynamic_cast<QgsVectorLayer*>(base);
  if (layer == nullptr) throw std::invalid_argument("layer is not a vector layer: " + layer_id);
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (!hasStyle || (renderer_xml.empty() && labeling_xml.empty() && legacyIsEmpty)) {
    return;
  }
  VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, layer_id);
  spec.id = layer_id;
  applyStyleToLayer(*layer, spec);
  layer->triggerRepaint();
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
}

bool QgisMapStack::removeLayer(const std::string& layer_id) {
  auto it = impl_->owned_layers.find(layer_id);
  if (it == impl_->owned_layers.end()) return false;
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(
      QString::fromStdString(layer_id));
  if (layer == nullptr) {
    impl_->owned_layers.erase(it);
    eraseMirrorByQgisId(layer_id);
    return false;
  }
  QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
  std::string doc_id = docVar.isValid() ? docVar.toString().toStdString() : "";
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    QgsProject::instance()->removeMapLayer(layer);
  }
  impl_->owned_layers.erase(it);
  if (!doc_id.empty()) {
    impl_->eraseMirrorByDocIdIfQgisMatches(doc_id, layer_id);
  } else {
    eraseMirrorByQgisId(layer_id);
  }
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  return true;
}

void QgisMapStack::setLayerVisibility(const std::string& layer_id, bool visible) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(layer);
  if (node != nullptr) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    node->setItemVisibilityChecked(visible);
  }
}

void QgisMapStack::setLayerOpacity(const std::string& layer_id, double opacity) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
}

void QgisMapStack::clearProjectLayers() {
  std::vector<std::string> empty;
  removeMirrorLayersExcept(empty);
}

std::string QgisMapStack::upsertMirrorLayer(const std::string& doc_id,
                                            const std::string& name,
                                            const std::string& geometry_type,
                                            const std::string& crs_auth_id,
                                            const std::string& geojson_feature_collection,
                                            const std::string& renderer_xml,
                                            const std::string& labeling_xml,
                                            const std::string& legacy_style_json,
                                            bool visible,
                                            double opacity) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  if (doc_id.empty()) throw std::invalid_argument("doc_id must not be empty");
  const QByteArray geoBytes = QByteArray::fromStdString(geojson_feature_collection).trimmed();
  if (geoBytes.isEmpty()) throw std::invalid_argument("geojson must not be empty for doc_id: " + doc_id);
  QgsProject* project = QgsProject::instance();
  QgsVectorLayer* existing = nullptr;
  std::string existing_id;
  auto mapIt = impl_->mirror_by_doc.find(doc_id);
  if (mapIt != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = project->mapLayer(QString::fromStdString(mapIt->second));
    if (base) {
      existing = qobject_cast<QgsVectorLayer*>(base);
      if (existing) {
        existing_id = mapIt->second;
      } else {
        impl_->eraseMirrorByDocId(doc_id);
      }
    } else {
      impl_->eraseMirrorByDocId(doc_id);
    }
  }
  if (!existing) {
    existing = findMirrorByDocId(project, doc_id);
    if (existing) {
      existing_id = existing->id().toStdString();
      impl_->mirror_by_doc[doc_id] = existing_id;
      impl_->owned_layers.insert(existing_id);
    }
  }
  if (existing) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
        QString::fromStdString(geojson_feature_collection));
    if (existing->dataProvider()) {
      if (!existing->dataProvider()->truncate()) {
        throw std::runtime_error("mirror truncate failed for doc_id: " + doc_id);
      }
    }
    if (!features.isEmpty()) {
      if (!existing->dataProvider() || !existing->dataProvider()->addFeatures(features)) {
        throw std::runtime_error("mirror addFeatures failed for doc_id: " + doc_id);
      }
    }
    existing->updateExtents();
    std::string new_sig = makeStyleSig(renderer_xml, labeling_xml, legacy_style_json);
    auto sigIt = impl_->mirror_style_sig.find(doc_id);
    bool sig_changed = (sigIt == impl_->mirror_style_sig.end() || sigIt->second != new_sig);
    if (sig_changed) {
      bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
      const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
      if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
        VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, existing_id);
        spec.id = existing_id;
        if (spec.id.empty()) spec.id = doc_id;
        applyStyleToLayer(*existing, spec);
      }
      impl_->mirror_style_sig[doc_id] = new_sig;
      // sig 双存：Impl::mirror_style_sig 是快速比对主源；customProperty
      // pwb/style_sig 供跨边界检视/调试，两者由本函数统一写入保持一致。
      existing->setCustomProperty(QStringLiteral("pwb/style_sig"), QString::fromStdString(new_sig));
    }
    existing->setName(QString::fromStdString(name));
    existing->setOpacity(std::clamp(opacity, 0.0, 1.0));
    QgsLayerTreeLayer* node = project->layerTreeRoot()->findLayer(existing);
    if (node) node->setItemVisibilityChecked(visible);
    impl_->owned_layers.insert(existing_id);
    for (auto& kv : impl_->tree_bridges) {
      if (kv.second) kv.second->setCanvasLayers();
    }
    return existing_id;
  }
  const QString uri = QStringLiteral("%1?crs=%2")
      .arg(QString::fromStdString(geometry_type), QString::fromStdString(crs_auth_id));
  auto layer = std::make_unique<QgsVectorLayer>(
      uri, QString::fromStdString(name), QStringLiteral("memory"));
  if (!layer->isValid()) throw std::runtime_error("memory layer creation failed: " + name);
  QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
      QString::fromStdString(geojson_feature_collection));
  if (!features.isEmpty()) {
    if (!layer->dataProvider()->addFeatures(features)) {
      throw std::runtime_error("addFeatures failed for new mirror layer: " + name);
    }
    layer->updateExtents();
  }
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
    VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, name);
    spec.id = layer->id().toStdString();
    if (spec.id.empty()) spec.id = name;
    applyStyleToLayer(*layer, spec);
  }
  std::string new_sig = makeStyleSig(renderer_xml, labeling_xml, legacy_style_json);
  layer->setCustomProperty(QStringLiteral("pwb/doc_id"), QString::fromStdString(doc_id));
  layer->setCustomProperty(QStringLiteral("pwb/style_sig"), QString::fromStdString(new_sig));
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
  const std::string id = layer->id().toStdString();
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    QgsProject::instance()->addMapLayer(layer.release());
    QgsMapLayer* added = QgsProject::instance()->mapLayer(QString::fromStdString(id));
    if (added) {
      QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(added);
      if (node) node->setItemVisibilityChecked(visible);
    }
  }
  impl_->owned_layers.insert(id);
  impl_->mirror_by_doc[doc_id] = id;
  impl_->mirror_style_sig[doc_id] = new_sig;
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
  return id;
}

void QgisMapStack::removeMirrorLayersExcept(const std::vector<std::string>& doc_ids) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  std::unordered_set<std::string> keep(doc_ids.begin(), doc_ids.end());
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  auto owned_copy = impl_->owned_layers;
  for (const auto& qgis_id : owned_copy) {
    QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(qgis_id));
    if (layer == nullptr) {
      impl_->owned_layers.erase(qgis_id);
      impl_->eraseMirrorByQgisId(qgis_id);
      continue;
    }
    QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
    std::string doc_id = docVar.isValid() ? docVar.toString().toStdString() : "";
    bool hasDoc = !doc_id.empty();
    bool keepIt = hasDoc && keep.find(doc_id) != keep.end();
    if (hasDoc) {
      if (!keepIt) {
        QgsProject::instance()->removeMapLayer(layer);
        impl_->owned_layers.erase(qgis_id);
        impl_->eraseMirrorByDocIdIfQgisMatches(doc_id, qgis_id);
      }
    } else {
      QgsProject::instance()->removeMapLayer(layer);
      impl_->owned_layers.erase(qgis_id);
      impl_->eraseMirrorByQgisId(qgis_id);
    }
  }
  std::vector<std::string> stale_docs;
  for (const auto& kv : impl_->mirror_by_doc) {
    if (impl_->owned_layers.find(kv.second) == impl_->owned_layers.end() &&
        !QgsProject::instance()->mapLayer(QString::fromStdString(kv.second))) {
      stale_docs.push_back(kv.first);
    }
  }
  for (const auto& d : stale_docs) impl_->eraseMirrorByDocId(d);
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
}

void QgisMapStack::setMirrorLayerOrder(const std::vector<std::string>& doc_ids_top_first) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  QgsLayerTreeGroup* root = QgsProject::instance()->layerTreeRoot();
  // 排序操作必须在 root 信号屏蔽 + registryBridge 禁用的保护区间内完成；
  // setCanvasLayers 依赖树信号驱动画布桥，必须等两个 RAII guard 析构后再调用。
  {
    auto* registryBridge = QgsProject::instance()->layerTreeRegistryBridge();
    bool bridgeWasEnabled = false;
    if (registryBridge && registryBridge->isEnabled()) {
      bridgeWasEnabled = true;
      registryBridge->setEnabled(false);
    }
    struct BridgeReenable {
      QgsLayerTreeRegistryBridge* bridge;
      bool wasEnabled;
      ~BridgeReenable() { if (bridge && wasEnabled) bridge->setEnabled(true); }
    } reenable{registryBridge, bridgeWasEnabled};
    const bool wasBlocked = root->blockSignals(true);
    struct RootUnblock {
      QgsLayerTreeGroup* r;
      bool wasBlocked;
      ~RootUnblock() { r->blockSignals(wasBlocked); }
    } unblock{root, wasBlocked};
    for (auto it = doc_ids_top_first.rbegin(); it != doc_ids_top_first.rend(); ++it) {
      const std::string& doc_id = *it;
      auto mapIt = impl_->mirror_by_doc.find(doc_id);
      if (mapIt == impl_->mirror_by_doc.end()) continue;
      QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(mapIt->second));
      if (!layer) continue;
      QgsLayerTreeLayer* node = root->findLayer(layer);
      if (!node) continue;
      QgsLayerTreeNode* parent = node->parent();
      if (!parent) continue;
      parent->takeChild(node);
      root->insertChildNode(0, node);
    }
  }
  for (auto& kv : impl_->tree_bridges) {
    if (kv.second) kv.second->setCanvasLayers();
  }
}

void QgisMapStack::setMirrorLayerVisibility(const std::string& doc_id, bool visible) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  auto it = impl_->mirror_by_doc.find(doc_id);
  QgsVectorLayer* layer = nullptr;
  if (it != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = QgsProject::instance()->mapLayer(QString::fromStdString(it->second));
    layer = qobject_cast<QgsVectorLayer*>(base);
    if (!layer) {
      layer = findMirrorByDocId(QgsProject::instance(), doc_id);
    }
  } else {
    layer = findMirrorByDocId(QgsProject::instance(), doc_id);
    if (layer) {
      impl_->mirror_by_doc[doc_id] = layer->id().toStdString();
      impl_->owned_layers.insert(layer->id().toStdString());
    }
  }
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(layer);
  if (!node) throw std::invalid_argument("layer node not found for doc_id: " + doc_id);
  node->setItemVisibilityChecked(visible);
}

std::vector<std::string> QgisMapStack::mirrorOrderTopFirst() const {
  std::vector<std::string> result;
  QgsLayerTreeGroup* root = QgsProject::instance()->layerTreeRoot();
  for (QgsLayerTreeNode* child : root->children()) {
    QgsLayerTreeLayer* layerNode = qobject_cast<QgsLayerTreeLayer*>(child);
    if (!layerNode) continue;
    QgsMapLayer* layer = layerNode->layer();
    if (!layer) continue;
    QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
    if (!docVar.isValid() || docVar.toString().isEmpty()) continue;
    if (impl_->owned_layers.find(layer->id().toStdString()) == impl_->owned_layers.end()) continue;
    result.push_back(docVar.toString().toStdString());
  }
  return result;
}

bool QgisMapStack::mirrorLayerVisibility(const std::string& doc_id) const {
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = QgsProject::instance()->mapLayer(QString::fromStdString(it->second));
    layer = qobject_cast<QgsVectorLayer*>(base);
  }
  if (!layer) layer = findMirrorByDocId(QgsProject::instance(), doc_id);
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(layer);
  if (!node) throw std::invalid_argument("layer node not found for doc_id: " + doc_id);
  return node->itemVisibilityChecked();
}

bool QgisMapStack::treeEchoSuppressed() const noexcept {
  return impl_ && impl_->suppress_tree_callbacks > 0;
}

void QgisMapStack::setMapTool(std::uintptr_t canvas_addr, const std::string& kind) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  // Release previous tool (Qt parent owns it) before overwriting — avoid double-delete
  auto existing = impl_->tools.find(canvas_addr);
  if (existing != impl_->tools.end() && existing->second) {
    if (canvas->mapTool() == existing->second.get()) {
      canvas->unsetMapTool(existing->second.get());
    }
    existing->second.release();
    impl_->tools.erase(existing);
  } else if (existing != impl_->tools.end()) {
    impl_->tools.erase(existing);
  }
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
    auto refIt = impl_->canvas_refs.find(canvas_addr);
    if (refIt == impl_->canvas_refs.end() || refIt->second.isNull()) return;
    auto cbIt = impl_->extent_callbacks.find(canvas_addr);
    if (cbIt == impl_->extent_callbacks.end() || !cbIt->second) return;
    QgsMapCanvas* c = refIt->second;
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
    auto refIt = impl_->canvas_refs.find(canvas_addr);
    if (refIt == impl_->canvas_refs.end() || refIt->second.isNull()) return;
    auto cbIt = impl_->xy_callbacks.find(canvas_addr);
    if (cbIt == impl_->xy_callbacks.end() || !cbIt->second) return;
    cbIt->second(p.x(), p.y());
  });
  impl_->xy_connections[canvas_addr] = conn;
}

std::uintptr_t QgisMapStack::createLayerTreeView(std::uintptr_t canvas_addr) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  (void)canvas;
  QgsLayerTree* root = QgsProject::instance()->layerTreeRoot();
  auto* model = new QgsLayerTreeModel(root);
  auto* view = new QgsLayerTreeView();
  model->setParent(view);
  model->setFlag(QgsLayerTreeModel::ShowLegend);
  model->setFlag(QgsLayerTreeModel::AllowNodeReorder);
  model->setFlag(QgsLayerTreeModel::AllowNodeRename);
  model->setFlag(QgsLayerTreeModel::AllowNodeChangeVisibility);
  view->setModel(model);
  const auto addr = reinterpret_cast<std::uintptr_t>(view);
  impl_->tree_views[addr] = view;
  return addr;
}

QgsLayerTreeView* QgisMapStack::treeViewOrThrow(std::uintptr_t address) const {
  const auto it = impl_->tree_views.find(address);
  if (it == impl_->tree_views.end() || it->second.isNull()) {
    throw std::invalid_argument("layer tree view address no longer valid");
  }
  return it->second.data();
}

void QgisMapStack::setTreeSelectionCallback(
    std::uintptr_t tree_addr, std::function<void(const std::string&)> callback) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  impl_->tree_sel_callbacks[tree_addr] = std::move(callback);
  auto connIt = impl_->tree_sel_connections.find(tree_addr);
  if (connIt != impl_->tree_sel_connections.end()) {
    QObject::disconnect(connIt->second);
    impl_->tree_sel_connections.erase(connIt);
  }
  impl_->tree_sel_connections[tree_addr] = QObject::connect(
      view, &QgsLayerTreeView::currentLayerChanged, view,
      [this, tree_addr](QgsMapLayer* layer) {
        const auto it = impl_->tree_sel_callbacks.find(tree_addr);
        if (it == impl_->tree_sel_callbacks.end() || !it->second) return;
        auto viewIt = impl_->tree_views.find(tree_addr);
        if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
        std::string id;
        if (layer != nullptr) {
          const QVariant doc = layer->customProperty(QStringLiteral("pwb/doc_id"));
          id = (doc.isValid() && !doc.toString().isEmpty())
                   ? doc.toString().toStdString()
                   : layer->id().toStdString();
        }
        it->second(id);
      });
}

int QgisMapStack::treeViewRowCount(std::uintptr_t tree) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  return model->rowCount();
}

std::string QgisMapStack::treeViewLayerName(std::uintptr_t tree, int row) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  QVariant d = model->data(idx, Qt::DisplayRole);
  return d.toString().toStdString();
}

void QgisMapStack::treeViewSetCurrentRow(std::uintptr_t tree, int row) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  view->setCurrentIndex(idx);
}

}  // namespace pwb::qgis_render
