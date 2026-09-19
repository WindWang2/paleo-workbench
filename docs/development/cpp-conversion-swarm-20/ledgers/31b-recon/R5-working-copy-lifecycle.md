# R5 recon — working-copy 生命周期语义契约与 C++ API 冻结提案

CONV-31b 切片（catalog 域 service/db 深核）。范围：`service.py` working-copy 全组（create/list/state/discard/recover/commit）+ `committing` 状态机 + `_pending_commit_assets` 僵尸防护（#1218）+ staging lease 协作（#1222）+ `_rollback` 补偿。**不移植** `edit_session.py`（D5）——其消费面仅作验收参照（§3.5）。

行号基准：`paleo_workbench/catalog/{service,db,storage,gc,service_v11,edit_session}.py` @ feat/cpp-catalog-service；C++ 侧 `libs/catalog/{include/pwb/catalog,src}`。

---

## ① 语义契约

### 1.1 状态机全图

登记表 `working_copies`（db.py DDL 517-528，注释 512-516）：`working_id TEXT PRIMARY KEY`（`wc-` + uuid4 前 12 hex，db.py:1347）、`path TEXT NOT NULL UNIQUE`（project 相对 POSIX）、`state DEFAULT 'checked_out'`、`payload_mtime_ns`/`source_size_bytes` 可空、`created_at`/`updated_at` 秒级 ISO 本地时间；索引 `idx_working_copies_source(source_version_id)`。身份永远是 working_id，display/file name 不参与身份。

```
                 register(placement 成功后, best-effort)
   (无行) ───────────────────────────────────────► checked_out
                                                      │  读侧 dirty_hint（mtime/size 漂移，纯计算不落库,
                                                      │  _working_copy_status 2369-2381）
                                                      ▼
   commit_working_copy 2560-2566              checked_out/dirty
   （先于 payload 移动, best-effort） ──────────► committing
                        │                            │
                        │ 异常补偿 2577-2586          │ commit 成功 2589-2593
                        ▼                            ▼
                      dirty（落库回退）           (行删除) = committed 终态
                        │                            │ crash 后由 recover 判定
                        │                            ▼
                        │              recover_working_copies 2495-2514:
                        │                committed 版本存在(source_uri 命中) → 行删除
                        │                不存在 → 回 dirty（文件从未移动, 原子）
                        ▼
   discard_working_copy 2433-2463 ──► (行删除+文件 unlink) = abandoned 终态
                                      committing 态拒绝丢弃（错误见 1.3）
   任意态 + 文件缺失（save-as/打包丢 working/）→ recover 删行 2488-2494
```

要点：
- **`dirty` 的落库写点只有两处**：commit 失败回退（2583）、recover 崩溃回退（2509-2511）。读侧 `dirty_hint` 是 advisory（误报安全——告知用户"可能含编辑"），永不写库。
- `committing` → `committed` **没有行状态迁移**：成功即删行（2589-2593）。"committed" 只在 DDL 注释里作为概念终态存在。
- 所有登记表写（register/update/remove）**全部吞错**（`except Exception: pass` / `except sqlite3.Error: pass`，db.py 1402-1425 + service.py 2351-2352）——登记是簿记，永不做 checkout/commit 的门（gate）。这是契约级语义，不是疏忽。

### 1.2 持久化时机与崩溃窗（逐窗）

checkout 侧（`create_working_copy` 2270-2353 → `storage.create_working_copy` 618-644）：
1. 解析版本（`_version_or_raise` 1252-1262）→ registry 查活副本（2288-2291，吞错）。
2. 布局复制：`working/{version_id}/<payload.name>`，temp `.work-` + `os.replace` + `_make_writable` + fsync 目录（storage.py 626-643）；失败 safe_unlink temp 后 re-raise。
   - **W1（checkout 崩溃窗）**：copy 中途 crash → temp `.work-*` 落在 `working/` 下；GC temp 扫描**永不进入** `working/`/`trash/`（gc.py 113-122 skip roots），行未写 → 无行。copy 完成、register 行前 crash → 行缺失、文件在：下次同版本 checkout 走"无行但盘上有文件"复用分支（2321-2322）或 `cleanup_working_copies` 判 version id 已知则保留。
