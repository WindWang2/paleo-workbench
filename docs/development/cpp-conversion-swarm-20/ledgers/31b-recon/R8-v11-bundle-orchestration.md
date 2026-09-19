# R8 recon — V11 bundle 编排面语义契约 + C++ API 冻结提案

切片：CONV-31b（`service_v11.py` bundle 放置编排剩余，31-decisions D6）。
基线：worktree `feat/cpp-catalog-service`；行号锚点以该 worktree 为准。
范围：`register_bundle_version` 全编排、`place_managed_tree`、`create/commit_bundle_working_copy`、
`verify_bundle_integrity`/`member_path`/`_validate_member_rel_path`、读侧 4 函数 + `migrate_run_ports` 核实。
**只做侦察与契约冻结，不改源码。** C++20、Qt-free。

---

## ① 语义契约（逐函数逐分支）

### 1. `storage.place_managed_tree`（storage.py 542-615）— V11 bundle 全成员放置原语

前置常量/助手：`STAGE_DIRS`（30-35，OUTPUT→`"outputs"`）、`is_safe_entity_id`（44-60）、
`_require_safe_entity_id`（63-67）、`ensure_catalog_layout`（70-82，**副作用**：创建全部
`raw/derived/intermediate/outputs/working/metadata/trash` 七目录）、`_project_dir`（200-202 =
`project_path.expanduser().resolve().parent`）、`safe_unlink`（296）、`fsync_dir`（345，win32/无
O_DIRECTORY 直接返回，全程 best-effort）、`_make_readonly`（362，best-effort）。

分支顺序（**冻结**，顺序即契约）：

| # | 条件 | 行为 | 错误（逐字） | 类型 |
|---|------|------|--------------|------|
| T1 | `asset_id`/`version_id` 非安全 id | 拒绝，**不建任何目录** | `Unsafe asset id {id!r}: only [A-Za-z0-9._-] allowed`（version 同构，storage.py 65-67） | CatalogError |
| T2 | 通过 | `ensure_catalog_layout`（建七目录） | — | — |
| T3 | `target_dir={root}/{stage_dir}/{asset}/{version}` 存在**且非空** | 拒绝 | `Managed payload already exists: {target_dir}` | **FileExistsError**（非 CatalogError） |
| T3b | target 存在但为**空**目录 | 允许（`mkdir(exist_ok=True)`） | — | — |
| T4 | `source_dir` 不是目录（**在 target mkdir 之后**检查） | 拒绝；此时 target 空目录**不清理**（裸调路径；经 service 不可达，service 238 先查） | `Bundle source directory not found: {source_dir}` | CatalogError |
| T5 | 逐成员（`sorted(rglob("*")` 中 `p.is_file()`，**Path 元组排序**非字符串排序）：mkstemp `.place-` 于 `member_target.parent` → 流式拷贝+SHA256+size → flush+fsync → `os.replace` → `fsync_dir(parent)`；异常 → `safe_unlink(tmp)` 重抛；成功 → `_make_readonly`（在 rename **之后**） | 收集 `(project_dir 相对 POSIX 路径, hex digest, size)` | 透抛 IO 异常 | — |
| T6 | 循环中任何异常 | `shutil.rmtree(target_dir, ignore_errors=True)` 后重抛 —— **全成员或无** | — | — |
| T7 | `placed` 为空（只有子目录无常规文件） | rmtree target + 拒绝 | `Bundle source directory is empty: {source_dir}` | CatalogError |
| T8 | `keep_source=False` | `shutil.rmtree(source_dir, ignore_errors=True)` | — | — |

返回：`placed` 三元组列表，按 T5 遍历序（Path 元组排序）。
**不做** blob 登记/dedup（与 `place_managed_file` 的关键差异：bundle 成员永不进 CAS）。
文件级先例 `place_managed_file` 已在 dedup.hpp（CONV-15，错误串字节一致 D9）。

### 2. `service_v11.register_bundle_version`（service_v11.py 216-402）— 全编排

**Phase A 纯校验（无锁、无 IO 写，216-293）**：

