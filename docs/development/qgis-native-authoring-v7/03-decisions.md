# 03 — Decisions（裁决记录）

> 每条裁决给出：背景 / 备选 / 选择 / 理由。按时间顺序追加，编号复用。

## D1 运行时 PySide6 与编译期 Qt 版本解耦

- **背景**：本机（Windows）从零构建 vendored QGIS 4.2。`C:/deps/Qt/6.8.0`（msvc2022_64）是唯一现成 Qt dev 树；仓库 venv 惯例 PySide6 6.11.2（main 与并行 worktree 均如此）。
- **备选**：(a) venv 降 PySide6 6.8.0.1 与 Qt 6.8.0 完全对齐；(b) 装 Qt 6.11 dev + PySide6 6.11；(c) 编译期 Qt 6.8.0 + 运行时 PySide6 6.11.2。
- **选择**：**(c)**。
- **理由**：(a) 实测失败——app 代码（`process_hub.QtLogHandler` 等）依赖 PySide6 6.11 的 Signal.emit 宽松签名，6.8 下 TypeError 连锁炸壳（已复现 42 处失败）；(b) QGIS 4.2 官方支持代次是 Qt 6.4–6.8，6.11 编译风险高且 aqt 未必有配套；(c) Qt 官方支持「按旧版本构建、以新版本运行」的前向二进制兼容——桥与 qgis_*.dll 按 6.8 头编译，运行期绑定 PySide6 6.11 的 Qt DLL。全部 PySide6 侧测试在 6.11.2 下通过。

## D2 vendored QGIS 的 Windows 构建路径与依赖树

- **背景**：v5/v6 的 vendor build 在 Linux；Windows 无先例。`C:/deps` 已有半成品依赖树（Qt 6.8.0、QCA、QtKeychain、winflexbison、vcpkg）。
- **裁决**：
  1. 手动 cmake 配置（与 setup.py 相同 flag 集 + Windows 附加项）构建到本 worktree 默认路径 `native/qgis_render_bridge/build/qgis-vendor`；产物按 `PALEO_QGIS_REUSE_VENDOR` 官方约定向并行 worktree 开放复用，不重复构建。
  2. vcpkg classic 模式恢复 `installed/`（gdal/geos/proj/sqlite3/libzip/gsl/protobuf，全部二进制缓存秒级恢复）；`libzip` 为 QGIS `find_package(LibZip REQUIRED)` 硬依赖（基线包集缺失，本 Goal 补齐）。
  3. 关闭 `WITH_POSTGRESQL`、`WITH_EXIV2`、`WITH_SPATIALITE`（无 MSVC 包；桥不消费这些 provider）。`WITH_GSL=ON`（vcpkg 有）。
  4. QScintilla 不走 vcpkg（其 port 依赖自建 qtbase，9 分钟后失败）：用 vcpkg 下载源（Debian dfsg tarball，QScintilla 2.14.1）针对 Qt 6.8.0 以 qmake+nmake 构建，安装树 `C:/deps/qscintilla-install`（lib 名 `qscintilla2_qt6` 命中 QGIS FindQScintilla 名称表）。
  5. vendored QGIS 两处 Windows 补丁（`include(CheckFunctionExists)` 提升；补回上游 `platform/windows/rc/version.rc.in`），UPSTREAM.md 已记录。
  6. 构建环境从 bash 清洗 PATH 后经 vcvars64 注入（剥掉 anaconda——首次配置曾把 TIFF/protoc 解析到 conda 树，混链风险）。
- **教训记录**：首次配置把 Qt 前缀写成 `C:/Qt/6.8.0`（该目录只有 Tools），真实安装在 `C:/deps/Qt/6.8.0`——cmake 对不存在前缀静默零候选，错误信息误导性极强。

## D3 capability 快照的权威源 = C++ 编译期 manifest

- **背景**：基线探测散落 5+ 处且只测 importability。
- **备选**：(a) Python 侧 hasattr 探测拼装；(b) C++ `capability_manifest()` 编译期注册表，Python 派生。
- **选择**：**(b)**，`contract_version=2`。探测零成本（不 init QGIS 运行时）；旧桥（<0.3.0 无 manifest）→ `degraded` 带具体缺项，不伪造能力面。运行时健康验证仍归 `qgis_backend_probe`（渲染后端选择）——能力面与运行时健康是两个关注点。

## D4 evaluator 语义解释（Goal §4 矩阵落地）

