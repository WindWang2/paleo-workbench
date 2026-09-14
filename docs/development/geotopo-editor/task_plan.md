# 任务计划：QGIS 原生地质拓扑矢量编辑与相带智能协同引擎（M1-M5）

- **Goal**：控制线动态构面（DCEL）、断-相协同截断、共边平滑重塑、地质拓扑规则守卫、多图层原子宏事务。
- **Worktree**：`../paleo-workbench-geotopo-editor` @ 分支 `feat/geotopo-editor`（基线 e7214566）
- **循环条件**：`docs_generated && tdd_all_green && memory_and_gil_audited && review_passed`（max_iterations=60）
- **硬约束**：≤3 subagents；`CMAKE_BUILD_PARALLEL_LEVEL=2` + Ninja；不破坏桥 ABI 与 POD 隔离。

## Phases

| # | Phase | Status | 产出 |
|---|-------|--------|------|
| 0 | 环境与侦察（worktree/venv/vendor 复用/基线编译） | complete | junction build→主仓 vendor；.venv（uv, py312） |
| 1 | 文档先行（5 份工程文档 + 计划文件） | in_progress | 00~04 五份文档 |
| 2 | Ticket 1：C++ DCEL 构面算核 | pending | geological_topology_core.{hpp,cpp} + geotopo 子模块 + tests |
| 3 | Ticket 2：断-相协同截断 | pending | PwbFaultCutTool + fault_cut_mirror_features + tests |
| 4 | Ticket 3：共边联动重塑 | pending | PwbBoundaryReshapeTool + reshape_shared_boundary + tests |
| 5 | Ticket 4：地质拓扑守卫 | pending | geological_invariants.py + facies_adjacency.json + tests |
| 6 | Ticket 5：原子宏事务 | pending | compound_macro + 补偿性提交回滚 + tests |
| 7 | 双轴审查 + 内存/GIL 审计 + 500+ 模糊测试 | complete | 双 FAIL→修复复验；1080 模糊全绿；报告落盘 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Git Bash `cmd //c` 内嵌引号被转义破坏，vcvars 调用静默失败（EXIT=1 空日志） | 1 | 改用 .scratch/build_bridge.bat 批处理封装 |