| # | 条件 | 错误（逐字） | 行 |
|---|------|--------------|----|
| A1 | `source_dir` 非目录 | `Bundle source directory not found: {source_dir}`（`str(Path)` 原样，未 resolve） | 238-239 |
| A2 | 每个 spec：`rel=Path(spec.rel_path).as_posix()` → `_validate_member_rel_path(rel)` | 见 §4 V1 | 243 |
| A3 | spec rel 重复 | `Duplicate member rel_path: {rel}` | 245 |
| A4 | `source_files`（rglob is_file 的 posix rel 集）为空 | `Bundle source directory is empty: {source_dir}` | 254-255 |
| A5 | `unexpected=sorted(spec集 − source集)` 非空 | `Member specs reference missing files: ['a.txt', 'sub/b.txt']`（Python list repr，已排序） | 256-258 |
| A6 | `len(source_files) > 64` | `Bundle exceeds member budget ({n} > 64); split the directory or import as separate assets` | 259-264 |
| A7 | 统一命名池（**单一池**，P1-4）：按 `sorted(source_files)` **字符串序**逐个分配——spec 名先注册（重复 → `Duplicate member name {name!r} in specs`，276-278）；无 spec 则候选 `(Path(rel).name, rel)` 取首个未用；双占用 → `{base}~{n}`（n 从 2 递增） | — | 270-293 |

**A7 关键语义**：spec 名查重与 auto 名分配**交错**进行（按 sorted rel 序），不是先查完所有 spec 再分配。
`plan_bundle_members`（v11_policy.cpp 224-303）已逐字实现 A3-A7 ✓（含 `<dir>` 占位的 A4 消息——
编排层须回填真实路径）。

**Phase B 锁内预检（294-297）**：`_asset_or_raise`（Unknown asset: {id}，service.py 1246）、
`run_id` 给定时 `get_run`（Unknown run: {id}）——**任何字节落盘前**拒绝。锁随后释放。

**Phase C staging lease（304）**：`_payload_staging_lease(_staging_target(stage, asset_id))`
（service.py 1645-1676）。租约键 = `<projname>.artifacts/<stage_dir名>/<asset_id>`（ON-DISK 名，
OUTPUT→`outputs`，service.py 1623-1641）。**best-effort**：租约库异常 → 无租约继续（#1222 GC 桥）。

**Phase D 放置+组装（305-359）**（锁外、lease 内）：
- 构造 `DataVersion`：`version_number=0`（commit 时赋）、`managed=True`、
  `source_uri=source_dir.resolve().as_posix()`（resolve 后绝对 posix）、
  `format=asset.metadata.get("format","")`（**来自 asset 元数据**）、`parent_version_ids` 拷贝、
  `metadata=dict(metadata or {})`。
- `place_managed_tree(source_dir, project_path, stage, asset.id, version.id, keep_source=True)`——
  **恒为 copy**；`move=True` 的 delete 半段在 Phase E 成功后才执行（P1-2 copy-then-delete）。
- `version_dir_rel` 从 `ensure_catalog_layout(project_path)/STAGE_DIRS[stage]/asset.id/version.id`
  相对 `_project_dir` 推导——**永不来自排序文件列表**（P1-1：字母序首个成员可能在子目录）。
- 成员组装（337-350）：`member_rel = file_rel[len(prefix):]`（纯字符串切片）；
  `name = spec.name | auto_names[rel] | Path(rel).name`；`member_role/ordinal/required` 有 spec 用
  spec（ordinal 可重复），无 spec 用枚举序号/`""`/`True`；`sha256=digest`、`size_bytes=size`。
- 兜底断言（351-355）：成员名重复 → `Bundle member names are not unique (internal error)`
  ——注意：此处 raise **不带** `_rollback_bundle`（不可达路径，理论孤儿，见 ⑥-7）。
- `version.path=version_dir_rel`；`size_bytes=Σ m.size_bytes or 0`；
  `sha256=aggregate_member_sha256(members)`（models.py 62-79：sha256("rel_path:sha256\n"…)，按
  `(ordinal,name)` 排序，任一成员无 digest → None）。

**Phase E 锁内提交（360-402）+ 回滚阶梯（冻结）**：

