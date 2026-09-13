# 03 — 验证（V12-C）

## 1. 验证环境

| 通道 | 说明 |
|---|---|
| **主通道（门禁）** | 仓库既有的 worktree 测试封装 `run_env.sh`：miniconda CPython 3.13、`QT_QPA_PLATFORM=offscreen`、`LIBGL_ALWAYS_SOFTWARE=1`、共享 main worktree 的 geo-viz-engine 子模块、**无 QGIS 桥**（.so 为 cpython-312 ABI）——与提示词要求的 Fallback 无桥验证模式一致 |
| 基线通道 | BASE 检出（`main/`，干净于 `926f3335`）+ 其配套 venv（CPython 3.12.13），跑 `bench_baseline.py` 量 BASE |
| 附加证据通道 | 同 venv + `PYTHONPATH=<worktree>:<main/native/qgis_render_bridge>`：**BASE 版预构建真桥**（本机既有产物，未重新编译——本 Goal 零 C++ 构建）在场跑拓扑/渲染测试 |

> 说明：worktree 自建 venv 因网络持续超时未成（`editables` 等构建依赖拉不下来）；
> 改用仓库 canonical 的 `run_env.sh` 通道。所有提交前测试都在该通道跑绿。

## 2. before / after 实测（同脚本：`bench_baseline.py`，600×450 网格，30 帧平移）

| 指标 | BASE | V12-C | 变化 |
|---|---|---|---|
| 纯 Python payload 绘制 median ms/帧 | 15.52 | **0.72** | **-95%** |
| native payload 绘制 median ms/帧 | 1.15 | 0.77 | -33%（余量为合成管线本身） |
| `rasterize()` 调用 / 帧 | 1.0 | **0.033**（=30 帧仅首帧 1 次） | 稳态 **0** |
| 全幅拷贝 MB / 帧 | 2.06 | **0.07**（同上，仅首帧建缓存摊销） | 稳态 **0** |
| `_prepared_layer` 重复调用（无变化） | 0.17 µs（基线已缓存） | 0.17 µs（不变；目标②基线已达成，见 01 §2） | — |
| `validate_records` 桥调用数（N=50/200/1000，fake 批量桥） | 50 / 200 / 1000 | **1 / 1 / 1** | N→1 |
| `validate_records` 桥调用数（BASE 真桥） | N | N（探针不支持 → 回退，行为不变） | 见 §5 |

## 3. 测试证据（主通道，`run_env.sh`，只跑相关文件）

| 文件 | 结果 |
|---|---|
| `tests/test_render_increment_v12.py`（新，20 用例：矩阵+反向对照） | **20 passed** |
| `tests/test_topology_batch_v12.py`（新，11 用例） | **10 passed, 1 skipped**（真桥用例无桥自跳） |
| `tests/test_mirror_cache_reset_v12.py`（新，2 用例） | **2 passed** |
| `tests/test_map_render_backend.py` | 17 passed |
| `tests/test_render_engine.py` | 11 passed |
| `tests/test_fallback_render_incremental.py` | 7 passed（2 行机械适配 `latest()`） |
| `tests/test_mirror_lifecycle_v11.py` | 22 passed |
| `tests/test_mirror_delta_publish.py` | 15 passed |
| `tests/test_mirror_fields_sig.py` | **1 failed — 既有失败**（`test_fields_json_signature_change_forces_republish` 在 BASE 同点同断言红，已实测复现于 `main/`；fields token 特性 BASE 即缺失，非本 Goal 引入，不修） |
| `tests/test_layer_tree_diff_v11.py` | 13 passed |
| `tests/test_mirror_capability_probe.py` | passed |
| `tests/test_topology_service.py` | passed |
| `tests/test_map_render_backend_patterns.py` / `test_render_engine_review_fixes.py` / `test_unified_map_visual_regression.py` / `test_issues_822_render_thread.py` | 全 passed |
| `tests/e2e/test_integrity_guard.py`（tautological 守卫） | **passed** |
| `tests/perf/test_mirror_publish_scale.py` | **未跑**（Goal 禁全量 perf；其中 `[50]` 基线已红为既有失败） |

**附加证据通道（真桥在场，CPython 3.12 + BASE 版 .so）**：
`tests/test_topology_batch_v12.py` **11 passed**（含 `test_real_bridge_without_batch_uses_fallback`：真桥实测 `validate_many` 不存在 → 探针 None → 逐要素回退，GEOS 判词正常）；
`tests/test_map_render_backend.py` **17 passed**。

