# 09 — Verification Report (V14-THREE-STAGE-UX)

验证日期：2026-09-20/21。分支 `feat/v14-three-stage-workbench-ux`。
**Local verification completed; online CI was not required or awaited for
this development goal.**

## 构建验证

- Configure：`Invoke-ResourceGate.ps1 Configure`（资源门 `-j2`，
  `CMAKE_PREFIX_PATH=Qt 6.8.0/msvc2022_64`，
  `PWB_QGIS_DEPS_PREFIX=vcpkg/x64-windows`——Windows vendor SDK 为本机
  既有构建，只读复用）。
- 全量构建：`pwb-platform` + 全部 platform/ui_stageflow/ui_shell 测试
  target，Ninja exit 0（重试循环跨内存门退避）。
- 全程 `-j2`（资源门锁 `cpp-migration-heavy.lock` 未绕过；内存门参数
  MinFreeGiB=1，因桌面环境空闲物理内存常态 1–3 GiB 而 commit 余量
  47 GiB——不绕锁只调阈值，与同机并行线通过同一 flock 互斥）。

## 测试结果（offscreen，Windows 本机）

`ctest -R '^(platform\.|ui_stageflow\.|ui_shell\.)'`：

- **21/21 可运行测试通过**（含既有回归 platform.app_shell/ui_wiring/
  lifecycle_cycles/edit_cycle/qgis_smoke/toolpolicy_*/services/
  ui_services/... 全绿）。
- 新增：`ui_stageflow.core`（9 用例）、`ui_stageflow.qt_widgets_smoke`
  （5 用例）、`platform.three_stage_flow`（安装幂等/注册 16 命令/palette
  find/阶段门控/三阶段布局矩阵 + canvas 指针恒等/偏好持久化+重置/
  任务中心 provider 安全性/第二窗口生命周期/析构后注册表存活）。
- Not Run ×2（closure_review_install/project_session）：需 DATA_INTEGRATION
  闭合（本机 reduced closure 无 SCIENCE），非失败。
- `platform.three_stage_flow` 曾现 1/6 间歇崩溃——定位为 review 修复第一版
  destroyed 钩子在成员析构后访问 id 列表；改到析构体后 10/10 稳定 +
  全套件两遍绿。

## Review 验证

两轮独立 review（架构/正确性 + 对抗/生命周期）：
- P0 ×2（无锁文档写、测试断言语义反转）→ 全部修复并有测试断言。
- P1 ×6 → 修复 5，1 项（selection bus publish 喂入）跨线登记。
- P2 ×12 → 修复 4，8 项登记 known limitations（含 file:line 依据）。
详见 07-review-findings.md。

## A/B 归因记录

- `platform.services` 的 Wayland-EGL 断言失败：基线（改动前同文件）同样
  不可能通过（断言依赖 Q_OS_UNIX-only 的 setenv 效应，Windows 从未跑过
  该路径）→ 平台守卫修复，非本线行为回归。
- 其余全部一次通过或修复后通过；无未解释失败。

## 交付物

- libs/ui_stageflow（Qt-free core + Qt shell + 测试）
- apps stage_flow_install.cpp（挂 bar/命令/providers/bank 接线/selection
  bus/stage 恢复）
- WorkstationFrame::mount_top_bar、MapDockManager::is_panel_registered、
  CommitCoordinator::set_document_section、Pwb* QSS 选择器
- Windows 可移植性修复 14 文件 + configure 修复 3 处 + 测试平台守卫
- 文档 00-09（本目录）
