# R4 recon — _CatalogMaps / _save / _BatchSave / 双层 CAS：语义契约与 C++ API 冻结提案

切片：CONV-31b（paleo-workbench catalog 域 service 编排核）。范围：`paleo_workbench/catalog/service.py` 的 `_CatalogMaps`(86-775)、`_BatchSave`(153-217, 1015-1142)、`_save`/`_flush_canonical_locked`/`_reload_document_locked`/`_maybe_checkpoint_manifest_locked`(1015-1126)、`mutation_serial`(347-360)、`index_revision`(1196)、`ensure_index_ready`/`rebuild_index`(1144-1194)、#411/#1220 双层 CAS、`_query_index_if_current`(4324)/聚合缓存(4233-4322)、懒开/warm(404-489, 1290-1324, 4616-4711)。
现有 C++ 地基：`libs/catalog/include/pwb/catalog/document_index.hpp` + `src/document_index.cpp`（CONV-31，全量重建快照）；`repository.hpp`（revision/事务先例）。行号锚点均指本 worktree 的 `service.py`。

---

## ① 语义契约

### 1.1 索引清单（键 / 值 / 桶语义）

`_CatalogMaps`(86-130) 是**一个不可变替换容器**（`_maps` 整体置 None/重建，读者持有快照对象，#619），内部字典增量维护：

| 索引 | 键 | 值 | 构建规则（`_ensure_maps` 521-568） |
|---|---|---|---|
| `asset_by_id` | `asset.id` | DataAsset | 末位胜（id 唯一，无冲突） |
| `version_by_id` | `version.id` | DataVersion | 同上 |
| `run_by_id` | `run.id` | DataRun | 同上 |
| `versions_by_asset` | `asset_id` | list[DataVersion]（文档序） | 逐 version append |
| `children_by_parent` | `parent_version_id` | list[DataVersion]（文档序） | 对每个 `parent_version_ids` 成员 append |
| `assets_by_legacy_id` | id 或 `legacy_resource_id` | DataAsset | 先 `{a.id: a}` 全量，再对 `legacy_resource_id` **setdefault（首个 bridged 胜，不看 trashed）**；id 键优先 |
| `managed_raw_by_key` | `(source_uri, sha256)` | version id | 谓词 `_managed_raw_dedup_key`(133-143)：managed ∧ stage==RAW ∧ ¬trashed ∧ source_uri/sha256 非空；**setdefault 首个胜** |
| `external_by_path` | `path` | version id | 谓词 `_external_dedup_key`(146-150)：¬managed ∧ ¬trashed ∧ path 非空；**setdefault 首个胜** |

关键不对称（冻结，oracle 必钉）：
- dedup 键 **build 首个胜 / `_add_version` 末位胜**（709/712 直接赋值覆盖）。无害：查询侧对候选做活性校验，键错只触发自愈扫描，不产生错误命中。
- legacy 桥 **build 首个 bridged 胜（即使 trashed）/ 删除路径 rebridge 活性优先**（见 1.3）。

### 1.2 维护原语（逐方法）

全部为"文档 + maps 原子同变"；**maps 未建（None）时只动文档**，首次使用再懒构建。

- `_add_asset`(589-607)：append 文档；`asset_by_id[id]=a`；`assets_by_legacy_id[id]=a`（id 键无条件覆盖）；legacy 键：现持有者 None 或 trashed → 接管（I2：活重导入顶掉 trashed 持有者）；否则 setdefault（保留首个活的）。
- `_remove_asset`(609-625)：**按对象身份**移出文档（`_discard_by_identity` 225-231，指针比较，非值相等 #1044）；pop `asset_by_id`；受影响键 = {id, legacy_resource_id} → `_rebridge_legacy_keys`。
- `_remove_assets_bulk`(627-647)：一次过滤文档；逐个 pop；全部受影响键**一次** rebridge（survivors 传入复用）。
- `_rebridge_legacy_keys(keys, survivors=None)`(649-688)：对每个 key：幸存者中无 claimant → pop 键；有 `a.id==key` 的 claimant → **幸存者序首个 id 匹配胜，无 trash 偏好（C1）**；否则**活的优先（幸存者序首个 live），无活则首个 claimant（I2）**。仅归一化受影响键，不动其他键。
- `_add_version`(690-712)：append 文档；`_batch_depth>0` 时记 overlay（见 1.5）；maps：`version_by_id[id]=v`、`versions_by_asset[asset_id]` append、每个 pid 的 `children_by_parent` append、dedup 键若命中谓词则**赋值（末位胜）**。
- `_remove_version`(714-725)：身份移出文档 + 三个桶身份移除 + `_drop_dedup_keys`；**空桶键保留**（只有 bulk 删空桶键）。
- `_remove_versions_bulk`(727-756)：一次过滤文档；逐个 pop version_by_id + drop dedup；受影响 asset 桶过滤后**为空则删键**（不为已删资产报版本）；受影响 parent 桶过滤。
- `_drop_dedup_keys`(491-519)：**trash-agnostic**（不看 trashed，与谓词不对称——条目可能活在索引里而 version 已 trashed）；仅当 `get(key)==version.id`（所有权校验）才删；trashed 后 remove 仍能正确清键。
- `_add_run`/`_remove_run`(758-766)：append / 身份移除 + pop。
- `_append_parent`(768-774)：`parent_id not in version.parent_version_ids` 去重后 append 版本字段 + child 桶。
- `_set_legacy_bridge`(1280-1288)：元数据-only 桥接（不走 add/remove）：直接赋 `asset.legacy_resource_id` + setdefault 桥键。
- `_ensure_maps`(521-568)：懒构建；**未 warm 时先 inline 物化再建**（懒开收敛点）。查找侧自愈：`_asset_or_raise`/`_version_or_raise`(1238-1262) miss → invalidate + 重建一次再判（漏维护点只付重建费，不错报 unknown）。
- `_maps_consistent`(570-587)：测试/自检 seam。

