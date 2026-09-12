# 07 — Staleness / Dependency Impact

## 1. 问题定义

```
A@v1 ─┐
B@v3 ─┼→ Run R → C@v5 → Run X → D@v2
M@v4 ─┘
```

- A current v1→v2 后：C@v5 基于旧输入（direct stale）；D@v2 传递 stale。
- 删除 A@v1：R 的该输入边断裂（lineage 残缺，但 run 保留历史事实）。
- D@v2 若 pinned：钉在旧输入 —— 已知晓，非错误。

## 2. 服务（`catalog/impact.py`）

```python
@dataclass
class StaleItem:
    version_id: str
    direct: bool                       # 直接基于过期输入 vs 传递
    via_run: str | None
    nearest_changed_ancestor: tuple[str, str, str] | None  # (ancestor_id, old, new)
    reason: str                        # 人可读
    pinned: bool                       # 豁免标记
    reproducible: bool                 # producing run 可重算

class ImpactService:
    def downstream_stale(self, *, changed_version_ids, scope=None) -> list[StaleItem]
    def upstream_impact(self, version_id) -> UpstreamImpact      # 改动/删除影响
    def delete_impact(self, version_id | asset_id) -> DeleteImpact
    def entity_staleness(self, entity_type, entity_id) -> list[StaleItem]
```

- 输入演进检测：对每个候选下游版本，取其祖先闭包中每个资产的
  current_version_id 对比 run 消费的历史版本 —— 不一致即 stale。
- `nearest_changed_ancestor`：沿 lineage 上溯遇到的第一个 (资产, 旧版,
  新版) 三元组 —— 直接回答"为什么过期"。
- `delete_impact`：受影响下游版本清单（live+trashed 分开）、断裂边数、
  级联建议（哪些应先重算/先 pin）。
- `entity_staleness`：井/调查 scope = 实体链接资产 ∪ 其下游闭包。

## 3. 语义规则

- **永不写回**：stale 永远即时计算（同 freshness 原则）。
- pinned 下游：报告但归类 `pinned-stale`，不计入"需重算"。
- trashed 输入：下游记 stale（reason=missing/trashed ancestor），除非该
  版本也 trashed。
- working copy live 的源版本：记 "recompute in progress" 提示。
- 无 producing run 的版本（手工导入 RAW）：不可重算（reproducible=False），
  影响报告必须区分。

## 4. 与既有 freshness 的关系

`workflow/freshness.py`（当前选择视角）保持不动，作为 UI "当前任务是否
最新"的既有入口。ImpactService 是通用图查询（任意版本演进/实体/删除），
复用 DependencyGraph 与其 revision 键控缓存；`FreshnessService` 后续可
委托 impact 计算内核（本 Goal 不强制改写 freshness 调用方）。

## 5. 规模

- 下游闭包 = SQL `idx_lineage_parent` 索引驱动的迭代扩展（每层一次批量
  IN 查询，复用 dependency graph 的批量构建器）。
- 实体 staleness 上限：井 scope 默认深度上限（可配置，默认全深度但节点
  数截断 + 报告截断标记）。
- 缓存：键 = (catalog_revision, mutation_serial, scope, changed 集指纹)，
  LRU ≤ 8。
