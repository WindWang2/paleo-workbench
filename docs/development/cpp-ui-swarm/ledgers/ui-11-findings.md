# UI-11 findings — qt-review-gov（15 Python 源 → 12 核 + 13 壳 + 1 原型）

Branch: `feat/cpp-qt-review-gov`（base origin/main，合并至 55881f9d）。
Worktree: `../worktrees/cpp-qt-review-gov`。切片 UI-11 of the M10 UI→C++
migration：评审/治理簇 —— 质检评审导出页、治理元数据、目录健康检查、
血缘浏览器、影响预览、版本工作台、导入计划、重链接、AI 检查顾问、
QC 问题表、工作流合同面板、综合编修原型（非生产）。所有目录/工程/QC
服务调用走注入 seam —— widget 不直接碰 catalog/project 服务；
语义核全部 Qt-free。

**UI-09 复用声明**：`task_panel_base.py`、`prediction_evidence_panel.py`
（及其 `prediction_task_panel.py` 特化）**不在本切片移植** —— UI-09 已
在 `pwb::ui_wellseis::qt`（`Pwb::UiWellseisQt`）交付 `TaskPanelBase` /
`PredictionTaskPanel` / `PredictionEvidencePanel`，宿主直接复用，无
第二拷贝。集成片决定归并。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `pages/review_export_page.py` | 评审导出页：ActionHeader 四动作编排（运行 QC/规则/导出/定稿）、`qc_<doc|report>.json` 文件名、`docs[-1]` 兜底定稿目标、完成文案（名称/版本/快照数）、内置规则文案、project-bound 门 | `review_core`（Qt-free：report filename/finalize target/done+config+run-done texts）+ `qt/review_export_page`（壳 + `IReviewActions` seam + dock/float 面板）+ `qt/result_summary_panel` + `qt/qc_issue_table`（共用） | ported |
| `pages/governance_dialog.py` | 治理元数据对话框：patch 构造（creator/approver/review_round/tags 等可空字段只写入非空）、编辑后校验 | `qt/governance_dialog`（壳；`patch()` 返回 `Result<Json>`） | ported |
| `pages/catalog_health_dialog.py` | 数据健康检查：audit 统计行（资产/版本/运行/标签 + 高/中/低问题数）、severity 排序（高>中>低）+ 中文标签、健康/警告 verdict 文案、深度/普通 busy 文案、worker-backed audit | `audit_summary`（Qt-free：sorted/severity label+token/summary line/verdict/busy）+ `qt/catalog_health_dialog`（JobOwner worker seam） | ported |
| `pages/lineage_explorer_dialog.py` | 懒加载血缘树：单 hop 扩展（绝不走全链）、OUTPUT→⚙Run→INPUT 交织、`version.parent_version_ids` 驱动 + resolved parents 配对、↺ 循环引用先查、⚠ 断链红行、`MAX_CHILDREN_PER_NODE=200` 溢出「…还有 N 个」、无上游/无下游终态注、current 行 `kind="version"`/`■ 当前:`、分支行 ⬆/⬇、summary/run 卡片文案、expand-RAW 深度/节点上限状态 | `lineage_expand`（Qt-free：expand_inputs/outputs、version_item_label、current/branch spec、summary/run card、expand_raw 状态）+ `qt/lineage_explorer_dialog`（QTreeWidget 懒展开 + `ICatalogApi`） | ported |
| `pages/impact_preview_dialog.py` | 删除影响预览：逐资产 `delete_impact` 收集（live_descendants/runs/linked/broken_edges/advice/map usages）、各 20/5/30 截取上限、**fail-closed**（计算异常计入 computation_errors 且仍强制下游确认契约）、markdown 分节渲染 | `impact_markdown`（`TrashImpactSummary::collect_trash_impact` + `render_markdown`）+ `qt/impact_preview_dialog`（壳） | ported |
| `pages/version_workbench_dialog.py` | 版本工作台：timeline 阶段 cell（`_STAGE_DISPLAY` 英文 token，trashed→已删除）、校验和/短 id 截 12、`v4（当前）` 标记、`共 N 个版本`/`name · type · 当前 vX`、详情块（父版本/生成 Run/记录路径/解析位置+缺失）、meta sorted-json、动作门（单选未删→promote+trash+open、已删→restore、双选→compare）、双版本字段 diff + sorted 元数据并集 | `version_view`（Qt-free：stage/checksum/short_id/value/json_text/cell/header/count/detail/gates/compare_rows/compare_title）+ `qt/version_workbench_dialog`（QTableView + `ICatalogApi`） | ported |
| `pages/ingest_plan_dialog.py` | 导入计划：决策列/状态/备注/实体列文案（重复 `⚠ 重复: asset[:10]`、待确认 `? 待确认`）、accept_all 跳过重复项、skip_unresolved 标记 ambiguous、汇总 `共 N 个数据项`、detail 面板逐项编辑 | `ingest_columns`（Qt-free：decision labels/status/note/entity display、accept_all/skip_unresolved/unresolved_skipped/summary）+ `qt/ingest_plan_dialog`（`IngestDialogHooks`：wells/surveys/build/execute 全注入） | ported |
| `pages/relink_dialog.py` | 缺失源重链接：行状态（relinkable→可重链接 / managed→需重新导入 / else→不支持重链接）、扫描汇总 `共扫描 N 个版本，缺失 M 个，其中可重链接（外部 RAW）K 个`、结果 `成功重链接 N 个，拒绝 M 个（…）` 截 8 + `… 共 X 条`（cancelled 不进文案）、身份证明失败即拒、worker-backed scan/relink | `relink_summary`（Qt-free：entry status/scan summary/result message）+ `qt/relink_dialog`（`ICatalogApi` + cancel_event seam） | ported |
| `pages/ai_check_advisor_dialog.py` | AI 检查顾问：BH/断层双报告 → HTML（summary + issues 列表） | `advisor_html`（Qt-free：`build_advisor_html`）+ `qt/ai_check_advisor_dialog`（QTextBrowser 壳） | ported |
| `pages/qc_issue_table.py` | QC 问题表：**行=rule**（非 issue）、spatial_issues 过滤（`geometry`/`centroid` truthy —— 空 dict 不算）、按 rule 分组、定位列 `feature_id or ref or "可定位"` + `(+N)`、结果列 derive_rule_result + 颜色 token | `qc_issue_rows`（Qt-free：rows/spatial_issues_of/by_rule + Python truthiness）+ `qt/qc_issue_table`（壳） | ported |
| `pages/workflow_contract_panel.py` | 工作流合同面板：未知合同 → 单行 warn `未知模块：<id>`、功能/实现状态/当前状态（未绑定工程）/输入/操作（序号+软件行）/参数/输出/上下游（、连接）/QC/待专家确认（OPEN 过滤）/dev_mode 开发详情块（contract id/DataRun ops/evidence rstrip('.')/question certainty） | `contract_lines`（Qt-free：panel lines + title text）+ `qt/workflow_contract_panel`（ReadinessFn seam + dev toggle） | ported |
| `prototypes/workstation_composite_prototype.py` | [非生产] 三布局原型：A/B/C variant、图层管理面板（move +1=上移更早、visible/opacity floor 0.05、snapshot `{project_crs,layers}` 逐字保留未触字段）、toolbar/事件过滤/发布守卫、真 QGIS DisplayMapCanvas | `composite_layers`（Qt-free：index/visible/opacity/move/snapshot/reads）+ `qt/composite_prototype`（**仅在 `pwb_ui_review_qgis` 目标**——真桥才编译） | ported |

