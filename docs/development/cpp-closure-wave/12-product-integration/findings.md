# 12 — findings（主程序收口审计与实现发现）

<!-- 审计对象：产品入口全部 placeholder / null provider / deferred host、
     01–11 安装点、全局组合结构。每条注明证据位置与处置。 -->

## R1 产品入口 placeholder / deferred 审计（基线 06211541）

| # | 位置 | 现状 | 属主/处置 |
|---|---|---|---|
| 1 | `app_shell.cpp` save/open_sample/properties/preview_settings 四信号 | UI-17 deferred：`main_window.cpp wire_app_shell` 注释明确"no production handler" | **本线已收口**：shell_project_actions 模块 + wire_app_shell 接线（本轮） |
| 2 | `app_shell.cpp:134` CommandPalette 构造：context_provider 缺省、tool_details 未注入 | UI-17 deferred | **本线已收口**：set_context_provider（ui_shell 具名租约，additive setter）+ set_tool_details_provider（explain/format_details 真源） |
| 3 | `app_shell.cpp:47-100` `UnavailableJointHost`（joint engine host 缺） | 诚实占位 | 06 线（真实宿主），分支未合流；12 只登记，不复制 WIP |
| 4 | `app_shell.cpp:198` IReviewActions provider 返回 nullptr | 诚实守卫（页面"未绑定工程"） | 09 线（ProjectReviewActions），分支未合流 |
| 5 | `app_shell.cpp:203` PreparationPage PagePlaceholder | 诚实占位 | 08 线，未合流 |
| 6 | `app_shell.cpp:213` LocalVizProvider base_builder message 态（解析注册表 preview seam） | 诚实占位 | 04 线，未合流 |
| 7 | `app_shell.cpp:191` DataPage composite deferred（DataWorkspace 承载管理面） | 诚实占位 | 04 线，未合流 |
| 8 | `main_window.cpp:618`（旧行号）deferred 注释 | 与 #1 同源 | 本轮已删除该注释并以真实连接取代 |

## R2 接线语义的 Python 对齐（冻结参考）

- save：`project_controller._on_save_project` → 三阶段保存；#1126 语义
  （Ctrl+S 先把打开的编辑会话提交进工程）在 C++ 侧由
  `save_open_project` 先 `commitActiveLayer`（与 closeEvent Save 分支同
  stage_commit 路径）再走 `ProjectManager prepare/execute/commit`。
  **差异**：C++ 只提交活动图层会话（与既有 closeEvent 口径一致），Python
  flush 全部 composite 会话——多会话并行编辑属 CONV-27 面簇，不在本线扩界。
- open_sample：Python `bootstrap_sample_project` 扫描 data/ 目录 + catalog
  批量登记 + demo prediction。C++ 现有真实构件 = newProject 生产生命周期
  + run publish；**资源扫描登记为 01 线目录依赖**（findings #3 同理）。本
  线样例 = newProject("惠西南样例工程") + 内置 8 井 fixture 经真实 run
  lifecycle 发布为"样例井位"catalog 版本 + workspace 绑定持久化（重开还原
  由 platform.shell_project_actions 验证）。
- properties：逐字段对齐 `project_properties_text`（工程名称/区域/工程文
  件/资源数量/导出图件/显示坐标系/版本）。差异：Python"未保存"分支在 C++
  单会话契约下不可达，空态诚实回答"没有打开的工程"。
- preview_settings：Python 经 WorkflowController 弹 PreviewSettingsDialog
  （reader_panel 读写）。C++ UI-07 已有 PreviewSettings/Store/Panel，缺的
  只是应用级容器：`showPreviewSettingsRequested` 用平台统一 QSettings 注入
  Store（组 "preview/settings"），Panel apply→store.save→accept。
  **差异**：QDialog::open()（窗口模态、不阻塞 GUI 线程轮次，offscreen 可
  测）代替 exec()；Python 的 reader_panel 直连在 C++ 数据页宿主（04 线）
  合流前不存在，设置经由共享存储生效。

## R3 接线暴露的接口事实

- `ProjectSession::store()` 是 `IProjectStore*`（窄接口）；文档/协调器需
  经 `AppContext::projectStore()` 的 typed `PwbDataStore` 句柄。
- PublishReceiptV1 直接携带 asset_id/new_version_id——样例发布后无需扫描
  catalog 即可构造 workspace 绑定。
- workspace 绑定持久化链：`MappingWorkspaceState::from_json(document.
  mapping_workspace())` → `set_layer_binding` → `write_mapping_workspace(
  document.root(), state)` → 工程保存落盘；openProject 按
  snapshot.layer_bindings 物化工作副本（复用既有语义，零新 schema）。
