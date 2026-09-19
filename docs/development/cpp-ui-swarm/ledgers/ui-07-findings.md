# UI-07 findings — qt-preview（15 文件）

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `pages/table_preview_widget.py` | 虚拟化只读表：`TablePreviewModel`（深度列 mono-bold+主题高亮、曲线定义表 tag/unit 列格式、数值右对齐等宽、NaN 淡显）、1M-cell 截断、400 行采样 auto-fit、TSV copy_all + 选区复制 | `preview_table`（Qt-free：is_number/深度列/曲线定义检测/截断/TSV）+ `table_preview_model`/`table_preview_widget`（qt） | ported |
| `pages/text_preview_widget.py` | 只读等宽 QTextEdit，wrap 切换 + 字号 | `text_preview_widget`（qt） | ported |
| `pages/rich_text_preview_widget.py` | QTextBrowser：非 file 资源拦截、wrap/字号 | `rich_text_preview_widget`（qt）+ `url_filter::resource_scheme_allowed`（Qt-free scheme 判定） | ported |
| `pages/message_preview_widget.py` | 居中 word-wrap label | `message_preview_widget`（qt） | ported |
| `pages/json_tree_preview_widget.py` | 懒加载 JSON 树：collapse 阈值、64 层构建上限、2000/批哨兵节点、初始深度展开 | `json_tree_spec`（Qt-free 节点规格：label/kind/collapse/batch offset）+ `json_tree_preview_widget`（QTreeView） | ported |
| `pages/image_preview_widget.py` | 有界解码 2048、80ms resize debounce、zoom .1–8 ×1.25、pan clamp、视口窗口化绘制 | `image_zoom`（Qt-free：zoom clamp/pan clamp/virtual size）+ `image_preview_widget`（qt，自绘 paintEvent） | ported |
| `pages/pdf_preview_widget.py` | QPdfView 连续页 + 全页渲染滚动 fallback、zoom 10–800 ×1.25、fit page/width/custom、页码导航、copy-all-text 1MB 截断 | `pdf_zoom`（Qt-free：clamp/step/fit 迁移/页码状态）+ `pdf_preview_widget`（qt，`Qt6::Pdf` 可选 — 缺失时全页渲染 fallback） | ported |
| `pages/media_preview_widget.py` | 懒构造 QMediaPlayer/QAudioOutput/QVideoWidget、进度/音量滑条、后端与解码器 fallback、hide 即停 | `media_time`（Qt-free ms→mm:ss）+ `media_preview_widget`（qt，`Qt6::Multimedia` 可选 — 缺失时 "音频预览不可用" fallback） | ported |
| `pages/web_document_preview_widget.py` | 懒构造 QWebEngineView、仅本地 scheme（file/data/about/blob）请求与导航拦截 | `url_filter`（Qt-free scheme 白名单）+ `web_document_preview_widget`（qt，`Qt6::WebEngineWidgets` 可选 — 缺失时占位文本） | ported |
| `pages/seismic_slice_preview_widget.py` | 轴 combo（inline/crossline/time）、slider 范围 shape−1 取中、16ms 渲染 debounce、全局 stretch 复用、蓝-白-红 ramp、Indexed8 QImage | `seismic_slice_spec`（Qt-free：ramp/轴标签/slider 范围）+ `seismic_slice_preview_widget`（qt，走 `pwb::viz::ISeismicVolume::read_slice` + `map_slice_to_indexed8`） | ported |
| `pages/summary_table_preview_widget.py` | 双 tab：stat chips（井名/曲线数/采样点）、元数据+明细表分隔条、可选数据 tab | `summary_table_preview_widget`（qt）+ `summary_chips`（Qt-free：摘要行 → chip 值语义） | ported |
| `pages/geotiff_preview_widget.py` | 缩略图 + 属性/值 元数据表 | `geotiff_preview_widget`（qt） | ported |
| `pages/preview_widgets.py` | 再导出 facade + QtMultimedia 懒 getattr | — | retired（C++ 直引头文件；懒媒体 seam 内嵌 media widget） |
| `pages/preview_settings_panel.py` | 8 类设置编辑器（general/text/table/image/pdf/json/media/geoviz）、mode→category、apply→store+signal、reset→默认 | `preview_settings`（Qt-free：POD+ coercion+fingerprint+mode map）+ `preview_settings_panel`/`preview_settings_store`（qt，QSettings `preview/settings`） | ported |
| `pages/lazy_visualization_tabs.py` | 双 tab 懒可视化：数据列表 stack（table/text/well_log_summary）+ 可视 stack（prompt/loading/message/host）、切 tab 激活、no-steal 契约 | `lazy_tabs_state`（Qt-free 状态机）+ `lazy_visualization_tabs`（qt） | ported（host 注入 QWidget* — GeoVizPreviewHost 未转，geoviz 域） |

