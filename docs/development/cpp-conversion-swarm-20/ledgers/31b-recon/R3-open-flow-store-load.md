# R3 recon — open() 全流程健康分流 + store.load/save + C++ open 编排契约冻结

CONV-31b 切片 R3（只读侦察，不改源码）。锚点行号 = worktree `feat/cpp-catalog-service` 当前 HEAD。
源：`paleo_workbench/catalog/service.py`（open/close/export_manifest/sweep_temp_on_open/mtime 记账）、
`paleo_workbench/catalog/store.py`（全文 229 行）、`paleo_workbench/catalog/db.py`（store_health/reset/write_all）、
既有 C++：`libs/catalog/include/pwb/catalog/repository.hpp` + `src/repository.cpp` + `gc.hpp` + `document_index.hpp` + `legacy_migration.hpp`。

---

## ① 语义契约

### 1.1 open() 健康分流矩阵（service.py:779-943；健康分类 db.py:1510-1576）

健康五值（db.py:1511）→ C++ `StoreHealth`（repository.hpp:17，一一对应）：

| Python | C++ | 判定（db.py 锚点） |
|---|---|---|
| `absent` | `Missing` | `not db_path.is_file()`（1523） |
| `legacy` | `Legacy` | size==0（1526，crashed first-open）；count 探针 "no such table"（1538）；sync_state 无表且 assets 空（1563）；`index_schema_version` 行缺失（1570）或版本 < 5（1576） |
| `canonical` | `Canonical` | 探针全过且 `index_schema_version == 5`（1576） |
| `corrupt` | `Corrupt` | DatabaseError/OSError/ValueValueError/TypeError 系（1541/1567）；sync_state 无表但 assets 非空（1563，tampered）；版本值非整数（1574） |
| `error` | `Unreadable` | OperationalError 非 no-such-table（1540，busy/locked）；stat OSError（1528） |

探针语义要点：`SELECT count(metadata) FROM assets` + `count(path) FROM versions` **强制数据页读**（PK autoindex 可答的 count(*) 会漏坏页，1532-1535）。C++ `status()`（repository.cpp:225-276）现用 `sqlite_master` 探针 —— 口径差见 ⑤。

**open() 处置矩阵**（service.py:778-943）：

| 入口健康 | 分支条件 | 处置动作 | 锚点 |
|---|---|---|---|
| canonical | `not lazy` | `index.load_document()`（db.py:1588，floor 语义 version ≥ 5，异常吞为 None）；**None → 降级 health="corrupt"**（path B：探针过但行读不出，#1027 review） | 818-826 |
| canonical | `lazy=True` | mtime 记账分支（1.2）；构造 `CatalogDocument(catalog_revision=store revision or 0)` 空文档、`_lazy=True`、`_warm=False`，**早退：不 `_ensure_maps`、不 sweep_temp** | 875-908 |
| error | 任意 | **raise CatalogError，消息逐字**：`f"Canonical catalog store exists but is unreadable: {index.db_path}. Not overwriting it with the manifest; resolve the read failure (close other instances, retry) and reopen."`（不落 manifest 回退——防 #411 last-writer-wins） | 827-837 |
| corrupt | 任意（含降级） | ① 隔离重命名 `f"{db_path.name}.corrupt-{datetime.now():%Y%m%d-%H%M%S-%f}"`（%f=微秒 6 位，同目录）② 先 `index.close()`（Windows 池连接握文件阻塞 rename）③ `os.replace` 失败 PermissionError → `gc.collect()+sleep(0.05)` 重试 ×10，仍败 best-effort 放行 ④ `index.reset()`（db.py:1042-1054：close + unlink db/`-journal`/`-wal`/`-shm`）。随后 document=None 落入迁移分支 | 838-874 |
| absent / legacy | — | document=None 直落迁移分支 | — |
| canonical（非 lazy，doc 已载） | `json_path.is_file()` | mtime 记账分支（1.2，比较对象 = document.catalog_revision） | 909-927 |
| **迁移/初始化** | `document is None`（absent/legacy/corrupt-reset 后） | `document = store.load()`（1.3 全部分支在此引爆/回退）→ `index.write_all(document)`（db.py:1578→rebuild：单事务 delete-and-rewrite，崩溃靠 SQLite 回滚，legacy json 不动，#1027）→ **失败向上传播**（重试从头干净）→ json 存在则 `_record_manifest_mtime_ns`（F8 基线） | 928-936 |
| 收尾（非 lazy） | — | 构造 service；`_flushed_revision = document.catalog_revision`；`_ensure_maps()` eager（首突变 O(Δ)）；`sweep_temp` → `sweep_temp_on_open()` | 938-942 |

