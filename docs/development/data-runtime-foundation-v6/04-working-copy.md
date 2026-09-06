# 04 — Working-Copy State Machine（#1211）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 状态机

```
NONE ──create──▶ CHECKED_OUT ──(mtime/size 漂移=保守 dirty 提示)──▶ DIRTY
                     │ commit_working_copy                     │
                     ▼                                         ▼
                 COMMITTING ──成功──▶ COMMITTED(行删除，载荷已移入受管存储)
                     │失败/崩溃
                     ▼
              recover_working_copies() 证据裁决：
                committed 版本 source_uri==工作路径 → 行删除（提交已落）
                否则 → 回 DIRTY（文件未动过——move 原子）
ABANDONED = discard_working_copy 显式终态（文件+行删除；COMMITTING 拒绝丢弃）
```

- 登记表 `working_copies`（canonical store 内，连接期幂等建表 + 重建 DDL + 删除序）：身份 = `working_id`(uuid) + `source_version_id`，**显示名/文件名永不参与身份**（重名井/重名文件不串）。
- `create_working_copy(version_id, allow_replace=False)`：同源活副本**复用**（不静默覆盖未提交编辑）；`allow_replace=True` 显式弃旧建新。
- **磁盘证据 fail-closed**（评审 R3#3 修复）：注册表降级（表损坏/INSERT 失败/v6 前旧副本无行）时，目标路径上已存在的文件仍被视作用户工作——复用或要求 allow_replace，绝不因登记缺失而清空。
- 并发 checkout 收敛：temp+replace 幂等（同字节）+ Windows replace 冲突重试；登记竞争 UNIQUE 容忍。
- 公共 API：`list_working_copies` / `working_copy_state`（保守 dirty 提示：mtime 或 size 漂移）/ `discard_working_copy` / `recover_working_copies`；恢复接线在工程打开维护线程（warm 之后）。
- save-as/便携打包丢弃 working/ → 恢复时清理死行。

## 2. 证据（tests/test_catalog_working_copy_lifecycle.py，7 例）

复用保编辑、重名身份独立、copy 后崩溃重开可枚举、提交中崩溃两分支证据裁决（已提交→清行 / 未提交→回 dirty 且文件完好）、显式丢弃终态、并发收敛、save-as 孤儿行清理。
