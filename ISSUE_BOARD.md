# ISSUE_BOARD — Auto-Issue Discovery

> **Created/Updated:** 2026-07-17  
> **Source:** Phase 1 full-workspace scan (pages · data objects · math · runtime)  
> **Lock rule:** 同时仅 1 个 Blocker/High 为 WIP  

| IssueID | 级别 | 归属 | 问题描述 | 预期目标 | 状态 |
|---------|------|------|----------|----------|------|
| ISS-DOM-01 | **Blocker** | 制备/全局 | 无独立 **WellTable**；井点仅 `sample_points` dict 列表，缺列语义(Hs/Ht/q/flag) | 定义 `WellTable`/`WellTableRow` 模型 + 与 FactorMapTask 双向适配 | **DONE** |
| ISS-DOM-02 | **Blocker** | 制备/编图 | **ConstraintLayers / BreakLines / DirectionLines** 未建模；engine fault 屏障未接线 | Pydantic 约束层模型；line_features 角色标注；IDW 传 fault_polylines | **DONE** |
| ISS-DOM-03 | **Blocker** | 编图 | **ContourDraft** 缺失；SurfaceWidget 未接入 workbench 修编流 | ContourDraft 对象 + 从 TrendSurface 生成等值线初稿 API | **DONE** |
| ISS-DOM-04 | High | 质检/全局 | **VersionSet** 缺失；专家定稿无法版本化 | VersionSet 挂 CompilationRun / paleomap 快照 | **DONE** |
| ISS-ALG-01 | **Blocker** | 制备/质检 | MAD 异常检测与砂地比 \(R_s=H_s/H_t\) 未实现 | `workflow/well_qc.py`：MAD z* + 砂地比约束写回 WellTable flags | **DONE** |
| ISS-ALG-02 | **Blocker** | 制备 | 方向加权趋势面未实现（仅各向同性 IDW） | `directional_trend_surface(points, theta, a, b, q, b_i)` | **DONE** |
| ISS-ALG-03 | High | 制备 | workbench 调用 IDW 时未传 **fault_polylines** | factor_interpolation 读取 BreakLines → engine | **DONE** |
| ISS-PREP-01 | High | 制备 | 制备页无 WellTable 表格编辑/异常高亮；插值在 GUI 线程 | Worker 线程 + 表格绑定 WellTable | **DONE** |
| ISS-MAP-01 | High | 编图 | 等值线初稿不可修编；factor_shelf 只展示不消费 grid | ContourDraft → 线要素/可编辑 isolines | **DONE** |
| ISS-MAP-02 | Medium | 编图 | `edit_history` 未稳定写入命令栈 | 关键 Command 提交时 append EditLog | **DONE** |
| ISS-QC-01 | Medium | 质检 | `run_basic_qc` 仅相带/层位两项，无点位 MAD/拓扑深度 | 扩展规则集挂钩 IssueLayer | TODO |
| ISS-QC-02 | Medium | 质检 | issues 非空间 **IssueLayer** | issues 带 geometry/ref 可图上定位 | TODO |
| ISS-PRED-01 | Medium | 测井/地震 | 预测任务仍以 MockPredictionAdapter 为主 | 真实 LAS/SEGY 特征链路加深 | TODO |
| ISS-VIZ-01 | Medium | 可视化 | Well-tie 无独立工作区 tab | 可选引擎 WellTieCanvas 页签 | TODO |
| ISS-KRIG-01 | Low | 制备 | UI「克里金」实为 SciPy linear | 标注 MVP 或接真实克里金 | TODO |
| ISS-ENV-01 | Medium | 全局 | 裸 `python -c` 无 PYTHONPATH 时 `import geoviz` 失败 | 文档/入口保证 editable install 或 path | TODO |
| ISS-E2E-01 | High | 全局 | 缺 WellTable→趋势面→等值线→定稿→QC 契约测试 | `test_e2e_factor_map_contract.py` | **DONE** |

### 已关闭（本会话前 backlog 巩固）

| IssueID | 说明 | 状态 |
|---------|------|------|
| T-SEIS-02 | Auto-Tie → SeismicView | DONE |
| T-MAP-04/06 | 隐藏层 hit-test + snap | DONE |
| T-MAP-05 | 演示草稿幂等 | DONE |
| T-PATH-01 | 路径 `..` confinement | DONE |
| T-UI-01 | 预览栏文案 | DONE |
| T-HOME-01 | 首页工作流证据 | DONE |

### 当前 WIP

- **ISS-QC-01** — 扩展 run_basic_qc 规则（下一步候选）

### 本轮完成证据

- 单因素主链 + E2E DONE
- Phase 26 baseline green: facade + async prep test fixes
- ISS-MAP-02: edit_history on command push/undo/redo
