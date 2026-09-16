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

# CPP-B 数据/工程线 goal-loop 区段（feat/cpp-data-project，2026-09-16 启动）

目标与 Oracle 见 `docs/development/cpp-data/`（Prompt B，总设计 P0/P2/P3 持久化、CPP-20/309/601/602）。迭代上限 15 轮；三线共享重型槽（Invoke-ResourceGate.ps1，8 GiB 门槛，2 jobs）。

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| B-1 | 侦察：协议/总设计/V13 文档/Python 模型（project/models+manager、catalog/models+db+storage+service 写路径、mapping_workspace/stage_state、paths）；worktree 复用核验（d0347da2，sparse OK，树干净）；工具链（VS2022 14.38 + VS 自带 cmake/ninja）；Python oracle（主仓 .venv 3.12.13 只读可用）；网络可用（sqlite.org 200）；内存 Probe=4.31 GiB → exit 75 | 关键语义已固化：.paleo.json（extra=allow 顶层、原子写+bak、5 路径节 relativize、project_root="."）；catalog.sqlite v5 canonical（16 表、WAL、sync_state 4 键）；artifacts 布局与 {stage}/{asset}/{version}/ 落盘；workspace dict 7 键 | 通过（轻量阶段，未需重型槽） | B0 文档 + 依赖落地（sqlite amalgamation、nlohmann 单头）→ B1 实现 |
| B-2 | B0 完成：4 份文档（baseline/contracts/schema-map/test-plan）+ oracle 管线（generate_fixtures.py 经真实 ProjectManager.save + DataCatalogService 产 8 fixture + manifest；dump_fixture.py 产 4 类 oracle dump）；vendored sqlite 3.45.1 + nlohmann 3.12.0 | fixture 落盘校验（typical: 2 asset/5 ver/1 run/2 tag + wc/lease/blob/members）；corrupt/future/missing 变体就位 | 通过 | C++ 主体实现 |
| B-3 | C++ 全量落盘：domain(ids/sha256/json/diagnostics)、project(schema spec 表+normalize+manager 原子写/恢复+paths)、workspace codec、catalog(sqlite RAII+repository+audit)、data_suite(contracts+CommitCoordinator+journal 恢复+facade)、pwb-inspect/migrate、9 个测试文件 + CMake | 未编译（内存门禁 75） | 未验证 | 门禁内 configure/build/test |
| B-4 | 静态自审两轮（无编译条件下的最大验证）：修复 UTF-8 路径桥、journal 恢复完整性（format/parents/size/ProjectSaved 分支/run+rebind 还原）、catalog 4 表漏加载、stage_states 种子、tmp 命名、.bak rename 语义、corrupt DB 分类、4 处测试结构错误；收尾文档 handoff.md + verification.md（含 6 次门禁探测台账） | 门禁 Probe ×6 全 75（free 4.2–4.7 GiB；Available 同级 → 机器真实吃紧）；按协议不绕过/不轮询 | 未通过（外部条件：可用内存） | 长等待后末次探测；仍 75 → 记录未完成状态并暂停 |

> 区段同步说明：本文件为 `.goal-loop-ledger.md` 的 CPP-B 任务区段快照
>（含 V13 历史区段，按协议保留不合并）。后续轮次先改根账本再同步到此。
