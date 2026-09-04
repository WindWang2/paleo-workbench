#include "edit_tools.hpp"

#include <cmath>
#include <limits>

#include <QKeyEvent>

#include <qgsabstractgeometry.h>
#include <qgsmapcanvas.h>
#include <qgsmapmouseevent.h>
#include <qgsmaptoolselectionhandler.h>
#include <qgspointlocator.h>
#include <qgsrubberband.h>
#include <qgssnappingutils.h>
#include <qgsvectorlayer.h>
#include <qgswkbtypes.h>

namespace pwb::qgis_render {

PwbEditPickTool::PwbEditPickTool(QgsMapCanvas* canvas, Callback callback,
                                 FeatureIdResolver resolver)
    : QgsMapTool(canvas),
      callback_(std::move(callback)),
      resolver_(std::move(resolver)) {
  // 拖动中 QgsMapCanvas::keyPressEvent 不转发工具而是发 keyPressed 信号
  // （mouseButtonDown 分支），Esc 取消必须走这条路径。
  QObject::connect(canvas, &QgsMapCanvas::keyPressed, canvas,
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

std::string PwbEditPickTool::basePayload(const Pick& pick) const {
  return std::string("\"layer_doc_id\":\"") + pick.docId +
         "\",\"feature_id\":\"" + pick.featureId + "\"";
}

// -- 顶点编辑 ---------------------------------------------------------------

void PwbVertexTool::canvasPressEvent(QgsMapMouseEvent* e) {
  if (e->button() != Qt::LeftButton) return;
  Pick pick;
  QgsVertexId vid;
  if (!pickFeature(e->mapPoint(), pick) || !nearestVertex(pick, e->mapPoint(), vid)) {
    callback_("pick_miss", "{}");
    return;
  }
  current_ = pick;
  vertex_id_ = vid;
  dragging_ = true;
  rubber_ = std::make_unique<QgsRubberBand>(canvas(), Qgis::GeometryType::Point);
  rubber_->setColor(QColor(255, 0, 0, 200));
  rubber_->setWidth(2);
  const QgsPoint p = pick.geometry.constGet()->vertexAt(vid);
  rubber_->addPoint(QgsPointXY(p.x(), p.y()));
}

void PwbVertexTool::canvasMoveEvent(QgsMapMouseEvent* e) {
  if (!dragging_) return;
  const QgsPointXY p = snapOrRaw(e->mapPoint());
  rubber_->reset(Qgis::GeometryType::Point);
  rubber_->addPoint(p);
}

void PwbVertexTool::canvasReleaseEvent(QgsMapMouseEvent* e) {
  if (!dragging_ || e->button() != Qt::LeftButton) return;
  const QgsPointXY p = snapOrRaw(e->mapPoint());
  const Pick pick = current_;
  const QgsVertexId vid = vertex_id_;
  cancelDrag();
  std::string payload = "{" + basePayload(pick) + ",\"path\":" +
                        vertexPathJson(pick.geometry.wkbType(), vid) +
                        ",\"x\":" + QString::number(p.x(), 'g', 12).toStdString() +
                        ",\"y\":" + QString::number(p.y(), 'g', 12).toStdString() + "}";
  callback_("vertex_moved", payload);
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

}  // namespace pwb::qgis_render