- `libs/ui_controllers`（UI-14 ProjectController/WorkflowController Qt
  壳）在 apps/ 零消费。**决策**：本线不整绑两个 controller 核心（其
  refresh_shell/maintenance/catalog 线程面需要 01/02 合流后的生产服务），
  先以独立 shell_project_actions 模块收口四入口；controller 绑定在依赖
  合流后的第二轮进行（task_plan 已记）。这避免"绑定核心但缝全是空函数"
  的假接线。
- `pwb-platform` 原本不链接预览闭包：12 线装配块补 `Pwb::UiCanvas`（其
  PUBLIC 传递 `Pwb::UiPagesPreviewQt`，UI-15 PreviewSettingsDialog 复用）
  + `PWB_WITH_UI_PAGES_PREVIEW_QT` 定义；缺 target 时处理器与连接不编译，
  app-bar 的预览设置请求退化为无接收者的信号（无假 UI）。

## R4 环境事实（本主机 cachyos-linux）

- cmake 不在系统 PATH；共享工具链在 `/tmp/pwb-oracle-venv/bin`
  （cmake 4.4.3 / ninja 1.13）。构建一律经资源门包装。
- vendored QGIS SDK（`native/qgis_render_bridge/build/qgis-vendor`，主工
  作区共享 SDK 路径契约）曾中断于 2660/3000；output/ 已有
  libqgis_core/gui/analysis/native.so，余 369 步（WMS provider 尾部）。
  恢复构建被 08 线活动资源锁推迟（exit 75 → 排队退避）。SDK 为只读复用
  资产，供各线共享。
- 平台 app 编译与 platform.* 测试因此可在本地完成后进行（不再依赖 CI）。

## R5 矩阵与验收工具

- `tools/migration/pwb_closure_matrix.py`：各线
  `capability-matrix.json` → closure-matrix.md（四列矩阵 + 结构问题 +
  未登记线 + 协调登记）。单调门：wired⇒implemented，
  verified⇒wired+evidence（merged 由 PR/协调登记独立跟踪）。
  缺文件 = "未登记"显式行，空 capabilities = "空登记"问题行，不静默丢弃。
- `scripts/cpp-migration/audit-licenses.sh`：部署树 + SDK 前缀的许可材料
  审计（Qt6 许可集/QGIS COPYING（SDK 根缺→以 QGIS 源码树为源，部署时落
  licenses/）/WLE LICENSE/ONNX LICENSE/PROJ 数据）；组件缺失时 SKIP 显式
  呈现（子模块未检出=SKIP 而非 MISSING），材料缺失 FAIL。

## R6 无 Python 审计归类修订（audit-python-runtime-deps.sh）

- 基线 06211541 上复跑出现两类命中，均为**脚本归类滞后**，非新违例：
  1. `self_check.cpp:586`：dlopen 模式命中注释散文（"dlopened ... pulled
     a python"）→ 修法：纯注释行（//、/*、*）豁免；代码内尾部注释仍被扫。
  2. `libs/cartography/cartography_bind`：CONV-27 pybind 门面（由
     paleo_workbench/mapping/cartography_native.py 经 HAS_CPP dispatch 消
     费，与 mapping_bind 同类，不入产品二进制链接）→ 加入 compat seam
     白名单，由 --exe ldd 审计兜底验证。
- 复跑结果：源审计 clean（exit 0）；--exe ldd 审计待部署包二进制（诚实
  SKIP，见 acceptance.md）。
- 部署契约缺口：deploy-native-product.sh 原不收集许可材料 → 新增 4b 步：
  QGIS COPYING（源码树兜底）+ Qt6 许可集 + WLE/ORT LICENSE（存在时）+
  THIRD-PARTY-LICENSES.md 通知；audit-licenses.sh 为其验收门。

## R7 测试基础设施链接事实（审查+构建暴露）

- tests/cpp/platform/CMakeLists.txt 的 `PWB_APP_SERVICE_SOURCES` 是所有自
  编译 main_window.cpp 的测试目标的公共源集合（6 处消费）。main_window 的
  DATA_INTEGRATION 处理器引用 shell_project_actions 符号后，任何不链接该
  源的目标都会 link 失败（实际发生）→ 修法：在该集合上按 `TARGET Pwb::Data`
  条件统一追加（与 CONV-30 的 pwb_link_job_runtime 强制约定同一模式），
  而非逐目标补链。
- 本线新增测试目标 platform.shell_project_actions（根 CMake 装配块内，
  BUILD_TESTING 守卫）：空态诚实应答 / 样例引导（catalog 版本 + 绑定落盘
  + 会话契约拒绝二次引导）/ 保存-重开往返 / UI-15 预览设置容器经共享
  store 持久化。
