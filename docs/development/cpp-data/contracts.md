# CPP-B 接口契约（冻结 v1）

对应总设计 §“接口握手 v1”。B 是 ProjectSnapshotV1 / LayerBindingV1 / CommitRequestV1 /
CommitReceiptV1 的 owner；A/C 是消费者。**公共接口不携带 QGIS/Qt/Python 类型**——A 经
`libs/application/adapters/` 连接，B 永远不接受 QgsFeature/QgsGeometry。

## 1. 构建

```text
cmake -S libs/data_suite -B build/cpp-data -DBUILD_TESTING=ON
cmake --build build/cpp-data --config Release   # 最多 2 jobs（经资源门禁）
ctest --test-dir build/cpp-data -R "^data\."    # 本线测试命名前缀
```

- 目标：`Pwb::Domain`、`Pwb::Project`、`Pwb::Workspace`、`Pwb::Catalog`、`Pwb::Data`（聚合）、
  工具 `pwb-inspect` / `pwb-migrate`。
- C++20；无 Qt/QGIS/Python 链接（验收 Oracle 1 用 `dumpbin /DEPENDENTS` 或链接清单核验）。
- vendored 依赖只出现在 `libs/data_suite/third_party/`（sqlite3 3.45.1、nlohmann json 3.12.0）；
  模块库经缓存变量 `PWB_VENDOR_DIR` 引用（默认相对解析到 `../data_suite/third_party`）。

## 2. 强类型 ID（`pwb/domain/ids.hpp`）

```cpp
PWB_STRONG_ID(AssetId)     // "asset_" + 12 hex
PWB_STRONG_ID(VersionId)   // "ver_"  + 12 hex
PWB_STRONG_ID(RunId)       // "run_"  + 12 hex
PWB_STRONG_ID(LayerId)     // 文档层 doc_id（QGS 侧唯一 join key）
PWB_STRONG_ID(EntityId)
PWB_STRONG_ID(OperationId) // CommitCoordinator 幂等键（调用方生成，uuid 十六进制）
```

均为显式构造的值类型（`std::string` 载体 + `==`/`<`/`hash`），无默认隐式转换；
`id.is_safe_storage_segment()` 实现 Python `_is_safe_version_id` 语义（`[A-Za-z0-9._-]`、
非点开头——作为 `{stage}/{asset}/{version}/` 路径段前的门禁）。

## 3. ProjectSnapshotV1（不可变工程快照）

```cpp
namespace pwb::data {
struct ProjectSnapshotV1 {
    std::filesystem::path project_file;     // *.paleo.json
    int schema_version = 1;                 // >KNOWN → 只读+诊断
    ProjectMetaV1 meta;                     // name/region/version/created/updated/project_root
    WorkspaceStateV1 workspace;             // 见 §5
    std::vector<EntityAssetLinkV1> entity_asset_links;
    std::vector<ResourceRefV1> resources;   // path(运行时绝对)/external/存在性
    std::vector<LayerBindingV1> layer_bindings;   // 从 memberships 投影
    std::string map_qgis_project_xml;       // 原样信封
    std::vector<DiagnosticV1> diagnostics;  // 未知节/future schema/丢失资源/路径逃逸
    bool read_only = false;                 // future schema / 损坏降级
};
}
```

语义：快照携带**诊断而非异常**；未知顶层节保留在底层文档（见 §6 持久化模型），快照层报告
`unknown_section` 诊断。`ProjectRepository::load()` 返回 `expected<ProjectSnapshotV1, DataError>`。

## 4. LayerBindingV1 / CommitRequestV1 / CommitReceiptV1

```cpp
struct LayerBindingV1 {          // 与 LayerMembershipRecord 绑定语义 1:1
    LayerId layer_id;
    std::string role;            // LayerRole 词表；未知→"legacy_unclassified"
    AssetId source_asset_id;     // 空 = UNKNOWN（不伪造）
    VersionId source_version_id; // 空 = UNKNOWN
    std::string binding_kind;    // "catalog_version"|"content_fingerprint"|""=未绑定
    std::string bound_at;        // ISO；空 = 历史
    std::string factor_task_id, constraint_kind, created_stage, created_at;
};

struct StagedAssetV1 {           // A/C 交给 B 的已落盘产物（不是 QgsFeature）
    std::filesystem::path source_path;      // 必须已存在
    std::optional<std::string> sha256;      // 缺省时 B 计算
    std::string format;
};

struct CommitRequestV1 {
    OperationId operation_id;               // 幂等键：重复提交返回同一 receipt
    AssetId asset_id;                       // 目标资产（须存在）
    VersionId base_version_id;              // 乐观锁：≠ asset.current_version_id → 冲突
    DataStage stage = DataStage::Derived;
    StagedAssetV1 staged;
    std::vector<VersionId> parent_version_ids;
    std::optional<RunId> run_id;            // manual_edit run（可选）
    std::optional<LayerId> rebind_layer;    // 提交成功后重绑的图层
    std::string version_name;               // → version.metadata["name"]（空=不写）
};

struct CommitReceiptV1 {
    OperationId operation_id;
    VersionId new_version_id;
    int version_number = 0;
    std::string sha256;                      // payload 实测
    std::uintmax_t size_bytes = 0;
    CommitStatus status;                     // Committed|Duplicate|Conflict|Failed|RolledBack
    std::vector<DiagnosticV1> diagnostics;   // 冲突详情/恢复结论/验证失败原因
};
```

