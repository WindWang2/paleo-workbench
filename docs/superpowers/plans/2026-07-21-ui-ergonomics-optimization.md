# Paleo Workbench UI 人体工程学优化实施计划

> **目标**：实现阶段式工作流导航 (Stage-based Workflow Ergonomic UI) 架构，重构 `AppShell` 布局，新增顶部 44px 阶段步进条 `WorkflowStepper` 与左侧动态上下文敏感侧栏 `ContextSidebar`，缩减 60%+ 鼠标移动距离并降低认知负荷，实现全量 TDD 测试覆盖。

---

## 一、 任务拆解与开发步骤 (TDD Workflow)

### Task 1: 导航映射与阶段模型扩展 (Navigation & Stage Mapping)
- **目标**: 在 `paleo_workbench/ui/navigation.py` 中重构并定义 4 大阶段与 10 个页面的映射结构，提供类型安全的索引转换函数。
- **文件步骤**:
  1. 编写 `tests/test_ui_navigation.py` (RED)：验证 4 个阶段定义、页面与阶段互转算法。
  2. 修改 `paleo_workbench/ui/navigation.py` (GREEN)：定义 `STAGE_DEFINITIONS`, `STAGE_PAGE_MAPPING`, `get_stage_for_page(page_index)`, `get_subpage_list(stage_index)`。

### Task 2: 顶部 `WorkflowStepper` 控件开发 (Top Stepper Bar)
- **目标**: 创建 `paleo_workbench/ui/workflow_stepper.py` 控件，提供高度 `44px` 符合人体工程学目标尺寸的阶段步进导航。
- **文件步骤**:
  1. 编写 `tests/test_ui_workflow_stepper.py` (RED)：测试 4 个 Stage 按钮初始化、点击信号广播、活动胶囊 (Pill Style) 样式刷新。
  2. 实现 `paleo_workbench/ui/workflow_stepper.py` (GREEN)：构建数字徽章、箭头指示与 `stage_changed(int)` 信号。

### Task 3: 动态 `ContextSidebar` 控件重构 (Context Sidebar)
- **目标**: 将 `paleo_workbench/ui/sidebar.py` 重构为 `ContextSidebar`，实现倒 L 型结构（顶部分段切页控件 + 中部上下文工具 + 底部收起按钮）。
- **文件步骤**:
  1. 编写 `tests/test_ui_sidebar.py` (RED)：测试上下文切页分段按钮、收起/展开折叠逻辑。
  2. 重构 `paleo_workbench/ui/sidebar.py` (GREEN)：实现当前 Stage 子页面的分段导航（Segmented Control）及折叠逻辑。

### Task 4: `AppShell` 视口组装与双层快捷键系统 (AppShell Integration & Ergonomic Shortcuts)
- **目标**: 将 `WorkflowStepper` 和 `ContextSidebar` 组装进 `AppShell`，实现阶段上次选定页面记忆及 `Ctrl+1~4` / `Alt+1~4` 双层快捷键与 Focus Guard 焦点防误触防护。
- **文件步骤**:
  1. 修改/扩展 `tests/test_app_shell.py` (RED)：测试阶段切换逻辑、子页记忆恢复及快捷键响应。
  2. 重构 `paleo_workbench/ui/app_shell.py` (GREEN)：集成 Stepper、Sidebar，实现 Stage 状态管理与输入框焦点安全拦截。

### Task 5: 视觉代币 (Tokens) 拓展与全量自动化回归验证 (Visual Polish & Verification)
- **目标**: 更新 `paleo_workbench/tokens.py` 中的 QSS 样式表，补充 Stepper 和 ContextSidebar 样式代币（最小点击尺寸 ≥ 36px）；运行全量 Pytest 进行无头模式自动化验证。
- **文件步骤**:
  1. 修改 `paleo_workbench/tokens.py`：注入 Stepper/Segmented Control 样式表。
  2. 运行 `QT_QPA_PLATFORM=offscreen python -m pytest` 确保 100% 测试全绿。
