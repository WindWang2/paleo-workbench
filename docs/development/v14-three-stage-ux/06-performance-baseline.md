# 06 — Performance Baseline (V14-THREE-STAGE-UX)

## 结构性断言（测试内嵌，platform.three_stage_flow）

- **stage 切换不重建 QGIS 工程/画布**：`check_stage_switch_and_layout`
  在 3 次 stage 循环前后抓 `findChild<QgsMapCanvas*>()` 指针断言不变
  （stages.py 契约「同一 QGIS project/canvas/图层权威贯穿全部阶段」的
  结构化验证）。仅可见性矩阵应用。
- **同一值 refresh 零信号**：true-change 判定（ui_stageflow.qt_widgets_smoke
  的 changed==1 断言）。
- **布局应用只动 visibility**：`applyStageVisibility` 全部走
  `set_dock_visible`/`set_panel_visible`/`setVisible`，无 resize/sizes 写。

## 已知性能特征（review 轮 2 确认，P2 记录不阻塞）

1. **每次 stage 切换两遍 readiness 全量评估**：CONV_27 构建下
   applyStageValue 的 refresh_readiness() 与随后的 stage_flow_->refresh()
   的 readiness seam 各跑一次 readiness_inputs()（遍历图层+线要素）。
   频度为用户点击级（非热路径）；修法（复用评估结果）登记为后续。
2. **snapshot.running_tasks 采样即弃**：无 job 状态变化 wiring 到
   refresh；任务中心有自己的 400ms 轮询（provider 只拷
   vector<JobSnapshot>，不碰 QSettings）。轻量刷新路径待 job 回调接线
   （不能直接接 400ms 轮询——会连带跑 readiness 全量）。
3. **QSettings sink 每调用解析**：仅用户操作（切阶段/面板开关）触发，
   低频；QSettings 自带缓存。
4. **任务中心 400ms 轮询**：不触碰 QSettings/工程文档；scheduler
   statuses 拷贝有界（max_workers=1+1）。

## 本机测量环境限制

- 本机为 reduced closure（CONV_27/SCIENCE/CLOSURE_MAPPING OFF）；
  ×100 循环计时在本机仅覆盖 reduced 路径。结构性断言（指针恒等、
  true-change、可见性-only）是机器无关的 gate；全闭合 Linux 机器的
  计时基线交由 CI/后续（known limitations 登记同一原因）。