### 1.3 触发点矩阵（写方法 → 维护/落盘形态；行号锚点）

| 写方法（组） | 行号 | maps 维护 | `_save` 形态 |
|---|---|---|---|
| register_version（已有资产） | 1729-1847 | `_add_version`@1815 | `_save(dirty)`@1825 |
| register_result_asset | 1849-1932 | 查@1888；`_add_asset`+`_add_version`@1910-11 | @1921 |
| register_derived_store | 1933-2037 | 查@1968；add@2015-16 | @2025 |
| import_raw | 2055-2143 | add@2131-32 | @2135 |
| link_external | 2145-2206 | add@2199-2200 | @2202 |
| commit_working_copy | 2525-2643 | add@2617；失败 `_rollback`→`_remove_asset`@2629 | @内联 |
| create_derived | 2645-2732 | add asset+version(+run)@2714-18 | @2725 |
| register_run / update_run_status | 2734-2813 | `_add_run`@2762 | @2764/2803 |
| 模型注册表 | 2821-3124 | 无（models 不入 maps） | `_save(DirtySet(models=…/model_versions=…))`@2910/2935/3009/3080 |
| update_asset_metadata | 3205-3247 | 无（字段原位翻转） | `_save(assets={id})`@3242 |
| trash_version/trash_asset | 3365-3453 | **无**（trashed 字段翻转不经 add/remove；dedup 键故意不清，查询侧活性校验兜底） | @3391/3397 |
| restore_version/restore_asset | 3455-3535 | 无（字段翻转） | @3473/3504 |
| purge_trashed | 3536-3661 | `_remove_versions_bulk`@3574；`_remove_assets_bulk`@3592/3622（僵尸资产）；restore 重建 add@3641-48 | @3628 等 |
| promote_version/promote_asset | 3665-3759 | `_add_version`+`_add_run`@3725-26 | @3729 |
| repair_ghost_runs | 3780-3813 | 无 | **`_save()` 全量 reconcile**@3812 |
| tags 17 方法 | 3841-4073 | 无 | `_save(dirty tags/…)`@3928 等 |
| rebase_artifact_paths | 4538-4584 | 无（路径字段翻转） | **`_save()` 全量**@4580 |
| migrate_legacy_resources | 4585-4614 | **直接改文档列表后 `_invalidate_maps`**@4600 | **`_save()` 全量**@4601 |
| `_rollback` | 1569-1608 | `_remove_asset`/`_remove_version`/`_remove_run`（投机型 add 的逆操作）+ current/payload 回写 | — |
| v11 bundle 放置（service_v11.py） | 380/394, 552/563 | add / 失败回滚 remove；其余 save-only@598/606/633/781；maps 读@121/183/666/698/756 | `dirty` |
| adapter 桥接（adapter.py，D5 退役） | — | `_set_legacy_bridge` | `_save(assets=…)` |

maps 生命周期锚点：open 贪心构建@940；`_reload_document_locked` invalidate@1102；`rebuild_index` invalidate@1194；warm 交换 invalidate+重建@463-467；migrate invalidate@4600。

### 1.4 `_save` → flush → revision（前进时机冻结）

