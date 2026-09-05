# Catalog Scale v5 — Target State（逐项验收清单）

规则：每项必须以本地可复现证据（测试/基准输出）勾选；禁止伪完成。性能 gate 优先“规模比率/复杂度”，绝对毫秒仅作观测记录。

## A. 查询层与索引（D1/D2）
- [x] A1 `DataCatalogService` 提供统一只读分页查询 API（filter 谓词 / 排序 / keyset 或 offset 分页 / 总数），UI 不再自行拼 SQL、不再直接持 `CatalogIndex`。
- [x] A2 分页查询不随总资产数全量物化 Python list（含 fallback 路径也有界/可解释）。
- [x] A3 服务级查询暴露 counts/facets（type/stage/tag/missing 等），供树徽标与 chip 计数。
- [x] A4 EXPLAIN QUERY PLAN 审计记录成文；为主查询模式补齐 composite/覆盖索引（至少：lineage parent 方向、paged 排序+过滤组合）。
- [x] A5 FTS5 vs LIKE/normalized-prefix 基准完成并记录决策；不引入 SQLite 之外的搜索存储。
- [x] A6 版本纪律复核：本分支的纯索引变更**有意不 bump** INDEX_SCHEMA_VERSION（连接时幂等 DDL 覆盖旧库），且修复了 load_document 版本等值比较的潜在数据丢失路径——其守护测试替代了 bump 回归。

## B. DataPage 虚拟化（D3）
- [x] B1 ≥25k（paged mode）页取回不在 GUI 线程同步执行 SQL；快速滚动/连续切 filter 不显示旧结果（latest-only）。
- [x] B2 页 cache 有明确上限；prefetch 前后页；请求可取消/失效。
- [x] B3 选择在翻页/刷新/排序后按 stable id 持久。
- [x] B4 model reset 最小化：分页路径插入/替换页不整表 reset；经典路径行为不回退。
- [x] B5 placeholder/loading 行语义清楚（不伪造数据行）。
- [x] B6 unmappable 智能视图回退路径仍可用且有测试。

## C. 批量导入（D4）
- [x] C1 导入管线有进度反馈（发现/登记阶段计数），UI 可见且不阻塞。
- [x] C2 导入可取消（协作式），取消后 catalog 状态一致（已批事务完整、无半登记）。
- [x] C3 导入收据：成功/跳过/失败明细可查（至少状态栏+详细报告入口）。
- [x] C4 保持单事务批提交（无 O(N²) 全量保存回归测试存在）。
- [x] C5 大文件不整体读入内存（流式 copy+hash 维持）。
- [x] C6 100k 文件规模 planning 测试（metadata-only/synthetic）不超比率预算。

## D. 检索/过滤 UX（D5）
- [x] D1 过滤条件以 chips 呈现，支持逐个移除 + clear all。
- [x] D2 total count + filtered count 在大规模下来自 query 层计数。
- [x] D3 saved filters 可保存/应用/删除（存 QSettings/user settings，不建新数据权威）。
- [x] D4 text/type/stage/tag/version-status/missing/external-managed/date/producer 谓词在 paged 模式下经 SQL 执行（不可映射视图才回退）。
- [x] D5 multi-selection 下批量操作可用。

## E. Version 工作台（D6）
- [x] E1 资产级版本 timeline（stage/checksum/run/parent/created）可查看。
- [x] E2 promote（不可变语义：复制新版本）/ trash / restore / open location 可用。
- [x] E3 版本 metadata 对比视图。
- [x] E4 clone/reprocess（create_derived/new version）入口存在。
- [x] E5 RAW 不可原地修改契约有回归测试守护（新增 UI 路径不破坏 service 层契约测试）。

## F. Tag 治理（D7）
- [x] F1 tag 名解析 O(1)（dict map），批量 tag 操作不再线性扫全部 tags。
- [x] F2 大选中批量 add/remove tag 不再 O(N×T)（单遍收集）。
- [x] F3 usage count / orphan cleanup / rename/merge 一致性可从 TagManager 使用。
- [x] F4 10w 资产 × 数百 tag 下 bulk tag 操作有比率测试。

## G. Lineage/Provenance（D8）
- [x] G1 独立 explorer：任一 OUTPUT/DERIVED 一步可见 producing run、参数、输入版本、上游 run、RAW 根；反向 RAW→products 可达。
- [x] G2 图 lazy expand（按需展开直接父子），不全量画 10w 节点。
- [x] G3 broken dependency（断链/missing 父版本）有可见警告。
- [x] G4 深链查询有界（depth/节点上限）且有比率测试。

## H. Missing Source / Relink（D9）
- [x] H1 缺失源状态可查询（service API），UI 可过滤+警告标识。
- [x] H2 relink 单个/批量：校验 size/mtime/sha256；身份一致才允许改引用，且产生可审计事件。
- [x] H3 fail-closed：内容不符绝不静默换绑（含 basename 相同场景）；引导走新 import/new version。
- [x] H4 relink 后 resolve_path/verify_integrity 一致性有回归测试。
- [x] H5 external basename 错绑禁止契约（#1140 既有）不回退。

## I. 工程对象视图（D10）
- [x] I1 按地质对象类型（Well/Horizon/Fault/Seismic/…）分组的浏览视图存在，数据来自 Catalog+domain binding，不建第二权威。
- [x] I2 对象详情含关联资产、provenance、missing 依赖、context action。

## J. 规模/一致性验收（D11）
- [x] J1 fast（2k/10k）分层规模测试进默认循环；heavy（50k/100k）显式 env 开关；可选 500k metadata-only。
- [x] J2 gate 以比率表达（首屏代价 ∝ page size 而非总数）。
- [x] J3 save/close/reopen/crash consistency 回归测试覆盖大目录。
- [x] J4 大操作（bulk tag/import/verify）可取消、有错误反馈、不冻结 UI（offscreen 测试证明）。
- [x] J5 无 100GB seismic 依赖。

## K. 交付
- [ ] K1 Review 1（correctness）/ Review 2（architecture）/ Review 3（UX/perf/adversarial）完成且问题当场修复。
- [ ] K2 原子 commits 链完整。
- [ ] K3 PR 到 main：背景/架构/功能/测试证据/性能证据/兼容性/风险/未做事项。
