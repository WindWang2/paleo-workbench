# R7 recon — 模型注册表 / promote / 治理元数据（CONV-31b）

侦察与契约冻结，不含实现。行号锚点基于 worktree `feat/cpp-catalog-service`：
- PY = `/home/kevin/project/worktrees/cpp-catalog-service/paleo_workbench/catalog/`（service.py / model_gates.py / governance.py / models.py / db.py）
- CPP = `/home/kevin/project/worktrees/cpp-catalog-service/libs/catalog/`

上位文档：`31-decisions.md` D1（policies.hpp 已含 can_promote_to_production，事实以结构体注入 = 依赖倒置先例）；`31-gap-analysis-big.md` §2（模型注册表 2815-3124 未覆盖）、§8（export_manifest 已透传 models/model_versions）。

---

## ① 语义契约（逐函数、逐分支、错误消息逐字）

### A. 模型注册表 — 读组

| 函数 | PY 锚点 | 语义 |
|---|---|---|
| `_model_or_raise(model_id)` | service.py:2815 | 线性扫 `document.models` 按 `model_id` 匹配；未命中 raise `CatalogError(f"Unknown model: {model_id}")` |
| `get_model(model_id)` | service.py:3016 | 直接委托 `_model_or_raise` |
| `get_model_version(model_id, model_version)` | service.py:3019 | `key = str(model_version)`；扫 `model_versions` 匹配 `(model_id, model_version==key)`；未命中 raise `f"Unknown model version: {model_id}@{model_version}"`（消息用**原始入参**，非 key；字符串入参下等价） |
| `get_model_version_by_id(id)` | service.py:3026 | 扫 `model_versions` 按 `id`；未命中 raise `f"Unknown model version: {model_version_id}"` |
| `list_models()` | service.py:3032 | 浅拷贝，**文档顺序**（= db 读回的 rowid 顺序，db.py:1686 `ORDER BY rowid`） |
| `list_model_versions(model_id=None)` | service.py:3035 | `model_id is None` 时不过滤（注意：空串 `""` 会过滤而非全量）；`sorted(key=created_at)`（ISO 字符串比较，stable sort → 平局保持文档顺序） |

### B. `register_model` — service.py:2821-2940

入口校验（锁外）：`if not model_id or not model_name: raise CatalogError("register_model requires model_id and model_name")`（逐字）。
随后取 `self._lock`（#517），调 `_register_model_locked`（2863）：

**存在同 `model_id` 时（幂等刷新分支）**：
1. `before` 快照 = (model_name, model_type, capability, provider, status, dict(metadata), dict(provenance))。
2. 刷新规则（`changed` 标志累积）：
   - `model_name`：无条件刷新（`!=` 即改；入参已保证非空）。
   - `model_type`：仅当入参 truthy **且** `!= "unknown"` 且与现值不同 → 改（空/`"unknown"` 永不覆盖）。
   - `capability`：仅 truthy 且不同 → 改（**空串永不抹掉**——find_production_model 依赖它，docstring 明示）。
   - `provider`：仅 truthy 且不同 → 改。
   - `status`/`metadata`：**仅 `force_status=True`** 时，`existing.status != status` 或 `existing.metadata != dict(metadata or {})` → 两者同时替换（metadata 是**整体替换**非合并）。`force_status=False`（默认）绝不触碰 status/metadata（评审 C2：种子/默认调用不得静默降级已 promote 的模型）。
   - `provenance`：入参 truthy → `existing.provenance.update(provenance)` **合并**（dict.update，键级覆盖）。
3. `changed=False`（纯 no-op 重注册）→ **不调 `_save`**，目录文件不重写、revision 不动。
4. `changed=True` → `_save(DirtySet(models={existing.id: None}))`；失败 → 恢复 `before` 快照（内存回滚）后 re-raise。

**新模型分支**：构造 `Model`（id=`_id("model")` 即 `{prefix}_{12hex}`（project/models.py:22）；`model_type=model_type or "unknown"`；metadata/provenance 各 `dict(x or {})` 拷贝），append 到 `document.models`，`_save(DirtySet(models={model.id}))`；失败 → `_discard_by_identity` 移除 + re-raise（service.py:2938 附近）。

### C. `register_model_version` — service.py:2942-3014

