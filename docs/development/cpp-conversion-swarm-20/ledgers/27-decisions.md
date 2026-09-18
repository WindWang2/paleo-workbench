# CONV-27 — Composer / Layout / Export C++ 化（决策账本）

每条记录：选择、被否的备选、理由。

## D-01 — 内核位置：新建 Qt-free `libs/layout_export`（pwb_layout_export）
- 选择：`build_layout_spec` / `hybrid_element_types` / 镜像门控 / 像素预算 /
  `LayoutExportReport` / screen-export parity 比对器全部落在新的 Qt-free、
  QGIS-free 静态库 `libs/layout_export`，复用 CONV-02 的
  `pwb_mapping_document::Composition` 作为唯一文档模型。
- 被否：塞进 `libs/qgis`（会把纯策略层拖进 Qt/QGIS 链接闭包，oracle 测试
  被迫拉起 QGIS runtime）；塞进 `libs/mapping_document`（CONV-02 决策 D-01
  明确把行为层排除在该库之外，职责是数据契约）。
- 理由：与 CONV-02 的分层一致（数据核 / 行为核 / 执行器三层），内核可以被
  fixture oracle 冻结而不需要 QGIS。

## D-02 — 执行器：不复制桥实现，抽出共享翻译单元
- 选择：把 `QgisMapStack::layoutExport`（native/qgis_render_bridge
  map_stack_service.cpp，V7/V8/V11 多轮加固的权威实现）的 spec→QgsLayout→
  导出主体原样抽到 `native/qgis_render_bridge/src/layout_spec_exec.{hpp,cpp}`，
  镜像上下文（doc_id→layer 解析、树序）经 `LayoutSpecExecContext` 注入；
  桥的 `layoutExport` 委托它（行为零变化），产品侧 `pwb::qgis::
  CompositionLayoutService` 直接调用同一 TU。
- 被否：在 libs/qgis 里照抄一份 spec 执行器（两个执行器必然漂移，违反
  “不另起平行架构”）；让平台链接整个 pybind 桥静态库（把画布/树/编辑等
  巨面拉进产品闭包）；C++ subprocess 调 Python（红线禁止）。
- 理由：单一权威执行器 + adapter seam；桥（Python 遗留面）与产品（C++ 主链）
  共用同一实现，wobble 面最小。

## D-03 — C++ 导出引擎策略：fail-closed，不移植 composer SVG 兜底渲染器
- 选择：C++ 链上 hybrid（timescale/inset_map/stat_chart/profile/
  fault_symbols/lithology_legend）或镜像门控未证 → 内核照 Python 全量产出
  warnings/hybrid_items，但 **不** 回退 composer SVG 引擎：报告
  `ok=false` + `failure` 诊断（超集键，Python 共有键逐一保形）。
- 被否：移植 renderer.py 1341 行 SVG 字符串渲染器到 C++（为一条 Python 遗留
  兜底路径复制整条渲染栈，且 QGIS 原生链无法与之共享符号权威）；静默降级为
  部分 QGIS 页面（Python 注释明说这是错的）。
- 理由：任务要求 “unsupported element fail-closed”；Python 兜底引擎保持
  legacy/oracle-only 分类，`composer/renderer.py`、`composer/export.py` 的
  Qt/SVG/PDF 路径不再被 C++ 主链需要。

## D-04 — 镜像描述的 C++ JSON 契约
- 选择：`mirror_layers` 接受 `null` / 层数组 / `{"layers":[...]}` 快照形；
  层元素按 `{id, layer_type, style{renderer}}` 读取。
- 被否：复刻 Python `getattr(dict,"layers")→None` 的字典怪癖（dict 永远不是
  快照对象，JSON wire 上不存在该形态）。
- 理由：JSON 边界上只有两种真实形态（裸序列 / 快照包装），语义等价、契约
  更诚实；fixture 两侧同形冻结。

## D-05 — 产品接线：CONV-27 选项门，默认路径零扰动
- 选择：root CMakeLists `PWB_BUILD_CONV_27`（隐含 CONV_02+DATA）；libs/qgis
  追加 `composition_layout_service.cpp` 并 PUBLIC 链接 `Pwb::LayoutExport`；
  app 的导出对话框在 `PWB_BUILD_CONV_27` 编译期内改走
  Composition→LayoutSpec→QgsLayout 全链；关掉选项时与 main 行为逐字节一致。
- 被否：无条件改 libs/qgis 依赖图（四个并行 worktree 共享该目录，最小化
  ABI/构建面）；给 app 引入独立 composition 编辑 UI（超范围）。
- 理由：与其他并行分支（尤其 cpp-build-packaging-hardening 触碰 app
  CMakeLists）冲突面最小；feature flag 是本仓库 CONV 惯例。

## D-06 — 报告契约：Python 键保形 + C++ 诊断超集
- 选择：`LayoutExportReport::to_dict` 逐一保形 Python 键（engine/path/format/
  dpi/ok/warnings/unmapped_elements/items/hybrid_items）；C++ 报告额外附
  `dimensions{width_px,height_px}`、`failure`、`filter_layers`（仅实际下发的
  图例过滤表）。
- 被否：只复刻 Python 键（丢掉任务要求的 dimensions / failure diagnostics）；
  改写 Python 键名（oracle 两侧失配）。
- 理由：oracle 重放冻结共有键；超集键只增不改，老消费者不受影响。

## D-07 — parity 契约：状态级比对 + by-construction 披露
- 选择：`screen_export_parity(canvas_state, export_state)` 内核纯函数比对
  extent/CRS/可见层集合与顺序/grid/legend 六个方面；style 与标注渲染注明
  `by_construction`（导出与画布共用同一 QgsProject 图层实例，符号权威唯一）。
- 被否：像素级颜色采样 parity（tests/test_qgis_screen_export_parity.py 的
  做法，需要两侧真实渲染产物，服务层无法在纯内核冻结）；只比对 extent。
- 理由：状态级比对可被 oracle 冻结且足以在导出前拦截 “画布≠导出” 的真实
  缺口；共享图层实例使 style 漂移在结构上不可能，如实披露即可。

## D-08 — CONV 编号取 27
- 选择：CONV-27。
- 理由：两个在开 PR（#1346 数据、#1348 workflow）都自称 CONV-26，取 27 避免
  账本/选项名三方碰撞。
