# CONV-26 — Findings（逐移植面笔记）

对照 Python 真源逐面记录；决策见 26-decisions.md，验收见 26-pr.md。

## SQL 分页（libs/catalog/paged_sql.*）

- Python 真源：`db.py _paged_predicates / _search_assets_page / _count_assets`。
  分页 SELECT 默认不 join（join 破坏 assets 索引序）；stage/size/version 序键定向
  LEFT JOIN；current_* 列以 100-id IN 批按主键补取；keyset `(name,id)` 仅 name 序；
  LIKE 经 `like_escape_literal` 转义 + `name_search` 有界折叠写入侧对齐；
  asset_ids 500-chunk IN；limit/offset 钳非负。逐片段等值（Review A 区域核查 CLEAN）。
- 行形状复用 entity_view 的 20-key `asset_page_row`，SQL 路径与文档路径 key-for-key
  一致（data.paged_sql 双路径互证 + keyset 深分页遍历=整页）。
- 行映射收敛到 `src/row_mapping.hpp`（repository/paged_sql 共用，schema 列变更单点）。

## 身份层（libs/data_suite/entity_identity.*）

- 真源：`project/domain.py`（normalize_well_name / WellRegistry / SurveyRegistry /
  resolve_well / upsert_entity_asset_link / asset_ids_for_entity）、`project/roles.py`
  （infer_role_for_type + ROLE_DEFINITIONS 声明序 format-hints 循环，trajectory 对
  泛型表格后缀的让位守卫）。
- `WellRegistry`：deque 存储（指针稳定）+ move-only（拷贝会悬空索引，显式删除）；
  by_key 对歧义键返回 null；find_all_by_name 插入序。
- resolve_well 链序 persisted_id→uwi→唯一规范名（alias 判定含退化空串对）→歧义
  （不静默合并）→显式映射（workarea.metadata 覆盖）。
- 边界：D2 的有界折叠；井名 header 提取冻结回退（D1）。

## ingest 计划纯核（libs/data_suite/ingest_plan.*）

- 真源：`resources/ingest_plan.py build_ingest_plan`。候选过滤（`._` 前缀、空文件）、
  shapefile 族组跑在**未过滤**集上（sidecar 整族收养）、preferred 过滤（族成员优先）、
  part-wise 路径序（rglob 排序 = PurePath 分量序，非字节序——primary 选择依赖项序，
  属契约）、分类复用 CONV-19 `classify_import_path`（.xml 有界嗅探，上限 16 MiB——
  Python 侧提取器本身有界）、256 MiB 哈希上限、身份提议分支（含各 confidence 档）、
  重复检测三索引（identity/external/sha；Python 的 path_index 为从未填充的死分支，
  不移植并在此声明）、primary 提议（seen 键集 + 实体现有绑定判空）。
- `to_dict` 投影：路径以原始 generic 串输出（Python `str(Path)`）；仅重复检测处显式
  resolve（与 Python 一致）。

## ingest 执行（libs/data_suite/ingest_exec.*）+ import_raw

- 真源：`execute_ingest_plan / _bind_plan_items / bind_well_extracts /
  bind_survey_extract / _ensure_survey / _ensure_geological`、`service.py import_raw`
  （place_managed_file CAS 去重 + 单事务落库 + 失败回滚暂存目录；共享 blob 不动）。
- 决策过滤（确认模式/execute_unconfirmed）、逐项幂等 (source,sha) 对（as_new_version
  有意绕过）、skip-with-reference、井绑定按 (scope,role) 插入序分组、组内 known-id
  链接先行 + 两遍解析（A 组内有界注册表建/盖戳；B 全量注册表链接，组内单一注册表——
  V6 §6 不逐条重建）、调查/地质实体字段集与 `_stamp` 对齐、primary 提升。
- 事务粒度 D3；`CatalogRepository::import_raw_transaction` 为无 run 的 asset+version+
  current 指针复合事务。
- 顺带修复既有缺陷：`open_read_write` 先建父目录再 sqlite Create 打开（此前新项目
  必须由调用方预建 artifacts 布局）。

## save-as 迁移（libs/project/relocation.* + libs/data_suite/save_as.*）

- 真源：`paths.py`（StagedArtifactRelocation/stage/commit/rollback/relocate/
  rebase_owned_artifact_path）+ `ui/project_controller.save_project_as`（占用目标
  拒绝——目标 artifacts 目录存在即拒；同路径=普通保存；先暂存→文档改写→**暂存
  catalog 改写**→新路径落盘→commit/rollback；失败反向恢复文档+重开旧 catalog）。
- `rebase_artifact_paths`（repository.cpp）：托管版本路径首段改写 + trash.
  original_path + model_versions.artifact_uri（收集后再更新，不边扫边写）；
  `.artifacts` 裸名按 Python endswith 语义接受。
- 失败恢复与句柄时序见 D6。

## workspace 写面（libs/workspace/mutations.*）

- membership upsert/remove（remove 同时清除各级 stage-state 的可见性/透明度/激活层
  覆盖——Python drop_membership）；rebind 写时 kind 强制（D7）；
  repair_stale_bindings 为 C++ 新面（Python 无直接对应）：悬挂 pin → 资产 current /
  未知，绝不删成员。

## 测试与 oracle

- `data.paged_sql`：冻结 paged_queries 矩阵回放（31 查询，含 keyset/钳位/谓词组合）
  + 双路径互证。
- `data.ingest_plan`：9 文件场景（井×2/重复/族组/调查/角色链）——纯计划逐字段、
  执行报告、SQL 分页、links/实体树、负载布局、幂等重跑全对账；取消/恢复行为测试。
- `data.lifecycle_ops`：暂存提交/回滚、改写矩阵、save-as 重开（catalog 改写+载荷
  可达）、占用拒绝、成员变更修复往返（含覆盖清除）。
- `data.lifecycle_e2e`：验收环（见 26-pr.md）。
- `data.metadata_scale`：12 万元数据 direct-seed；首页 ~1ms / 深 offset 页 ~7ms /
  count ~4ms / keyset 全程 ~8.6s / 全文档装载 ~0.36s（本机级天花板，确定性 sanity）。
- 确定性：生成器双跑 sha256 相等（D4）；fixture 无绝对路径（D5）。

## Review 记录（三轮，全部子代理只读 + 自动修复复验）

- A（语义保真）：12 发现——P2×1（save-as 失败文档悬挂）修复；P3×11 中修复 8
  （stage 覆盖清除、时间戳诚实化、kind 写时强制、asset_ids 去重、别名空串边、
  `.artifacts` 裸名、井盖戳、目录迭代异常协议），3 项归档为 D2/D9 边界声明。
- B（架构）：12 发现——P2×3（死守卫、commit 忽略+活句柄、文档悬挂）修复；P3×9
  中修复 7（边扫边写、空 if、抛异常的 exists、未用变量、拷贝陷阱、注册表重建、
  决策文档缺失），P3×2（Pwb::Ingest PUBLIC→PRIVATE、行映射去重）同批修复。
- C（闭环）：8 发现——P2×2（fixture 路径依赖、决策文档缺失）修复；P3×6 中修复/
  补声明 5（goal-loop 追加、本地门禁锁、助手去重、死守卫、model_versions 记入
  ledger），XML 无界读修复（16 MiB 上限）。
- 修复后全套 27/27 ×2 绿。