**顺序敏感**（锁的边界是显式设计）：
1. `self._model_or_raise(model_id)` —— **锁外**（校验 model 存在）。
2. `if str(status) == "production": raise CatalogError("register_model_version cannot set status=production; register as demo then call promote_model()")`（逐字，源码为两段字符串拼接）。
3. 重复检查（**锁外**）：`any(v.model_id == model_id and v.model_version == str(model_version))` → raise `f"ModelVersion {model_id}@{model_version} already registered"`。⚠ Python 存在 TOCTOU 窗口（检查与锁内 append 之间）；C++ 提案在锁内复查（见 ⑤ 偏离 1）。
4. checksum 推导（**锁外**，注释明示"锁绝不跨磁盘 IO"）：`checksum is None and artifact_uri` truthy → `Path(artifact_uri).expanduser()`；`is_file()` → `sha256_file(candidate)`（流式，catalog/checksum.py）；`OSError` → **静默回落 None**；非文件/空 uri → 保持 None。
5. 构造 `ModelVersion`（id=`_id("mver")`；`model_version=str(...)`；`status=status or "demo"`；schemas/metadata/provenance 各 `dict(x or {})`）。
6. 锁内：append → `_save(DirtySet(model_versions={version.id}))`；失败 → `_discard_by_identity` 移除 + re-raise。

DTO 默认值陷阱（models.py:211-238）：`ModelVersion.status` 字段默认 **`"production"`**（为旧文档加载而设）；本函数用参默认 `"demo"` 覆盖之。C++ DTO 必须逐字镜像行加载默认（production），注册函数默认独立传 "demo"（见 ⑥ 风险 3）。

### D. `promote_model(model_id, model_version)` — service.py:3043-3088

**全程持锁**（含门禁评估；门禁只调 get_model/get_model_version，无 IO）：
1. `model = self._model_or_raise(model_id)` → 未命中 `f"Unknown model: {model_id}"`。
2. 按 `(model_id, key=str(model_version))` 扫版本；未命中 raise `f"ModelVersion {model_id}@{model_version} not registered"`（注意与 C 组的 already registered 措辞不同）。
3. `ok, reason = can_promote_to_production(self, model_id, model_version)`（`require_input_schema=True` 默认）；`not ok` → raise `f"Cannot promote to production: {reason}"`（reason 逐字来自门禁，见 E）。
4. 三元突变：`model.status = "production"`、`version.status = "production"`、`version.demo_only = False`。
5. **单次原子 `_save(DirtySet(models={model.id}, model_versions={version.id}))`**（两行一个事务）；失败 → 恢复三个字段 + re-raise。
6. 返回该 `ModelVersion`。

### E. `model_gates.can_promote_to_production` — model_gates.py:25-59（C++ 已在 policies.cpp:423-463 逐字实现）

判定序（首个命中即返回）：
1. `get_model`/`get_model_version` 抛错 → `(False, str(exc))`（即 A 组的两条 Unknown 消息原样透传）。
2. `version.demo_only` → `(False, "demo_only model versions cannot be promoted to production")`。
3. provider 规范化 = `(model.provider or "").strip().casefold()`；命中 `{demo, local_asset}`（集合元素同样 strip+casefold，H4-3c：`"Demo"`/`"local-asset"` 不得漏过）→ `(False, f"provider {model.provider!r} is not promotable to production")`——**repr 用未 strip 的原始值**（Python 单引号 repr）。
4. model_type 同法命中 `{demo, heuristic}` → `(False, f"model_type {model.model_type!r} is not promotable to production")`。
5. `model.metadata.get("scientific") is False`（**身份比较**：仅布尔 False，0/"false" 不算）→ `(False, "model metadata marks scientific=False")`。
6. `version.metadata.get("scientific") is False` → `(False, "version metadata marks scientific=False (H4-3b)")`。
7. `require_input_schema and not version.input_schema` → `(False, "input_schema is required for production promotion (H5-b)")`。
8. `(True, "ok")`。

`require_input_schema=False` 是**读路径专用豁免**（Agent L P2）：schema 契约前的历史 promote 不得在升级后从读取中消失。

### F. `find_production_model(capability)` — service.py:3090-3124（读路径，**不持锁**）

