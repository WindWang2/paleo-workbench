// Ticket 1（vector-perf-increment）：SpatialIndexCore 实现。
//
// 布局：nodes_/entries_ 连续数组 + 下标寻址（缓存友好）。STR 装载产物为
// 满叶；运行期 insert 沿最扩张最小的子树下降，满节点二次分裂（Guttman
// pickSeeds/pickNext）逐层向上级联；删除走墓碑（结构不收缩，MBR 保持
// 有效超集，rebuild 归零——镜像整层重发/会话提交后整体重建摊平）。
//
// 注意：nodes_ 会增长（push_back 再分配）——所有逻辑只持下标，不跨
// push_back 持引用。

#include "spatial_index_core.hpp"

#include <algorithm>
#include <cmath>
#include <queue>
#include <tuple>
#include <utility>

namespace pwb::qgis_render {

namespace {

constexpr int kSplitItems = SpatialIndexCore::kMaxChildren + 1;  // 17
constexpr std::size_t kMinFill = 6;  // 17 项分裂两侧下限（≈ M/2-取整）

inline double minDist2(double px, double py, double bminx, double bminy,
                       double bmaxx, double bmaxy) {
  const double dx = px < bminx ? bminx - px : (px > bmaxx ? px - bmaxx : 0.0);
  const double dy = py < bminy ? bminy - py : (py > bmaxy ? py - bmaxy : 0.0);
  return dx * dx + dy * dy;
}

}  // namespace

void SpatialIndexCore::rebuild(std::vector<VertexEntry> entries) {
  std::unique_lock lock(mutex_);
  nodes_.clear();
  feature_slots_.clear();
  entries_ = std::move(entries);
  live_ = entries_.size();
  root_ = -1;
  if (entries_.empty()) return;
  const std::size_t n = entries_.size();

  // -- STR：x 中心切片 → 片内 y 中心排序 → 顺序满叶打包 ------------------
  const std::size_t leaf_target = (n + kMaxChildren - 1) / kMaxChildren;
  const std::size_t slices = std::max<std::size_t>(
      1, static_cast<std::size_t>(
             std::ceil(std::sqrt(static_cast<double>(leaf_target)))));
  std::vector<int32_t> order(n);
  for (std::size_t i = 0; i < n; ++i) order[i] = static_cast<int32_t>(i);
  std::sort(order.begin(), order.end(), [this](int32_t a, int32_t b) {
    return entries_[a].x < entries_[b].x;
  });
  std::vector<int32_t> packed;
  packed.reserve(n);
  const std::size_t slice_size = (n + slices - 1) / slices;
  for (std::size_t s = 0; s < slices; ++s) {
    const auto begin =
        order.begin() + static_cast<std::ptrdiff_t>(s * slice_size);
    const auto end = order.begin() + static_cast<std::ptrdiff_t>(
                                        std::min(n, (s + 1) * slice_size));
    std::sort(begin, end, [this](int32_t a, int32_t b) {
      return entries_[a].y < entries_[b].y;
    });
    packed.insert(packed.end(), begin, end);
  }

  // -- 逐层打包（每节点 ≤kMaxChildren 孩子），最后剩单节点为根 -----------
  std::vector<int32_t> level;
  for (std::size_t i = 0; i < n; i += kMaxChildren) {
    const std::size_t count = std::min<std::size_t>(kMaxChildren, n - i);
    Node leaf;
    leaf.leaf = true;
    leaf.count = static_cast<int32_t>(count);
    for (std::size_t k = 0; k < count; ++k) {
      const std::size_t e = packed[i + k];
      leaf.children[k] = static_cast<int32_t>(e);
      if (k == 0) {
        leaf.bminx = leaf.bmaxx = entries_[e].x;
        leaf.bminy = leaf.bmaxy = entries_[e].y;
      } else {
        leaf.bminx = std::min(leaf.bminx, entries_[e].x);
        leaf.bminy = std::min(leaf.bminy, entries_[e].y);
        leaf.bmaxx = std::max(leaf.bmaxx, entries_[e].x);
        leaf.bmaxy = std::max(leaf.bmaxy, entries_[e].y);
      }
    }
    nodes_.push_back(leaf);
    level.push_back(static_cast<int32_t>(nodes_.size() - 1));
  }
  while (level.size() > 1) {
    std::vector<int32_t> next;
    for (std::size_t i = 0; i < level.size(); i += kMaxChildren) {
      const std::size_t count =
          std::min<std::size_t>(kMaxChildren, level.size() - i);
      Node branch;
      branch.leaf = false;
      branch.count = static_cast<int32_t>(count);
      for (std::size_t k = 0; k < count; ++k) {
        const int32_t child = level[i + k];
        branch.children[k] = child;
        const Node& c = nodes_[child];
        if (k == 0) {
          branch.bminx = c.bminx;
          branch.bminy = c.bminy;
          branch.bmaxx = c.bmaxx;
          branch.bmaxy = c.bmaxy;
        } else {
          branch.bminx = std::min(branch.bminx, c.bminx);
          branch.bminy = std::min(branch.bminy, c.bminy);
          branch.bmaxx = std::max(branch.bmaxx, c.bmaxx);
          branch.bmaxy = std::max(branch.bmaxy, c.bmaxy);
        }
      }
      nodes_.push_back(branch);
      next.push_back(static_cast<int32_t>(nodes_.size() - 1));
    }
    level = std::move(next);
  }
  root_ = level[0];

  // 回填 parent（BFS；STR 产物无 parent 信息）。
  std::vector<int32_t> pending{root_};
  while (!pending.empty()) {
    const int32_t idx = pending.back();
    pending.pop_back();
    const Node& node = nodes_[idx];
    if (node.leaf) continue;
    for (int i = 0; i < node.count; ++i) {
      nodes_[node.children[i]].parent = idx;
      pending.push_back(node.children[i]);
    }
  }

  // 项位账。
  feature_slots_.reserve(live_ * 2);
  for (std::size_t i = 0; i < n; ++i) {
    feature_slots_[entries_[i].feature_id].push_back(static_cast<int32_t>(i));
  }
}

void SpatialIndexCore::insert(VertexEntry entry) {
  std::unique_lock lock(mutex_);
  if (root_ < 0) {
    // 空树：单叶起步。
    entries_.clear();
    entries_.push_back(std::move(entry));
    feature_slots_.clear();
    feature_slots_[entries_[0].feature_id].push_back(0);
    Node leaf;
    leaf.leaf = true;
    leaf.count = 1;
    leaf.children[0] = 0;
    leaf.bminx = leaf.bmaxx = entries_[0].x;
    leaf.bminy = leaf.bmaxy = entries_[0].y;
    nodes_.assign(1, leaf);
    root_ = 0;
    live_ = 1;
    return;
  }
  entries_.push_back(std::move(entry));
  const int32_t entry_idx = static_cast<int32_t>(entries_.size() - 1);
  feature_slots_[entries_[entry_idx].feature_id].push_back(entry_idx);
  ++live_;

  // 最小扩张下降到叶。
  int32_t node_idx = root_;
  while (!nodes_[node_idx].leaf) {
    const Node& node = nodes_[node_idx];
    double best = -1.0;
    int32_t best_child = node.children[0];
    for (int i = 0; i < node.count; ++i) {
      const Node& c = nodes_[node.children[i]];
      const double d = minDist2(entries_[entry_idx].x, entries_[entry_idx].y,
                                c.bminx, c.bminy, c.bmaxx, c.bmaxy);
      if (best_child < 0 || d < best) {
        best = d;
        best_child = node.children[i];
      }
    }
    node_idx = best_child;
  }
  insertIntoNode(node_idx, entry_idx);
}

void SpatialIndexCore::insertIntoNode(int32_t node_idx, int32_t item_idx) {
  if (nodes_[node_idx].count < kMaxChildren) {
    Node& node = nodes_[node_idx];
    node.children[node.count++] = item_idx;
    if (node.leaf) {
      const VertexEntry& e = entries_[item_idx];
      enlargeAncestors(node_idx, e.x, e.y, e.x, e.y);
    } else {
      const Node& c = nodes_[item_idx];
      nodes_[item_idx].parent = node_idx;
      enlargeAncestors(node_idx, c.bminx, c.bminy, c.bmaxx, c.bmaxy);
    }
    return;
  }
  // 满节点：携新项二次分裂，向上级联。
  const bool leaf = nodes_[node_idx].leaf;
  std::vector<int32_t> kids(nodes_[node_idx].children,
                            nodes_[node_idx].children + nodes_[node_idx].count);
  kids.push_back(item_idx);

  const auto item_mbr = [&](int32_t item, double& minx, double& miny,
                            double& maxx, double& maxy) {
    if (leaf) {
      minx = maxx = entries_[item].x;
      miny = maxy = entries_[item].y;
    } else {
      minx = nodes_[item].bminx;
      miny = nodes_[item].bminy;
      maxx = nodes_[item].bmaxx;
      maxy = nodes_[item].bmaxy;
    }
  };
  const auto group_mbr = [&](const std::vector<int32_t>& group, double& minx,
                             double& miny, double& maxx, double& maxy) {
    item_mbr(group.front(), minx, miny, maxx, maxy);
    for (std::size_t i = 1; i < group.size(); ++i) {
      double a, b, c, d;
      item_mbr(group[i], a, b, c, d);
      minx = std::min(minx, a);
      miny = std::min(miny, b);
      maxx = std::max(maxx, c);
      maxy = std::max(maxy, d);
    }
  };

  // pickSeeds：合并面积 - 自身面积 之和最大的一对。
  std::size_t seed_a = 0, seed_b = 1;
  double worst = -1.0;
  for (std::size_t i = 0; i < kids.size(); ++i) {
    for (std::size_t j = i + 1; j < kids.size(); ++j) {
      double aminx, aminy, amaxx, amaxy, bminx, bminy, bmaxx, bmaxy;
      item_mbr(kids[i], aminx, aminy, amaxx, amaxy);
      item_mbr(kids[j], bminx, bminy, bmaxx, bmaxy);
      const double enc = (std::max(amaxx, bmaxx) - std::min(aminx, bminx))
                       * (std::max(amaxy, bmaxy) - std::min(aminy, bminy));
      const double self = (amaxx - aminx) * (amaxy - aminy)
                        + (bmaxx - bminx) * (bmaxy - bminy);
      if (enc - self > worst) {
        worst = enc - self;
        seed_a = i;
        seed_b = j;
      }
    }
  }
  std::vector<int32_t> group_a{kids[seed_a]}, group_b{kids[seed_b]};
  std::vector<char> taken(kids.size(), 0);
  taken[seed_a] = taken[seed_b] = 1;
  // pickNext + 最小填充守卫。
  for (std::size_t i = 0; i < kids.size(); ++i) {
    if (taken[i]) continue;
    const std::size_t remaining_after =
        static_cast<std::size_t>(
            std::count(taken.begin(), taken.end(), 0)) - 1;
    if (group_a.size() + remaining_after <= kMinFill) {
      for (std::size_t k = i; k < kids.size(); ++k) {
        if (!taken[k]) group_a.push_back(kids[k]);
      }
      break;
    }
    if (group_b.size() + remaining_after <= kMinFill) {
      for (std::size_t k = i; k < kids.size(); ++k) {
        if (!taken[k]) group_b.push_back(kids[k]);
      }
      break;
    }
    double aminx, aminy, amaxx, amaxy, bminx, bminy, bmaxx, bmaxy;
    double kminx, kminy, kmaxx, kmaxy;
    group_mbr(group_a, aminx, aminy, amaxx, amaxy);
    group_mbr(group_b, bminx, bminy, bmaxx, bmaxy);
    item_mbr(kids[i], kminx, kminy, kmaxx, kmaxy);
    const double enc_a =
        (std::max(amaxx, kmaxx) - std::min(aminx, kminx))
            * (std::max(amaxy, kmaxy) - std::min(aminy, kminy))
        - (amaxx - aminx) * (amaxy - aminy);
    const double enc_b =
        (std::max(bmaxx, kmaxx) - std::min(bminx, kminx))
            * (std::max(bmaxy, kmaxy) - std::min(bminy, kminy))
        - (bmaxx - bminx) * (bmaxy - bminy);
    if (enc_a < enc_b
        || (enc_a == enc_b && group_a.size() <= group_b.size())) {
      group_a.push_back(kids[i]);
    } else {
      group_b.push_back(kids[i]);
    }
    taken[i] = 1;
  }

  // 原节点 ← A；新节点 ← B（parent 后统一接线）。
  const int32_t old_parent = nodes_[node_idx].parent;
  Node node_a;
  node_a.leaf = leaf;
  node_a.parent = old_parent;
  node_a.count = static_cast<int32_t>(group_a.size());
  std::copy(group_a.begin(), group_a.end(), node_a.children);
  group_mbr(group_a, node_a.bminx, node_a.bminy, node_a.bmaxx, node_a.bmaxy);
  nodes_[node_idx] = node_a;

  Node node_b;
  node_b.leaf = leaf;
  node_b.parent = old_parent;
  node_b.count = static_cast<int32_t>(group_b.size());
  std::copy(group_b.begin(), group_b.end(), node_b.children);
  group_mbr(group_b, node_b.bminx, node_b.bminy, node_b.bmaxx, node_b.bmaxy);
  nodes_.push_back(node_b);  // 此后旧引用全部失效（只再用下标）
  const int32_t new_idx = static_cast<int32_t>(nodes_.size() - 1);
  if (!leaf) {
    for (int i = 0; i < nodes_[new_idx].count; ++i) {
      nodes_[nodes_[new_idx].children[i]].parent = new_idx;
    }
  }

  if (node_idx == root_) {
    Node root;
    root.leaf = false;
    root.count = 2;
    root.children[0] = node_idx;
    root.children[1] = new_idx;
    root.bminx = std::min(nodes_[node_idx].bminx, nodes_[new_idx].bminx);
    root.bminy = std::min(nodes_[node_idx].bminy, nodes_[new_idx].bminy);
    root.bmaxx = std::max(nodes_[node_idx].bmaxx, nodes_[new_idx].bmaxx);
    root.bmaxy = std::max(nodes_[node_idx].bmaxy, nodes_[new_idx].bmaxy);
    nodes_.push_back(root);
    root_ = static_cast<int32_t>(nodes_.size() - 1);
    nodes_[node_idx].parent = root_;
    nodes_[new_idx].parent = root_;
    return;
  }
  insertIntoNode(old_parent, new_idx);  // 级联
}

void SpatialIndexCore::enlargeAncestors(int32_t node_idx, double minx,
                                        double miny, double maxx, double maxy) {
  int32_t idx = nodes_[node_idx].parent;
  while (idx >= 0) {
    Node& node = nodes_[idx];
    const bool changed = minx < node.bminx || miny < node.bminy
        || maxx > node.bmaxx || maxy > node.bmaxy;
    if (!changed) break;
    node.bminx = std::min(node.bminx, minx);
    node.bminy = std::min(node.bminy, miny);
    node.bmaxx = std::max(node.bmaxx, maxx);
    node.bmaxy = std::max(node.bmaxy, maxy);
    idx = node.parent;
  }
}

std::size_t SpatialIndexCore::removeFeature(int64_t feature_id) {
  std::unique_lock lock(mutex_);
  const auto it = feature_slots_.find(feature_id);
  if (it == feature_slots_.end()) return 0;
  std::size_t removed = 0;
  for (const int32_t slot : it->second) {
    if (slot < 0 || slot >= static_cast<int32_t>(entries_.size())) continue;
    if (entries_[slot].feature_id == kVertexTombstone) continue;
    entries_[slot].feature_id = kVertexTombstone;
    ++removed;
    --live_;
  }
  it->second.clear();
  return removed;
}

std::size_t SpatialIndexCore::size() const {
  std::shared_lock lock(mutex_);
  return live_;
}

void SpatialIndexCore::clear() {
  std::unique_lock lock(mutex_);
  nodes_.clear();
  entries_.clear();
  feature_slots_.clear();
  live_ = 0;
  root_ = -1;
}

void SpatialIndexCore::radiusQuery(double cx, double cy, double radius,
                                   std::vector<VertexEntry>& out) const {
  std::shared_lock lock(mutex_);
  if (root_ < 0 || nodes_.empty()) return;
  const double r2 = radius * radius;
  const double minx = cx - radius, miny = cy - radius;
  const double maxx = cx + radius, maxy = cy + radius;
  std::vector<int32_t> stack{root_};
  while (!stack.empty()) {
    const int32_t idx = stack.back();
    stack.pop_back();
    const Node& node = nodes_[idx];
    if (node.bmaxx < minx || node.bminx > maxx || node.bmaxy < miny
        || node.bminy > maxy) {
      continue;
    }
    if (node.leaf) {
      for (int i = 0; i < node.count; ++i) {
        const VertexEntry& e = entries_[node.children[i]];
        if (e.feature_id == kVertexTombstone) continue;
        const double dx = e.x - cx, dy = e.y - cy;
        if (dx * dx + dy * dy <= r2) out.push_back(e);
      }
    } else {
      for (int i = 0; i < node.count; ++i) stack.push_back(node.children[i]);
    }
  }
}

void SpatialIndexCore::rectQuery(double minx, double miny, double maxx,
                                 double maxy,
                                 std::vector<VertexEntry>& out) const {
  std::shared_lock lock(mutex_);
  if (root_ < 0 || nodes_.empty()) return;
  std::vector<int32_t> stack{root_};
  while (!stack.empty()) {
    const int32_t idx = stack.back();
    stack.pop_back();
    const Node& node = nodes_[idx];
    if (node.bmaxx < minx || node.bminx > maxx || node.bmaxy < miny
        || node.bminy > maxy) {
      continue;
    }
    if (node.leaf) {
      for (int i = 0; i < node.count; ++i) {
        const VertexEntry& e = entries_[node.children[i]];
        if (e.feature_id == kVertexTombstone) continue;
        if (e.x >= minx && e.x <= maxx && e.y >= miny && e.y <= maxy) {
          out.push_back(e);
        }
      }
    } else {
      for (int i = 0; i < node.count; ++i) stack.push_back(node.children[i]);
    }
  }
}

bool SpatialIndexCore::nearest(double cx, double cy, double max_distance,
                               VertexEntry& out) const {
  std::shared_lock lock(mutex_);
  if (root_ < 0 || nodes_.empty()) return false;
  const double max2 = max_distance * max_distance;
  using Item = std::pair<double, int32_t>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
  queue.emplace(minDist2(cx, cy, nodes_[root_].bminx, nodes_[root_].bminy,
                         nodes_[root_].bmaxx, nodes_[root_].bmaxy),
                root_);
  double best2 = max2;
  bool found = false;
  while (!queue.empty()) {
    const auto [dist2, idx] = queue.top();
    queue.pop();
    if (dist2 > best2) break;
    const Node& node = nodes_[idx];
    if (node.leaf) {
      for (int i = 0; i < node.count; ++i) {
        const VertexEntry& e = entries_[node.children[i]];
        if (e.feature_id == kVertexTombstone) continue;
        const double dx = e.x - cx, dy = e.y - cy;
        const double d2 = dx * dx + dy * dy;
        if (d2 <= best2) {
          best2 = d2;
          out = e;
          found = true;
        }
      }
    } else {
      for (int i = 0; i < node.count; ++i) {
        const Node& c = nodes_[node.children[i]];
        queue.emplace(minDist2(cx, cy, c.bminx, c.bminy, c.bmaxx, c.bmaxy),
                      node.children[i]);
      }
    }
  }
  return found;
}

}  // namespace pwb::qgis_render
