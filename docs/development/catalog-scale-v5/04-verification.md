# Catalog Scale v5 — Verification Ledger

基准环境：Linux 6.18 LTS，conda `paleo312`（py3.12），offscreen。所有数字为 [measured]，min-of-3。

## Baseline（改动前 origin/main 049423ab）
- `pytest tests/test_catalog_service.py tests/test_paged_catalog_mode.py tests/test_catalog_scale.py tests/test_data_asset_table.py` → **98 passed** (13.95s)。
- `tests/test_catalog_crash_safety.py` → 23 passed（用于判定后续失败为分支引入）。

## 100k 查询审计（scripts/audit_catalog_query_plans.py，真实 DataCatalogService 构建）

### 第一轮（D1 后、索引修复前）
发现：
1. **`idx_assets_trashed` 劫持 planner**：默认页查询 `SEARCH a USING idx_assets_trashed` + `TEMP B-TREE FOR ORDER BY`（#1043 同型陷阱：近全表匹配索引被优先选择）。
2. `catalog_aggregates()` 389ms（4 组 group-by）且树徽标每次刷新都重算。
3. order stage/size ~125ms/页（LEFT JOIN 全集排序）。

### 第二轮（连接时 DROP idx_assets_trashed + partial 覆盖索引 idx_assets_live_name_id 后）
| 操作 | 第一轮 | 第二轮 |
|---|---|---|
| page0 (500, name) | 19.69 ms | **4.31 ms** |
| deep offset 50k | 57.32 ms | **7.45 ms** |
| count all | 2.59 ms | 3.01 ms |
| catalog_aggregates | 389.31 ms | **0.00 ms**（revision 键控缓存命中） |
| text filter count | 16.58 ms | 17.71 ms |
| tag filter count | 37.36 ms | **6.85 ms** |
| stage filter count | 170.63 ms | 164.50 ms（已知：count 经 versions 子查询，UI 径用缓存 aggregates） |
| order_by modified page | 20.76 ms | **4.09 ms** |
| order_by type page | 21.12 ms | **4.03 ms** |
| order_by stage/size page | ~125 ms | ~130 ms（可选项排序，全集聚合；见 Known costs） |

EXPLAIN（第二轮）：默认页/文本过滤/modified 序均 `SCAN a USING <order-satisfying index>`，无 TEMP B-TREE；lineage 双向均索引覆盖。

### FTS5 决策（A5）
最坏情况（中段子串 `LIKE '%00042%'`）在 100k 行 = **16-17ms**；前缀/规范化路径均 ≤17ms。FTS5 引入 index schema churn + 全量重建 + token 维护，收益不成立。**决策：不启用 FTS5**，维持 `name_search`(NFKC+casefold) + LIKE + 复合索引方案。

### Known costs（记录，不阻塞）
- `order_by stage/size/version` 页取回 ~130ms@100k（LEFT JOIN 全集排序）；用户显式排序场景。
- `count_assets(stage=…)` ~165ms@100k；UI 计数走缓存 aggregates 不受影响。
- 深层 OFFSET 分页 7.45ms@50k-offset（keyset 路径在 provider 中默认使用）。

## 测试记录
- `tests/test_catalog_paged_query.py` — 14 passed（含 load_document 版本地板守护、mid-batch fallback、行形状 parity）。
- `tests/test_catalog_tag_scale.py` — 4 passed + 1 skipped（默认 N=64 低于噪声底跳过；`CATALOG_SCALE_N=2000` 启用 ratio gate）。

## 崩溃/一致性回归
- `tests/test_catalog_crash_safety.py` 23 passed（在 db.py 索引修复 + load_document 地板修复后）。

## 后续里程碑实测（全部 [measured]，conda paleo312，offscreen）

### D3 异步分页模型
- `tests/test_paged_catalog_mode.py` 14 passed（含 100k 行 fixture：page<50ms、count<100ms、lazy paging 改为 qtbot.waitUntil 异步契约）。
- `tests/test_paged_async_model.py` 6 passed：data()-驱动页取回（滚动跳页取可见窗口）、filter 快速切换 latest-only、LRU 有界、回收站只列已删、**DataPage 经 service 门面进入分页模式**（修复 `service.index` 死路径）。
- UI 回归：test_data_asset_table/test_data_page/test_data_manager_ui2/test_asset_table_model_differential/test_datapage_stress/test_catalog_paged_query → 158 passed。

### D9 Missing/Relink
- `tests/test_catalog_relink.py` 9 passed（指纹/摘要两级身份证明、basename 错绑拒绝、size-only 拒绝、managed 拒绝、save 失败精确回滚、relink_history 重开仍在）。
- `tests/test_relink_dialog_ui.py` 3 passed（worker 扫描渲染、目录重定向拒绝陌生人、同文件目录重定向成功后重扫为空）。
- 相关回归 152 passed。

### D4 导入管线
- `tests/test_import_registration_flow.py` 3 passed：分块取消后 reopen 目录恰含已登记资产（无半登记）、进度=真实登记数、收据文本。
- 导入相关回归 105 passed。

### D5/D10 检索/对象视图
- `tests/test_filter_chips_bar.py` 3 passed：chips 渲染/移除、保存过滤器 QSettings 往返、**实体视图留在 SQL 分页路径**（有界集合 → chunked IN；超限诚实回退）。

### D6/D8 工作台/浏览器
- `tests/test_version_workbench_dialog_ui.py` 5 passed；`tests/test_lineage_explorer_dialog_ui.py` 10 passed（断链节点、子节点上限、深度上限、循环引用、定位信号）。
- 合并回归（context menu/data_page/relink/paged async）119 passed。

### D11 规模/崩溃分层
- fast：`tests/test_catalog_scale_v5.py` 6 passed + 2 heavy-skipped（默认 N=2k，4x 增长下页取回 sub-linear；save/reopen linear；连续切 filter 有界）。
- heavy（PALEO_CATALOG_SCALE_HEAVY=1，本地实测）：50k/100k 页取回/计数/聚合/深偏移预算 → **2 passed (11.49s)**。
- 崩溃：`tests/test_crash_scale.py` 2 passed（2k 资产批提交中 SIGKILL：mid-tx 回滚为 0、post-commit 全保留；重开后查询面完好、工程可再写）。

### FTS5 决策（A5 最终）
最坏子串 LIKE 16-17ms@100k（见 100k 审计），维持 normalized LIKE + 复合索引方案，不引入 FTS5。
