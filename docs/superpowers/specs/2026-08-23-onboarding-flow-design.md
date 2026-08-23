# 启动引导与新建工程流程重设计（Onboarding Flow）

日期：2026-08-23
状态：已确认（auto 模式下依据用户明确描述直接定稿）

## 背景与目标

当前 `main()` 启动即空项目（`e3fd7e9e`），首页直接显示模块关系图，没有任何"下一步该做什么"的引导；「新建工程」菜单动作只弹一个确认框然后给出一个空工程，数据导入要用户自己到数据页点「导入目录」。

目标流程（用户原话）：

1. 软件打开 → 开始页面，引导用户**新建**或**打开**工程文件。
2. 新建工程 → 进入**新建工程引导**（向导）：
   - 选择原始数据文件夹；
   - 中间文件目录默认 = 原始数据文件夹，可改设为其他文件夹；
   - 导入后**自动分析构建**：盘点井数据、地震数据、时深数据、层位数据等；
   - 针对井数据，按每口井的坐标绘制**工区预览图**；
3. 形成对应的**报告**，显示在主页。

## 现状盘点（探索结论）

- `ProjectController._on_new_project/_on_open_project/open_sample_project` 已封装确认框 + `_end_current_session` 会话门闩 + catalog 开闭 + shell 重建——所有工程切换必须走这里，不能绕。
- `import_folder()`（`resources/import_service.py:239`）→ `ImportReport{added, skipped_*, warnings, by_type, summary_text()}`。
- `stage_resources()` worker 线程安全（只读文件），`bind_staged()` 纯文档写入 → `BindingReport{wells_created, surveys_created, entities_created, ambiguous_assets, issues}`（`catalog/domain_binding.py:454-615`）。向导里文档尚未激活，两者都可在后台线程顺序执行。
- 时深/层位：`classifier` 已能把 `.dat` 按路径分为 `time_depth`/`horizon`/`well_stratification`（盘点计数够用）；domain 层面对时深无实体识别——本设计**不扩 domain 白名单**（YAGNI，盘点报告按资源类型计数即可覆盖"时深数据有哪些"）。
- 工区边界 `workarea.boundary` 目前无任何自动生成；井坐标来自 well_head DAT（LAS 只给井名）。向导用井坐标凸包（monotonic chain，~30 行纯 Python，零依赖）回填边界，让预览图有工区范围。
- `WellMapPanel`（折叠面板，内嵌 `ProjectWellMapPage`）可独立嵌入任意 `QDialog`，geoviz 缺失时自动降级为文案，不崩。
- 首页卡片统一 `QFrame#PanelCard` + `update_state(state, steps)` 模式；`HomePage.update_state(state, steps, project=None)` 已能拿到 project。
- 中间文件（`.artifacts` 目录）位置由工程文件（`.paleo.json`）位置决定（`paths.py:26 artifact_dir_for`，硬编码同名相邻）。因此"中间文件目录"= 工程文件保存目录，默认取原始数据文件夹。

## 设计

### 1. 开始页引导（HomePage）

- 新增 `StartGuideCard`（PanelCard）：标题「开始使用」+ 三个按钮「新建工程」(PrimaryButton) /「打开工程」/「打开样例工程」。
- HomePage 新增信号：`new_project_requested` / `open_project_requested` / `open_sample_requested`，在 `PaleoWorkbenchWindow._wire_menu_bar` 同等位置接到既有 controller 入口（复用确认框与会话门闩，零逻辑复制）。
- 可见性规则（`update_state` 内）：项目无资源且无盘点报告时显示引导卡；否则隐藏。
- 新增 `OnboardingReportCard`（PanelCard）：`set_report(report: dict)`，展示数据盘点（按类型计数）、工区识别（井/地震/实体/歧义）、问题列表（封顶 5 条）、工区范围；`project.onboarding_report` 非空时显示。

### 2. 新建工程向导（NewProjectWizardDialog）

新文件 `paleo_workbench/ui/pages/new_project_wizard.py`，`QDialog + QStackedWidget` 两步（仓库无 QWizard 惯例，沿用 GovernanceMetadataDialog/CatalogHealthDialog 模式）：

- **第 1 步·设置**：工程名称（默认取数据文件夹名）；原始数据文件夹（浏览按钮）；「中间文件与原始数据同目录」复选框（默认勾选，取消后可另选目录）。行内 error_label 校验：名称非空、目录存在、目标 `<中间目录>/<名称>.paleo.json` 不存在。
- **第 2 步·分析与预览**：进入即启动后台 worker（OwnedWorkerJob 模式）跑 `analyze_data_folder`，期间不确定进度条；完成后显示分类盘点表 + 识别摘要 + 展开的 `WellMapPanel`（工区预览图，绑定向导内的临时文档）。
- 「完成」→ accept，暴露 `result_document / project_name / intermediate_dir`。
- 「上一步」可返回改设置；分析中「取消」= 取消 worker + reject。

### 3. 纯逻辑层（paleo_workbench/project/onboarding.py）

```
analyze_data_folder(root, *, project_name, engine=None) -> OnboardingResult
  ProjectDocument.new → import_folder → resources.extend
  → stage_resources → bind_staged → boundary_from_wells(凸包回填)
  → sync_well_location_map → build_onboarding_report → doc.onboarding_report
boundary_from_wells(doc) -> list[list[float]]   # monotonic chain, ≥3 点成环
build_onboarding_report(...) -> dict            # 见下
```

报告 dict（持久化进 `ProjectDocument.onboarding_report`，新增字段 `dict`，默认 `{}`，对旧工程迁移安全）：
`generated_at / source_folder / intermediate_folder / imported_count / by_type{中文标签:count} / skipped / warnings / wells_total / wells_with_coords / surveys / entities / ambiguous / issues[:20] / extent[xmin,xmax,ymin,ymax]|null`

### 4. 工程创建落账（ProjectController）

- `menu_bar.new_project_requested`（及首页引导卡按钮、Ctrl+N）→ 打开向导。
- 新增 `create_project_from_document(doc, intermediate_dir) -> bool`：
  `_end_current_session` 门闩 → `ProjectManager(<中间目录>/<名称>.paleo.json).save(doc)` → `window.project/project_path` 落账 → `_open_catalog`（失败仅警告）→ `_refresh_shell` → `_schedule_catalog_maintenance`（与 `open_project_path` 对齐）。
- 原「新建工程=空工程」语义由向导第 1 步不选数据文件夹时不提供——向导强制选目录（用户流程如此）；保留 `new_project(name)` 方法本身不动（测试与其他调用方）。

### 5. 不做的事（YAGNI）

- 不扩 `domain_binding` 的时深实体识别；不做最近工程列表；不改 `.artifacts` 可配置化（用工程文件位置天然承载"中间文件目录"语义）；不动菜单「打开工程/打开样例工程」既有流程。

## 测试

- `tests/test_onboarding.py`：凸包（<3 点、共线、正常环）、报告构建、`analyze_data_folder` 在临时数据树上的端到端（LAS + well_head dat 用既有测试 fake/夹具模式）。
- `tests/test_new_project_wizard.py`：第 1 步校验（空名称/目录不存在/目标已存在）、第 2 步分析完成态（monkeypatch analyze）、取消。
- `tests/test_home_start_guide.py`：空项目显示引导卡 + 三个信号发射；有报告的项目显示报告卡、隐藏引导卡。
- controller：`create_project_from_document` 落盘 + project_path 落账 + 已存在目标拒绝。
- 全量回归 + 离屏截图（开始页引导态、向导两步、主页报告卡）。