| Python source | C++ target | 理由 |
|---|---|---|
| `pages/task_panel_base.py` | —（UI-09 `pwb::ui_wellseis::qt::TaskPanelBase`） | 已合并入 main；不重复移植 |
| `pages/prediction_evidence_panel.py` | —（UI-09 `pwb::ui_wellseis::qt::PredictionEvidencePanel`） | 同上 |
| `pages/prediction_task_panel.py` | —（UI-09 `pwb::ui_wellseis::qt::PredictionTaskPanel`） | 同上（TaskPanelBase 特化） |

## 结构

`libs/ui_review/`（三层，同 ui_map/ui_wellseis 先例）：

- **`pwb_ui_review`**（`Pwb::UiReview`，Qt-free，不链 Qt）— 11 TU/12 头：
  `catalog_api`（`ICatalogApi` + `LineageHop`/`ResolvedPath` DTO）、
  `lineage_expand`、`impact_markdown`、`audit_summary`、`relink_summary`、
  `version_view`、`ingest_columns`、`qc_issue_rows`、`contract_lines`、
  `advisor_html`、`composite_layers`、`review_core`（`IReviewActions`）、
  `tokens`（severity/rule 描述表）。
- **`pwb_ui_review_qt`**（`Pwb::UiReviewQt`）— 13 壳 TU + 13 Q_OBJECT 头：
  上述全部 widget。链 `Pwb::UiReview` + `UiWidgets`（PwbDialog/ObjectTable）
  + `UiShellQt`（dock/float/persistence）+ `UiPagesDataQt`（ActionHeader）
  + `JobQt`（worker 对话框）；13 个 `unique_ptr<incomplete>` 成员全部
  out-of-line 析构。
