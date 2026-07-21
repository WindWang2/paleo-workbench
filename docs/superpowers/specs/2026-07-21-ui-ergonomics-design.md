# Paleo Workbench UI Ergonomics Optimization Design

**Date**: 2026-07-21  
**Status**: Approved  
**Topic**: UI Layout & Ergonomic Optimization (阶段式工作流导航与人体工程学重构)

---

## 1. Executive Summary & Goals

Paleo Workbench (古地理图编制系统) 当前包含了 10 个平铺展现在左侧 `IconRail` 中的独立页面。随着功能的丰富，原先平铺列出的导航模式存在以下人体工程学与可用性痛点：
1. **认知负荷过高**：地质专家在 10 个平铺选项中频繁选择，增加了视觉搜索开销与心理决策延时。
2. **鼠标漫游半径过大**：鼠标指针在左侧导航与右侧地图视图/属性面板之间频繁大幅度往返。
3. **缺少阶段感**：地质古地理编制具有天然的业务阶段递进关系（数据预处理 ➔ 综合解释 ➔ 古地理编图 ➔ 成图审核），平铺导航无法体现业务流程。

本设计提出 **阶段式工作流导航 (Stage-based Workflow Ergonomic UI)** 架构方案：
- 引入顶部 **WorkflowStepper (工作流阶段步进条)**，将 10 个子页面聚合为 4 个业务阶段。
- 重构左侧为动态 **ContextSidebar (上下文敏感侧栏)**，仅展示当前阶段所需的 2~4 个子页面分段按钮与阶段高频工具。
- 遵循菲茨定律（Fitts's Law），扩大交互控件的目标点击尺寸（≥ 36px），缩减鼠标移动路径 60% 以上。

---

## 2. Architecture & Stage Mapping

### 2.1 Stage Classification (4-Stage Pipeline)

将现有 10 个页面统一组织为 4 个阶段，在 `paleo_workbench/ui/navigation.py` 中建立标准映射关系：

| 阶段索引 & 名称 | 包含的子页面 (Page Index & Name) | 阶段业务定位 |
| :--- | :--- | :--- |
| **Stage 0: 数据与预处理** | `PAGE_INDEX_DATA` (数据管理)<br>`PAGE_INDEX_PREPARATION` (数据制备) | 原始地质/测井/地震数据导入、格式校验与预处理插值准备 |
| **Stage 1: 综合解释与预测** | `PAGE_INDEX_WELL_LOG` (测井预测)<br>`PAGE_INDEX_SEISMIC` (地震预测)<br>`PAGE_INDEX_SEQUENCE` (层序格架)<br>`PAGE_INDEX_STRATIGRAPHY` (地层对比) | 地质多学科单井/剖面/地震综合解释与层序对比 |
| **Stage 2: 古地理编图与可视化** | `PAGE_INDEX_MAPPING` (古地理编图)<br>`PAGE_INDEX_VISUALIZATION` (二维/三维可视化) | 核心地质编图工作位（沉降/相带绘制）与 2D/3D 效果实时渲染 |
| **Stage 3: 成图审核与管理** | `PAGE_INDEX_REVIEW` (成图审核)<br>`PAGE_INDEX_HOME` (项目概览/首页) | 地质规范审核、元数据校验、成果导出与项目总体管理 |

### 2.2 AppShell Layout Hierarchy

重构 `paleo_workbench/ui/app_shell.py` 的总体视口结构：

```
+------------------------------------------------------------------------+
| MenuBar (顶部菜单栏)                                                   |
+------------------------------------------------------------------------+
| WorkflowStepper (新增: 顶部 44px 阶段步进导航条, 包含 4 个 Stage 步进项)    |
+------------------------------------------------------------------------+
| +-----------------+ +------------------------------------------------+ |
| | ContextSidebar  | | Main Workspace Viewport                        | |
| | (阶段上下文侧栏 | | (QStackedWidget - 10个 Page 页面容器)             | |
| |  含子页面分段切 | |                                                | |
| |  换与快捷工具)  | |                                                | |
| +-----------------+ +------------------------------------------------+ |
+------------------------------------------------------------------------+
| StatusBar (底部状态栏)                                                  |
+------------------------------------------------------------------------+
```