3. register 行（2339-2352）：mtime_ns 取 stat 快照、`source_size_bytes` 取源版本 size；吞错。

commit 侧（`commit_working_copy` 2525-2594 → `_commit_working_copy_inner` 2596-2643 → `register_version` 1729-1835 → `_build_version` 1670-1727 → `place_managed_file(keep_source=False)` storage.py 378-517）：
1. parent 推断（2548-2554）：`parent_version_ids` 省略时取 `working_path.parent.name`（即源 version id 目录名），仅当它存在于 `document.versions` 才采纳，否则空。bundle 侧改从 wc 行取（service_v11 538-540）。
2. 行→`committing`（2560-2566，吞错，**先于任何 payload 移动**）。
3. `asset_id is None` 分支（2607-2634，#1218）：锁内 `_new_asset` + `_add_asset`（**仅内存**，不落库）+ `_pending_commit_assets.add`；随后无锁调 `register_version(..., move=True, _restore_payload_to=working_path)`；except 锁内 `_remove_asset` + discard；finally discard。payload 搬移+哈希不持服务锁（GB 级副本不能冻结全目录）。资产行与版本行在 `register_version` 的 `_save` **同一事务**落库（DirtySet 同时含 asset+version，1821）——持久层无"零版本资产"窗口；窗口只在内存文档，由 `_pending_commit_assets` 保护（见 1.4）。
4. `register_version` 内：staging lease 包住 place→commit 全窗（1776-1779，见 1.5）→ `place_managed_file(move)`：流式 copy+hash 到 `.place-` temp → fsync → `os.replace` → 只读标记 → **`safe_unlink(source)`（514-515，copy-then-unlink，非 rename）**；dedup 命中也 unlink 源（434-437）。
   - **W2（committing 已置、未 place）** crash：文件原地 → recover 回 dirty，无损。
   - **W3（replace 成功后、unlink 源后、`_save` 前）** crash：working 文件已删、无版本行 → recover 因 `path.is_file()` 为假走 `missing_dropped` 删行；已放置的 stage payload 成 stage_orphan（可被显式 GC 清）。**这是唯一真实的用户数据不可达窗口**（字节完整落在 stage 目录但无版本引用）——Python 现状如此，C++ 按 parity 保留，不得静默"修复"（见 ⑤）。
   - **W4（`_save` 已提交、删行前）** crash：版本存在且 `source_uri == working 路径` → recover `committing_dropped` 删行。
5. 成功 → 删行（2589-2593，吞错）。

失败补偿链（非 crash，逐异常，`_rollback` 1569-1608）：
- place 后校验失败（资产被删 1791-1796 / 版本 id 重复 1797-1803 / run 缺失 1805-1812）：`_rollback(payload, restore_payload_to=working_path)` → `os.replace(payload, working_path)`（1594-1600）把已搬走的副本**放回原处**；CAS 路径（blob）豁免——共享内容寻址永不 unlink（1589-1593）。
- `_save` 失败（1826-1834）：内存撤版本 + 恢复 `current_version_id` + 撤 run 输出链接 + payload 放回。
- 新资产分支失败：内存撤资产 + discard 僵尸标记（2626-2631）。
- 最外层（2577-2586）：行回 `dirty`，re-raise。
- 净效果：**不留 phantom**（无孤儿版本行/资产行/已搬无主的 working 文件——除 W3 崩溃窗外）。

### 1.3 复用判定与错误消息逐字

复用判定序（`create_working_copy`，单文件面）：
1. registry 活副本 = `get_live_working_copy_for_source`（db.py 1375-1384）：`state IN ('checked_out','dirty','committing') ORDER BY created_at LIMIT 1`（同源多个活副本取最旧）。
2. 活行 + 文件在 + `not allow_replace` → **静默返回既有路径**（2297-2298，复用无错误消息——这是契约：重复 checkout 不得悄悄丢弃未提交编辑）。
3. 活行 + 文件在 + `allow_replace` → `_discard_working_copy_row_and_file`（2299，文件+行皆删）后新 checkout。
4. 活行 + 文件不在 → 死行，删行后新 checkout（2300-2306，save-as/打包丢 `working/`）。
5. 无行但盘上存在 `working/{version_id}/<payload.name>` 且 `live is None and not allow_replace` → 返回盘上文件（2318-2322，**对盘上证据 fail-closed**：登记簿忘了也不能清掉用户未提交工作，#1211 不得因簿记退化而 fail-open）。
6. 并发同版本 checkout 收敛：`_place_working_copy` PermissionError 重试 4 次（0.05/0.10/0.15s 退避后第 4 次抛，2327-2337）——Windows rename 瞬时碰撞，败者字节相同。

