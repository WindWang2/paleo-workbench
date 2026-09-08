# 06 — Performance（性能与稳定性证据）

> Gate 原则（Goal §9）：call-count / rebuild-count / 复杂度比，不用绝对毫秒。
> 探针实现：`tests/test_v7_stability_probes.py`（headless，本机必绿）+
> `tests/test_qgis_v7_authoring.py`（QGIS 腿，桥构建后执行）。

## 1. Evaluator / ToolContext（纯契约层）

| 探针 | 规模 | Gate | 结果 |
|---|---|---|---|
| `test_evaluate_all_constant_in_selection_size` | selection 10 vs 100,000 | 时间比 < 4×（10000× 规模差） | 通过（O(1) w.r.t. 选集规模） |
| `test_evaluate_all_covers_registry_each_call` | 30 工具 | 每次评估覆盖全注册表 | 通过 |
| `test_100x_tool_state_resync` | 100 次 `_sync_action_state` | 无状态累积错误；enabled/checked 正确 | 通过 |

## 2. EditDelta / 会话层

| 探针 | 规模 | Gate | 结果 |
|---|---|---|---|
| `test_journal_memory_bounded_at_scale` | 3020 次编辑 vs 上限 1024 | `len(deltas) <= 1024` | 通过 |
| `test_undo_depth_unchanged_by_delta_stream` | 50 次属性编辑 | undo 栈 51（1 add + 50 change），delta 流零额外命令 | 通过 |
| `test_session_operations_scale_gracefully` | 1k / 10k / 100k 要素 | 构建后 move×20 有绝对上限保险丝（<5s，回归绊线）；delta 有界 | 通过（100k 构建为线性一次成本，单要素操作 O(1) 命令） |

## 3. 工具/图层切换稳定性（headless 腿）

| 探针 | 规模 | 结果 |
|---|---|---|
| `test_100x_activate_deactivate_cycle` | 100 次激活/去激活 | 通过；活动工具与会话状态一致 |
| `test_esc_cancels_active_tool_after_cycles` | 循环后 Esc | 通过；采点取消、工具保持激活 |
| `test_50_layer_switches_keep_single_active` | 50 图层切换 | 通过 |
| `test_selection_semantics_at_10k` | 10k 要素选集 | select_all/invert/toggle 全量正确 |

## 4. 帧级链路回归防护

- P1-5（Review 1）：`tool_context_inputs` 的选集几何类型从 O(全部要素) 修正为 O(1)（图层 kind 权威）——`extent_changed` 帧级链上的回归已消除并有基线断言。

## 5. QGIS 腿（PALEO_REQUIRE_QGIS=1；桥构建后补充执行证据）

- [ ] 桥 `capability_manifest()` 调用计数（零 QGIS init 成本）
- [ ] 原生 measure 回调 payload 尺寸/频率
- [ ] endpoint/intersection 下推后的 `setSnappingConfig` 接受性
- [ ] vendored QGIS 构建：2997 编译目标 @ -j2，全程 RAM 峰值 ≤ 机器上限（31.2GB）
