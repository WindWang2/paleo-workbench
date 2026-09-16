# Goal Loop Ledger — V13 Geological Data Lineage Workspace & QGIS Compilation Control Plane

## CPP migration plan preparation — 2026-09-16

Goal: tag the reviewed migration plan, create three bounded goal-loop prompts and isolated worktrees. Oracle: committed plan/tag/worktree identities agree; each prompt has ownership, acceptance and resource limits; shared gate rejects concurrent/low-memory heavy work. Limit: 15 iterations. No migration implementation jobs are launched by this preparation task.

| Round | Change | Verification | Result | Next |
|---|---|---|---|---|
| 1 | Located and read installed goal-loop; retained complete skill in repository; wrote three prompts and shared contracts | Confirmed source baseline 671ee426, absent destination branches/tag, actual low free RAM | Preparation in progress | Validate executable resource gate |
| 2 | Added shared resource admission gate with 2-job cap, memory threshold and worktree-local build path | PowerShell parse PASS; actual low-memory rejection exit 75; actual exclusive-lock rejection exit 75; skill copy equal after newline normalization; all three prompt checks PASS | Passed | Commit plan and create tag/worktrees |
| 3 | Mock-command test exposed absent environment variable restored as empty string under PowerShell 7; fixed by removing only variables originally absent | First mock run failed on restoration assertion; no real build/test process was started | Fixed, pending recheck | Rerun resource contract checks |
| 4 | Reverified the focused environment-restoration fix and gate contracts | Mock build exit 23 propagated; jobs=2; environment restored; CTest zero-test guard; outside-build rejection; Configure arguments preserved: all PASS | Passed | Commit plan, prepare sparse worktrees, verify common lock |
| 5 | Staging the formerly untracked design exposed four Markdown trailing-space hard breaks; replaced with blockquote paragraph breaks | Staged diff check initially failed on exactly four lines | Fixed | Repeat staged check and commit |
| 6 | Prepared three sparse worktrees; explicitly populated their new empty indexes; documented safe initialization | All three worktrees clean; all three reject a main-repo shared lock with exit 75; after release all execute their memory probes; original composite_document.py SHA-256 unchanged | Passed | Seal local annotated tag and fast-forward clean worktrees to final plan commit |

---

Branch: `feat/geological-data-lineage-qgis-control-v13` (base: origin/main @ 40531741)
Worktree: `C:\Users\wangj.KEVIN\projects\paleo-workbench-geodata-qgis-v13`

## Oracle（完成条件）

§33 Definition of Done 全部满足，且最终 PR 已创建（不合并）。可客观验证：
1. 分层测试（domain/data-manager/QGIS/cross-domain E2E）在本地通过；
2. §24 E2E 场景（import→bind→process→map→edit→commit→lineage→stale→recompute→update map→save/reopen）有真实测试通过；
3. `docs/development/geodata-qgis-control-v13/` 15 篇文档齐全；
4. branch 已 push、PR 已创建。

## 环境配方（本 worktree，已验证）

```bash
cd ../paleo-workbench-geodata-qgis-v13
export WT=C:/Users/wangj.KEVIN/projects/paleo-workbench-geodata-qgis-v13
# fast 腿
QT_QPA_PLATFORM=offscreen PYTHONPATH="$WT/native/qgis_render_bridge" \
  ../paleo-workbench/.venv/Scripts/python.exe -m pytest <files> -q --timeout=180 -p no:cacheprovider
# qgis 腿（额外）
PALEO_QGIS_BUILD_DIR="C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor" ...
```
已复制主仓构建的 `qgis_render_bridge.cp312-win_amd64.pyd`（v0.7.0a0, 2026-09-15 18:13）到本 worktree native/ 以满足 conftest 桥源断言。若后续修改 C++ 需重建。

## 迭代记录

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | Phase 0 侦察：fetch、审 PR/issues、建 worktree、5 路并行只读审计、测试配方验证（fast 11 passed / qgis 4 passed） | 审计报告完成；环境可用 | 通过 | 写 baseline/overlap 文档，进入 Phase 1 |
| 2 | Phase 1 domain contracts：manual_edit run / 绑定字段 / source_usage / stage 状态 / intermediate policy / order 契约（19+4 测试）；邻接回归 70 passed + qgis 20 passed | 全绿（commits 7690c340/77a53c0f） | 通过 | Phase 2 UI |
| 3 | Phase 2/3：IngestPlanDialog + impact 门 + Inspector 用途行 + factor/fusion pin + harness 6 actions + Inspector 数据来源行；16+6+7+3 测试 | 全绿（010dfe13/63912df3/后续） | 通过 | E2E |
| 4 | Phase 4 E2E：§24 十八步全链；揭露并修复 3 个生产缺陷（producing_run_id 误读 / ref 缺 version_number / version.id 误读 → 真 stale 被 CURRENT 掩盖） | E2E 42/42（f03f81f7） | 通过 | 文档 + 审查 |
| 5 | Phase 5 文档 00-14；Phase 6 对抗性审查（子 agent 11 项发现）全部修复（含 as_new_version 丢失 / teardown UB / legacy 行键错 / RUNNING run 泄漏 / fail-open 门） | V13 全套 29+ 测试复验绿（18360589） | 通过 | 全量回归 + 15-verification + push + PR |

