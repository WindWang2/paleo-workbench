# 02 — Transaction / Revision Model（#1220）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 旧缺陷（check-then-act）

revision 在事务外读取（`service.py` flush 前置检查），`apply_changes` 提交时无条件覆写 `catalog_revision`——B 读 revision 与 B 提交之间 A 提交 → 双写者同值互相掩盖；`rebuild_index` 无守卫无锁；无范围 reconcile 全量 diff 会**删除对方进程的行**；死代码 `_sync_index_best_effort` 整体绕过守卫。

## 2. 新模型（BEGIN IMMEDIATE + 事务内 CAS）

```
 BEGIN IMMEDIATE                      ← 先取写锁（跨进程在 SQLite 层串行）
   SELECT catalog_revision FROM sync_state
   IF expected_revision IS NOT NULL AND stored != expected:
       ROLLBACK; raise CatalogStaleWriteError   ← 原子中止
   ...dirty 行 upsert/delete（不变）...
   UPDATE sync_state revision
 COMMIT
```

- `apply_changes(document, dirty, lookups, expected_revision)` 与 `reconcile(document, expected_revision)`（含空 dirty 仅盖章分支）全部走上述协议；池化连接先 `if conn.in_transaction: rollback()` 防悬挂。
- 服务侧 `_flush_canonical_locked`/`_ensure_index_fresh` 传 `_flushed_revision` 基线；便宜前置检查保留为快速失败，**权威判定在事务内**。
- `rebuild_index`：持服务锁 + 陈旧守卫 + 重建后重定基线。
- `CatalogStaleWriteError` 移至 db 层（service 再导出，全部既有导入点不变）。
- 语义：最多一个冲突写者成功；另一个收到类型化错误（中文可操作信息）；事务内任何异常整体回滚（部分 upsert 不可能）；重试由用户显式重开触发，绝不盲目覆盖。

## 3. 证据（tests/test_catalog_transaction_cas.py）

- **TOCTOU 窗口模拟**：预检被骗（返回旧基线）+ 存储已推进 → CAS 在事务内拦截，外部提交完整存活。
- **无范围 reconcile 拒绝**：陈旧全量 diff 不再删外来行。
- **rebuild 守卫**。
- **真·双进程**：子进程 `import_raw` 提交 → 父会话下一写 CatalogStaleWriteError，子进程的行存活。
- **批内原子性**：batch 中多个注册随 CAS 失败整体回滚，无部分提交。

## 4. 已知边界（见 11-known-limitations）

`rebuild_index` 预检与重建事务之间、schema-absent 回退 `write_all` 仍是窄窗口（显式维护操作场景）；`index.sync()` 无生产调用者保持休眠。
