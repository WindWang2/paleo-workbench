# 11 — Performance（M12/M14）

## 差分刷新（M12）

`_apply_tool_availability` 的 help 文本按 **ToolContext 签名**差分重建：
`explain()`（每工具一次求值 + 文本拼装，占刷新成本大头）只在签名变化时
执行；enable/visible/checked 每次照常应用（零漂移风险）。state_changed
风暴（单操作 ~30 次发射）不再重拼 45 个 tooltip。

## 结构性界（M14，测试钉住）

* `evaluate_all`（复杂上下文）均值 < 5ms（20 次均值断言）。
* 1000 层：全量树重建有界；**差分重载**（结构未变）远快于全清重建；
  `_sync_action_state`（evaluator + help 缓存 + 装饰 + 状态条）< 2s
  @1000 层（断言留 10x 余量）。
* pan/zoom 轻路径（V8 已建）：checked + 状态条，不触发全量求值——保持。
* 禁止模式（Goal §28）：selection→全要素扫描 / mousemove→拓扑求值 /
  pan→树重建 / tool update→工具条 widget 重建——现有路径无违反
  （评审 R5 复核）。

## 批量建层注记

结构变化（建层）本就 immediate 全量重组——用户逐层操作无风暴；程序化
批量（测试）经 disconnect 抑制。若未来出现程序化批量建层产品路径，需要
批处理 API（记录，非本方向范围）。
