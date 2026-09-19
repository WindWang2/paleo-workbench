# UI-16 findings — visualqa-misc（7 Python 源 → 5 核 + 3 壳 + 检查语义层）

Branch: `feat/cpp-ui-visualqa`（base `7bf29aae` — 含 UI-08 mapedit /
UI-09 wellseis / UI-10 seqviz / UI-11 review / UI-12 workstation /
UI-14 root controllers）。Worktree: `../worktrees/cpp-ui-visualqa`。
切片 UI-16 of the M10 UI→C++ migration：视觉 QA 收尾簇 ——
`visual_qa_v6..v11.py` 六个版本累积的截图/检查 harness 语义 +
`prototypes/proto_dual_volume_overlay.py` 非生产双体数据叠加原型。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `visual_qa_v6.py` | 6 态注册表；编图三阶段（stage dock show/raise → set_stage → settle 200ms）；命令面板上下文（phase1 + `filter_input="单因素"`）；WRITE 授权对话框（`WRITE_GRANT_ACTION_IDS=("map.add_layer","map.export")`，agent seam 建 dialog）；状态栏 workbench 段（`ui_context_service.refresh()`） | `kV6States` + `write_grant_action_ids`/`palette_context_filter` 常量 + `v6_checks` + `qa_driver` 六个 `drive_*` | ported |
| `visual_qa_v7.py` | 8 态；`_add_layer` 四路径（create_layer + set_membership + set_active_layer + sync_action_state → `QaLayerSpec` seam 单点）；工具可用性检查；图层树装饰（frozen maturity + sync_composition_now）；取消中任务（submit → 300ms → cancel → task dock）；toolbar 溢出宿主行；Inspector factor 竞态 settle 400ms 后显式 `_inspect_layer_selection` | `kV7States` + `v7_checks` + `VisualQaProbe::add_layer(QaLayerSpec)`/`submit_cancellable`/`cancel_task`/`enforce_toolbar_rows`/`inspect_layer` seams + `drive_*` | ported |
| `visual_qa_v8.py` | 6 态；空工程工具面（none_factory — `needs_project=false` 唯一条目）；派生图层 dirty 编辑；冻结成果；palette disabled reason；native activation 失败回退；阻塞任务工具面 | `kV8States`（`v8_shot_table` 保 needs_project 标记）+ `v8_checks` + `drive_*` | ported |
| `visual_qa_v9.py` | 6 态；响应式工作站（prime → resize → settle）；dock 几何守恒（preset_visibility_only：before 快照 → apply preset → 校验；agent_grow_only：resize 420 → show_agent） | `kV9States` + `v9_checks` + `VisualQaProbe::{apply_preset,show_agent_panel,dock_geometry}` seams + `drive_*` | ported |
| `visual_qa_v10.py` | 10 态；专业编制 UX —— raw 只读、捕获 preferred line role、editing dirty chip、snapping 细节、topology error chip、CRS 未声明/不匹配告警、冻结层面、canvas 上下文菜单 parity、1366 compact toolbar 身份 | `kV10States` + `v10_checks` + `drive_*` | ported |
| `visual_qa_v11.py` | 13 场景注册表；`_SCENARIO_BUILDERS` → 真部件（prediction task panel/seismic context toolbar/inspector/task center/command palette/state surfaces）+ 注入面（app shell/data page/stage bar+panel）；`scenario_needs_workstation_shell` 闸门；inspector version/run payload fixtures；theme matrix（light/dark × 1280×720/1920×1080） | `kV11Scenarios` + `v11_checks`（52 检查语义）+ `qt/scenario_host`（`ScenarioSeams` + 13 `build_*` + `run_scenario_checks`） | ported |
| `proto_dual_volume_overlay.py` | 合成 amplitude/coherence 3D 体（endpoint-inclusive linspace）；inline/crossline/time 切片（clamped index，`(x*ny+y)*nz+z` 序）；alpha blend / RGB fusion / coherence-mask 三渲染变体；uint8 clip+trunc | `dual_volume`（`SynthVolume`/`slice_*`/`render_*`，Qt-free 数学）+ Qt `DualVolumeOverlayWidget`/`ProtoDualVolumeWindow`（axis combo/slice+opacity+threshold slider/variant radios/QPixmap 渲染/状态读出） | ported |

