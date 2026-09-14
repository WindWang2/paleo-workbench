// Ticket 2（vector-perf-increment）：TopoIncrementalState / topoDiff 实现。

#include "incremental_topology.hpp"

#include <QByteArray>
#include <qgsvectorlayer.h>

namespace pwb::qgis_render {

namespace {

constexpr quint64 kFnvOffset = 1469598103934665603ULL;
constexpr quint64 kFnvPrime = 1099511628211ULL;

quint64 fnv1a64(const QByteArray& bytes) {
  quint64 hash = kFnvOffset;
  const char* data = bytes.constData();
  const qsizetype size = bytes.size();
  for (qsizetype i = 0; i < size; ++i) {
    hash ^= static_cast<quint64>(static_cast<unsigned char>(data[i]));
    hash *= kFnvPrime;
  }
  return hash;
}

}  // namespace

quint64 topoFingerprint(const QgsGeometry& geometry) {
  if (geometry.isNull() || geometry.isEmpty()) return 0;
  return fnv1a64(geometry.asWkb());
}

void TopoIncrementalState::clear() {
  valid = false;
  config = QJsonObject();
  layer_docs.clear();
  map_crs_id.clear();
  stamps.clear();
}

bool TopoIncrementalState::sameRequest(const QJsonObject& cfg,
                                       const QStringList& docs,
                                       const QString& crs_id) const {
  return valid && config == cfg && layer_docs == docs && map_crs_id == crs_id;
}

TopoDiff topoDiff(
    const TopoIncrementalState& last,
    const QHash<QString, QHash<qint64, TopoFidStamp>>& current) {
  TopoDiff diff;
  auto grow_box = [&diff](const TopoFidStamp& stamp) {
    if (stamp.maxx < stamp.minx) return;  // 空戳
    if (diff.dirty_box.isNull()) {
      diff.dirty_box = QgsRectangle(stamp.minx, stamp.miny, stamp.maxx,
                                     stamp.maxy);
    } else {
      diff.dirty_box.combineExtentWith(
          QgsRectangle(stamp.minx, stamp.miny, stamp.maxx, stamp.maxy));
    }
  };
  // 现存要素：指纹变化 → 脏。
  for (auto layer_it = current.constBegin(); layer_it != current.constEnd();
       ++layer_it) {
    const QString& layer_id = layer_it.key();
    const auto old_layer = last.stamps.constFind(layer_id);
    for (auto fid_it = layer_it.value().constBegin();
         fid_it != layer_it.value().constEnd(); ++fid_it) {
      const qint64 fid = fid_it.key();
      const TopoFidStamp& now = fid_it.value();
      bool is_dirty = true;
      if (old_layer != last.stamps.constEnd()) {
        const auto old_stamp = old_layer.value().constFind(fid);
        if (old_stamp != old_layer.value().constEnd()
            && old_stamp.value().hash == now.hash) {
          is_dirty = false;
        }
      }
      if (is_dirty) {
        diff.dirty[layer_id].insert(fid);
        grow_box(now);
      }
    }
  }
  // 被删要素：旧盒参与脏区（删除可在邻域翻开新缝/新叠）。
  for (auto layer_it = last.stamps.constBegin();
       layer_it != last.stamps.constEnd(); ++layer_it) {
    const QString& layer_id = layer_it.key();
    const auto now_layer = current.constFind(layer_id);
    for (auto fid_it = layer_it.value().constBegin();
         fid_it != layer_it.value().constEnd(); ++fid_it) {
      const bool still_there =
          now_layer != current.constEnd()
          && now_layer.value().contains(fid_it.key());
      if (!still_there) {
        grow_box(fid_it.value());
      }
    }
  }
  return diff;
}

QgsRectangle expandDirtyBox(const QgsRectangle& box, double tolerance) {
  if (box.isNull() || box.isEmpty()) return box;
  // 手势编辑影响域：外包矩形外扩 2×tolerance（设计文档 02 §2.2）。
  return QgsRectangle(box.xMinimum() - 2.0 * tolerance,
                       box.yMinimum() - 2.0 * tolerance,
                       box.xMaximum() + 2.0 * tolerance,
                       box.yMaximum() + 2.0 * tolerance);
}

bool incrementalTopologyDisabledByEnv() {
  return qEnvironmentVariableIsSet("PWB_DISABLE_INCREMENTAL_TOPO")
      && QString::fromLocal8Bit(qgetenv("PWB_DISABLE_INCREMENTAL_TOPO"))
             != QStringLiteral("0");
}

}  // namespace pwb::qgis_render