## 结构

`libs/ui_pages_preview/`（与 UI-06 同构）：

- **`pwb_ui_pages_preview`**（`Pwb::UiPagesPreview`）— Qt-free 语义核：
  `preview_settings`（全字段 POD + `_INTEGER_RANGES`/`_BOOLEAN_FIELDS` 强校验 +
  sha256-16 fingerprint + `_MODE_CATEGORY`）、`preview_table`（is_number/深度列/
  曲线定义/1M 截断/400 采样/TSV）、`json_tree_spec`（节点 kind+label+batch）、
  `pdf_zoom`（clamp 10–800/step 1.25/fit 迁移/页状态）、`image_zoom`（clamp
  .1–8/pan clamp/virtual size）、`media_time`（mm:ss）、`lazy_tabs_state`（状态机）、
  `seismic_slice_spec`（B-W-R ramp/slider 范围）、`url_filter`（web 导航 +
  rich-text 资源 scheme 白名单共用）、`summary_chips`。
- **`pwb_ui_pages_preview_qt`**（`Pwb::UiPagesPreviewQt`）— 15 个 widget 壳 +
  `preview_settings_store`（QSettings）。链 `Pwb::UiPagesPreview` +
  `Pwb::UiShellQt`（style_bind）+ `Pwb::PlatformServices`（theme tokens）+
  `Pwb::Viz`（地震切片）；`Qt6::Pdf/PdfWidgets`、`Qt6::Multimedia/MultimediaWidgets`、
  `Qt6::WebEngineWidgets` 各自 `find_package(QUIET)` + `PWB_HAVE_*` 宏降级 —
  镜像 Python 的 lazy/缺后端 fallback 纪律。

## Oracle（`tools/oracle/generate_ui_preview_fixtures.py`）

PySide6 缺失环境用 importlib 叶加载 + stub（同 ui_shell 先例）。冻结面：

1. **settings**：defaults→mapping/fingerprint、from_mapping 正/反例（未知键忽略、
   布尔非 bool→TypeError、整数越界→ValueError、pdf_fit_mode 非法→ValueError）、
   store load/save/reset 经 stub QSettings 往返、`_MODE_CATEGORY` 全 13 mode。
2. **table**：`_is_number` 判例、深度列检测（DEPT/DEPTH/深度/无）、曲线定义检测、
   1M-cell 截断 keep 数 + 提示文案、`copy_all` TSV、数值/NaN 对齐与角色判定。
3. **json_tree**：payload→首层节点描述（label `{object · N keys}`/`[N items]`/
   `[list · N]`/标量 str）、collapse 判定、64 层上限、batch offset 推进、哨兵文案。
4. **pdf_zoom**：zoom_in/out 序列→percent+fit_mode 迁移、clamp 边界、页状态
   `"n / m"`、prev/next enable。
5. **image_zoom**：set_zoom_factor 序列→clamped、fit_mode 置位、pan clamp 几何、
   virtual size。
6. **media**：`_ms` mm:ss 判例。
7. **lazy_tabs**：操作序列→（current widget 名、index、_requested、emit 次数）。
8. **seismic**：shape→slider max/midpoint、ramp 采样 RGBA。
9. **url/resource filter**：scheme 白名单判例。
10. **summary_chips**：摘要行→chip 值（井名/曲线数 N 条/采样点千分位）。
11. **negative self-check**：改一个期望值 → replay 必须 FAIL。

Replay：`ui_pages_preview.oracle_replay`；widget 面 `ui_pages_preview.qt_widgets_smoke`（offscreen）。

## 依赖与复用

- `pwb::ui_shell::style_bind` + `style_palette()` — QSS 绑法同 summary/seismic 的 Python 版。
- `pwb::platform_services` theme tokens — SPACE_*/RADIUS_*/FONT_FAMILY_MONO。
- `pwb::viz::ISeismicVolume` + `map_slice_to_indexed8` — 地震切片不重写拉伸核。
- **PreviewSettings**：`ui_data_core::PreviewSettings`（UI-03 `libs/ui_data_core`）不在
  本分支基线上，故本切片自带同名 POD（`pwb::ui_pages_preview::PreviewSettings`，
  字段/range/默认值逐字段对齐 `resources/preview_settings.py`）。两片同 main 后
  并存于不同 namespace；集成片做映射或归并 —— 记为已知偏离。

## Not ported / deferred