错误消息逐字（本组全部）：
- `f"Unknown version: {version_id}"`（`_version_or_raise` 1261）
- `f"Payload not available: {payload}"`（create_working_copy 2309，payload 为 resolve_path 绝对路径）
- `"工作副本正在提交中，不能丢弃；请等待提交完成或重启后恢复。"`（discard_working_copy 2448-2451，committing 态丢弃拒绝，CatalogError）
- `f"Source file not found: {source_path}"`（register_version 1761）
- `f"Unsafe asset id {asset.id!r}: only [A-Za-z0-9._-] allowed"`（`_build_version` 1689-1691，#1175）
- `f"Unsafe version id {version_id!r}: only [A-Za-z0-9._-] allowed"`（1708-1711）
- `f"Version {version_id} is already committed and immutable"`（ImmutableVersionError，1768-1770 与 1801-1803 两处）
- `f"Managed payload already exists: {target}"`（place_managed_file 446-447，FileExistsError）
- `f"Checksum mismatch for {source}: caller reported {known_sha256}, actual {hex_digest}"`（507-510）
- bundle 姊妹面（service_v11）：`f"Version {version_id} is not a bundle"`（469）、`f"Bundle payload not available: {payload_dir}"`（477）、`f"Working directory not found: {working_dir}"`（536）

discard 语义（2433-2463）：无行 → 文件在则 safe_unlink 返回 True，不在返回 False；有行非 committing → 删文件+删行返回 True。**唯一被批准的销毁未提交编辑途径**（除 commit 外）。

`working_copy_state`（2404-2419）：路径不在 project 目录下（relative_to ValueError）→ None；无行 → None。`list_working_copies`（2396-2402）：登记表读失败 → `[]`（吞错）。`_working_copy_status` 的 `dirty_hint`（2369-2381）：`exists 且 state ∈ (checked_out, dirty)` 且（mtime_ns ≠ checkout 快照 或 size ≠ source_size_bytes）——任一指纹漂移即 dirty 提示；`source_version_known` = 源版本仍在 maps（源被 purge 后 False，UI 提示孤儿副本）。bundle 行的 `source_size_bytes=None`（目录 stat 是元数据噪声，防 dirty_hint 误报，service_v11 513-516）。

### 1.4 僵尸防护 `_pending_commit_assets`（#1218）

`service.py:339` 初始化 `set[str]`；2618 add / 2630+2634 discard；唯一消费点 `purge_trashed` 3578-3586：`live_asset_ids = {v.asset_id for v in document.versions}` 后 `|= self._pending_commit_assets`（3581），使"有零版本资产"（I3 僵尸）判定放过**正在无锁 payload 窗口中的新建资产**。纯内存、进程内状态——持久层永远不会有零版本资产（同事务落库），窗口只存在于"内存文档 + 服务锁外"的组合。C++ 单写者模型下同样需要（R6 purge 与本切片 commit 共享同一可变集）。

### 1.5 staging lease 与 payload 放置的协作（#1222）

