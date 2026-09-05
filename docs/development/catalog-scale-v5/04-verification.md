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

### 标准 benchmark（benchmarks/catalog_scale_benchmark.py，10k/50k，[measured]）
| operation | 10,000 ms | 50,000 ms |
|---|---|---|
| register_version | 5.3 | 17.0 |
| register_version_2nd | 4.7 | 17.1 |
| filter_by_tag | 3.5 | 18.8 |
| search_hit / miss | 2.1 / 1.5 | 8.7 / 8.4 |
| trash / restore_asset | 3.1 / 3.0 | 6.3 / 6.9 |
| add_tag / remove_tag / rename_tag | 0.3 / 0.1 / 0.2 | 0.3 / 0.2 / 0.2 |
| filter_by_type（旧 materialized search_assets API，即分页路径存在的原因） | 76.5 | 746.2 |

注：100k 分页查询另见上方 EXPLAIN 审计（page0 4.3ms / count 3.0ms / 聚合缓存命中 0ms）。

## 全量套件对照（既有基线问题，非本分支引入）
- 全量快速套件（`-m "not slow and not qgis and not opengl and not welllog_binding"`）在 ~52%（`tests/test_issues_825_829_846.py` → `test_issues_834_factor_race.py` 区域，渲染线程/ThreadPoolExecutor）出现一次 SIGSEGV；同区域 `tests/test_issues_823_828_830_833.py` 的 2 个失败（native status staleness）在 pristine `origin/main` 完全复现。
- `tests/e2e/test_harness_scenarios.py::test_scenario_c_coherence_on_active_volume`（RAM governor 软限）在 pristine main 同样失败。
- `tests/test_mapping_page.py` 的 6 failed + 1 error 在 pristine main 完全一致。
结论：全量套件在本机存在与 catalog 无关的既有不稳定（与 progress.md 的 full-suite triage 记录一致）；本分支 touched-area 套件 289 passed / 3 skipped。

## 已知限制（评审后接受并记录）
1. 分页模式跨页淘汰的选择恢复为尽力而为（stable-key 8192 LRU；排序/刷新后不可解析的行会被诚实收缩）。
2. 打开中的 batch_save 期间刷新分页视图会走文档回退（在调用线程物化，100k 下数秒）——罕见且保正确；数据页的刷新发生在登记完成后。
3. 实体成员集合 >5000 时诚实回退物化路径（不做分块谓词的无界展开）。
4. `count_assets(stage=…)` 与 stage/size/version 列排序在 100k 为 ~130-165ms（SQL 全集聚合/排序，显式用户动作）。
