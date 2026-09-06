# Catalog Scale v5 — Review Rounds（三轮独立审查与处置）

审查对象：`049423ab..HEAD`（feat/catalog-scale-v5）。每轮由独立审查代理执行，逐条以 file:line 求证后分类处置。修复全部当场落地并补测试。

## Review 1 — Correctness（数据一致性/错误处理/取消/并发/退化输入）
确认无误的部分：journal `add_tags` 回滚、relink 回滚、分块取消一致性、`_query_index_if_current` 门、空输入/键集游标/Unicode、回退行与 SQL 行契约 parity。
确认缺陷与处置：
1. **P1 游标投毒**：旧查询的在途页把 keyset 游标写回新查询的游标表 → 新结果静默跳行。已修：provider 引入 query generation，写入仅在代数匹配时发生（`paged_asset_model.page_with`）。
2. **P1 饱和丢页永不重试**：MAX_INFLIGHT 满时 data() 的请求被丢弃且无重画。已修：demand 队列 + 页完成时按容量重发。
3. **P1 瞬时 SQLite 错误被当作空页**：`_safe` 吞错导致空页 → 模型误钳制 total（且无 Qt 信号）。已修：空页先有界重试（≤3），真正的收缩以 beginResetModel/endResetModel 包裹（Qt 契约）；`_on_page_failed` 同样重试。
4. P2 分块导入的块提交失败清空全部登记映射 → 只回退当前块。
5. P2 回退排序 NULL 顺序与 SQLite（ASC NULLs first）不一致 → 已对齐。
6. P2 relink 对话框取消是死管道（未传入 scan/循环）→ 已传入，关闭即停；在途项由 3s 有界 join 覆盖。
7. P2 lineage 循环守卫只覆盖未解析父 → 已覆盖已解析父与下游节点。
8. P2 分页模式下文件叶自动选中失效 → 经 stable-key 行索引定位。
9. P2 load_document 版本地板无上界 → 接受并记录：未来版本必须 bump 文档 schema（另有校验），从陈旧 manifest 重建是更坏的失败面（db.py 注释与守护测试说明）。

## Review 2 — Architecture（第二权威/边界/重复/合并风险）
无 P1。三个 P2：
1. decisions.md D-11 与实现矛盾（危险方向）→ 已重写为修订版（见 02-decisions.md）。
2. `sources._probe_path` 与 `resolve_path` 语义分歧欠文档（扫描只查第一梯队，工程重定位后可能误报缺失——上界语义）→ 已在两处补充说明。
3. UI 直读 `service.document.asset_tags` → 新增 `DataCatalogService.tag_ids_for_asset()`，新调用点走服务 API。
其余确认干净：无第二持久权威；对话框全部只走 service 门面；无全局 token 改动；合并风险低。

## Review 3 — UX / Performance / Adversarial
核心发现是同一根因的整合缺口：分页行是 `SqlCatalogAssetRef`，下游却按 legacy 类型分支——paged 死路径修复后暴露。处置：
1. **P0 右键菜单在分页行必崩**（export 探针读 `asset.format`）→ ref 携带 format/stage/managed 等事实字段。
2. **P1 版本工作台/血缘/提升等在分页行永久禁用**（`versions=[]`）→ `_current_version_id_for` 识别 ref 的 `current_version_id`。
3. **P1 移出/还原/批量标签/批量校验/预览对 ref 静默无效** → 控制器加 ref 分支（trash/bulk tag/restore/bridged map/伴生重构），全部走 service。
4. **P1 提升在 GUI 线程复制+哈希任意大文件** → OwnedWorkerJob + 完成后刷新。
5. **P1 选择全部卡顿/批量操作范围错位** → 单次解析；范围问题由 ref 支持后消除（操作只作用于可解析行）。
6. P2 每次变更后冷聚合 ~389ms 冻结 → `cached_catalog_aggregates` 热路径直读 + 冷路径后台计算，徽标到货后刷新。
7. P2 分页早退跳过树工程区/回收站徽标 + 10 万行重选循环 → 已补/已跳过。
8. P2 已存过滤器文本被覆盖、chips 与搜索框失同步 → `apply_saved_filter` + `set_search_text_silent` 单向同步。
9. P2 列设置对分页模型无效 → set_column_keys 双模型。
其余（文档化接受）：跨淘汰的选择恢复为尽力而为（stable-key LRU）；批内回退物化罕见且保正确；>5000 实体集合诚实回退；map 区域全量套件 SIGSEGV 与 test_mapping_page 失败在 pristine main 复现，属既有基线问题。

## 回归
修复后 touched-area 套件（21 个文件，含全部新测试）：**289 passed, 3 skipped**；另有 e2e harness 一项（`test_scenario_c_coherence_on_active_volume`）在 pristine main 同样失败（RAM governor 环境问题），记录为既有基线失败。