`_save(dirty=None)`(1015-1047)，持锁：
1. **`_mutation_serial += 1` 无条件最先执行**（含 batch 内、含后续失败——serial 只增不回滚，never resets）。
2. `_batch_depth>0`：`dirty is None` → `_pending_reconcile=True`；否则 `_pending_dirty.merge(dirty)`；**直接 return**（不 bump revision、不 flush、不 `_mutations_since_manifest++`）。
3. 非批：`document.catalog_revision += 1` → `_flush_canonical_locked(dirty or 空, reconcile=dirty is None)`；**异常 → revision -= 1 后 re-raise，不 reload（内存保留变更，与盘分歧，靠调用方 `_rollback`）**；成功 → `_mutations_since_manifest += 1` → `_maybe_checkpoint_manifest_locked()`。

`_flush_canonical_locked`(1049-1084)：
- **前置检查（#411 快速失败）**：`index.revision()` 非 None 且 ≠ `_flushed_revision` → `CatalogStaleWriteError`。
- `reconcile` → `index.reconcile(document, expected_revision=_flushed_revision)`；否则 → `index.apply_changes(document, dirty, lookups={assets: maps.asset_by_id, versions: maps.version_by_id, runs: maps.run_by_id}, expected_revision=_flushed_revision)`（maps 即 O(Δ) 查找 seam）。
- **事务内 CAS（#1220）**：`expected_revision` 在 `BEGIN IMMEDIATE` 内比对（db.py 2028-2051 / reconcile 2454），外来提交在 pre-check 与事务之间落地也会中止——至多一个冲突写者成功。
- 成功后 `_flushed_revision = document.catalog_revision`（基线刷新）。

`_reload_document_locked`(1086-1108)：load 失败 → 清 pending 并抛 CatalogError；成功 → 换 document、invalidate maps、清 pending/batch 状态、`_flushed_revision = index.revision()`。**这是"内存永不领先于盘"的恢复原语**（#1027：重载即回滚快照，不做深拷贝）。

`_maybe_checkpoint_manifest_locked`(1110-1126)：`_mutations_since_manifest > 1` → return；manifest 文件已存在 → return；否则 `export_manifest()`（**吞掉一切异常**，含 StaleWrite）。净效果：只在"manifest 尚不存在 且 距上次 checkpoint ≤1 次非批 save"时写（新项目首个成功 flush 必写；规模项目静默）。`export_manifest`(987-1011)：**自做 #411 前置检查（StaleWrite 不吞，显式调用者拿到真错误）** → 写 manifest → 记 mtime 到 sync_state → `_mutations_since_manifest=0`。

`index_revision()`(1196) = **store 的 revision**（非 document）。`ensure_index_ready`→`_ensure_index_fresh`(1144-1167)：**Python 未持服务锁**（仅靠 warm-guard 的锁 + SQLite 层串行）；stale → StaleWrite；否则 reconcile(expected_revision)。`rebuild_index`(1173-1194)：持锁、pre-check stale、reset+rebuild、`_flushed_revision=document.catalog_revision`、invalidate maps。

### 1.5 `_BatchSave` 合批语义（153-217, 1128-1142）

- **enter**（持锁）：depth==0 时采样 `_batch_base_revision = document.catalog_revision`、清空两个 overlay；depth+=1。
- **exit**（持锁）：depth-=1；仍嵌套 → 直接返回（**只有最外层 flush**）。最外层：先清 base_revision/overlays → 若（body 异常）或（`_pending_dirty.is_empty()` 且 ¬`_pending_reconcile`）→ `_reload_document_locked()`（放弃一切）→ 否则取出 combined dirty + reconcile 标志并清零 → **`document.catalog_revision += 1`（恰在此处前进一次）** → flush；**flush 异常 → reload + re-raise**（reload 顺带恢复批前 revision）；成功 → `_maybe_checkpoint_manifest_locked()`。
- **异常路径**：body 异常 = 什么都不落盘 + reload（内存回滚到 store 状态）；flush 失败 = 事务已回滚 + reload + re-raise。嵌套时内层异常沿外层 exit 走放弃分支。
- **overlay（#1139）**：`_add_version` 在 depth>0 时对 managed 记 `_batch_overlay_managed[(source_uri, sha256)] = id`（**无 RAW/¬trashed 谓词、字段可 None**），非 managed 记 `_batch_overlay_external[path]=id`（任何非 managed）。批内 remove **不**清 overlay（消费侧 `get_version` 活性校验兜底）。消费方是 adapter `_find_managed_raw`/`_find_external_by_path`(adapter.py 348-485) 的三层梯：① index_revision==document.revision → SQLite 直查；② `_batch_overlay_fresh()`（depth>0 ∧ index_revision==base_revision，即 store=批前状态）→ (index ∪ overlay) 完备，miss 即缺席证明；③ 文档线性扫描并**回写修复 maps 键**(416-418)。C++ 侧 adapter 退役（D5），该梯的宿主是 import 去重路径（接口点见 ③）。
- `mutation_serial` 与批：每次内层 `_save` +1（即使 deferred）；**批 exit 本身不 +1**。`catalog_revision` 批内冻结在批前值——这正是 revision-键缓存（聚合 4242-4262、paged 4384、adapter tag map）必须二元键 `(catalog_revision, mutation_serial)` 的原因。