逐版本扫描 `document.model_versions`，淘汰链（全部 continue，不抛错）：
1. `version.demo_only or version.status != "production"` → 跳过。
2. `self._model_or_raise(version.model_id)` 抛 CatalogError（孤儿版本，model 行缺失）→ **跳过不抛**。
3. `model.status != "production" or model.capability != capability` → 跳过。
4. 重验门禁 `can_promote_to_production(self, model.model_id, version.model_version, require_input_schema=False)`；`not ok` → 跳过（H4-3a/H4-3c：promote 后身份被改写的模型永不作为生产 served）。
5. `best is None or version.created_at > best.created_at` → 取代（ISO 字符串 `>`；**平局保留文档序先到者**）。
6. 无合格者返回 `None`（调用方必须诚实呈现"无生产模型"，不得跑 mock）。

### G. `update_asset_metadata(asset_id, patch)` — service.py:3205-3247

1. 持锁；`_asset_or_raise`（map 未中先 `_invalidate_maps`+重建安全网，service.py:1238-1248）→ `f"Unknown asset: {asset_id}"`。
2. `normalized = normalize_governance_patch(patch)`（governance.py:177-196）——抛 **`GovernanceError`（ValueError 子类，非 CatalogError）**：
   - 保留键拒绝：`format`/`external`/`trash`/`legacy_tags`（RESERVED_METADATA_KEYS，governance.py:143）→ `f"字段 {key!r} 是目录内部保留键，不能通过治理信息修改"`（`{key!r}` = Python repr 单引号）。
   - 治理键 → `normalize_governance_value`（governance.py:146-174）：
     - `value is None` → `""`；`" ".join(str(value).split())` 空白折叠；空 → `""`（= 清除字段）。
     - 自由文本键（source/region/creator）→ `text[:200]` 截断。
     - 受控词键（discipline 13 值 / confidence high·medium·low / review_status draft·pending_review·approved·rejected）→ `aliases` 查找：先 `casefold(lowered)` 键、再原 `text` 键；未中再判 `lowered in vocabulary` / `text in vocabulary`；仍未中 → `f"{spec.label}({key}) 的值 {text!r} 不在受控词表中: {allowed}"`（`allowed = "、".join(vocabulary)`，词表声明序）。
   - 非治理键 → **原样透传**（值类型不变）。
   - 上述全部消息 C++ policies.hpp:40-57 已逐字冻结（31-decisions D1）。
3. 应用循环（按 patch 的 dict 序）：`stored = None if value in (None, "") else value`；`asset.metadata.get(key) != stored` 才动——`stored is None` → `pop(key, None)`（键不存在也不算 changed）；否则赋值。
4. `changed=False` → 返回 asset，**不 save、updated_at 不动**。
5. `changed=True` → `asset.updated_at = _now_iso()`（project/models.py:18，UTC isoformat）→ `_save(DirtySet(assets={asset.id}))`；失败 → 恢复 `before_metadata` dict + `before_updated` + re-raise。
6. 版本级对应方法**刻意不存在**（版本元数据不可变，ADR 0056）。

### H. `promote_version(version_id, to_stage=OUTPUT, reviewed_by=None, note=None)` — service.py:3665-3740

1. `source = self._version_or_raise(version_id)` → `f"Unknown version: {version_id}"`。
2. `source.trashed` → `f"Cannot promote a trashed version: {version_id}"`。
3. `to_stage` 非 DataStage → `DataStage(to_stage)` 强转。
4. `source_payload = self.resolve_path(source)`（**resolve_path 阶梯是另一切片的接缝**，service.py:1502-1544）；`not is_file()` → `f"Source payload not available: {source_payload}"`（消息含**绝对路径字符串**）。
5. `asset = self._asset_or_raise(source.asset_id)`；`previous_current = asset.current_version_id`。
6. **promote run 形状（冻结）**：`DataRun(id=_id("run"), operation="promote", input_version_ids=[source.id], parameters={"to_stage": to_stage.value, "reviewed_by": reviewed_by, "note": note})`；`status` 默认 "completed"；`output_version_ids` 在版本建成后回填 `[version.id]`。`reviewed_by`/`note` 为 None 时 JSON 里是 `null`。
7. staging lease（#1222）：`with self._payload_staging_lease(self._staging_target(to_stage, asset.id))`——kind 默认 `"register"`；target = `"<项目名>.artifacts/<STAGE_DIRS[to_stage]>/<asset_id>"`（ON-DISK 目录名 `outputs`，**不是** `stage.value` `"output"`，R3#1）；lease 获取失败 → None，继续（best-effort）。
8. **锁外** `_build_version(..., version_id=None, parent_version_ids=[source.id], run_id=run.id, metadata={"promoted_from": source.id, "reviewed_by": reviewed_by, "note": note}, move=False)`：
   - unsafe asset.id 门：`f"Unsafe asset id {asset.id!r}: only [A-Za-z0-9._-] allowed"`（#1175）。
   - `version_number = self._next_version_number(asset.id)`（**锁外暂估值，随后被覆盖**）。
   - `place_managed_file(..., keep_source=True)` → payload **复制不移动**（内容同 CAS blob 时零拷贝收养）；`path/size_bytes/sha256` 回填；`format = asset.metadata.get("format", "")`；`managed=True`。
   - 新版本 `metadata = {"promoted_from": source.id, "reviewed_by": ..., "note": ...}`。
