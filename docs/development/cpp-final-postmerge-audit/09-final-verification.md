# 09 — 最终验证报告(fix/cpp-final-postmerge-audit vs origin/main 7bfe7585)

## 结论

11 commits(10 fix/feat + 1 docs),37 files,+~2100/−。全部 P0/P1 修复并经独立终审+负对照验证;P2 修复 12 项、P3 修复 7 项,其余按理由归类 08。pytest 面本地复现的 2 个回归与 3 个断言漂移全部修复。

## 分级验证

### L1 static
- audit-python-runtime-deps.sh:**PASS**(产品源码无 Python C API/PySide/python 子进程;pybind 限兼容 seam)
- final-closure-gate static:**PASS**(矩阵测试 4/4)
- 迁移矩阵(修正后):678 模块,NATIVE_PRODUCT 167 / LEGACY_REFERENCE 395 / PARTIAL_NATIVE 77 / NATIVE_LIBRARY_NOT_WIRED 39

### L2 touched targets
每个 commit 目标构建+定向测试通过(见 05)。#1446 新测试可执行 platform.constraint_authoring。

### L3 adjacent regression
每次 P1/P2 修复后跑 41–60 项相邻套件(ui_map/ui_widgets/platform/composition/export/mapping;closure_workflow/ui_controllers/workflow)全绿。

### L4 complete native product
- 干净 worktree 全量构建(1617 目标):exit 0;后续每个 commit 增量全量重编全绿
- **ctest 全量:237/237 PASS**(并行 -j2 一次,顺序复核;-j2 期间 platform.closure_mapping 一次 Timeout,单独重跑 1.6s 通过=负载假象,顺序复核确认)

### L5 product diagnostics
- `--capabilities`:20 hard capabilities runtime-ok;runtime-ok 行 25(含 5 kernel)
- `--self-check`:**13/13**
- `--diagnostics`:正常(qgis dev/vendored;providers 17;EPSG:4326 ok;temp ok;python-free verified)

### L6 final closure gate
- static:PASS(实测)
- configure:PASS(需 env 注入 vendored SDK 路径——脚本默认 /home/kevin/main 为他机假设,非代码缺陷)
- build:PASS(构建 pwb-platform 至 build/final-closure)
- test:gate 脚本口径缺陷 —— `run_build` 只编 `-t pwb-platform`(第 67 行)而 `run_tests` 期望全部 platform_* 测试可执行在该目录 ⇒ 任何分支在 `all` 上都会 62/66 Not Run(基线同样失败,非本分支回归;终审 reviewer 已记录)。**等价证据**:resource-gate Test 阶段直接对全量 native-product 构建目录执行同一正则:**71/71 PASS**。
- package/runtime:受 test 阶段口径阻塞未达;以 L1–L5 证据闭环。
- 建议后续修复:run_build 增加 `-t all` 或在 tests 前构建测试目标(不属本 PR 范围,记入 08 的脚本项)。

### GUI smoke
- offscreen(pwb-platform 20s 存活,0 崩溃)与真实 X11(DISPLAY=:0,10s 存活,0 崩溃)双证据;两者均只证明启动/壳稳定性,深交互(打开工程/三阶段/QGIS 画布)由 ctest platform.* 套件覆盖。

### Python 面(legacy 回归)
test_v13_harness_data_lineage 6/6(#1452 修)、test_audit_ui 6p1s(#1451 修)、harness_policy+catalog_scale 27p1s。venv Python3.14 与 geoviz <3.13 约束冲突,geoviz 族 pytest 未跑(记 08)。

## 因果实证(负对照)

- #1443:摘除 join 守卫→测试进程 exit 134(terminate);恢复→绿。
- #1445 D-02:施加"reversed adds"→pin 测试失败→撤销(pin 现存于 ui_map.qgis_smoke)。
- 终审 P1(R-01/R-02):静态证据(局部地址逃逸/nlohmann copy-and-swap 语义,reviewer 双 shard 独立命中)+ 代码走读确认。

## 数字基线对照(main @ 7bfe7585 → 本分支)

| 指标 | main 基线 | 本分支 |
|---|---|---|
| ctest | 236/236(需 LD_LIBRARY_PATH+ONNX 环境) | **237/237** |
| capabilities | 20/20 hard(含 3 处误导 kernel 标签之一) | 20/20 hard + 标签已修正 |
| self-check | 13/13 | 13/13 |
| 矩阵 NATIVE_PRODUCT | 133(脚本)/115(提交副本) | 167(双向修正) |
| open issues | 19 | 2(#1429 保留 + #1453 群已修汇总;R-08..R-10 归类项在 #1451/#1453 跟进) |

## 不依赖线上 CI 声明

本任务全部完成判断来自本地证据(上表)。CI runner 积压导致 main push 队列 >8h;CI 系 issue(#1427/#1428/#1430/#1431)的关闭依据为代码双重核实 + PR 作者本地记录 + 本审计本地复现(可复现项),已在关闭评论中注明待 CI 佐证。