### 1.6 读侧新鲜度（`_query_index_if_current` 4324-4345 / 聚合缓存 4233-4322）

- `_batch_depth>0` → None（store 没见过批内变更，必须文档兜底）。
- lazy 且 ¬warm → index（文档为空设计上，store 即真相）——C++ 不移植（见 ⑤）。
- `index.revision() != document.catalog_revision`（或读失败）→ None；否则 index。
- 聚合缓存单槽，键 `(catalog_revision, mutation_serial, include_trashed)`；`cached_catalog_aggregates` 只读不算（UI 徽章同步路径）。

### 1.7 懒开 / warm / 方法包装（404-489, 1290-1324, 4616-4711）——**不 1:1 移植边界**

`_lazy/_warm/warm_document/require_warm/_warm_locked/_lazy_get_*/_lazy_read_cache` + `_WARM_REQUIRED_METHODS`(4616-4689) 的 functools 包装(4692-4708)：全部是 Python GUI 打开 100k 工程的**性能形态**（懒物化 + 后台 warm + 读直连 SQLite + 包装器强制物化）。C++ 等价 = **直连**：service core 只做贪心 open（= Python `_warm=True` 恒成立），无包装层、无 `_lazy_read_cache` 对象恒等缓存。语义上唯一需要保留的是 1.6 的"batch 内 store 不可信"判定（与懒开无关）。close() 的懒会话 mtime 快路径（958-985）随之退役。

---

## ② 冻结 C++ API 提案（C++20、Qt-free；仅提案不实现）

### 2.1 已有 vs 缺失（document_index.hpp 现状）

**已有**：`DocumentIndex`（全量 `rebuild` 快照；`asset/version/run`、`versions_of_asset/children_of`、`asset_by_legacy_id`、`managed_raw_for/external_for`）；自由函数 `managed_raw_dedup_key/external_dedup_key`（谓词与 1.1 精确一致，含 ¬trashed）。
**缺**：增量维护（add/remove/rebridge/drop）、节点稳定地址、batch、save/flush/reload/checkpoint/CAS 编排、mutation_serial、overlay。**关键障碍**：`DocumentIndex` 存 `const T*` 指向 `CatalogDocument` 的 `std::vector` 值元素——vector 扩容/删除使指针失效，Python 的"对象引用恒稳"语义在值存储上不成立。

### 2.2 新增 `libs/catalog/include/pwb/catalog/service_core.hpp` + `src/service_core.cpp`

