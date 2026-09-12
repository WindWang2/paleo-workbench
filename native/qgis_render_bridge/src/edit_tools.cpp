#include "edit_tools.hpp"

#include <cmath>
#include <limits>
#include <set>

#include <QKeyEvent>

#include <qgsabstractgeometry.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsexception.h>  // QgsCsException lives here in QGIS 4.2 (no qgscsexception.h)
#include <qgsdistancearea.h>
#include <qgsmapcanvas.h>
#include <qgsmapmouseevent.h>
#include <qgsmaptoolselectionhandler.h>
#include <qgspointlocator.h>
#include <qgsproject.h>
#include <qgsrubberband.h>
#include <qgssnappingutils.h>
#include <qgssnapindicator.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayereditutils.h>  // M1 v2：moveVertex/deleteVertex/insertVertex
#include <qgsvertexmarker.h>
#include <qgswkbtypes.h>

namespace pwb::qgis_render {

PwbEditPickTool::PwbEditPickTool(QgsMapCanvas* canvas, Callback callback,
                                 FeatureIdResolver resolver)
    : QgsMapTool(canvas),
      callback_(std::move(callback)),
      resolver_(std::move(resolver)) {
  // 拖动中 QgsMapCanvas::keyPressEvent 不转发工具而是发 keyPressed 信号
  // （mouseButtonDown 分支），Esc 取消必须走这条路径。
  // context 传 this（终局审查 I1）：连接随工具析构断开，不裸捕悬垂 this。
  QObject::connect(canvas, &QgsMapCanvas::keyPressed, this,
                   [this](QKeyEvent* e) { keyPressEvent(e); });
}

PwbEditPickTool::~PwbEditPickTool() = default;

void PwbEditPickTool::keyPressEvent(QKeyEvent* e) {
  if (e->key() == Qt::Key_Escape && dragging_) {
    cancelDrag();
    e->accept();
    return;
  }
  QgsMapTool::keyPressEvent(e);
}

void PwbEditPickTool::deactivate() {
  cancelDrag();
  QgsMapTool::deactivate();
}

void PwbEditPickTool::cancelDrag() {
  dragging_ = false;
  rubber_.reset();
  current_ = Pick();
}

bool PwbEditPickTool::pickFeature(const QgsPointXY& mapPoint, Pick& out) const {
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  const double tol = kTolerancePx * mup;
  const QgsGeometry probe = QgsGeometry::fromPointXY(mapPoint);
  double best = std::numeric_limits<double>::max();
  bool found = false;
  for (QgsMapLayer* ml : canvas()->mapSettings().layers()) {
    auto* vl = qobject_cast<QgsVectorLayer*>(ml);
    if (vl == nullptr) continue;
    const QString docId = vl->customProperty(QStringLiteral("pwb/doc_id")).toString();
    if (docId.isEmpty()) continue;  // 只拾取文档镜像层
    const QgsRectangle rect(mapPoint.x() - tol, mapPoint.y() - tol,
                            mapPoint.x() + tol, mapPoint.y() + tol);
    QgsFeature f;
    auto it = vl->getFeatures(QgsFeatureRequest(rect));
    while (it.nextFeature(f)) {
      if (!f.hasGeometry()) continue;
      const double d = f.geometry().distance(probe);
      if (d <= tol && d < best) {
        best = d;
        found = true;
        out.layer = vl;
        out.fid = f.id();
        out.geometry = f.geometry();
        out.docId = docId.toStdString();
        if (resolver_) {
          out.featureId = resolver_(vl, f.id());
        } else {
          out.featureId = std::to_string(static_cast<long long>(f.id()));
        }
      }
    }
  }
  return found;
}

bool PwbEditPickTool::nearestVertex(const Pick& pick, const QgsPointXY& mapPoint,
                                    QgsVertexId& out) const {
  const QgsAbstractGeometry* g = pick.geometry.constGet();
  if (g == nullptr) return false;
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  double best = kTolerancePx * mup;
  bool found = false;
  const int n = g->nCoordinates();
  for (int nr = 0; nr < n; ++nr) {
    QgsVertexId id;
    if (!pick.geometry.vertexIdFromVertexNr(nr, id) || !id.isValid()) continue;
    const QgsPoint p = g->vertexAt(id);
    const double d = std::hypot(p.x() - mapPoint.x(), p.y() - mapPoint.y());
    // 严格小于：等距保留先出现顶点——闭合环首/末顶点同坐标时取首顶点，
    // 与 Python 侧顶点寻址惯例一致。
    if (d < best) {
      best = d;
      out = id;
      found = true;
    }
  }
  return found;
}

std::string PwbEditPickTool::vertexPathJson(Qgis::WkbType wkbType,
                                            const QgsVertexId& id) {
  QStringList parts;
  switch (QgsWkbTypes::flatType(wkbType)) {
    case Qgis::WkbType::Point:
      break;
    case Qgis::WkbType::MultiPoint:
      parts << QString::number(id.part);
      break;
    case Qgis::WkbType::LineString:
      parts << QString::number(id.vertex);
      break;
    case Qgis::WkbType::MultiLineString:
      parts << QString::number(id.part) << QString::number(id.vertex);
      break;
    case Qgis::WkbType::Polygon:
      parts << QString::number(id.ring) << QString::number(id.vertex);
      break;
    case Qgis::WkbType::MultiPolygon:
      parts << QString::number(id.part) << QString::number(id.ring)
            << QString::number(id.vertex);
      break;
    default:
      break;
  }
  return ("[" + parts.join(QStringLiteral(",")) + "]").toStdString();
}

QgsPointXY PwbEditPickTool::snapOrRaw(const QgsPointXY& mapPoint) const {
  const QgsPointLocator::Match m = canvas()->snappingUtils()->snapToMap(mapPoint);
  return m.isValid() ? m.point() : mapPoint;
}

QgsPointLocator::Match PwbEditPickTool::snapMatch(const QgsPointXY& mapPoint) const {
  return canvas()->snappingUtils()->snapToMap(mapPoint);
}

namespace {

const char* matchTypeName(QgsPointLocator::Type type) {
  switch (type) {
    case QgsPointLocator::Vertex:
      return "vertex";
    case QgsPointLocator::Edge:
      return "segment";
    case QgsPointLocator::MiddleOfSegment:
      return "midpoint";
    case QgsPointLocator::Centroid:
      return "centroid";
    case QgsPointLocator::Area:
      return "area";
    case QgsPointLocator::LineEndpoint:
      return "endpoint";
    default:
      return "unknown";
  }
}

}  // namespace

void PwbEditPickTool::updateSnapIndicator(
    const QgsPointXY& mapPoint, const QgsPointLocator::Match* match) {
  // 复用调用方已查的命中（updateHover 同一 move 内已查过）；未传则自查。
  const QgsPointLocator::Match local =
      match == nullptr ? snapMatch(mapPoint) : QgsPointLocator::Match();
  const QgsPointLocator::Match& m = match != nullptr ? *match : local;
  if (!snap_indicator_) snap_indicator_ = std::make_unique<QgsSnapIndicator>(canvas());
  snap_indicator_->setMatch(m);
  // 节流：命中签名（类型/层/要素）不变且命中点位移 <= 1 像素时不回传。
  std::string signature;
  if (m.isValid()) {
    signature = std::to_string(static_cast<int>(m.type()));
    if (m.layer() != nullptr) {
      signature += ":" + m.layer()->customProperty(QStringLiteral("pwb/doc_id"))
                                .toString()
                                .toStdString();
    }
    signature += ":" + std::to_string(static_cast<long long>(m.featureId()));
  }
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  const bool moved =
      m.isValid() &&
      std::hypot(m.point().x() - snap_feedback_x_, m.point().y() - snap_feedback_y_) > mup;
  // 初始态 signature 为空且从未发射：unmatched（空签名）必须能发出——否则
  // snapping 关闭时宿主永远收不到"无命中"回执（首次发射守卫）。
  if (snap_feedback_emitted_ && signature == snap_feedback_signature_ && !moved) return;
  snap_feedback_signature_ = signature;
  snap_feedback_emitted_ = true;
  std::string payload;
  if (m.isValid()) {
    std::string docId;
    std::string featureId;
    if (m.layer() != nullptr) {
      docId = m.layer()->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString();
      featureId = resolver_ ? resolver_(m.layer(), m.featureId())
                            : std::to_string(static_cast<long long>(m.featureId()));
    }
    payload = std::string("{\"matched\":true,\"x\":") +
              QString::number(m.point().x(), 'g', 12).toStdString() +
              ",\"y\":" + QString::number(m.point().y(), 'g', 12).toStdString() +
              ",\"layer_doc_id\":\"" + docId + "\",\"feature_id\":\"" + featureId +
              "\",\"match_type\":\"" + matchTypeName(m.type()) + "\",\"distance\":" +
              QString::number(m.distance(), 'g', 12).toStdString() + "}";
    snap_feedback_x_ = m.point().x();
    snap_feedback_y_ = m.point().y();
  } else {
    payload = "{\"matched\":false}";
  }
  callback_("snap_feedback", payload);
}

void PwbEditPickTool::hideSnapIndicator() {
  if (snap_indicator_) snap_indicator_->setMatch(QgsPointLocator::Match());
  if (snap_feedback_emitted_ && !snap_feedback_signature_.empty()) {
    snap_feedback_signature_.clear();
    callback_("snap_feedback", "{\"matched\":false}");
  }
}

std::string PwbEditPickTool::basePayload(const Pick& pick) const {
  return std::string("\"layer_doc_id\":\"") + pick.docId +
         "\",\"feature_id\":\"" + pick.featureId + "\"";
}

// -- 顶点编辑 ---------------------------------------------------------------

PwbVertexTool::~PwbVertexTool() = default;

// -- v2（M1 §4 当前层档；editLayer() 非空时启用）-----------------------------

QgsVectorLayer* PwbVertexTool::editLayer() const {
  if (!edit_layer_provider_) return nullptr;
  QgsVectorLayer* layer = edit_layer_provider_();
  if (layer == nullptr || !layer->isEditable()) return nullptr;
  return layer;
}

std::vector<PwbVertexTool::VertexRef> PwbVertexTool::verticesNear(
    QgsVectorLayer* layer, const QgsPointXY& center, double radius) {
  std::vector<VertexRef> out;
  if (layer == nullptr) return out;
  QgsFeature feature;
  QgsFeatureIterator cursor = layer->getFeatures();  // 合并编辑缓冲
  while (cursor.nextFeature(feature)) {
    if (!feature.hasGeometry()) continue;
    const QgsGeometry geometry = feature.geometry();
    const QgsAbstractGeometry* raw = geometry.constGet();
    if (raw == nullptr) continue;
    const int total = static_cast<int>(raw->vertexCount());
    for (int nr = 0; nr < total; ++nr) {
      QgsVertexId vid;
      if (!geometry.vertexIdFromVertexNr(nr, vid) || !vid.isValid()) continue;
      const QgsPoint point = raw->vertexAt(vid);
      if (std::hypot(point.x() - center.x(), point.y() - center.y())
          <= radius) {
        out.push_back({feature.id(), vid, QgsPointXY(point.x(), point.y())});
      }
    }
  }
  return out;
}

void PwbVertexTool::clearSharedMarkers() {
  shared_markers_.clear();
}

void PwbVertexTool::beginSharedDrag(const QgsPointXY& anchor,
                                    std::vector<VertexRef> shared) {
  shared_drag_ = std::move(shared);
  drag_anchor_ = anchor;
  dragging_ = true;
  clearHover();
  hideSnapIndicator();
  // 公共节点高亮（§4）：拖动集合 = 全部同位置节点（视觉区分「拓扑同步」）。
  for (const VertexRef& ref : shared_drag_) {
    auto marker = std::make_unique<QgsVertexMarker>(canvas());
    marker->setCenter(ref.pos);
    marker->setIconType(QgsVertexMarker::ICON_CIRCLE);
    marker->setIconSize(8);
    marker->setColor(QColor(255, 140, 0, 220));
    marker->setPenWidth(2);
    shared_markers_.push_back(std::move(marker));
  }
  rubber_ = std::make_unique<QgsRubberBand>(canvas(), Qgis::GeometryType::Point);
  rubber_->setColor(QColor(255, 0, 0, 200));
  rubber_->setWidth(2);
  rubber_->addPoint(anchor);
}

void PwbVertexTool::finishSharedDrag(QgsVectorLayer* layer,
                                     const QgsPointXY& target) {
  const std::vector<VertexRef> refs = std::move(shared_drag_);
  cancelDrag();
  clearSharedMarkers();
  const QgsPointXY anchor = drag_anchor_;
  // 零位移抑制（v1 同语义）：单击不是拖动。
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  if (std::hypot(target.x() - anchor.x(), target.y() - anchor.y())
      < kTolerancePx * mup) {
    return;
  }
  // 每层每手势恰一宏（§2 不变式）：全部共享节点一次移动、一条撤销记录。
  layer->beginEditCommand(refs.size() > 1 ? QStringLiteral("Moved vertices")
                                          : QStringLiteral("Moved vertex"));
  QgsVectorLayerEditUtils utils(layer);
  bool moved = false;
  std::vector<QgsFeatureId> touched;
  for (const VertexRef& ref : refs) {
    QgsFeature feature;
    if (!layer->getFeatures(QgsFeatureRequest(ref.fid)).nextFeature(feature)
        || !feature.hasGeometry()) {
      continue;
    }
    const int nr = feature.geometry().vertexNrFromVertexId(ref.vid);
    if (nr < 0) continue;
    if (utils.moveVertex(target.x(), target.y(), ref.fid, nr)) {
      moved = true;
      touched.push_back(ref.fid);
    }
  }
  if (!moved) {
    layer->destroyEditCommand();
    return;
  }
  layer->endEditCommand();
  emitGesture(refs.size() > 1 ? "vertex_move_multi" : "vertex_move",
              refs.size() > 1 ? "Moved vertices" : "Moved vertex", layer,
              touched);
}

void PwbVertexTool::emitGesture(const char* gesture, const char* undo_text,
                                QgsVectorLayer* layer,
                                const std::vector<QgsFeatureId>& fids) const {
  const QString doc_id =
      layer->customProperty(QStringLiteral("pwb/doc_id")).toString();
  std::string payload = "{\"layer_doc_id\":\"" + doc_id.toStdString()
      + "\",\"gesture\":\"" + gesture + "\",\"undo_text\":\"" + undo_text
      + "\",\"features\":[";
  // 闭合环的重复闭合点会命中多个 vertex——宿主 id 去重保序。
  std::vector<std::string> host_ids;
  for (const QgsFeatureId fid : fids) {
    std::string host_id = resolver_
        ? resolver_(layer, fid)
        : std::to_string(static_cast<long long>(fid));
    if (std::find(host_ids.begin(), host_ids.end(), host_id)
        != host_ids.end()) {
      continue;
    }
    host_ids.push_back(std::move(host_id));
  }
  for (size_t i = 0; i < host_ids.size(); ++i) {
    if (i > 0) payload += ",";
    payload += "\"" + host_ids[i] + "\"";
  }
  payload += "]}";
  callback_("edit_gesture", payload);
}

void PwbVertexTool::canvasPressEvent(QgsMapMouseEvent* e) {
  if (e->button() != Qt::LeftButton) return;
  if (QgsVectorLayer* layer = editLayer()) {
    // v2 当前层档：拾取容差内找层内顶点 → 1e-8 精确重合集 = 共享节点。
    const double mup = canvas()->mapSettings().mapUnitsPerPixel();
    const std::vector<VertexRef> picked =
        verticesNear(layer, e->mapPoint(), kTolerancePx * mup);
    if (picked.empty()) {
      callback_("pick_miss", "{}");
      return;
    }
    const QgsPointXY anchor = picked.front().pos;
    std::vector<VertexRef> shared =
        verticesNear(layer, anchor, kSharedNodeEpsilon);
    if (shared.empty()) {
      callback_("pick_miss", "{}");
      return;
    }
    beginSharedDrag(anchor, std::move(shared));
    return;
  }
  Pick pick;
  QgsVertexId vid;
  if (!pickFeature(e->mapPoint(), pick) || !nearestVertex(pick, e->mapPoint(), vid)) {
    callback_("pick_miss", "{}");
    return;
  }
  current_ = pick;
  vertex_id_ = vid;
  dragging_ = true;
  clearHover();
  hideSnapIndicator();  // 拖动期间指示器冻结在原位（review-5 #19）——隐藏，松手后 move 重建
  rubber_ = std::make_unique<QgsRubberBand>(canvas(), Qgis::GeometryType::Point);
  rubber_->setColor(QColor(255, 0, 0, 200));
  rubber_->setWidth(2);
  const QgsPoint p = pick.geometry.constGet()->vertexAt(vid);
  rubber_->addPoint(QgsPointXY(p.x(), p.y()));
}

void PwbVertexTool::canvasMoveEvent(QgsMapMouseEvent* e) {
  if (!dragging_) {
    // V10：非拖动 hover——顶点/段命中 marker + snap 指示与节流反馈。
    // updateHover 返回它已查到的 locator 命中，指示器复用（单次 move 单次
    // snapToMap，review-4 #2）。
    const QgsPointLocator::Match m = updateHoverMatch(e->mapPoint());
    updateSnapIndicator(e->mapPoint(), &m);
    return;
  }
  const QgsPointXY p = snapOrRaw(e->mapPoint());
  rubber_->reset(Qgis::GeometryType::Point);
  rubber_->addPoint(p);
}

void PwbVertexTool::canvasReleaseEvent(QgsMapMouseEvent* e) {
  if (!dragging_ || e->button() != Qt::LeftButton) return;
  const QgsPointXY p = snapOrRaw(e->mapPoint());
  if (!shared_drag_.empty()) {
    // v2：共享节点集整体落位（每层每手势恰一宏）。
    if (QgsVectorLayer* layer = editLayer()) {
      finishSharedDrag(layer, p);
      return;
    }
    shared_drag_.clear();
    clearSharedMarkers();
  }
  const Pick pick = current_;
  const QgsVertexId vid = vertex_id_;
  // 零位移抑制（review-5 #5）：press→release 顶点位移小于拖动阈值（拾取容差
  // 像素数，QGIS 桌面 click-vs-drag 同语义）= 单击而非拖动——提交会产生
  // 同值 SetVertexCommand（undo 栈噪音 + 幻影脏会话）。
  {
    const QgsPoint orig = pick.geometry.constGet()->vertexAt(vid);
    const double mup = canvas()->mapSettings().mapUnitsPerPixel();
    if (std::hypot(p.x() - orig.x(), p.y() - orig.y()) < kTolerancePx * mup) {
      cancelDrag();
      return;
    }
  }
  cancelDrag();
  clearHover();  // 提交后镜像异步刷新（120ms 防抖）：立即失效，防止 stale 几何上删点
  std::string payload = "{" + basePayload(pick) + ",\"path\":" +
                        vertexPathJson(pick.geometry.wkbType(), vid) +
                        ",\"x\":" + QString::number(p.x(), 'g', 12).toStdString() +
                        ",\"y\":" + QString::number(p.y(), 'g', 12).toStdString() + "}";
  callback_("vertex_moved", payload);
}

void PwbVertexTool::canvasDoubleClickEvent(QgsMapMouseEvent* e) {
  if (dragging_) {
    cancelDrag();
    clearSharedMarkers();
    return;
  }
  updateHover(e->mapPoint());
  if (!hover_.has_segment) return;
  const auto flat = QgsWkbTypes::flatType(hover_.pick.geometry.wkbType());
  if (flat == Qgis::WkbType::Point || flat == Qgis::WkbType::MultiPoint) return;
  if (QgsVectorLayer* layer = editLayer();
      layer != nullptr && hover_.pick.layer == layer
      && hover_.pick.geometry.constGet() != nullptr) {
    // v2：段上插点直写缓冲（一宏「Added vertex」）。
    const QgsVertexId at = hover_.insert_before;
    const QgsPointXY p = hover_.segment_point;
    const int before = hover_.pick.geometry.vertexNrFromVertexId(at);
    clearHover();
    if (before < 0) return;
    layer->beginEditCommand(QStringLiteral("Added vertex"));
    QgsVectorLayerEditUtils utils(layer);
    if (!utils.insertVertex(p.x(), p.y(), hover_.pick.fid, before)) {
      layer->destroyEditCommand();
      return;
    }
    layer->endEditCommand();
    emitGesture("vertex_insert", "Added vertex", layer, {hover_.pick.fid});
    e->accept();
    return;
  }
  const Pick pick = hover_.pick;
  const QgsVertexId at = hover_.insert_before;
  const QgsPointXY p = hover_.segment_point;
  clearHover();
  std::string payload = "{" + basePayload(pick) + ",\"path\":" +
                        vertexPathJson(pick.geometry.wkbType(), at) +
                        ",\"x\":" + QString::number(p.x(), 'g', 12).toStdString() +
                        ",\"y\":" + QString::number(p.y(), 'g', 12).toStdString() + "}";
  callback_("vertex_inserted", payload);
  e->accept();
}

void PwbVertexTool::keyPressEvent(QKeyEvent* e) {
  if (e->key() == Qt::Key_Delete && !dragging_) {
    if (QgsVectorLayer* layer = editLayer()) {
      // v2 联合删除：hover 顶点位置的同位置节点集（1e-8）整体删除；
      // 任一要素低于最少顶点 → 整手势拒绝（原子语义）。
      if (hover_.has_vertex && hover_.pick.layer == layer
          && hover_.pick.geometry.constGet() != nullptr) {
        const QgsPoint hover_point =
            hover_.pick.geometry.constGet()->vertexAt(hover_.vertex);
        std::vector<VertexRef> shared = verticesNear(
            layer, QgsPointXY(hover_point.x(), hover_point.y()),
            kSharedNodeEpsilon);
        // 闭合环的重复闭合点与自身「共享」——同要素只删一个节点
        // （QGIS deleteVertex 自持 ring 闭合不变量）。
        {
          std::vector<VertexRef> deduped;
          std::set<QgsFeatureId> seen;
          for (const VertexRef& ref : shared) {
            if (seen.insert(ref.fid).second) deduped.push_back(ref);
          }
          shared = std::move(deduped);
        }
        bool guarded = !shared.empty();
        for (const VertexRef& ref : shared) {
          QgsFeature feature;
          if (!layer->getFeatures(QgsFeatureRequest(ref.fid))
                   .nextFeature(feature) || !feature.hasGeometry()) {
            guarded = false;
            break;
          }
          Pick probe;
          probe.layer = layer;
          probe.fid = ref.fid;
          probe.geometry = feature.geometry();
          probe.docId = layer->customProperty(
              QStringLiteral("pwb/doc_id")).toString().toStdString();
          probe.featureId = resolver_
              ? resolver_(layer, ref.fid)
              : std::to_string(static_cast<long long>(ref.fid));
          if (!minVerticesAfterDelete(probe, ref.vid)) {
            guarded = false;
            break;
          }
        }
        if (!guarded) {
          callback_("vertex_delete_rejected", "{}");
          e->accept();
          return;
        }
        clearHover();
        layer->beginEditCommand(shared.size() > 1
                                    ? QStringLiteral("Deleted vertices")
                                    : QStringLiteral("Deleted vertex"));
        QgsVectorLayerEditUtils utils(layer);
        bool deleted = false;
        std::vector<QgsFeatureId> touched;
        for (const VertexRef& ref : shared) {
          QgsFeature feature;
          if (!layer->getFeatures(QgsFeatureRequest(ref.fid))
                   .nextFeature(feature) || !feature.hasGeometry()) {
            continue;
          }
          const int nr = feature.geometry().vertexNrFromVertexId(ref.vid);
          if (nr < 0) continue;
          if (utils.deleteVertex(ref.fid, nr) != Qgis::VectorEditResult::Success) {
            continue;
          }
          deleted = true;
          touched.push_back(ref.fid);
        }
        if (!deleted) {
          layer->destroyEditCommand();
          callback_("vertex_delete_rejected", "{}");
          e->accept();
          return;
        }
        layer->endEditCommand();
        emitGesture("vertex_delete", "Deleted vertex", layer, touched);
      } else {
        callback_("vertex_delete_rejected", "{}");
      }
      e->accept();
      return;
    }
    if (hover_.has_vertex && minVerticesAfterDelete(hover_.pick, hover_.vertex)) {
      const Pick pick = hover_.pick;
      const QgsVertexId vid = hover_.vertex;
      clearHover();
      std::string payload = "{" + basePayload(pick) + ",\"path\":" +
                            vertexPathJson(pick.geometry.wkbType(), vid) + "}";
      callback_("vertex_deleted", payload);
    } else {
      // 守卫拒绝（无 hover / 低于最少顶点）给出可诊断回执（review-5 #10），
      // 不再是无声死键；按键仍消费：不冒泡成其它快捷键。
      callback_("vertex_delete_rejected", "{}");
    }
    e->accept();
    return;
  }
  PwbEditPickTool::keyPressEvent(e);
}

void PwbVertexTool::deactivate() {
  clearHover();
  clearSharedMarkers();
  shared_drag_.clear();
  hideSnapIndicator();
  PwbEditPickTool::deactivate();
}

bool PwbVertexTool::updateHover(const QgsPointXY& mapPoint) {
  updateHoverMatch(mapPoint);
  return hover_.has_vertex || hover_.has_segment;
}

QgsPointLocator::Match PwbVertexTool::updateHoverMatch(const QgsPointXY& mapPoint) {
  hover_ = HoverState();
  const QgsPointLocator::Match m = snapMatch(mapPoint);
  if (m.isValid() && m.layer() != nullptr) {
    const QString docId =
        m.layer()->customProperty(QStringLiteral("pwb/doc_id")).toString();
    if (!docId.isEmpty()) {
      QgsFeature f;
      if (m.layer()->getFeatures(QgsFeatureRequest(m.featureId())).nextFeature(f) &&
          f.hasGeometry()) {
        hover_.pick.layer = m.layer();
        hover_.pick.fid = m.featureId();
        hover_.pick.geometry = f.geometry();
        hover_.pick.docId = docId.toStdString();
        hover_.pick.featureId =
            resolver_ ? resolver_(m.layer(), m.featureId())
                      : std::to_string(static_cast<long long>(m.featureId()));
        QgsVertexId vid;
        if (m.hasVertex()) {
          if (f.geometry().vertexIdFromVertexNr(m.vertexIndex(), vid) && vid.isValid()) {
            hover_.has_vertex = true;
            hover_.vertex = vid;
          }
        } else if (m.hasEdge()) {
          // Match 语义：段命中的 vertexIndex 是段首顶点；插点位置 = 段终点。
          if (f.geometry().vertexIdFromVertexNr(m.vertexIndex() + 1, vid) &&
              vid.isValid()) {
            hover_.has_segment = true;
            hover_.insert_before = vid;
            hover_.segment_point = m.point();
          }
        }
      }
    }
  }
  if (!hover_.has_vertex && !hover_.has_segment) {
    // 2) snapping 关闭时的回退：容差拾取 + 单几何顶点/段扫描（O(单要素顶点)）。
    Pick pick;
    if (pickFeature(mapPoint, pick)) {
      QgsVertexId vid;
      if (nearestVertex(pick, mapPoint, vid)) {
        hover_.has_vertex = true;
        hover_.pick = pick;
        hover_.vertex = vid;
      } else {
        QgsVertexId endVid;
        QgsPointXY proj;
        if (nearestSegmentOnFeature(pick, mapPoint, endVid, proj)) {
          hover_.has_segment = true;
          hover_.pick = pick;
          hover_.insert_before = endVid;
          hover_.segment_point = proj;
        }
      }
    }
  }
  if (editLayer() != nullptr
      && (hover_.has_vertex || hover_.has_segment)
      && hover_.pick.layer != nullptr
      && hover_.pick.layer != editLayer()) {
    // v2 当前层档：hover 只认编辑目标层（其他层命中 = 无操作——
    // 删除/插点不越层写缓冲）。
    hover_ = HoverState();
  }
  updateHoverMarker();
  return m;
}

bool PwbVertexTool::nearestSegmentOnFeature(const Pick& pick,
                                            const QgsPointXY& mapPoint,
                                            QgsVertexId& endVid,
                                            QgsPointXY& projOut) const {
  // V10（review-1 #3 重构）：投影/最近段查询交给 QGIS 核心公开算子——
  // closestSegmentWithContext 返回投影点 + 段后顶点号（= 插入位置），不再
  // 手写逐段扫描（第二几何内核气味；且核心算子覆盖曲线段）。
  if (QgsWkbTypes::geometryType(pick.geometry.wkbType()) == Qgis::GeometryType::Point)
    return false;
  QgsPointXY proj;
  int nextVertexNr = -1;
  const double dist2 = pick.geometry.closestSegmentWithContext(mapPoint, proj, nextVertexNr);
  if (dist2 < 0.0) return false;
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  if (std::sqrt(dist2) >= kTolerancePx * mup) return false;
  QgsVertexId id;
  if (!pick.geometry.vertexIdFromVertexNr(nextVertexNr, id) || !id.isValid())
    return false;
  endVid = id;
  projOut = proj;
  return true;
}

bool PwbVertexTool::minVerticesAfterDelete(const Pick& pick,
                                           const QgsVertexId& vid) const {
  const QgsAbstractGeometry* g = pick.geometry.constGet();
  if (g == nullptr) return false;
  const auto flat = QgsWkbTypes::flatType(pick.geometry.wkbType());
  const int count = g->vertexCount(vid.part, vid.ring);
  if (flat == Qgis::WkbType::Polygon || flat == Qgis::WkbType::MultiPolygon) {
    // 宿主 GeoJSON ring 存闭合重复点：>=4（3 真实 + 闭合）为下限。
    return count - 1 >= 4;
  }
  if (flat == Qgis::WkbType::LineString || flat == Qgis::WkbType::MultiLineString) {
    return count - 1 >= 2;
  }
  // Point/MultiPoint 不走删点（多点删点 = 删部件，走 delete_part 命令）。
  return false;
}

void PwbVertexTool::updateHoverMarker() {
  if (hover_.has_vertex) {
    if (!hover_marker_) hover_marker_ = std::make_unique<QgsVertexMarker>(canvas());
    const QgsPoint p = hover_.pick.geometry.constGet()->vertexAt(hover_.vertex);
    hover_marker_->setCenter(QgsPointXY(p.x(), p.y()));
    hover_marker_->setIconType(QgsVertexMarker::ICON_CIRCLE);
    hover_marker_->setColor(QColor(255, 0, 0, 190));
    hover_marker_->setIconSize(10);
    hover_marker_->setPenWidth(2);
    hover_marker_->show();
  } else if (hover_.has_segment) {
    if (!hover_marker_) hover_marker_ = std::make_unique<QgsVertexMarker>(canvas());
    hover_marker_->setCenter(hover_.segment_point);
    hover_marker_->setIconType(QgsVertexMarker::ICON_BOX);
    hover_marker_->setColor(QColor(255, 128, 0, 190));
    hover_marker_->setIconSize(8);
    hover_marker_->setPenWidth(2);
    hover_marker_->show();
  } else {
    hover_marker_.reset();
  }
}

void PwbVertexTool::clearHover() {
  hover_ = HoverState();
  hover_marker_.reset();
}

// -- 要素移动 ---------------------------------------------------------------

void PwbMoveTool::canvasPressEvent(QgsMapMouseEvent* e) {
  if (e->button() != Qt::LeftButton) return;
  Pick pick;
  if (!pickFeature(e->mapPoint(), pick)) {
    callback_("pick_miss", "{}");
    return;
  }
  current_ = pick;
  origin_ = e->mapPoint();
  dragging_ = true;
  const Qgis::GeometryType gt = QgsWkbTypes::geometryType(pick.geometry.wkbType());
  rubber_ = std::make_unique<QgsRubberBand>(canvas(), gt);
  rubber_->setColor(QColor(255, 128, 0, 160));
  rubber_->setWidth(2);
  rubber_->setToGeometry(pick.geometry, nullptr);
}

void PwbMoveTool::canvasMoveEvent(QgsMapMouseEvent* e) {
  if (!dragging_) return;
  const double dx = e->mapPoint().x() - origin_.x();
  const double dy = e->mapPoint().y() - origin_.y();
  QgsGeometry moved = current_.geometry;
  moved.translate(dx, dy);
  rubber_->setToGeometry(moved, nullptr);
}

void PwbMoveTool::canvasReleaseEvent(QgsMapMouseEvent* e) {
  if (!dragging_ || e->button() != Qt::LeftButton) return;
  const double dx = e->mapPoint().x() - origin_.x();
  const double dy = e->mapPoint().y() - origin_.y();
  const Pick pick = current_;
  cancelDrag();
  std::string payload = "{" + basePayload(pick) +
                        ",\"dx\":" + QString::number(dx, 'g', 12).toStdString() +
                        ",\"dy\":" + QString::number(dy, 'g', 12).toStdString() + "}";
  callback_("feature_moved", payload);
}
// -- 选择 -------------------------------------------------------------------

PwbSelectTool::PwbSelectTool(QgsMapCanvas* canvas, Callback callback,
                             FeatureIdResolver resolver)
    : PwbEditPickTool(canvas, std::move(callback), std::move(resolver)),
      handler_(std::make_unique<QgsMapToolSelectionHandler>(
          canvas, QgsMapToolSelectionHandler::SelectSimple)) {
  QObject::connect(handler_.get(),
                   &QgsMapToolSelectionHandler::geometryChanged, canvas,
                   [this](Qt::KeyboardModifiers modifiers) {
                     onGeometryChanged(modifiers);
                   });
}

void PwbSelectTool::canvasPressEvent(QgsMapMouseEvent* e) {
  handler_->canvasPressEvent(e);
}

void PwbSelectTool::canvasMoveEvent(QgsMapMouseEvent* e) {
  handler_->canvasMoveEvent(e);
}

void PwbSelectTool::canvasReleaseEvent(QgsMapMouseEvent* e) {
  handler_->canvasReleaseEvent(e);
}

void PwbSelectTool::keyReleaseEvent(QKeyEvent* e) {
  handler_->keyReleaseEvent(e);
}

void PwbSelectTool::deactivate() {
  handler_->deactivate();
  PwbEditPickTool::deactivate();
}

// -- 测距（V7）---------------------------------------------------------------

PwbMeasureTool::PwbMeasureTool(QgsMapCanvas* canvas, Callback callback)
    : PwbEditPickTool(canvas, std::move(callback)) {
  // 激活时按画布 CRS 配置测算器：地理 CRS + 工程椭球体 → 椭球测算（米），
  // 否则平面测算（地图单位）。CRS 中途变更由工具重激活兜底（shim 每次
  // set_map_tool 重建工具实例）。
  distance_ = std::make_unique<QgsDistanceArea>();
  const QgsCoordinateReferenceSystem crs =
      canvas->mapSettings().destinationCrs();
  distance_->setSourceCrs(crs, QgsProject::instance()->transformContext());
  const QString ellipsoid = QgsProject::instance()->ellipsoid();
  ellipsoidal_ = crs.isGeographic() && !ellipsoid.isEmpty();
  if (ellipsoidal_) distance_->setEllipsoid(ellipsoid);
}

PwbMeasureTool::~PwbMeasureTool() = default;

void PwbMeasureTool::canvasPressEvent(QgsMapMouseEvent* e) {
  if (e->button() == Qt::RightButton) {
    if (!points_.isEmpty()) callback_("measure_completed", payloadJson("measure_completed", e->mapPoint()));
    reset();
    return;
  }
  if (e->button() != Qt::LeftButton) return;
  const QgsPointXY p = snapOrRaw(e->mapPoint());
  points_.push_back(p);
  if (!rubber_) {
    rubber_ = std::make_unique<QgsRubberBand>(canvas(), Qgis::GeometryType::Line);
    rubber_->setColor(QColor(255, 170, 0, 210));
    rubber_->setWidth(2);
  }
  rubber_->addPoint(p);
  callback_("measure_updated", payloadJson("measure_updated", e->mapPoint()));
}

void PwbMeasureTool::canvasMoveEvent(QgsMapMouseEvent* e) {
  if (points_.isEmpty() || !rubber_) return;
  // 折线 = 已采点 + hover 点（预览段），逐帧重建（RubberBand 语义）。
  rubber_->reset(Qgis::GeometryType::Line);
  for (const QgsPointXY& p : points_) rubber_->addPoint(p);
  rubber_->addPoint(e->mapPoint());
  callback_("measure_updated", payloadJson("measure_updated", e->mapPoint()));
}

void PwbMeasureTool::canvasReleaseEvent(QgsMapMouseEvent* e) {
  Q_UNUSED(e);
}

void PwbMeasureTool::keyPressEvent(QKeyEvent* e) {
  if (e->key() == Qt::Key_Escape) {
    const bool had = !points_.isEmpty();
    reset();
    if (had) callback_("measure_canceled", "{}");
    e->accept();
    return;
  }
  QgsMapTool::keyPressEvent(e);
}

void PwbMeasureTool::deactivate() {
  reset();
  QgsMapTool::deactivate();
}

double PwbMeasureTool::totalIncluding(const QgsPointXY& hover) const {
  if (points_.isEmpty()) return 0.0;
  QVector<QgsPointXY> all = points_;
  all.push_back(hover);
  try {
    return distance_->measureLine(all);
  } catch (const QgsCsException&) {
    // 椭球测算换带失败：回落平面距离，绝不静默吞掉（payload 如实报告）。
    double total = 0.0;
    for (int i = 1; i < all.size(); ++i)
      total += std::hypot(all[i].x() - all[i - 1].x(), all[i].y() - all[i - 1].y());
    return total;
  }
}

std::string PwbMeasureTool::payloadJson(const char* action, const QgsPointXY& hover) const {
  QStringList pts;
  for (const QgsPointXY& p : points_)
    pts << QStringLiteral("[%1,%2]")
               .arg(QString::number(p.x(), 'g', 12),
                    QString::number(p.y(), 'g', 12));
  QStringList segs;
  QgsPointXY prev;
  bool first = true;
  for (const QgsPointXY& p : points_) {
    if (!first) {
      double d = 0.0;
      try {
        d = distance_->measureLine(prev, p);
      } catch (const QgsCsException&) {
        d = std::hypot(p.x() - prev.x(), p.y() - prev.y());
      }
      segs << QString::number(d, 'g', 12);
    }
    prev = p;
    first = false;
  }
  if (!points_.isEmpty()) {
    double live = 0.0;
    try {
      live = distance_->measureLine(points_.constLast(), hover);
    } catch (const QgsCsException&) {
      live = std::hypot(hover.x() - points_.constLast().x(),
                        hover.y() - points_.constLast().y());
    }
    segs << QString::number(live, 'g', 12);
  }
  return std::string("{\"action\":\"") + action +
         "\",\"points\":[" + pts.join(QStringLiteral(",")).toStdString() +
         "],\"segments\":[" + segs.join(QStringLiteral(",")).toStdString() +
         "],\"total\":" +
         QString::number(totalIncluding(hover), 'g', 12).toStdString() +
         ",\"ellipsoidal\":" + (ellipsoidal_ ? "true" : "false") + "}";
}

void PwbMeasureTool::reset() {
  points_.clear();
  rubber_.reset();
}

}  // namespace pwb::qgis_render

