# paleo_workbench 整体简化与重构设计

日期：2026-07-20
状态：P1 已完成（2026-07-20，分支 refactor/p1-dedup-deadcode），P2-P4 待实施

## 背景与诊断

`paleo_workbench` 共 164 个 Python 文件 / 27952 行，其中 `ui/` 占 68%。诊断发现四类系统性问题：

1. **成对复制粘贴**：`ui/pages/prediction_task_panel.py ↔ seismic_task_panel.py`（~330 行近乎逐字相同）；`workflow/seismic_prediction.py ↔ well_log_prediction.py`（~160 行重复）；画布面板、viz host 等多处样板重复。
2. **分层反向依赖**：`viz → ui`（viz/map_load.py、viz/adapter.py、viz/hosts/* 引用 ui.pages）；`resources → workflow`（export_service.py:18）；`ui/workflow_controller.py → ui/app_shell`（PAGE_INDEX_* 常量）。靠 30+ 处函数内 import 维持。
3. **死代码**：`adapters/` 包（217 行）生产零引用；`ui/widgets/` 五个抽象组件零生产使用；`workflow/well_table.py:174 get_well_table` 无调用点。
4. **上帝类/职责错位**：`map_edit_scene.py`（1381 行/84 方法）；预览子系统在 UI 层做格式解析（preview_provider.py:666 `_xml_well_log_preview` 195 行/嵌套 10 层）；`preview_widgets.py` 12 个无关控件堆一个文件。

## 总原则

- 每批（P1–P4）独立交付、独立可回滚；任一批完成后即可暂停。
- 只改结构，不改功能行为。
- 每批结束跑全量 pytest（现有 166 个测试文件作为安全网），全绿才算完成。
- 不动 `mapping/map_edit_api.py` 的 C++/Python 双实现结构（刻意设计，见 mapping/CPP_EXTENSION.md）。
- 死代码删除前用 vulture 复核动态引用。
- 测试逻辑不重写，仅随接口变化调整 import 与断言目标路径。

## P1 — 低风险去重 + 死代码清理

1. 提取共享任务面板基类/组合件，合并 `ui/pages/prediction_task_panel.py` 与 `seismic_task_panel.py`，标签文案参数化（~330 行去重）。
2. 参数化预测主流程（workflow 名、任务名、标签），合并 `workflow/seismic_prediction.py` 与 `well_log_prediction.py` 的公共部分（~160 行去重）。
3. 删除死代码：`adapters/` 包（含其 3 个契约测试的相应处理）、`workflow/well_table.py` 的 `get_well_table`、`ui/widgets/` 中零生产使用的组件。
4. `PAGE_INDEX_*` 常量从 `ui/app_shell.py` 上移到新模块 `ui/navigation.py`；`app.py` 对 `workflow_controller` 的 12 处私有成员访问（`_wire_*`、`_preview_settings_dialog`）改为公开方法。

验收：pytest 全绿；两个面板与两个预测工作流的行为与 UI 文案不变。

## P2 — 分层修复

1. 斩断 `viz → ui`：`mapping_helpers`、`prediction_helpers`、`seismic_prediction_helpers`、`geoviz_preview_host` 从 `ui/pages` 下沉到 `viz/`（机械移动 + 改 import）。
2. 统一 export 三模块（`workflow/export.py`、`resources/exporters.py`、`resources/export_service.py`）为一个明确归属的 export 模块，消除 `resources → workflow` 反向边。
3. 清理剩余函数内 import（30+ 处），能在模块顶层导入的全部上移；确为避免循环而保留的加注释说明。

验收：pytest 全绿；依赖方向恢复为 `ui → viz/workflow/resources/mapping → project`。

## P3 — 预览子系统归位

1. `preview_provider.py` / `fallback_preview.py` 的格式解析（LAS/SEGY/XML/Office/ZIP 等）从 `ui/pages` 下沉到 `resources/` 下的预览解析模块。
2. `preview_provider.py:175 _build_preview` 的巨型格式分派改为注册表模式。
3. 拆分 `preview_widgets.py`：12 个预览控件按类型分文件。

验收：pytest 全绿，重点回归 `test_preview_*` 系列；预览缓存/worker 链路行为不变。

## P4 — 拆 map_edit_scene.py（1381 行 / 84 方法）

1. 捕捉候选计算（纯几何）抽出并入 `mapping/map_edit_api`。
2. 草图绘制状态机独立成模块。
3. 交互事件路由与文档同步留在 scene 类，目标降至 ~600 行以内。

验收：pytest 全绿，重点回归 `test_map_edit_*` 系列。

## 明确不做

- `ui/pages/module_relationship.py`（内聚、低耦合，投入产出低）。
- 任何功能行为变更、UI 文案变更。
- C++ 扩展双实现结构。

## 风险与回滚

- P1 每项改动独立成 commit，可单独 revert。
- P2/P3 为机械移动 + import 变更，风险集中在漏改动态引用（getattr/importlib），以全量测试 + grep 符号引用双重验证。
- P4 风险最高，放在最后，待前三批测试基线稳定后进行。
