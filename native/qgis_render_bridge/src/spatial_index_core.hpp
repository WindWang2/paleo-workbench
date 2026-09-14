#pragma once

// Ticket 1（vector-perf-increment）：动态 R-Tree 顶点空间索引核。
//
// 纯数据结构层（不依赖 QGIS 类型）：STR 批量装载 + 运行期二次分裂插入 +
// feature 粒度墓碑删除 + 半径/矩形/KNN 查询。读多写少：std::shared_mutex
// 读共享锁（渲染/定位线程并发读无等待路径），写互斥（调用方保证 GUI 单写者）。
//
// 语义对齐 PwbVertexTool::verticesNear 线性扫描：项 = 每个几何顶点
// （含闭合环首尾重复点，不做去重——去重语义属于调用方）。

#include <cstddef>
#include <cstdint>
#include <shared_mutex>
#include <unordered_map>
#include <vector>

namespace pwb::qgis_render {

// 墓碑哨兵（feature_id 置此值的条目视为已删）。命名空间作用域 inline
// constexpr：MSVC 对类内 static constexpr int64_t 成员多处使用报 C2086。
inline constexpr int64_t kVertexTombstone = INT64_MIN;

// 索引项：一个顶点。vtype 保存 Qgis::VertexType 的整型值（曲线类型段点），
// 查询侧原样还原 QgsVertexId——与 vertexIdFromVertexNr 的输出逐字段一致。
struct VertexEntry {
  double x = 0.0;
  double y = 0.0;
  int64_t feature_id = 0;
  int32_t part = 0;
  int32_t ring = 0;
  int32_t vertex_nr = 0;
  int32_t vertex_type = 0;  // Qgis::VertexType
};

class SpatialIndexCore {
 public:
  // STR（Sort-Tile-Recursive）批量装载；entries 原样收编（可移动）。
  void rebuild(std::vector<VertexEntry> entries);
  // 运行期插入（二次分裂，逐层级联）。
  void insert(VertexEntry entry);
  // 删除该要素全部顶点项（墓碑语义：条目留位、查询跳过；rebuild 归零）。
  // 返回删除的项数。O(k)（k = 该要素顶点数）。
  std::size_t removeFeature(int64_t feature_id);
  std::size_t size() const;
  void clear();

  // 与 center 距离 <= radius 的全部顶点（hypot 精确判定，非 bbox 近似）。
  void radiusQuery(double cx, double cy, double radius,
                   std::vector<VertexEntry>& out) const;
  void rectQuery(double minx, double miny, double maxx, double maxy,
                 std::vector<VertexEntry>& out) const;
  // KNN k=1：max_distance 内最近顶点；无命中返回 false。
  bool nearest(double cx, double cy, double max_distance,
               VertexEntry& out) const;

  static constexpr int kMaxChildren = 16;

 private:
  struct Node {
    double bminx = 0.0, bminy = 0.0, bmaxx = 0.0, bmaxy = 0.0;
    int32_t count = 0;
    bool leaf = true;
    int32_t parent = -1;
    // 叶：entries_ 下标；枝：nodes_ 下标。
    int32_t children[kMaxChildren] = {};
  };

  // 墓碑哨兵（feature_id 置此值的条目视为已删）。
  static constexpr int64_t kTombstone = INT64_MIN;

  // item_idx：叶=entries_ 下标；枝=nodes_ 下标。满则携新项二次分裂并向上
  // 级联（递归）。
  void insertIntoNode(int32_t node_idx, int32_t item_idx);
  void enlargeAncestors(int32_t node_idx, double minx, double miny,
                        double maxx, double maxy);

  mutable std::shared_mutex mutex_;
  std::vector<Node> nodes_;
  std::vector<VertexEntry> entries_;
  // 每要素项位账（removeFeature 定位）；rebuild 重建。
  std::unordered_map<int64_t, std::vector<int32_t>> feature_slots_;
  std::size_t live_ = 0;
  int32_t root_ = -1;
};

}  // namespace pwb::qgis_render