错误码（`pwb/domain/errors.hpp`，`DataError{code, message, detail}`）：
`ok` / `invalid_argument` / `not_found` / `conflict_base_version` / `duplicate_operation`（幂等命中，
非错误，status=Duplicate）/ `immutable_version` / `unsafe_id` / `path_escape` / `io_error` /
`corrupt_json` / `corrupt_database` / `future_schema` / `recovery_required` / `cancelled` / `unknown`。

## 5. WorkspaceStateV1

`MappingWorkspaceState` dict 的类型化投影（7 键全量），`to_dict()`/`from_dict()` 与 Python
`stage_state.py` 字段级一致；未知 role/stage/binding_kind/maturity 的回落规则同 Python
（LEGACY_UNCLASSIFIED / FACIES_CALIBRATION / 不加载该 maturity 项）。`tree` 与
`compilation_input_set` 原样 JSON 保留（B 不解释 QGS 树语义）。

## 6. 持久化模型（unknown-field round-trip 的实现基础）

`.paleo.json` 不降级为无类型 `QJsonObject`，也不用全字段结构体硬编码：
**每层 = 已知字段的类型化视图 + `nlohmann::ordered_json extra`（该层未知键）**。
写回 = 类型化字段序列化 ⊕ extra 原样合并（键序按 Python `model_dump` 字段序 + extra 按字母序
追加）。这同时满足“不无类型化”与“未知字段任意可扩展层级保留”。

可扩展层级（Python `extra="allow"` 或 dict 载体）：文档顶层、`Geo3DWorkspaceState`、
`mapping_workspace` 全嵌套 dict、`compilation_input_sets`、`integrated_interpretations`、
`interpretation_revisions`、`onboarding_report`、各 `metadata`/`properties`/`display` dict。
非可扩展层级（pydantic 默认 ignore）：Python 自身也不保留未知键——本线与 Python 行为对齐，
差异记入 schema-map §“层级矩阵”。

## 7. CommitCoordinator（B 唯一提交协议）

- journal：`<proj>.artifacts/metadata/commit_journal/<operation_id>.json`，阶段化推进
  （`write_journal` → `stage_payload` → `catalog_commit` → `project_commit` → `rebind` → `complete` → `cleanup`）。
- 每阶段先持久化 journal 再动作；崩溃后 `recover()` 幂等继续或显式回滚（列出待恢复产物，不静默丢弃）。
- SQLite 单事务提交新版本/run/binding/current 指针；工程文件经原子替换；两者不宣称单一 ACID。
- 验证：staged 路径存在、hash 匹配（提供时）、相对工程位置、id 安全性、base version 乐观锁、
  版本 id 不可变（重 id → `immutable_version`）。
- 原版本不覆盖：payload 落 `{stage}/{asset}/{version}/`，已存在即失败；不动 base payload。

## 8. CLI（退出码契约）

`pwb-inspect`：只读。`--project <file>`（必需）`--format json|text`（默认 json）。
退出码：0=正常；2=用法错误；3=工程不可读/损坏；4=future schema（仍输出诊断 JSON）；5=内部错误。

`pwb-migrate`：默认预检（`--check`，dry-run 报告）。实际转换必须 `--input`（副本）
+ `--output-dir`（输出目录，不得等于输入目录，拒绝覆盖真实工程）。退出码：0=完成/预检通过；
1=发现需迁移项（预检）；2=用法错误；3=IO/损坏；4=future schema；5=内部错误。

## 9. Python oracle runner

`tools/oracle/generate_fixtures.py`（在 B 归属 `tools/` 下、只读主仓解释器运行）：
构造代表性工程 + catalog → 保存到 fixture 目录；`dump_fixture.py`：读 fixture → 语义 dump（JSON）。
C++ 测试对同一 fixture 产出等价 dump，比较器做**语义比较**（对象键序无关；数组业务顺序保留；
数值按 JSON 数值等价 —— int/float 区分、`1.0` vs `1` 视为不同仅当类型不同；null/缺失键不等价）。
