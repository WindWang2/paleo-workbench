# R6 recon — resolve_path 完整阶梯 + 服务层 trash/restore/purge 状态机（契约冻结）

对象：`paleo_workbench/catalog/service.py`（1502-1608、3249-3661）+ `storage.py`（205-337）↔ 现有 C++ `libs/catalog`（trash.hpp 已交付 storage 级，D1）。
结论速览：storage 级搬移/回收已完成且错误串字节对齐；缺的是**编排层**——tombstone 元数据形状与写入时机、锁内两段 save 序（tombstone→持久化→搬移→路径回写）、current_version_id 重分配、僵尸资产/待提交资产判定、崩溃窗探针、purge 的 refcount+回滚快照。resolve_path 六梯全缺（sources.hpp 只有第一梯 probe）。

---

## ① 语义契约

### 1.1 resolve_path 完整阶梯（service.py:1502-1544）

前置：`project_dir = project_path.expanduser().resolve().parent`（1515）——project_path 是 `*.paleo.json` 文件，project_dir 是其父目录（所有 project-relative version.path 的锚）。

| 梯 | 判定（按序，先中先返） | 指纹比对 | 行号 |
|---|---|---|---|
| R1 | `version.managed` → **无条件**返回 `project_dir / version.path`（不 stat、不验存在——托管路径由本服务放置，天然可信） | 无 | 1516-1517 |
| R2 | `Path(version.path).is_file()` → 返回 `raw_path.resolve()`（记录路径原样命中；通常是绝对路径） | 无（exact by construction） | 1518-1520 |
| R3 | `(project_dir / raw_path).resolve().is_file()` → 返回该候选（project-relative join；pathlib 语义：raw 为绝对路径时 join 被替换，退化为 R2 的 resolve 重试） | 无 | 1521-1523 |
| R4 | posix 分段（`split("/")` 去空段）；`project_dir.name` 出现在段中（`parts.index` 取**首次**出现）→ `subpath = parts[idx+1:]` 非空且 `(project_dir/subpath).resolve()` 是文件 | **有**：`_fallback_identity_ok` 门 | 1524-1533 |
| R5 | `len(parts) >= 2` → 末两段 join 到 project_dir | **有**：同上门 | 1534-1538 |
| R6 | 末一段（basename）join 到 project_dir | **有**：同上门 | 1539-1543 |
| R7 | 全部落空 → 返回**记录路径原样**（大概率缺失；integrity 报 missing，relink 可救） | — | 1544 |

失败级联：R4-R6 指纹门失败 = **继续降梯**（不是报错）——调用方最终拿到 R7 的缺失路径，`verify_integrity` 报 `"missing"`（queries.py:71-75 先跳过 trashed 再 stat）。resolve_path 永不抛错、永不返回 None。

**已知文档/代码分歧（如实）**：docstring（1504-1513）声称 "deliberately NO basename / last-two-segments guess"，但代码 1534-1543 存在这两梯——被 `_fallback_identity_ok` 身份门改造过（#1221 演进：从"删除回退"改为"fail-closed 身份验证回退"）。**以代码为准冻结**；测试 `test_resolve_path_never_rebinds_same_named_in_project_file`（tests/test_catalog_resolve_path_safety.py:49-74）钉的正是"同名替身内容不同→门拒→落 R7"。

### 1.2 _fallback_identity_ok fail-closed（1546-1565）

逐分支（try 包裹，任何 `OSError` → `return False`）：

1. `version.sha256` 非空 → `sha256_file_or_none(cand) == version.sha256`（**全文件重哈希**；checksum.py:48，读失败返回 None → False）
2. elif `version.size_bytes is not None` → `cand.stat().st_size == version.size_bytes`（弱指纹，仅尺寸）
3. 两者皆无 → **fail-closed 返回 False**（#1221：无身份证据的版本宁可 surface 为 missing，绝不静默绑同名陌生科学数据文件）

