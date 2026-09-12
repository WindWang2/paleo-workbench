# 06 — Native Tree Transaction (V11, bridge 0.7.0a0)

## 1. 窗口语义

`begin_tree_update() → token` … `end_tree_update(token)`：

* 窗口内：全部画布同步挂起（pending 标记），revision 照常递增；
* 收口：一次全画布 sync + 一次 refresh（零中间帧、无闪烁）；
* token 配对（乱序/无 begin 抛错）；嵌套计数（内层收口不刷新）；
* shutdown 强制复位遗留窗口（客户端异常路径不永久挂起同步）；
* 失败语义：窗口内单调用仍可抛；end 总会收口——已应用变更保留，
  partial failure 由调用方经 revision/diff 对账。

## 2. revision

每次图层集同步（程序化 + 用户树编辑回声批次）递增。Python 侧：
`reconcile` 收口记录 `_applied_tree_revision`；面板回写丢弃
`revision ≤ applied` 的回声（02 不变式 3 的语义级回声抑制——
SuppressGuard 之外的第二道防线 + 窗口内竞态检测）。旧桥 payload 无
revision（=0 → 永不过期）。

## 3. 观测面

`runtime_facts` 新增 `tree_revision` / `canvas_sync_count` /
`tree_update_windows` / `tree_update_depth`——规模测试的结构性断言来源
（50 upserts = 1 sync；1000-layer publish = 1 sync）。

## 4. 附带修复

`applyTreePlacements` 不再 `expandAllNodes`（收起状态破坏，audit
D3-native）；返回 revision。`mirrorTreeOrderTopFirst`（全树走查）与
`mirror_order_top_first`（root-only legacy）并存。

## 5. Python 入口

`tree_transaction(stack)` 上下文管理器（能力感知：旧桥/无桥透明降级
为逐调用语义）。已接入 `LayerGroupController.reconcile` 与整次
`mirror_snapshot_to_stack` 发布。
