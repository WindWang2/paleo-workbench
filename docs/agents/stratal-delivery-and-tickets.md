# 交付说明 + 剩余工作 Ticket（3D 地震体可视化 + 井震联合分析专业化）

> **Branch:** `3D` · **日期:** 2026-08-08
> **范围:** 阶段 1–4（边界下沉 → 引擎能力补齐 → 主程序专业化 → 工程化收尾）

---

## 一、变更文件 / 模块总览

### geo-viz-engine（引擎核心，全部在子模块内）

| 文件 | 性质 | 内容 |
|---|---|---|
| `packages/geoviz_seismic/geoviz_seismic/stratal.py` | **新** | 等时/比例地层切片纯 numpy 核心（4 函数，线性 T 插值） |
| `packages/geoviz_seismic/geoviz_seismic/renderer_3d.py` | 改 | stratal 状态 + `_sync_stratal_planes` + `set/get/clear/set_visible` 公共 API |
| `packages/geoviz_seismic/geoviz_seismic/__init__.py` | 改 | 导出 stratal 模块 + 4 函数 |
| `geoviz/__init__.py` | 改 | facade 注册 4 stratal 函数 + `HorizonParser`/`HorizonAxes` |
| `packages/geoviz_seismic/geoviz_seismic/gl_clipping.py` | 新（阶段1） | `ClippedGLMeshItem`/`VolumeItem`（从主仓库 `engine.py` 下沉） |
| `packages/geoviz_seismic/geoviz_seismic/crossplot.py` | 新（阶段1） | `analyze_lithology_crossplot` |
| `packages/geoviz_plots/geoviz_plots/geomodel/` | 新（阶段1） | primitives / borehole_tunnel / fault_dislocation |
| `packages/geoviz_well_tie/geoviz_well_tie/{synthetic,auto_tie,calibration}.py` | 改（阶段1） | 井震标定核心 |
| `packages/geoviz_well_seismic_3d/.../well_geometry.py` | 改（阶段1） | `offset_curve_along_trajectory` |
| `docs/reference-stratal-slices.md` | **新** | stratal 特性参考文档 |
| `tests/test_stratal_slice.py` | **新** | 63 算法测试 |
| `tests/test_renderer_3d_stratal.py` | **新** | 52 渲染测试 |
| `tests/test_{geomodel_geometry,gl_clipping,well_seismic_promoted}.py` | 新（阶段1） | 89 下沉回归 |

### paleo-workbench（主仓库，薄适配层 + UI）

| 文件 | 性质 | 内容 |
|---|---|---|
| `paleo_workbench/viz/geomodel/__init__.py` | 改（阶段1） | 删除 5 引擎子模块 → 薄适配层 + 4 兼容 shim |
| `paleo_workbench/viz/stratal_adapter.py` | **新** | 工作台胶水（.dat→sample-index 网格 + 演示体） |
| `paleo_workbench/ui/pages/geological_modeling_3d_page.py` | 改 | 分析标签面板 + stratal 入口 + 模型树子项 + 跨页信号 |
| `paleo_workbench/ui/pages/well_log_prediction_page.py` | 改 | `set_selected_well` 跨页 seam |
| `paleo_workbench/ui/workflow_controller.py` | 改 | `wire_geomodel_page` + 井同步转发 |
| `paleo_workbench/app.py` | 改 | 注册 `wire_geomodel_page` |
| `tests/test_stratal_adapter.py` | **新** | 5 测试 |
| `tests/test_stratal_page_entry.py` | **新** | 7 测试（含最小可观察结果） |
| `tests/test_cross_page_well_sync.py` | **新** | 4 测试 |
| `tests/test_geoviz_package_independence.py` | 改 | allow-list 追加 6 名 |
| `scripts/run_tests.sh` | 改 | 修复 conda PATH bug |
| `docs/agents/geo-viz-boundary.md` | 改 | 阶段 1 分析 + 阶段 2/3 增量结论 |
| `docs/geomodel-architecture.md` | 改 | 反映迁移后薄适配层 + 新能力 |

---

## 二、新能力演示路径（一步步操作）

### 等时/比例地层切片（阶段 2 能力，阶段 3 演示入口）

1. 打开「井震联合」页（左侧导航第 10 项）。
2. 在顶部浮动工具栏点「分析」按钮 → 下方出现分析标签面板。
3. 切到「**等时切片与属性**」tab。
4. **无 SEGY 演示**（离屏/无数据时）：勾选「用合成演示体（无 SEGY 时预览）」→ 点「生成地层切片」。
   → 3D 视口加载合成体并叠加 **3 张比例地层切片**（k=0.25/0.5/0.75，紫色边框），active 切片橙色高亮。
5. **真实数据**：用「浏览…」选顶部/底部两个 `.dat` horizon → 选比例切片组合 → 取消演示勾选 → 「生成地层切片」。
   → 在两个 horizon 间按比例生成切片，倒转/缺失单元自动掩码。
6. 在左侧模型树取消勾选「地层切片体 (geoviz)」可隐藏切片；「清除」按钮移除全部。