## 4. 渲染等价性声明

**无像素变化**。论证 + 证据：
- 标量栅格：像素唯一来源仍是 `rasterize()` 的字节；缓存的 QImage 与旧路径每帧新建的 QImage 字节相同，`drawImage` 目标矩形/变换提示未动。测试 `test_scalar_grid_reuses_qimage_across_frames_and_stays_pixel_identical` 断言 **缓存路径帧与全新后端直渲染帧逐字节相等**。
- 几何不变场景的像素恒等：可见性往返（`test_visibility_roundtrip_keeps_prepared_entry`）、undo 回到相同几何（`test_undo_redo_rebuilds_and_restores_geometry_pixels`）均断言帧字节级一致。
- 既有像素级护栏全绿：`test_fallback_render_incremental`（#391 平移逐像素等价族）、`test_unified_map_visual_regression`、`test_map_export_consistency` 所属家族未受影响（相关文件通过）。

## 5. 缓存失效矩阵（7 场景 × 测试名 × 反向对照）

| # | 场景 | 正向测试（断言失效/复用正确） | 反向对照（破坏键→断言陈旧被服出） |
|---|---|---|---|
| 1 | 改顶点 | `test_vertex_edit_invalidates_prepared_and_changes_pixels` | `test_negative_control_broken_prepared_key_serves_stale_geometry` |
| 2 | 增/删要素 | `test_feature_removal_invalidates_prepared_and_changes_pixels` | 同 #1 机制（同一键） |
| 3 | 改样式（不动几何） | `test_style_change_reuses_prepared_geometry`（帧变+零重建） | `test_negative_control_broken_frame_key_serves_stale_style` |
| 4 | 可见性/不透明度 | `test_visibility_roundtrip_keeps_prepared_entry` | 同 #3 对照（帧键 visible 恒真→隐藏层不消失，同用例断言） |
| 5 | 切换图层/文档 | `test_layer_switch_prunes_prepared_entries` + `test_scalar_grid_layer_switch_prunes_cache` | `test_negative_control_broken_prune_*`（prepared/scalar 两件） |
| 6 | 切换 CRS | `test_crs_switch_reprojects_through_new_cache_entry` | `test_negative_control_broken_reproject_key_serves_stale_projection` |
| 7 | undo/redo | `test_undo_redo_rebuilds_and_restores_geometry_pixels` | 同 #1 机制（修订键对照覆盖） |
| 8+ | scalar 数据/样式变更 | `test_scalar_grid_data/style_change_invalidates_cache` | `test_negative_control_broken_scalar_key_serves_stale_pixels` |
| 9 | scalar payload 侧修订 | `test_scalar_grid_payload_revision_alone_invalidates_cache` | 同 #8 机制 |
| 10 | scalar payload 对象替换 | `test_scalar_grid_payload_object_swap_forces_miss` | `test_negative_control_dropped_payload_identity_serves_previous_image` |
| M1 | mirror reset 清签名缓存 | `test_reset_publish_ledger_clears_signature_cache` | 用例内置前后对照（reset 前 len==1 / 后 len==0 / 重发布重签） |
| M2 | 栈回收三表同剪 | `test_stack_gc_purges_signature_and_raster_entries_with_ledger` | 同上（剪前非空/剪后空） |

## 6. 拓扑批量：调用数证据

- fake 批量桥：`test_batch_bridge_single_call_for_many_records` —— 50 条记录
  `many_calls == 1`、`validate_calls == 0`；批/逐结果全等
  （`test_batch_and_per_feature_paths_issue_identical_results`）。
- fake 老桥：`test_legacy_bridge_without_batch_keeps_per_record_path` ——
  `validate_calls == 50`（BASE 行为保持）。
- 异常/形状不符回退：三个用例（raise/short/not_list）各一次警告 + Shapely 兜底。
- 探针：参数名不符拒绝（`test_probe_rejects_...`）；pybind doc 声明接受
  （`test_probe_accepts_pybind_doc_style_declaration`）。
- 真桥（BASE .so）：探针 None + 逐要素 GEOS 判词照常（§3 附加通道）。

## 7. 并发预算记录

- 侦察阶段：1 条消息 2 个 Explore subagent（渲染路径 / mirror+topology）。
- 评审阶段：1 条消息 2 个 subagent（Standards 轴 / Spec 轴）。
- 全程未超过 2 个并发。
