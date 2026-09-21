# 07 — 独立终审 findings(主审计员复核)

三路独立 reviewer(未参与开发)对 `origin/main...HEAD` 从零评审:**24 条**(P0=0 / P1×2 / P2×7 / P3×15)。
其中 2 个 P1 与 2 个 P2 系**本分支修复自身引入**,由独立终审发现并已修复(commit 450af0bc,另见 05)。

## P0:无。

## P1(均已修复)

| ID | 标题 | 位置 | 处置 |
|---|---|---|---|
| R-01 | #1449 deregister 闭包按引用捕获 submit() 栈局部 engine_token/done,worker 线程调用即 use-after-scope(经 closure_e2e_test 624+1 触发) | workflow_scheduler.cpp:39 | ✅ 改按值捕获 |
| R-02 | #1446 syncConstraint 在替换突变(nlohmann copy-and-swap 释放旧数组)后仍解引用 matched.lines[0] 读 constraint_kind → UAF,标准保存路径 | constraint_authoring.cpp:591/613 | ✅ hoist 到变异前 |

## P2(已验证并修复 5 项 + 归类 2 项)

| ID | 标题 | 处置 |
|---|---|---|
| R-03 | closeProject 的 Save 分支只提交图层工作副本,从不落盘工程文档 → #1446 的 constraint 登记被静默丢弃 | ✅ 走 save_open_project 管线 |
| R-04 | 保存路径只 flush 活动层,而 harvest 遍历全部层(缓冲几何可被写进文档且之后无法清除) | ✅ commitAllDirtyLayers |
| R-05 | close→open 后 active_facts_ 停在 engaged-empty → 下工程首层不再自动激活 | ✅ clear_active_layer() |
| R-06 | #1450 层位候选漏 stratigraphy.sequence_boundaries(Python 权威源)→ 典型工程 combo 仍空 | ✅ 补 scan |
| R-07 | D-01 姊妹路径 libs/qgis LayoutService::export_layout 仍反转 top-first 喂 setLayers | ✅ 同修 |
| R-08 | WorkerHost generation 极窄残留竞态(body 检查点被抢占横跨 shutdown+重启) | 归入 08(需 epoch 重构专项) |
| R-09 | project_controller workarea 段仍在 worker 调 host_.document()/读 host_ 成员 | 归入 08(控制器尚未接产品;join 纪律缓解) |
| R-10 | 测试钉住有洞(mirror 重排 dance 零覆盖、fingerprint 无 oracle 值、#1447 全层脏保护无测试) | 归入 08(补测试专项;#1446/#1447 已有主链测试) |

## P3(修复 3 项 + 归类 12 项)

已修:R-11 applyScaleRange 条件写残留 stale bound→无条件双写;R-12 layoutMapLayerOrder 注释纠正;#1448 matrix 死条件删除。
归类 08:约束编号按 role 计数/legacy 回退词表、行 id churn、role 回落 other、closeProject 不清 joint3D、fallback 闭区间/不认 0 禁侧、CMake 引用未提交文档(本 PR 随台账入库后消解)、#1443 顺带 schema 修正卫生。

## 复审结论

一致性:三个 reviewer 的 P1/P2 主结论一致(2×UAF 各被两个 shard 独立发现)。构建/ctest/self-check/gate 本地结果由主审计员复跑确认(终审只读约束,未复跑)。