1. **save_edits 需要 dirty**（Goal 原文 "editing AND dirty"）：改变基线行为（原先 editing 即 enabled）。`toggle_editing` 二次点击仍保存退出（controller 层语义不变）；测试 `test_toolbar_actions_track_editing_state` 已按新契约更新。
2. **split/merge 在 fallback 画布保持可用**：它们是命令（非画布交互），执行引擎 QGIS 优先、shapely 显式回退（vector_operations 既有路由）。能力探测影响的是「执行引擎」（记入 EditDelta.qgis_capability），不是可用性——禁用会让 headless 测试环境失去 split 能力，且 Goal §5 明确 fallback 服务于 headless/minimal testing。
3. **reshape 是 native-only**：交互 = 原生 addLine 数字化器（无新 C++ 工具 kind）+ 桥 `geometry.reshape`（QgsGeometry::reshapeGeometry，无 shapely 等价）。fallback 画布不提供（Goal §5：fallback 不获得 QGIS 路径没有的专业功能）。evaluator 要求 `qgis.native_tool.addLine` AND `qgis.geometry_op.reshape`。
4. **measure 双态**：manifest 声明 `measure` → 原生 PwbMeasureTool（QgsDistanceArea，地理 CRS+椭球时椭球测算——修正 Python `math.dist` 在地理系的科学错误）；旧桥 → 视口路由 fallback（保留，诚实降级）。display 模式放行 measure（只读检查工具）。
5. **snapping/topology 只需有活动图层即可切换**（基线要求 editing），对齐 QGIS 桌面（捕捉开关与编辑态解耦）。
6. **门禁判词优先**：`_role_gate` 优先用宿主注入的 `edit_gate_reason`（权威文本），`raw_locked/stage_locked` 分类标记只在其缺席时提供归类描述。

## D5 snapping 下推的能力门控（反静默漂移）

- endpoint → `Qgis::SnappingType::LineEndpoint`（vendored 4.2 支持）；intersection → `setIntersectionSnapping`。两者**只在 manifest features 声明后下推**：旧桥 parseSnappingTypes 会静默丢弃未知 type 字符串——静默语义漂移是 Goal 明令禁止的失败模式。grid 模式无 QGIS 对应物（Paleo 域构造），维持 Python-only（fallback 采点轨），不伪装下推。

## D6 native identify 的面板语义

- 原生 `QgsMapToolIdentifyFeature` 只回 (doc_id, feature_id)。面板条目从 CompositeEditController 图层记录（Python 权威）重建——不建第二数据源；多图层命中列举仍由 Python `identify_all` 提供（fallback 路径）。单命中 vs 多列的语义差异如实记录（本文件），不伪装收敛。

## D7 EditDelta 是审计契约，不是第二权威

- delta 从命令流**派生**（`_record` 钩子），compound 展平为逐操作 delta；undo/redo 不产生 delta（历史导航非新编辑）；rollback 整段作废 journal（与会话 `_journal` 的 None 语义对齐）。`source_tool` 后缀 `(native)`/`(python-fallback)` 区分执行路径；`qgis_capability` 为 manifest 稳定摘要（fallback = "unavailable"，诚实）。journal 上限 1024（防无界内存）。

## D8 工作站拓扑传播 = 编图页同语义 + 门禁过滤

- `composite_editing` 的 VertexTool 装配补上 `on_vertex_committed`（基线断线）。传播只向 `can_edit_layer` 放行的图层进行（`propagate_shared_vertex` 会为共享节点图层开 session——RAW/锁定图层绝不能因此获得脏会话）。传播覆盖全部编修图层（跨相邻要素边界），编图页语义是活动图层——工作站多图层语境下这是正确泛化，行为对齐点是无差别的「精确共享节点替换」。

## D9 阶段可见性单权威

- `apply_stage_tool_profile` 不再直改 QAction.setVisible；可见性统一经 ToolContext.hidden_by_stage_profile 由 evaluator 裁定（否则两个可见性权威会互相踩）。

## D10 vendored QGIS 源内符号（C++ 编辑工具）扩展约定

- PwbMeasureTool 复用 `PwbEditPickTool` 基类（snapOrRaw/Esc 语义免费获得）；工具实例 per-canvas 缓存（Qt parent=画布持有），回调经 `alive_token_` + `measure_callbacks` 表（与 select/identify 同防悬垂模式），destroyed 链回收进孤儿回调坟场。
- measure 工具在激活时钉死 QgsDistanceArea 的 CRS/椭球配置（shim 每次 set_map_tool 重建实例，画布 CRS 变更天然失效重建——与采点 scratch CRS 钉死语义一致）。