9. **锁内（#517 + #849-1）**：`version.version_number = self._next_version_number(asset.id)` **重新分配**（`_build_version` 锁外算的数作废；否则同 asset 并发 promote 双双 max+1 → [1,2,2]，audit #849-1）→ `_add_version`（+索引维护）→ `_add_run` → `asset.current_version_id = version.id` → 单次 `_save(DirtySet(assets={asset.id}, versions={version.id}, runs={run.id}))`。
10. save 失败 → `_rollback(versions=[version], runs=[run], payload=payload, restore_current=(asset, previous_current))`（service.py:1569-1603）：移除行+索引、恢复 current；payload——**CAS blob 路径绝不 unlink**（共享不可变）；有 `restore_payload_to` 则 `os.replace` 回移；否则 `safe_unlink` + 尽力剪空目录。
11. 源版本**原样保留**（不可变+溯源）；仅 asset 的 current 前移。

`_next_version_number(asset_id)`（service.py:1616-1620）：`max(versions_by_asset[asset_id] 的 version_number, default=0) + 1`。C++ `CatalogDocument::next_version_number`（models.cpp:50-58）已等价（扫全表 versions）。

### I. `promote_asset(asset_id, to_stage=OUTPUT, reviewed_by=None, note=None)` — service.py:3742-3759

`_asset_or_raise` → `f"Unknown asset: {asset_id}"`；`current_version_id is None` → `f"Asset has no current version: {asset_id}"`（逐字）；否则委托 `promote_version(asset.current_version_id, ...)`。

### J. 持久化契约（db.py ↔ C++ 现状）

PY 侧（canonical sqlite v5+）：
- 表结构 db.py:463-493：`models(id PK, model_id, model_name, model_type DEFAULT 'unknown', capability DEFAULT '', provider DEFAULT '', status DEFAULT 'demo', metadata TEXT DEFAULT '{}', created_at DEFAULT '', provenance TEXT DEFAULT '{}')` + `idx_models_model_id`；`model_versions(id PK, model_id, model_version DEFAULT '1', artifact_uri DEFAULT '', checksum NULLABLE, input_schema/output_schema TEXT DEFAULT '{}', preprocessing_version/runtime DEFAULT '', deterministic INT DEFAULT 1, demo_only INT DEFAULT 0, status DEFAULT 'production', metadata, created_at, provenance)` + `idx_model_versions_model_id`。
- 行序列化 `_model_row`/`_model_version_row`（db.py:671-722）：JSON 列 `json.dumps(..., ensure_ascii=False)`；bool → int。
- 写通道：`_MODEL_UPSERT_SQL`/`_MODEL_VERSION_UPSERT_SQL`（ON CONFLICT(id) DO UPDATE 全列）；`apply_changes` 内 dirty.models/model_versions（db.py:2147-2160，id 不在文档 = DELETE）+ `_ordered` rowid 保序；全量 diff `_symmetric_diff`（db.py:2352-2357）；初始批量插入 db.py:2565-2571。
- 读回：`SELECT * FROM models ORDER BY rowid`（db.py:1686/1706）→ DTO（int→bool）。

