# 05 — Project Open/Save/Backup/Recovery（#1229）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 决策表（`manager._load_data`，全部在触碰任何文件之前分流）

| 失败 | 判定 | 动作 |
|---|---|---|
| PermissionError（AV/同步锁/他实例占用） | 暂时不可读 | 类型化 `ProjectUnreadableError`；**main 与 .bak 均不动**；UI 给重试指引 |
| 其他读 OSError | 暂时/IO | 原样上抛（fail-safe） |
| FileNotFoundError | 保存中断（main→bak 已完成、tmp→main 未落） | 校验 .bak → 恢复 main |
| JSON/校验错误 | **损坏确证** | **先校验 .bak**（不可用则原错误上抛、main 保持原位——无失踪工程悬空态，评审 R1#4）→ 损坏字节隔离为 `*.corrupt-<ts>`（法证）→ .bak 顶替 main |
| .bak 缺失/亦损坏 | 无法恢复 | 诚实失败（保留原始错误与字节） |

- 恢复留痕：`ProjectMeta.last_recovery = {source, recovered_at, error, quarantined}` 设在模型上、快照保持磁盘真相 → **下一次保存必定落盘**（即便无其他变更）；manager 每 load 重置陈旧证据（评审 R1#5）。
- mtime 基线取自实际支撑会话的文件；恢复后保存守卫有效（测试钉住）。

## 2. 保存守卫 v2（内容哈希）

快照增加 `disk_sha256`（load/commit 采集）。mtime 漂移 + 哈希一致 = 外部工具良性 touch → 重定基线继续保存；内容真变 → `ProjectStaleWriteError` 拒绝（同步工具误报消除，真实冲突不放过）。

## 3. 证据（tests/test_project_recovery_v6.py，6 例）

暂时不可读绝不回退（main/.bak 字节前后不变）、损坏隔离+记录往返落盘、中断保存恢复、双损坏诚实失败、良性 touch 可保存、真实外来写入仍拒绝。既有 project_manager/async_save/adversarial_m5 全绿；顺手修复 main 上 #1170 未知字段警告自 `extra="allow"` 落地后哑火的既有缺陷（按声明字段集判别）。
