# 00 — Overlap Audit（起点检查）

Data Fabric V11 开发前对仓库并行工作的重叠面审计。
审计时间：2026-09-12。审计人：data-fabric-v11 goal agent。

## BASE SHA

```
6c08fb7d8a9fa3e6276f335b2a7e583dcc5ec55a
Merge pull request #1253 from WindWang2/feat/qgis-spatial-layer-platform-v10
```

本地 `main` 与 `origin/main` 同步于该 SHA。#1267 / #1277 均 **未合并**（OPEN、MERGEABLE），
故本 Goal 以当前 main 为基线，不叠加它们的分支。

## 最近相关 merged PR（不重复实现）

| PR | 主题 | 与 V11 的关系 |
|---|---|---|
| #1254 | QGIS 原生矢量编辑 V10 | 无重叠（mapping/qgis 层） |
| #1253 | QGIS 空间图层平台 V10 | 无重叠 |
| #1252 | QGIS 制图 UX V10 | 无重叠 |
| #1232 | **Data & Runtime Foundation V6** — lazy catalog、事务性 CAS、payload lease、working-copy 生命周期、恢复、session guards | **直接前置工作**。V11 的 working copy / 崩溃恢复 / lease 语义在此基础上演进，不重写 |
| #1212/#1211/#1218–#1222 等 catalog 修复系列 | 10 万级打开、working copy 覆盖保护、GC 竞态 | 前置修复，V11 保持其语义 |
| #1249 | 地质解释与编修工作台 V9（MapProduct 生命周期、CompilationInputSet） | 部分前置：成果 freeze/publish/supersede 已 catalog 化 |

## 当前 open PR

### PR #1267 — `fix(v10): 修复 review #1255–#1264 确认的 10 个问题`（branch `v10-review-fixes`）

- **Owner**：#1255–#1264（全部为 QGIS 映射/矢量编辑工具修复：action_registry 词表、捕捉定位器失效、undo 单元、provider_writable、性能门禁、health 探针、路径硬编码、拓扑错误计数）。
- **涉及文件**：`mapping/`、`ui/map_action_controller.py`、`ui/qgis_stack/`、`qgis_runtime/health.py`、`qgis_runtime/paths.py`、`native/qgis_render_bridge/`、若干测试。
- **与 V11 重叠**：**零核心重叠**。不含 catalog / project domain / data manager 文件。
- **V11 决策**：完全不触碰 #1255–#1264 范围；合并顺序无约束。

### PR #1277 — `fix: converge deep review findings across workstation, QGIS and data workflows`（branch `review-convergence-20260912`）

- **Owner**：#1265–#1276（含 #1265 POSIX loader 崩溃、#1266 tautological 断言、#1268 编辑会话跨层提交、**#1269 Data Manager 分页模式仍在 GUI 线程 list_assets() 全量物化**、#1270 砂地比单位、#1271 freeze pins、#1272 属性表全量物化、#1273 RAW editable、#1274 theme lambda、#1275 插值诚实性、#1276 捕捉配置）。
- **涉及文件（与 V11 有交集的）**：`catalog/db.py`、`catalog/service.py`（#1269 引入 `list_asset_identities` 3 列 SQL）、`project/well_identity_adapter.py`、`ui/pages/data_page.py`、`workflow/factor_*`、`workflow/integrated_compilation.py`。
- **与 V11 重叠**：**真实重叠点 = #1269**（Data Manager 分页读取面）。V11 的 Data Manager 实体树重构会重写 `data_page.py` 的读取面，天然涵盖"分页模式不做全量物化"这一诉求；#1277 其余部分（QGIS 编辑会话、算法修复、属性表虚拟化）与 V11 核心无重叠。
- **V11 决策**：本 Goal 基于 main 开发，**不 cherry-pick、不复制 #1277 的补丁**；V11 的实体视图/分页服务自带轻量身份查询（等价能力、独立实现，避免对未合并分支的依赖）。两个 PR 若先后合并，`data_page.py` 读取面以 V11 版本为准（功能超集）；`catalog/db.py` 若冲突，V11 保留双方 SQL 能力。已在 PR 描述中声明。

## 当前相关 issues

- **#1278（OPEN）+ 子 issue #1279–#1286（全部 CLOSED）**：拓扑编辑地图 —— 相图编辑迁移 QGIS 原生拓扑编辑的 wayfinder 规划（决策+研究），产出 `docs/specs/topological-editing-migration-spec.md`，实施按 M0–M5 里程碑另行领取。
  - 与 V11 的关系：**不同 effort**。其关注 QGIS 拓扑编辑（顶点工具/分割/合并/检查器）；V11 关注数据资产图。边界接触点：#1278 的 Out-of-scope 明确"RAW/模型结果层开放直接编辑——门禁语义不变，继续走「复制为草稿」"，与 V11 §10 working-copy 原则一致，无冲突。V11 不实现拓扑编辑；拓扑编辑的 M0+ 实施不依赖 V11 schema（user_vector_layers 是 project 文档层数据，非 catalog 管线资产）。
  - 子 issue #1283（存储与镜像同步通道）提到 user_vector_layers 真源与台账 —— 均在 project 文档层，不与 V11 的 DataAsset/DataVersion 体系交叉。
- **#1266 / #1265**（OPEN，ready-for-agent）：属 #1277 owner 范围（已在其修复清单内），V11 不重复修。
- **#1230**（OPEN，CI 策略）：流程性 issue，无代码重叠。
- 其余 open issues（#1255–#1264 系）均归 #1267/#1277 所有。

## 本 Goal 明确不重复实现的内容

1. #1267 的 10 项 QGIS 工具修复；
2. #1277 的 #1265–#1276 修复（尤其 #1269 的 `list_asset_identities` 具体 SQL —— V11 用自己的分页/身份查询服务覆盖同一诉求）;
3. #1278 拓扑编辑迁移的任何实施；
4. 已合并 #1232 系列已交付的：lazy catalog 打开、CAS 事务、staging lease、working copy 注册表/恢复 —— V11 只在其上演进（见 05-version-lifecycle.md）；
5. QGIS 桥/渲染栈的一切。

## 既有 owner 汇总

| 内容 | Owner |
|---|---|
| #1255–#1264 | PR #1267 |
| #1265–#1276 | PR #1277 |
| 拓扑编辑迁移实施 | #1278 规划下的后续实施会话 |
| Data Fabric V11（本 Goal） | data-fabric-v11 分支 |

## 基线结论

以 main @ 6c08fb7d 为基线创建 worktree `../paleo-workbench-data-fabric-v11`、分支 `data-fabric-v11`。
#1267/#1277 未合并，不作为基线；重叠面已在上文逐一登记。