- lease 键：`_staging_target(stage, asset_id)`（1623-1639）= `<project>.artifacts/<STAGE_DIRS[stage]>/<asset_id>` 的 project 相对 POSIX 前缀——**必须用磁盘目录名（OUTPUT→"outputs"）而非 stage.value**（GC 从真实布局算相对路径，值形态键永不前缀匹配，注释引 R3#1）。blob 导入追加 `<name>.artifacts/blobs`（1641-1642）。
- 生命周期（`_payload_staging_lease` 1644-1668，contextmanager）：`acquire`（db.py 1227-1263，`INSERT OR REPLACE` 每 target 一行、BEGIN IMMEDIATE、schema 缺失/失败 → None）→ **yield 包住 `_build_version`（place 字节落盘）+ 锁内元数据提交 `_save`** → finally `release`（DELETE by lease_id，吞错）。即 lease 覆盖"盘上有字节、元数据未引用"的整个窗口。
- **best-effort 契约**：lease 是防护不是门——acquire 失败按 pre-lease 语义继续（注册不因此失败）；release/heartbeat 失败吞掉。
- TTL `STAGING_LEASE_TTL_SECONDS = 3600.0`（db.py 1225）；`active_staging_targets`（1289-1308）按 `heartbeat_at > now−TTL` 的 **ISO 字符串字典序**比较；`prune_stale_staging_leases`（1310-1331）清死 lease（显式 plan_gc 前调用，gc.py 174-177），防崩溃注册永久护住孤儿。`heartbeat`（1275-1287）为多小时计算准备——但 register_version **不**调 heartbeat（长拷贝超 1h TTL 是已知边界，parity 保留）。
- working 副本源文件一侧**不需要 lease**：`working/` 不在 stage/trash/blob 扫描类里，只有 `cleanup_working_copies` 显式钩子能动它（gc.py 195-207 分类 + 392-425 清理；判定 = 目录首段 version id 不在 `document.versions`）。
- GC 侧重验证：sweep 每删 64 个一批前在服务锁内重取 referenced+leased（gc.py 330-351），关 plan→sweep TOCTOU。

### 1.6 recover_working_copies 判定分支（2465-2523）

输入 = 全部行（list，任意 state，created_at 序）。逐行判定（**顺序即语义**：缺文件判定先于 committing 判定）：

| 分支 | 条件 | 动作 | 计数 |
|---|---|---|---|
| 缺文件 | `not path.is_file()` | 删行 | `missing_dropped` |
| committing + 已落地 | `state=='committing'` 且存在 committed 版本 `v.source_uri == path.resolve().as_posix()`（2482-2484 预建 `{source_uri: version}` 索引，仅含非空 source_uri） | 删行（commit 已成、只丢删行） | `committing_dropped` |
| committing + 未落地 | 同上但无命中版本 | `update_state('dirty')`（move 是 copy-then-unlink 原子序，文件未动即完好） | `reverted_to_dirty` |
| 其它（checked_out/dirty 且文件在） | — | 保留 | — |

收尾发 telemetry 事件 `working_copy.recovery`，detail=`{**healed, surviving: len(list_working_copies())}`（2515-2522），返回存活副本 statuses。注意：W3 窗口（unlink 后 crash）落入第一分支 `missing_dropped`——如实计为"文件已丢"。

`source_uri` 匹配锚点：`_build_version` 1697 记录 `source_path.resolve().as_posix()`，recover 2496 用 `path.resolve().as_posix()` 比对——**两侧都 resolve**，符号链接/大小写在 exotic 文件系统上可能错配（见 ⑥）。

---

## ② 冻结 C++ API 提案

### 2.1 归属决定：**新建 `working_copy.hpp`**（不并入 service_core）

理由：
1. **内聚性**：这是带独立崩溃恢复故事的完整状态机（独立表、独立终态语义、独立 telemetry 事件），与 service_core 的 open/batch/resolve_path 关注点正交；31 先例是"一个 Python 关注点一个头"（trash.hpp←storage 残余、gc.hpp←gc.py、telemetry.hpp）。
2. **R8 复用**：bundle 的 `create/commit_bundle_working_copy`（service_v11 463-586）走**同一** committing 迁移/回退/删行序列——独立头让 R8 组合迁移原语而非复制粘贴；并入 service_core 会迫使 R8 依赖整块服务层。
3. **分层正确**：trash.hpp 已持布局/复制原语（`working_dir_for`/`create_working_copy` 放置）；working_copy.hpp 是其上的服务层状态机，镜像 service.py 内"storage 放置 vs 生命周期"的拆分。service_core（31b 后续）作为编排者调用它。
4. **验收参照**：edit_session（不移植）与 UI 控制器消费的正是这一面——独立头 = 独立可测的最小验收单元。

### 2.2 签名（C++20、Qt-free、沿用 Result/DataError 与 context-struct 风格）