C++ 现状：
- `models.hpp` **无 Model/ModelVersion DTO**；`CatalogDocument` 无对应 vector。
- `repository.cpp` load（309-467）读 assets/version_members/versions/runs/run_ports/tags/asset_tags/version_tags/working_copies/lineage/staging_leases——**不读 models/model_versions**。
- `export_manifest`（repository.cpp:480-525）：`manifest["models"]/["model_versions"] = passthrough_rows(db, ...)`（140-：PRAGMA 探列、TEXT-JSON 列解析）——**raw 行透传**，不丢注册表内容。
- `rebase_artifact_paths`（repository.cpp:1084-1100）：**已有** `model_versions.artifact_uri` 首段改写（save-as 搬迁）——当前唯一的 model_versions 写路径。
- 无 typed upsert、无 delete、无 promote 双行事务。

---

## ② 冻结 C++ API 提案（C++20、Qt-free）

### ②.1 DTO 并入 `models.hpp`（与 DataAsset/DataRun 同居，Python 命名 1:1）

```cpp
namespace pwb::catalog {

struct Model {
    std::string id;                // domain::make_id("model")  → "model_{12hex}"
    std::string model_id;
    std::string model_name;
    std::string model_type = "unknown";
    std::string capability;
    std::string provider;
    std::string status = "demo";
    domain::Json metadata = domain::Json::object();
    std::string created_at;        // 空 → refs::utc_now_iso()
    domain::Json provenance = domain::Json::object();
};

struct ModelVersion {
    std::string id;                // domain::make_id("mver")
    std::string model_id;
    std::string model_version = "1";
    std::string artifact_uri;
    std::optional<std::string> checksum;
    domain::Json input_schema = domain::Json::object();
    domain::Json output_schema = domain::Json::object();
    std::string preprocessing_version;
    std::string runtime;
    bool deterministic = true;
    bool demo_only = false;
    std::string status = "production";   // 行加载默认（models.py:230）！注册函数另行传 "demo"
    domain::Json metadata = domain::Json::object();
    std::string created_at;
    domain::Json provenance = domain::Json::object();
};

}  // namespace pwb::catalog
```

`CatalogDocument` 增补：`std::vector<Model> models; std::vector<ModelVersion> model_versions;`
+ `const Model* find_model(std::string_view model_id) const;`
+ `const ModelVersion* find_model_version(std::string_view model_id, std::string_view model_version) const;`
+ `const ModelVersion* find_model_version_by_id(std::string_view id) const;`
+ 可变重载（register/promote 快照回滚需要）。

### ②.2 新头 `libs/catalog/include/pwb/catalog/model_registry.hpp` + `src/model_registry.cpp`

注册表读写全组为**自由函数 + 保存接缝**（沿 D1 依赖倒置：操作吃 `CatalogDocument&`，持久化经回调注入，C++ 尚无 service 类时即可落地/可测）：

