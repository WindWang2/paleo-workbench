# 03 — Payload Registration Protocol + GC Coordination（#1222, #1218）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 协议

所有锁外放置漏斗统一走（概念上的 PREPARE→COPY→HASH→FSYNC→VERIFY→METADATA COMMIT→PUBLISH）：

```
acquire_staging_lease(targets)          ← 租约行入库（目标=盘上目录前缀）
place_managed_file / place_blob         ← 锁外复制+流式哈希+fsync+temp+replace+只读位
locked: BEGIN IMMEDIATE + CAS + 行提交  ← 元数据事务（§02）
release_staging_lease                   ← 成功/失败皆释放
```

- 租约目标 = `<name>.artifacts/<STAGE_DIRS[stage]>/<asset_id>`（**盘上目录名**，评审 R3#1 修复：曾用 `stage.value` 导致 OUTPUT 全部失效）+ dedup 导入附加 blob 根。
- 已接线：`register_version`（含 blob）、`register_result_asset`、`import_raw`（主批量漏斗，评审 R3#2 修复）、`create_derived`、`promote_version`、adapter `_register_produced`、harness mapping npz。`register_derived_store` 的移动+提交全程持锁，由 sweep 的持锁复查天然保护。
- 地震属性：作业启动即取租约，`VolumeAttributeJob.on_band` 每 band 心跳（TTL 1h），on_done/on_fail/on_cancel 释放。
- GC（gc.py）：plan（auto+explicit）跳过租约前缀；死租约在 explicit plan 时修剪；**sweep 分块（64 项）持服务锁复查**——每块重取 referenced 集 + 活租约集后才 unlink，注册提交与 sweep 删除在锁上互斥，plan→sweep TOCTOU 与 place→commit 窗口同时关闭。Windows 只读位被 chmod-retry 击穿不构成保护（从来不是语义边界）。
- `#1218`：`commit_working_copy(asset_id=None)` 不再持锁跨载荷 IO（资产先行登记 + 失败回滚；窗口内 zombie 分类器由 `_pending_commit_assets` 遮蔽，评审 R2#5）。

## 2. 证据（tests/test_catalog_gc_registration_race.py）

- **对抗性 register‖sweep**：`_build_version` 在放置后、提交前**确定性驻留**（每个放置都门控），窗口敞开期间连扫两轮 explicit sweep——载荷存活（评审后测试证明具备杀伤力：临时还原 "output" 拼写 bug 即红）。
- 陈旧 plan 报告 sweep 不能删新注册载荷（锁内复查）。
- 租约 TTL 过期 → 恢复孤儿分类；blob 导入在并发 sweep 下存活。
- #1218：提交大文件期间并发目录变更不被阻塞（锁已释放的证据）。
