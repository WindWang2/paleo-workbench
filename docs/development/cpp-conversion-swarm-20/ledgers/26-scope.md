# CONV-26 — Data / Workspace / Catalog / Project lifecycle closure（scope ledger）

- 分支：`feat/cpp-data-workspace-catalog-closure`
- Worktree：`/home/kevin/project/worktrees/cpp-data-workspace-catalog-closure`
- BASE：`origin/main` @ `ff67dcf3`
- 日期：2026-09-18

## 本分支负责

以现有 CPP-B 数据内核（`libs/{domain,project,workspace,catalog,data_suite}`，CONV-15/19 已交付
GC/dedup/分页/ingest 解析器）为基础，补齐数据主线闭环中仍缺失的业务面，使 C++ 产品
不依赖 Python runtime 即可完成：

1. **SQL 级稳定分页**（A/E）：`CatalogRepository` 增加 db.py `_search_assets_page` /
   `_count_assets` 对应的 SQLite 直查路径（索引序 + keyset cursor + 两步 current-version
   批取），大数据量下不再全量加载 `CatalogDocument`。oracle 冻结对账。
2. **Ingest 编排**（D/F）：移植 `paleo_workbench/resources/ingest_plan.py` 两阶段语义——
   `build_ingest_plan`（纯：扫描/shapefile 族组/分类/身份提议/重复检测/primary 提议）与
   `execute_ingest_plan`（分块事务、取消、错误汇总、幂等重跑=中断导入恢复契约）。
   需随迁最小依赖面：`infer_role_for_type`（roles.py）、`resolve_well` 身份链
   （project/domain.py 的确定性解析）、`upsert_entity_asset_link`（单 primary 不变量）。
3. **import_raw 注册面**（A）：managed RAW 拷贝入库 + CAS blob 复用（复用 CONV-15
   `dedup.hpp`，不复制第二份算法）。
4. **Project save-as**（C）：`stage_artifact_relocation`/`relocate_artifacts`/
   `rebase_owned_artifact_path` 移植（copy-then-delete 可逆迁移、目标 artifacts 已存在则
   拒绝），挂到 `ProjectManager` save-as 语义。
5. **Workspace membership 写 API**（B）：`MappingWorkspaceState` 之上的
   add/remove/rebind（pinned version 切换）与 stale 引用修复（悬挂 version → current）。
6. **E2E 验收**：`create project → 目录导入 → versions/runs → workspace membership →
   save/save-as → reopen → SQL 分页 → provenance audit` 全链 C++ 自跑测试。
7. **十万级元数据 sanity**（E）：direct-seed 10 万级 assets/versions 元数据，验证 SQL
   分页/open/audit 路径有界（确定性 perf sanity，不是 benchmark）。

## 明确不负责

- UI 表格/图层交互（QGIS/UI 分支）；
- Workflow stale/recompute（Workflow 分支，含 `cpp-workflow-runtime-closure` worktree）；
- Prediction 推理（Prediction 分支）；
- packaging / 集成安装器（Product/Build 分支）；
- 100G 地震体全量压测（按总原则明确排除；用小 fixture / synthetic 数据）；
- LAS/geotiff/excel 真实解析引擎（CONV-19 已冻结"依赖缺失回退"为长期语义，本片沿用：
  井名 header 提取走 fallback 链 = directory hint，与 Python 引擎缺失时行为一致）；
- `EntityViewService` wells/surveys UI 装配（CONV-15 D2 已声明不做，不伪造）；
- NFKC+casefold 全量 Unicode 检索归一化（CONV-15 D6 边界维持）；
- models/model_versions 注册表读模型、staging_leases 写路径（v3-handoff §5 遗留，
  若本片余量允许再评估，默认不做）。

## 与其他并行方向的边界

- `cpp-workflow-runtime-closure`（workflow 运行时）：其消费本片的 repository 接口契约；
  本片不改 `libs/workflow*` 任何文件。
- 根 `CMakeLists.txt` 仅做纯追加 CONV-26 option 块 + 给既有 CONV-19 add_subdirectory 加
  `if(NOT TARGET pwb_ingest)` 守卫（CONV-11 已有同型先例），不影响其他分支默认配置。
- `libs/ingest` 只读复用（classifier/io_registry 表），不修改其语义；如需新增纯函数
  放在 data_suite 侧。
- `.goal-loop-ledger.md` 追加一节，不重排既有内容。

## 验收口径

- 本地（resource gate 之内）configure/build/ctest 全绿 ×2；
- oracle 对账：ingest 计划 + SQL 分页两套冻结 fixture，含 tamper 负向检查；
- E2E 测试在纯 C++ 环境跑通（无 Python runtime 参与运行时路径）；
- 三轮 review（正确性/架构/闭环）+ 修复复读。