```cpp
// libs/catalog/include/pwb/catalog/working_copy.hpp
#pragma once
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/domain/errors.hpp"
#include <filesystem>, <optional>, <set>, <string>, <vector>

namespace pwb::catalog {
namespace fs = std::filesystem;

// db.py:512-516 状态机字面量。committed/abandoned 无行（终态=行删除）。
enum class WorkingCopyState { CheckedOut, Dirty, Committing };
inline constexpr std::string_view to_string(WorkingCopyState) noexcept;  // "checked_out"/"dirty"/"committing"
std::optional<WorkingCopyState> parse_working_copy_state(std::string_view);

// service.py _working_copy_status(2357-2394) 的完整形状（edit_session 验收参照）。
struct WorkingCopyStatus {
    std::string working_id, source_version_id, display_name, created_at, updated_at;
    fs::path path;                 // 绝对路径 = project_dir / row.path
    WorkingCopyState state;
    bool exists = false;
    bool dirty_hint = false;       // 1.3 指纹规则（保守误报安全）
    bool source_version_known = false;
};

// 单写者上下文（GcContext 先例）。pending_commit_assets 与 R6 purge 共享（#1218）。
struct WorkingCopyContext {
    fs::path project_path;         // .paleo.json 项目文件（gc.hpp 同约定）
    CatalogRepository* repo;       // 必非空：三个窄写 + lease 写侧
    CatalogDocument* document;     // 必非空：读侧（表已随文档加载 repository.cpp:435-451）
                                   //          + source_uri 恢复索引 + 资产/版本查找
    std::set<std::string>* pending_commit_assets = nullptr;  // #1218；可空=无 purge 并发
};

// service.py:2270 create_working_copy。复用/allow_replace/死行/盘上 fail-closed
// 分支逐条 parity（1.3）；PermissionError 4 次退避重试保留。
// 成功含 best-effort 登记（登记失败不失败 checkout，错误进日志/diagnostics）。
domain::Result<fs::path> create_working_copy(WorkingCopyContext& ctx,
                                             const domain::VersionId& source_version_id,
                                             bool allow_replace = false);

// service.py:2396。登记表读失败 → 空（吞错 parity）。
std::vector<WorkingCopyStatus> list_working_copies(WorkingCopyContext& ctx);

// service.py:2404。路径不在 project 目录下或无行 → nullopt。
std::optional<WorkingCopyStatus> working_copy_state(WorkingCopyContext& ctx,
                                                    const fs::path& working_path);

// service.py:2433。committing 拒绝：DataError 消息逐字节 =
// "工作副本正在提交中，不能丢弃；请等待提交完成或重启后恢复。"
// 返回：true=删了登记副本或无行文件；false=啥都没有。
domain::Result<bool> discard_working_copy(WorkingCopyContext& ctx,
                                          const fs::path& working_path);

// service.py:2465 + telemetry 2515-2522。判定分支顺序 = 1.6 表格。
struct WorkingCopyRecovery {
    int committing_dropped = 0, reverted_to_dirty = 0, missing_dropped = 0;
    std::vector<WorkingCopyStatus> surviving;
};
WorkingCopyRecovery recover_working_copies(WorkingCopyContext& ctx);

// ---- commit 编排（两段式, 1.2 步骤 1-5）--------------------------------
struct CommitWorkingCopyRequest {
    std::optional<domain::AssetId> asset_id;        // nullopt = 新资产（#1218 无锁窗口）
    std::string name;                               // 语义双轨：新资产=资产名; 既有资产=version metadata["name"]（空串不写键）
    domain::DataStage stage = domain::DataStage::Derived;
    std::optional<std::vector<domain::VersionId>> parent_version_ids;  // nullopt=按目录名推断(2548-2554)
    std::optional<domain::RunId> run_id;
    domain::Json metadata = domain::Json::object();
};
domain::Result<DataVersion> commit_working_copy(WorkingCopyContext& ctx,
                                                const fs::path& working_path,
                                                const CommitWorkingCopyRequest& req);

// ---- R8 复用的迁移原语（bundle 提交共用, 不复制状态机）-------------------
// 均 best-effort（吞错 parity）；返回是否成行。
bool mark_committing(WorkingCopyContext& ctx, const fs::path& working_path);   // 2560-2566
bool revert_to_dirty(WorkingCopyContext& ctx, const std::string& working_id);  // 2577-2586
bool drop_row(WorkingCopyContext& ctx, const std::string& working_id);         // 2589-2593

// ---- staging lease（db.py 1227-1331 写侧, gc.hpp 已有读侧）--------------
// RAII: acquire 失败 → 空 id（pre-lease 语义继续）；析构 release 吞错。
class StagingLeaseGuard {
public:
    StagingLeaseGuard(CatalogRepository& repo,
                      std::vector<std::string> targets,
                      std::string kind = "register");
    ~StagingLeaseGuard();                       // release(lease_id)
    StagingLeaseGuard(StagingLeaseGuard&&) noexcept;
    const std::string& id() const noexcept;     // 空 = 未取得
private: /* pimpl 或直接成员 */ };
std::string staging_target(const fs::path& project_path,
                           std::optional<domain::DataStage> stage,
                           std::optional<std::string_view> asset_id);  // _staging_target 1623-1639
std::string blob_staging_target(const fs::path& project_path);        // 1641-1642
}  // namespace pwb::catalog
```

