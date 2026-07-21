# 测井可视化 C++ 加速与模块化架构设计 (Well Log Viz Modular Architecture)

## 一、 模块划分与归属原则

为了保持项目的清晰架构，严格遵守 **“应用 UI 与 可视化引擎算法”** 解耦的分层原则：

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Paleo Workbench Application Layer (paleo_workbench/ui/)                  │
│  - well_log_canvas_panel.py                                             │
│  - sequence_framework_page.py                                          │
│  - multiwell_correlation_workbench.py                                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (仅调用 viz/ 提供的控制与 View 接口)
┌────────────────────────────────────▼────────────────────────────────────┐
│ Paleo Workbench Viz Integration Layer (paleo_workbench/viz/)            │
│  - well_log_api.py (测井数据处理与 LOD 算法门面，HAS_CPP_WELL_LOG)      │
│  - hosts/well_log_host.py (对齐 geoviz_well_log 的 UI 宿主桥接)        │
└───────────────────┬─────────────────────────────────┬───────────────────┘
                    │ (算法与渲染下沉)                 │ (调用底层可视化引擎)
┌───────────────────▼─────────────────┐   ┌───────────▼───────────────────┐
│ Native C++ Core Module              │   │ GeoViz Visualization Engine   │
│ (native/well_log_core)              │   │ (geo-viz-engine/geoviz_well_log)│
│  - minmax_lod_downsample            │   │  - well_log_view.py           │
│  - fast_las_reader                  │   │  - cross_well_widget.py       │
│  - crossover_polygon_fill           │   │  - renderer/                  │
└─────────────────────────────────────┘   └───────────────────────────────┘
```

---

## 二、 模块职责边界明细

| 模块层级 | 文件路径 / 模块名 | 职责描述 | 禁忌规则 |
| :--- | :--- | :--- | :--- |
| **应用 UI 层** | `paleo_workbench/ui/pages/` | 负责布局、工具栏、菜单交互、信号槽连接。 | ❌ **禁止**包含数据采样算法、字符串解析、几何坐标计算。 |
| **Viz 适配/API层** | `paleo_workbench/viz/well_log_api.py` | 暴露公开的数据处理算法入口（`minmax_downsample`, `fast_las_parse`, `generate_crossover_fill`），管理 `HAS_CPP_WELL_LOG` 降级。 | ❌ **禁止**直接操作 PySide6 控件或 Qt 事件循环。 |
| **可视化引擎层** | `geo-viz-engine/packages/geoviz_well_log/` | 负责多轨道（Track）、多井连井（Cross-well）的画布渲染、坐标映射与刻度线绘制。 | ❌ **禁止**依赖 `paleo_workbench/ui/` 的任何界面。 |
| **原生 C++ 核心层** | `native/well_log_core/` (C++17 + pybind11) | 负责纯数学/密集内存计算：Min-Max LOD 降采样、文本快速解析、多边形求交、DTW 对齐。 | ❌ **禁止**依赖 Python 运行时 GUI 库；仅操作连续 C 内存或 NumPy Buffer。 |

---

## 三、 TDD 开发计划 (RED ➔ GREEN ➔ REFACTOR)

1. **Task 1: 算法契约与测试 (RED)**
   - 创建 `tests/test_well_log_api.py`，定义 `minmax_downsample`、`fast_las_parse` 与 `generate_crossover_fill` 的测试用例。
2. **Task 2: Viz Python 门面与保底实现 (GREEN)**
   - 创建 `paleo_workbench/viz/well_log_api.py`，实现全套 Pure Python / NumPy 回退算法。
3. **Task 3: 原生 C++ 模块构建 (`well_log_core`) (GREEN)**
   - 建立 `native/well_log_core/`，编写 C++17 算法与 `pybind11` 绑定，确保 Windows (MSVC) / Linux (GCC) 双平台编译通过。
4. **Task 4: 数值等价性测试与性能验证 (REFACTOR)**
   - 创建 `tests/test_well_log_cpp.py` 验证 C++ 与 Python 路径数值一致性，全量回归 pytest 测试。
