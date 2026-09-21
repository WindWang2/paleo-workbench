# 01 — Open-issue ↔ main 状态交叉验证(stale reconciliation)

基准:origin/main @ 7bfe7585。验证方法:逐 issue 打开 main 代码现场核对修复 + 本地复现/测试证据。PR #1434 (a1423299) 声称的修复全部核实。

## 结论表(19 个 open issue)

| Issue | 主题 | 分类 | 证据 |
|---|---|---|---|
| #1339 | attr_str `or ""` 假值塌缩 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | evidence.cpp 各 resolver 站点改用 `attr_str_or_empty`(truthy 塌缩);py_text.hpp:250 注释引用 #1339;workflow_graph.contracts 在 ctest 236/236 中通过 |
| #1340 | rebuild dict 覆盖语义 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | graph.cpp:76-125 重写为 dict 视图语义(首键序+末值,`try_emplace`+覆盖)、setdefault 存在性检查(:113-117)、find_reuse_run 反向迭代去重视图(:227-229);注释引用 #1340 |
| #1341 | available_evidence 选择器绕过 parse | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | evidence.cpp:530-560 draft/prediction 全部改走 f-string → resolve_evidence(string) 路径;注释引用 #1341 |
| #1342 | D3 环成员论断错误 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | cpp-conversion-swarm-20/ledgers/25-decisions.md D3 段已改写:"对 ≥3 节点环,成员集合取决于 DFS 遍历起点……修正 #1342 指出的错误论断" |
| #1343 | 文本/迭代语义 punchlist | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | py_text.hpp:59(Unicode strip)、:68(repr 引号)、:172(str(None))、graph.cpp:407(dict 键迭代/TypeError 不吞);注释逐条引用 #1343 |
| #1344 | contracts_test 覆盖缺口 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | contracts_test.cpp 扩至 157 用例(含 dup-id/3环/rebuild×2/resolver-sentinel);ctest 通过 |
| #1345 | 公共面/卫生收敛 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | 三套 py_str/py_repr/truthy/strip 收敛到 workflow_graph/src/py_text.hpp(单份实现) |
| #1357 | curve_expr stod 溢出等 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | curve_expr.cpp:93(strtod→inf)、:528-549(Call(func=Attribute) 先拒绝 "function '?' not allowed");well_science.curve_ops 309 用例通过 |
| #1358 | polygonize 环闭合 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | polygonization.cpp:394-398 精确闭合(首尾 != 追加首点),注释引用 #1358;mapping_kernel.polygonization 通过 |
| #1385 | QGIS 镜像/导出性能 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | mirror_snapshot.cpp:396-411 doc_id 索引、:303 jsonFromVariant 直连;canvas_shim.cpp 多处 find_mirror_layer;export 只导 mirror 层 |
| #1388 | 表格大数据路径 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | asset_table_core.cpp:429-445 decorate-sort-undecorate;filter_index.cpp:216 QueryPlan 每查询一次;注释引用 #1388 |
| #1392 | 卫生项集合 | **FIXED_ON_MAIN_BUT_ISSUE_STALE** | map_chrome_painter.cpp:111,172(#1392 缓存);domain strip/lower_ascii 收敛 |
| #1427 | CI 2 核预算假设 | **FIXED_ON_MAIN_BUT_ISSUE_STALE**(CI 未复核,见下) | tests/conftest.py:15 `PALEO_BUDGET_CORES=8` 会话级;clamp/catalog_scale 归一化 |
| #1428 | i18n/集成回归 6 项 | **FIXED_ON_MAIN_BUT_ISSUE_STALE**(同上) | 断言对齐/os._exit(0) 等,PR 作者本地 51+3 通过 |
| #1429 | Windows access violation | **PARTIALLY_FIXED — 保持 open** | PR #1434 仅隔离崩溃文件为独立步;根因("产品析构序待 CI core dump")未解;Windows 环境本机不可复现 |
| #1430 | vendored QGIS moc 错配 | **FIXED_ON_MAIN_BUT_ISSUE_STALE**(CI 未复核) | CI yaml 去掉 CMAKE_PREFIX_PATH/PKG_CONFIG_PATH(vendored 只用系统 Qt) |
| #1431 | shapefile 无效几何误报 | **FIXED_ON_MAIN_BUT_ISSUE_STALE**(CI 未复核) | vector_adapter.py:46-74 GEOS canary 探测 |
| (新) | main CI nightly perf gate | 新发现 | `test_facies_atlas_bench.py::test_zoom_pan_sla` 20.09s vs SLA 16.0(run 35580075660) |
| (新) | harness data.ingest schema | 新发现(本地复现) | `data_lineage.py:84` 声明 created_entities=array;#1439 起 `ingest_plan.py:481` 为 int 计数 → 动作判 invalid → harness 动作失败(P2) |
| (新) | audit_ui 3 失败 | 新发现(本地复现) | `map_layer_properties.py` 英文错误文案("Invalid Classes JSON")/缺"工程管理"占位 vs 测试中文断言(2026-09-15 a3e73198 引入漂移;P3 测试对齐) |

## CI 状态事实

- main 的 push CI run(#1441/#1442 merge 后)排队 8-10h 未执行(runner 积压);PR #1439/#1440 分支 CI **failure**(legacy Python 面:audit_ui×3、v13_harness×2、visual_qa_v6 capture SIGSEGV、GL shader 噪声)。
- nightly Perf gate 与 Slow tests(schedule)在 main 失败:perf SLA 超标 1 项。
- 结论:**不能用"CI 绿"作为关闭 #1427/#1428/#1430/#1431 的证据**;采用代码核实 + PR 作者本地运行记录 + 本审计本地复现(可复现项)作为证据,并在关闭评论中如实说明。

## 处置

- #1339-#1345、#1357、#1358、#1385、#1388、#1392 → 证据评论 + 关闭(fixed by PR #1434 @ a1423299)。
- #1427、#1428、#1430、#1431 → 证据评论 + 关闭(修复合入 + 双重代码核实;CI 积压待后续 run 确认,评论注明)。
- #1429 → 保持 open(仅隔离,根因未修)。