## 结构

`libs/ui_visualqa/`（两 target，同 UI-09..14 先例）：

- **`pwb_ui_visualqa`**（`Pwb::UiVisualqa`，STATIC，Qt-free）—
  4 TU：`qa_check`（`CheckResult`/payload→JSON）、`qa_states`
  （V6–V11 注册表 + 常量 + shot 表）、`qa_checks`（全部纯检查语义，
  `run_state_checks`/`run_scenario_checks` 按名分派）、
  `dual_volume`（合成体 + 切片 + 三渲染变体）。PUBLIC `Pwb::Domain`
  （ordered JSON）、PRIVATE `Pwb::ToolPolicy`（工具可用性权威）。
- **`pwb_ui_visualqa_qt`**（`Pwb::UiVisualqaQt`，AUTOMOC，需
  `Qt6::Widgets`）— 3 TU：`qa_driver`（`settle()` =
  QEventLoop+QTimer+processEvents；V6–V10 `drive_*`；驱动分派表；
  `run_state_checks` probe 绑定版）、`scenario_host`（V11 构建器 +
  seam 闸）、`dual_volume_overlay`（部件 + host window）。

## Seam 约定（不移植不伪造）

| seam | 宿主面 | 空值语义 |
|---|---|---|
| `VisualQaProbe`（抽象） | 工作站壳全表面（stages/layers/tools/docks/palette/dialog/status/agent/scheduler/geometry…） | `run_state_checks` 未绑 → 每态产出 `surface_available=false` + `drive_state=false` 检查；绝不伪造 |
| `QaShellSurface` | AppShell（V11 `first_open_empty_shell` 等需全壳的场景） | 未注入 → 场景检查报 `surface_available=false` |
| `QaDataPageSurface` | DataPage（`data_manager_surface`） | 同上 |
| `QaStageSurface` | MappingStageBar+Panel（`stage_bar_phase*`、palette 场景 action card 宿主） | 同上；stage action 词表经 `ScenarioSeams::stage_actions` 注入 —— **不重复造表**，权威仍是 `pwb::tool_policy::stages`/`ui_workstation::stage_actions` |
| 重型引擎 | 地震/体渲染引擎 | 双体原型刻意保持合成自含（Python 源本就是内存生成体），不冒称生产集成 |

Fail-closed 细则：缺 action → `exists=false`；缺 tool →
`exists=false`；缺 dock → hidden；缺场景段 → failing check；
未知态名 → 空检查向量 + `drive_state=false`；未知场景 →
`std::invalid_argument`（Python `KeyError` 意图）。

## Divergence note（有意偏差，已注记）

- `scenario_needs_workstation_shell`：Python 对
  `("first_open_empty_shell","command_palette_disabled_reason")`
  返 true；C++ 仅 `first_open_empty_shell` —— palette 场景直接构建
  真 `CommandPalette` + `CommandRegistry` 评估器（Python 壳接线的
  正是该权威裁决路径），无需整壳。
- C++ 新增 `surface_available`/`snapshot missing` 等基础设施检查名
  —— seam 未绑时的诚实标记，Python 侧靠异常路径隐式表达。

## 构建说明

- 根 `CMakeLists.txt` UI-16 块在 UI-14 之后、CONV-04 之前；门条件
  `PWB_BUILD_PLATFORM AND TARGET Qt6::Widgets AND TARGET
  Pwb::UiShellQt AND Pwb::UiWellseisQt AND Pwb::UiWorkstationQt AND
  Pwb::UiWidgets AND Pwb::PlatformServices AND Pwb::ToolPolicy AND
  Pwb::Domain`，未满足 → STATUS 提示跳过（Python harness 仍是生产路径）。