```cpp
namespace pwb::catalog {

// 保存接缝（R4 _save 通道的模型注册表投影）：按文档序提交 dirty 行
// （id 不在文档 = 删除），成功返回 Ok；失败时调用方负责内存回滚。
struct RegistrySave {
    std::vector<std::string> models;          // 文档序 dirty model ids
    std::vector<std::string> model_versions;  // 文档序 dirty mver ids
};
using RegistrySaver = std::function<domain::DataError(const RegistrySave&)>;

struct RegisterModelRequest {
    std::string model_id, model_name;
    std::string model_type = "unknown", capability, provider, status = "demo";
    domain::Json metadata = domain::Json::object();
    domain::Json provenance = domain::Json::object();
    bool force_status = false;
};
// 幂等注册/刷新（契约 ①.B）。成功返回指向 doc 内的 Model。
domain::Result<Model*> register_model(CatalogDocument& doc, const RegistrySaver& save,
                                      const RegisterModelRequest& req);

struct RegisterModelVersionRequest {
    std::string model_id, model_version = "1", artifact_uri;
    std::optional<std::string> checksum;   // nullopt 且 uri 可读 → sha256_file（锁/提交外执行）
    domain::Json input_schema = domain::Json::object(),
                output_schema = domain::Json::object();
    std::string preprocessing_version, runtime;
    bool deterministic = true, demo_only = false, status = "demo";
    domain::Json metadata = domain::Json::object(), provenance = domain::Json::object();
};
domain::Result<ModelVersion*> register_model_version(
    CatalogDocument& doc, const RegistrySaver& save,
    const RegisterModelVersionRequest& req);   // 契约 ①.C；重复检查在提交前复查一次

domain::Result<const Model*> get_model(const CatalogDocument&, std::string_view model_id);
domain::Result<const ModelVersion*> get_model_version(
    const CatalogDocument&, std::string_view model_id, std::string_view model_version);
domain::Result<const ModelVersion*> get_model_version_by_id(
    const CatalogDocument&, std::string_view model_version_id);
std::vector<const Model*> list_models(const CatalogDocument&);
// model_id == nullptr → 全量（镜像 None 语义；不用空串判全量）
std::vector<const ModelVersion*> list_model_versions(
    const CatalogDocument&, const std::string* model_id);

domain::Result<ModelVersion*> promote_model(CatalogDocument& doc,
    const RegistrySaver& save,
    std::string_view model_id, std::string_view model_version);  // 契约 ①.D

const ModelVersion* find_production_model(
    const CatalogDocument&, std::string_view capability);        // 契约 ①.F

// 内部（头文件内可见以便 oracle 复用）：文档 → 门禁事实的装配器，
// 是 D1 依赖倒置接缝的具体化；find_production_model 用 require_input_schema=false。
std::tuple<std::optional<domain::ModelGateFacts>,
           std::optional<domain::ModelVersionGateFacts>,
           std::optional<std::string>>   // lookup_error：A 组消息逐字
model_gate_facts(const CatalogDocument&, std::string_view model_id,
                 std::string_view model_version);

}  // namespace pwb::catalog
```

调用方（未来 C++ service）职责：锁的获取（promote_model/find 事实装配无 IO，可整体入锁）、`_save` 实现、revision/CAS。

### ②.3 `update_asset_metadata` → 新头 `asset_metadata.hpp`（与注册表分离；governance 归 policies.hpp 已有面）

```cpp
namespace pwb::catalog {
using AssetSaver = std::function<domain::DataError(const domain::AssetId&)>;

// 契约 ①.G：governance 规范化（调 policies::normalize_governance_patch）、
// None/"" → 键删除、no-op 不 save、updated_at=utc_now_iso()、失败快照回滚。
// GovernanceError 映射 DataError{InvalidArgument, 逐字中文消息}。
domain::Result<DataAsset*> update_asset_metadata(
    CatalogDocument& doc, const AssetSaver& save,
    const domain::AssetId& asset_id, const domain::Json& patch);
}
```

### ②.4 promote 版本提升 → `version_promote.hpp`（run 形状 + 锁窗语义冻结）

```cpp
namespace pwb::catalog {
struct PromoteOptions {
    domain::DataStage to_stage = domain::DataStage::Output;
    std::optional<std::string> reviewed_by, note;
};
// 冻结的 run/版本 DTO 装配（契约 ①.H.6/8）——纯函数，无 IO：
DataRun make_promote_run(const domain::VersionId& source_id, const PromoteOptions&);
domain::Json make_promote_version_metadata(const domain::VersionId& source_id,
                                           const PromoteOptions&);
// staging lease 键（契约 ①.H.7）："<proj>.artifacts/<kStageDirs[to_stage]>/<asset_id>"
std::string promote_staging_target(std::string_view artifacts_dir_name,
                                   domain::DataStage, std::string_view asset_id);
}
// repository.hpp 增补（一行事务，全有或全无 + revision bump）：
//   domain::DataError upsert_model(const Model&);
//   domain::DataError upsert_model_version(const ModelVersion&);
//   domain::DataError promote_model_transaction(const Model&, const ModelVersion&);
//   domain::DataError commit_promote_transaction(const DataVersion&, const DataRun&);
//     （= upsert_version_rows + upsert_run_rows + run_inputs/run_outputs +
//        current 指针前移 + bump_revision，一事务；比 commit_version_transaction
//      多插 run 行，repository.cpp:945-969 先例只挂 run_outputs）
//   load 增读：models/model_versions SELECT * ORDER BY rowid（列序 db.py:1686-1706）
```

编排（resolve_path、place_managed_file、lease、`next_version_number` 锁内重分配、失败 `_rollback`）归 C++ service 切片；本提案冻结其全部形状与顺序。

---