语义：sha256 梯 > size 梯 > 拒绝。注意只有 sha256/size 二档，**没有** mtime（区别于 sources.hpp `relink_identity_proof` 的 sha256→stat_fingerprint(含 mtime_ns) 二档——relink 面向 external_stat 记录，本门面向 version 字段）。

### 1.3 服务层 trash 状态机 vs storage 级分工线

**已在 C++（trash.hpp/cpp，D1 交付）**：`trash_payload`（原子搬移 + blob 豁免 + 目录树整体搬移 + fsync×2 + 空祖先剪枝×2）、`restore_payload`（搬回 + 重新只读 + 目标已存在拒绝）、`purge_trashed_payload`（shared 标志的 refcount unlink）、`is_cas_path`、`trash_dir_for`、`create_working_copy`。错误串已逐字对齐（trash.cpp:153/179/184/247 ↔ storage.py:243/284/277,287）。

**缺的编排层（本切片主体）**，每个 trash/restore 都遵循**锁内两段序**：

```
trash:   内存 tombstone → save#1(持久化 tombstone) → 磁盘搬移 → save#2(路径回写)
restore: 内存 untombstone（含搬回/probe） → save（单段）→ 失败→重打 tombstone+搬回 trash
```

tombstone 元数据形状（_tombstone_version，3251-3268，内存-only 不动 payload）：
`version.metadata["trash"] = {"reason": reason, "original_stage": stage.value, "original_path": 原path, "trashed_at": 同trashed_at}`；同时 `trashed=True, trashed_at=now`。返回 original_path。

`_move_payload_to_trash`（3270-3285）：非 managed → False（external 文件永不触碰）；`trash_payload` 抛 CatalogError（payload 已缺）→ False（**metadata-only tombstone**）；成功 → `version.path = new_rel`，True。**blob-backed 路径 trash_payload 原样返回** → new_rel==old → True 但路径未变 → save#2 仍执行（幂等写）。注意：它只捕获 CatalogError；其他 OSError 会向上传播（见 ⑥ 崩溃容忍）。

`_active_current_candidate`（3356-3363）：该资产**文档序**（versions_by_asset 顺序 = rowid 序）最后一个非 trashed 且 ≠exclude 的版本 id；无 → None。**语义是文档序末位，不是 max(version_number)**。

#### trash_version（3365-3401）逐分支

1. 锁内；`_version_or_raise`（1252-1262，miss→重建 maps 再查→仍无→`CatalogError("Unknown version: {id}")`，1261）
2. **幂等**：已 trashed → 原样返回（无 save）
3. `_asset_or_raise`（1238-1250，`"Unknown asset: {id}"`）；记 previous_current
4. `_tombstone_version`；若 `asset.current_version_id == version.id` → 重指 `_active_current_candidate`
5. save#1 `DirtySet(assets={asset.id}, versions={version.id})`；**失败 → `_rollback_tombstone`**（3444-3453：清 trashed/trashed_at/metadata["trash"]，`asset.current_version_id = previous_current`——payload 未动过，仅内存）+ re-raise
6. `_move_payload_to_trash`；moved 则 save#2（同 dirty）；**失败 → `_rollback_trash_move`**（3287-3302：按 trash.original_path 把 payload 搬回原位、version.path=original；**tombstone 保留**——版本保持 trashed、payload 在原位，restore 可正确处理）+ re-raise

崩溃窗（docstring 3374-3378 + 测试 test_catalog_crash_safety.py:419/446）：
- **W1** save#1 后、搬移前崩溃：tombstoned + path=original + payload 在原位（一致态，restore 免 probe）。
- **W2** 搬移后、save#2 前崩溃：tombstoned + path=original（陈旧）+ payload 实际在 `trash/{vid}/`——由 `_probe_trash_payload` 在 restore 时恢复。

#### trash_asset（3403-3442）

