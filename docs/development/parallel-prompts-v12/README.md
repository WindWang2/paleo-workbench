# Parallel Optimization Prompts (V12) — 使用说明

本目录包含 **3 个可并行执行的 `/goal` 开发 prompt**，用于 zcode 上的长周期自动化开发。

来源分析报告：`docs/development/parallel-optimization-directions-20260913.md`

## 三个方向

| # | 文件 | 方向 | 核心目标 | 风险 |
|---|------|------|----------|------|
| 1 | `prompt-1-ingest-io.md` | 导入 / 入库 I/O 流水线 | 单次受管 RAW 导入从「读 3 遍 + 写 2 遍」→「读 1 遍 + 写 1 遍」；目录扫描元数据收集并发化 | 低（纯 Python I/O，语义零变化） |
| 2 | `prompt-2-geopipeline.md` | 编图计算核 | 克里金 N=2000 从 27.6s → IDW 同阶；多边形化 150×150 从 24.2s → 亚秒；等值线 300×300 显著下降 | **高**（数值正确性，需黄金值基线） |
| 3 | `prompt-3-render-increment.md` | 渲染 / 镜像增量通道 | 标量栅格不再每帧全幅 `.copy()`；`_PreparedLayer` 按 data_revision 缓存；拓扑校验批量接口 | 中（缓存陈旧 = 数据损坏级风险） |

## 为什么可以并行

三个 prompt 的文件集 **零交集**：

- **方向一**触达 `paleo_workbench/data/**`、`paleo_workbench/ingest/**`（导入与存储层）
- **方向二**触达 `paleo_workbench/geological_pipeline/**`、`paleo_workbench/workflow/constrained_idw_adapter.py`（计算核）
- **方向三**触达 `paleo_workbench/mapping/map_render_backend.py`、`mapping/topology.py`、`mapping/qgis_mirror.py`（渲染与镜像）

唯一潜在耦合点是「计算核产出的栅格 → 渲染层消费」的数据契约。三个 prompt 均已写入硬约束：**不得修改跨方向共享的数据结构的公开契约**（如需变更，写进 `00-decisions.md` 并在 PR 描述中显式标注，由人工串行裁决）。

## 用法

每个 prompt 是自包含的独立任务，交给 zcode 的 `/goal` 入口即可：

```
/goal @docs/development/parallel-prompts-v12/prompt-N-<name>.md
```

三条线可同时启动，各自独立 worktree：

| 方向 | worktree 路径 | 分支 |
|------|---------------|------|
| 1 | `../paleo-workbench-ingest-io-v12` | `feat/ingest-io-v12` |
| 2 | `../paleo-workbench-geopipeline-v12` | `feat/geopipeline-v12` |
| 3 | `../paleo-workbench-render-increment-v12` | `feat/render-increment-v12` |

## 三个 prompt 共有的硬约束

每个 prompt 的 §1 都写死了以下内容，用于约束 zcode 的资源占用：

1. **worktree**：`git worktree add ../paleo-workbench-<name> -b <branch> origin/main`
   ⚠️ **禁止 `git worktree prune`**（本仓曾因此清空 12 个 worktree 注册）。收尾用 `git worktree remove <path>`。
2. **编译预算**：**不需要编译 C++**、**不需要 QGIS 桥**；禁止运行 `tests/perf/` 全量、`-m slow`、`-m opengl`、3D 腿。
3. **并发上限**：**最多同时 2 个 subagents**。需要第 3 个视角时**串行**执行，不得并行开第 3 个。
4. **无 CI**：不等待、不依赖任何 CI 结果；本地验证通过即可提交。
5. **提交与 PR**：在分支上 commit → `git push -u origin <branch>` → `gh pr create`（`GH="/c/Program Files/GitHub CLI/gh.exe"`）。
6. **反空断言**：必须包含反向对照（人为破坏后断言必须变红）；本仓有 tautological 守卫（禁 `assert True` / `or True`）。

## 可用 skills

prompt 中引用的 skills 分两类：

**本仓内已核实存在**（`agent/skills/`）：
`wayfinder`、`to-spec`、`to-tickets`、`tdd`、`implement`、`code-review`、`diagnosing-bugs`、`codebase-design`、`domain-modeling`、`grilling`、`ask-matt`、`git-guardrails-claude-code`

**zcode 侧提供**（本仓不含，由宿主注入）：
`/goal`、`planning-with-files`、`gstack`（`/ship`、`/investigate`、`/browse`）

> ⚠️ gstack 的 `/qa` 与 `/review` 会 shadow 本仓的 `agent/skills/qa` 与 `agent/skills/code-review`。
> **本仓优先** —— 质量门与代码审查一律走本仓 skill。

## 编排流程

每个 prompt 都要求按本仓既有流程执行：

```
wayfinder（规划成 issue 地图 → decision tickets）
  → to-spec → to-tickets
  → tdd → implement
  → code-review（双轴 + 并行 2 subagent）
  → gstack /ship
```

## 交付物

每个 prompt 都要求把过程文档写入 `.agent-work/<goal>/`：

```
00-baseline.md            基线（含改动前实测数据）
00-decisions.md           架构决策（方向二为必需，含 A/B 选项裁决）
01-*.md                   侦察与问题定位
02-architecture.md        方案设计
03-work-breakdown.md      工作分解
04-test-strategy.md       测试策略
05-performance-budgets.md 性能预算
06-review-log.md          审查记录
07-final-verification.md  最终验证
```

## token 预算

每个 prompt 按 **10 亿 tokens** 的开发量规划。若在单次会话内无法收敛，prompt 要求：

- 以 `.agent-work/<goal>/progress.md` 作为断点续传锚点
- 每完成一个可验证里程碑即 commit（不要攒大提交）
- 在预算耗尽前，确保分支处于「可编译 + 测试绿 + 文档同步」的一致状态
