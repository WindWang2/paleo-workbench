# Prompt 1 — QGIS 原生地质拓扑矢量编辑与相带智能协同引擎

> **使用方式**：直接复制以下全部内容，粘贴到 zcode agent 的输入框中直接运行（无需在命令行拆分执行）。
> 本 Prompt 内部已通过 `$goal` 与 `$loop` 命令调度，内置「先生成文档 → TDD 驱动开发 → 最终 Multi-pass Review」三阶段闭环。

```markdown
$goal "研发古地理编图系统专属的 QGIS 原生地质拓扑矢量编辑与相带智能协同引擎（M1-M5），支持控制线动态构面、断-相协同截断、共边平滑重塑与地质拓扑规则守卫。全程先生成文档，再以 TDD 严格驱动，最后执行代码审查闭环。"

$loop max_iterations=60 condition="docs_generated && tdd_all_green && memory_and_gil_audited && review_passed"

## 0. 任务元数据与资源边界（硬约束）

- **所属系统**：Paleo Workbench 古地理编图桌面系统（C++20 QGIS Render Bridge + PySide6）。
- **任务目标**：攻坚古地理相带编绘核心能力缺失——从通用 GIS 点线面编辑跨越到「地质控制线网络动态多边形化、同沉积断层截断相带、相带共有边界联动重塑与时空地质拓扑规则硬守卫」。
- **研发规模**：支持至少 4 小时全自主推演与开发，对标 10 亿+ tokens 研发交付量（含全量设计、算核实现、全覆盖测试集、内存/GIL 对抗审计）。
- **⛔ 编译与计算资源硬约束**：
  1. **最多只能启用 3 个 subagents**（严禁任何时刻同时超过 3 个 subagent 运行，防止 CPU/RAM 耗尽）。
  2. **C++ 编译控制**：编译 `native/qgis_render_bridge` 时必须限制并发 `CMAKE_BUILD_PARALLEL_LEVEL=2`，严格使用 Ninja 构建。
  3. **环境隔离**：在主仓库同级目录建立独立 worktree `../paleo-workbench-geotopo-editor`，切入独立分支 `feat/geotopo-editor`。
  4. **代码纯洁性**：恪守 `CLAUDE.md` 与 Karpathy Guidelines，严禁破坏既有 QGIS 桥 ABI 与 POD 隔离原则。

---

## 1. 启用的 Skills 与协作规范

请按需自动调用以下 skills：
- `planning-with-files`：强制以文档管理进度与决策，所有状态实时落盘至 `docs/development/geotopo-editor/`。
- `matt` / `gstack`：用于全流程任务跟踪、架构切片、Git 分支守卫与提交收尾。
- `wayfinder`：将未知地质拓扑歧义转化为显式 ticket，不要中途停下来向用户提问。
- `tdd`：红绿重构循环，任何实现代码提交前必须先有失败的真实断言测试。
- `code-review`：Standards 轴与 Spec 轴双重视角并行审查（使用 ≤2 个 subagents 并行审查）。

---

## 2. 三阶段开发流转协议（Document-First → TDD → Review）

```
┌────────────────────────────────────────────────────────────────────────┐
│ 阶段一：先生成文档 (Documentation First)                                │
│   └─ 00-decisions.md / 01-architecture-rfc.md / 02-contracts.md        │
│   └─ 03-tdd-plan.md / 04-known-limitations.md                          │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段二：TDD 驱动开发 (TDD-Driven Development)                          │
│   └─ Ticket 1: C++ DCEL 构面算核 (Planar Graph Minimal Cycles)          │
│   └─ Ticket 2: 断-相协同截断工具 (PwbFaultCutTool & Split Engine)       │
│   └─ Ticket 3: 相带共边联动重塑 (Coincident Boundary Reshape)           │
│   └─ Ticket 4: 地质拓扑规则守卫 (Facies Adjacency Invariants Gate)     │
│   └─ Ticket 5: 原子宏事务与撤销重做 (Multi-Layer Atomic Commits)       │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段三：最后 Review 与对抗性审计 (Multi-pass Review & Verification)    │
│   └─ Standards 审查 + Spec 契约审查 + 内存泄漏/GIL 死锁审计            │
│   └─ 500+ 退化几何模糊测试 + 04-verification-report.md 验收产出         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 阶段一：先生成文档（必须首先落地，严禁跳过）

在开始编写代码前，必须在 `docs/development/geotopo-editor/` 目录下创建并维护以下 5 份结构化工程文档：

1. `00-decisions.md`：记录所有技术决策（如 DCEL 浮点容差选择、GEOS/QGIS 内部几何依赖隔离方案），遇到未确定细节按「默认地质最佳实践」自决并记录理由。
2. `01-architecture-rfc.md`：详述 C++ 双向连通边表（DCEL）的拓扑图构建数学模型，线切面（Polygon Splitting）、弧段共用（Shared Boundary Ribbons）与相带属性继承的算法推导。
3. `02-interface-contracts.md`：详细定义 C++ 与 Python 之间的 pybind11 接口契约、错误码定义、JSON/POD 承载格式。
4. `03-tdd-test-plan.md`：详细罗列各工步的红绿测试清单、测试数据集生成方案、预期断言。
5. `04-known-limitations.md`：诚实记录本期不做的边界情况（如三维空间拓扑投影畸变等）。

---

## 4. 阶段二：TDD 驱动开发（红绿循环，逐 Ticket 推进）