### 1.2 manifest mtime 记账（service.py:238-261 + 884-896/915-927）

- 状态存 sqlite `sync_state` 表 key=`manifest_mtime_ns`（值=十进制 ns 字符串）。读：`_read_sync_state` → int，ValueError→None（238-247）。写：`INSERT OR REPLACE`，**全 try 吞掉——记账永不搞挂 checkpoint**（249-261）。
- `_disk_mtime_ns` = `path.stat().st_mtime_ns`，OSError→None（218-222）。
- 采纳规则（三条路径同构：lazy 884-896、非 lazy 915-927、close 969-976）：
  记账失效（recorded None / current None / **不等**）→ `store.load()`（CatalogError→legacy=None，corrupt manifest **不阻塞 open**）→ 当且仅当 `legacy.catalog_revision > {store/doc}_revision`（**严格大于**，等于不采纳）→ `index.write_all(legacy)` + 采用该 revision/document。语义：老 json-canonical 版本背后写 manifest 时，新 revision 赢并被事务性重导入。

### 1.3 store.load 精确分支（store.py:103-155）与错误消息逐字

| # | 条件 | 动作 |
|---|---|---|
| L1 | `catalog.json` is_file，`json.loads`+`model_validate` 成功 | 返回文档 |
| L2 | 解析/校验抛 `OSError/ValueError/TypeError`（JSONDecodeError 与 pydantic ValidationError 均 ValueError 子类）且 **bak 不存在** | `_isolate_corrupt_file(canonical)` → **raise CatalogError**：`f"Catalog file is corrupt and no backup is available: {path} ({error})"` |
| L3 | bak is_file，解析/校验成功 | **重晋升**：`os.replace(bak, path)` + `fsync_dir`，OSError 吞掉（best-effort）；返回 bak 的文档 |
| L4 | bak 也解析失败 | `_isolate_corrupt_file(canonical)` + `_isolate_corrupt_file(bak)` 双隔离 → **raise CatalogError**：`f"Catalog file and its backup are both corrupt: {path} (backup error: {error})"`（audit #848：不留原始 JSONDecodeError 泄漏） |
| L5 | canonical 缺失且 bak 缺失 | 返回 `CatalogDocument()`（空目录 = revision 0 空文档） |

`_isolate_corrupt_file`（48-63）：目标名 `f"{path.name}.corrupt-{strftime('%Y%m%d-%H%M%S-%f')}"`；`os.replace` + `fsync_dir`；OSError → **返回原路径**（字节原地保留，best-effort）。注意同一微秒两次隔离会 os.replace 覆盖——Python 现行为，如实保留。

### 1.4 store.save 五步 + unchanged-skip + 首存种子（store.py:157-229）

1. `ensure_catalog_layout`（storage.py:70-82，**resolved** project dir 派生 `<proj>.artifacts/` + 各 stage 目录）。序列化：pretty=`indent=2` / compact=`separators=(",",":")`，均 `ensure_ascii=False`（183-192）。
2. **unchanged-skip #1183**（194-199）：`digest=sha256(payload utf-8).hexdigest()`；当 `_last_write` 非空且 digest 相等且**盘上 mtime_ns 仍等于上次记录值** → 直接 return（不碰盘）。mtime 卫兵防外部删改 manifest 后的假 skip。
3. tmp：`mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=同目录)` → 形如 `.catalog.json.<随机>.tmp`；write+flush+**fsync**（200-208）。
4. 旧 canonical 存在 → `os.replace(path, bak)`（old_moved=True）；**不存在（首存）→ `_seed_initial_backup(bak, payload)`**（66-87）：原子写**同一 revision** 到 bak（#372/C14：一次已存的目录永无无备份窗口）。tmp 中缀 `.catalog.json.bak.<随机>.tmp`，失败 unlink+raise。
5. `os.replace(tmp, path)` + `fsync_dir`（214-215）。**异常恢复**（216-226）：`safe_unlink(tmp)`；若 old_moved 且 path 不存在且 bak 存在 → `os.replace(bak, path)` best-effort（把上一版放回去），然后 raise。
6. 成功后记录 `_last_write = (digest, mtime_ns(path))`（227-229）。

