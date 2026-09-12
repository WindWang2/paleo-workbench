# 13 — Known Limitations (V11)

## 1. 本 goal 显式未做

* M1–M5 原生拓扑编辑（顶点工具 v2 / 避免重叠 / 追踪 / 分割合并 /
  检查器 / Python 拓扑服务退休）——规格已物化，按 §8 逐 M 领取。
* committed* 增量回写通道、提交后台账对齐、编辑期台账冻结（需原生会话）。
* `GroupNode.expanded` 持久化迁移（仍在 QSettings/项目名 key，D12）。
* 死 API 清理（`set_group_visible`/`snapshot_bridge_tree`/`RoleRule`/
  `profile_group_order`/`flatten_for_render`）。
* Registry 缺口（MAP_SYMBOL/PENDING_REVIEW_AREA specs，D14-ws）。
* 旧 mapping page 的两套平行树（MapLayerTree/NativeLayerTree）收敛。
* Fallback 降级横幅持久化（现为一次性提示；阶段显隐 fallback 静默 no-op）。

## 2. 环境约束

* C++ 未走 CI——PR 需声明：bridge 0.7.0a0 在本机 MSVC 14.38 + conda Qt
  6.11.2 构建验证；Linux/CI 行为未验证。
* 已知环境失败（main 同现，非 V11 引入）：test_mapping_stage_ui 多测
  access violation；authoring_ux registry-flags（#1267 拥有）。
* 1000 层 native 发布用真实桥验证（单窗口单同步）；更大规模（10k/100k
  要素）未跑——结构性断言已覆盖调用数，计时预算按 #1278 未决处理。

## 3. 合并顺序要求

#1267 与 #1277 先合（两者 mergeable）。V11 在 `map_stack_service.cpp`、
`qgis_mirror.py`、`canvas_shim.py`、`composite_editing.py` 与之有文本交叠——
按语义取并集（V11 的窗口/修订/全树走查 + 他们的 locator/空集保护/delta
优化互补，无逻辑冲突）。