## 环境备忘（补充）

- worktree submodule：geo-viz-engine/well-log-engine 经本地 --reference 克隆填充（直连 GitHub shallow clone 会 EOF）；third_party gdal/proj 未初始化（测试不需要）。
- vendor runtime 经 junction：`native/qgis_render_bridge/build/qgis-vendor` → 主仓同路径（mklink /J），默认解析即可用，无需 PALEO_QGIS_BUILD_DIR。
- 后台 pytest 与前台 pytest 并行会互相拖慢并可能触发 timeout 假阳性——全量回归必须独占运行。


---

## 任务区段：CPP-C 算法/工作流/科学可视化（feat/cpp-science-viz，2026-09-16 启动）

目标与 Oracle：主仓 docs/development/full-cpp-migration-v1/04-prompt-science-viz.md（8 项全选）。上限 15 轮。

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | 启动+侦察：读协议/总设计/CLAUDE；worktree 复用核验（cpp-migration-plan-v1 为祖先、工作区干净）；子模块按 gitlink 本地克隆初始化（geo-viz-engine@08851951、well-log-engine@f845e7ab，WLE 主仓为 shallow 改直克隆）；审 A 线 contracts（无 ABI manifest→viewer 用 venv Qt 6.8.0 测试配置）；写 C0 四文档（baseline/migration-matrix/contracts/test-plan），冻结 C1 算法=seismic.coherence_c3（生产链 providers→KERNELS['c3']→geoviz_seismic）与容差 | 远端无新提交；工具链核验（MSVC 14.38+VS CMake/Ninja）；内存 4.17 GiB<8 门禁→先做独立源码工作；tiny.sgy/A1.Las fixture 可用，geoviz loader 只读 oracle 验证通过（8×8×32 dt=2ms） | 通过（C0 交付） | C1：libs/algorithms + libs/workflow 编码 |
| 2 | C1–C4 全部源码落地：pwb::science SDK（types/outcome/algorithm/publisher/registry）+ coherence_c3 移植（reflect 填充/奇数窗口钳制/float32 幂迭代/NaN→1.0 语义对齐 oracle）+ pwb::workflow task runtime（单 worker、queued→running→{succeeded/failed/cancelled}，取消只 request_stop 终态由 execute 决定）+ pwb::viz（SelectionEventV1、地震数据源接口、in-memory/owning backend、map_slice_to_indexed8）+ science_suite CMake 入口（viewer opt-in fail-closed）+ 4 个 Qt-free 测试 + viewer 测试 + WLE 宿主 adapter + 2 个 oracle 生成脚本；冻结 fixture 已生成（coherence 7 case 含真实 tiny.sgy ×2 参数组、seismic crossline-major 置换 + 三轴 expected + indexed8） | MSVC /Zs 语法检查核心 4 文件+测试 4 文件全部 EXIT=0；O6 静态 grep：核心无 Python/Qt Widgets/QGIS 代码引用（仅 2 处注释文字）、无第二 GIS 栈；oracle 生成器实测发现并修正 iline 1-based 值语义与常量体非精确 1.0（0.99999976）两点，baseline 文档同步 | 通过（源码级）；构建待门禁 | 内存 4.78<8 GiB 被拒 1 次 → 写 verification/handoff 骨架后再探；随后门禁下 configure/build/ctest G1-G4 |
| 3 | 资源等待与阻断处理：门禁 Probe 4 次 exit 75（4.17/4.78/4.84/4.52 GiB）；只读诊断确认 Available≈Free≈4.5 GiB（桌面应用稳态占用 ~26 GiB：ZCode×4/ChatGPT/WXWork/Feissu/opencode/WSL，无编译进程，非门禁度量缺陷）；自审查修复 3 处（task_runtime 持锁发布×2、析构语义）；完成 handoff.md + verification.md（O6 已验证、O1-O5/O7 构建侧如实标 blocked-on-memory）；提交 013d9354；长间隔重探（4min/7min 后仍 4.35 GiB） | 独立源码/契约/文档工作全部完成并提交；MSVC /Zs 全绿；oracle fixture 已入库；仅剩必须过 ≥8 GiB 门禁的 build/ctest | 未通过（外部资源条件阻塞，非代码缺陷） | 需要用户释放内存至 ≥8 GiB（关闭部分桌面应用）或明确授权降低小目标构建门限；随后按 verification.md §5 序列执行并回填 |
| 4 | 终局探测：累计等待 ~25 分钟（4/7/10 分钟间隔）后第 5 次 Probe 仍 exit 75（4.22 GiB） | 独立工作已穷尽（源码/契约/文档/fixture/静态验证全部完成并提交 013d9354、8ce51843）；阻塞项仅为必须过门禁的 build/ctest（O1/O2-C++侧/O3-ctest/O4/O7）与构建后回填 | 未通过（持续外部资源阻塞） | <loop-pause>：需用户释放内存至 ≥8 GiB（关闭部分桌面应用，如 WXWork/飞书/ChatGPT/空闲 ZCode 会话/WSL）或明确授权对小型核心构建降低门限；随后执行 verification.md §5 序列并回填实测数字 |
