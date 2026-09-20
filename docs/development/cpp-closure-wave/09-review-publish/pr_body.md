# 09 — 审核治理、质量规则与可验证发布（closure_review）

Base: `06211541` (origin/main at branch point) · Branch: `codex/cpp-close-09-review-publish-20260920` · Wave coordination: `.git/codex-coordination/cpp-close-wave/09-line.json` (outside repo) · Line ledger: `docs/development/cpp-closure-wave/09-review-publish/`

## 用户可见流程前后变化

之前：成图审核页（hub 3 → 成图审核）的四个动作（运行质检 / 规则 / 导出 / 专家定稿）全部命中 `未绑定工程` 守卫——`app_shell.cpp` 的 `IReviewActions` provider 恒返回 `nullptr`；原生 app 也没有任何把工程文档落盘的路径。

之后（打开工程后进入成图审核页）：

1. **预检**：「运行质检」对工程中每幅古地理图执行 6 条基本规则 + 10 条扩展规则 + 编图侧几何委托，报告按图 upsert（稳定 id，重跑不虚增），并绑定活动编译运行；
2. **定位问题**：每个问题带 `feature_id/feature_kind/ref`，几何问题带 GeoJSON `geometry` + 质心定位点（面积质心，退化面顶点均值兜底）——质检表的空间过滤即"定位"；
3. **修复再检**：修复后重跑，报告按图替换（同 id），coverage/rule_status 诚实记录每条规则 evaluated/skipped 及原因；
4. **发布/导出**：「导出」把质检报告原子写入 `<project>.artifacts/exports/`（临时文件 + fsync + 回读 parse 验证 + rename），并登记 `export_artifacts`；「专家定稿」执行守卫（演示草稿/lineage 未登记/非生产拒绝，可选 QC 通过门）→ 同层位旧 final 替代为 superseded → 新 VersionSet + 指纹快照 → 等值线草稿置 final → 编译运行推进 export_ready；每步变更经 `PwbDataStore::save_document()` 落盘，**保存失败 = 动作失败**（短写/磁盘满绝不产生成功回执）；
5. **来源追溯**：重开工程后 quality_reports / version_sets（含快照与指纹）/ export_artifacts 全部可见。

未绑定工程时页面保持明确的「未绑定工程」守卫，不产 mock 数据。

## 范围

- **新增 `libs/closure_review`**：Qt-free QC/定稿/导出核（`workflow/qc.py`、`map_qa_rules.py`、`versioning.py`、`qc_report_export.py`、`paths.py::artifact_dir_for` 的语义移植；几何自交校验复用 `ui_data_core::validate_ring`，质心复用 `mapping_kernel::ring_centroid/signed_area`）+ `ProjectReviewActions` 后端 + headless 测试。
- **新增 `apps/paleo_workbench_platform/closure_review_install.{hpp,cpp}`**：installer；`main_window.cpp` 仅三处 BEGIN/END CLOSURE-REVIEW 命名块（include / 装配 / openProject 成功尾部 notify），**app_shell.cpp 零改动**。
- **`PwbDataStore::save_document()`（additive，函数租约已在协调登记）**：原生 app 首个文档级持久化 seam——必须走 store 自身 ProjectManager 以维持 stale-write 基线不变量。
- **`ReviewExportPage::set_actions_provider`（additive inline）**：迟绑定 provider。
- 不拥有：通用 interchange 格式核（10）、工作流 QC 编排数值核（02）、编图完整规则集（08，经 `CartographicQaDelegate` seam 接入）。

## 依赖 PR

- 无硬依赖。02 线 `closure_workflow` facade 合流后可替换内部实现，本线接口不变；catalog DataRun 登记面落地后翻转 `provenance_registered`（当前诚实为 false）。

## 测试（基线 06211541 → head 97c7ae42+，SHA 见下方各命令）

- `closure_review.core_test`（headless）：有错/无错工程 QC 可解释性、自交定位、CRS/样式规则、活动报告选择、越界+coverage 语义、导出成功/失败两路、定稿守卫/替代/指纹、后端闭环、保存失败非成功回执、未绑定诚实态；
- `ui_review.core_smoke` / `ui_review.qt_widgets_smoke`：回归（additive setter 不改既有行为）；
- `platform.closure_review_install`：真实 MainWindow + 真实 typical fixture 工程——装配、页面状态来自真实文档、save_document、重开可追溯；
- 关键确定性回归两遍；全量产品矩阵由 12 线在集成候选上统一执行（上方命令可重放）。

## 资源约束

- 全部 configure/build/test 经 `scripts/cpp-migration/invoke-resource-gate.sh`（common-dir flock、j≤2、8GiB 内存门）；与他线竞争时 90s 退避排队，未抢锁、未删锁。
- 工具链：`/home/kevin/pwb-sdks/root/usr/bin`（需 `LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib`）。

## 已知限制（真实限制，不掩盖）

- **catalog 溯源登记**：qc / version_finalize 的 catalog DataRun 注册面未在本线落地，报告 `provenance_registered=false` 诚实记录；目录侧重跑登记合流后翻转。
- **编图侧规则集**：完整 §14 cartographic QA 归 08 线；本线交付委托 seam + 真实几何默认委托（未闭合环/重复顶点/退化面），更丰富规则集经同一 seam 接入，未绑定时 coverage 记 skipped+原因（`cartographic_side_checks` 键为本线扩展）。
- **Python 流程兼容**：未删除任何 Python 参考代码；C++ 生产路径无解释器/subprocess/静默 fallback。
- `ui/pages/review_export_page.py` 对照的 `review_export_page.cpp` 既有"未绑定导出仍提示完成"缺陷（UI-11 范围、当前接线不可达）已在 ledger 记录，未在本线 churn。
