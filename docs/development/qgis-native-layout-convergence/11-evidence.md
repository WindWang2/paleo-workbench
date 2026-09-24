# 11 — 收敛证据（build/test/review/LOC）

基线：origin/main `192422c60`（PR #1481 合并后）· 分支 `feat/qgis-native-layout-composer-framework`
构建预设：`linux-native-product`（Ninja），vendored QGIS 4.2.0 SDK 只读复用，未重编 QGIS。

## Build

- `pwb_qgis`（含 6 个新 layout TU + AUTOMOC）编译链接通过。
- `pwb-platform` 链接通过；全量 254 个测试目标全部构建成功。
- 并行度全程 `-j4`（≤j6 上限）；GCC 16.2.1 随机 ICE（qfloat16/qpalette/qflags/std_function/map_edit_scene/qgscoordinatereferencesystem 等）以重试循环应对——同一目标重跑即过，非代码缺陷。

## Test（本地 ctest，无 CI 依赖）

最终回归：**254 个测试，251 通过**。失败 3 个（prediction.runtime / ui_data_core.import_oracle / closure_science.core）经在 pristine main 基线 build 目录复跑确认**为基线已有失败**（与 #1472 记录的 main 红同族），与本分支无关。

本方向新增/重写测试：

| ctest | 覆盖 | 结果 |
|---|---|---|
| `platform.layout_convergence`（新） | §1 structural：10 模板全部物化为 manager 注册的真实 QgsPrintLayout、原生 Map/Legend/ScaleBar/Label/Picture、slot 语义、模板 metadata、map 继承 session 层序；多布局共存；duplicate 保 slot + 不继承迁移锚（uuid rekey 用例）。§2 persistence：serialize→fresh session restore 几何/类型/z/slot 0.05mm 容差 roundtrip、幂等、clean 恢复。§3 migration：10 模板 legacy Composition→native（item 数含 grid 折叠/numeric 附加）、幂等 pin、unknown 元素→诚实 placeholder + verbatim 上报。§4 interaction：QUndoStack undo/redo、is_dirty/mark_saved。§5 atlas：50 feature coverage→50 页 PNG 全部落盘。§6 scale/lifecycle：120+ item 布局、3 次重复导出、preview 同引擎、close→serialize→fresh restore 保 120+ items | PASS 5.1s |
| `platform.export_layout`（重写） | 持久 layout PNG/PDF/SVG + 内容非空断言 + 未知格式 fail-closed + 像素预算拒绝 | PASS 0.9s |
| `platform.closure_mapping`（battery 重写） | 安装级：LayoutEditorPanel 挂载、模板物化进 session 权威、编辑器 refresh 选中、导出 SVG 真实文件 | PASS |

## Review

两轮独立评审（全新会话，逐行 + 对照 vendored QGIS 源码 + 本地编译实证）：

- **R1**：1 P0 / 4 P1 / 7 P2 / 6 P3。
- **R1→修复**：P0（删除布局空场景崩溃）、P1 全部（mark_saved 时机 fail-open、duplicate 丢 slot、pie 几何、compose 面板布局污染/预览错位）、P2 全部、P3 可直接修项。
- **R2（验证轮）**：12 项修复判定 10 项完全成立、2 项部分成立（graticule catch 类型无效 → **已修**：QgsCsException 不派生 std::exception，改专项 catch + 兜底；compose 替换粒度 → **已修**：用 LayoutInfo.dirty）。新发现 1 P1（同 catch 问题）+ 1 P2（布局脏不可见于关闭守卫 → **已修**：并入 anyDirtyEditSession）+ 10 P3（其中 8 项已修：门控对称、numeric id、atlas map extent 还原、零页守卫、死字段、多 grid 警告、失效 ifdef、拼写；2 项记录为已知限制：视图重挂载连接有界累积、slot item 无通用属性面板时的提示文案）。
- **终态：P0=0，P1=0；P2=0（R1/R2 所列全部处理）；P3 余 2 项外观级已知限制。**

## LOC / 依赖图变化