同构但批量：非 trashed 版本逐个 tombstone（文档序）→ `asset.trashed=True, trashed_at=now, current_version_id=None` → save#1（全部版本+资产；失败→逐版本 `_rollback_tombstone` + 资产标志还原）→ 逐版本搬移（moved 子集）→ 有 moved 才 save#2（**dirty 只含 moved**；失败→仅对 moved 逐个 `_rollback_trash_move`）。

### 1.4 restore 反向序 + _untombstone_version 崩溃窗恢复

`_probe_trash_payload`（3304-3316）判定分支：
1. `trash_dir_for(project)/version_id` 不是目录 → None
2. `sorted(顶层**文件** p)` 为空 → None（注意：目录树 payload 的 trash 条目是目录，`is_file()`=False → **probe 对树 payload 无效**，落"保 original_path，integrity 报缺失"）
3. 否则返回 `files[0]`（排序后第一个）相对 project_dir 的 posix 路径

`_untombstone_version`（3318-3354）分支树：
- `original_path = metadata["trash"]["original_path"] or version.path`
- managed：
  - 主路径：`version.path = restore_payload(project, resolve_path(version), original_path)`（resolve_path(version) 即 trash 现位；恢复后重打只读）
  - CatalogError → **崩溃窗恢复**：probe trash/{vid}/ → 命中：`version.path = probed` 再试一次 restore_payload；再失败 → `version.path = original_path`（认缺，integrity 报 missing）。probe 未命中（metadata-only trash 或 payload 丢失）→ 同样保 original_path
- 非 managed：`version.path = original_path`（external 本就没动过）
- 收尾：`trashed=False, trashed_at=None, metadata.pop("trash")`

`restore_version`（3455-3479）：锁 → raise 门 → 幂等（非 trashed 原样返回）→ **先抓 reason**（pop 前快照，供回滚重打）→ untombstone → current 重指条件：`current is None` **或** current 指向的版本不存在/已 trashed（`any(v.id == current and not v.trashed)`，3467-3470）→ 指向本版本 → save；失败 → `_rollback_untombstone`（3522-3534：`_tombstone_version(reason=捕获的reason)` + managed 则 `_move_payload_to_trash` 搬回 trash + `current=previous_current`）。

`restore_asset`（3481-3520）：对**全部**版本中 trashed 者 untombstone（reason 先快照成 restore_targets 对）；`asset.trashed=False`；current 为 None 时重指"存活版本文档序末位"；save 失败 → 资产标志还原 + **只回滚 restore_targets**（原本就 live 的版本必须保持 live——测试 test_audit_catalog.py:187）。

### 1.5 purge_trashed（3536-3661）：refcount + 僵尸 + 两类资产处置

顺序（每步都是载荷）：
1. 收集 trashed_versions / trashed_assets；`purged_ids` 并集；预摘 tag maps（version_tags/asset_tags）
2. `surviving_digests = {v.sha256 | v 非 trashed 且有 sha256}`（3557-3561）——**只有幸存版本保护 blob**；两个同 digest 的 trashed 版本同灭 → blob 可删
3. `payload_purges = [(resolve_path(v), v.managed and v.sha256 ∈ surviving_digests)]`——**在删除行之前**计算（resolve 依赖版本行；trashed managed 的 path 即 trash 相对路径）
4. `_remove_versions_bulk(trashed_versions)`
5. **僵尸资产**（I3）：`live_asset_ids = 剩余版本的 asset_id 集 ∪ _pending_commit_assets`（3578-3581，#1218/R2#5：在途 working-copy commit 拥有无版本资产）；非 trashed 且不在 live 集 → 删除 + 摘其 asset_tags（removed_zombie_tags）
6. trashed 资产二分（3600-3621）：`surviving_asset_ids = 剩余非 trashed 版本的 asset_id 集`。命中 → **保留并 un-trash**（先快照 (trashed, trashed_at, metadata) 供回滚；C3：restore_version 可单救一版，删资产会孤儿化该 live 版本）；未命中 → 删除
7. save（versions+assets+zombies+两类 tags 的 dirty）；**失败全量内存回滚**：`_add_version`×n、`_add_asset`×zombies、removed trashed 资产按**对象身份**（`is`，C++ 用 id 不在文档判）重加、untrashed_snapshots 标志还原、三个 tag map `update()` 回灌（含 zombie tags，3653-3655）+ re-raise
8. **持久化成功后**才 best-effort unlink：`purge_trashed_payload(project, path, shared)`（失败无害——残留 trash payload = 无害孤儿）
9. 返回 `len(trashed_versions) + len(trashed_assets)`（**僵尸不计入**）

