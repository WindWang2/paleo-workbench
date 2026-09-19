# UI-15 findings — root canvas（8 Python 源 → 7 核 + 7 壳 + 3 QGIS 面）

Branch: `feat/cpp-ui-root-canvas`（base `origin/main` `7bf29aae`）。
Worktree: `../worktrees/cpp-ui-root-canvas`。切片 UI-15 of the M10
UI→C++ migration：统一/原生地图画布 + 图层树 + 图层属性 +
原生符号学桥 + 地图导出 worker + 预览设置对话框。
应用壳接线（app_shell 集成）不在本切片 —— 一律注入 seam，绝不伪造
页面。综合编修继续硬依赖 `QgisCanvasShim`/`QgsMapCanvas`/`mapstack`
（不动）；本切片交付的 `UnifiedMapCanvas` 是无桥/CI 回退面。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `unified_map_canvas.py` | `_sanitize_extent`（finite/换轴/1% 退化补边 #1166）、`fit_extent_to_aspect`/`_letterboxed_extent`（#522 等比信框）、`_default_export_height`（view 纵横比 → [64,16000]，退化 →1600）、`_snapshot_signature` 去重键（crs+id+type+双 revision+visible+round(opacity,6)+scale_range+source_version_id — features/style 不入键）、`snapshot_source_version_ids`（dict.fromkeys 序）、100 条 extent history、`screen_to_map`/`map_to_screen`（退化 → None/画布中心）、pan/zoom/wheel（指针锚定）、空格拖拽平移、tool-controller 回调（非编辑权威）、selection/capture/snap overlay 绘制（snap 解析失败 → 早退）、`"key_up"` 式键名（非 `QKeySequence` 名）、shared `paint_map_decorations`/`palette_token` chrome、PNG/SVG/PDF 导出（vector 导后 backend 态保留）、`_image_buffer` 帧所有权 | `map_render_backend`（Qt-free：`Extent`/snapshot/Frame records + 纯函数 + `MapRenderBackend` ABC + factory registry）+ `UnifiedMapCanvas`（Qt 壳 + `MapToolController`/`OverlayProvider`/`VectorPaintCapableBackend` seam） | ported |
| `native_map_canvas.py` | `MapScene` 观察者为唯一合成权威；scene 替换 epoch++ 使全部在途 raster 失效；raster cache 键 `(data_revision, style_revision)`；完成图仅在 scene epoch+layer id+raster key+scalar 指针四者仍吻合时落账；raster 失败按 `(layer_id, key)` 每实例去重记 #897；`fit_to_scene` 4% 边距；有效可见层×opacity 绘制 raster/contour/point；交互异步取图、`prepare_for_export` 同步补齐；close/shutdown 关 controller | `layer_scene`（`NativeMapScene`/`IScalarRasterSource`/`RasterKey`/`RasterImage`/Contour/Point — 内嵌权威 `LayerRegistry` TU）+ `NativeMapCanvas` | ported |
| `native_render_worker.py` | `OwnedWorkerJob` 语义：单活跃后台 raster；latest-request-per-layer（他层请求不丢本层有用在途件）；同层 revision 变更协作取消投递（绝不强停 native raster）；stale 结果按请求身份拒绝；shutdown 有界可 detach（#1042）；FIFO pending 按原槽序 | `NativeRasterRequestController`（`JobScheduler` 单 lane + `JobOwner`；`desired_`/`pending_order_`/`active_`；完成回调里 `dispatch_next()`，不靠 `released` 做正常续派） | ported |
| `native_layer_tree.py` | 每个请求都对权威 `LayerRegistry` 现解（无影子节点/影子态）；display 序=registry 反序；active-layer 选择保留；add/remove/move/group/zoom/properties/export 动作；drag/drop 父解析+绝对 z-index（非组落点→其父、row<0→append、clamp、越末 → z0、空 siblings → 顶）；组 id `f"group_{uuid4().hex[:12]}"`；共享 icon factory + spacing 常量；上下文菜单 enablement parity | `layer_tree_core`（`display_children`/`resolve_drop`）+ `NativeLayerModel`（QAbstractItemModel，token↔id）+ `NativeLayerTree`（QFrame+QTreeView+QAction 面） | ported |
| `map_layer_properties.py` | 不持平行层态：widget→`PropertiesForm`→payload；scalar/legacy/qgis 三路径；QGIS Apply 保留既有 label 配置（#929）；Classes JSON 行内校验（#426，parse 失败不动现行 renderer）；空名回落 layer_id | `layer_properties_core`（`PropertiesForm`/`build_properties_payload`/`classes_json_error`）+ `MapLayerPropertiesDialog`（General/Source/Symbology 三 tab + `SymbologyHooks` 注入缝 — qt target 不链 qgis target） | ported |
| `map_symbology_bridge.py` | 原生 `QgsRendererPropertiesDialog`/`QgsSymbolSelectorDialog`/`QgsStyleManagerDialog`；geometry 由 feature.geometry.type 首知值定（默认 Polygon）；#937-2 空 categorized/graduated → "single"；#937-3 labeling_xml 透传；legacy 平铺 style → renderer_xml 迁移；payload revision+1；空 renderer → `SymbologyBridgeError`；`{"qgis_style","opacity"}` 结果形 | `symbology_core`（`geometry_type_for_features`/`normalize_dialog_style`/`SymbologyRequest`/`apply_dialog_result`/`apply_symbol_result`）+ `qgis_symbology_bridge`（gui_service 对话宿主 + `symbology_renderer_info`） | ported |
| `map_export_worker.py` | `render_and_save_map_export`：prefer_native → throwaway QGIS backend render_sync（失败 → degrade 记录 + fallback 渲染，#923 honest engine）；cancel 检查点恰三处（native 后/fallback 后/decorations 后 save 前 — #1224）；`QImage(...).copy()`+`paint_map_decorations`（dpi→`device_px_per_logical_px`）；PNG 写失败 → runtime_error；`snapshot_map_export`/`unified_map_canvas_from` duck-walk；partial 文件全清（#937-11/#852）；worker=JobScheduler+JobOwner，`finished/failed/cancelled` | `export_core`（`MapExportSpec`/`MapExportReport`/`ExportCancelled`/`make_export_spec`/`discard_partial_export_file`）+ `MapExportWorker` + `render_and_save_map_export`/`snapshot_map_export`/`unified_map_canvas_from` | ported |
| `preview_settings_dialog.py` | modal 容器包既有共享 panel；中文题 `"预览设置"`；min-width 520；legacy `SPACE_4`=20 margin；Apply 才 accept、Reset 不关；settings_applied 转发 | `PreviewSettingsDialog`（wrap `Pwb::UiPagesPreviewQt` panel — panel 增 `apply_button()`/`reset_button()` 公共访问器） | ported |
| `mapping/map_render_backend.py`（消费契约）+ `qgis_render_bridge` bindings | `QgisMapRenderBackend`：`set_layer_snapshot` eager/pending 推 native payload；`request_render` coalesce 最新代 + `take_completed_frame` 守新代；`render_sync`/`export_map_body` 同步；**#932 stale-delta** → 全量 reship+retry 一次；encoder 缓存保留 + 移除层 prune；shutdown 清桥+encoder；`parse_layers`/`legacy_style_to_renderer_xml`/`renderer_info` | `snapshot_encoder`（Qt-free 编码+feature 复用/delta/stale-delta 判定）+ `snapshot_codec`（Json→`VectorLayerSpec` + legacy 迁移 + renderer_info）+ `QgisSnapshotRenderBackend` + `install_qgis_backend_factory`/`qgis_backend_probe` | ported |