### 1.5 close / export_manifest / sweep（service.py:945-1011, 1110-1126）

- `close`（958-985）：lazy 且 `_mutations_since_manifest==0` → 仅当 recorded mtime ≠ 盘上 mtime（或 json 缺失）才 export；否则 export。一切失败吞掉（manifest 永不阻塞关 canonical）；再 `index.close()`。
- `export_manifest`（987-1011）：锁内 #411 stale 卫兵——`index.revision() != _flushed_revision` → **raise CatalogStaleWriteError（中文逐字）**：`"数据目录元数据已被其他实例修改；为避免覆盖他人提交，本次 manifest 导出已中止。请重新打开工程后重试。"`；随后 `store.save` + `_record_manifest_mtime_ns` + `_mutations_since_manifest=0`。
- `_maybe_checkpoint_manifest_locked`（1110-1126）：节流——仅当 `mutations<=1` 且 **manifest 尚不存在**（新工程首存可携带性）时补写，异常吞掉。
- `sweep_temp_on_open`（945-956）：`_gc_sweep(dry_run=False, explicit=False)` 全 try 吞（清残永不阻塞 open）。注意它在 `_WARM_REQUIRED_METHODS`（4618）里：lazy 服务先 require_warm 物化再扫；**lazy open 早退路径根本不调它**。
- **迁移二义性澄清**：open() 的"legacy 迁移"= **catalog.json(manifest) → catalog.sqlite 事务重建**（write_all）。`.paleo.json resources → catalog` 是**另一个面**：`service.migrate_legacy_resources`（4585-4602）锁内调 `migration.migrate_resources` 纯文档投影（幂等、legacy id 复用为 asset id、`_invalidate_maps`+`_save`），**不在 open 流程内**，C++ 已由 CONV-31 `legacy_migration.hpp migrate_resources` 承接。二者仅共享"事务性/源不动/幂等"原则——oracle 与 API 均不得混同。

---

## ② 冻结 C++ API 提案（C++20、Qt-free；只提案不实现）

### 2.1 repository.hpp / repository.cpp 追加（31-findings B 预告的 `load_manifest` 落点）

```cpp
namespace pwb::catalog {

// ---- store.py 路径推导 parity（storage.py catalog_dir_for: <proj>.artifacts/metadata）
std::filesystem::path catalog_manifest_file(const std::filesystem::path& project_path);      // .../metadata/catalog.json
std::filesystem::path catalog_manifest_bak_file(const std::filesystem::path& project_path);  // .../metadata/catalog.json.bak

// ---- store.py _isolate_corrupt_file(48-63) parity，best-effort：
// 重命名为 "<name>.corrupt-YYYYmmdd-HHMMSS-<微秒6位>"（本地时区）；失败返回原路径。
std::filesystem::path isolate_corrupt_file(const std::filesystem::path& file);

// ---- store.py CatalogStore.load(103-155) parity。
// 缺失=空文档；L2/L4 为 DataError(CorruptDatabase, <Python 骨架逐字, 括号 detail 见⑤>)。
struct ManifestLoad {
    CatalogDocument document;              // 空 = L5
    bool from_backup = false;              // L3
    bool repromoted_backup = false;        // L3 的 os.replace(bak, path) 已执行
    std::filesystem::path isolated;        // canonical 隔离目标（空=未隔离）
    std::filesystem::path isolated_backup; // bak 隔离目标（空=未隔离）
    int schema_version = 1;                // 只读不门禁（与 Python load 一致）
    domain::Json models_rows = domain::Json::array();        // 透传（无域读模型）
    domain::Json model_versions_rows = domain::Json::array();
};
domain::Result<ManifestLoad> load_manifest(const std::filesystem::path& manifest_path);

// ---- store.py CatalogStore.save(157-229) parity（含 #372/C14 首存种子与 #1183 skip）。
struct ManifestCheckpointState {            // = Python _last_write（实例态）
    std::string digest;                     // sha256 hex
    std::int64_t mtime_ns = 0;
    bool valid = false;
};
domain::DataError save_manifest(const std::filesystem::path& manifest_path,
                                const CatalogDocument& document,
                                const domain::Json& models_rows,
                                const domain::Json& model_versions_rows,
                                bool pretty = false,
                                ManifestCheckpointState* state = nullptr);  // null = 不做 skip
}  // namespace pwb::catalog
```

