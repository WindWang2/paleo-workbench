# 06 — 测试计划与证据

## Level 1 static

- `scripts/cpp-migration/audit-python-runtime-deps.sh`:**PASS**(源码面 clean;pybind11 限兼容 seam)
- `python3 tools/migration/pwb_final_closure_matrix.py`:678 模块;矩阵测试 4/4(final-closure static 内)
- `scripts/cpp-migration/final-closure-gate.sh static`:**FINAL_CLOSURE_GATE_PASS**(对 #1448 修正后重生成的矩阵)

## Level 2 touched targets

每个 commit 附带目标构建+定向测试(见 05 表);全部通过后才提交。

## Level 3 adjacent regression

#1445/#1447/#1449 后各跑 41–60 项相邻套件(ui_map/ui_widgets/platform/composition/export/mapping;closure_workflow/ui_controllers/workflow)全绿。

## Level 4 complete native product

- 干净 worktree 全量构建:1617 目标,**exit 0**(基础;#1444 后增量重编多次全绿)
- 全量 ctest(修复完成后):**237/237 PASS**(原 236+新增 platform.constraint_authoring;并行 -j2 一次,顺序复核一次)

## Level 5 product diagnostics

- `pwb-platform --capabilities`:20 hard 全 runtime-ok;25 行 runtime-ok 总计;factor_fusion_kernel 标签已修正(经 science_service 接入)
- `pwb-platform --self-check`:**13/13**
- `pwb-platform --diagnostics`:正常(qgis dev prefix vendored SDK;providers 17;crs/temp ok;python runtime verified)

## Level 6 final closure

- `final-closure-gate.sh static`:PASS
- `final-closure-gate.sh configure`:PASS(需 env 提供 SDK 路径:PALEO_QGIS_SOURCE_DIR 等;脚本默认主机路径 /home/kevin/main 不适用于本机——非缺陷,环境差异已记录)
- `final-closure-gate.sh all`:后台执行中(build/final-closure 独立构建目录;结果记入 09)

## GUI smoke

- offscreen:`QT_QPA_PLATFORM=offscreen pwb-platform` 20s 存活,零崩溃输出(offscreen 证据)
- 真实 X11(DISPLAY=:0):10s 存活,零崩溃(X11 证据)

## Python 面(legacy 回归)

- tests/test_v13_harness_data_lineage.py:6/6(#1452 schema 修复后)
- tests/test_audit_ui.py:6 passed 1 skipped(断言语义对齐后)
- test_harness_policy / test_catalog_scale_v6:27 passed 1 skipped 合计
- 本机 venv 限制:python3.14 不满足 geoviz <3.13 约束,geoviz 依赖族 pytest 未跑(fix/因子调度族),以 #1434 作者本地记录+ctest 侧对应 C++ 测试为证据

## 负对照(因果实证)

- #1443:移除 join 守卫→测试二进制 exit 134(terminate called);恢复→绿。修复与崩溃的直接因果被证明。
- #1445 D-02:施加"reversed adds"修复→pin 测试失败(证明前向添加才正确)→撤销修复、保留 pin。