每个 Ticket 严格执行：**写失败测试（Red）→ 最小实现（Green）→ 重构优化（Refactor）→ 单一 Atomic Git Commit**。

### Ticket 1：C++ 原生 DCEL 平面相带多边形化算核
- **文件定位**：
  - 新建 `native/qgis_render_bridge/src/geological_topology_core.hpp`
  - 新建 `native/qgis_render_bridge/src/geological_topology_core.cpp`
  - 绑定至 `native/qgis_render_bridge/src/bindings.cpp`
- **契约要求**：
  - 输入：一组控制线（GeoJSON 或 `QgsGeometry` 序列，含古岸线、相变分界线、断层线）。
  - 算法：构造有向边、相交打断（Node Segment Intersections）、左转算法（Leftmost Turning）提取最小闭合回路，剔除外包大框，生成拓扑有效的相带多边形集合。
  - 性能门禁：在包含 5,000 条线段的网格下，多边形化耗时 $\le 30\text{ ms}$。
  - **TDD 先行**：在 `tests/test_geological_topology_core.py` 中编写多种自交、T型相交、孤立悬挂线用例，确保初始红灯，实现后全部绿灯。

### Ticket 2：断-相协同截断工具 (`PwbFaultCutTool`)
- **文件定位**：
  - 修改 `native/qgis_render_bridge/src/edit_tools.hpp` / `edit_tools.cpp`
  - 修改 `paleo_workbench/ui/workstation/composite_editing.py`
- **契约要求**：
  - 继承 `QgsMapTool` 实现断层交互式切割工具。支持用户点选或绘制断层折线，自动拾取穿越的相带面要素，在 C++ 镜像层缓冲中执行原子分割（Split Features）。
  - 保持属性延续性：原相带的沉积相代码、层序界面等属性自动克隆至分割后的两个新多边形，同时打上断裂控制标记字段 `fault_bounded=True`。
  - **TDD 先行**：在 `tests/test_fault_cutting.py` 中编写断裂部分穿越、多次相交、端点正好贴合边界等边缘用例。

### Ticket 3：相带共有边界联动平滑重塑 (`PwbBoundaryReshapeTool`)
- **文件定位**：
  - 修改 `native/qgis_render_bridge/src/edit_tools.cpp`
  - 修改 `paleo_workbench/mapping/geometry_operations.py`
- **契约要求**：
  - 拾取两相邻相带多边形的共享弧段（Shared Arc），拖拽手势重塑弧段形状（样条平滑或折线微调），释放时两边多边形同时更新，无裂隙（Sliver）、无重叠（Overlap）。
  - 结合 `AvoidIntersectionsV2` 机制，自动向关联图层散布拓扑对齐点。
  - **TDD 先行**：在 `tests/test_boundary_reshape.py` 中断言两相带面积之和在重塑前后完全守恒（无缝隙丢失）。

### Ticket 4：地质拓扑规则形式化守卫（Geological Invariant Gate）
- **文件定位**：
  - 新建 `paleo_workbench/mapping/geological_invariants.py`
  - 接入 `paleo_workbench/ui/workstation/composite_editing.py` 中的提交门禁
- **契约要求**：
  - 实现基于 `facies_taxonomy.json` 的相序空间连续性校验器：如果出现「深海相与冲积扇相直接相邻（缺失陆棚与滨岸过渡相）」、「相带内部存在未封闭悬挂断层」、「等厚线跨越剥蚀边界未断开」等情形，提交时拦截并给出精准地质语义警告。
  - **TDD 先行**：编写 `tests/test_geological_invariants.py`，覆盖合法相序与非法相序的所有矩阵组合。

### Ticket 5：多图层原子编辑事务与撤销重做（Atomic Multi-layer Commits）
- **文件定位**：
  - 修改 `paleo_workbench/mapping/native_edit_session.py`
  - 修改 `paleo_workbench/ui/workstation/composite_editing.py`
- **契约要求**：
  - 支持单次手势同时跨线层（相带边界线）与面层（相带多边形层）开辟复合宏命令（Compound Undo Command），一次 Ctrl+Z 能够原子级同步撤销线与面的变更。
  - **TDD 先行**：编写多图层联合编辑并发撤销压力测试用例。

---

## 5. 阶段三：最后 Review 与对抗性审计闭环

在所有代码编写与功能测试通过后，**必须启动严格的多轮 Review 与对抗性验证**（并发 subagents $\le 2$）：

1. **Standards 规范审查**：
   - 检查 C++ 内存泄漏（`QgsFeature`、`QgsGeometry` 对象是否正确以值传递或智能指针管理，无裸 `new` 泄漏）。
   - 检查 Python/C++ 跨边界异常拦截，确保 `try ... catch (const std::exception&)` 完整包裹所有 pybind11 回调，绝不让底层 C++ 异常崩溃进程。
2. **Spec 契约与地质真实性审查**：
   - 验证生成的相带图层是否满足《勘探管理图件图册编制规范》对沉积相多边形拓扑的硬性规定。
3. **极端对抗性模糊测试（Fuzz Testing）**：
   - 运行程序化生成的 500+ 个病态几何（包含 0.000001 容差极小刺状多边形、自交 8 字形环、数万个密集共线点），断言编辑引擎永不卡死、永不段错误（Segfault）。
4. **验证报告与收尾**：
   - 将最终测试结果、耗时基准、测试覆盖率完整记录在 `docs/development/geotopo-editor/04-verification-report.md` 中。
   - 使用 `gstack` / Git 规范清理提交记录，生成合并就绪的 PR。
```
