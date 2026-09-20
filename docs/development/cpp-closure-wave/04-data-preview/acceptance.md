# 04 线 acceptance（验收矩阵）

implemented / merged / wired / verified 四列口径：implemented=本分支有代码；merged=已在 base；wired=生产调用链可达（AppShell/MainWindow 真挂载）；verified=本分支测试证据。

| 能力 | Python 冻结源 | implemented | merged | wired | verified |
|---|---|---|---|---|---|
| 单一真实数据页（收编重复入口） | ui/app_shell.py DataPage 组合 | ✅ | ✅(VizEDataPage) | ✅ AppShell adopt（closure_preview::install） | ✅ platform.closure_preview（单页断言+无 dock） |
| 单一资产选择状态（AssetSelectionBus） | data_view_models 选择语义 | ✅ | — | ✅ bus 绑定 workspace | ✅ pa_flow §6（选择/删除/工程切换清除） |
| catalog 资产源 | data_page._catalog_service | ✅ | ✅(PwbDataStore) | ✅ install store getter + openProject 通知 | ✅ pa_flow §6b（真 bootstrap→快照→行→registry 预览） |
| 解析注册表 base seam | preview_provider super()._build_preview | ✅ | ✅(ingest::build_preview) | ✅ 数据页 builder + VisualizationPage provider | ✅ pa_flow §6/§6b（csv/txt/json/geojson 真实内容） |
| 保留 image/table/JSON/PDF 能力 | data_reader_panel._mode_handlers | ✅(+D1 修复) | ✅ | ✅ | ✅ pa_flow §6（table TSV 内容/text/image zoom） |
| json_tree/rich_text/web_document/geotiff/media 目标 | 各 preview widget | ✅ | ✅ | ✅ closure 注册 reader targets | ✅ pa_flow §6（json payload/media 路由） |
| LAS presenter 消费 | las_preview + WLE | ✅(viz-a) | ✅ | ✅ 经 base registry（LAS 分支已装） | ✅（registry 分支存在性由 ui_pages_preview oracle 覆盖；.las 走 base 路径） |
| 地震 presenter 消费（D→E） | seismic_preview_presenter | ✅ | ✅ | ✅ closure 注册 kind="seismic"（JobCenter 异步开体） | ✅ platform.closure_preview（注册断言）；落画由 viz_d_presenter_smoke 覆盖 |
| 统一预览设置 | preview_settings_panel.py + UI-15 | ✅ | ✅ | ✅ preview_settings_requested→Dialog→reader/store/controller | ✅ platform.closure_preview（接线存在）；对话框行为由 ui_canvas smoke 覆盖 |
| 可取消加载 | （任务书强制，Python 无此 UI——记录为任务增补） | ✅ | — | ✅ loading 页取消钮→JobOwner cooperative cancel | ✅ pa_flow §6（取消→诚实"预览已取消"） |
| 快速切换（generation guard） | preview_worker 语义 | ✅ | ✅ | ✅ | ✅ pa_flow §6（superseded 投递不落画，末选获胜） |
| 图表导出真实内容校验 | viz_charts export | ✅(viz-e) | ✅ | ✅ | ✅ pa_flow §3/§4（SVG circle 数/刻度/带填充 + PDF 头）；本线保留 |
| 解析失败诚实呈现 | preview_parsers 错误形状 | ✅ | ✅ | ✅ | ✅ pa_flow §6（坏 JSON→解析失败 message；缺文件→missing） |
| 媒体环境不可用诚实降级 | media_preview_widget | ✅ | ✅ | ✅ | ✅ pa_flow §6（offscreen 路由 media 目标不伪造帧；播放为环境能力） |

## 验证轮记录（@worktree HEAD，build/cpp-integrated）

- viz_e.pa_flow：**143 检查全过**（含 §6/§6b 新增 60+ 断言）。
- platform.closure_preview：**全过**（单页/收编/presenter 注册/通知幂等/双窗口）。
- 受影响集 `ui_pages_data|ui_pages_preview|viz_e|platform.|viz_charts|ui_data_core`：**30/30 ×2 遍全绿**（含此前 ledger 记录为环境性失败的 ui_pages_preview.qt_widgets_smoke——加载路径修复后通过）。
- MALLOC_CHECK_=3 审计（viz_e.pa_flow + platform.closure_preview + platform.app_shell + ui_pages_data.smoke）：**4/4 通过**。
- 全量构建（617+ 目标闭包）：通过。

## 明确未执行/边界（如实）

- 真 GL 硬件像素验证未做（offscreen 环境无显示面；媒体播放为环境能力，测试仅断言诚实路由）。
- 时深（viz-b）presenter：B 线未提供 presenter 入口（其 dock 路线独立），未注册、不可用消息如实列出注册表状态；05 线交付后经同一 register_external_presenter 契约接入，无需本线改动。
- 12 线统一候选上的全量矩阵归 12 执行；本线提交可重放命令（progress.md）。
