# 13 — Review Findings（V13）

## E2E 驱动发现并修复的生产缺陷（P0 级——真 stale 被掩盖）

1. **factor 新鲜度恒 UNKNOWN（真实 adapter）**
   `mapping_workspace/dependencies._evaluate_factors` 读
   `getattr(info, "run_id", "")`——`DataVersionRef` 无此字段（实为
   `producing_run_id`）→ run 输入恒空 → 诚实 UNKNOWN 恰好掩盖了
   应有的 STALE 判定。InMemoryCatalog 同构所以 V11 测试未暴露。
2. **`DataVersionRef` 缺 version_number**
   `_asset_current_version` 的 max-by-number 选择在 ref 上恒 0。
   additive 补字段（adapter 填真值；0=未知有兜底）。
3. **`_asset_current_version` 读 `version.id`**
   ref 字段是 `version_id` → 当前版本恒空 → `_check_pinned_versions`
   永远返回 CURRENT。**生产中 phase1/factor/integrated 的 stale 提示
   在真实目录下从未正确触发过**（fake 测试路径全绿掩盖）。
   修复 = version_id 读取 + 同号末位兜底。

三处同根源：**跨 seam 的形状假设用 getattr 默认值掩盖**。教训记入
审查清单：跨 port/ref 边界的字段访问应显式对齐类型（或测试覆盖
真实 adapter 形状）。

## 其余发现（修复）

4. `execute_ingest_plan` 报告吞掉显式 skip 的非重复项（agent 视角
   "1 imported, 0 skipped, 0 issues" 而 1 项消失）→ 计入 report.skipped。
5. `p2-attribute-*` mkdtemp 无工程路径失败后成孤儿 → 失败必清/收编清壳。
6. `_reassign_active_target` 覆盖用户显式阶段目标（W-P）。
7. 图层级显隐/不透明度用户手势不落 StageViewState（W-P）。
8. ghost-run 监控（audit._ALWAYS_PRODUCING / repair_ghost_runs）
   需要跟随 manual_edit 新词（双名覆盖）。

## 审视过但判定不修（记录理由）

- `agent/` legacy swarm stub：未接线、不破坏兼容；移除是独立清理 PR 议题；
- IngestPlanDialog 实体覆盖的"新建候选去重"：候选列表可能含重复井——
  低危（选错可改），留 UX 打磨；
- 组级 opacity：QGS 无此概念，不伪造 UI。