- 配置（本机 cmake/ninja/ctest 在 `/tmp/pwb-oracle-venv/bin/`；QGIS
  兄弟路径需显式覆盖）：

  ```bash
  /tmp/pwb-oracle-venv/bin/cmake --preset linux-ninja \
    -DPALEO_QGIS_SOURCE_DIR=.../third_party/qgis \
    -DPALEO_QGIS_SDK_DIR=.../native/qgis_render_bridge/build/qgis-vendor/output \
    -DPALEO_QGIS_BUILD_DIR=.../native/qgis_render_bridge/build/qgis-vendor
  /tmp/pwb-oracle-venv/bin/cmake --build build/presets/linux-ninja \
    --target ui_visualqa.core_smoke ui_visualqa.qt_widgets_smoke
  /tmp/pwb-oracle-venv/bin/ctest --test-dir build/presets/linux-ninja \
    -R 'ui_visualqa\.' --output-on-failure
  ```

## 验证

- `ui_visualqa.core_smoke`（27 案例，Qt-free）：V6–V11 注册表逐字
  parity、`make_check` 词表、未绑 probe fail-closed、未知态空向量、
  V6 stage/write-grant、V7 cancelling、V8 empty/blocking、V9
  compact/preset、V10 CRS/frozen/raw/dirty、V11 task/seismic/
  stage/task-center/palette/theme-matrix/unknown、合成体维度+索引
  序、切片提取、alpha blend、RGB fusion、threshold mask、axis/
  variant 词表 —— **全过**。
- `ui_visualqa.qt_widgets_smoke`（16 案例，offscreen）：36 态驱动
  分派全覆盖、未绑 probe fail-closed、V6–V10 fake-probe 端到端、
  13 场景分派覆盖、未知场景抛 `invalid_argument`、未绑 seam
  unavailable、seam-backed 场景、真部件场景、palette 场景（含
  stage 词表注入）、theme matrix 双主题双尺寸、双体窗口 smoke
  —— **全过**。
- `ctest -R ui_visualqa` 2/2 通过。

## 修缺记录（构建/测试期暴露）

| 位置 | 问题 | 修法 |
|---|---|---|
| `core_smoke_test.cpp` 首版 | 尾部片段损坏（拼接错位） | 检视尾部后重写末段（合成体/切片/渲染/词表断言） |
| `qt_widgets_smoke_test.cpp` fake probe | `layers[selected]` 空串键隐式插空 map 项 | 改 `find()`，仅命中才改 |
| `theme_matrix` 采样 | fake stage 面近平板 QWidget → 采样网格仅 1 色 | 加 side-by-side 全高 styled frame/子面，保证 ≥2 色入样 |
| 测试运行时 | Qt/QGIS 依赖库（libodbc/libcryptopp/libblosc/libqhull_r/libxerces/libgeotiff/libmuparser/libspatialite…）不在默认 loader 路径 | 测试 CMake `ENVIRONMENT_MODIFICATION` prepend `PALEO_QGIS_RUNTIME`/`PWB_QT_RUNTIME`/`LD_LIBRARY_PATH` + `QT_QPA_PLATFORM=offscreen` |
| 配置 | `cmake/PwbQgisSdk.cmake` 默认兄弟路径 `<repo>/../main` 与实机 `~/project/paleo-workbench` 不符 | `-DPALEO_QGIS_{SOURCE,SDK,BUILD}_DIR` 显式覆盖（cache-overridable，未改 SDK 检查） |
| PATH | 系统无 `cmake` | 全程用 `/tmp/pwb-oracle-venv/bin/{cmake,ctest,ninja}` |

## 已知缺口（留给集成切片）

- `VisualQaProbe`/`QaShellSurface`/`QaDataPageSurface`/`QaStageSurface`
  生产适配待应用壳集成切片 —— 当前测试注入 fake；未绑一律
  fail-closed 而非伪造。
- 双体原型渲染仍走 `QPixmap`+CPU raster（Python parity）；生产体
  渲染归 seismic/volume 引擎切片，不在本切片重实现。
- V11 `theme_matrix` 用注入 stage surface 采样 —— 真 MappingStageBar
  主题矩阵验证待其移植后接入。