| 阶 | 失败点 | 补偿 |
|----|--------|------|
| E1 | `_asset_or_raise` 再查失败（资产被并发删） | `_rollback_bundle`（rmtree version 目录，ignore_errors，404-406）+ 重抛 |
| E2 | `version.id` 已在 `document.versions` | `_rollback_bundle` + `Version {version.id} is already committed and immutable`（ImmutableVersionError，366-370） |
| E3 | `get_run(run_id)` 再查失败 | `_rollback_bundle` + 重抛 |
| E4 | `_save(dirty)` 异常（dirty=assets{asset}+versions{version}+run 若有 `mark_runs`） | 撤销 `run.output_version_ids.append` → `_remove_version` → 恢复 `asset.current_version_id` → `_rollback_bundle` → 重抛 |
| E5 | 成功后 `move=True` | `shutil.rmtree(source_dir, ignore_errors=True)`（398-401，仅元数据已提交才消费源） |

成功路径顺序：`version.version_number = _next_version_number(asset.id)`（max+1，service.py 1616；
C++ `CatalogDocument::next_version_number` 已有）→ `_add_version` → `asset.current_version_id=version.id`
→ run output 回填（若缺）→ `_save`。

### 3. `verify_bundle_integrity`（425-461）/ `member_path`（417-423）

**verify**：
- 版本不存在 → `Unknown version: {id}`（`_version_or_raise`）。
- `not version.members` → `{"bundle": False, "status": "unknown"}`。
- 否则 `{"bundle": True, "members": [...], "status": worst}`；每成员条目
  `{name, rel_path, status}`，仅 `modified` 追加 `actual_sha256`。
  成员状态：文件缺失→`missing`；存在且 `member.sha256 is None`→`unknown`；
  digest 不等→`modified`；相等→`verified`。rank：verified<unknown<modified<missing。
- 尾部聚合校验：`worst=="verified"` 且重算 aggregate 非 None 且
  `version.sha256 not in (None, recomputed)` → `status="modified"`。
- 每成员路径经 `member_path`（含 rel 校验）。哈希用 `sha256_file`（checksum.hpp 已有 C++）。

**member_path**：`_version_or_raise` → rel（VersionMember.rel_path 或入参 str）→
`_validate_member_rel_path` → `base = resolve_path(version)`（managed = `project_dir/version.path`
直拼；external 走 service.py 1502-1560 阶梯，31b service_core 范围）→ `base / rel`。

### 4. `_validate_member_rel_path`（408-415）— 拒绝分支逐字

`candidate = Path(rel_path)`；拒绝当且仅当：
- `candidate.is_absolute()`，**或**
- `".." in candidate.parts`（任一分量为 `..`），**或**
- `not rel_path`（空串）。

