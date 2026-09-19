# VIZ-A 账本（LAS/WLE 收敛与测井绘制差量）

分支：`codex/viz-a-welllog-convergence`（worktree `worktrees/viz-a-welllog-convergence`）
基线：`origin/main @ 7290f72728c0b6ff04c33a573cb0e964e3b5ff58`（2026-09-19 fetch）
submodule：`well-log-engine @ f845e7ab`（只读）、`geo-viz-engine @ 08851951`（oracle 参考，只读）
迭代上限：200 轮（goal-loop）。每轮：读账本→评估差距→单一改动→亲自验证→记账。

## 硬性 Oracle（完成条件）

1. 同一 LAS 经既有 dock 路径（`WellLogHostWidget::load_las`）与新 preview（ingest registry LAS 分支）/worker（`ui_workers` well_log_load + 生产 load_fn）两路得到可解释一致的数据/单位/诊断；正常文件返回真曲线/真预览（非 message result）。
2. WLE 差距表（`gap-table.md`）所有纳入行为均有实现或已实现证据；困难项排除必须给出依据（无消费方/属他线/ECharts 旧栈等）。
3. viewer 真实 load→显示→轨道调整→导出可运行；失败、取消、重开与迟到回调有回归测试。
4. P-B 专用配置（`scripts/cpp-migration/run-viz-a-gate.sh`）可执行：两遍 ctest、受影响回归、ON/OFF 检查、真实图像/导出证据。
5. 本 ledger、差距表、对账裁决（`reconciliation.md`）、API 交接（`api-handoff.md`）与 PR 完整。

## 资源控制约定（本任务强制）

- 一切重型命令经 `scripts/cpp-migration/invoke-resource-gate.sh`（锁在 `.bare/cpp-migration-heavy.lock`，本机共享 git common dir）。
- 强制 `-j 2`（`CMAKE_BUILD_PARALLEL_LEVEL=2`、`CTEST_PARALLEL_LEVEL=2`、OMP/OPENBLAS/MKL/NUMEXPR=1），入场内存 ≥8 GiB；exit 75 → 30–60s 退避后重试。
- build 目录：`build/viz-a`（本 worktree 独占）。仅增量构建本任务 target 闭包。
- 门禁已持锁时不嵌套调用门禁。

## 轮次记录

| 轮 | 改动 | 验证 | 结果 | 下一步 |
|---|---|---|---|---|
| 1 | 定位仓库/worktree 创建（origin/main @ 7290f727）、submodule 初始化（WLE f845e7ab、geoviz 08851951）、四路只读勘察（WLE 能力面/geoviz 行为面/ui_workers+预览消费链/构建门禁体系）、读 #1359/#1394/#1375 实现 | worktree `git rev-parse HEAD` = 7290f727；submodule status 正确 | 通过 | 建 ledger/差距表骨架；写 ingest LAS preview 核心 |
| 2 | 全量实现并本地 commit 9214994：ingest LAS 预览核心+registry 替换+WLE bridge（受守卫 target）、ui_workers wle_load 生产适配、pattern/robust_scale 绘制差量内核、app viz_a_install、oracle 生成器×2、fixture 17+1、差距表/对账/交接文档、run-viz-a-gate.sh | 逐文件 `g++ -fsyntax-only -Wall -Wextra` 全过；oracle 18 案例（9 一致/9 裁决、18/18 负面自检） | 通过（静态） | 门禁实跑 |
| 3 | 门禁首跑（后台等锁）：**假绿**——gate() 内 `if cmd; then` 吞掉 exit 75，6 步全"成功"打印 ALL GREEN；exit 0 无效。审核 1（Python/科学语义）+审核 2（C++/Qt 生命周期）并行完成 | 读 /tmp/viz_a_gate_run1.log 确认 6×"gate action failed (exit 0)" 后仍 ALL GREEN | **失败（脚本缺陷，已定性）** | 修 gate 重试逻辑 + 审核发现 |
| 4 | 修审核 1/2 全部发现（生成器 first_token/tab 转录、坏 ~C 分层 R18、井名 last-wins R16、行内 # R15、py_round printf 正确舍入、PNG 魔数、apps CMake 顺序死接线→根 VIZ-A 块、DATA+SCIENCE+VIEWER 顺序→VIZ_A_LATE_BRIDGE 重入、gate `\|\| code=$?`、viz_a_install generation 守卫）；补 fixture 18-22 重生成 oracle（23 案例、12 一致/11 裁决、23/23 负检） | 静态检查全过；commit 84c6b707 | 通过（静态） | 门禁重跑 |
| 5 | 门禁二跑：**再次假绿且 configure 实败**——①重入守卫在 add_library 之后→CMP0002 重复 target（审核 3 实测复现）；②set -e 被移除且未检查 gate() 返回值→失败照走 ALL GREEN。审核 3（产品接线/范围/构建）完成：P0×2、P1×4、P2×6 | /tmp/viz_a_gate_run2.log：CMake Error duplicate pwb_ingest + 末行 ALL GREEN（exit 0） | **失败（已定性）** | 修审核 3 全部发现 |
| 6 | 修审核 3：①重入守卫移到 add_library 前（ingest CMake 头部 VIZ-A 块）②gate 全步骤过 `must()`（失败即 exit）+ 注明失败传播契约 ③颜色表去重（document_plan 导出 `facies_colors()`，viz_a 委托，8 5 条单副本）④诊断要素贯通（LasPreviewData.diagnostics + WleDocumentPayload{document,diagnostics}，consistency 三路断言）⑤迟到丢弃回归（resolve seam 置 flag→JobCancelled）⑥删恒真断言/死宏 ⑦WRAP 首 token 归一 ⑧tie 排序纯 CJK 前置断言 ⑨hpp 文案对齐实现 | 静态检查全过（本轮） | 通过（静态） | 门禁三跑（带失败传播 + QGIS SDK 复用） |