- **`pwb_ui_review_qgis`**（`Pwb::UiReviewQgis`，仅 `Pwb::UiMapQgis` 在场）—
  `composite_prototype`：非生产三布局原型，画布为真 QGIS
  DisplayMapCanvas；无桥配置不编译此目标。

## 服务 seam（不移植不伪造）

| seam | 服务域 | 承接方式 |
|---|---|---|
| `ICatalogApi` | catalog 版本/资产/血缘读、路径解析、版本列举、promote/trash/restore、缺失源扫描、重链接、audit | `catalog_api.hpp` 纯虚接口；血缘/健康/工作台/重链接四壳经 provider lambda 注入 |
| `IReviewActions` | 活动 QC 报告、run_map_qc、导出 JSON、定稿、默认导出目录、图件/artifact 读 | `review_core.hpp`；ReviewExportPage 经 provider 注入（project-bound 才激活） |
| `IngestDialogHooks` | 工程井/测井列表、plan 构建、plan 执行 | `ingest_plan_dialog.hpp` 四 std::function 槽 |
| `IDeleteImpact` / `IMapUsageSource` | delete_impact hop / 编图引用 | `impact_markdown.hpp`；fail-closed 契约由核承担 |
| `ReadinessFn` | workflow contract readiness report | `workflow_contract_panel` 注入（nullopt → 未绑定工程） |
| composite 画布 | 真 QGIS canvas | `_qgis` 目标持有；面板/图层语义在 Qt-free 核 |

## 测试（ctest `ui_review.*`，linux-ninja preset）

- **`ui_review.core_smoke`** — **14 tests / 0 failures**：lineage 扩展
  （run 交织/循环/断链/溢出/终态/卡片）、impact fail-closed 计数、
  audit 排序/文案、QC 行（rule 驱动 + truthy geometry）、relink
  状态/扫描/结果、version view（阶段 token/校验和/cell/门/diff）、
  ingest 列 + 批量编辑、review 流（文件名/定稿目标/文案）、contract
  未知行、composite 层变更 + snapshot、advisor html。
- **`ui_review.qt_widgets_smoke`** — **11 tests / 0 failures**
  （`QT_QPA_PLATFORM=offscreen`，ctest 属性携带）：每壳构造即答 +
  Fake `ICatalogApi`/`IReviewActions`/`IngestDialogHooks` 状态更新；
  `relink_dialog_scan` 经 `QTRY_VERIFY_WITH_TIMEOUT` 泵 worker；
  `run_qc` 尾部模态框经 `singleShot(0)` 自动 accept。
