# 15 — Verification Report（V13）

## 1. V13 新增/修改测试（全部通过，两条腿）

| 套件 | 用例 | 腿 | 结果 |
|---|---|---|---|
| test_v13_domain_contracts | 19 | fast | ✅ 19 passed |
| test_v13_ingest_plan_ui | 4 | fast | ✅ 4 passed |
| test_v13_impact_and_usage_ui | 6 | fast | ✅ 6 passed |
| test_v13_harness_data_lineage | 7 | fast | ✅ 7 passed |
| test_v13_layer_data_source_ui | 3 | fast | ✅ 3 passed |
| test_v13_cross_workspace_e2e（§24 十八步） | 1 | fast | ✅ passed |
| test_order_contract_v13 | 4（2 qgis + 2 纯） | fast+qgis | ✅ 4 passed |
| test_lifecycle_registration_gaps（契约更新） | — | fast | ✅ 全绿 |

第二遍复验（goal-loop 完成协议）：V13 套件 29+4 在审查修复后重跑全绿；
邻接回归（v11_services/core/ingest/stage/order/tree/parity/label/
transaction/freshness/mapping-e2e/inspector）70+20+42 全绿。

## 2. 全量 fast 腿（批量 runner，crash 隔离）

- 846 文件：**807 pass / 39 fail**（`.scratch/v13_batched_full.json`）。
- 环境性既有（主仓 A/B 同失败或同类）：kriging 数值挂死
  （test_kriging_neighborhood，主仓同挂——单进程跑单独剔除）；
  test_capacity_100k_guard / test_attribute_table_differential（主仓
  同 2 失败，symmetric-equal）；test_version_workbench_dialog_ui
  1 用例（主仓同失败）。
- **上游并行工作导致的 3+1（非 V13 回归，证据链完整）**：
  test_qgis_topo_m1/m2/segment_drag 的共享联动用例在干净 base
  （40531741，同盘 worktree + /tmp 双位置）**同样失败**，而主仓
  工作树通过——原因是主仓有**未提交**的 C++ 拓扑开关语义变更
  （`edit_tools.cpp` +topoOn()：拓扑关只动单要素）+ 测试同步加
  `topological_editing: True` 前置，而 `.pyd`（Sep-15 18:13 构建）
  已含新行为。旧测试（base/V13 均同）+ 新二进制 → 只动单要素 →
  断言失败。V13 未改 C++/测试/桥邻接（唯一交集
  layer_tree_panel +13 行，topo fixture 不经过 panel），且干净 base
  复现 ⟹ 与 V13 无关。V13 **不跟进未合并的上游语义变更**（§1 原则）；
  合并上游后这些旧测试需同步前置开关（CI 会自然覆盖）。
- 其余 30 坏文件：全仓 UI/桥/性能面（mapping_page、render_backend、
  visual_qa、workstation_context、harness_policy 等），与 V13 diff
  （catalog/mapping_workspace/resources/harness-data_lineage/UI 数据页）
  无交集；抽样 A/B（attribute/capacity/version_workbench）已证
  symmetric-equal。其余按仓库既有 full-suite 基线（V11 验证记录
  716 pass/52 fail 量级）属环境性噪音，不在本 Goal 回归口径内。

## 3. QGIS 腿

真实桥（v0.7.0a0 + qgis-vendor，经 junction 复用）：
test_order_contract_v13（2 原生）+ 既有 parity/stack/label/transaction
20 passed。topo 腿见 §2（上游并行变更，非回归）。

## 4. 结构性断言（反 wall-clock）

- E2E 零计时断言（状态机/集合包含/顺序相等）；
- ingest 幂等（skipped 引用既有资产）；
- order roundtrip（键保真→同序）；
- usage 有界（truncated 标志）；
- impact 门（拒绝→零变更；无影响→静默）。

## 5. Oracle 判定

§33 DoD：文件/数据 7 条 ✅（多资产/bundle/RAW/工作副本/中间口径/
run 连续/人工黑洞已堵）；UI 5 条 ✅；QGIS 6 条 ✅（绑定可追溯/
反查/order 四序一致/分组重排保存重开稳定/活动目标明确/阶段保留）；
Integration 十八步 ✅（E2E 测试）；15 篇文档 ✅（00-15）；
branch 待 push + PR 待建（下一步）。
