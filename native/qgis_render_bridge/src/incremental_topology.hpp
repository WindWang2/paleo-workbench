#pragma once

// Ticket 2（vector-perf-increment）：局部脏区拓扑增量计算引擎。
//
// 废除"每次 run 全图层全要素扫描"：以 (layerId, fid) → 几何指纹（WKB
// FNV-1a64）缓存刻画每要素版本；两次 run 之间指纹变化（含新增/删除）的
// 要素构成脏集，其外包矩形并集外扩 2×tolerance 为脏区；检查池限制为
// 脏要素 ∪ 脏区相交的干净邻居——（脏,任意）对重证，（干净,干净）对的
// 历史错误对象沿用（其检查实例随 retired 名单保活，fix 通道不断链）。
//
// gap 规则不可子集化（覆盖全局属性，子池产生边界假间隙）——仅享受
// "指纹无变化 → 缓存直返"快路径（00-D2 已记录）。

#include <cstdint>

#include <QHash>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QStringList>

#include <qgsgeometry.h>
#include <qgsrectangle.h>

namespace pwb::qgis_render {

// WKB 全量 FNV-1a64 指纹（内容敏感：重排环序/保面积滑动均不逃逸）。
quint64 topoFingerprint(const QgsGeometry& geometry);

struct TopoFidStamp {
  quint64 hash = 0;
  double minx = 0.0, miny = 0.0, maxx = 0.0, maxy = 0.0;
};

// 增量状态：上一次 run 的请求指纹与要素戳。layerId → fid → stamp。
class TopoIncrementalState {
 public:
  bool valid = false;
  QJsonObject config;
  QStringList layer_docs;
  QString map_crs_id;
  QHash<QString, QHash<qint64, TopoFidStamp>> stamps;

  void clear();
  bool sameRequest(const QJsonObject& cfg, const QStringList& docs,
                   const QString& crs_id) const;
};

struct TopoDiff {
  // layerId → 需重证的要素（指纹变化 ∪ 新增）。
  QHash<QString, QSet<qint64>> dirty;
  // 脏区并集（含被删要素的旧包围盒）；无脏时为空矩形。
  QgsRectangle dirty_box;
  bool empty() const { return dirty.isEmpty(); }
};

// 上次戳 vs 当前戳的差分。removed 要素的旧盒参与脏区（删除可在邻域
// 产生新 gap/重叠）。
TopoDiff topoDiff(const TopoIncrementalState& last,
                  const QHash<QString, QHash<qint64, TopoFidStamp>>& current);

// 脏区外扩：precision（配置位数）→ 容差，外扩 2×。
QgsRectangle expandDirtyBox(const QgsRectangle& box, double tolerance);

// 禁用开关（全量参照路径，测试用）。
bool incrementalTopologyDisabledByEnv();

}  // namespace pwb::qgis_render