```cpp
// service_core.hpp — DataCatalogService 编排核（maps/save/batch/revision-CAS）。
// 惰性文档契约（service.py _lazy/_warm/_WARM_REQUIRED_METHODS）不移植：
// core 恒为贪心 open（= Python eager，_warm 恒 true）。Qt-free, C++20。
#pragma once
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include <cstdint>, <filesystem>, <mutex>, <optional>, <string>, <string_view>, <vector>

namespace pwb::catalog {

// Python list.remove 的身份移除（#1044）：核心内部对节点指针判等。
class CatalogEntityStore {          // 稳定地址的实体图（= Python 对象引用语义）
 public:
  const DataAsset*  add_asset(DataAsset a);     // append 文档序，返回稳定指针
  const DataVersion* add_version(DataVersion v);
  const DataRun*    add_run(DataRun r);
  void remove_asset(const DataAsset* a);        // 身份移除，保序
  void remove_assets_bulk(std::vector<const DataAsset*> as);
  void remove_version(const DataVersion* v);
  void remove_versions_bulk(std::vector<const DataVersion*> vs);
  void remove_run(const DataRun* r);
  CatalogDocument materialize() const;          // O(N) 值拷贝，仅供全文档操作
  const DataAsset* find_asset(std::string_view id) const;   // 线性，仅降级路径
  // ... 版本/运行同构；文档序遍历迭代器
};

class CatalogMaps {                 // _CatalogMaps 等价（增量维护版）
 public:
  void rebuild(const CatalogEntityStore& doc);            // _ensure_maps
  bool consistent(const CatalogEntityStore& doc) const;   // _maps_consistent（测试）
  // 增量维护 —— 与 CatalogEntityStore 写操作在同一 API 内原子同变（1.2 契约）
  void on_add_asset(const DataAsset* a);                  // I2 活接管规则
  void on_remove_asset(const DataAsset* a);               // 触发 rebridge({id, legacy_id})
  void on_remove_assets_bulk(...);                        // 单次 rebridge(survivors)
  void on_add_version(const DataVersion* v);              // 末位胜 dedup 键
  void on_remove_version(const DataVersion* v);           // 含 drop_dedup_keys（trash-agnostic 所有权校验）
  void on_remove_versions_bulk(...);                      // 删空 versions_by_asset 桶键
  void on_add_run(const DataRun* r);  void on_remove_run(const DataRun* r);
  void on_append_parent(const DataVersion* child, std::string_view parent_id);
  void on_set_legacy_bridge(const DataAsset* a, std::string legacy_id);
  // 查询（O(1)）
  const DataAsset*  asset(std::string_view id) const;
  const DataVersion* version(std::string_view id) const;
  const DataRun*    run(std::string_view id) const;
  const DataAsset*  asset_by_legacy_id(std::string_view legacy_id) const;
  const DataAsset*  live_asset_by_legacy_id(std::string_view legacy_id) const;
  const std::vector<const DataVersion*>* versions_of_asset(std::string_view id) const;
  const std::vector<const DataVersion*>* children_of(std::string_view pid) const;
  std::optional<std::string> managed_raw_for(std::string_view uri, std::string_view sha) const;
  std::optional<std::string> external_for(std::string_view path) const;
  // apply_changes 的 O(Δ) 查找 seam（见 ③ R1）
};

class CatalogServiceCore {          // 编排核：持锁 + store + maps + save/batch
 public:
  struct Deps { CatalogRepository* repo;                 // R1 seam（不拥有）
               std::filesystem::path manifest_path; };
  CatalogServiceCore(CatalogDocument eager_doc, Deps deps);  // R3 open 流程的终态

  // -- 查询（自愈：miss → rebuild 一次再判，再 miss 才报 unknown）--
  const DataAsset*  find_asset(std::string_view id);
  const DataVersion* find_version(std::string_view id);
  // ... §1.2 查询面同构；next_version_number（versions_by_asset 基础上 O(V_a)）

  // -- 维护 API：实体写回的唯一入口（1.3 矩阵）；返回稳定指针 --
  const DataAsset*  add_asset(DataAsset a);
  const DataVersion* add_version(DataVersion v);
  const DataRun*    add_run(DataRun r);
  void remove_asset(const DataAsset*);  void remove_assets_bulk(...);
  void remove_version(const DataVersion*);  void remove_versions_bulk(...);
  void remove_run(const DataRun*);
  void append_parent(std::string_view version_id, std::string_view parent_id);
  void set_legacy_bridge(const DataAsset*, std::string legacy_id);
  void invalidate_maps();             // 直接改文档列表后的显式逃生口（migrate 形态）

  // -- save / revision（1.4 契约）--
  domain::DataError save();                      // 全量 reconcile（dirty 未知）
  domain::DataError save(DirtySet dirty);        // 增量 flush
  std::uint64_t mutation_serial() const;         // 恒增；失败也不回滚
  int document_revision() const;                 // document.catalog_revision
  std::optional<int> index_revision() const;     // store revision
  std::optional<int> flushed_revision() const;   // CAS 基线（测试/诊断）

  // -- batch（1.5 契约；RAII 析构无法传播异常 ⇒ 冻结 callable 形态为公面）--
  // body 抛出或返回错误 ⇒ reload + 不落盘 + 错误外传；成功 ⇒ 恰一次 flush(+1 revision)
  template <typename F> auto batch(F&& body) -> std::invoke_result_t<F&&>;
  // 内部允许 begin_batch()/end_batch() 配对（end_batch 可返回 DataError），不作公面冻结。

  // -- manifest --
  domain::DataError export_manifest(bool pretty = false);  // #411 前置检查，stale 报错不吞
  void checkpoint_manifest_throttled();                    // 1.4 触发条件，内部吞错
  void close();                                            // checkpoint(吞错) + repo->close()

  // -- 读侧新鲜度（1.6；供 R2 双轨读）--
  bool index_current_for_read() const;   // batch>0 ⇒ false；index_rev==doc_rev ⇒ true

 private:
  mutable std::mutex mutex_;           // 显式串行化，见 2.3
  CatalogEntityStore doc_;
  CatalogMaps maps_;                   // 可空语义：built_ 标志
  std::uint64_t mutation_serial_ = 0;
  int batch_depth_ = 0;  DirtySet pending_dirty_;  bool pending_reconcile_ = false;
  std::optional<int> batch_base_revision_;
  std::unordered_map<std::string, std::string> overlay_managed_, overlay_external_;
  std::optional<int> flushed_revision_;
  int mutations_since_manifest_ = 0;
  // *_locked 私有方法族：save_locked / flush_locked / reload_locked /
  // maybe_checkpoint_locked / batch_enter_locked / batch_exit_locked
};

}  // namespace pwb::catalog
```