## 结构

`libs/ui_canvas/`（三 target + 测试，同 ui_widgets/ui_map 先例）：

- **`pwb_ui_canvas_core`**（`Pwb::UiCanvasCore`，STATIC，Qt-free）—
  7 TU：`map_render_backend`、`layer_scene`、`layer_tree_core`、
  `layer_properties_core`、`symbology_core`、`export_core`、
  `snapshot_encoder`；**外加 vendored `native/layer_model_core/src/
  layer_model.cpp`**（权威 `LayerRegistry`/`MapLayer` — 与 pybind
  extension 编译同一 TU，无 pybind、纯 STL）。PUBLIC 链
  `Pwb::Domain`/`Pwb::UiMap`/`Pwb::Cartography`。
- **`pwb_ui_canvas`**（`Pwb::UiCanvas`，AUTOMOC，需 `Qt6::Widgets` +
  `Pwb::UiWidgets` + `Pwb::UiPagesPreviewQt` + `Pwb::JobQt`）— 7 TU：
  `unified_map_canvas`、`native_map_canvas`、
  `native_raster_controller`、`native_layer_tree`、
  `map_layer_properties`、`map_export_worker`、
  `preview_settings_dialog` + `qt_meta.hpp` metatype 声明 +
  私有 `json_variant.hpp`。
- **`pwb_ui_canvas_qgis`**（`Pwb::UiCanvasQgis`，AUTOMOC，仅在
  `Pwb::Qgis` 已准入处）— 3 TU + **vendored bridge TUs**
  `qgis_render_bridge.cpp`/`style_codec.cpp`/`gui_service.cpp`
  （single-authority 复用，同 CONV-29 `layout_spec_exec` 先例）；
  `PALEO_QGIS_PREFIX_PATH="${PALEO_QGIS_SDK_DIR}"` 烘焙。

根 `CMakeLists.txt`：UI-15 块追加于 UI-14 之后、CONV-04 之前；
`Pwb::Cartography` 缺失时 `pwb_add_subdirectory_once` 补入；
不满足门槛 → STATUS 提示（Python 面仍为生产路径）。

## 语义/parity 决策（含 issue 引用）

- **#426** Classes JSON 校验在行内（`classes_error_label`），parse
  失败 → payload 不写 categories/ranges 但其余合法变更照走。
- **#522** 所有等比/信框计算走 `fit_extent_to_aspect`/
  `letterboxed_extent`（isclose rel_tol=1e-3 直通）。
- **#852/#1224/#937-11** 导出取消只在三 checkpoint 生效
  （non-interruptible render）；任何非成功结局删 partial 文件。
