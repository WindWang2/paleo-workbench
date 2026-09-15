# 08 — Stage Layer Policy（W-P，V13）

三阶段（FACIES_CALIBRATION / CONSTRAINT_FACTOR / INTEGRATED_COMPILATION）
profile/组模板/锁定组语义复用 V5-V11，未改。

## V13 修复：切换保留用户状态

1. **活动编辑目标恢复**：`_reassign_active_target` 顺序改为
   本阶段持久 `active_layer_id`（validator 探针确认图层仍在）→
   恢复；否则 profile 首个有图层角色 → 重算；均无 → None。
   此前无条件重算覆盖用户显式选择（切走再回丢失；工程重开同样丢）。
   「绝不跨阶段继承」不变——读的是本阶段自己的视图状态。
2. **图层级显隐/不透明度覆盖**：native 树勾选回声（echo 门内）与
   不透明度滑条（用户手势）落 `StageViewState.layer_visibility/
   layer_opacity`；程序化批量应用（stage visibility 推送、epoch 切换）
   不经此——阶段默认不被冻成用户覆盖。
3. 顺序不受 stage 切换影响（V11 语义，V13 测试再钉）。

## 交付覆盖

- `tests/test_v13_domain_contracts.py::TestStageStatePreservation`
  （往返恢复/死图层重算/覆盖层 roundtrip）；
- E2E save/reopen 步（tree+binding 不变）。

## 遗留

- 展开态 QSettings 按工程名（非工程文件）键控——重命名/复制工程丢失
  （V11 已知限制 D12，未修）；
- 组级 opacity echo 不存在（QGS 组无 opacity 概念，不伪造）。
