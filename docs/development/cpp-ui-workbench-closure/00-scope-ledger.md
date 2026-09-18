# CONV-27 — Qt6/QGIS 原生 UI 工作站闭环（feat/cpp-qgis-ui-workbench-closure）

**Base**: `origin/main` @ `ff67dcf3`（CONV-25 合并后）
**Worktree**: `../worktrees/cpp-qgis-ui-workbench-closure`
**启动**: 2026-09-18

## 目标与用户流程

把 Python/PySide6 工作站最关键的专业 UI 工作流迁到现有 C++ Qt6/QGIS 平台，
形成真正可用的 C++ 原生地学编图工作站。验收流程：

```
打开 C++ 工作站 → 打开项目 → 加载图层 → 预测层显示 → 切换约束阶段
→ 编辑矢量约束 → 生成/显示单因素图 → 进入综合编图 → 图层管理/样式
→ 保存项目
```

关键 UI 逻辑不依赖 PySide6。

## Scope Ledger — 本分支负责

1. **三阶段工作流 UI（B）**：`libs/ui` StageDock（阶段切换、就绪度清单、
   阶段描述）+ `stage_readiness` 纯内核（port of
   `paleo_workbench/mapping_workspace/readiness.py` + `stage_profiles.py`
   的检查清单语义，输入适配为 C++ 会话状态）。
2. **QGIS 图层树闭环（C）**：`libs/ui` LayerTreePanel — 包装
   `QgsLayerTreeView` + `QgsLayerTreeViewDefaultActions`（分组/重命名/
   排序/右键菜单）+ active layer 双向同步（修复 row→id 索引误配）+
   编辑态 indicator + 角色/成熟度显示。
3. **编辑工具生命周期（D）**：select（`QgsMapToolSelect`）+ 数字化
   （`QgsMapToolDigitizeFeature` point/line/polygon）+ 既有 vertex 工具，
   统一 enablement matrix（mode × layer kind × editable × selection →
   enabled），以 `platform.tool_matrix` 测试钉死。
4. **图层属性/符号化（E）**：`QgsRendererPropertiesDialog`（QGIS 原生）
   托管 + `QgsMapLayerStyleManager` 样式持久化（样式随 QGIS project 落盘）。
5. **约束/预测面板（F）**：约束图层列表面板（按角色过滤的图层清单 +
   约束线计数）——读侧汇总，复用 DomainLayerFacts/MapSession 权威。
6. **状态持久化（G）**：UI 布局（QSettings + 版本防护 + 损坏回退 +
   重置布局动作），与业务 state（QGIS project / working copies）分离。
7. **离屏 QA（H）**：截图 smoke、图层树/工具生命周期/阶段切换/
   布局恢复测试（`platform.*` ctest 家族）。
8. **Shell 接线（A）**：MainWindow 侧最小挂钩（新组件以 `Pwb::Ui`
   库形式接入）；不重排既有 main.cpp/main_window.cpp 结构。

## 明确不负责（与其他并行方向的边界）

- **Catalog/数据内核**：`feat/cpp-data-workspace-catalog-closure`（CONV-26，
  PR #1346）负责 store/catalog/project 生命周期。本分支只消费
  `PwbDataStore`/`IProjectStore` 既有接口，不改 libs/catalog、libs/project。
- **Workflow recompute**：`feat/cpp-workflow-runtime-closure`（CONV-26）
  负责。本分支不实现 recompute/dependency graph。
- **算法核**：预测/因子算法由 Science/Prediction 线负责；本分支只做
  UI 展示与既有 `run_map_pipeline` 的调用面。
- **Packaging/bootstrap 拆分**：`feat/cpp-native-product-closure`
  正在拆 main.cpp → app_context/bootstrap/self_check 并改 main_window
  服务层注入。本分支 **不重组 main.cpp**，新组件全部落 `libs/ui`
  新文件，main_window 只做加法式挂钩（CONV-16 模式），把合并冲突面
  压到最小。
- **Python UI 删除**：PySide6 旧链保持原样（oracle/reference），不动。

## 冲突控制承诺

- 新文件为主：`libs/ui/include/pwb/ui/*`、`libs/ui/src/*`、
  `tests/cpp/platform/*_conv27*.cpp`。
- 共享文件（根 CMakeLists.txt、libs/ui/CMakeLists.txt、
  tests/cpp/platform/CMakeLists.txt、apps CMakeLists）：只加
  `BEGIN CONV-27 ... END CONV-27` 纯追加块。
- main_window.{hpp,cpp}：加法式最小 patch（新 dock 挂钩 + 新 action
  wire），不移动既有代码。
- 不动 libs/qgis、libs/application 的既有接口；如需扩展走新增
  头文件/新增方法。

## 资源控制

- 使用 `scripts/cpp-migration/invoke-resource-gate.sh`（Probe/Configure/
  Build/Test），`CMAKE_BUILD_PARALLEL_LEVEL=2`，单 worktree 单重型构建。
- vendored QGIS SDK（core/gui/analysis）复用主仓
  `native/qgis_render_bridge/build/qgis-vendor/output`（本机 Linux/GCC/Qt
  同 ABI 构建，经 env 注入路径），不重复构建。

## 环境配方（本 worktree）

```bash
export WT=/home/kevin/project/worktrees/cpp-qgis-ui-workbench-closure
export CMAKE=/home/kevin/toolchain/cmake-dist/bin/cmake
export PALEO_QGIS_SOURCE_DIR=/home/kevin/project/paleo-workbench/third_party/qgis
export PALEO_QGIS_SDK_DIR=/home/kevin/project/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output
export PALEO_QGIS_BUILD_DIR=/home/kevin/project/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor
cd $WT && $CMAKE --preset linux-gcc-release   # PWB_BUILD_PLATFORM=ON
```

ctest 全家（含新 UI 测试）：

```bash
cd $WT/build/cpp-platform && ctest --output-on-failure
```