- composite 原型在 `_qgis` 目标 —— 真桥处手动覆盖（无 QGIS smoke
  目标，与 CMakeLists 注释一致）。

## Smoke/parity 修正轮（本轮实测揪出的偏差）

### 实现侧（oracle 对照后修正）

| 位置 | 偏差 | 修正 |
|---|---|---|
| `impact_markdown.cpp` | `insert(end, first_n(u,30).begin(), first_n(u,30).end())` —— **两个不同临时量的迭代器**，insert 越界狂读 → `std::bad_alloc` 崩溃 | 先物化 `usages_limited` 再取其迭代器 |
| `lineage_expand.cpp` | `current_item_spec` 返回 `Kind::Current` —— Python payload 为 `"kind": "version"`，头注释也写 kind Version | 改 `Kind::Version`（壳对 Version/Current 本就同等处理） |
| `contract_lines.cpp` + `workflow_contract_panel.cpp` | null 合同返回空 vector，壳不补行 —— Python 渲染 `未知模块：{contract_id}` warn 行 | `contract_panel_lines` 加 `contract_id` 形参并自发该 warn 行；壳传入 `contract_id_` |
| `version_view.cpp` | `stage_display` 用 `stage_label`（中文 "输出成果"）—— Python `_STAGE_DISPLAY` 是英文 enum token | switch → `RAW/DERIVED/INTERMEDIATE/OUTPUT`（fallback `domain::to_string`） |
| `composite_prototype.cpp/hpp` | `LayerManagerPanel` 继承不完整类型（头里只有前向声明）→ 无法作 QWidget 使用；`move(int)` 域方法遮蔽 `QWidget::move` | 头含真 `QFrame` 定义；壳内 `layer_manager_->QWidget::move(...)` 限定调用 |
| 各 Q_OBJECT 头 | `unique_ptr<JobOwner/LayoutPersistence/StableSelection>` 成员 + 前向声明 → moc TU `sizeof` 不完整类型 | 5 个类补 out-of-line 析构（.cpp 在完整头后定义） |
| relink/ingest/version_workbench .cpp | `const T& row_entry(...)` 返回 `QVariant::value<T>()` 临时量引用 → 悬垂 | 按值返回 DTO |
| 多个 qt 头 | `namespace pwb::domain { class Json; }` —— `Json` 是 `ordered_json` **别名**非类，前向声明毒化 → 大面积级联错 | 改含 `pwb/domain/json.hpp` 真定义 |
| `review_export_page.cpp` | `QPushButton` 未含头 | 补 include |

### 测试侧（fixture 对齐 Python 语义）

| 位置 | 偏差 | 修正 |
|---|---|---|
| `core_smoke_test.cpp` lineage fixtures | `hop.parents` 填了但 `version.parent_version_ids` 空 —— Python 遍历的是后者 | fixture 补 `parent_version_ids`（实现本就 parity） |
| `core/qt` smoke QC fixture | `"geometry": Json::object()` 空对象 —— Python `issue.get("geometry")` 对 `{}` 为 falsy → 非 spatial | 改非空 Point geometry（实现 truthy_member 本就 parity） |
| `core_smoke_test.cpp` | `audit_verdict(false)` 期望 "存在问题"、relink 状态对调、`cancelled` 期望 "取消"、`version_cell` 期望 "v4 ●"、`workbench_count_text` 期望 "3 个版本" | 全部对齐 Python 原文：`⚠️ 发现需要处理的健康问题` / managed→需重新导入、else→不支持重链接 / 结果文案无 cancelled 分支 / `v4（当前）` / `共 N 个版本` |
| `qt_widgets_smoke_test.cpp` | `recenter` 未把中心版本注册进 `api->versions` —— Python `_on_locate` 先 `get_version`；`hooks` `std::move` 后又调用 → `bad_function_call` | fixture 补 `versions.push_back`；detail 编辑直接传行表 |
| `qt_widgets_smoke_test.cpp` | `run_qc` 尾部 `QMessageBox::information` 模态永久阻塞 offscreen | `QTimer::singleShot(0)` 在嵌套 exec 内自动 accept（不动生产码） |

