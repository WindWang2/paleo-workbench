# 03 — 产品逻辑执行图(原生 pwb-platform @ main 7bfe7585)

来源:main.cpp → bootstrap.cpp → app_context/app_shell/main_window.cpp 实读。本文件记录真实执行链与断链点。

## 启动链

```
main(argc, argv)
 → pwb::app::Bootstrap::run
    → diagnostics::install_message_collector
    → QgsApplication / QgisRuntime init(QGIS prefix = vendored SDK)
    → 模式分派:--self-check / --capabilities / --diagnostics / (默认)交互窗口
    → AppContext(产品服务注册表,20 hard capabilities)
    → MainWindow(壳)
```

## 壳装配(MainWindow 构造序,节选)

- `app_shell_->install_canvas(canvas_)` — QGIS canvas 装入
- `closure_review::install_review_actions` — 审核治理动作
- `viz_a::install`(LAS 预览)、`closure_preview::install`(预览管线)、`viz_e::install_data_dock`(数据页 dock)
- `install_conv27_surface()` — CONV-27 工作台面(stage dock/域层树/编辑工具)
- VIZ-B cross-well dock(根 CMake post-slices 块,#1442 修正后的接线位)
- `closure_mapping::install`(CLOSURE-MAPPING:制图文档 bank、数据制备页、因子制备 worker、组图面板)
- `closure_science::qt::attach_prediction_pages`(S1 预测页)
- `stage_flow_install`(PWB_WITH_STAGE_FLOW:阶段条挂载、命令面板 17 条、任务中心 provider、选择/焦点总线)
- AppShell 构造 `CompositeDocument`(app_shell.cpp:128)

## 工程生命周期

- `newProject` / `openProject`(PWB_WITH_DATA_INTEGRATION):单窗口单工程会话;打开时 `store->recover()`(journal 回放)→ `set_store` → `closure_mapping::notify_project_changed`(重绑制备页+文档 bank)→ 物化 bound GeoJSON 为 `.pwb-working` 工作副本(错误路径回滚 store 并再次 notify)
- 切换/关闭:notify_project_changed → 各 dock `notify_project_store_changed`(closure_preview / closure_review / joint3d bind_project_assets)

## 三阶段(Stage1 预测 / Stage2 约束+单因素 / Stage3 综合编图)

- 权威:`ProjectSession`(stage 值)+ 工程文档 `mapping_workspace.current_stage`;`applyStageValue` 走 session;`StageFlowController` 应用 per-stage 面板可见性/工具门控/QSettings 偏好;`MappingStageBar` 挂 WorkstationFrame app bar(#1438)
- 同一 canvas / 同一 QgsProject / 同一 selection bus(QtSelectionContext + ViewCoordinationController,工程打开时绑定、store detach 时清空)
- 阶段化图层策略:#1437 layer control plane(QgsLayerTree 运行时权威 + workspace JSON 持久化权威,单向 reconcile)

## 单因素数据链(实测)

```
工程文档 root
 → factor_prepare_production::build_prepare_slice(读 factor_map_tasks / constraint_layers / coordinate / stratigraphy)
 → ui_workers::build_prepare_snapshot
 → closure_mapping_install:set_prepare_worker_fn(GUI 线程快照)
 → run_factor_prepare_schedule(job_runtime:取消令牌/进度)
 → 科学核:IDW / Kriging / 约束IDW(constraint_lines 消费、指纹复用、CRS fail-closed)
 → live grid store + commit + provenance rail(catalog 版本)
 → 轮廓/图层/QGIS 呈现
```

### 断链点(重要发现 F-1,P1)

**约束的创作侧(production 侧)缺失**:
- `MappingStagePanel` 8 个约束按钮(物源线/物源方向/展布线/古岸线/相带控制线/断层/插值边界/掩膜)`emit constraint_requested(kind)`(mapping_stage_panel.cpp:327-328)
- `CompositeDocument` 仅向上转发(composite_document.cpp:159-160)
- **apps/ 全仓无任何 connect 消费者**(grep 证实)——信号进入虚空
- 无产品代码写 `constraint_layers` 进工程文档(schema.cpp:515 有字段定义;读者众多)
- 无产品代码设置 `binding.constraint_kind`(workspace/state.cpp 只做 round-trip)
- `workflow_runtime::commit_constraint_group`(约束组→目录版本写入路径)**无 app 侧调用者**
- 同时 stage panel 的 `action_requested` / `locate_requested` 亦无消费者

后果:Stage2「约束与单因素」中,约束绘制按钮无效(silently ignore,违反目标 §15 fail-closed 要求);约束 IDW/克里金的约束消费链只有当工程文档已经带有 constraint_layers(legacy Python 产品创建或手写)时才可达。**消费侧完备、生产侧断链。**

## 综合编图链(Stage3)

- 组图文档 bank(MapDocumentBank:active_changed/document_saved/dirty_changed → stage_flow_install:580-584 连接)
- 9 内建模板 → Composition(mapping_document 单一权威)→ SVG 预览渲染器 → 导出 SVG/PNG/PDF(预算→QGIS 执行器→composer 引擎,engine 标签如实)
- 融合:`IntegratedGridSeams` 生产实现(closure_workflow/grid_seams.cpp;catalog pin 装载+current 三级解析+缺失 pin 拒绝)
- QC:DataRun 注册(workflow rail)后 `provenance_registered` 才为 true;导出写 `export_artifacts`

## 失败语义/取消

- job_runtime:CancellationToken + 世代 task_key(#1442 修正:preview task_key 按 request generation 作用域)
- constraint CRS 冲突 fail-closed(factor_prepare_production.cpp:411-428)
- 组图导出:引擎不可用时按钮弹「导出引擎不可用」(honest);融合 seam nullopt=拒绝

## 待复核(交给 shard findings 汇总)

- viz_b/c/d/e 各 dock 的工程切换状态残留
- 关闭窗口时 worker join/dock 销毁序(#1429 的 Windows 崩溃家族提示析构序风险)