### 1.6 _rollback（1569-1608）：注册路径的补偿范围（区别于 trash 专用回滚）

签名：`assets=(), versions=(), runs=(), payload=None, restore_current=(asset, prev)|None, restore_payload_to=None`。顺序（固定）：
1. 逐个 `_remove_asset` → `_remove_version` → `_remove_run`（内存 maps 维护）
2. `restore_current`：`asset.current_version_id = previous`
3. payload 三分支：
   - `is_cas_path(project, payload)` → **绝不 unlink**（blob 共享、内容寻址、不可变；失败 save 不能毁别人的引用）
   - `restore_payload_to` 给出且 payload 存在 → `os.replace(payload, restore_payload_to)`（被消费的 working copy 送回原处——失败 commit 不得毁用户数据；OSError 吞掉）
   - 否则 `safe_unlink(payload)` + 剪空父目录与祖父目录（rmdir best-effort）

供 `_build_version`/register 系失败路径用；trash/restore/purge 用的是 1.3-1.5 各自专用回滚，**不共用本函数**。

### 1.7 错误消息逐字（冻结）

| 消息 | 源 | C++ 状态 |
|---|---|---|
| `Unknown version: {version_id}` | service.py:1261 | 待 trash_service |
| `Unknown asset: {asset_id}` | service.py:1249 | 待 trash_service |
| `Managed payload not found: {source}` | storage.py:243 | ✅ trash.cpp:153,247 |
| `Trashed payload not found: {source}` | storage.py:284 | ✅ trash.cpp:179 |
| `Restore target already exists: {target}` | storage.py:277,287 | ✅ trash.cpp:184 |
| `Unsafe version id {id!r}: only [A-Za-z0-9._-] allowed` | storage.py:63-67 | trash.hpp is_safe_entity_id 判定已有（消息形态核对 trash.cpp 交付） |

---

## ② 冻结 C++ API 提案

### 2.1 resolve 阶梯 → 新小头 `libs/catalog/include/pwb/catalog/resolve.hpp`

```cpp
namespace pwb::catalog {
// service.py:1502-1544 完整阶梯（R1-R7）。纯函数：(project_path, version, fs)，
// 无 document/锁依赖。永不失败：落空返回记录路径原样（R7）。
std::filesystem::path resolve_payload_path(const std::filesystem::path& project_path,
                                           const DataVersion& version);
// #1140/#1221 fail-closed 身份门（1546-1565）：sha256 梯→size 梯→拒绝。
bool fallback_identity_ok(const std::filesystem::path& candidate,
                          const DataVersion& version);
}
```

归属理由：不进 sources.hpp——那里 `missing_probe_path` 刻意只有第一梯（O(n) 扫描不得跑身份哈希，注释 44-51），混入完整梯易被误用；也不等 service_core——阶梯零服务依赖，先落地即可让 queries.hpp `verify_integrity` 的 `resolve` 回调（当前默认第一梯，D4）与 audit/explain 升级为完整梯。两个自由函数即可，无需 index/锁。

### 2.2 trash 编排层 → 新头 `libs/catalog/include/pwb/catalog/trash_service.hpp`

不扩 trash.hpp（D1 已冻结 storage 级分工线）；采用 tags.hpp `TagSaveHook` + sources.hpp `relink_external_source(document, index, …, save, now_iso)` 先例：**文档指针 + 只读 index 快照 + save 钩子**，save 失败时函数内还原内存态并返回错误。