## 环境

- Linux x86_64，gcc 16.2.1，cmake 4.4.3，ninja 1.13.2，Qt 6.11.2（/usr，满足 WLE Qt≥6.8），python3 3.13.15，nproc 16，内存 available ≈47 GiB。
- 无预建 WLE 安装树（全盘无 WellLogConfig.cmake）→ viewer 配置走 submodule 源码构建（`libs/science_suite` 强制 WELLLOG_BUILD_PYTHON/TEXT/TESTS/BENCHMARKS=OFF、QT_WIDGETS=ON）。
- 主工作区 `/home/kevin/projects/paleo_project/main` 有用户未跟踪文件（docs/development/cpp-conversion-swarm-20/*）——不触碰。

## 记录不改项（审核 P2 残留，如实声明）

- `path_stem`（Python Path.stem 语义）三处小复制：`las_preview.cpp`、`wle_load.cpp`、`las_preview_wle_test.cpp`——为 8 行工具跨 lib 建依赖不值；三处均有注释指向彼此。
- `JobCenter::make_owner` 每次"打开 LAS"新建 owner（只增不减，随窗口生命周期回收）：沿用 main_window 既有模式（SEG-Y/因子图同款），不为本线改 JobCenter。
- pattern tie 排序按字节长度（==字符数，前提：纯 CJK 键集）——`viz_a.patterns` 有前置断言锁死该前提。
- app 级 generation 守卫（过期投递丢弃）为 compile-cover：platform app 无独立测试目录归本线，运行面由 worker 级迟到丢弃回归 + job_bridge released 契约（审核 2 核实）背书；如实标注。

## 门禁执行记录

- run1（2026-09-19，/tmp/viz_a_gate_run1.log）：假绿（exit 75 被 if/fi 吞）。教训已写进脚本注释。
- run2（2026-09-19，/tmp/viz_a_gate_run2.log）：configure 实败（重复 pwb_ingest target）+ 假绿（未检查 gate() 返回值）。两缺陷均已修。
- run3（/tmp/viz_a_gate_run3.log）：configure 真实失败暴露（Qt6 IMPORTED target 作用域），已修（测试目录自行 find_package）。
- run4（…run4.log）：构建暴露 viz_a.wle_load 缺 WLE 头路径，已修（直链 WellLog::IO）。
- run5（…run5.log）：首轮真实测试——暴露 4 类问题：ingest oracle 重冻结污染（本机 Python 依赖与原冻结环境不同）、core 测试数据形状 UB、tamper 未写盘、patterns oracle 裸 NaN、viewer_flow GLX BadValue。
- run6（…run6.log）：GLX 定性——offscreen 平台插件在本机（真实显示器）无法建 GL 上下文；对比 science.viewer.well_log（未强制 offscreen）通过。
- run7（…run7.log）：ingest oracle 恢复原件+仅两处裁决补丁；tamper 全文件覆盖；science.viewer 构建清单补齐。
- run8（…run8.log）：GL 环境改显示器条件化（DISPLAY 存在→仅软件 GL；无显示→offscreen）；02 号 no-curve 案例按构造内容不变（豁免篡改分歧检查，跨案例判别覆盖）。
- run9（…run9.log）：两遍 ctest 首次全绿（12/12×2）；MALLOC 步骤 Exec 参数拼接 bug（-j/-m 落进被包裹命令）已修（gate() 传verbatim）。
- run10（…run10.log）：**全绿**（12/12×2 + MALLOC 6/6 + OFF 1/1）；step7 因 SDK 发现路径错跳过。
- run11（…run11.log）：路径修后 step7 全平台 configure 暴露 QGIS SDK 清单缺陷（`/home/kevin/pwb-sdks/root/usr/include` 不存在——SDK 打包问题，非本分支）。
- run12-15（…run12-15.log）：install_cover 目标引入与编译修复（QMainWindow include、viz_a_test ARGN、moc-free host 的 static_cast 语义）。
- run16（…run16.log）：**最终全绿**——13/13 测试 ×2 遍、MALLOC 7/7、OFF 检查 1/1、step7 install_cover 过（全平台 configure 因上述 SDK 清单缺陷按设计记为 best-effort 失败，不阻塞；接线由 install_cover 编译+运行覆盖）。
- step-7 说明：QGIS SDK 清单含不存在绝对路径属平台线/SDK 打包问题，本线不修共享 SDK；如实记录于此。

## 覆盖差异声明（默认门禁 vs 本专用门禁）

- 默认 `run-integrated-gate.sh`（PLATFORM+DATA+SCIENCE，VIEWER=OFF）：覆盖 ingest/ui_workers/science.* 回归，不覆盖 science.viewer.*、viz_a.* 的 WLE 依赖测试，也不编译 app 接线（PWB_WITH_VIZ_A 不定义，main_window 钩子在 #ifdef 内为死码，合法降级）。
- 本专用门禁（SCIENCE+VIEWER+VIEWER_TESTS+CONV_22，PLATFORM=OFF）：上述 WLE 面全测 + OFF 反向检查（默认配置可配置、LAS 分支诚实降级、无桥 target）；step 7 追加 PLATFORM=ON 编译覆盖 app 接线（复用 sibling main 的 vendored QGIS SDK，只读）。

## 最终验收快照（2026-09-19，run16）

- 分支 HEAD：见 git log（本 ledger 与代码同 commit）。
- 专用门禁 `scripts/cpp-migration/run-viz-a-gate.sh`：exit 0。
  - 两遍 ctest：`viz_a.*|science.viewer.*|ingest.*|ui_workers.*` 13/13 × 2。
  - MALLOC 审计（MALLOC_CHECK_=3）：viz_a.* 7/7。
  - OFF 检查：viewer-OFF 配置成功、`viz_a.las_preview_core` 通过、build.ninja 无 WLE bridge target。
  - step7：`viz_a.install_cover` 过；全平台 configure 因共享 QGIS SDK 清单缺陷（不存在的绝对 include 路径）按设计 best-effort 记录失败。
- GL 环境声明：本机有真实显示器（GLX）→ 测试以软件 GL + 真实显示器跑；无显示环境（headless CI）自动 offscreen。真 GL 初始化断言在 science.viewer.well_log（真实 GL 上下文 + capability report）通过。
- 三轮独立审核（Python/科学语义、C++/Qt 生命周期、产品接线/范围/构建）全部 P0/P1 修复并复测；P2 残留见"记录不改项"。
- 迭代：16 轮门禁执行（2 次脚本假绿事故已修复并写入脚本注释）、6 个测试目标、23 oracle 案例（12 一致/11 裁决/23 负检）+22 scale 案例+42 图案探针+12 颜色探针。
