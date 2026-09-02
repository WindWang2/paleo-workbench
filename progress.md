# Progress — QGIS Authoring Core

## Files changed (branch feat/qgis-authoring-core)

### Native bridge (C++)
- `native/qgis_render_bridge/src/style_codec.{hpp,cpp}` — NEW: renderer XML
  round-trip, legacy spec → renderer builder (single/categorized/graduated/
  rule), dialog layer factory.
- `native/qgis_render_bridge/src/gui_service.{hpp,cpp}` — NEW: modal
  QgsRendererPropertiesDialog / QgsSymbolSelectorDialog /
  QgsStyleManagerDialog host; RAII session (mirror layer + QgsStyle).
- `native/qgis_render_bridge/src/geometry_service.{hpp,cpp}` — NEW: QGIS
  geometry ops, GeoJSON in/out.
- `native/qgis_render_bridge/src/qgis_render_bridge.{hpp,cpp}` — renderer_xml/
  labeling_xml/rules on VectorLayerSpec; mirror diagnostics counters;
  export_vector (SVG/PDF via CustomPainterJob); z-order fix (reverse layer
  list for QgsMapSettings).
- `native/qgis_render_bridge/src/bindings.cpp` — new API surface + dict-tolerant
  geometry args.
- `native/qgis_render_bridge/setup.py`, `CMakeLists.txt` — link qgis_gui +
  qgis_analysis + Qt6Svg; compile new modules.

### Python mapping
- `paleo_workbench/mapping/qgis_style.py` — NEW: QgisStylePayload,
  migrate_legacy_style, availability probe.
- `paleo_workbench/mapping/geometry_service.py` — NEW: QGIS-backed merge/split
  routed through VectorEditSession.
- `paleo_workbench/mapping/vector_operations.py` — routes to QGIS when built,
  Shapely kept as explicit fallback.
- `paleo_workbench/mapping/map_render_backend.py` — `_flatten_qgis_style`
  wire promotion; base/QGIS `export_map_body`.

### UI
- `paleo_workbench/ui/map_symbology_bridge.py` — NEW: native symbology dialog
  entry points (typed errors, payload bumping).
- `paleo_workbench/ui/map_layer_properties.py` — professional path: native
  editor button + renderer info; legacy form retained for no-bridge runtimes.
- `paleo_workbench/ui/pages/mapping_page.py` — features/fields passed to the
  properties dialog; `qgis_style` applied through the normal style path.
- `paleo_workbench/ui/unified_map_canvas.py` — SVG/PDF export prefers native
  map-body export (true vector) and paints decorations on top.

### Tests
NEW: test_qgis_style_payload.py (no bridge), test_qgis_authoring_codec.py,
test_qgis_rule_renderer.py, test_qgis_geometry_service.py,
test_qgis_geometry_edit_session.py, test_qgis_symbology_dialog_bridge.py,
test_qgis_style_revision.py, test_qgis_screen_export_parity.py,
test_qgis_visual_regression.py (4-layer geological scene: facies categorized,
fault rule, contour, wells+labels; composition/z-order/histogram/determinism).
UPDATED: test_map_layer_properties.py (legacy fixture + new QGIS-path test).

### Docs
- docs/adr/0059-qgis-authoring-core.md (new)

## Test status
- `-m qgis`: 63 passed, 2 skipped (pre-existing skips)
- focused suites: render backend / snapshot encoding / canvas / frame delivery /
  authoring / styles / layer tree / export worker / interaction / edit commands:
  all green except one PRE-EXISTING baseline failure documented below.
- full suite: running (see findings.md for baseline-failure policy)

## Benchmarks
- (pending)

## Known issues
- BASELINE (pre-existing on pristine origin/main, this machine):
  test_map_export_consistency.py::test_export_png_matches_screen_frame_and_
  carries_dpi_metadata fails with the fallback backend (screen frame blank at
  probes while export renders). Reproduces with branch changes stashed and in
  the main worktree. Not introduced here; not fixed here (surgical scope).

## Remaining
- benchmarks (10k/100k), full-suite triage, commit split, push, PR.

---

## 2026-09-02: Open Issues 清仓 + QGIS Workstation Convergence（feat/qgis-workstation-convergence）

### Open Issues（9/9 处理完毕）
- #1120 linked map canvas shutdown → WorkAreaMapWidget.shutdown + linked shutdown_workers + HomePage.shutdown_workers
- #1121 responsive inspector persistence → 保存按「可见」写 blob + restore 后重跑响应式 + user-hide 标志持久化
- #1122 DockTitleBar 停靠态拖出浮动（阈值撕出）+ featuresChanged + a11y + eventFilter 防御
- #1123 浮动专属 220×160 最小尺寸（topLevelChanged 切换）
- #1124 flush_layout 先于 hide；teardown 冻结 + 断信号；幂等 shutdown
- #1125 linked 恢复布局门闩（默认比例不覆盖已恢复状态）
- #1126 工程保存/切换 flush 编辑会话（提交 + 拓扑门禁 + 显示态一并落盘）
- #1127 14 项生命周期回归测试 + 12 项 review 回归测试
- #1128 Activity「历史」不再误开 Agent 日志 tab

### QGIS 收敛（Composite = 唯一未来主 GIS 工作区）
- CRS 权威链修复（_publish 不再写死 EPSG:4326）
- 图层属性 / 符号系统 / 标注：复用 MapLayerPropertiesDialog + symbology bridge（桥未构建走 legacy 快速字段；renderer XML 仍为权威）
- split / merge：geometry_service（QGIS）或 shapely 兜底 → VectorEditSession 命令
- topology：开关 + 保存门禁 + make-valid 修复（可撤销）
- 地质模板字段 schema（断层/相带/物源/展布/打断/方向/井点/范围）+ field_schema 持久化
- 属性表（QGIS 式窗口：行=要素、列=schema、双向选集、批量修改）
- Identify Results 多图层识别 + 定位缩放
- 捕捉配置（全局 + per-layer enable/vertex/segment/tolerance(px×比例)/priority + 井位参考点）
- 状态栏（CRS/范围/渲染器诚实显示/选择/编辑图层/捕捉）
- 联动工作区假按钮移除（选择/平移/测量/显示属性），域选择接线窗格聚焦

### 性能（fallback 渲染器，本机）
- 渲染基准 10k/50k/100k：首帧 1.2/5.2/11.2s，RSS 873MB@100k；快照热重建 0.1ms；帧缓存命中 ~0.04ms
- 交互路径：toggle/opacity 10k/50k 亚毫秒；100k ~22ms（可见性需重发快照，设计行为）；identify/snap 恒亚毫秒
- 数字化点击：120ms debounce + 修订缓存 → 100k 图层 10 连击 ~0.3s（原 ~23s）；save_edits 全量提交 100k ~4.3s
- 已知边界：会话内大图层每次 settle 仍全量重编码该图层（~230ms@100k）——增量快照列后续工作

### Review 循环
- 一轮：Blocker=1 / High=3 / Medium=5 / Low=9 → 全部修复（18 项）
- 二轮：修复全部确认正确；新增 Medium=1（undo 选集修剪）+ Low=5 → 已修复
- 终态：Blocker=0，High=0；149 项回归通过（预先存在的环境性失败不含其中）
