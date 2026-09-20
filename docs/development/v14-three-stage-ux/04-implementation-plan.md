# 04 — Implementation Plan

里程碑顺序（每步可独立编译、可测）：

## M1 构建通道 + build 修复（已完成）
- [x] 资源门 wrapper（MSVC env + gate -j2 + MinFreeGiB 调低到 1，不绕锁）
- [x] configure 修复：UI-14-IMPLY 补 MAPPING_KERNEL；well_crosswell 挂载补 WLE 守卫；
      显式 CMAKE_PREFIX_PATH(Qt 6.8) + PWB_QGIS_DEPS_PREFIX(vcpkg)
- [x] 后台构建 pwb-platform + 核心 platform 测试

## M2 `libs/ui_stageflow` 新库
- [ ] `stage_presentation.{hpp,cpp}`：snapshot、StageLayoutProfile 纯函数、
      KV 持久化 sink（load/save dock overrides + split）、版本栅栏
- [ ] `surface_state.{hpp,cpp}`：SurfaceKind/SurfaceState/派生函数 + StateToken 桥
- [ ] Qt shell：`StageFlowController`（QObject：订阅、快照、布局应用、bar 同步）
- [ ] CMake + 根挂载一行 + `ui_stageflow_tests`（core 单测 + qt smoke）

## M3 ui_shell / ui_composite 小改（additive）
- [ ] `WorkstationFrame::mount_top_bar(QWidget*)`
- [ ] `build_platform_qss` 补 `Pwb*` 状态组件选择器（tokens 驱动）
- [ ] （MappingStageBar 不改——已完整）

## M4 apps 装配 `stage_flow_install.cpp`
- [ ] bar 挂载 + stage/horizon 接线（applyStageValue / target_horizon 写）
- [ ] openProject 后 stage 恢复（workspace codec → ProjectSession）
- [ ] 生产命令注册（C5 约定，能力守卫）
- [ ] TaskCenter providers 注入（JobCenter 投影）
- [ ] bank/scene 信号链接线 + MapEditToolbar 安装
- [ ] ViewCoordinationController 实例化 + sinks 绑定（含 Pwb::UiControllers 链接）
- [ ] MainWindow 具名块调用 install（PWB_WITH_STAGE_FLOW 守卫）

## M5 测试
- [ ] `ui_stageflow.core`（纯函数 + 持久化往返 + 版本栅栏 + fail-closed）
- [ ] `ui_stageflow.qt_widgets_smoke`（controller 同步/布局应用/bar mount 二次调用）
- [ ] `platform.three_stage_flow`（MainWindow 级：stage 切换×3、命令注册数、
      task center provider、工程重开恢复 stage、布局应用断言、双窗口）
- [ ] `ui_visualqa` 新场景（三阶段 12 态语义断言，offscreen）
- [ ] 生命周期对抗：关工程中计算、切换中 queued selection、删层时 inspector 开、
      dock 销毁时回调、重开恢复布局、resize storm

## M6 性能与结构断言
- [ ] stage 切换 ×100（无 QGIS 工程重建断言：canvas 指针不变 + 无 layer reload 计数）
- [ ] horizon 切换 ×100、dock show/hide ×100、resize storm
- [ ] 命令 find() ×1000 延迟预算
- [ ] 泄漏冒烟（双窗口构造/析构 ×5）

## M7 Review + 收尾
- [ ] architecture/correctness review（agent）
- [ ] adversarial/lifecycle review（agent）
- [ ] P0/P1 清零；P2 → known limitations
- [ ] rebase origin/main、全量关键回归、push、PR