消息（隐式拼接后单空格）：`Unsafe member rel_path {rel_path!r}: must stay inside the version payload directory`
（`!r` = Python 单引号 repr）。注意：POSIX 下 `\` 不是分隔符、`C:\x` 不是绝对路径——逐字保真。

### 5. `create_bundle_working_copy`（463-520）— R5 共用底座之上的目录版

| # | 分支 | 行为/错误 |
|---|------|-----------|
| C1 | 版本不存在 | `Unknown version: {id}` |
| C2 | `not version.members` | `Version {version_id} is not a bundle`（469） |
| C3 | live 查询 `_index.get_live_working_copy_for_source`（state ∈ checked_out/dirty/committing，按 created_at 取首，db.py 1375-1386） | **异常吞掉** → None |
| C4 | `payload_dir=resolve_path(version)` 非目录 | `Bundle payload not available: {payload_dir}`（477） |
| C5 | live 存在且 `project_dir/live["path"]` 是目录：`!allow_replace` → **复用返回**；否则 rmtree + `remove_working_copy`（吞错）；是文件/不存在 → 仅删行（吞错） | 复用不破坏 |
| C6 | `target = working_dir_for(project)/version.id`；存在且**非空**且 `!allow_replace` → 返回（**未注册也复用**）；存在 → rmtree | 494-498 |
| C7 | `mkdir(parents=True)`；**逐成员** `shutil.copyfile(member_path → target/rel)`（先 `dst.parent.mkdir`）；非成员文件**不拷** | 499-505 |
| C8 | `register_working_copy(source_version_id, rel, display_name=target.name, payload_mtime_ns=None, source_size_bytes=None)`（目录 stat size 是噪音，防止脏提示误报）——**吞错**（登记非 checkout 门槛） | 506-519 |

### 6. `commit_bundle_working_copy`（522-586）

| # | 分支 | 行为/错误 |
|---|------|-----------|
| M1 | `working_dir` 非目录 | `Working directory not found: {working_dir}`（536） |
| M2 | `wc_row=working_copy_state(working_dir)`（service.py 2404：project 相对 rel → `get_working_copy_by_path`；项目外/未注册 → None） | — |
| M3 | `parent_version_ids is None` → `[wc_row["source_version_id"]]`（有行）否则 `[]` | 538-540 |
| M4 | 有 `working_id` → `update_working_copy_state(id,"committing")`（吞错） | 541-546 |
| M5 | `asset_id is None`：`name or working_dir.name` → 锁内 `_new_asset+_add_asset+_pending_commit_assets.add`（GC 保护窗口）→ `register_bundle_version(..., move=True)`；异常 → `_remove_asset`（若仍在）重抛；finally discard | 548-567 |
| M6 | 否则直接 `register_bundle_version(asset_id, ..., move=True)` | 568-573 |
| M7 | 任何异常 → `update_working_copy_state(id,"dirty")`（吞错）+ 重抛 | 574-580 |
| M8 | 成功 → `remove_working_copy(working_id)`（吞错）；返回新版本 | 581-586 |

### 7. 读侧 4 函数 + `migrate_run_ports` 核实（对照 v11_policy.hpp/cpp）

| Python | 行 | C++ 现状 | 结论 |
|--------|----|----------|------|
| `inputs_by_role` | 167-174 | `inputs_by_role(run, role)` ✓（合成视图过滤） | **已覆盖**；缺 get_run→Unknown run 胶水（service_core） |
| `runs_consuming` | 176-197 | `runs_consuming(document, index, role, version_id)` ✓（含 legacy untyped run 计入分支 187-189） | **已覆盖**；iteration order = document.runs 序 = Python map 插入序 ✓ |
| `ports_for_run` | 199-210 | `ports_for_run(run)` ✓（匿名合成：role="input"/"output"、required=True、ordinal=0） | **已覆盖** |
| `migrate_run_ports` | 745-782 | `migrate_run_ports(document*, index)` ✓ + `operation_output_roles()` 表 ✓（732-743 十项逐字）；幂等（已有 output_ports 跳过）、known_outputs 过滤未知 id、inputs 保持匿名 | **决策面已覆盖**；缺持久化半段（DirtySet.mark_runs+_save，service_core/R1） |

读侧结论：**决策表全部已在 v11_policy**，31b 只欠编排胶水（锁/save/raise 消息）。

---

## ② 冻结 C++ API 提案

### 归属裁定
- **`place_managed_tree` → dedup.hpp/cpp 扩展**（放置原语家族：blob/place_managed_file/tree 同 TU；
  复用 `reserve_temp`/`fsync_dir`/readonly 助手与 stage 映射）。trash.hpp 不承载放置语义。
- **新 `v11_bundle.hpp/cpp`**：bundle 编排（注册回滚阶梯、成员组装、verify、rel-path 守卫、
  bundle working-copy create/commit 胶水）。v11_policy.hpp **不再扩**（决策面已完备，保持纯决策）。
- **service_core（31b）**：锁纪律、`_save`/DirtySet 真通道、resolve_path 阶梯、`_asset_or_raise`/
  `_version_or_raise`/`get_run`、`_new_asset`/`_pending_commit_assets`、staging lease 存储、
  working-copy 注册表实现（R5）。v11_bundle 通过窄缝（seam）回调这些，不复制。

### dedup.hpp 追加

```cpp
struct PlacedTreeMember {
    std::string rel_path;      // project-dir 相对 POSIX，含
                               // "{artifacts}/{stage}/{asset}/{version}/" 前缀
    std::int64_t size_bytes = 0;
    std::string sha256;
};

