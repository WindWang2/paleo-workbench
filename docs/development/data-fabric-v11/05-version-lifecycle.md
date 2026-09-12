# 05 — Version Lifecycle（RAW / WORKING / INTERMEDIATE / DERIVED / OUTPUT）

## 1. 阶段语义（四枚举不动，语义落实）

| 阶段 | 语义 | 可变性 |
|---|---|---|
| RAW | 外部获取的原始数据 | **永不可原地修改**；修正=新版本（数据来源演进） |
| INTERMEDIATE | 计算中间产物 | 可重算；受 retention 策略管辖 |
| DERIVED | 正式科学成果（解释/预测/标定） | 不可变；进入科学审查流 |
| OUTPUT | 发布/导出交付物 | 不可变；面向工程外交付 |

`DataStage` 枚举**不加第五个值**（catalog.json/SQLite 兼容）；"WORKING"
由 uncommitted workspace 表达（下 §2）。

## 2. Working / Edit Session

既有单文件机制（#1211/#1232）不动：
`create_working_copy`（真实拷贝、live 复用、fail-closed 磁盘证据）→
编辑（外部工具或应用内）→ `commit_working_copy`（move→新不可变版本，
状态机 committing 崩溃恢复）/ `discard_working_copy`。

V11 新增 `catalog/edit_session.py` 编排层：

```python
class EditSession:            # 业务对象级
    session_id: str
    entity_type: str; entity_id: str; role: str
    checkouts: list[CheckoutRef]   # (working_id, source_version_id, path)
    opened_at: str
```

- `open_edit_session(entity, role)`：checkout 该角色 primary 资产 current 版本；
  同源 live 副本存在 → 复用并报告（不覆盖，#1211）。
- `commit_session(...)`：逐文件 commit（同 asset 或新 asset 可选），失败已提交
  部分保留 + 报告部分成功（commit 是原子单文件，session 是宏）。
- `cancel_session()`：逐个 discard。
- 会话记录进 SQLite `edit_sessions` 表（崩溃后 open 的会话在恢复面提示）。
- revision conflict：commit 时源资产 current_version_id 已前进 →
  报冲突，提供"作为新版本提交（parent=两者）"或"取消"。

覆盖数据类型：曲线文件（LAS）、tops 表、TD 表、JSON 类解释工件
（.correlation/.fault 等已走 create_derived 的保持不变 —— edit session
面向"用户手工修订"场景）。

## 3. Retention / Cleanup 策略

`retention_class` 词表（存 `version.metadata["retention_class"]`，
注册时由 producer 声明，默认按 stage+operation 推断）：

| class | 含义 | cleanup 资格 |
|---|---|---|
| `cache` | 纯缓存，可廉价重算 | 可清理（无下游依赖时） |
| `recomputable` | 可重算但代价高 | 提示后可清理 |
| `retain` | 必须保留（如外部数据派生链断裂点） | 不可清理 |
| `user` | 用户手工产物（默认 for DERIVED/OUTPUT） | 不可自动清理 |

规则：
- RAW 永远 `retain`。
- 默认：INTERMEDIATE→`recomputable`（注册者可降 `cache`）；DERIVED/OUTPUT→`user`。
- `protected by downstream dependency`：任何版本只要存在下游 live lineage
  边（非 trashed 后代）即不可清理 —— 与 retention class 无关（双门槛）。
- `cleanup_eligibility(version_id)` → {eligible, blockers: [downstream refs,
  pin, retention class, working copy live]}。
- `plan_cleanup(scope)`：批量清单（dry-run 优先），执行走 trash（可恢复），
  不直接删。

## 4. Pin（治理覆盖）

- `service.pin_version(version_id, reason)` / `unpin_version` /
  `is_pinned(version_id)`。存储：`version.metadata["pin"] = {reason, pinned_at}`。
- 效果：cleanup 永久阻断；staleness 报告中 pinned 下游记为
  "pinned-stale"（=已知晓、钉在旧输入，**非错误**）。
- 不变量：pin 不触碰 payload/path/sha（治理层，同 trash 先例）。

## 5. 生命周期状态查询

`version_lifecycle_status(version_id)`（explain/impact/UI 共用）：
stage、retention_class、pinned、live working copy、trashed、
下游计数、可重算性（producing run 存在且 operation 在可重算词表）。
