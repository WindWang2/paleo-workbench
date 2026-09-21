# 05 — Test Plan

分层（全部本地 offscreen，Windows 本机为 gate）：

## T1 单元（`ui_stageflow_tests/ui_stageflow.core`）
- stage_layout_profile：三阶段 × 全 dock 键的期望矩阵（与 kStageGroupVisibility 投影一致）；
  未知 stage → 默认 profile + lenient。
- 持久化：dock overrides/split 保存→载入往返；版本栅栏（版本不符丢弃）；损坏行跳过。
- surface_state：全 SurfaceKind → title/hint 非空、StateToken 映射双信号（glyph+label）、
  未知输入 fail-closed。
- snapshot：provider nullopt → 诚实 Unknown（不猜）。

## T2 Qt smoke（`ui_stageflow.qt_widgets_smoke`，QT_QPA_PLATFORM=offscreen）
- StageFlowController：stage 变更 → bar set_current_stage 调用序、dock 可见性应用、
  快照字段联动；同值变更不发信号（真变化才通知）。
- mount_top_bar：一次成功、二次 false；bar reparent 后父对象销毁安全。

## T3 平台集成（`platform.three_stage_flow`，编 MainWindow）
- 启动后 command_registry 非空（≥N 条）、palette find() 命中 stage 命令。
- stage 切换 ×3 循环：StageDock/bar/快照三处一致；面板可见性按 profile 断言。
- 工程打开→stage 恢复（写 mapping_workspace.current_stage=stage3 的工程重开）。
- TaskCenter：注入 provider 后 snapshot 非空、job 完成→行消失。
- bank 信号：active_changed → MappingPage::update_state 被调（探针）。
- 双窗口：两个 MainWindow 各自 controller，selection 互不串扰。
- 生命周期：关窗时 workers shutdown 路径不崩（job running 中 close）。

## T4 visual QA 语义断言（ui_visualqa 场景 + offscreen 截图为人工 evidence）
12 状态：Stage1 normal / missing seismic / prediction running；Stage2 editing constraint /
factor running / stale；Stage3 integrated / factor reference selected；compact viewport；
no project；degraded QGIS；error。断言为语义性（部件存在性/可见性/状态文本），
不依赖像素 diff。

## T5 性能/结构断言（T3 内嵌计数器 + 独立 perf 用例）
- stage 切换 ×100：QgsProject 实例不变、canvas widget 指针不变（无重建）、
  耗时预算；horizon ×100；dock toggle ×100。
- 命令 find ×1000。
- resize storm（QResizeEvent ×200）无崩溃。
- 构造/析构 ×5 双窗口（泄漏冒烟 + registry 重注册安全）。

## T6 回归
- 既有 `platform.*` 全套 + `ui_shell.*` + `ui_map.qgis_smoke` + `ui_composite` smoke
  在改动后必须全绿（A/B 归因：若基线也失败则记录非本线引入）。

## A/B 纪律
本地失败疑似基线问题时：clean origin/main worktree 同机同配置同命令复现后再归因。
