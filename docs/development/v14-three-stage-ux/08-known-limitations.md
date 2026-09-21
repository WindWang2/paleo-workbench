# 08 — Known Limitations (V14-THREE-STAGE-UX)

如实声明本线交付边界与未覆盖面。

## 构建覆盖边界（本机 Windows reduced closure）

本机验证于 `PWB_BUILD_PLATFORM+DATA+MAPPING_KERNEL`（无 SCIENCE/
CONV_27/CLOSURE_MAPPING/CONV_16 闭合）。因此以下路径**本机未编译**：

1. `apply_stage_authority` 的 CONV_27 分支（applyStageValue 完整刷新链）；
   reduced 分支（set_mapping_stage 直写）已测。语义等价性由代码审查确认。
2. `window.constraint_panel`/`window.factor_stats` 的 stage 可见性应用
   （applyStageVisibility 的 window.* 分支仅编译空体）。
3. CLOSURE_MAPPING bank→MappingPage::update_state 接线（代码在
   PWB_WITH_CLOSURE_MAPPING 守卫内；全闭合装配后生效）。
4. restoreStageFromProject / horizon 读写的 DATA_INTEGRATION 分支。
5. selection bus 的 bind_project（restore 路径内）。

全部闭合路径依赖 Linux 全闭合构建验证（CI 域，本线声明 no-online-CI）。

## 功能边界（与三阶段目标的差距，如实）

- **Selection bus publish 喂入端未接**：总线实例化 + 3 个 sink 接线完成，
  但无生产 publish_* 调用者（地图井点击/地震游标属 layer-tree 线 seam）。
  「unwired SelectionBus」状态从「零实例」推进到「实例+sink 就绪」。
- **层位 combo 无候选列表**：install 只回填当前 target_horizon，不提供
  层序格架 options（依赖 stratigraphy sections 结构，跨线）。
- **命令面板无 map:* 工具命令**：本线注册 17 条 shell/导航/面板命令；
  map 工具族命令属 tool-policy 线已有 details provider 生态。
- **surface_state 词汇无生产消费者**：统一状态模型 + QSS 选择器已备，
  页面接入属后续迭代（当前页面继续用既有 Pwb* 组件直构）。

## Review P2 登记项（后续依据）

1. 双遍 readiness 评估（复用结果）；
2. running_tasks 轻量刷新路径（job 回调→部分刷新，避开 readiness）；
3. 层位候选列表接线（stratigraphy sections）；
4. sink/top_bar 的 QPointer 加固（无当前触发面）；
5. 启动序 stage profile 与 restore_window_layout 优先级声明；
6. nav_targets 由 ui_shell 暴露 id→index（消硬编码镜像）；
7. apply_horizon 的 read_only/write_granted 前置检查；
8. 测试 hermetic（QSettings 注入 QTemporaryDir INI）。

## 平台边界

- QGIS vendor SDK 复用主仓 Windows 构建；Linux SDK 不适用（该 cmake
  面向 Linux 路径）——Linux 构建走各自既有 preset。
- 本机 Qt 无 Pdf/Test 模块：PdfPreviewWidget 走 fallback 分支（守卫
  修复后诚实降级）；测试用自研 harness（无 QtTest 依赖）。
