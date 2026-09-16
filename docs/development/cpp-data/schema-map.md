# Schema Map — .paleo.json / catalog.sqlite / workspace（逐字段语义）

来源：`paleo_workbench/project/models.py`、`manager.py`、`paths.py`、`domain.py`、
`catalog/models.py`、`db.py`、`storage.py`、`mapping_workspace/stage_state.py`（基线 d0347da2）。
约定：**默认值** = 键缺失时的 Python 行为；**null 语义** = 显式 null 与缺失是否等价。

## 1. `.paleo.json` 顶层（ProjectDocument，extra="allow"）

序列化：UTF-8，`indent=2`，`ensure_ascii=False`，键序 = pydantic 字段序 + 未知键（保留原值）。

| 键 | 类型 | 默认/缺省 | null 语义 | 备注 |
|---|---|---|---|---|
| schema_version | int | 1 | 无 | >1 → 本线只读+诊断（future schema） |
| meta | ProjectMeta | 必填 | — | 见 §2 |
| coordinate | CoordinateReference | 全默认 | — | project_crs=""、crs_locked=false、target_crs 可 null、display_crs="EPSG:4326 / WGS84"、transform_history=[] |
| stratigraphy | StratigraphicFramework | 全默认 | — | target_horizon=""、sequence_boundaries=[]、systems_tract_scheme="LST/TST/HST"、interpretation_version="v1"、applicable_*=[] |
| facies_taxonomy | dict\|null | null | null=内置默认 | dict 载体原样 |
| workarea | WorkArea\|null | null | — | schema v2 内存迁移产物；见 §2 |
| wells / seismic_surveys / geological_entities / auxiliary_entities | list | [] | — | 域实体，见 §2 |
| entity_asset_links | list | [] | — | 见 §2 |
| resources | list[ResourceItem] | [] | — | **路径节**；见 §5 |
| well_tables | list | [] | — | rows 内浮点/null 原样（pass-through） |
| constraint_layers | list | [] | — | coordinates [[x,y],..] pass-through |
| map_products | list | [] | — | id/output_version_id/run_id/生命周期字段 |
| contour_drafts | list | [] | — | segments 坐标 pass-through |
| compilation_runs | list | [] | — | workflow_steps 枚举见 §6 |
| factor_map_tasks | list | [] | — | **路径节**（grid_artifact_path）；status 词表 pending/complete/failed；parameters 内联 grid_z 为 legacy |
| horizon_interpretations | list | [] | — | **路径节**（artifact_path） |
| correlation_interpretations / fault_interpretations | list | [] | — | 引用型 |
| prediction_tasks | list | [] | — | adapter_kind: mock/http/local |
| paleomap_documents | list | [] | — | **路径节**（reference_layers[].source_path）；facies/line/label/well_overlays/map_chrome dict pass-through |
| user_vector_layers | list | [] | — | features[].geometry/properties pass-through；geometry_kind: point/line/polygon |
| map_qgis_project_xml | str | "" | 无 null | QGS 呈现态信封，**原样字符串**（B 不解析） |
| workstation_reference_layers | list | [] | — | MapReferenceLayer 同构 |
| onboarding_report | dict | {} | — | dict 载体原样 |
| quality_reports | list | [] | — | rule_status/coverage dict |
| version_sets | list | [] | — | status: open/final/superseded |
| export_artifacts | list | [] | — | **路径节**（output_path） |
| joint_analysis | JointAnalysisState | 全默认 | — | 数值/bool/null 混合体原样 |
| geo3d_workspace | Geo3DWorkspaceState | 全默认 | — | **extra="allow"**：未知键保留 |
| mapping_workspace | dict | {} | — | 见 §4（B 类型化解析） |
| compilation_input_sets | list[dict] | [] | — | dict 载体原样（schema 由 workflow 拥有） |
| integrated_interpretations | list[dict] | [] | — | 同上 |
| interpretation_revisions | list[dict] | [] | — | 同上 |

**未知顶层键**：`extra="allow"` → 加载保留、保存原样写回（#1170）。加载时 log warning + 本线诊断。

## 2. 关键嵌套模型

**ProjectMeta**：name(必填)/region("")/version("0.2.17a0")/created_at/updated_at(ISO UTC，
`datetime.now(timezone.utc).isoformat()` — 微秒 6 位)/project_root(持久化恒 `"."`)/
last_recovery(dict|null，恢复事件记录：source/recovered_at/error/quarantined)。

