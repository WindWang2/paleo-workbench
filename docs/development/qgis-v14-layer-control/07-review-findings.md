# 07 — Review Findings & Disposition

两轮独立 review（按 Prompt 要求的两类：架构/正确性 + 对抗性/性能/生命周期）。
发现与处置全记录；P0/P1 修复后零残留。

## Round 1 — 架构/正确性（独立 agent，可执行验证）

审查者实际编译并运行了三套本地测试后再审（8/8、4/4、composite 全过）。

### P0（5 项，全部修复）

| # | 发现 | 修复 |
|---|---|---|
| 1 | `str_below` 移植错：递减错字符、pad 差一、空串 UB（`key_before("zaa")` abort；会产生 `` ` `` 非法字符污染持久化树）。oracle 原用例未覆盖第二分支所以未暴露 | `substr(0, stripped_len+1)` + pad `rest.size()-stripped_len-1`；generator 补 `zaa/baa/abca` 与 `x/xaba` 等第二分支用例，fixture 重生成（61394B），回放全过 |
| 2 | `default_layer_sort_key` 十进制字符串拼接 → 混位带序倒置（`"150/…" < "20/…"`；qc_warning 应在 base_reference 之上却排其下）。可执行对照证实（Python `qc1,well1,base1` vs C++ `well1,base1,qc1`） | 改用 `band_sort_key`/`BandSortKey` 元组比较；新增用户组混带 parity 验证（`l0 l4 l3 l2 l1` 两边一致） |
| 3 | applier `takeChild` 返回值当节点用——本仓 vendored SDK 中 `takeChild` 返回 `bool`，`QList<QgsLayerTreeNode*>` append bool 是编译错误 | 不再使用返回值（指针本已在手） |
| 4 | applier 子树搬家缺两道桥验证过的保护：`removeChildrenPrivate` 递归卸载嵌套子树会摧毁嵌套用户组；`takeChild` 期间 registry bridge 无条件收集图层 id（#1154 整组蒸发） | 从 `map_stack_service.cpp` 逐行移植 `detachGroupSubtree/restoreGroupSubtree`（后序卸载）+ `RegistryBridgeDetach`（断接重接）到全部三处 takeChild 舞步 |
| 5 | `main_window.cpp` 两个 V14 函数定义在 `} // namespace pwb::app` 之后——编译错误 | 移入 namespace 内 |

### P1（7 项，全部修复或落实）

| # | 发现 | 处置 |
|---|---|---|
| 6 | oracle fixture 未提交（审查者验证时生成又删除） | 已重新生成并随 PR 提交（`workspace_tests/fixtures/layer_control_oracle.json`） |
| 7 | `test_stage_switch_survives_rematerize_failure` 空转（无 reconcile 基线，throw 路径未触发） | 测试先 reconcile 建基线再置 throw |
| 8 | `ensure_memberships` 幽灵清理对部分组合快照是破坏性写（非 GeoJSON/已删版本的 membership 会被清并随 save 持久化） | 新增 `full_composition` 参数（默认 true=Python 语义）；平台 glue 显式传 false（部分组合下绝不清理） |
| 9 | 用户树编辑无写回路径（拖拽会在重开时回退）+ targets/stage resolver 未接线 | glue 接 resolver/validator/revalidate；`syncLayerControlOnSave` 前 `observe_tree_nodes(tree_snapshot_nodes())` 采纳用户结构编辑（经同一角色校验）；实时 model 信号写回记为 Prompt-2 接入点（08 §2） |
| 10 | `role_is_raw_protected` 少 2 角色（factor_grid/factor_classification） | 对齐 `layer_roles.py ROLE_RAW_PROTECTED` 全 7 角色 |
| 11 | presentation flag 词汇偏离冻结契约（`unbound/binding_unknown` 不在表内；缺 `role:<v>`；`bound_to_asset_only` 命名错） | 只发冻结词汇 + `role:<v>`；结构体布尔字段承载绑定状态；改名 `bound_by_fingerprint` |
| 12 | applier 用 `qobject_cast`——桥 M2T3 实证 vendored 构建下不可靠 | 全部改 `nodeType()` 枚举 + `static_cast` |

### P2（9 项：修复 3、记档 6）

- **修复**：键稳定性断言加强过程中发现真实语义——stage 切换会物化/隐去**空系统组**（键模板派生、确定性），层键必须永不变；断言改为区分两者（并暴露了 phase2.analysis/constraints 的正确物化行为）。
- **修复**：`layer_exists_now` 头注释与行为矛盾——注释改为如实描述（无探针保目标；平台恒接探针）。
- **修复**：stage validator 异常逃逸 → try/catch 归 false（Python parity）。
- 记档：`bound_at` 写侧时间戳语义与 Python caller-verbatim 分歧（沿用 conv-26 既有 `mutations.cpp` 行为，08 §4）；`placement_of` 无 membership → legacy 组（=Python `home_group_for_role(None)`）；diff 输出因 std::map 键序与 Python 插入序不同（applier 顺序不敏感，benign）；`build_index` const 内铸造组 id（QGIS 侧唯一副作用点，注释声明）；map/QMap 序 diff（byte 级 fixture 对比时需注意）；`export_vector` 导出**集合**同时收紧为仅镜像层（与桥 #1385 语义一致的行为变化，见 04）。