manifest JSON 键集（= Python `CatalogDocument.model_dump` 的 10 键，models.py:276-294）：`schema_version, catalog_revision, assets, versions, runs, tags, models, model_versions, asset_tags(dict), version_tags(dict)`——**无 working_copies/lineage/staging_leases**（仅存 SQLite）。C++ 解析器需新增 `parse_manifest(Json)→ManifestLoad`（现仅有写侧 export_manifest:481-565 的序列化半边）。错误消息骨架逐字：
- `"Catalog file is corrupt and no backup is available: " + path + " (" + detail + ")"`
- `"Catalog file and its backup are both corrupt: " + path + " (backup error: " + detail + ")"`

### 2.2 open 编排归属：新 `include/pwb/catalog/service_core.hpp` + `src/service_core.cpp`

理由：open 编排需要 status + load_document + load_manifest + write_all + mtime 记账 + DocumentIndex + gc 接线，跨 repository/store/gc 三面，不应塞进 repository（单一 sqlite 职责）也不该等一个完整 service 类（31b 尚无锁/懒开/批量面）。落点为无状态自由函数 + 报告结构体：

```cpp
namespace pwb::catalog {
struct CatalogOpenOptions { bool lazy = false; bool sweep_temp = true; };

struct CatalogOpenReport {
    StoreHealth health;                     // 降级后终值（path B 记 Corrupt）
    bool rebuilt_from_manifest = false;     // write_all 发生（迁移/corrupt 恢复）
    bool adopted_newer_manifest = false;    // mtime 分支采纳了更新的 manifest revision
    bool manifest_baseline_recorded = false;
    std::filesystem::path isolated_store;   // corrupt sqlite 隔离目标（空=无）
    int revision_baseline = 0;              // = Python _flushed_revision
};

struct CatalogSession {                     // 31b 后续 service 面的种子
    CatalogDocument document;               // lazy=true 时空（仅 revision）
    DocumentIndex index;                    // 仅 eager（= _ensure_maps）
    CatalogOpenReport report;
};

domain::Result<CatalogSession> open_catalog(
    const std::filesystem::path& project_path,   // .paleo.json 工程文件路径
    const CatalogOpenOptions& options = {});
}  // namespace pwb::catalog
```

编排序（严格对 1.1 矩阵）：status() → canonical/non-lazy `load_document()` None 降级 → Unreadable 抛 verbatim → Corrupt 隔离+reset → mtime 记账分支 → `load_manifest` → `write_all` → 记基线 → 构建 `DocumentIndex` → `sweep_temp` 时调 `gc::sweep_gc(ctx, /*dry_run=*/false, /*explicit_sweep=*/false, ...)` 并吞掉一切异常。**lazy=true 早退于 maps/sweep 之前**。

### 2.3 repository.hpp 追加（编排所需的 sqlite 侧小面）

```cpp
class CatalogRepository {
public:
    // ---- db.py write_all/rebuild(1578-1586) parity：单事务 delete-and-rewrite。
    domain::DataError write_all(const CatalogDocument& document);
    // ---- service.py 238-261 parity：sync_state key "manifest_mtime_ns"。
    std::optional<std::int64_t> recorded_manifest_mtime_ns() const;
    void record_manifest_mtime_ns(const std::filesystem::path& manifest_path);  // 吞错
    // ---- db.py reset(1042-1054) parity：close + 删 db/-journal/-wal/-shm。
    void reset();
};
```

