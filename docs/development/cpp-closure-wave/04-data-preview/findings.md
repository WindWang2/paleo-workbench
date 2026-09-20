# 04 线 findings（盘点与证据）

基线 `06211541`，worktree 干净。盘点 = 根任务直读 + Explore 子代理报告（3.08M tokens）交叉确认。

## 已合并基础（@06211541 查证）

- viz-e 已合并：`register_external_presenter({kind, supports, create, note})` 进程级 presenter 注册表（viz_e_install.cpp，first-wins 线程安全）；`preview_dispatch`/`kPreviewModes` 词表含 `xy_scatter`/`surface`；`VizEDataPage` + `install_data_dock`（guard `PWB_WITH_VIZ_E && PWB_WITH_CONV_30`）。
- viz-a 已合并：`viz_a::install(QMainWindow*, JobCenter*)` → `install_wle_las_preview_provider()`（ingest registry LAS 分支生效）。
- viz-d 已合并：D→E 装配缝 `make_seismic_preview_presenter()`（"注册策略归 E"）。
- UI-17 AppShell 已合并：hub0 = HomePage + DataWorkspace("management")；`LocalVizProvider` base_builder 为 message 桩；`preview_settings_requested` 信号无消费者（deferred）。
- 异步基建已在：`ui_data_core/preview_worker.hpp`（generation 失效）；PreviewRequestController 走 JobCenter；viz-e surface 路径有 generation guard + JobOwner 样板。
- 预览设置已在：`ui_pages_preview::PreviewSettings`（同形三份 POD）+ `PreviewSettingsStore` + `PreviewSettingsPanel`（UI-15 PreviewSettingsDialog 模态包裹）。

## 四大缺口（本线对象，全部有代码证据）

1. **重复数据入口**：app_shell hub0-management 与 viz_e dock 各一个 `DataWorkspace` 实例，选择状态私有于各自 DataAssetTable，无共享。
2. **无 catalog 资产源**：`set_asset_rows` 全仓无生产调用者；真实链（PwbDataStore → snapshot → catalog_assets/versions + resolved_path）已具备。
3. **解析注册表 base seam 缺失**：真实解析核 `pwb::ingest::preview::build_preview` 无人从数据页/可视化页消费；VizEDataPage 对 txt/csv/pdf/png/json 落"暂无原生预览"；AppShell VisualizationPage base_builder 为 message 桩。
4. **预览设置/取消缺失**：apply_preview_settings 无产品入口；show_loading 无取消；preview_settings_requested 无消费者。

## 实施中发现并修复的缺陷（含主线既有）

| # | 缺陷 | 证据 | 修复 |
|---|---|---|---|
| D1 | **主线潜伏**：DataReaderPanel 构造器把原生预览 widget 注册在 `text`/`table` 等短名，而 `target_for` 按 `preview_target` 解析出的 `text_preview`/`table_preview` 查表——文本/表格/图像/PDF 真实预览自 UI-06 合入起就静默回退到 message widget（mode 标签照报，无内容）；native load 分支按 target 名匹配同样永不命中 | pa_flow :702-710 断言（result 有数据、widget 空：`hdr=2 rows=2 tsv=0`） | 构造器改按分派名注册（empty_label/message_label/text_preview/table_preview/image_preview_widget/pdf_preview_widget）；native load 分支改按 **mode** 匹配 |
| D2 | **主线潜伏**：DataAssetTable 无模型时 `table_->selectionModel()` 为 null，`update_assets` 首调即段错误（无人调用过所以未暴露） | platform.closure_preview 首跑 SIGSEGV（gdb: sync_selection→blockSignals） | 新增 `VectorAssetRowSource`（16 列，data_table_columns 词表对齐）随表自动安装；`set_model` 仍可被 UI-03 宿主替换 |
| D3 | adopt 流程若在 hub swap 前收编 workspace，`replace_submodule` 的 setParent(nullptr) 会把 workspace 从复合页布局拽走 | 静态推演 + platform 测试断言 parent 链 | replace_submodule 仅在 old 仍属本 stack 时 detach |
| D4 | 取消时 bump generation 会连"已取消"投递一起吞掉（loading 永挂） | pa_flow :831 | cancel_active_preview 不再 bump；surface 护栏移至 preview_asset 入口 |
| D5 | worker 线程经共享 QSettings load 与 GUI 线程 save 并发（QSettings reentrant 非并发安全） | 设计评审 | settings 访问互斥化（load_settings/save_settings），builder 传 settings 值 |
| D6 | 本机 loader 缺 libodbc 路径 → ui_pages_preview 两个 ctest 加载即败（viz-e ledger 记录的 qt_widgets_smoke "环境性失败"实为加载器问题叠加） | ctest 0.13s 失败 + 直跑全过 | 测试属性补平台同款 ENVIRONMENT_MODIFICATION（既定模式）；修复后 qt_widgets_smoke 亦全过（超出上游论证的环境性结论） |
| D7 | ingest json_tree 结果只报 json_ok 不携带 payload | registry/document_parsers.cpp | 适配器有界重读+解析（worker 线程），payload 经 PreviewResultView 新增的 `payload_owner` shared_ptr 跨投递拷贝存活 |

## 环境与协作事实

- cmake/ninja 位于 /tmp/pwb-oracle-venv/bin；QGIS vendor SDK 只读复用主工作区 output/。
- 共享锁高竞争：14/06/03/08/05/09/10/07/12 线先后持锁；/tmp/gate_retry_04.sh 45s 退避排队，全程未绕锁。
- platform.app_shell / platform.closure_preview 需 APP_SHELL UI 闭包目标齐全。