---

## 3. Detailed Component Specifications

### 3.1 `WorkflowStepper` (Top Stepper Bar)

- **模块位置**: `paleo_workbench/ui/workflow_stepper.py`
- **尺寸规范**: 固定高度 `44px`，边距与间距遵循 `tokens.py` 规定（高 `44px` 符合触摸/鼠标点击的 Ergonomic Target Size）。
- **视效与交互**:
  - **Stage 项**: 包含带圆角数字徽章的文本指示器（如 `❶ 数据与预处理`、`❷ 综合解释`、`❸ 古地理编图`、`❹ 成图审核`）。
  - **连接器**: 阶段间以轻量箭头 `›` 连接。
  - **活动状态 (Active Pill)**: 当前 Stage 使用 `primary_accent` 高亮背景胶囊样式，非活动项悬浮展示轻亮 Hover 效果。
  - **信号发送**: 触发 `stage_changed(int stage_index)` 信号。

### 3.2 `ContextSidebar` (Context-sensitive Left Sidebar)

- **模块位置**: `paleo_workbench/ui/sidebar.py`
- **层级划分 (Inverted-L Flow)**:
  1. **Sub-page Segmented Control (顶部分段切换栏)**:
     仅显示当前 Stage 下包含的子页面列表（如在 Stage 2 下显示 `[古地理编图] | [三维/二维可视化]`）。
  2. **Context Quick Tools (中部上下文快捷工具)**:
     可容纳当前阶段常用的快捷调色板、图层显示开关或快照按钮。
  3. **Collapse/Expand Toggle (底部收起按钮)**:
     支持将侧栏收缩至 `36px` 极简列或全隐藏，主视图画布可充容占据 100% 视口空间。

---

## 4. Ergonomics & Interaction Rules

1. **Fitts's Law 目标可达性**:
   - 所有导航按钮、分段按钮最小点击尺寸提升至 `36px × 36px`，减小指针精确瞄准的物理张力。
2. **倒 L 型动线 (Inverted-L Motion)**:
   - 顶部选择阶段 ➔ 鼠标向下移动切换子页面/辅助工具 ➔ 向右操作画布，移动路线自然连贯。
3. **快捷热键与盲操 (Shortcuts System)**:
   - **阶段热键**: `Ctrl + 1` ~ `Ctrl + 4` 快捷切换 Stage 0 ~ 3。
   - **子页热键**: `Alt + 1` ~ `Alt + 4` 快捷切换当前 Stage 内子页面。
   - **顺序循环**: `Ctrl + Tab` 在当前 Stage 的子页面间顺序循环切页。
   - **焦点保护 Guard**: 在 `QLineEdit` / `QTextEdit` 等输入框获取焦点时，自动挂起单键与热键导航，防止文字输入被误切页。

---

## 5. State Management & Backward Compatibility

1. **Stage 内状态记忆**:
   - `AppShell` 记录每个 Stage 最后一次选中的子页面索引。切回该 Stage 时自动恢复到上次留存的子页面。
2. **API & 信号兼容**:
   - 保留 `PAGE_INDEX_DATA` 至 `PAGE_INDEX_REVIEW` 所有常量定义。
   - `AppShell._switch_page(index: int)` 保留签名，供单元测试和各 Page 之间交叉跳转调用。
   - `icon_rail` 保持为可选项或映射至底层 `WorkflowStepper` 的广播接口，保证现存自动化 UI 测试无缝兼容。

---

## 6. Verification & Test Plan

1. **单元测试**:
   - 编写 `tests/test_ui_workflow_stepper.py` 验证 4 个阶段切换与 `stage_changed` 信号广播。
   - 编写 `tests/test_ui_sidebar.py` 验证动态子页面列表更新与折叠逻辑。
2. **集成测试**:
   - 运行现存全套 `pytest -q`（特别是 `test_app_shell.py`），确保页面切换与快捷键焦点保护不受影响。
3. **无头 UI 运行验证**:
   - 使用 `QT_QPA_PLATFORM=offscreen python -m pytest` 进行回归验证。