**WorkArea**：id/name/description/boundary([[x,y],..])/boundary_crs/project_crs/display_crs/
vertical_datum/horizontal_units/vertical_units/metadata{}/created_at("")/updated_at("")。

**WellEntity**：id/name(必填)/uwi("")/aliases[]/surface_[xyz](float|null)/source_crs("")/
project_[xy](float|null)/coordinate_status("missing" 词表)/kb/td(float|null)/status("active")/
spatial_scope("workarea"|"reference")/tags[]/metadata{}/created_at("")/updated_at("")。

**SeismicSurveyEntity**：id/name(必填)/survey_type("3d"|"2d")/crs("")/extent[]/
inline_range/crossline_range([start,stop,step])/n_samples(int|null)/dt_ms(float|null)/metadata{}/时间戳。

**DomainEntity**：id/kind("geological"|"auxiliary")/name(必填)/entity_kind("")/description("")/metadata{}/时间戳。

**EntityAssetLink**：id/entity_type("well"|"seismic_survey")/entity_id/asset_id/role("other")/
is_primary(false)/unresolved(false)/note("")/metadata{}/created_at("")。

**ResourceItem**：id("res_"+hex12)/name(必填)/path(必填，**路径节**)/type/format(必填，"")/
crs(null)/status("indexed")/tags[]/source("local")/parsed_summary{}/checksum(null)/
external(false，relativize 派生)/artifact_role(null)。

**UserVectorLayer/UserVectorFeature**：id/name("编修图层")/geometry_kind/template("")/crs("")/
style{}/field_schema{}/features[]/visible(true)/opacity(1.0)；feature: id(必填)/geometry{}/properties{}。

**MapProductRecord**：id/product_name(必填)/factor_task_ids[]/interpretation_refs[]/
composition_ref(null)/notes("")/output_version_id("")/run_id("")/scientific_fingerprint("")/
created_at/status("final"|"superseded")/frozen(false)/superseded_by(null)/cloned_from(null)/
lifecycle("draft"|"reviewed"|"frozen"|"published"|"superseded")/product_qa{}/manual_adjustments[]/
fusion_version_id("")/integrated_interpretation_id("")/input_set_id("")。

## 3. 路径语义（§5 所引）

- `project_dir_for(p)` = `expanduser().resolve().parent`。
- 保存 relativize：绝对→resolve 后 `relative_to(project_dir)` 成功则 POSIX 相对 + external=false；
  失败则绝对 POSIX + external=true。相对输入先 `project_dir / cand` 再 resolve。
- 加载 resolve：绝对→原样 resolve POSIX；相对→`project_dir/cand` resolve 后**必须在 project_dir 内**
  （`..` 逃逸 → ProjectPathError 诊断，Python 抛异常；本线记录诊断且该资源标丢失）。
- Windows 盘符/UNC/正斜杠：POSIX 化统一 `as_posix()`；Unicode 原样（UTF-8）。
- `map_qgis_project_xml` 不参与路径处理。

## 4. mapping_workspace（dict，schema_version=1）

| 键 | 类型 | 语义 |
|---|---|---|
| schema_version | int | 默认 1 |
| current_stage | str | 词表 `facies_calibration`/`constraint_factor`/`integrated_compilation`（stages.py STAGE_ORDER）；未知→回落 facies_calibration |
| stage_states | dict[stage→StageViewState] | 仅 STAGE_ORDER 内的 stage 被加载；每 state 8 键：stage/group_visibility{gid→bool\|null}/group_locked/layer_visibility{lid→bool\|null}/layer_opacity{lid→float}（null 项**写回时剔除**）/active_layer_id(str\|null)/active_tool(str\|null)/customized(bool) |
| memberships | dict[layer_id→record] | 10 键：layer_id/role(33 角色词表，未知→legacy_unclassified)/factor_task_id/constraint_kind(词表外→"")/created_stage/source_version_id/created_at/source_asset_id/binding_kind(catalog_version\|content_fingerprint\|""=UNKNOWN)/bound_at；全部 str，缺失→"" |
| tree | dict | 原样 pass-through（QGS 运行态序） |
| artifact_maturity | dict[key→str] | 词表 draft/reviewed/frozen/published；**词表外的项加载时丢弃**（Python from_dict 行为） |
| compilation_input_set | dict[str→str] | 值强转 str |

## 5. catalog.sqlite（STORE_SCHEMA_VERSION=5，canonical）

`PRAGMA journal_mode=WAL; busy_timeout=5000`。无外键（投影设计）。所有时间戳 TEXT ISO。