## Round 2 — 对抗性/性能/生命周期（真实执行，修复后代码）

审查者先编译运行了三套测试（8/8、14/14、4/4 全过）、验证 fixture
确定性（两次生成 byte 一致），并写了三个对抗探针：对 diff+applier
take/insert 语义做了 **≤6 节点全排列 × 组/层掩码 151,080 案**的穷举
验证、planner 环探针、save/reopen 端到端探针。

### P0（1 项，已修复）

| # | 发现 | 修复 |
|---|---|---|
| R2-1 | `remove_groups_except` 误用卸载舞步：`detachGroupSubtree` 把被删组的**直接子节点也一并卸下**（后序卸载语义），随后 `group->children()` 恒为空 → 上提循环成死代码、无 `restoreGroupSubtree` → 被删组的子层**丢失**（树中消失），且后续 reconcile 的 placements 找不到节点 → skipped>0 → **每次 reconcile 永久中止循环**。FakeStack 无子结构所以测试未覆盖 | 逐行移植桥原版：doomed 列表自底向上收集；层子节点 takeChild+addChildNode 上提；组子节点额外走 detach/restore 保护舞步（takeChild 递归剥离后代的 SDK 语义已从 vendored 源码 `qgslayertreenode.cpp:298-343` 证实） |

### P1（2 项，已修复）

| # | 发现 | 修复 |
|---|---|---|
| R2-2 | save 前 `observe_tree_nodes` 只改运行时表——`state.tree` 仅由 reconcile 写，用户拖拽在重开时依旧回退（探针实证：reopen 后 `placement_of(draft1)` 回落 home） | glue 记录组合快照成员；observe 成功后**重新 reconcile（不 force，diff 恰为用户最小移动集）**再持久化；端到端探针验证 reopen 后 `user.1` 保留（E2E PASS） |
| R2-3 | `export_vector` 过滤用 `pwb/doc_id`，而 V14 打开路径经 `layer_adapter` 只写 `pwb/layer_id` → 导出集为空/缺失且返回成功；`layerOrder()` 空时静默导出白图 | join key 改 `layer_adapter::layer_id_of`（legacy 出参兼容）；导出集空 → 诚实返回错误串中止 |

### P2（4 项：修复 3、记档 1）

- **R2-4（修）** 展开态持久化断裂（expand_states 无写入方、树载入忽略 expanded）→ `load_placements_from_state` 收集持久化展开旗标为恢复默认层。
- **R2-5（修）** 环提升产生重复挂载（user.A↔user.B 各挂 3 次、层挂 2 次）→ 提升时同步从旧父子序表移除；探针验证全树各节点恰挂 1 次（PASS）。
- **R2-6（修）** 打开路径 reconcile 无宿主守卫（异常逃逸进 Qt slot）→ try 包裹，控制面降级、打开继续；save 侧 re-reconcile 同样守卫。
- **R2-7（档）** diff 的兄弟序依赖「实际树中无 desired 外的陈旧节点」这一宿主义务（Python 同源继承）；见 08 §6。

### P3（8 项：修复 3、记档 5）

- 修：`TreeTransactionWindow` move-assign 先 close 旧窗口；`reassign_active_target` 对未知持久化阶段防御（不再解引用 optional）；测试诚实度（FakeStack token 校验、首次 reconcile placements == 1、键稳定性断言区分层/组并要求层键在场）。
- 档：root 级 O(R²) 去重（Python 同源、root 节点数有界）；`key_of` 无键回退 id（Python 同源不一致，root by_key 路径两侧均不触发）；root 新层尾部/用户组新层头部方向怪癖（Python 忠实移植，测试注释如实）；`ensureGroupNodeId` 铸 `user_<uuid>`（桥继承词汇）与契约 `user.` 前缀差异；08 文档当时未写（本 PR 补齐）。

### 审查者证实的通过项（摘）

`str_below` 第二分支（oracle 新用例覆盖 za­a/baa/abca 全过）；元组
BandSortKey 序；LIS/LCS patience 移植（穷举正确）；applier 升序放置
+组先于层的 take/insert 序（当实际树==diff 基线时穷举正确）；
`reconciling_` RAII 复位；`register_layer` created_at/created_stage
保留；`remove_user_group` 上提 ≡ Python；幽灵清理豁免逐字节对齐；
用户解锁跨重复 stage 切换存活；LayerTargets fail-closed 全组；中止保
基线且窗口闭合；fixture 确定性。

**最终计数：P0 = 0，P1 = 0（两轮全部清零或以探针/移植证据处置）。**