- 新增产品代码：`libs/qgis` layout 六件套 + `tests/cpp/platform/test_layout_convergence.cpp` ≈ **3980 行**（含测试）。
- 删除：`layout_service` + `composition_layout_service`（libs/qgis 双旧服务 4 文件）、`ui_seqviz` composition 三件套（panel/state/replay 6 文件）、`test_composition_export.cpp` ≈ **2690 行**；`closure_mapping_install.cpp` 2433→1383 行（registry 表/双引擎导出/帧缓存/live seams 删除）。
- git diff 总计：32 文件，+535 / −4427（已跟踪部分）+ 新文件 ~3500 行。
- `ui_seqviz` 链接闭包移除 `Pwb::MappingDocument` 与 `Qt6::Svg`；`Pwb::Qgis` 新增 `Pwb::MappingDocument`（模板语义 + 迁移读取的冻结角色）。

## QGIS 替代矩阵

| 旧自研 | QGIS 原生承载 |
|---|---|
| Composition/ComposerElement 几何/状态 | QgsLayoutItem（attemptMove/Resize、z、visibility、lock） |
| CompositionEditSession/CommandStack | QgsLayoutUndoStack→QUndoStack |
| composer_renderer SVG 引擎 | QgsLayout + 原生 items + PwbLayoutSlotItem |
| composer_export + Qt replay（QSvgRenderer/QPdfWriter） | QgsLayoutExporter（PDF/SVG/PNG 统一） |
| composer_templates 实例化 | LayoutAuthority::instantiate_template（同一声明语义 → 原生物化） |
| composition_layout_service/layout_spec_exec（瞬态 layout） | LayoutAuthority（QgsLayoutManager 持久注册）+ 直接导出 |
| flattened legend builder | QgsLayoutItemLegend（linked map + sync mode） |
| 自研 scale/north/grid 绘制 | QgsLayoutItemScaleBar / Picture(NorthArrow_02) / QgsLayoutItemMapGrid |
| CompositionPanel 表单编辑 | LayoutEditorPanel（QgsLayoutView+ rulers + 公共属性 widget + undo） |
| LayoutComposePanel 自绘预览 | 真实 layout QgsLayoutExporter 96dpi 渲染 |

## 退休清单 / 保留兼容层

- **删除**：上表全部旧产品路径；`closure_mapping_install` 的 registry 表、双引擎 export、帧缓存、`export_composition_async` 死声明。
- **保留（冻结 oracle/迁移输入）**：`libs/mapping_document` composer_renderer/composer_export/composer_templates（模板语义单一来源 + oracle 测试 + 迁移读取）；`libs/layout_export` + `native bridge layout_spec_exec`（pybind legacy 路径冻结，产品闭包不再链接）。
- **QPT 兼容**：layout 持久化为 writeLayoutXml 标准布局 XML，可与 QGIS 模板（.qpt）互通。

## 生命周期/规模证据

- close→serialize→reopen 恢复 120+ item 布局（测试 §6）；50 页 atlas 输出（§5）；多布局共存 + duplicate/remove（§1）；undo/redo + dirty→保存→clean（§4）。
- 保存流：`syncLayoutsOnSave`（prepare_save 前）→ `markLayoutsSaved`（commit_save 后）——失败路径保持 dirty（fail-closed）。
- 项目切换：openProject 无条件 restore；closeProject `layout().clear()`——跨工程零泄漏。

## 与并行 worktree 冲突矩阵

| Worktree | 交集 | 风险 |
|---|---|---|
| #1 shell（main_window.cpp/app_shell） | 均改 main_window.cpp/hpp（本分支：导出对话框重写 + layout hook + composition install binder） | 中：同文件不同 hunk，语义无交叠（shell 改 dock/action 装配区） |
| #2 layers | 无文件交集 | 低 |
| #3 data（libs/project/libs/data_suite） | 无改动（layouts 挂 root JSON，未动 libs/project） | 低 |
| #4 processing | 无文件交集 | 低 |
| 共享 | `cmake/PwbNativeProduct.cmake`（capability 表 CONV-29 行改义）、`libs/ui_seqviz/CMakeLists.txt` | 低：机械冲突，意图一致（各分支均收敛到 QGIS 原生） |