`write_all` 与 R1 的 apply_changes 通道有重叠（见 ③）；若 R1 冻结 `apply_changes(full reconcile)`，则 `write_all` 应是它的全量包装而非第二实现。

### 2.4 TU/CMake

新 TU：`src/service_core.cpp`（+ manifest 解析可放 `repository.cpp` 尾部或新 `manifest.cpp`，建议后者避免 repository.cpp 再膨胀——现 1288 行）。`libs/catalog/CMakeLists.txt` 追加 `# BEGIN CONV-31b` 块（先例 CONV-15/26/31），不动既有列表。g++ 直连验证口径同 31-decisions D2。

---

## ③ 依赖与接口点

- **R1（CAS/flush/apply_changes）**：`write_all` 与 revision 读写共享 sync_state 通道——谁冻结 apply_changes，write_all 归谁包装（2.3）。`export_manifest` 的 #411 stale 卫兵（中文 CatalogStaleWriteError）依赖 `_flushed_revision` 语义 = R1 的 flush 基线；open 面只**读**基线（report.revision_baseline），不得重复实现 CAS。
- **R4（_CatalogMaps 构建）**：eager 收尾 `_ensure_maps` → C++ `DocumentIndex`（document_index.hpp:22-27，CONV-31 已交付）；lazy 路径不建、warm 时建——R4 的懒建/失效面与本处 lazy 早退契约衔接。
- **R9（C++ 面貌）**：健康枚举与 `StoreHealth`（repository.hpp:17）同名同义；错误走 `domain::Result/DataError`（ErrorCode::CorruptDatabase/NotFound/IoError）；路径推导复用 `pwb::project::artifact_dir_for`（trash.cpp:27 先例）。
- **gc.hpp**（接线点，仅记录）：`sweep_gc(context, dry_run=false, explicit_sweep=false, ...)`（gc.hpp:73）≡ `sweep_temp_on_open`；GcContext{project_path, const CatalogDocument*}（gc.hpp:51-56）。
- **legacy_migration.hpp**：不在 open 流程（1.5 澄清）；`needs_migration/migrate_resources` 是独立调用面。
- **checksum.hpp**：`save_manifest` 的 digest 用 sha256（注意 `sha256_text` 会 CRLF→LF 规范化——JSON dump 无 CR，等价；如要逐字节口径可加 `sha256_bytes`，属有界选择）。

---

## ④ oracle 冻结场景建议

1. **健康矩阵 ×5**：canonical（直接载入 revision）/ legacy（manifest 迁移 write_all + 基线记录）/ absent（空文档 revision 0 + write_all 空初始化）/ corrupt（隔离文件名正则 `^catalog\.sqlite\.corrupt-\d{8}-\d{6}-\d{6}$` + reset 三残留文件删除 + manifest 重建 revision）/ error（异常类型 + 消息逐字断言）。
2. **path B**：探针健康但行读失败 → 降级 corrupt 流（隔离 + manifest 重建，不静默空库）。
3. **mtime 记账三态**：recorded==current（不解析 manifest）/ manifest 外部更新且 revision 更大（采纳 + write_all）/ revision 相等或更小（忽略）；recorded 缺失（首次，全量解析）。
4. **store.load 四分支**：L1 常规；L3 canonical 缺 + bak 在（重晋升后 bak 消失、canonical 就位、revision 保持）；L3' canonical 坏 + bak 在（同上 + canonical 被隔离）；L2 坏且无 bak（消息逐字 + 隔离）；L4 双坏（双隔离 + 消息逐字）；L5 双缺（空文档）。
5. **save 三态**：首存种子（bak 出现且 revision = canonical）；二次保存 rotation（bak = 上一版）；**unchanged-skip**（digest+mtime 均未变 → mtime/bak 全不动）；外部改 manifest 后 mtime 失配 → skip 被击败、重写。
6. **lazy open**：空文档 + store revision 基线 + 不建 maps + 不 sweep（行为断言，非字段断言）。
7. **close 快路径**：lazy+0 突变且 mtime 基线一致 → manifest 字节不动（mtime 不变）。

---

## ⑤ 有界偏离清单（如实）

