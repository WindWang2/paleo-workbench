# 09 — Mirror Lifecycle (V11)

## 1. Save-intent channel（会话 ↔ 发布）

```
用户手势 → VectorEditSession（journal + working copy）
    │ 未提交：发布不可见（_host_records 只结算提交基线）
    ├─ commit → data_revision+1 → 发布可见（delta 通道）
    └─ rollback → 基线不动 → 发布 stable（无重发）
```

* **选择通道**（vector_layer）：会话打开时可选中集 = 会话视图（新增
  要素立即可选）；`_selection` 本体仍是基线视图 ids 子集——提交/回滚时
  `intersection_update` 自动 cross-check。`set_staged_selection` 允许在
  会话外登记意图，会话开启时按当前视图结转（宽容丢弃未知 id）。
* **发布侧 save-intent**：`mirror_snapshot_to_stack` 只消费提交基线
  （`_host_records` 语义）；待提交会话的变更对发布不可见（S1/S2 场景）。
* **全或无保存**（#1283，M0）：`flush_edit_sessions` 两阶段——阶段 1 对
  全体会话判定门禁（任一失败则一个都不提交），阶段 2 逐层提交（中途
  异常则剩余回滚）。

## 2. Per-feature signature cache（O(changed) 发布）

```
settle（composite_editing）→ session journal → touched fids
    → snapshot_changed_hints() → panel._publish → shim → mirror
    → changed_hints 生效：提示集外要素免签（旧签即新签）
```

* 无提示回落全量签名比较（正确性不变；delta 内容仍精确）。
* 发布成功后缓存刷新（新签进 `(stack, layer, revision)` 槽）；旧修订
  条目逐出（无界增长防护）；`reset_publish_ledger` 连带清缓存。
* 结构性保证（test_mirror_lifecycle_v11）：300 要素单点扰动 = 1 次重签；
  同修订重发布 = 0 次签名；delta 只含触及要素。

## 3. Raster ledger（零调用短路）

tokens = (data_revision, style_sig, visible, opacity, name, source_path)。
全等 → 零桥调用（此前每次发布都重调，N 次/发布）。任一变化即下推——
C++ 侧 `style_only_change` 快道接住纯样式变化（renderer 通道重应用，
不重建图层）。scalar_grid 的数据修订由 `ScalarDataMirror.ensure` 键控
（同修订同源路径，天然命中）。

## 4. 状态机（goal §17 的正式落点）

| 转换 | 触发 | 发布行为 |
|---|---|---|
| create | create_layer/register | 首发布全量 |
| mirror | 首次 publish | 全量 + 台账建基线 |
| update data | session commit | delta（changed_hints 快道） |
| update style | style_revision/style_sig | 样式通道（栅格：renderer 快道） |
| rename | rename_layer | name token → 重发布（V10 M-E） |
| move | 树事件/plan reconcile | 树事务窗口内放置（本层不重发） |
| hide/show | 显隐事件 | 可见性直写（C++ setMirrorLayerVisibility） |
| replace source | 源路径/修订变化 | 全量重建（栅格：新源路径） |
| schema change | fields 漂移 | 全量重发（memory provider 约束） |
| remove | remove/unregister | remove_except + 台账/缓存剪枝 |
| restore | 重加同 id | 台账已剪 → 全量（无过期复用） |

remove 整层时 `_MIRROR_LEDGER`/`_SIGNATURE_CACHE`/`_RASTER_LEDGER` 的对应
条目随 keep-set 剪枝（v7 §9 语义扩展到三表）；同 id 重加 = 全量（防过期
复用）。`id(stack)` 复用防护（V10 M-E R2）覆盖三表（签名/栅格清表与
reset 同步）。

## 5. 与 #1283 的关系

已落地：按需生长的 Python 侧对应物（save-intent 缓冲 + 提交基线语义）、
全或无保存（两阶段 flush）、停发窗口的语义等价物（会话期发布走基线，
天然不停发未提交变更）。未落地（M1+ 原生编辑会话上线时）：committed*
增量回写通道、台账提交后对齐（当前仍走发布验证）、编辑期台账冻结——
这些需要原生编辑会话存在，M0 只建 Python 侧地基。
