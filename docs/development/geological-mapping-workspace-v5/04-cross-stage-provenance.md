# 04 — 跨阶段溯源与新鲜度

## 复用 Catalog（§32，不造第二 DB）

`MappingDependencyService`（`dependencies.py`）只做 domain 查询：
`resolve_version` / `resolve_run` / `list_versions`（CatalogPort 协议）。

## 版本钉住关系

| 成果 | 钉住来源 | 评估路径 |
|---|---|---|
| Phase1 解释草稿（`phase1_draft:<layer>`） | membership `source_version_id`（RAW 相图版本） | 钉住版本是否仍为资产当前版 |
| 单因素（`factor:<task>`） | `grid_artifact_version_id` → run → input versions | 输入版本货币性 + 输出是否被取代 |
| 综合解释（`integrated:<layer>`） | `compilation_input_set`（Compilation Input Set，§57） | 版本 + 指纹双轨 |
| MapProduct（`mapproduct:<id>`） | 组装 run inputs | 同上 |

## 状态机（§31/§32）

```
CURRENT ──上游新版本──▶ STALE ──重算钉新版──▶ CURRENT
   │                        │
   └──版本缺失/清理──▶ MISSING_INPUT
   └──自身有更新版──▶ SUPERSEDED
   无版本/run ──────▶ UNKNOWN
```

**过期绝不删除**：STALE 是标记与提示（阶段条徽标「N↑」、顶部
「N 项输入成果已过期」），旧图保留可查；重算产出新版本而非静默覆盖
（§85 有专门测试：P3 用 Factor v1 → P2 出 v2 → P3 标 STALE，成果保留）。

## Compilation Input Set（§57）

Phase 3 「选择证据版本」动作显式确定综合图的输入版本/指纹集合，存于
`MappingWorkspaceState.compilation_input_set`，随工程持久化并进入
MapProduct 组装溯源（`assemble_map_product` 复用 workflow.map_product）。
