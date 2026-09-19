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

## 环境

- Linux x86_64，gcc 16.2.1，cmake 4.4.3，ninja 1.13.2，Qt 6.11.2（/usr，满足 WLE Qt≥6.8），python3 3.13.15，nproc 16，内存 available ≈47 GiB。
- 无预建 WLE 安装树（全盘无 WellLogConfig.cmake）→ viewer 配置走 submodule 源码构建（`libs/science_suite` 强制 WELLLOG_BUILD_PYTHON/TEXT/TESTS/BENCHMARKS=OFF、QT_WIDGETS=ON）。
- 主工作区 `/home/kevin/projects/paleo_project/main` 有用户未跟踪文件（docs/development/cpp-conversion-swarm-20/*）——不触碰。