## ③ 依赖与接口点

| 对端 | 接缝 |
|---|---|
| **R1（db 写通道）** | `apply_changes` 的 dirty.models/model_versions 分支（db.py:2147-2160）+ `_ordered` rowid 保序 + `_symmetric_diff`（2352-2357）+ 初始批量（2565-2571）。C++ 落点 = `upsert_model/upsert_model_version`（含 id-缺失即 DELETE 语义）；RegistrySaver 的实现最终走 R1。**ORDER BY rowid 读回**是文档序的来源（list_models 顺序 + 重插 rowid 不变量）。 |
| **R4（_save/save 通道）** | `_save(DirtySet)` 语义：no-op 不落盘不 bump revision（register_model 幂等分支、update_asset_metadata no-op 分支都依赖）；失败 → 调用方内存回滚；revision 仅 flush 成功后前进。RegistrySaver/AssetSaver 即其投影接口。 |
| **R9（现有面）** | policies.hpp:84-113 `can_promote_to_production` + ModelGateFacts/ModelVersionGateFacts（直接消费，勿重写）；policies.hpp:40-57 governance 规范化（update_asset_metadata 直接调）；checksum.hpp `sha256_file/sha256_file_or_none`（register_model_version 工件哈希，OSError→None 用 or_none 变体）；dedup.hpp `place_managed_file`（promote 复制放置，keep_source=true）；models.hpp `next_version_number`（#849-1 重分配直接用）；refs.hpp `utc_now_iso`；domain/ids.hpp `make_id`（"model"/"mver" 前缀）；repository.cpp export_manifest 透传（524-525）与 rebase 的 model_versions.artifact_uri 改写（1084-1100，勿回归）。 |
| 其他 | resolve_path 阶梯（另一 recon 的面，promote_version 前置）；storage `STAGE_DIRS` ↔ models.hpp `kStageDirs`；staging lease（#1222，acquire/release 归 service 索引面）。 |

---

## ④ oracle 冻结场景建议（`tools/oracle/generate_catalog_domain_fixtures.py` 增节）

1. **promote 门禁矩阵**（9 行 × reason 逐字）：ok；(False, lookup Unknown model/version)；demo_only；provider demo/local_asset（含 `"Demo"`、`" local_asset "` 变体，验证 strip+casefold）；model_type heuristic；model.metadata.scientific=False；version.metadata.scientific=False（消息含 `(H4-3b)`）；input_schema 空（promote 时拒绝 / find 时容忍，`require_input_schema` 不对称）。provider/model_type 消息须带**未规范化原值的 Python repr**。
2. **find_production_model 矩阵**：version.status≠production / model.status≠production / demo_only / capability 不匹配 / 孤儿 model_id（跳过不抛）/ 门禁重验失败（promote 后改 provider）各一行 + newest-by-created_at（含同刻平局保文档序先到）。
3. **register_model 刷新矩阵**：空 capability/provider/model_type="unknown" 不抹已有值；force_status=False 保 status+metadata（C2）；force_status=True 替换 metadata（非合并）；provenance 键级合并；纯 no-op → revision 不变（无 save 的可观测证据）。
4. **register_model_version**：重复 `(model_id, model_version)` 消息逐字；status="production" 拒绝消息逐字（含分号+空格）；checksum 从工件推导 / 不可读工件 → null。
5. **#849-1 版本号锁内重分配**：同 asset 两版本预置后并发序（build 期暂估 N+1 → 提交期重分配 N+1/N+2，产出 [.., N+1, N+2] 而非 [.., N+1, N+1]）。C++ oracle 可用"分配器在 build 与 commit 各调一次、commit 值生效"的断言形状。
6. **governance 规范化管线**：别名折叠（"待审核"→pending_review、"高"→high、"stratigraphy"→correlation、"pending"→pending_review）；自由文本 200 截断 + 空白折叠；保留键（format/external/trash/legacy_tags）拒绝消息逐字（含 repr 单引号）；None/"" → 键删除；非治理键透传（含非标量值）；no-op patch → revision 不变；save 失败 → metadata/updated_at 快照回滚。
7. **promote run 记录形状**：operation/parameters/metadata 键逐字（to_stage 用 stage.value "output"；reviewed_by/note null）；parent_version_ids=[source]；源版本未变；asset.current_version_id 前移；payload 复制（源文件仍在）；失败路径 CAS blob 不删除。