// storage.py place_managed_tree (542-615)。逐成员原子（mkstemp ".place-" +
// 流式写/hash + fsync + rename + dir fsync + chmod readonly），任一失败
// 整树 rmtree 回滚。成员序 = Python Path 元组排序（见 ⑤-1）。
// keep_source=false 在全部成员落盘后才 rmtree 源目录。
// 错误码：UnsafeId（T1）/ ImmutableVersion（T3，消息字节一致，dedup.cpp
// 389 先例）/ InvalidArgument（T7 空源）/ IoError（T5 透传）。
domain::Result<std::vector<PlacedTreeMember>> place_managed_tree(
    const fs::path& source_dir, const fs::path& project_path,
    domain::DataStage stage, const std::string& asset_id,
    const std::string& version_id, bool keep_source = true);
```

（T4 源缺失经编排层 A1 先行拦截；裸调映射提议 `NotFound` + 同消息——冻结点。）

### v11_bundle.hpp（新 TU，草案冻结）

```cpp
namespace pwb::catalog {

// ---- rel-path 守卫（§4 逐字） -----------------------------------------------
domain::DataError validate_member_rel_path(const std::string& rel_path);
// PathEscape / "Unsafe member rel_path '<rel>': must stay inside the version payload directory"

// member_path 纯核：payload_base（resolve_path 结果，service_core 注入）+ rel。
domain::Result<fs::path> bundle_member_path(const fs::path& payload_base,
                                            const std::string& rel_path);

// ---- 注册编排：两阶段可组合 + 一步式包装 --------------------------------------
struct BundleRegistrationPlan {          // Phase A+B 产物（纯+IO 读）
    std::map<std::string, VersionMember> spec_by_rel;   // posix 规范化后
    std::vector<std::string> source_files;              // posix rel，字符串排序
    BundleMemberPlan names;              // v11_policy::plan_bundle_members
};
domain::Result<BundleRegistrationPlan> plan_bundle_registration(
    const fs::path& source_dir,
    const std::vector<VersionMember>& member_specs);    // A1-A7 全部错误在此

struct BundleSeams {                     // service_core/R1/R5 注入点
    // #1222 staging lease（best-effort：acquire 失败返回 nullopt 照常继续）
    std::function<std::optional<std::string>(const std::string& target)> acquire_lease;
    std::function<void(const std::string& lease_id)> release_lease;
    // Phase E 单事务持久化（R1 DirtySet 通道：asset+version(+run) 一修订）。
    std::function<domain::DataError(/*DirtySet 由 service_core 具型化*/)> save;
};

// Phase D+E：放置 + 组装 + 提交 + 回滚阶梯（§1 Phase E 表逐行）。
// 版本 id 由调用方预生成（service_core id 工厂）注入 *version（version_number
// 由 next_version_number 在锁内赋值）。document 变更在调用方单写者纪律下进行。
domain::Result<DataVersion> commit_bundle_registration(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    domain::DataStage stage, const BundleRegistrationPlan& plan,
    const fs::path& source_dir, DataVersion version /*半成品*/,
    std::optional<domain::RunId> run_id, bool move, const BundleSeams& seams);

// 一步式（service_core 在外层加锁/释放/再加锁时使用上面两段更精确）。
domain::Result<DataVersion> register_bundle_version(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    const fs::path& source_dir, domain::DataStage stage,
    const std::vector<VersionMember>& member_specs,
    const std::vector<domain::VersionId>& parent_version_ids,
    std::optional<domain::RunId> run_id, domain::Json metadata,
    bool move, const BundleSeams& seams);

// ---- verify（§3 决策+IO 混合；payload_base 由 resolve_path 注入） -------------
struct BundleMemberReport {
    std::string name, rel_path, status;          // verified|unknown|modified|missing
    std::optional<std::string> actual_sha256;    // 仅 modified
};
struct BundleIntegrityReport {
    bool bundle = false;
    std::string status = "unknown";
    std::vector<BundleMemberReport> members;
};
BundleIntegrityReport verify_bundle_integrity(const DataVersion& version,
                                              const fs::path& payload_base);

// ---- bundle working-copy（R5 注册表缝） ---------------------------------------
struct WorkingCopyRegistrySeam {        // R5 拥有实现；全部操作吞错 = Python try/except
    virtual std::optional<WorkingCopy> live_for_source(const domain::VersionId&) const = 0;
    virtual std::optional<WorkingCopy> by_rel_path(const std::string&) const = 0;  // M2
    virtual void register_checked_out(const domain::VersionId&, const std::string& rel,
                                      const std::string& display_name) = 0;        // C8（mtime/size 恒 null）
    virtual void set_state(const std::string& working_id, const std::string& state) = 0; // committing/dirty
    virtual void remove(const std::string& working_id) = 0;
};

domain::Result<fs::path> create_bundle_working_copy(
    const DataVersion& version, const fs::path& payload_base,
    const fs::path& project_path, bool allow_replace,
    WorkingCopyRegistrySeam& registry);            // C1-C8

domain::Result<DataVersion> commit_bundle_working_copy(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const fs::path& working_dir,
    std::optional<domain::AssetId> asset_id,       // nullopt → new_asset 缝（M5）
    std::optional<std::string> name, domain::DataStage stage,
    const std::vector<domain::VersionId>* parent_version_ids,  // null → M3 默认
    std::optional<domain::RunId> run_id, domain::Json metadata,
    WorkingCopyRegistrySeam& registry, const BundleSeams& seams,
    const std::function<domain::AssetId(const std::string&, domain::Json)>& new_asset);

}  // namespace pwb::catalog
```

错误码映射（冻结提案）：Unknown asset/version/run → `NotFound` + 逐字消息；
`_validate_member_rel_path` → `PathEscape`；safe-id 门 → `UnsafeId`；
已提交版本 → `ImmutableVersion`；`FileExistsError("Managed payload already exists")` →
`ImmutableVersion`（dedup.cpp 389 先例）；A1-A6 校验类 → `InvalidArgument`。
成功哨兵遵循 31-decisions D3（显式 `ErrorCode::Ok`）。

---

## ③ 依赖与接口点

| 依赖 | 拥有者 | 接口点 |
|------|--------|--------|
| DirtySet + `_save` 单事务 | **R1**（db.apply_changes） | E4 dirty = assets{asset}+versions{version}+runs{run?}；repository 需一事务写 asset 行+version 行（含 version_members）+run 行（含 run_ports）——对照 `commit_version_transaction`（repository.hpp 70）确认是否复用或新增 bundle 变体 |
| 单版本 working-copy 状态机 | **R5** | 共用底座冻结：状态词表 `checked_out/committing/dirty`（live 集，db.py 1380）；`WorkingCopy` 行（models.hpp 95-105 已有）；"复用优先、allow_replace 才清"（单文件 495-498 同构）；注册表操作全吞错；`register` 恒 `payload_mtime_ns/source_size_bytes` 可空；`recover_working_copies`（service.py 2457+）负责 M4→崩溃窗愈合（source_uri 匹配判定 commit 是否落盘）——bundle 与单文件共用 |
| trash / 布局 | **R6（trash.hpp 已交付）** | `stage_dir_name`/`working_dir_for`/`is_safe_entity_id`/`is_cas_path`；place_managed_tree 的目录创建应与 trash.cpp `artifacts_root` 对齐（注意 ⑥-8：Python 建七目录，trash.cpp 只建 root） |
| storage dedup | 已交付（dedup.hpp） | `place_managed_file` 先例（错误映射/原子模式/诚实 checksum）；bundle **不走** CAS |
| checksum | 已交付 | `sha256_file`（verify 用；分块 1 MiB parity） |
| staging lease | service_core（31b） | 键格式 `<projname>.artifacts/<stage_dir名>/<asset_id>`；GC（gc.cpp）orphan 扫描必须同键前缀跳过（R3#1 先例："outputs" 非 "output"） |
| models | 已交付 | `VersionMember/RunPort/aggregate_member_sha256`（models.hpp 19-38/145）；`CatalogDocument::next_version_number`（140） |
| Python 侧 service 基建 | service_core（31b） | `_asset_or_raise/_version_or_raise/get_run` 消息、`resolve_path`（1502）、`_new_asset`（2039）、`working_copy_state`（2404）、`_pending_commit_assets`（339，GC 保护 3581） |

---

## ④ oracle 冻结场景建议（tests/ 现有 + 补充）

现有用例直接作 oracle 素材：
1. `test_v11_core.py::test_register_bundle_version_roundtrip`（146）——4 成员含 `sub/`、spec 角色/
   required 透传、aggregate、size 求和、member_path、verify verified→篡改后 modified（含 chmod 后写）。
2. `test_v11_core.py::test_bundle_rejects_escaping_member_spec`（193）——spec `../outside.shp`。
3. `test_v11_core.py::test_bundle_rejects_spec_for_missing_file`（209）——ghost spec + 断言零放置。
4. `test_v11_core.py::test_bundle_working_copy_commit_cycle`（226）——checkout→复用同目录→编辑→
   commit（version_number==2、编辑成员 sha 匹配、源目录消失、原版本成员完好）。
5. `test_v11_core.py::test_bundle_members_survive_reopen`（258）。
6. `test_v11_invariants.py::test_bundle_member_paths_never_escape_payload_dir`（153）+
   aggregate 可从成员重算；`test_committed_version_payload_is_readonly`（37）。
7. `test_v11_review1_fixes.py`：`test_nested_member_bundle_paths`（33，P1-1）、
   `test_over_budget_bundle_rejected_before_any_io`（54，move=True 源 70 项完好）、
   `test_duplicate_member_names_rejected_or_disambiguated`（71）、
   `test_member_name_collision_nested_vs_top_level`（299，重开一致）、
   `test_spec_name_vs_auto_name_collision_disambiguated`（321，spec 赢、auto 得 `~2`）、
   `test_migrate_run_ports_backfills_outputs_only_and_idempotent`（185）。

建议**新增**冻结场景（C++ oracle 缺口）：
- **命名池冲突矩阵**：spec-vs-spec（`Duplicate member name`）、spec-vs-auto（`~2` 后缀）、
  auto bare-vs-rel（`data.csv` vs `sub/data.csv`）、三重冲突耗尽 → `~2/~3` 递增。
- **copy-then-delete 崩溃窗**：注入 `_save` 失败 → E4 全补偿（run 回填撤销、version 移除、
  current_version_id 还原、树删除、**源目录仍在**）；注入 Phase E1/E2/E3 → 树删除 + 原 raise 类型。
- **放置中途失败**：第 k 个成员写失败（chmod 目标目录只读模拟）→ 前 k-1 成员与 target_dir 全清。
- **T3 分支**：预置非空 target_dir → `Managed payload already exists`（空 target_dir 允许覆盖通过）。
- **rel-path 拒绝逐字**：`""`、`"../x"`、`"a/../../x"`、`"/abs/x"`（POSIX）；接受 `".."` 字面文件名
  （如 `"a..b"`）与反斜杠名。
- **A7 顺序敏感情境**：`"a/b"` vs `"a.txt"` 混排（Path 元组序 vs 字符串序不同）钉死 ordinal 回填序。
- **verify 边界**：member.sha256 为 None → unknown；删成员文件 → missing；aggregate 与 version.sha256
  不一致（手工篡改 version 行）→ 整体 modified。
- **WC 状态机**：live 行 + 目录存在 × allow_replace{0,1}；live 行 + 目录缺失（只删行）；
  未注册非空 target（复用）；M5 失败 → 新资产移除 + 行回 dirty。

---

## ⑤ 有界偏离清单（如实）

1. **Path 排序语义**：Python `sorted(Path)` 按组件元组比较（`a/b < a.txt`），std::filesystem::path
   比较按原生串（`a.txt` < `a/b`）。placed 序 = ordinal 回填序 → C++ 须显式实现组件向量比较，否则
   无 spec 成员的 ordinal 与 Python 不同（名字池不受影响，其用字符串排序）。**建议保真实现**；
   若实现为字符串序则为已声明偏离（仅影响 ordinal 展示序，不影响身份/校验）。
2. **符号链接**：Python rglob 不下钻目录符号链接、`is_file()` 跟随文件符号链接（按内容拷贝）；
   C++ `recursive_directory_iterator`（默认 follow_directory_symlink 关闭）+ `fs::is_regular_file`
   （跟随）等价；须显式跳过符号链接目录项本身。
3. **safe-id 非 ASCII**：沿用 15-decisions D14 已声明超集（trash.cpp 64-90 注释）；bundle 放置共用
   同一助手 → 同一偏离面。
4. **Windows 分支不移植**（本机/目标 POSIX）：8.3 短路径 resolve 锚定、`safe_unlink` NTFS 只读舞步、
   `fsync_dir` win32 直接返回（C++ 保留 O_DIRECTORY best-effort 语义）。
5. **错误码映射为新增决策**（Python 只有异常类）：§② 映射表为冻结提案，非既有事实。
6. **`register` 内部兜底断言无回滚**（351-355）：C++ 建议保持逐字（不可达）而非"顺手加回滚"——
   如加，记为有意偏离。
7. **staging lease / 注册表操作吞错**：Python 全部 try/except pass；C++ 缝接口以"失败即无操作"语义
   对齐（不引入 Python 不会抛的硬失败）。
8. **`working_copy_state` 项目外路径** → None（ValueError 捕获）；C++ by_rel_path 前缀失配 → nullopt。
9. **C++ `RunPort.direction` 额外字段**（models.hpp 30，Python 无）：序列化时注意不落入既有表列。

---

## ⑥ 风险 / 先例坑

1. **D3 成功哨兵**：所有 `domain::DataError` 出口显式 `ErrorCode::Ok`（31-decisions D3，三处初版踩坑）。
2. **stage 目录名双源**：models.hpp `kStageDirs`（enum 序）与 trash.cpp `stage_dir_name`（switch）
   已重复；place_managed_tree 第三处引用时必须收敛到单一来源——"outputs 非 output"是 R3#1 租约键
   前例的真实事故形态。
3. **放置在锁外**（Python 两段锁，Phase B/E 之间无锁）：C++ service_core 若用不可重入锁，一步式
   API 无法内嵌加锁 → 已按 plan/commit 两阶段设计规避；一步式仅供测试/已持锁调用方。
4. **GC 交互窗口**：放置后提交前靠 staging lease 免于 orphan 回收；lease 是 best-effort，无 lease 时
   靠 GC 锁内复验（#1222）。gc.cpp 的 orphan 扫描键格式必须与 `_staging_target` 前缀一致。
5. **崩溃窗两处**：(i) 放置后提交前 → 孤儿树（GC 职责）；(ii) save 后 move-rmtree 前（M5）→ 数据双份 +
   残 working 目录 + `committing` 僵尸行（`recover_working_copies` 职责，R5/service_core）。
   v11_bundle 不自愈，只负责 M4/M7/M8 状态翻转。
6. **A7 交错语义**：spec 名查重与 auto 分配按 sorted rel 交错——不可"先验全部 spec 名"重构，否则
   错误触发顺序与 auto 后缀分配都会变（test 321 依赖此序）。
7. **`Bundle member names are not unique (internal error)` 无回滚**：不可达兜底，保真移植时注意别在
   此分支添加 Python 没有的 rmtree。
8. **ensure_catalog_layout 副作用**：Python 每次放置建七目录（70-82）；trash.cpp `artifacts_root`
   只建 root。place_managed_tree 采用哪种将影响依赖目录存在的测试（working/trash 惰性创建可接受，
   但需声明；建议 Python 保真）。
9. **P1-1/P1-2/P1-4 是评审修复回归项**：version_dir_rel 必须从布局推导；move 必须 copy-then-delete；
   命名必须单一池——oracle 场景 7/§④ 新增矩阵即为其回归钉。
10. **成员 ordinal 语义**：spec.ordinal 可重复且不重排（aggregate 按 (ordinal,name) 排序，与列表序
    解耦）；组装时勿"规范化"ordinal。
11. **verify 报告 JSON 键序**：`bundle/members/status` + `actual_sha256` 条件键——parity 测试用
    ordered_json 断言键序。

— R8，2026-09-19