### 邻切片修正（本切片暴露的上游缺陷）

| 位置 | 缺陷 | 修正 |
|---|---|---|
| `libs/ui_pages_data/CMakeLists.txt` | `preparation_page.hpp` 留在 `pwb_ui_pages_data_qt` AUTOMOC 源清单而 `.cpp` deferred —— `PreparationPage(QWidget* = nullptr)` 可默认构造 → moc metatype 生成 default-ctor thunk → **任何消费者**链 `mocs_compilation.o` 即 undefined ref（本切片测试是首个消费者） | 从源清单摘除该头（文件保留盘上），注释记因；`.cpp` 落地时再加回 |

此前轮次已修（编译期）：`LayerManagerPanel::move` 遮蔽、StrongId 字面量
二义（`RunId{std::string("…")}`）、const map `operator[]`、QString↔std::string
断言转换、`ObjectTableModel`/`QPushButton` 不完整类型 include。

## 验证结果

- `ninja -C build/presets/linux-ninja pwb_ui_review pwb_ui_review_qt
  pwb_ui_review_qgis ui_review.core_smoke ui_review.qt_widgets_smoke`：
  **全部编译+链接通过**（含 `pwb_ui_pages_data_qt` 重归档）。
- `ctest -R ui_review`：**2/2 PASS**（core 14 + qt 11 用例，0.34s）。
- 直接运行：`ui_review.core_smoke` 14/0 fail；`QT_QPA_PLATFORM=offscreen
  ui_review.qt_widgets_smoke` 11/0 fail（需 `source ~/pwb-sdks/env.sh`
  供 libodbc 等 vendor 依赖 —— 与 ui_wellseis 同约束）。
- 已知非本切片问题：`JobScheduler::boost` nodiscard 警告、sqlite3 三方
  警告、qt smoke 未配 `LD_LIBRARY_PATH` 的兄弟套件（同 UI-09 记录的
  预存环境问题）。

## Not ported / deferred

| 面 | 理由 |
|---|---|
| `task_panel_base.py` / `prediction_evidence_panel.py` / `prediction_task_panel.py` | UI-09 已在 `pwb::ui_wellseis::qt` 交付（merged main）——宿主复用，无第二拷贝 |
| catalog/project/QC/ingest 服务本体 | `libs/catalog`/`project`/`ingest` 是服务编排域 —— 经 `ICatalogApi`/`IReviewActions`/`IngestDialogHooks` 注入；真绑定属集成片 |
| composite 原型的 QGIS 画布 | 非生产壳；`_qgis` 目标条件编译，无桥不入 |
| MainWindow/AppContext/页面接线 | W5 集成片域，本波不接线 |
| QGIS smoke 测试目标 | 真桥手动覆盖（同 ui_wellseis 先例的约定外项——本切片更小，未立 `ui_review.qgis_smoke`） |

## 冲突面声明

- 根 `CMakeLists.txt`：UI-09 块后新增 `# BEGIN UI-11` 块
  （`PWB_BUILD_PLATFORM + Pwb::Data + Pwb::JobQt + Qt6::Widgets` 门控；
  `Pwb::WorkflowContracts` 缺失时经 `pwb_add_subdirectory_once` 补入 ——
  CONV-23 常关）。无新 `option()`；不满足时 `message(STATUS …)` 跳过。
- **`libs/ui_pages_data/CMakeLists.txt`**：从 `pwb_ui_pages_data_qt`
  AUTOMOC 源清单摘除 deferred 的 `preparation_page.hpp`（原因见上表）——
  跨切片但属本切片暴露的构建缺陷修复，非行为变更。
- 未动任何 Python UI 文件、未动其他切片源码、未接线
  `apps/paleo_workbench_platform`。