repository.hpp 需补的窄写（本切片交付或与 R1 协商，见 ③）：
```cpp
// lease 写侧（gc.hpp 的 active_staging_targets 是文档读, 见 ⑥ 风险 R-leak）
std::optional<std::string> acquire_staging_lease(const std::vector<std::string>& targets,
                                                 const std::string& kind = "register");
void release_staging_lease(const std::string& lease_id);      // 吞错
void heartbeat_staging_lease(const std::string& lease_id);    // 吞错
int prune_stale_staging_leases(const std::string& cutoff_iso);

// set_working_copy_state 现漏 updated_at 刷新（repository.cpp:932-943 vs db.py:1402-1414）
// ——冻结要求补齐（见 ⑤）。

// 新资产+版本(+run 链接) 单事务变体（Python _save 同事务含 asset 行, 1821）：
domain::DataError commit_working_copy_transaction(
    const std::optional<DataAsset>& new_asset, const DataVersion& version,
    const std::optional<domain::RunId>& run_id);   // 现有 commit_version_transaction 的带资产变体
```

行为冻结要点（实现者必须遵守）：
- 登记表写全部 best-effort：错误进 diagnostics/日志，**绝不**让 checkout/commit 失败（parity 2351-2352）。
- 迁移原语同时更新 `document->working_copies`（单写者内存真源）与 sqlite 行，二者保持一致序：先库后内存（或同函数内）。
- 时间戳：本地时区 `%Y-%m-%dT%H:%M:%S`（telemetry.hpp 先例）；`working_id = "wc-" + 12 hex`（随机源与 data_suite 现有 id 生成一致）。
- commit 的 metadata flush 通道：R1 `apply_changes` 落地前用 `commit_working_copy_transaction`；落地后切换，语义不变（同事务 asset+version+current+run_outputs+revision）。

---

## ③ 依赖与接口点

