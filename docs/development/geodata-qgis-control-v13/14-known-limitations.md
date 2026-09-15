# 14 — Known Limitations（V13）

按影响域列出本轮**明确未做/有意不做**的事项（非缺陷——缺陷见 13）。

## 数据/谱系

1. factor grid「活窗」：插值→保存之间 `.factor_grid.npz` 在 artifacts
   树未入库（staging lease 仅一路径）；崩溃窗口内重开工程该 grid 不可溯源。
2. artifacts 树持久文件（`<artifacts>/intermediate`、`derived/attr.zarr`）
   已登记但 payload 不在 catalog 存储布局——双存储位置待统一（V12 遗留）。
3. workflow checkpoint（%TEMP% paleo-workflow-runs）无按龄清扫；分类为
   EPHEMERAL（policy 表），不 catalog 化。
4. recompute 可执行 handler 仅 factor_map；prediction/fusion/map_compile
   计划可见（dry_run）但执行显式失败（无 handler 不虚构计算）。
   `data.recompute_stale` 对这些步骤返回 failed_run_ids + no-handler 消息。
5. EditSession 仍是宏非事务（多文件部分提交如实入账，无原子回滚）。

## QGIS/编图

6. 原生层编辑会话（镜像层几何编辑）与 catalog 版本提交之间无自动
   桥——图层数据"编辑→提交新版本"经工作副本手动流（E2E 步 9-10）；
   自动 capture→commit 是下一个 Goal 的接缝。
7. 图层重排/激活的 harness action 未加（域入口唯一且已测试：
   LayerGroupController.observe/register；agent 化需先解决
   CompositeDocument 生命周期注入）。
8. QGS 层对象上无 catalog id 自定义属性（有意——doc_id 唯一 join，
   防 QGS 外部编辑产生双权威）；跨进程消费 QGS 文件时需 Python 域在场。
9. 展开态按工程名 QSettings 键控（重命名/复制工程丢失，V11 D12）。
10. 组级无 opacity（QGS 概念缺失，不伪造）。

## UI

11. 井详情页 per-role 动作按钮组（设 primary/补角色/提交副本）未接
    （域 API 齐备）；版本导航仍在对话框域。
12. IngestPlanDialog 实体候选可能重复列出；大计划（>5000 项）截断
    仅 agent 路径有提示，UI 靠滚动。
13. impact 预览是同步计算（有界）；特大工程首次可能数百毫秒——
    未移 worker（后续按反馈）。

## 规模

14. lineage/impact 仍内存文档遍历（无 SQL CTE）；entity_staleness
    全量后过滤。10k 井由 V11 scale 护栏覆盖，更大规模 V14+。
15. usages 无持久化索引（每次线性扫内存权威集合）。

## 兼容

16. 历史 working_copy_commit run 与新 manual_edit 并存（监控双名覆盖；
    旧工程的 provenance 查询需同时查两个 operation）。