| 面 | 理由 |
|---|---|
| `GeoVizPreviewHost`（lazy tabs 的 host 主体） | geoviz 引擎域（viz/hosts），UI-10/集成片；本切片以 `QWidget*` 注入点承接，语义不变 |
| `preview_settings.py` 的 `PreviewSettingsStore` QSettings 身份 | Python 用 org `PaleoWorkbench`/app `paleo-workbench`；C++ 侧 `settings_application()` = `Workstation` —— 沿用平台身份（已持久化数据互通属集成片决定），store 类保持 group `preview/settings` 一致 |
| QtMultimedia/WebEngine/Pdf 的强依赖 | 全部 `PWB_HAVE_*` 守卫 + 文本 fallback（Python 同款降级路径） |
| 接线（preview panel 注册进资产详情） | W5 集成片域 |
| QGIS 专属测试目标 | UI-07 范围内没有 QgsMapCanvas 面（GeoViz host 已推迟）；地震重核经 `Pwb::Visualization` 真 `ISeismicVolume`/`map_slice_to_indexed8` 在 qt_widgets_smoke 内实走，无需 vendor-QGIS 测试夹具 |

## Oracle 驱动修正（replay/smoke 实测揪出的偏差）

| 位置 | 偏差 | 修正 |
|---|---|---|
| `media_time.cpp` | `ms/1000`、`s/60` C++ 截断除法 vs Python `//` 地板除 → `_ms(-500)` 应为 `"-1:59"` 而非 `"00:-1"` | `floor_div` 地板除 + `s - m*60` 取模 |
| `image_zoom.cpp` | `virtual_size`/`clamp_pan` 未处理 null pixmap 早退 `(0,0)` | 非正尺寸早退 `{0,0}` |
| `summary_chips` | Python chip 粘滞语义（缺 key 不覆写）被初版"缺 key 回默认"覆盖 | `SummaryChipValues` 字段改 `std::optional`，widget 仅在 has_value 时写入 |
| `lazy_tabs_state.cpp` | `show_error(retryable, activate)` 直接置 tab，漏掉 `_on_current_changed` 的 latch+emit 路径 | activate/was_visual 时改走 `tab_changed(1)`，可重试错误的 `_requested` 经 tab 路径锁存（fixture emitted 序列验证） |
| `pdf_preview_widget.cpp` ctor | 初版构造后未刷新页状态 → 后补 `update_page_status()` 又过正（"1 / 0"）→ 实测 Python `__init__` 在 document 存在时**不**调 `_update_page_status`，保持 "0 / 0" + 按钮默认 enabled 的怪癖 | 移除无条件刷新，按 document==nullptr 分支原样冻结怪癖态 |
| `preview_settings.cpp` | `fingerprint()` 曾按字段序拼 JSON，Python 是 `sort_keys=True` 紧凑串 + sha256[:16] | 键序排序 + 紧凑分隔符 + ASCII 转义，oracle `04e986d3aa5330c0` 通过 |
| `preview_table` | display/导出未 strip cell | `table_cell_text` 公共剥离（fixture `display`/`row_texts`/`copy_all` 验证） |
| `json_tree_spec.cpp` | 哨兵文案放错列（Python 在 key 列） | `sentinel_node().key` 承载文案 + `（点击左侧箭头加载）` 占位子节点 |

## 验证结果（linux-ninja preset，-j2）

- `ui_pages_preview.oracle_replay`：**24/24 PASS**（含 negative self-check —
  对 settings-fingerprint/media/table-truncation/json_tree-depth_cap/lazy_tabs
  5 个代表面各篡改一处期望值，replay 均检出失配）。
- `ui_pages_preview.qt_widgets_smoke`：**56 checks ALL PASS**，`QT_QPA_PLATFORM=offscreen`，
  含 teardown 父子/延迟删除安全、真 `QPdfDocument` 单页加载（嵌入 xref 正确的小 PDF）、
  真 `ISeismicVolume` 切片轴切换、QSettings 注入 store 往返、panel mode→category
  13 项映射、chip 粘滞、lazy-tab latch/emit/host 注入/engine-guard。
- CTest：`ui_pages_preview.*` 2/2 通过（TIMEOUT 120/180）。

## Oracle 生成器补注

`tools/oracle/generate_ui_preview_fixtures.py` 注入完整 PySide6 stub 套件（信号
同步发射、tab/stack 索引追踪、QStandardItemModel 真树、dict-QSettings、
`QPixmap.scaled` 真 KeepAspectRatio、`qRgba` 真打包）；`numpy` 用逐元素 list
stub（仅 widget 自身的 ramp/转置数学被走）；`seismic_3d_api`/`geoviz host`/
`preview_provider` 为 sentinel/stub（各自域有自己的 oracle/归属）。QtPdf/
QtMultimedia stub 走 `preview_widgets` facade 同一 seam，与 Python 测试
monkeypatch 路径等价。

## 冲突面声明

- 根 `CMakeLists.txt`：`if(PWB_BUILD_PLATFORM)` 块内 `add_subdirectory(libs/ui_pages_preview)`（ui_shell 之后）。
- `libs/qgis/CMakeLists.txt` 的 `Pwb::Domain` 守卫修复：仅当本构建命中该缺陷才施加（UI-01 已声明同款）。