| 对端 | 接口 | 说明 |
|---|---|---|
| **R2 CRUD** | `CatalogDocument.working_copies`（models.hpp:131，repository.cpp:435-451 已加载） | 读侧（by_path/live_for_source/list）在 working_copy.hpp 内对文档做小过滤即可，无需 repository 读 API。get_live 过滤谓词冻结：`state IN (checked_out,dirty,committing) ORDER BY created_at LIMIT 1`。 |
| **R1 apply_changes** | commit 的 `_save(DirtySet{asset,version,run})` 通道 | Python 落库是 asset+version+current+run_outputs 同事务（1821-1825）；C++ 过渡用 `commit_working_copy_transaction`，R1 落地后切 apply_changes。**不得**拆两事务（会持久化零版本资产）。 |
| **R1/R6 共享** | `pending_commit_assets`（context 指针） | R6 purge_trashed 的僵尸判定必须 union 该集（3578-3586 parity）。建议 context 由 31b service_core 持有并传两端。 |
| **R6 trash 机** | `trash.hpp create_working_copy/working_dir_for/safe_unlink` | 布局/复制已交付；discard 需要 safe_unlink（Windows 只读位）——trash.cpp 内部有等价实现但**未导出**，需导出或 working_copy.cpp 内复用。`is_cas_path`（trash.hpp:36）供 `_rollback` blob 豁免。 |
| **R6 gc** | `gc.hpp cleanup_working_copies/active_staging_targets` | cleanup 钩子与登记表**无耦合**（只按 version id 存在性删文件；行随后由 recover missing_dropped 清）；lease 读侧见 ⑥ R-leak。 |
| **R8 bundle** | `mark_committing/revert_to_dirty/drop_row` + `WorkingCopyStatus` | `create/commit_bundle_working_copy`（service_v11 463-586）复用同一状态机；bundle 差异（目录复制、`source_size_bytes=None`、parent 从 wc 行推断）留在 R8 层。 |
| **telemetry** | `telemetry.hpp record_catalog_event` | `working_copy.recovery` 事件（detail 三计数 + surviving 数）。 |
| **edit_session（不移植, 验收参照）** | 其消费面形状 | 期望 API：`create_working_copy(version_id, allow_replace=False)->Path`、`working_copy_state(path)->{working_id,source_version_id,path,state,dirty_hint,...}|None`、`discard_working_copy(path)->bool`、`commit_working_copy(path, asset_id=, name=, stage=, parent_version_ids=, run_id=, metadata=)->DataVersion`、`create/commit_bundle_working_copy`（members 版本自动分流）。C++ 的 Status 结构即此 dict 形状的直接映射。 |
| **UI/harness 消费者** | `ui/data_lifecycle_controller.py`、`ui/project_controller.py`、`harness/actions/data_lineage.py` | 确认非死代码；C++ 侧由 data_suite/后续 UI 切片消费，不影响本库 API。 |

---

## ④ oracle 冻结场景建议

1. **crash 恢复矩阵**（核心，建议 8 case 全冻结进 `tests/cpp/data/fixtures/catalog_domain/` 或行为测试）：
   - (committing, 版本存在且 source_uri 命中) → 行删、文件状态不变、计数 committing_dropped=1；
   - (committing, 无版本) → 回 dirty、文件未动、reverted_to_dirty=1；
   - (checked_out, 文件在) → 原样保留；
   - (dirty, 文件在) → 原样保留（不误升级/不误删）；
   - (任意态, 文件缺) → 删行、missing_dropped=1；
   - 多行混合 → 计数分桶正确 + surviving 只含活副本；
   - telemetry 事件落盘且 detail 数值正确；
   - **判定顺序**：committing+文件缺 → 走 missing_dropped（不是 committing 分支）。
2. **僵尸防护**：文档含"零版本资产 A（不在 pending）"与"零版本资产 B（在 pending）" → purge 只清 A；commit 失败/成功后 pending 集为空。
3. **复用/replace 拒绝**：
   - 活行+文件+无 allow_replace → 返回原路径且文件 mtime 不变（未重写）；
   - allow_replace=True → 文件被换新、行重建；
   - 活行+文件缺 → 死行删除后新 checkout；
   - 无行+盘上文件 → fail-closed 复用（不 clobber）；
   - 源版本 payload 缺失 → `"Payload not available: <abs path>"` 逐字节。
4. **discard 守卫**：committing 态 → CatalogError 中文消息逐字节（含全角标点）；无行+文件 → True；无行+无文件 → False。
5. **dirty_hint 矩阵**：mtime 漂移 / size 漂移 / state=committing 时不算 / 文件缺时不算 / bundle 行（size=nullopt）只看 mtime。
6. **commit 两段式**：成功后 working 文件消失、版本链 parent=目录名、新资产名=name；既有资产时 `metadata["name"]` 写入且空名不写键；`_save` 失败注入 → 版本不存在、current 未变、payload 回到 working 路径、行回 dirty（**无 phantom 断言**）；place 失败 → 文件从未离开。
7. **lease 协作**：lease 持有期间 active_staging_targets 含 stage 目标前缀；release 后不含；staging_target 用磁盘目录名（"outputs" 非 "output"）。
8. **W3 窗口**（诚实偏离）：模拟 unlink 后 crash → recover 报 missing_dropped（不虚构恢复）。

---

## ⑤ 有界偏离清单（如实）