---

## ⑤ 有界偏离清单（如实）

1. **register_model_version 重复检查收窄进提交窗**：Python 检查在锁外（TOCTOU：两线程可同时通过 any() 后串行 append 出重复对）。C++ 在提交前复查一次。单线程 oracle 不可见差异；行为只会更严。
2. **GovernanceError 类型折叠**：C++ 单一 DataError 通道（code=InvalidArgument + 逐字中文消息）；Python 区分 GovernanceError(ValueError) vs CatalogError。消息保真，类型映射需在 R4/service 边界文档化。
3. **错误类型总体映射**：CatalogError → DataError{NotFound（Unknown *）/InvalidArgument（参数校验、门禁拒绝、governance）}；ImmutableVersionError 保留现有枚举。消息逐字，仅 code 是新增归属。
4. **`f"Source payload not available: {path}"` 的路径串**：Python `str(Path)`；Linux 上与 `std::filesystem::path::string()` 一致；Windows 分隔符差异按本仓库"Linux 行为先"先例（D 系列既有做法）。
5. **register_model_version 的 model 存在性检查时点**：Python 锁外校验后、锁内 append 前模型可能被删（可产生孤儿 model_version；find_production_model 容忍）。C++ 镜像"校验早于提交"次序，不额外加锁内复查（与偏离 1 只覆盖唯一性检查保持最小收窄）。
6. **metadata 相等性**：Python dict == 键序无关；nlohmann Json 对象 == 亦键序无关——等价，无偏离（记录以备 review）。

---

## ⑥ 风险 / 先例坑

1. **ORDER BY rowid 陷阱**：C++ 通用读 helper（repository.cpp:164）按 `ORDER BY id`；models/model_versions 必须按 **rowid** 读（db.py:1686/1706），否则 list_models 顺序漂移、重插行 rowid==文档序不变量破坏（`_ordered` 依赖）。
2. **ModelVersion.status 双默认**：DTO/行默认 `"production"`（旧文档加载），注册函数默认 `"demo"`。C++ 若统一成一个默认，要么破坏旧行加载保真，要么绕过 Stage-13 安全设计。二者必须分开声明（②.1 已显式注释）。
3. **`scientific is False` 身份比较**：仅布尔 False 触发；0、"false"、null 均不触发。JSON 往返后 0 不得误判（policies.cpp:453-457 已正确，勿在装配 facts 时提前归一化）。
4. **promote 读豁免不可"修复"**：`require_input_schema=False` 只属 find_production_model；把它统一成 True 会让 schema 契约前的历史 promote 从读取消失（Agent L P2 回归）。
5. **锁边界是语义**：register_model_version 的哈希、promote_version 的 payload 复制都必须在锁/事务外（Python 注释明示"锁绝不跨磁盘 IO"）；#849-1 的重分配又必须在锁内。C++ service 化时把任一侧收错都会复现 [2,2] 或长时间持锁。
6. **no-op 不落盘**：register_model 幂等分支与 update_asset_metadata no-op 分支依赖"changed=False → 不调 save"。若 C++ saver 侧无条件 flush，会产生 revision 噪声 + manifest 重写（#1183 unchanged-skip 失效）。
7. **export_manifest 双源**：typed 读落地后 manifest 既可走 typed 序列化也可维持 passthrough_rows；二选一须显式（维持 passthrough 最稳，typed 列序/JSON 列解析必须与 PRAGMA 探测等价），避免 models 出现两种列集合。
8. **rebase 已写 model_versions.artifact_uri**（repository.cpp:1084-1100）：新增 typed upsert 不得改变其首段改写语义；反之 promote/register 写入的 artifact_uri 也要能被后续 rebase 正确处理。
9. **名字冲突面**：`pwb::catalog::Model` 较泛用；当前无冲突（现有 DTO 均在 pwb::catalog），但 prediction 域未来入 C++ 时需别名区分——先例：DataAsset/DataVersion/DataRun 均为平名，保持一致即可。
10. **DataError 成功哨兵先例（D3）**：新 repository 事务函数成功必须显式 `DataError(ErrorCode::Ok, "")`，勿重蹈 apply_run_ports 尾返回踩坑。