```cpp
namespace pwb::catalog {
using TrashSaveHook = std::function<domain::DataError()>;  // stands in for service._save(DirtySet)

// 幂等（已 trashed / 非 trashed → no-op 成功）。NotFound = "Unknown version/asset: X" 逐字。
// trash_version: 两段序（tombstone save → move → path 回写 save），失败走 1.3 对应回滚。
domain::DataError trash_version(CatalogDocument* doc, const DocumentIndex& index,
                                const fs::path& project_path, const std::string& version_id,
                                const std::string& reason, const TrashSaveHook& save,
                                const std::string& now_iso = "");
domain::DataError trash_asset(CatalogDocument* doc, const DocumentIndex& index,
                              const fs::path& project_path, const std::string& asset_id,
                              const std::string& reason, const TrashSaveHook& save,
                              const std::string& now_iso = "");
domain::DataError restore_version(CatalogDocument* doc, const DocumentIndex& index,
                                  const fs::path& project_path, const std::string& version_id,
                                  const TrashSaveHook& save);
domain::DataError restore_asset(CatalogDocument* doc, const DocumentIndex& index,
                                const fs::path& project_path, const std::string& asset_id,
                                const TrashSaveHook& save);

struct TrashPurgeResult { std::size_t removed = 0; };  // trashed versions + trashed assets
domain::DataError purge_trashed(CatalogDocument* doc, const DocumentIndex& index,
                                const fs::path& project_path, const TrashSaveHook& save,
                                const std::set<std::string>& pending_commit_assets,
                                TrashPurgeResult* out);

// 崩溃窗探针（3304-3316）：trash/{vid} 顶层排序后第一个**文件**的项目相对 posix 路径。
std::optional<std::string> probe_trash_payload(const fs::path& project_path,
                                               const std::string& version_id);

// 暴露给测试/oracle 的纯片段：
struct TrashMetaView {                       // metadata["trash"] 四键
    std::optional<std::string> reason, original_stage, original_path, trashed_at;
};
TrashMetaView trash_meta_of(const DataVersion&);           // 空 view = 无 tombstone
std::optional<std::string> active_current_candidate(const DocumentIndex&,
                                                    const DataAsset&,
                                                    const std::string& exclude_id);
}
```

设计要点：
- **save 钩子是唯一持久化缝隙**：函数自知脏集（trash: assets={asset}, versions={…}；purge 另有 version_tags/asset_tags 与 zombie 资产）。R1/R4 的 DirtySet 通道落地后钩子签名可升级为 `DataError(const DirtySet&)`，调用方（service_core）闭包绑定——先冻结裸 `()` 形（tags.hpp 先例），升级是纯加法。
- 搬移/回收一律走 trash.hpp 既有函数（错误串已对齐）；编排层不碰 fs 细节。
- reason 捕获快照（restore 前 pop）、tombstone 元数据四键形状、`"trash"` 键名均属冻结契约。
- purge 的 `pending_commit_assets` 显式入参（C++ 无服务单例；service.py:3581 的 `_pending_commit_assets` 集合由 service_core/R5 维护）。

---

## ③ 依赖与接口点