1. **登记表吞错 vs Result 风格**：Python 处处吞错；C++ 用 diagnostics/日志记录但同样不让 checkout/commit 失败——行为等价、可观测性更强。
2. `set_working_copy_state` 现不刷新 `updated_at`（repository.cpp:932-943）——与 db.py:1402-1414 不一致，**实现时补齐**（签名加 updated_at 参数或内部取 now）。
3. `insert_working_copy` 用 `INSERT OR REPLACE`（repository.cpp:893）vs Python 裸 INSERT + 服务层吞 IntegrityError：path UNIQUE 冲突时 C++ 静默换行、Python 静默不写。服务层复用分支已阻止重复登记，残余差异可接受；oracle 不放 dup-path 用例。
4. `working_id`/时间戳生成源：uuid4 → 进程 RNG 十二 hex；时间 → telemetry.hpp 本地时区格式。id 不透明，无行为断言。
5. PermissionError 退避重试保留（Linux 上近乎不可触发，Windows 契约）。
6. W3 崩溃窗（copy-then-unlink 与元数据提交之间）按 parity 保留，不引入"先落元数据后删源"的反转（会改变可观测行为与 GC 分类）。
7. register_version 不 heartbeat 长拷贝（>1h TTL 失效）——parity 保留。
8. 懒开/方法包装/单槽缓存（Python UI 性能形态）不适用于单写者 C++，不移植（31-gap §2 同结论）。
9. `_working_copy_status` 的 `maps.version_by_id` 存在性检查 → `document->find_version`（等价）。

---

## ⑥ 风险 / 先例坑

- **R-leak（新发现，须转 R-me gc / 31b 编排）**：`gc.hpp active_staging_targets(document, cutoff)` 读的是**文档快照**（gc.cpp:178-183），而 Python 版直查 sqlite（db.py:1289-1308）。单写者单线程内无并发问题，但 lease 的存在意义是跨**进程/线程**防护（另一进程的显式 sweep 或 C++ 服务多线程化后）：文档快照看不见"刚 acquire 的 lease"→ in-flight 字节被当孤儿删掉，#1222 被静默击穿。建议：sweep 前从 repository 活读 lease 表（新增 `active_staging_targets_live()`），或规定 lease 写侧同步维护 document.staging_leases。
- **source_uri 匹配脆弱性**：recover 与 `_build_version` 都 `resolve().as_posix()`，但登记行 path 是 checkout 时快照——项目目录被 symlink 挂载/重开后 resolve 结果漂移 → committing_dropped 误判成 reverted_to_dirty（或反之）。parity 保留，oracle 用例用真实路径避免碰它。
- **`_pending_commit_assets` 是进程内内存**：crash 即蒸发（无危害——持久层无零版本资产）；但 C++ 若 31b service_core 引入线程池，commit 无锁窗口与 purge 的并发必须靠同一把服务锁或该集合加互斥——Python 用 `self._lock`（2615/2627/2633 三段锁内操作）。冻结：pending 集的 add/discard/union 必须与 purge 僵尸判定互斥。
- **先例坑（D3）**：`DataError()` 默认 code=Unknown——成功路径显式 `DataError(ErrorCode::Ok, "")`；本切片 Result 返回值多，逐处核对。
- **先例坑（31b D4/31 D6）**：`resolve_path` 完整阶梯在 31b 服务层——本切片 `create_working_copy` 依赖它（2307）；在 service_core 落地前 C++ 侧先实现 managed-only 精确匹配（`project_dir / version.path`，1516-1517），external 版本 checkout 报 `"Payload not available"`（external 版本本就极少 checkout，如实记偏离）。
- **trash.hpp 的 `create_working_copy` 只做放置**（无登记/复用/重试）——本提案在其上叠服务层，不要把状态机塞回 trash.hpp（那会破坏 storage.py↔service.py 的分层镜像）。
- **错误消息语言**：本组唯一中文用户面消息是 discard 的 committing 拒绝——逐字节冻结（含全角逗号/分号/句号）；其余英文消息同样逐字节。oracle 断言用字符串常量, 不要复制粘贴时被编辑器改全半角。
- **`datetime.now()` 本地时间**：created_at/updated_at/lease 时间戳全是本地无时区 ISO 秒——跨时区移动项目目录会乱序（created_at 排序的"最旧活副本"选择可能变）；parity 保留。