- **#897** raster 失败日志按 `(layer_id, RasterKey)` **每实例**去重
  —— 无 static/global 抑制。
- **#923** `prefer_native_renderer` 只由 live canvas backend 名
  `"qgis"` 触发；native 失败 degrade 后 `report.engine` 仍记
  `"fallback"`，绝不冒充 QGIS 导出。
- **#929/#937-3** QGIS Apply/symbol accept 时既有 `labels`/
  `labeling_xml` 透传，不被新 renderer 覆盖。
- **#932/#941-6** encoder 缓存（feature_payloads/feature_entries/
  shipped_revisions/force_full_ids）由 backend 持有；delta 仅在
  mirror 确持上一 revision 且 delta<full 时走；stale-delta 异常 →
  全量 reship 一次；不再出现的 vector 层 cache 随快照 prune。
- **#937-2** categorized/graduated 无 field 且无 fields →
  `"single"` 迁移；有 field 无分类 → 首 feature 属性 seed_values（≤8）。
- **#1042** `shutdown(wait_ms)` 返回 join 成败；超时 detach 进
  `DetachedJobKeeper`，canvas/export 据此闸口。
- **#1166** `map_to_screen` 退化 extent → `nullopt`（Qt 壳画中心点）。
- `JobOwner::released` **不是**正常完成回调 —— raster controller
  在正常 finished 投递里 `dispatch_next()`，scheduler 先置 terminal
  再放行下一件（单 owner 语义不破）。
- 键名 parity：`Qt::Key_*` 显式映射 → `"key_up"` 等（`Qt.Key.name
  .lower()` 而非 `QKeySequence.toString`）。
- snap_point overlay：畸形值解析失败 → 静默早退（Python except 早退
  parity），绝不抛出。
- `BackendFactory` 为裸函数指针（`std::shared_ptr<MapRenderBackend>(*)()`）
  —— 测试工厂以 static/无捕获 lambda 注入；`is_qgis` 标记仅供
  `create_native_map_render_backend`/`prefer_qgis` 使用。

## 测试

`libs/ui_canvas/ui_canvas_tests/`（ctest 名 `ui_canvas.*`）：

- `ui_canvas.core_smoke` — 25 checks：extent sanitize/fit/letterbox、
  export height、signature/source-version、坐标换算、backend base
  校验+同步帧、factory 选择+native 守卫、display/drop、三种
  properties payload、classes 校验、normalize/geometry/request/
  apply、export spec/清理、WKT、encoder 全量/复用/delta/prune/
  stale-delta。
- `ui_canvas.qt_widgets_smoke` — 11 checks（`QT_QPA_PLATFORM=
  offscreen`）：unified backend status/帧投递/去重、导航+history、
  export snapshot+duck-walk、export worker degrade+PNG+cancel
  checkpoint、native canvas scene/raster cache/4% 边距、raster
  controller desired/invalidate/shutdown、tree 反序/父解析/active/
  group-id、properties dialog payload+行内校验、preview dialog
  modal/title/宽度。
- `ui_canvas.qgis_smoke` — 6 checks（真 vendored QGIS runtime，
  `standalone_test` 惯例：`QApplication` + 桥自举 initQgis）：
  codec spec 转换/缺键抛错、legacy→renderer_xml+renderer_info、
  snapshot backend render_sync 160²/SVG 落盘/幂等 shutdown、
  probe+factory→"qgis" backend、symbology probe。

结果：`ctest -R "ui_canvas|ui_map|ui_pages_preview"` **8/8 全绿**
（core 25 + qt 11 + qgis 6 + ui_map 3 + preview 2 无回归）。

## 边界（不做/不伪造）

- 综合编修/层树/属性对话框的 QGIS 原生面（`QgisCanvasShim`、
  `QgisLayerTreePanel`、`exec_layer_properties`）不动 —— 本切片
  symbology bridge 供 `MapLayerPropertiesDialog` 经 `SymbologyHooks`
  注入使用。
- 应用壳（app_shell）接线不在此切片；`UnifiedMapCanvas` 构造允许
  注入 backend（host/test double），无 backend 时走 factory
  registry（`Pwb::UiCanvasQgis` 存在时 `install_qgis_backend_factory`
  已注册 qgis 面）。
- 具体 fallback renderer（`FallbackMapRenderBackend`）属 mapping
  切片 —— factory 未注册时 canvas/导出诚实失败（`create_map_render_
  backend` 抛出，Python selector parity），绝不静默产空图。
- 无影子层态：tree model/properties dialog 只读 `LayerRegistry`/
  `LayerView`，绝不复制可变状态。

## 已知限制

- `QgisSnapshotRenderBackend::request_render` 为异步并行 job —— 无
  事件循环时 `render_active` 滞留、`take_completed_frame` 不投递
  （#938-5 桥契约；canvas 经 `QTimer` poll 泵 GUI 循环，正常路径不触）。
- `open_renderer_properties`/`open_symbol_selector`/`open_style_manager`
  为模态原生对话框 —— 冒烟不测对话交互本身（无人驱动），只测
  probe/codec/请求整形。