- **R1/R4（save/apply_changes）**：TrashSaveHook 即 `_save(DirtySet)` 缝隙的两端。trash 两段序对 CAS（`CatalogStaleWriteError`）与 flush 失败的行为依赖"钩子返回非 Ok→触发对应回滚"这一契约；purge 回滚是全量内存快照还原（1.5.7）。DirtySet 落地前，oracle 测试用可注入失败次数的假钩子模拟 save#1/save#2 分别失败（对应 Python 测试 monkeypatch `_flush_canonical_locked`，test_audit_catalog.py:130/157/187/218）。
- **R5（working-copy）**：① purge 的 `pending_commit_assets` = service.py:339/2618/2630 维护的在途集合（#1218 僵尸防护）；② `_rollback` 的 `restore_payload_to` 分支 = commit_working_copy 失败时送回被消费副本（test_catalog_service.py:595）；③ trash.hpp `create_working_copy` 已交付，R5 直接消费。
- **R9（现有 C++ 面）**：`trash.hpp`（全部 fs 级操作 + 错误串）；`queries.hpp verify_integrity`（trashed 跳过 + `resolve` 回调缝隙——resolve.hpp 落地后 `entity_view`/audit 可绑定完整梯，消除 D4 第一梯偏离）；`sources.hpp`（missing_probe_path 保持第一梯契约不变；relink 身份哲学同源 #1140）；`impact.hpp delete_impact`（**纯咨询前置检查**，trash_version 本体不做任何下游门禁——UI 先问 delete_impact 再调 trash；两者无调用依赖，仅语义配套）；`document_index.hpp`（index 为 const 指针快照，**变更后须 rebuild**——trash_service 每函数结束态由调用方重建）；`gc.hpp`（trash_orphan 判定：有 live 记录的 trash payload 永不算孤儿，test_catalog_gc.py:173——W2 窗不误扫）。
- 消费方（Python 侧对照）：`_move_payload_to_trash`/purge 内嵌 `resolve_path`（3279/3567）；`queries.verify_integrity`、`audit._check_payloads`（657：trashed payload 缺失 = LOW 非 HIGH，crash-window 态不算 mismatch——test_catalog_audit_module.py:234/248，31 号切片已含 audit，交互点在 resolve 回调）；`service_v11.member_path/verify_bundle_integrity`；`adapter._version_ref`。

---

## ④ oracle 冻结场景建议

沿用 D2 模式：`tools/oracle/generate_catalog_domain_fixtures.py` 增设 `resolve_ladder`、`trash_machine` 两个 scenario（Scratch 布局 + 真实 import + oracle.json 断言），C++ 侧 replay。建议用例（≥20）：

resolve_ladder：
1. managed join（R1，路径不存在也返回 join 结果）
2. 记录绝对路径存在（R2）／project-relative join（R3）／项目名 re-anchor——**含项目名出现两次取首次**的 corner
3. R4/R5/R6 各梯 sha256 门通过（内容同→重绑成功）
4. R5 size-only 门通过；R6 无 sha 无 size → **fail-closed 落 R7**（#1221）
5. 同名替身内容不同（#1140 核心场景）→ 落 R7 且 verify_integrity 报 missing
6. sha256 门读文件失败（候选中途删除）→ 继续降梯

trash_machine：
7. trash managed 单版本：两次 save、path 改写为 `trash/{vid}/{name}`、目录树 payload 整树入 trash
8. trash external：metadata-only，path 不变，**磁盘文件原封不动**
9. trash blob-backed：path 不变（dedup_flow 场景已冻结三快照，catalog_gc_test.cpp:501 起可直接复用）
10. 幂等：二次 trash/restore no-op（无 save）
11. current 重分配：trash 当前版 → 指向文档序最新存活版；全灭 → None
12. save#1 失败 → `_rollback_tombstone` 全还原；save#2 失败 → payload 回原位 + **tombstone 保留**
13. W1 崩溃窗：restore 原位成功（免 probe）；W2 崩溃窗：probe 恢复 + `plan_gc` 零 trash_orphan（复刻 test_catalog_crash_safety.py:419/446）
14. purge refcount：同 digest 双版本一存活 → blob 留；末引用 → blob 删（test_catalog_dedup.py:196/211）
15. purge 僵尸：全版本被单独 trash+purge 的 live 资产消失；在途 pending_commit 资产存活
16. purge trashed 资产二分：有存活版本 → un-trash 保留；无 → 删除；返回计数不含僵尸
17. purge save 失败 → 全量还原（含 tag 回灌与 untrashed 快照）；失败后 payload 仍可 restore（unlink 只在持久化后）
18. restore 失败保留 reason；restore_asset 失败保持 live 版本 live（test_audit_catalog.py:187/218）
19. zombie 探针边界：trash/{vid} 只有目录（树 payload W2 窗）→ probe None → 保 original_path
20. unsafe version_id → trash_payload 拒绝（消息逐字）