**能看到的最小结果**：3D 视口出现 ≥1 张色标的比例地层切片平面（演示模式下 3 张），active 切片有橙色边框。

### 跨页面井选中联动

1. 在「井震联合」页 3D 视口点击一口井（拾取模式）。
2. `well_selected` 信号触发 → 切到「测井预测」页 → 对应井名的预测任务被选中（画布/证据面板同步刷新）。

---

## 三、剩余工作 Ticket（按优先级排序）

### P0 — 阻塞性 / 正确性

无（核心路径测试全绿，0 新增回归）。

### P1 — 应跟进

1. **[stratal] 真实 SEGY 端到端验证** — 当前真实数据路径有单测覆盖适配层逻辑，但未在有真实 SEGY 的环境跑过完整 `build_stratal_grids` → 渲染链。需在带 SEGY 的工作站验证 survey/registration 对齐与 horizon NaN 传播。验收：真实数据下生成切片且与 `extract_along_horizon` 结果定性一致。
2. **[stratal] 地层切片属性叠加** — 当前切片显示原始振幅。应支持把 `compute_rms_amplitude`/`compute_coherence_c3` 等 3D 属性体沿 stratal 曲面采样显示（复用 `extract_stratal_slice` 的 window/mode）。验收：等时切片 tab 增加属性下拉，切片内容随选择变化。
3. **[facade] `Renderer3D` 未在 facade 导出** — 页面经 `WellSeismicJointWidget.renderer` 间接访问；若未来需直接构造，应按 GL 惰性加载模式加入 facade。影响：外部消费者无法 `from geoviz import Renderer3D`。

### P2 — 增强 / 体验

4. **[stratal] 非平面 warped-quad 渲染** — 当前切片平面铺在曲面平均深度的 XY 平面上（最简表示）。当地层强烈起伏时，真实非平面几何更准确。验收：`_sync_stratal_planes` 增加可选 warped-quad 路径，与平面模式可切换。
5. **[cross-page] 反向联动（WellLog→3D）** — 当前仅 3D→WellLog 单向。反向需在 WellLog `_on_task_selected` 发信号，3D 页 `_select_joint_wells` 需井对语义。验收：WellLog 选任务→3D 高亮对应井。
6. **[cross-page] SeismicPage 井概念** — SeismicPage 无 per-well 状态，无法接收 `well_selected`。需先加 well-name 状态 + setter。验收：3D 选井→SeismicPage 同步井震标定目标井。
7. **[stratal] 持久化** — stratal 切片状态（surfaces/fractions/active）未持久化到 `JointAnalysisState`（对比 orthogonal/time 切片已持久化）。验收：重开工程恢复 stratal 选择。
8. **[512 限制] 性能附加项（未做）** — 目标里的"放宽 SEGY 单轴 512 预览限制 + 分块加载"未在本轮完成。stratal 已用线性插值 + map_coordinates，但预览体仍是 128/轴降采样。验收：可测量地处理 >512 数据且交互流畅。

### P3 — 技术债

9. **[boundary] `paleo_workbench/viz/fault_displacement.py` 残留引擎逻辑** — `FaultDisplacement` 类（与 `FaultCuttingEngine` 不同）仍是纯 numpy 几何，未在阶段 1 迁移清单内。应下沉到 `geoviz_plots.geomodel`。验收：删除主仓库文件，facade 再导出。
10. **[boundary] `geoviz_well_tie` 双实现收敛** — 子波（`wavelet.py` vs `wavelet_engine.py`）、合成（`synthetic.py` vs `synthetic_generator.py`）、互相关（`auto_tie.py` vs `tie_evaluator.py`）各有未导出的第二实现。应收敛到单一权威实现。验收：删除未导出副本，保留签名兼容。
11. **[test] offscreen-GL 既有失败** — `test_update_slice_planes_for_only_replaces_changed_axis` 等在 offscreen GL 下失败（in-place 路径依赖真 GL）。应加 GL 能力检测或改为状态断言。验收：offscreen 下该测试稳定通过或显式 skip。

---

## 四、模块边界最终结论

**引擎核心与主仓库边界已清晰且被测试强制：**

- `tests/test_geoviz_package_independence.py` 强制主仓库生产代码只能 `from geoviz import <allow-listed>`，禁止直接 import `geoviz_*` 子包。
- 阶段 1 迁移把 5 个引擎子模块（~1100 行算法）从 `paleo_workbench/viz/geomodel/` 下沉到 geo-viz-engine，主仓库 `viz/geomodel/` 现为 4 文件薄适配层（models/advisor/exporters + 兼容 shim）。
- 阶段 2 新增的 stratal 能力**从一开始就正确归属**：算法在 `geoviz_seismic.stratal`，渲染在 `Renderer3D`，主仓库只有 `stratal_adapter.py` 胶水层（无算法）。
- 主程序专业化（阶段 3）全部为 UI 编排 + facade 调用 + 业务级信号，未在主仓库重复实现任何引擎逻辑。

**结论：模块边界目标达成，可进入维护期。**
