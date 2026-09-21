# 05 — 修复计划与执行(全部完成)

分支 `fix/cpp-final-postmerge-audit`(9 commits,37 files,+1826/−170)。每个 commit 对应一个 issue,均带回归测试。

| Commit | Issue | 类别 | 内容 | 回归测试 |
|---|---|---|---|---|
| 94812536 | #1443 (P0) | fix(science) | launch_worker 对 joinable 线程赋值→terminate;join-before-assign | closure_science.qt_hooks 第二次 demo 运行(负对照实证:无修复 exit 134,有修复绿) |
| 7e6bcd70 | #1444 (P1) | fix(build) | CMake 家族 7 处:mapping_kernel 挂载时序、CONV-14 依赖蕴含(脚本+PwbFeatures)、CLOSURE-SEISMIC/VIZ-B LAS post-hoc、三阶段产品安装移出 BUILD_TESTING、linked_workspace post-hoc(连带修复从未编译过的 TU:tuple/slots 宏/QComboBox 前向声明)、cpp-close-01 死 option 删除 | cmake --preset linux-gcc-release 从 FATAL→exit 0;build.ninja PWB_WITH_CLOSURE_SEISMIC 0→32;ui_composite smoke 现在覆盖 linked_workspace 半边 |
| 04a512e2 | #1445 (P1) | fix(qgis) | D-01 导出 z 序反转删除;D-03/D-04 mirror 平铺 reversed+takeChild 舞步+注册桥 detach;D-05/D-06 比例尺域对调;D-07 捕捉方向;**D-02 撤销**(注册桥默认 TopOfTree 插入→前向添加本就正确)+ 钉契约测试 | ui_map.qgis_smoke 堆叠 pin;60 项目标测试 |
| 65d3c4b0 | #1446 (P1) | feat(constraints) | Stage-2 约束创作链:createStageConstraint(GPKG+绑定+角色注册+文档登记)+ syncConstraintGeometryOnSave(constraints_sync.py 移植:收割/指纹/replace 语义)+ constraint_requested 接线 | platform.constraint_authoring 全链(创建→数字化→收割→指纹→幂等) |
| 6c61c394 | #1447 (P1) | fix(lifecycle) | 全图层脏保护、closeProject+close-then-open、部分失败续走尾部、ProjectSession::close 不再销毁 EditController(detach_all) | platform.app_shell 切换电池 |
| 9d064850 | #1449 (P2) | fix(workers) | WorkerHost finished_ 复位+generation;session_generation_ 原子化+worker 只读原子;WorkflowScheduler done-latch epoch | 47 项平台/工作流测试 |
| 2fd1265c | #1450 (P2) | fix(ui) | horizon candidates 从工程文档注入;占位 dock 永不被 profile 强制展示(has_panel_factory) | three_stage_flow 新契约断言 |
| 4e1945fd | #1448 (P2) | fix(migration) | 矩阵真值:全别名集+传递闭包+生产 TU include 证据(NATIVE_PRODUCT 133→167,NOT_WIRED 73→39) | final-closure static gate 对重生成矩阵 PASS |
| 56fc012f | #1451 (P3) | fix(review) | E-2 除零守卫、B-09 终态清理、F-12 状态栏双写、F-09 layersRemoved 清理、N-3 能力标签、F-07/N-2 文档与断言对齐 | audit_ui 6/6 等 |

## 修复中撤销的审计发现

- **D-02**(DisplayMapCanvas 堆叠颠倒):vendored QGIS 注册桥默认 AboveInsertionPoint→fallthrough TopOfTree,新层总在树顶——前向添加即正确。反向对照实验(提议的 reversed 修复)被新增 pin 测试当场拒绝。教训已写入测试注释。

## 修复中新发现并修复的问题

- ProjectSession::close() 销毁 EditController(edit_.reset())→ 窗口关闭后 edit() 空引用(#1447 实施中被新 null-safe 断言路径暴露,gdb 定位)
- linked_workspace.cpp 从未编译过,存在三处真实编译错误(#1444 实施时暴露)