1. **错误消息括号 detail**：C++ JSON 解析器（nlohmann 系）与 Python json/pydantic 的错误文本不同——骨架与路径段逐字，括号内 detail oracle 掩码。
2. **模型校验语义**：pydantic `model_validate` 的宽松类型校验 vs C++ 手写 `parse_manifest` 显式分支（建议：任何字段缺/型错 → 按 corrupt 走 L2/L4 同一分支）；oracle 只覆盖两侧共同构造的 fixture。
3. **mtime 记账 tick**：POSIX 用 `::stat st_mtim`（ns，与 Python `st_mtime_ns` 逐 tick 一致）；Windows 用 `last_write_time` 映射 100ns tick（Python 同源）；**禁用**秒级 `_stat64`。记账只需同语言自洽 + 与 Python 写入的基线可比较。
4. **线程形态**：`threading.RLock` + db.py 每线程连接池不移植；open 编排单线程（Python open 路径本就单线程，db.py:850 注释）。lazy/warm/方法包装（#1212）是 Python UI 性能形态，31-gap §2 已裁定不 1:1 移植——C++ `lazy` 选项仅保留"空文档 + revision 基线 + 早退"语义。
5. **mkstemp 随机中缀**：模式逐字（`.catalog.json.<rand>.tmp`），随机段内容不逐字。
6. **Windows gc-retry 循环**（service.py:855-871，864-871）：Python 特有的引用环 sqlite 句柄问题；C++ 无此形态，POSIX 直接 rename，Windows 单次重试即可——如实记录。
7. **fsync_dir**：POSIX 实装（`open(O_RDONLY|O_DIRECTORY)+fsync`），Windows no-op——与 Python（storage.py:345-356）相同的平台分歧。
8. **models/model_versions**：C++ 无域读模型（models.hpp 无 Model 结构）→ `domain::Json` 透传（load 保形、save 原样回写）；`schema_version` 读取不门禁（与 Python load 一致）。
9. **status() 探针口径**：C++ 用 `sqlite_master`（repository.cpp:242）而非 Python 的强制数据页 count——坏页漏检由 path B（load_document 失败降级）兜底；矩阵语义等价，探针细节不同，如实记录。
10. **时区**：corrupt 时间戳本地时区 `%Y%m%d-%H%M%S-%f`（Python `datetime.now()`）——C++ 同取本地时间；文件名不跨语言逐字比较，正则覆盖。

---

## ⑥ 风险 / 先例坑

- **D3 哨兵**：成功路径必须显式 `DataError(ErrorCode::Ok, "")`——31 切片三处踩坑（31-decisions D3）。
- **CMakeLists 共享冲突**：必须用 `# BEGIN CONV-31b` 独立块追加，不动 CONV-31 块（31-findings B；先例 15/26）。
- **CAS 越权**：open/export 面不得私自实现 revision 比较——#411/#1220 的比较必须在写事务内（R1 领地）；export_manifest 的中文 stale 消息逐字保留。
- **reset 残留**：漏删 `-wal`/`-shm` 会让重建读到旧页（db.py:1049-1053 四后缀全删）；C++ Database 若开 WAL 尤甚。
- **fsync 顺序**：L3 重晋升 rename 后必须 `fsync_dir`（store.py:151），否则崩溃窗口丢目录项——C++ 最易省略点。
- **严格大于**：manifest 采纳用 `>`；`==` 不采纳（防同 revision 重放翻转 mtime 基线）。oracle 必须含 equal-revision 反例。
- **lazy 早退**：C++ 编排若把 sweep 统一放函数尾，会违反 1.1 矩阵（lazy 不扫）——早退位置是契约。
- **close 记账漏写**：export 后忘 `record_manifest_mtime_ns` → 每次 close 全量重写（#1183 语义丢失 + 大工程性能回归）。
- **首存种子 vs rotation 判定**：以"canonical 是否存在"为界（store.py:209/213），不要用"是否首存调用"之类的实例态判断——跨实例/崩溃后仍须正确。
- **双微秒覆盖**：同微秒双隔离 `os.replace` 覆盖前一份——Python 现状，如实保留勿"修复"。
