# 09 — Verification Report

Base `412d8baf`（= 执行时 origin/main）· 全程 `-j4` 上限（resource
gate flock 之下）· 本地验证为 gate，未等待线上 CI。

## 1. 本地执行的验证（全部通过）

| 验证 | 载体 | 结果 |
|---|---|---|
| Python oracle 冻结回放 | `workspace.layer_control_oracle`（8 用例 / 61,394B fixture，含 str_below 第二分支、LIS、耗尽重排、usage 截断/降级） | 8/8 PASS |
| 结构规模断言 | `workspace.layer_control_scale`（1000 层键/diff/查询/run 上限） | 4/4 PASS |
| 控制平面契约（call-count） | `ui_composite.layer_control`（14 组：单窗口/最小 op/中止保基线/降级/绑定/观察校验/阶段保序/目标 fail-closed/presentation/1000 层） | 全部 PASS |
| save/reopen 保序 E2E | Round-2 探针：observe 拖拽 → re-reconcile → to_json → from_json → `placement_of` 保留 `user.1` | PASS |
| 环注册表去重 | Round-2 探针：user.A↔user.B 环 → 全树各节点恰挂 1 次 | PASS |
| 混带科学序 parity | Python/C++ 对照（qc_warning…base_reference 五角色混 sub_order） | `l0 l4 l3 l2 l1` 两侧一致 |
| fixture 确定性 | 生成器两次运行 | byte 一致 |
| data 闭包构建 | `PWB_BUILD_DATA=ON`（域/工程/工作区/目录/摄取 + 工具）via resource gate | 100% Built |
| 基线 A/B | clean `origin/main` worktree 同配置 | 复现 `tests/cpp/data` 平台链接配置失败 → 判定 main 既有（非本线引入） |

运行命令（Qt-free，无需 Qt/QGIS）见 05 §4。

## 2. 审查验证（两轮独立 review，P0/P1 清零）

- **Round 1（架构/正确性）**：审查者自行编译运行三套测试后对照 Python
  oracle 与 vendored SDK 审查。5×P0 + 7×P1 全部修复（str_below 移植
  UB、band 排序倒置、takeChild bool、子树/registry 桥保护缺失、
  namespace 等）。07 §Round-1。
- **Round 2（对抗/性能/生命周期）**：151,080 案 diff+applier 穷举、
  planner 环探针、save/reopen 端到端探针。1×P0 + 2×P1 + 4×P2 全部
  修复（remove_groups_except 子层丢失、save 采纳不持久、export join
  key）；3×P3 修复、其余记档 08。07 §Round-2。

## 3. 未覆盖（如实申报）

- QGIS/平台 TU 编译与 Qt 真窗口 E2E（本机无 vendored SDK）——08 §3；
  首次 SDK 环境清单见 05 §3。
- ASan/UBSan 未跑（同因）；Qt-free 核心无裸内存操作。
- 线上 CI 未运行、未等待（按 Prompt：本地验证为 gate）。

## 4. DoD 对照（Prompt §19）

| 要求 | 证据 |
|---|---|
| QGIS 是运行时树权威 | 02 §0/§2；applier 只经稳定公共 API 改树 |
| 领域元数据与 QGIS 状态分工 | 绑定/组语义在 workspace；QGIS 只存 join key + 组 id 投影 |
| 数据版本 ↔ 图层双向 | `source_usage`（oracle 回放）+ membership 正向 |
| active/edit/tool target 一致 | `LayerTargets` 不变量组 + fake-stack 断言 |
| 组/重排统一事务 | 单窗口 call-count 断言；中止保基线测试 |
| 阶段切换不毁序 | 键稳定性断言（层键永不改写） |
| tree/canvas/label/legend/layout parity | top-first 单一契约 + 命名转换助手 + export_vector 树序修复 |
| 1000 层可操作 | scale/call-count 双测试 |
| save/reopen 不反序不丢组 | E2E 探针 + 树持久化 roundtrip |
| fallback/degraded 诚实 | 降级 no-op + 原因记录测试 |
| 无 Python 生产依赖 | 全部新代码为 C++；Python 仅 oracle/生成器 |
| #1434 overlap 避让 | 01 矩阵；canvas_shim 正交修复已声明 |
| P0/P1 清零 | 07 两轮处置表 |