TU 划分：`service_core.cpp`（编排 + batch + flush/CAS 调用）、`service_core_maps.cpp`（CatalogMaps 增量维护，或并入前者）；`CatalogEntityStore` 与 `CatalogMaps` 放同头文件（内部协作紧，无独立消费者）。`DirtySet`、`CatalogRepository::apply_changes/reconcile/revision/write_all/rebuild/reset/load_document` 是 R1 交付面（③）。

### 2.3 串行化设计（C++ 无 RLock，如实权衡）

Python `threading.RLock`(288) 可重入——公共方法在 `_save` 下嵌套。C++ 冻结：
- **默认 `std::mutex`（非递归）+ `*_locked` 分层**：公共方法持锁一次后只调 `_locked` 私有族；**不变式：持锁路径禁止再进公共方法**（以可重入为前提的 Python 嵌套全部改写为直调 `_locked` 层）。理由：Python 服务文档化支持多线程（UI 线程 save + worker verify_integrity 并发），C++ adapter 面预期相同；读者需要 document+maps 一致快照，故读写同锁（与 Python 等价，不用 shared_mutex——DocumentIndex 快照可在未来提供无锁读升级，不冻结）。
- **备选（记录不冻结）**：单线程假设（UI worker 独占）+ `assert(!locked_by_other_thread)` 调试哨。省锁但砍掉 Python 明示的并发读契约，且 #1218/#1222 语义依赖"锁内编排"表述。若后续实测锁是瓶颈再评估。
- Python 已知锁不一致点：`_ensure_index_fresh`/`ensure_index_ready` **不持服务锁**（1144-1167）——C++ `ensure_index_ready` 统一持锁（严格更强，无行为回退；偏离记录于 ⑤）。

### 2.4 revision/serial/CAS 编排冻结（`save_locked` 伪码）

```
save_locked(dirty?):            # 1.4 精确映射
  ++mutation_serial_
  if batch_depth_ > 0:
      dirty ? pending_dirty_.merge(dirty) : pending_reconcile_ = true;  return Ok
  ++doc_.revision
  err = flush_locked(dirty or {}, reconcile = dirty == nullopt)
  if err: --doc_.revision; return err        # 不 reload（Python 奇偶性：内存保留变更）
  ++mutations_since_manifest_; maybe_checkpoint_locked()   # 吞一切错误

flush_locked(dirty, reconcile):
  stored = repo->revision()
  if stored && stored != flushed_revision_: return StaleWrite        # #411
  err = reconcile ? repo->reconcile(materialize(), flushed_revision_)
                  : repo->apply_changes(resolver, dirty, flushed_revision_)  # #1220 事务内 CAS
  if !err: flushed_revision_ = doc_.revision
```

`batch(body)`：enter（depth 0 时采样 base_revision、清 overlay）→ 执行 body（锁外或锁内由 body 决定；实体维护 API 自持锁）→ exit：depth-- ；嵌套则返回；异常/空 pending → `reload_locked()` 后传播；否则 revision++ → flush（失败 reload 后传播）→ maybe_checkpoint。reload 失败本身按 1.4 抛 CatalogError 语义（DataError StoreUnreadable）。

StaleWrite 错误编码：冻结"**可区分的错误身份**"（`domain::DataError` 新 code `StaleWrite`，或独立异常类型）；Python catch 面按 `CatalogStaleWriteError` 区分（open 的 error 分流、export_manifest、flush、ensure_index_fresh、rebuild_index 五处），C++ 必须保留可判别性——具体编码与 R1 对齐。

---

## ③ 依赖与接口点

