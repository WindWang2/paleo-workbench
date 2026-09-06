# ADR 草案：工区数据目录的 10 万级扩展与生命周期 UX（catalog-scale-v5）

状态：随 PR 提交 · 范围：`catalog/**`、Data Explorer、导入管线

## 背景
仓库已完成 SQLite canonical store（#1027）、batch_save（#849-3/C38）、分页浏览原型（P0-B）与 dedup overlay（#1139）。本 Goal 将其推进为可长期管理 10 万级资产的专业工区数据管理：查询分页成为 service 契约、页取回离开 GUI 线程、Missing Source/Relink/Version/Lineage 形成产品闭环。

## 决策
1. **分页查询是 service 的只读门面，不是第二个查询引擎**（`search_assets_page`/`count_assets`/`catalog_aggregates`）。Index 可证明当前（非批内、revision 对齐）时由 SQLite 应答；批内或异常时由文档侧按同一行契约应答（(revision, serial, query) 单槽缓存），UI 永不自拼 SQL、永不全量物化。修复生产死路径：DataPage 曾读取不存在的 `service.index`，≥25k 分页模式从未生效。
2. **索引布局演进不走版本 bump**：新增的复合/部分索引全部连接时幂等创建（`idx_assets_live_name_id` 等）；并删除 planner 敌对的 `idx_assets_trashed`（#1043 同型陷阱，页取回 19.7→4.3ms@100k）。同时修复 `load_document` 将 index 布局版本与 canonical 语义版本做等值比较的潜在数据丢失路径（任何 bump 都会触发从陈旧 manifest 重建），改为版本地板（≥5），以守护测试钉死。
3. **FTS5 不采用**：100k 行最坏子串 LIKE 实测 16–17ms，规范化 name_search + 复合索引满足预算；FTS5 的 schema churn 与重建成本不成立。
4. **页取回 = 稀疏有界 LRU + 线程池 + epoch latest-only**：24 页上限、每页 500 行、MAX_INFLIGHT=4、data() 按需请求远页（滚动跳页取可见窗口）、顺序 prefetch 1 页；行数恒为 SQL 总数（滚动条诚实），未取行渲染"…"。
5. **Missing Source 是派生态**：stat-only 扫描（可协作取消）不写库——写标志位会成倍增加写放大并与跨进程 revision guard 冲突。Relink 仅限外部 RAW，身份证明必须来自记录在案的事实（sha256 > size+mtime 指纹，指纹在 link/relink 时写入 metadata）；其余一律拒绝（fail-closed，#1140 不变量不回退）；成功追加 `relink_history` 审计条目（canonical metadata 内，无第二权威）。managed 载荷缺失不可 relink（属损坏，重导入）。
6. **导入登记分块批提交（500/块）**：有界 dirty set 与崩溃窗口；协作式取消以块为粒度，取消后每个已完成块一致（重开测试钉死"恰为已登记数"）；进度上报真实登记数而非块边界。
7. **Version 工作台与 Lineage 浏览器是 service 门面上的薄 UI**：不可变契约（promote=复制新版本）不因 UI 而弱化；血缘展开只用单跳 `get_lineage`，全链行走仅存在于有硬上限的"展开至 RAW 根"动作；断链父版本（trash+purge）渲染 ⚠ 节点。
8. **工程对象视图不建第二权威**：地质对象浏览继续由 WorkArea entity 绑定 + Catalog 派生；有界实体成员集合映射为分块 `a.id IN (…)` 谓词（≤5000），超限诚实回退物化路径。
9. **保存的过滤器存 QSettings**（用户偏好，存查询文本而非数据 id），不新增工程文件格式。

## 后果
- 100k 资产：默认页取回 ~4.3ms（∝页大小）、深分页 ~7.5ms、计数 ~3ms、聚合 revision 缓存命中 0ms；GUI 线程不再执行页 SQL。
- 版本纪律：未来纯索引变更无需 bump；任何列级变更仍按既有 rebuild 机制处理，且 load_document 不再可能误判 healthy canonical store。
- 已知成本：stage/size/version 列排序页 ~130ms@100k（LEFT JOIN 全集聚合，显式用户动作）；`count_assets(stage=…)` ~165ms（UI 计数走缓存聚合）。
