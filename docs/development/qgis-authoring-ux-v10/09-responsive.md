# 09 — 响应式（V9 基础上的 V10 增量）

V9 dock framework（compact<1100/normal/wide≥1600/ultrawide≥2200 +
resizeDocks 策略 + 地板）零重写。V10 增量：

* **1366×768 工具面身份**（视觉 QA 状态 `compact_1366_toolbar_identity`）：
  Qt overflow 收纳是呈现行为；断言动作身份（QAction 仍在 controller）与
  结论一致（`action.isEnabled() == availability.enabled`）不因收纳漂移。
* 状态条读数在窄宽下省略（`_elide_label` 168px 上限 + tooltip 全文）。
* 阶段条/inspector/hub 的既有适配（V9）保持；1920/2560 由 V9 视觉 QA
  状态覆盖（wide/ultrawide）。
