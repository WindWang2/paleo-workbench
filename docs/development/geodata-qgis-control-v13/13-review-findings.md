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

## 独立对抗性审查轮（Phase 6，子 agent 全 diff 审查）

11 项发现全部处置（commit 18360589）：

**P1（3）**
1. IngestPlanDialog teardown 可销毁运行中的 QThread（UB）+ 5s GUI 冻结
   → cancel→quit→wait，超时走 finished→deleteLater 兜底；执行期计划只读。
2. `as_new_version` 决策在 execute 中静默消失（UI 提供、harness 接受、
   执行层丢弃）→ 纳入执行，有意绕过幂等（语义即"重复内容作新资产"）。
3. Inspector 地图用途对桥接 legacy 行键错（AssetView.id=res_… vs
   asset_…）静默为空 → `service.asset_id_for_legacy()` 公开解析。

**P2（6）**
4. 预订 RUNNING run 后 copy worker 拒绝 → 幻影 RUNNING 泄漏 → 预订前查忙。
5. impact 门 fail-open（计算异常静默放行破坏性操作）→ fail-closed。
6. `data.commit_working_copy` 恒另立新资产（与 UI/EditSession 语义分叉）
   → 缺省同资产升版。
7. composite「版本缺失」行不可达（get_version 抛错不返回 None）→
   except 分支。
8. `data.ingest` decisions 键大小写/分隔符静默不匹配 → normcase 归一。
9. intermediate_policy 无生产接线 → 诚实标注 advisory（测试 pin 口径，
   接线入 known-limitations）。

**P3（2）**：10. 执行期间计划可编辑（跨线程改决策）→ 面板禁用；
11. EditSession failed_count 计入 provenance 预订失败 → 只数失败提交。

审查确认无问题的角度：EditSession 补偿完整性、panel echo 早退路径
（基线即有）、旧工程 from_dict 兼容、register_layer 放置丢弃风险
（所有调用点均已守卫）、source_usage 并发、ingest skip-only 分块
行为。