- **R1（db.py apply_changes/DirtySet 通道）**：① `DirtySet` C++ 型：8 桶（assets/versions/runs/tags/models/model_versions/asset_tags/version_tags），**mark 顺序必须保序**（db.py `_ordered` 2001-2026 靠它维持 rowid/文档插入序，批量事务内新行按 mark 序追加）——建议 `std::vector<std::string>` + 并存 set 去重；`merge`/`is_empty` 语义同 799-829。② `CatalogRepository` 增：`apply_changes(resolver-or-document, DirtySet, EntityResolver, std::optional<int> expected_revision)`、`reconcile(document, expected_revision)`、`revision() -> optional<int>`、`write_all/rebuild/reset/load_document`、`find_managed_raw/find_external_by_path`（dedup 梯第①层）。③ 查找 seam 冻结为 `struct EntityResolver { const DataAsset* (*asset)(void*, std::string_view); const DataVersion* (*version)(void*, std::string_view); const DataRun* (*run)(void*, std::string_view); void* ctx; }`（或等价小虚接口）——core 传 `CatalogMaps` 指针实现，保证 O(Δ)；apply_changes 在 schema 缺失时回退 write_all（db.py 1976-1983）。④ 事务内 CAS 失败必须以 StaleWrite 身份返回。
- **R3（open 流程构建 maps）**：open 健康分流/legacy 迁移/`_record_manifest_mtime_ns` 记账归 R3；open 终态 = `CatalogServiceCore(eager_doc, deps)` 且 `flushed_revision = document.catalog_revision`（Python 939-940）；贪心 `_ensure_maps` 在 core 构造内完成。close 的 mtime 快路径依赖 R3 的 sync_state mtime 记账（若 R3 不做，C++ close 恒 checkpoint，见 ⑤-8）。
- **R2（SQL 双轨读）**：消费 `index_current_for_read()`（= `_query_index_if_current` 去懒开分支）与 `(document_revision, mutation_serial)` 二元缓存键；批内/revision 漂移一律文档兜底。dedup 梯（1.5 三层）宿主在 C++ import 路径：需要 core 暴露 `batch_base_revision()`/overlay 查询或聚合后的 `managed_raw_for_including_overlay()`——冻结为 core 查询面的一部分（私有梯函数 `dedup_lookup_managed_raw(uri, sha)` 内联①②③层）。
- **CONV-31 已交付面**：`DocumentIndex` 保留两个角色：全量重建参考实现（reload/rebuild/open 后的等价性 oracle）+ dedup 键自由函数被 `CatalogMaps` 复用（勿复制谓词）。gc.hpp/trash.hpp 消费 core 的 `versions_of_asset`/document 遍历（gc.py 3360/1619 同构）。

---

## ④ oracle 冻结场景建议（`tests/cpp/data/fixtures/catalog_domain/oracle.json` 扩展或行为测试）

1. **maps 一致性脚本回放**：对同一变更脚本（add asset×3 含 legacy 桥、add version×5 含 dedup 谓词命中/不命中、trash 翻转、remove 单个/批量、restore、purge 僵尸）双跑 Python service（临时真库）vs C++ core，断言：全部 8 索引逐键相等 + `materialize()` 文档相等。必含钉死项：(a) **legacy 桥不对称**——build 时首个 bridged 胜（trashed 也胜）vs remove 后 rebridge 活性优先；(b) dedup 键 build 首胜 vs add 末位胜；(c) `_drop_dedup_keys` 所有权校验（键被他者持有时不清）；(d) 单删留空桶键 vs bulk 删空桶键；(e) 身份移除不等值移除（构造等值孪生实体）。
2. **CAS 拒绝**：双实例同库，B 先 save 成功；A `save(dirty)` → StaleWrite、A document_revision 回滚到 +0、A 内存实体仍在（分歧奇偶性）、重开后只见 B 数据。`export_manifest` 在同态下显式调用 → StaleWrite 不吞。
3. **#1220 事务内 CAS**：在 flush 前置检查后、事务前直接改 store 的 sync_state revision（测试直写），断言 flush 仍中止且 revision 回滚（证明 CAS 不依赖前置检查窗口）。
4. **batch flush 时机**：批内 N 次 `_save`：mutation_serial +N、document_revision 不动、store revision 不动、行未落；exit：store revision 恰 +1、行全落、manifest（不存在时）写一次；批体抛异常 → store 零变化 + reload（内存回滚）+ serial 不回滚（+N 保留）。嵌套两层：内层 exit 零效果。空批（无 dirty）exit：仅 reload 分支，无 revision++。
5. **checkpoint 节流**：新项目：save#1 写 manifest（mtime 记账 + 计数清零）；save#2 不重写（mtime 不变）；close 重写。已有 manifest 项目：首个 save 不触发重写。
6. **overlay 去重**：批内两次 import 同 (uri, sha) → 第二次解析到同一 version id；批内 remove 已 add 的 version 后再 import → 活性校验兜底（不错误命中）。

