#include "edit_tools.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
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

// -- v2（M1 §4 当前层档 + M2 §4 全部层档/拓扑点/避免重叠）--------------------

QgsVectorLayer* PwbVertexTool::editLayer() const {
  if (!edit_layer_provider_) return nullptr;
  QgsVectorLayer* layer = edit_layer_provider_();
  if (layer == nullptr || !layer->isEditable()) return nullptr;
  return layer;
}

std::vector<QgsVectorLayer*> PwbVertexTool::candidateLayers() const {
  std::vector<QgsVectorLayer*> out;
  if (candidate_layers_provider_) out = candidate_layers_provider_();
  return out;
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
        out.push_back({layer, feature.id(), vid,
                       QgsPointXY(point.x(), point.y())});
      }
    }
  }
  return out;
}

std::vector<PwbVertexTool::VertexRef> PwbVertexTool::discoverAllLayers(
    const QgsPointXY& mapPoint, double pick_radius) {
  // 候选层内最近顶点为锚（同 CRS 层才可比坐标——§2 跨层拓扑仅同 CRS）。
  const auto candidates = candidateLayers();
  std::vector<VertexRef> picked;
  for (QgsVectorLayer* layer : candidates) {
    if (layer == nullptr) continue;
    for (VertexRef& ref : verticesNear(layer, mapPoint, pick_radius)) {
      if (!ref.layer->crs().isValid()) continue;
      if (!picked.empty()
          && ref.layer->crs() != picked.front().layer->crs()) {
        continue;  // 与首个命中层不同 CRS：不参与本轮发现
      }
      picked.push_back(std::move(ref));
    }
  }
  if (picked.empty()) return picked;
  const QgsPointXY anchor = picked.front().pos;
  // 同 CRS 过滤（§2）：坐标只在同 CRS 层间可比——异层 CRS 直接不参与。
  const QgsCoordinateReferenceSystem primary_crs =
      picked.front().layer != nullptr ? picked.front().layer->crs()
                                      : QgsCoordinateReferenceSystem();
  std::vector<VertexRef> shared;
  std::vector<std::string> join_ids;
  for (QgsVectorLayer* layer : candidates) {
    if (layer == nullptr || !layer->crs().isValid()
        || (primary_crs.isValid() && layer->crs() != primary_crs)) {
      continue;
    }
    for (const VertexRef& ref : verticesNear(layer, anchor,
                                             kSharedNodeEpsilon)) {
      shared.push_back(ref);
      if (!layer->isEditable()) {
        // 同层闭合环重复点会重复触发——去重（一次入集请求足矣）。
        const std::string doc = layer->customProperty(
                                    QStringLiteral("pwb/doc_id"))
                                    .toString()
                                    .toStdString();
        if (std::find(join_ids.begin(), join_ids.end(), doc)
            == join_ids.end()) {
          join_ids.push_back(doc);
        }
      }
    }
  }
  // §3 按需生长：未在会话中的伙伴层同步请求入集（宿主门禁复查——
  // 拒绝层不参与；回调同步，release 时该层若已入会话即参与移动）。
  if (!join_ids.empty()) {
    std::string ids = "[";
    for (size_t i = 0; i < join_ids.size(); ++i) {
      if (i > 0) ids += ",";
      ids += "\"" + join_ids[i] + "\"";
    }
    ids += "]";
    callback_("join_requested", "{\"layer_doc_ids\":" + ids + "}");
  }
  return shared;
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
    if (ref.layer == nullptr) continue;
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

QList<QgsVectorLayer*> PwbVertexTool::avoidLayersFor(
    QgsVectorLayer* edited) const {
  QList<QgsVectorLayer*> out;
  // M2：读画布挂载工程（跨栈单例生命周期不可靠——GUI 数字化基类单读
  // instance 由 setSnappingConfig 推送覆盖，本类不依赖单例）。
  QgsProject* project = canvas() != nullptr ? canvas()->project() : nullptr;
  if (project == nullptr || edited == nullptr) return out;
  const Qgis::AvoidIntersectionsMode mode =
      project->avoidIntersectionsMode();
  if (mode == Qgis::AvoidIntersectionsMode::AllowIntersections) return out;
  if (mode == Qgis::AvoidIntersectionsMode::AvoidIntersectionsCurrentLayer) {
    out.append(edited);
    return out;
  }
  for (QgsVectorLayer* layer : project->avoidIntersectionsLayers()) {
    if (layer != nullptr && layer->isEditable()) out.append(layer);
  }
  return out;
}

std::vector<QgsFeatureId> PwbVertexTool::applyVertexMoves(
    QgsVectorLayer* layer, const QgsPointXY& target,
    const std::vector<VertexRef>& refs) {
  std::vector<QgsFeatureId> touched;
  if (layer == nullptr || refs.empty()) return touched;
  // 按 fid 分组，逐要素：几何副本上 moveVertex → 避免重叠 → changeGeometry
  // →（工程拓扑开关开）自层拓扑点散布——全部在同一宏内。
  std::map<QgsFeatureId, std::vector<const VertexRef*>> by_fid;
  for (const VertexRef& ref : refs) {
    if (ref.layer != layer) continue;
    by_fid[ref.fid].push_back(&ref);
  }
  const QList<QgsVectorLayer*> avoid_layers = avoidLayersFor(layer);
  QgsProject* project = canvas() != nullptr ? canvas()->project() : nullptr;
  const bool topological = project != nullptr && project->topologicalEditing();
  bool any = false;
  layer->beginEditCommand(refs.size() > 1 || by_fid.size() > 1
                              ? QStringLiteral("Moved vertices")
                              : QStringLiteral("Moved vertex"));
  for (const auto& [fid, fid_refs] : by_fid) {
    QgsFeature feature;
    if (!layer->getFeatures(QgsFeatureRequest(fid)).nextFeature(feature)
        || !feature.hasGeometry()) {
      continue;
    }
    QgsGeometry geometry = feature.geometry();
    bool moved = false;
    for (const VertexRef* ref : fid_refs) {
      const int nr = geometry.vertexNrFromVertexId(ref->vid);
      if (nr < 0) continue;
      moved = geometry.moveVertex(QgsPoint(target.x(), target.y()), nr)
          || moved;
    }
    if (!moved) continue;
    // 避免重叠（§4 顶点/移动复刻）：裁掉与避让层既有要素的重叠部分；
    // 失败保持未裁几何（诚实，不静默丢改动）。
    if (!avoid_layers.isEmpty()) {
      QHash<QgsVectorLayer*, QSet<QgsFeatureId>> ignore;
      ignore.insert(layer, QSet<QgsFeatureId>{fid});
      const Qgis::GeometryOperationResult avoid_result =
          geometry.avoidIntersectionsV2(avoid_layers, ignore);
      if (avoid_result == Qgis::GeometryOperationResult::InvalidBaseGeometry
          || avoid_result
                 == Qgis::GeometryOperationResult::InvalidInputGeometryType) {
        // 保持 moved 几何。
      } else if (geometry.isEmpty()) {
        // 完全被裁空：放弃本要素变更（保持原几何）。
        QgsFeature fresh;
        if (layer->getFeatures(QgsFeatureRequest(fid)).nextFeature(fresh)) {
          geometry = fresh.geometry();
        }
      }
    }
    layer->changeGeometry(fid, geometry);
    touched.push_back(fid);
    any = true;
  }
  if (!any) {
    layer->destroyEditCommand();
    return {};
  }
  if (topological) {
    layer->addTopologicalPoints(QgsPoint(target.x(), target.y()));
    layer->addTopologicalPoints(
        QgsPoint(drag_anchor_.x(), drag_anchor_.y()));
  }
  layer->endEditCommand();
  return touched;
}

void PwbVertexTool::scatterTopologicalPoints(
    const QgsPointXY& anchor, const QgsPointXY& target,
    const std::vector<QgsVectorLayer*>& extra_layers) {
  QgsProject* project = canvas() != nullptr ? canvas()->project() : nullptr;
  if (project == nullptr || !project->topologicalEditing()) return;
  const QgsPoint points[2] = {QgsPoint(target.x(), target.y()),
                              QgsPoint(anchor.x(), anchor.y())};
  for (QgsVectorLayer* layer : extra_layers) {
    if (layer == nullptr || !layer->isEditable()
        || layer->geometryType() == Qgis::GeometryType::Point) {
      continue;
    }
    // bbox 预查（§4）：层范围与散布点完全不相交 → 不开宏（空手势不留痕）。
    bool intersects = false;
    for (const QgsPoint& point : points) {
      const QgsRectangle extent = layer->extent();
      if (point.x() >= extent.xMinimum() - 1e-8
          && point.x() <= extent.xMaximum() + 1e-8
          && point.y() >= extent.yMinimum() - 1e-8
          && point.y() <= extent.yMaximum() + 1e-8) {
        intersects = true;
        break;
      }
    }
    if (!intersects) continue;
    bool changed = false;
    layer->beginEditCommand(QStringLiteral("Topological points"));
    for (const QgsPoint& point : points) {
      changed = (layer->addTopologicalPoints(point) == 0) || changed;
    }
    if (!changed) {
      layer->destroyEditCommand();  // 无插入 → 不留痕
    } else {
      layer->endEditCommand();
    }
  }
}

void PwbVertexTool::finishSharedDrag(const QgsPointXY& target) {
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
  // release 时按当前可编辑层重组（join_requested 同步入集的层此刻已可编辑）。
  std::vector<QgsVectorLayer*> layers;          // 保序去重
  std::vector<VertexRef> live;
  for (const VertexRef& ref : refs) {
    if (ref.layer == nullptr || !ref.layer->isEditable()) continue;
    if (std::find(layers.begin(), layers.end(), ref.layer) == layers.end()) {
      layers.push_back(ref.layer);
    }
    live.push_back(ref);
  }
  if (live.empty()) return;
  std::vector<QgsFeatureId> all_touched;
  for (QgsVectorLayer* layer : layers) {
    // 释放时 vid 可能因伙伴层早前手势而过期——重新按位置对齐：
    // anchor 位置的顶点（缓冲现值）即本手势目标。
    std::vector<VertexRef> current = verticesNear(layer, anchor,
                                                  kSharedNodeEpsilon);
    for (const QgsFeatureId fid : applyVertexMoves(layer, target, current)) {
      all_touched.push_back(fid);
    }
  }
  // 同 CRS 其余会话层的拓扑点散布（各层自己的宏；bbox 预查）。
  {
    std::vector<QgsVectorLayer*> scatter_targets;
    if (candidate_layers_provider_) {
      for (QgsVectorLayer* layer : candidateLayers()) {
        if (layer == nullptr || !layer->isEditable()
            || std::find(layers.begin(), layers.end(), layer) != layers.end()
            || layer->geometryType() == Qgis::GeometryType::Point) {
          continue;
        }
        scatter_targets.push_back(layer);
      }
    }
    scatterTopologicalPoints(anchor, target, scatter_targets);
  }
  emitGestureMulti(live.size() > 1 ? "vertex_move_multi" : "vertex_move",
                   live.size() > 1 ? "Moved vertices" : "Moved vertex",
                   layers, all_touched);
}

void PwbVertexTool::finishSharedDeleteAt(const QgsPointXY& at) {
  // 发现（当前层或全部层档候选）同位置节点集；同要素闭合环重复点去重。
  std::vector<VertexRef> shared;
  if (allLayersScope()) {
    for (QgsVectorLayer* layer : candidateLayers()) {
      if (layer == nullptr) continue;
      for (const VertexRef& ref : verticesNear(layer, at, kSharedNodeEpsilon))
        shared.push_back(ref);
    }
  } else if (QgsVectorLayer* layer = editLayer()) {
    shared = verticesNear(layer, at, kSharedNodeEpsilon);
  }
  {
    std::vector<VertexRef> deduped;
    std::set<std::pair<QgsVectorLayer*, QgsFeatureId>> seen;
    for (const VertexRef& ref : shared) {
      if (seen.insert({ref.layer, ref.fid}).second) deduped.push_back(ref);
    }
    shared = std::move(deduped);
  }
  if (shared.empty()) {
    callback_("vertex_delete_rejected", "{}");
    return;
  }
  // 最小顶点守卫（每要素一次删除；原子拒绝）。
  for (const VertexRef& ref : shared) {
    QgsFeature feature;
    if (ref.layer == nullptr
        || !ref.layer->getFeatures(QgsFeatureRequest(ref.fid))
              .nextFeature(feature) || !feature.hasGeometry()) {
      callback_("vertex_delete_rejected", "{}");
      return;
    }
    Pick probe;
    probe.layer = ref.layer;
    probe.fid = ref.fid;
    probe.geometry = feature.geometry();
    probe.docId = ref.layer->customProperty(
        QStringLiteral("pwb/doc_id")).toString().toStdString();
    probe.featureId = resolver_
        ? resolver_(ref.layer, ref.fid)
        : std::to_string(static_cast<long long>(ref.fid));
    if (!minVerticesAfterDelete(probe, ref.vid)) {
      callback_("vertex_delete_rejected", "{}");
      return;
    }
  }
  clearHover();
  std::vector<QgsVectorLayer*> layers;
  std::vector<QgsFeatureId> touched;
  for (const VertexRef& ref : shared) {
    QgsVectorLayer* layer = ref.layer;
    if (layer == nullptr || !layer->isEditable()) continue;
    if (std::find(layers.begin(), layers.end(), layer) == layers.end()) {
      layers.push_back(layer);
      layer->beginEditCommand(QStringLiteral("Deleted vertex"));
    }
    QgsFeature feature;
    if (!layer->getFeatures(QgsFeatureRequest(ref.fid)).nextFeature(feature)
        || !feature.hasGeometry()) {
      continue;
    }
    const int nr = feature.geometry().vertexNrFromVertexId(ref.vid);
    if (nr < 0) continue;
    QgsGeometry geometry = feature.geometry();
    if (!geometry.deleteVertex(nr)) continue;
    layer->changeGeometry(ref.fid, geometry);
    touched.push_back(ref.fid);
  }
  // 每层收宏（拓扑开 → 自层散布旧位置）；同 CRS 其余会话层散布旧位置。
  QgsProject* canvas_project =
      canvas() != nullptr ? canvas()->project() : nullptr;
  const bool topological =
      canvas_project != nullptr && canvas_project->topologicalEditing();
  for (QgsVectorLayer* layer : layers) {
    if (topological) layer->addTopologicalPoints(QgsPoint(at.x(), at.y()));
    layer->endEditCommand();
  }
  {
    std::vector<QgsVectorLayer*> scatter_targets;
    if (candidate_layers_provider_) {
      for (QgsVectorLayer* layer : candidateLayers()) {
        if (layer == nullptr || !layer->isEditable()
            || std::find(layers.begin(), layers.end(), layer) != layers.end()
            || layer->geometryType() == Qgis::GeometryType::Point) {
          continue;
        }
        scatter_targets.push_back(layer);
      }
    }
    scatterTopologicalPoints(at, at, scatter_targets);
  }
  if (!touched.empty()) {
    emitGestureMulti(touched.size() > 1 ? "vertex_delete_multi"
                                        : "vertex_delete",
                     "Deleted vertex", layers, touched);
  } else {
    for (QgsVectorLayer* layer : layers) layer->destroyEditCommand();
  }
}

void PwbVertexTool::emitGestureMulti(
    const char* gesture, const char* undo_text,
    const std::vector<QgsVectorLayer*>& layers,
    const std::vector<QgsFeatureId>& fids) const {
  std::string docs = "[";
  for (size_t i = 0; i < layers.size(); ++i) {
    if (layers[i] == nullptr) continue;
    const QString doc = layers[i]->customProperty(
        QStringLiteral("pwb/doc_id")).toString();
    if (i > 0 && docs.size() > 1) docs += ",";
    docs += "\"" + doc.toStdString() + "\"";
  }
  docs += "]";
  // 宿主 id 去重保序（闭合环重复闭合点会命中多个 vertex）。
  std::vector<std::string> host_ids;
  for (const QgsFeatureId fid : fids) {
    for (QgsVectorLayer* layer : layers) {
      if (layer == nullptr) continue;
      bool belongs = false;
      QgsFeature probe;
      if (layer->getFeatures(QgsFeatureRequest(fid)).nextFeature(probe)) {
        belongs = probe.isValid();
      }
      if (!belongs) continue;
      std::string host_id = resolver_
          ? resolver_(layer, fid)
          : std::to_string(static_cast<long long>(fid));
      if (std::find(host_ids.begin(), host_ids.end(), host_id)
          != host_ids.end()) {
        continue;
      }
      host_ids.push_back(std::move(host_id));
    }
  }
  std::string features = "[";
  for (size_t i = 0; i < host_ids.size(); ++i) {
    if (i > 0) features += ",";
    features += "\"" + host_ids[i] + "\"";
  }
  features += "]";
  std::string primary;
  if (!layers.empty() && layers.front() != nullptr) {
    primary = layers.front()->customProperty(
        QStringLiteral("pwb/doc_id")).toString().toStdString();
  }
  callback_("edit_gesture",
            "{\"layer_doc_id\":\"" + primary + "\",\"layers\":" + docs
                + ",\"gesture\":\"" + gesture + "\",\"undo_text\":\""
                + undo_text + "\",\"features\":" + features + "}");
}

void PwbVertexTool::canvasPressEvent(QgsMapMouseEvent* e) {
  if (e->button() != Qt::LeftButton) return;
  if (QgsVectorLayer* layer = editLayer()) {
    const double mup = canvas()->mapSettings().mapUnitsPerPixel();
    std::vector<VertexRef> shared;
    if (allLayersScope()) {
      // M2 全部层档：跨候选层发现（同 CRS 过滤 + join_requested 入集）。
      shared = discoverAllLayers(e->mapPoint(), kTolerancePx * mup);
    } else {
      // v2 当前层档：层内拾取 → 1e-8 精确重合集 = 共享节点。
      const std::vector<VertexRef> picked =
          verticesNear(layer, e->mapPoint(), kTolerancePx * mup);
      if (!picked.empty()) {
        const QgsPointXY anchor = picked.front().pos;
        shared = verticesNear(layer, anchor, kSharedNodeEpsilon);
      }
    }
    if (shared.empty()) {
      callback_("pick_miss", "{}");
      return;
    }
    beginSharedDrag(shared.front().pos, std::move(shared));
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
    // v2：共享节点集整体落位（每层每手势恰一宏 + 拓扑点散布）。
    finishSharedDrag(p);
    return;
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
    const QgsFeatureId insert_fid = hover_.pick.fid;
    const int before = hover_.pick.geometry.vertexNrFromVertexId(at);
    clearHover();
    if (before < 0) return;
    layer->beginEditCommand(QStringLiteral("Added vertex"));
    QgsVectorLayerEditUtils utils(layer);
    if (!utils.insertVertex(p.x(), p.y(), hover_.pick.fid, before)) {
      layer->destroyEditCommand();
      return;
    }
    if (canvas()->project() != nullptr
        && canvas()->project()->topologicalEditing()) {
      layer->addTopologicalPoints(QgsPoint(p.x(), p.y()));
    }
    layer->endEditCommand();
    emitGestureMulti("vertex_insert", "Added vertex", {layer},
                     {insert_fid});
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
      // v2 联合删除（M1 当前层 + M2 全部层档跨层）：hover 顶点位置的
      // 同位置节点集（1e-8）整体删除；同要素闭合环重复点去重；
      // 任一要素低于最少顶点 → 整手势拒绝（原子语义）。
      if (hover_.has_vertex && hover_.pick.layer == layer
          && hover_.pick.geometry.constGet() != nullptr) {
        const QgsPoint hover_point =
            hover_.pick.geometry.constGet()->vertexAt(hover_.vertex);
        finishSharedDeleteAt(QgsPointXY(hover_point.x(), hover_point.y()));
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

PwbMoveTool::~PwbMoveTool() = default;

QgsVectorLayer* PwbMoveTool::editLayer() const {
  if (!edit_layer_provider_) return nullptr;
  QgsVectorLayer* layer = edit_layer_provider_();
  if (layer == nullptr || !layer->isEditable()) return nullptr;
  return layer;
}

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
  // M2（§4 移动复刻）：目标处于原生会话 → 平移直写缓冲。
  native_dragging_ = editLayer() != nullptr && pick.layer == editLayer();
  native_layer_ = pick.layer;
  native_fid_ = pick.fid;
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
  const bool native = native_dragging_;
  native_dragging_ = false;
  cancelDrag();
  if (native) {
    finishNativeMove(dx, dy);
    return;
  }
  std::string payload = "{" + basePayload(pick) +
                        ",\"dx\":" + QString::number(dx, 'g', 12).toStdString() +
                        ",\"dy\":" + QString::number(dy, 'g', 12).toStdString() + "}";
  callback_("feature_moved", payload);
}

void PwbMoveTool::finishNativeMove(double dx, double dy) {
  // M2：一宏「Moved feature」= 平移 + 避免重叠（裁掉与避让层的重叠，
  // 多部件保留最大块由 avoidIntersectionsV2 语义覆盖）+ 拓扑点散布。
  QgsVectorLayer* layer = native_layer_.data();
  if (layer == nullptr || !layer->isEditable()) return;
  const double mup = canvas()->mapSettings().mapUnitsPerPixel();
  if (std::hypot(dx, dy) < kTolerancePx * mup) return;  // 零位移抑制
  QgsFeature feature;
  if (!layer->getFeatures(QgsFeatureRequest(native_fid_))
           .nextFeature(feature) || !feature.hasGeometry()) {
    return;
  }
  QgsGeometry geometry = feature.geometry();
  if (geometry.translate(dx, dy) != Qgis::GeometryOperationResult::Success) {
    return;
  }
  QList<QgsVectorLayer*> avoid_layers;
  QgsProject* project = canvas() != nullptr ? canvas()->project() : nullptr;
  if (project != nullptr) {
    const Qgis::AvoidIntersectionsMode mode =
        project->avoidIntersectionsMode();
    if (mode == Qgis::AvoidIntersectionsMode::AvoidIntersectionsCurrentLayer) {
      avoid_layers.append(layer);
    } else if (mode
               == Qgis::AvoidIntersectionsMode::AvoidIntersectionsLayers) {
      for (QgsVectorLayer* avoid : project->avoidIntersectionsLayers()) {
        if (avoid != nullptr && avoid->isEditable()) avoid_layers.append(avoid);
      }
    }
  }
  if (!avoid_layers.isEmpty()) {
    QHash<QgsVectorLayer*, QSet<QgsFeatureId>> ignore;
    ignore.insert(layer, QSet<QgsFeatureId>{native_fid_});
    const Qgis::GeometryOperationResult avoid_result =
        geometry.avoidIntersectionsV2(avoid_layers, ignore);
    if (avoid_result == Qgis::GeometryOperationResult::Success
        || avoid_result
               == Qgis::GeometryOperationResult::GeometryTypeHasChanged) {
      if (geometry.isEmpty()) return;  // 全被裁空：放弃（保持原几何）
    }
    // 基底几何无效等失败：保持平移几何（诚实保留改动）。
  }
  layer->beginEditCommand(QStringLiteral("Moved feature"));
  layer->changeGeometry(native_fid_, geometry);
  if (project != nullptr && project->topologicalEditing()) {
    // 平移后几何的全部顶点散布进本层（自层拓扑闭合）。
    QgsVertexId vid;
    for (int nr = 0; nr < static_cast<int>(
             geometry.constGet() ? geometry.constGet()->vertexCount() : 0);
         ++nr) {
      if (geometry.vertexIdFromVertexNr(nr, vid) && vid.isValid()) {
        const QgsPoint p = geometry.constGet()->vertexAt(vid);
        layer->addTopologicalPoints(p);
      }
    }
  }
  layer->endEditCommand();
  emitGestureFrom(layer, "feature_move", "Moved feature", {native_fid_});
}

void PwbMoveTool::emitGestureFrom(
    QgsVectorLayer* layer, const char* gesture, const char* undo_text,
    const std::vector<QgsFeatureId>& fids) const {
  const QString doc = layer
      ? layer->customProperty(QStringLiteral("pwb/doc_id")).toString()
      : QString();
  std::string features = "[";
  for (size_t i = 0; i < fids.size(); ++i) {
    std::string host_id = resolver_ && layer
        ? resolver_(layer, fids[i])
        : std::to_string(static_cast<long long>(fids[i]));
    if (i > 0) features += ",";
    features += "\"" + host_id + "\"";
  }
  features += "]";
  callback_("edit_gesture",
            "{\"layer_doc_id\":\"" + doc.toStdString() + "\",\"layers\":[\""
                + doc.toStdString() + "\"],\"gesture\":\"" + gesture
                + "\",\"undo_text\":\"" + undo_text + "\",\"features\":"
                + features + "}");
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

void PwbSelectTool::onGeometryChanged(Qt::KeyboardModifiers modifiers) {
  QStringList ids;
  std::string docId;
  auto* vl = qobject_cast<QgsVectorLayer*>(canvas()->currentLayer());
  const QgsGeometry g = handler_->selectedGeometry();
  if (vl != nullptr && !g.isEmpty()) {
    docId = vl->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString();
    if (!docId.empty()) {
      const double mup = canvas()->mapSettings().mapUnitsPerPixel();
      const double tol = kTolerancePx * mup;
      QgsFeature f;
      if (g.type() == Qgis::GeometryType::Point) {
        const QgsPointXY p = g.asPoint();
        const QgsRectangle rect(p.x() - tol, p.y() - tol, p.x() + tol,
                                p.y() + tol);
        const QgsGeometry probe = QgsGeometry::fromPointXY(p);
        auto it = vl->getFeatures(QgsFeatureRequest(rect));
        while (it.nextFeature(f)) {
          if (f.hasGeometry() && f.geometry().distance(probe) <= tol)
            ids << QString::fromStdString(
                resolver_ ? resolver_(vl, f.id())
                          : std::to_string(static_cast<long long>(f.id())));
        }
      } else {
        auto it = vl->getFeatures(QgsFeatureRequest(g.boundingBox()));
        while (it.nextFeature(f)) {
          if (f.hasGeometry() && g.intersects(f.geometry()))
            ids << QString::fromStdString(
                resolver_ ? resolver_(vl, f.id())
                          : std::to_string(static_cast<long long>(f.id())));
        }
      }
    }
  }
  QStringList mods;
  if (modifiers & Qt::ControlModifier) mods << QStringLiteral("ctrl");
  if (modifiers & Qt::ShiftModifier) mods << QStringLiteral("shift");
  QStringList quoted;
  for (const QString& id : ids) quoted << "\"" + id + "\"";
  QStringList quotedMods;
  for (const QString& m : mods) quotedMods << "\"" + m + "\"";
  const std::string payload =
      std::string("{\"layer_doc_id\":\"") + docId + "\",\"feature_ids\":[" +
      quoted.join(QStringLiteral(",")).toStdString() + "],\"modifiers\":[" +
      quotedMods.join(QStringLiteral(",")).toStdString() + "]}";
  callback_("selection", payload);
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