| 表 | 列（类型） | 备注 |
|---|---|---|
| assets | id PK, name, name_search(NFKC+casefold), type('unknown'), description(''), current_version_id(null), legacy_resource_id(null), metadata(JSON '{}'), created_at(''), updated_at(''), trashed(0), trashed_at(null) | |
| versions | id PK, asset_id, version_number, stage, managed(1), path(''), source_uri(null), format(''), size_bytes(null), sha256(null), run_id(null), metadata('{}'), created_at(''), trashed(0), trashed_at(null), parent_ids(JSON '[]') | members 不在此表 |
| tags | id PK, name UNIQUE, display_name(null), metadata('{}') | |
| asset_tags / version_tags | (asset_id\|version_id, tag_id) PK | |
| runs | id PK, operation, parameters('{}'), generator(''), status('completed'), model_ref(JSON null), created_at('') | status 词表含 running/failed/completed/cancelled |
| run_inputs / run_outputs | (run_id, version_id) PK | |
| lineage | (parent_version_id, child_version_id) PK | 派生自 versions.parent_ids |
| models / model_versions | 见 db.py | 注册表 |
| sync_state | key PK, value | schema_version=1 / index_schema_version=5 / catalog_revision(int) / manifest_mtime_ns |
| staging_leases | (lease_id, target) PK, kind('register'), acquired_at, heartbeat_at | 瞬态 |
| working_copies | working_id PK, source_version_id, path UNIQUE, state('checked_out'), display_name(''), created_at, updated_at, payload_mtime_ns(null), source_size_bytes(null) | 状态机 checked_out/dirty/committing/committed/abandoned |
| run_ports | (run_id, direction, version_id, role, ordinal) PK, required(1), entity_type(''), entity_id(''), note('') | direction: input/output；ports ⊆ flat 列表 |
| version_members | (version_id, name) PK, rel_path, member_role(''), ordinal(0), required(1), sha256(null), size_bytes(null) | bundle；聚合 hash = sha256("rel_path:sha256\n"…) 按 (ordinal,name) 序 |

**读侧约束**：`index_schema_version` 严格可读且 ≥5 才接受为 canonical store；不满足 →
`corrupt_database`/`future_schema` 诊断（Python 行为：拒用并按 legacy 处理/报错，不静默重建）。
**checkpoint**：`catalog.json`（+`.bak`）为导出清单；字段 = CatalogDocument 模型（schema_version=1,
catalog_revision, assets/versions/runs/tags/models/model_versions/asset_tags/version_tags）。

## 6. 枚举/null/数值规则汇总

- DataStage：`raw|derived|intermediate|output`（版本列存储小写字符串；未知值 → 诊断 + 拒绝写入，读取时保留原值并诊断）。
- run.status：开放词表，写侧本线只用 completed/failed/running（manual_edit 协议）。
- float|null：pydantic Optional 区分 null 与缺失（等价：默认即 None）；JSON 数值原样精度（double）。
- int vs float：`1` 与 `1.0` 序列化不同（pydantic 按字段类型）——比较器按类型敏感处理。
- bool：0/1 存 SQLite；JSON true/false。
- 数组业务顺序：memberships/stage_states 是 dict（键序无关，比较器对象语义）；
  versions/runs/features/rows 等数组顺序**必须保留**。

## 7. 层级矩阵（unknown-field round-trip 范围）

| 层级 | Python 行为 | C++ 本线行为 |
|---|---|---|
| 文档顶层 | extra=allow 保留 | 类型化 + extra 保留 |
| Geo3DWorkspaceState | extra=allow | 同 |
| mapping_workspace 嵌套 dict | dataclass from_dict 容忍缺键；**未知键丢弃**（to_dict 固定键集） | 已知键类型化；未知键保留于 extra 并写回（**严格于 Python**——不丢用户数据；差异已记录） |
| ProjectMeta 等普通 pydantic 模型 | 未知键忽略丢弃 | 与 Python 一齐丢弃？**否**——保留于 extra 并写回（见下） |
| metadata/properties/display 等 dict 载体 | 原样 | 原样 |

> 决策：C++ 兼容层对所有嵌套层级保留未知键（load→save 无损），这**超集**于 Python 行为
> （Python 在非 extra 层会丢弃）。理由：B 的验收要求“未知字段在任意可扩展层级 round-trip 保留”，
> 且写回保留不会破坏 Python 读取（pydantic ignore 未知键）。schema-map 如实记录两侧行为差异。