---

## ⑤ 有界偏离清单（如实）

1. **懒开/warm/包装不移植**：`_lazy/_warm/warm_document/require_warm/_lazy_*读/_lazy_read_cache/_WARM_REQUIRED_METHODS` 包装与 `_query_index_if_current` 的 lazy 分支全部退役；C++ core = Python eager 恒 warm，直连。GUI 快开性能形态由应用层另行解决（不在本切片）。
2. **RLock → std::mutex + `*_locked` 分层**：可重入改为结构化不嵌套；`ensure_index_ready` 由 Python 无锁改为持锁（严格更强）。
3. **上下文管理器 → callable `batch(body)`**：析构不可抛异常，故不冻结 RAII 公面；异常传播/重载语义逐条保持（1.5）。
4. **聚合/分页单槽缓存**：`(catalog_revision, mutation_serial, …)` 二元键语义经 `mutation_serial()`/`document_revision()` 暴露；缓存本体归调用方（UI 性能形态，不进 core）。
5. **节点存储**：`CatalogEntityStore`（`unique_ptr` 节点 + 稳定地址）替代 Python 对象引用图；`CatalogDocument` 值形态只在 `materialize()` 边界出现（全文档操作本就 O(N)，复杂度不变）。
6. **mutation_serial 用 `std::uint64_t`**（Python int 无界；C++ `models.hpp` revision 为 `int`，长会话 flush 级增长在 int 域内安全，serial 选更宽类型防累积）。
7. **StaleWrite 编码**：Python 专用异常 → C++ `domain::DataError` code（或等价可判别身份），编码细节与 R1 对齐后冻结。
8. **close 懒快路径**：若无 R3 mtime 记账，C++ close 恒 checkpoint（Python 仅 lazy 无变更时跳过；eager Python 也恒写，故对 eager 语义零偏离）。
9. **Windows `gc.collect` 重命名重试环（open corrupt 分流）**：归 R3；C++ 以 `std::filesystem::rename` best-effort 等价，无 GC 环（平台细节，记录不逐帧对齐）。
10. **`export_manifest(pretty)`**：repository 现签名无 pretty；默认 compact（#1183 主路径）一致，pretty 为显式导出增参（实现时补）。

---

## ⑥ 风险 / 先例坑

- **指针失效是头号坑**：任何绕过维护 API 直接改 `CatalogEntityStore` 向量的路径都会悬垂 `CatalogMaps`。冻结纪律：实体写只走维护 API；确需直改（migrate 形态 4600）必须先 `invalidate_maps()`。debug 构建加 `consistent()` 断言（先例：D3 三处 DataError 哨兵坑——错误路径返回值必须显式）。
- **双索引漂移**：`DocumentIndex`（快照）与 `CatalogMaps`（增量）并存，谓词/桥规则必须单源（复用 document_index 的自由函数；桥规则不对称要注释钉死，防止后人"顺手修齐"）。
- **mark 序即行序**：DirtySet 若用无序容器，批量插入 rowid 序漂移 → load_document 文档序漂移 → maps 桶序漂移 → oracle diff 爆炸（R1 接口硬约束）。
- **非批 save 失败不 reload**（Python 奇偶性）：内存领先于盘直到调用方 `_rollback`/reload。C++ 保持同构，但这是 adapter 集成的经典坑——文档化 + oracle 场景 2 钉死。
- **serial 失败也前进**：缓存键消费者必须把"失败 mutation"也视为失效（Python 同构；实现方容易"优化"掉）。
- **reconcile 的 DELETE 全量 diff 语义**：stale 基线下 reconcile 会删外来行——Python 以 pre-check 拒之；C++ 必须两道都在（#411+#1220），只留事务内 CAS 的话 pre-check 的快速失败错误信息（中文文案）也应对齐（先例：D4 文案/形状差异要如实记录）。
- **CMake/无本机 cmake**：新 TU 挂 `pwb_catalog` target_sources 按 CONV-15/26/31 先例（D2）。
- **批 exit 重载失败窗**：reload 抛 CatalogError（store 不可读）时批异常被替换——Python 同构（1093-1100），C++ 用 DataError 编码保留两层信息（返回 flush 原错误 + 附注 reload 失败，或链式错误；冻结为实现期决策，oracle 只钉"异常仍外传"）。
