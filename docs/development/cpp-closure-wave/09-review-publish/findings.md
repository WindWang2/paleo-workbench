# 09 — findings

## R1 盘点（基线 06211541）

### 缺陷点（本线要替换的）

- `apps/paleo_workbench_platform/app_shell.cpp:196-198`：ReviewExportPage 的
  IReviewActions provider 是 `[](){ return nullptr; }` — 页面永远渲染“未绑定工程”守卫。
- `apps/paleo_workbench_platform/main_window.cpp`：
  `save_project_requested` 无生产处理器（代码注释明确“Deferred request surfaces …
  never silently faked”）。原生 app 打开工程后**没有任何**把 ProjectDocument 落盘的路径
  （唯一 save 是 openProjectDialog 新建工程 bootstrap，main_window.cpp:971）。
  → 本线认领该共享保存缺陷：`PwbDataStore::save_document()`（函数租约已登记），
  否则 QC 报告/定稿/导出登记无法“重开可追溯”。

### 现有可复用面（已实现/已 wired，非“未实现”）

- `libs/ui_review`：页面壳、IReviewActions 接口、flow texts、QC issue rows、
  result summary 全部已在（UI-11）；缺的只是后端绑定。
- `libs/project`：ProjectDocument 是 JSON 树（root()），schema.cpp:490-529 已物化
  paleomap_documents/quality_reports/version_sets/compilation_runs/well_tables/
  contour_drafts/export_artifacts 等全部 section；ProjectManager 三阶段原子保存 +
  stale-write guard（disk_sha256 基线，nullopt 时跳过）+ read_only 守卫。
- `libs/application` PwbDataStore：持有 live document() 与 project_file()；
  openProject 成功路径 main_window.cpp:1042-1060（context_.setProjectStore(store)）。
  manager 为 private Impl 成员 — 第二个 ProjectManager 实例会破坏 01 线的
  stale-write 基线不变量（之后 store 侧保存将被拒），所以保存必须走 store 自身的
  manager → save_document() 加在 PwbDataStore 上是唯一正确位置。
- `libs/ui_data_core`：`validate_ring(MapRing) → [{"code","message","edges"}]`
  （map_edit_geometry.hpp:83）= geoviz.validate_ring 对等面，含 self_intersection 码。
- `libs/mapping_kernel`：`ring_centroid`（面积质心 + 退化兜底，V8 M4 语义，
  polygonization.hpp:58）= Python geometry_operations.centroid 对等面。
- `AppShell::review_page()` 访问器已存在（app_shell.hpp:129）→ installer 无需改
  app_shell.{hpp,cpp}；ReviewExportPage 需 additive `set_actions_provider`（本线文件）。
- workflow_controller（UI-14）已有 `update_review_export_page` fan-out seam 与
  WorkflowServiceApi.active_quality_reports 注入位 — 本线后端可直接供能。

### Python 冻结参考（语义权威，本轮逐行核对）

- `paleo_workbench/workflow/qc.py`：BASIC_QC_RULES 六规则、make_issue 空间字段
  （feature_id/feature_kind/geometry/centroid/ref）、_geometry_centroid fail-closed→
  顶点均值兜底→fail-open、_status_from_issues（error/critical>warning>pass）、
  run_basic_qc upsert-by-linked_map_document_id（稳定 id）、active-run 绑定
  （compilation_runs[-1]）、rule_status 全 evaluated + coverage{evaluated,skipped}。
- `paleo_workbench/workflow/map_qa_rules.py`：EXTENDED_QC_RULES 十规则 +
  extended_rule_coverage（out_of_bound/low_confidence/export_fallback 缺输入时
  evaluated=false + reason）。
- `paleo_workbench/workflow/versioning.py`：finalize 守卫（is_demo_draft →
  “演示草稿不能专家定稿”；production==False 且 lineage==untracked → lineage 拒绝；
  非 production 拒绝）、require_qc_pass、supersede 同层位 final、
  _version_set_for_horizon（open→final）、build_snapshot（fingerprint=
  sha256(stable_json)[:16]）、contour_draft→final、run 状态机 →export_ready、
  catalog DataRun best-effort（失败不影响 finalize 本身）。
- `paleo_workbench/workflow/qc_report_export.py`：_json_safe（非有限→null）、
  atomic_output + 写后 parse 验证、register→record_export（ExportArtifact:
  linked_id=map_doc_id||report.id, format="qc_json", source_task_ids=[report.id]）。
- `resources/export_service.py::default_export_dir`：project_path None →
  ~/paleo_exports；否则 ensure_artifact_layout/<project_dir>/exports mkdir。

### 容差/差异记录（oracle 说明）

- fingerprint：Python 用 json.dumps(sort_keys)+sha256[:16]；C++ 用 domain::Json
  （对象键有序）canonical dump + SHA-256[:16]。**不承诺跨语言字节一致**，验收约束是：
  同内容→同指纹、内容变化→指纹变化（测试断言此性质）。
- centroid：Python 面积质心失败回退顶点均值，畸形→None；C++ mapping_kernel
  ring_centroid 同语义（含 isclose(area2,0) 兜底）。

### 协作边界核对

- 02 线 interfaces_provided “closure_workflow typed facade for 03/08/09” — 软依赖。
  本线 workflow/qc.py+versioning.py 语义先行自持；02 facade 合流后可切换内部实现，
  接口（IReviewActions/closure_review 核）不变。
- 04 线已占用 main_window.cpp 的 BEGIN/END CLOSURE-PREVIEW 块与 app_shell 两函数租约 —
  本线使用独立 BEGIN/END CLOSURE-REVIEW 块，不触碰其块。
- 12 线拥有 AppShell/AppContext 组合 — 本线零改动 app_shell.*，main_window.cpp
  仅命名块三处（include/install/notify）。
- git worktree list 核对：13 条线 worktree 已注册，09 未占用 →
  codex/cpp-close-09-review-publish-20260920 + cpp-close-09-review-publish 新建成功。