---

## ⑤ 有界偏离清单（如实）

1. **路径规范化**：Python `Path.resolve()`（非 strict、解析符号链）↔ C++ `weakly_canonical`（sources.cpp 先例）；POSIX 存在前缀下等价。join 语义核对：pathlib 与 `fs::path::operator/` 对绝对右操作数都是"替换"，行为一致——测试钉住。
2. `now_iso` 注入参数（sources.hpp 先例）；Python 内部取 `_now_iso()`。
3. save 缝隙 = 钩子而非真实 `_save/_flush_canonical_locked` + revision CAS（R1/R4 领地）；崩溃窗用"分阶段直调"模拟（同 Python 测试手法）。
4. **probe 对目录树 payload 无效**是 Python 原行为（`p.is_file()` 过滤），冻结为契约而非偏离——但必须写进契约文档防"修复"。
5. purge 计数不含僵尸资产（Python 原样）。
6. `_rollback`（1569-1608）属注册路径补偿，归 R2/R4 注册切片；本切片只冻结其 CAS/working-copy/剪枝三分支语义供复用，不实现。
7. `sha256_file_or_none` ↔ `domain::Sha256::of_file` Result→nullopt（OSError→None 对齐）。
8. resolve_path docstring 与代码分歧（1.1）：按代码冻结，建议顺手修上游 docstring（不在本切片）。
9. `_version_or_raise` 的 maps 重建重试（1252-1264 安全网）在 C++ 单文档形态下无意义——直接 index 查找 + NotFound，行为等价（index 即重建产物）。

---

## ⑥ 风险 / 先例坑

- **身份门跑全文件哈希**：R4-R6 每候选一次 sha256 全读。绝不接进 O(versions) 扫描（sources 第一梯契约、queries 默认回调都不能换）——resolve.hpp 注释必须写明。
- **`parts.index` 取首次项目名出现**；多段同名（嵌套迁移）行为易写错，oracle 场景 2 钉死。
- **绝对路径 join 替换语义**：R3 对绝对 raw 退化为 R2 重试；C++ `operator/` 同语义但值得一条断言。
- **trash_asset 中途非 CatalogError 异常**（os.replace 底层 OSError 未捕获）：save#1 已持久化、部分 payload 已搬、save#2 未跑 → 恰好落入 W2 态，probe 兜底——设计上可容忍，但契约测试应记录"不需要额外补偿"。
- **purge 顺序是载荷**：payload_purges 必须在删行前 resolve；unlink 必须在 save 成功后（失败 save 后 trash payload 必须仍可 restore，test_audit_catalog.py:130）。
- **purge 回滚的对象身份判定**（`not any(existing is asset …)`，3647）：C++ 用 id 成员判定，勿用指针相等（文档重载后指针失效）。
- **三个 tag map 回灌**（3653-3655，含 zombie tags）是易漏点：zombie 摘 tag 发生在 save 前，失败回滚必须回灌。
- **`_active_current_candidate` = 文档序末位**，非 max(version_number)——promote 的锁内重编号（#849-1）后文档序才是权威。
- **DocumentIndex 快照失效**：trash_service 各函数结束后调用方须 `index.rebuild(doc)`；函数内不得缓存跨 save 的 index 指针（document_index.hpp 头注）。
- **impact.hpp 不做门禁**：勿在 trash_version 里加"下游 stale 拒绝"——Python 服务无此门，delete_impact 是 UI 咨询面；加了就是行为偏离。
- 先例坑（31 号切片 D3）：`DataError()` 默认 Unknown——trash_service 成功路径显式 `DataError(ErrorCode::Ok, "")`；失败回滚后返回钩子错误而非自造错误码。
