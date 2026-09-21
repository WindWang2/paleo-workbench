# V14-CONSTRAINT-FACTOR — 05 测试计划

## A. 域/单元（closure_workflow_tests/factor_prepare_production_test.cpp）

### A1 kernel 正路径
- IDW：合成 8 点（synthetic seed 0, 地层厚度）→ grid_n=50 → complete；z 轴长度 2500；quality_metrics.range 与样本 min–max 一致（padding 外推容差）；指纹五元组落 parameters+grid_metadata；live store 命中。
- kriging：同上（variance_grid 非空、kriging_diagnostics 存在）。
- constrained_idw：≥3 井 + boundary 环 → 分辨率 clamp；diagnostics.duplicate_wells_dropped。
- 确定性：同输入两次 batch → z 逐位相等。

### A2 degenerate/negative（fail-closed）
- 0/1 有效点 → failed + Python validate 文本；2 点共线 → 正常（kriging ridge 回退路径不崩）。
- 全 NaN 值 → failed。
- duplicate_policy=error + 重复坐标 → failed（仅该任务，批次继续）。
- 方法=样条/方向趋势 → failed，错误文案含"未原生接入"；无 fake 网格。
- 约束 CRS 组不兼容 → failed。
- constrained <3 井 → failed（ValueError 文案）。
- boundary 自交/退化 → constrained 走 hull 回退或显式诊断（按核行为断言，不 silent）。

### A3 分类/复用
- 首跑 4 任务 dirty（MISSING_OUTPUT）→ 全计算；二跑同输入 → 全 CLEAN（reused，executed=0）。
- 改 1 任务 value → 仅该任务 dirty（DIRTY_VALUES），其余 CLEAN（"只重算受影响"任务级证据）。
- 改约束（break 线坐标）→ idw 任务 DIRTY_CONSTRAINTS；kriging 任务仍 CLEAN（constraints fp 不含 break？——按 Python：break 只进 idw/constrained 的 geometry fp；kriging 的 breaks=[]，故仍 CLEAN——断言此不对称即约束消费诚实性）。
- 改 grid_n → DIRTY_GEOMETRY；改 power → DIRTY_ALGORITHM。

### A4 commit
- 代数不匹配 → 全丢弃，live grid 按 fingerprint 条件逐出；project 不变。
- cancelled → 无部分 commit；非 reused 网格失效。
- created-defaults：空任务列表首跑 → 4 任务 bootstrap（非 failed 补丁）；live 已有任务时的迟到默认 → 全丢弃。
- 指纹复验：commit 前篡改 live 任务 sample_points → 该 item 丢弃。
- 定点替换：live 任务未知字段（自定义 key）在 commit 后保留（整体替换语义）。
- well_table_id/constraint_pins 落盘。

### A5 catalog
- 登记：run(running)→INTERMEDIATE 版本→complete；task.grid_artifact_version_id 回填；list_runs 可见 operation=factor_map、domain_task_id。
- catalog=null → 降级（无 version_id，registration_errors 空，任务仍 complete）。
- 登记抛异常 → run failed + error 参数；任务补丁保留。
- 重复 commit（同 fingerprint 重跑）→ 不重复登记（reused 路径不登记）。

### A6 contour upsert/map-apply
- 空 paleomap_documents → 新建文档 + line features（role=contour、level、closed）；二跑 → 保 draft id、文档 feature 替换不叠加；linked_map_document_id 复用。

### A7 持久化/重开
- FileCatalogRepository 落盘 → 重开 → runs/versions 完整（reopen 断言）。
- save/reopen 工程：任务 JSON 与 catalog 版本一致（grid_artifact_version_id 可解析）。

## B. 平台级（tests/cpp/platform/test_closure_mapping.cpp 增补）
- 装配后 PreparationPage 点生成（无 Qt 交互：直接调 seam 函数）→ 任务 complete、contour 可提取、paleomap_documents 有 contour features。
- 切项目守卫（既有测试保持绿）。

## C. parity/oracle
- mapping_kernel/factor_host/ui_workers 既有 oracle 全绿（回归）。
- Python 冻结参考对照：synthetic points、指纹 canonical JSON、nice levels（既有 oracle 覆盖）；本线新增 envelope→parameters 键序一致性用例（对拍 factor_grid_io 既有 fixture）。

## D. 性能（06 基线文档记录）
- 100/1000 井 × grid_n {50,100,200} × {idw,kriging}；5/10/20 任务队列；半途取消；重开缓存命中。阈值断言宽松（结构性：完成时间 < 参考值×3），精确数字进 06。

## E. review 门
- 两类独立 review（architecture/correctness + adversarial/performance/lifecycle）；P0/P1 清零后 PR。
