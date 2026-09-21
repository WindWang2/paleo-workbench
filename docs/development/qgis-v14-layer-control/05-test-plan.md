# 05 — Test Plan

## 1. 已落地的测试（本机全绿）

### workspace.layer_control_oracle（8 用例，冻结 Python 产品回放）
fixture：`workspace_tests/fixtures/layer_control_oracle.json`（61 KB，由
`tools/oracle/generate_layer_control_fixtures.py` 从真 Python 产品生成）。
- `key_primitives_parity`：索引键/序列/between/after/before/耗尽/校验。
- `assign_keys_for_order_parity`：12 案（fresh/LIS 保键/单拖中点/头尾
  pending/向下拖/逆序重键/None 过滤/耗尽重排/超长重排/空）。
- `role_bands_parity`：33 角色带 + 未知回落 150 + factor 秩 + band_sort_key。
- `layer_tree_model_parity`：遍历/父子/roundtrip/flatten_for_render。
- `tree_from_nodes_parity`：桥节点→观察快照。
- `tree_diff_parity`：6 案（相同/组内换序 LCS/跨组移动/建删改态/组搬家/
  根级换序）最小操作集逐一比对。
- `source_usage_parity`：7 个 version 查询（含 truncated 上限、无 project、
  空 id、include_runs=false）+ 6 个 asset 查询（含无 catalog 诚实降级）。
- `stage_view_behavior_parity`：effective/record（clamp 0.05–1.0）/reset。

### workspace.layer_control_scale（4 用例，结构断言）
- 1000 层 fresh 键定宽不增长；单拖 ≤1 键变更；全逆序受重排阈值约束。
- 1000 层 diff：同树 0 op；单交换 ≤2 move；全逆序 ≤999 move；10 轮
  shuffle 全管道 < 5s。
- 1000 层 × 20 组树查询有界。
- usage run 上限 100 + truncated 如实。

### ui_composite.layer_control（14 组 fake-stack 检查，全部通过）
单事务窗口/幂等 reconcile/skipped 中止保基线/桥异常保基线/降级诚实
no-op/无栈全降级/注册绑定 V13 默认 kind/观察校验+重键/阶段切换保序+
目标重指派/rematerize 失败不中断切换/用户组上提/副本紧邻/目标模型
fail-closed+删除重验证+漂移报告/presentation 词汇/1000 层 call-count。

## 2. 分类覆盖对照（Prompt 测试要求）

| 类别 | 载体 |
|---|---|
| domain/unit | oracle 回放 8 + fake-stack 14 组 |
| negative/fail-closed | skipped 中止、桥异常、降级、目标 preflight、耗尽异常、未知角色/阶段回落 |
| persistence/save-reopen | 状态 roundtrip（codec 既有 + tree to/from_json parity）；平台 save 写回 `mapping_workspace`（glue，见 §3-QT） |
| old-project compatibility | codec 既有 fallback 用例（tests/cpp/data）+ plan 的 legacy 路由（fake-stack 覆盖 root 路由） |
| concurrent/lifecycle | 事务窗口异常路径收口、目标重验证、组生命周期 |
| cancellation/late-result | 降级 + revision 对账（echo_is_stale fake-stack 路径）；桥 late-echo 既有测试 |
| scale 结构断言 | 1000 层 call-count + diff/键规模上界 |
| performance baseline | 06（wall-time 仅作 sanity，结构断言为主） |
| cross-module E2E | 平台 glue 链（openProject→reconcile→stage→save）——本机不可编，见 §3 |
| oracle/parity | 61KB 冻结 fixture，Python 生成 |
| ASan/UBSan | 未跑（环境无编译平台闭包）；Qt-free 核心无裸内存操作，见 08 |
| Qt offscreen / QGIS 真 SDK | 本机无 vendored SDK；QGIS 侧 TU 不可编译——见 §3 与 08 |

## 3. 待 SDK 环境执行的验证（如实申报）

- `pwb_ui_composite_qgis`/`pwb_qgis`（layer_tree_stack.cpp）编译 +
  `QgsLayerTreeStack` 冒烟（组 upsert/放置/窗口/快照）。
- 平台 glue 编译 + openProject→reconcile→stage→save→reopen E2E
  （Prompt §17 场景 1–20 的 Qt 真窗口路径）。
- `export_vector` 树序修复的 SVG/PDF 与屏幕一致性（复用
  test_qgis_screen_export_parity 模式扩展）。

## 4. 运行方式

```bash
# Qt-free 核心（无需 Qt/QGIS）
cmake -S . -B build -DPWB_BUILD_DATA=ON -DPWB_BUILD_MAPPING_KERNEL=ON \
      -DPWB_BUILD_PLATFORM=OFF -DBUILD_TESTING=ON   # 注意 tests/cpp/data
                                                    # 平台链接为 main 既有
                                                    # 配置问题（08 §5）
ctest --test-dir build -R workspace
# 手编直跑（本机实际执行的路径）：
g++ -std=c++20 ... workspace_tests/*.cpp workspace/src/*.cpp domain/src/*.cpp
```
