# 模块边界分析：`paleo_workbench.viz.geomodel` → `geo-viz-engine`

> **Branch:** `3D`
> **Last updated:** 2026-08-08
> **Scope:** 阶段 1 — 边界分析与引擎下沉

## 1. 边界规则（本次执行采用的判定标准）

| 归属 | 允许内容 |
|---|---|
| `geo-viz-engine` | **全部可视化引擎核心**：SEGY 加载与缓存、体渲染、切片（含等时/比例切片）、RGB 多属性混色、GLSL、井震标定核心算法（合成记录、互相关、时深、3D 曲线生成）、`geoviz_well_seismic_3d` 联合场景逻辑、以及一切纯 numpy 几何/网格生成与 GL 渲染原语 |
| `paleo_workbench` | 页面编排、UI 控件、工作流胶水代码、对 geo-viz-engine **公共 facade API** 的调用、**业务级 AI 顾问**、**数值模拟导出** |

补充约束（既有工程约定，本次继续遵守）：

- 主仓库生产代码只能 `from geoviz import <allow-listed name>`，禁止直接 import `geoviz_*` 子包。
  由 `tests/test_geoviz_package_independence.py::test_workbench_production_imports_only_geoviz_facade` 强制。
- 新增 facade 导出必须同时登记在 `geoviz/__init__.py::_COMPATIBILITY_EXPORTS` 与该测试的
  `GEOVIZ_PUBLIC_FACADE` 允许清单里。

## 2. 现状：哪些代码在错误位置

迁移前 `paleo_workbench/viz/geomodel/` 共 9 个模块 / 1476 行：

| 文件 | 行数 | 内容性质 | 判定 |
|---|---|---|---|
| `engine.py` | 285 | `ClippedGLMeshItem` / `ClippedGLVolumeItem`（GL_CLIP_PLANE 三向剖切渲染原语）+ 圆柱/管道/断层面纯 numpy 网格生成 + 3 个未被调用的 Qt 便利包装 | ❌ 引擎核心（体渲染 / GL） |
| `well_seismic.py` | 276 | Ricker 合成记录、互相关自动标定、时深偏移、井旁 3D 曲线偏移、RGB 三属性混色、岩性交会图统计、**`CrossWellFenceGenerator` 全量重复副本** | ❌ 引擎核心（井震标定 + RGB 混色）且含重复实现 |
| `borehole_tunnel.py` | 321 | 钻孔按煤层面分段、RMF（Double Reflection）扫掠管道网格 | ❌ 引擎核心（纯 numpy 几何） |
| `fault_dislocation.py` | 160 | `FaultCuttingEngine.apply_dislocation` 断层错断（linear/exponential/gaussian 衰减） | ❌ 引擎核心（纯 numpy 几何） |
| `fence_generator.py` | 62 | `CrossWellFenceGenerator.extract_seismic_slice` | ❌ **与 `geoviz_plots.fence.fence_generator` 逐字重复** |
| `models.py` | 56 | `Layer` / `BoreholeRecord` / `FaultRecord` / `TunnelRecord` / `GridSpec` 领域 dataclass | ✅ 留主仓库（advisor + exporters 的输入模型） |
| `advisor.py` | 159 | `check_boreholes` / `check_coplanar_faults` 业务级数据一致性诊断 | ✅ 留主仓库（业务级 AI 顾问） |
| `exporters.py` | 102 | FLAC3D / Abaqus 结构网格导出 | ✅ 留主仓库（数值模拟导出） |
| `__init__.py` | 57 | 22 个符号再导出 | ✅ 改为薄适配层 |

### 已发现的重复实现（迁移必须一并收敛）

1. **`CrossWellFenceGenerator` 三份**
   - `geoviz_plots/fence/fence_generator.py` ← 权威实现（`generate_fence_mesh` + `extract_seismic_slice`，每井独立深度 + 除零保护）
   - `paleo_workbench/viz/geomodel/fence_generator.py` ← `extract_seismic_slice` 逐字重复
   - `paleo_workbench/viz/geomodel/well_seismic.py:164-275` ← 两个方法都重复，且 `generate_fence_mesh` 用了错误的共享 `max_depth`、无除零保护
2. **`geoviz_well_tie` 包内自带双实现**（本次不删除，仅明确权威路径）
   - 子波：`wavelet.py`（导出）vs `wavelet_engine.py`（未导出）
   - 反射系数/合成：`synthetic.py`（导出）vs `synthetic_generator.py`（未导出，`compute_reflectivity` 签名不同）
   - 互相关：`auto_tie.py`（导出 `auto_tie_with_quality`）vs `tie_evaluator.py`（未导出）
3. **主仓库 `WellSeismicTieCalibration.compute_synthetic` 与 `geoviz_well_tie.compute_reflectivity + generate_synthetic` 数学等价**，只是把「声波→阻抗→反射系数→Ricker 卷积」揉成了一个方法。

## 3. 建议迁移清单

### Tier 1 — 本阶段执行

| # | 来源（主仓库） | 目标（geo-viz-engine） | 目标公共 API |
|---|---|---|---|
| 1 | `well_seismic.py::WellSeismicTieCalibration.compute_synthetic` | `geoviz_well_tie/synthetic.py` | `synthetic_from_logs(sonic, density, *, wavelet_freq=30.0, dt_s=0.002)` |
| 2 | `well_seismic.py::WellSeismicTieCalibration.auto_correlate` | `geoviz_well_tie/auto_tie.py` | `correlate_synthetic_to_trace(synthetic, seismic_trace)` |
| 3 | `well_seismic.py::WellSeismicTieCalibration.align_twt_depth` | `geoviz_well_tie/calibration.py` | `shift_depths(depths, depth_shift)` |
| 4 | `well_seismic.py::WellCurve3DGenerator.generate_curve_mesh` | `geoviz_well_seismic_3d/well_geometry.py` | `offset_curve_along_trajectory(well_path, curve_values, *, scale=0.1)` |
| 5 | `well_seismic.py::RGBAttributeFusion.blend_rgb` | `geoviz_seismic/attributes.py` | `blend_rgba(r_channel, g_channel, b_channel, *, alpha=0.85)` |
| 6 | `well_seismic.py::LithologyCrossplotEngine.analyze` | `geoviz_seismic/crossplot.py`（新建） | `analyze_lithology_crossplot(gr, ai, lithology)` |
| 7 | `well_seismic.py::CrossWellFenceGenerator`（重复副本） | — | **删除**，收敛到 `geoviz_plots.fence` |
| 8 | `fence_generator.py`（整个模块，逐字重复） | — | **删除**，收敛到 `geoviz_plots.fence` |
| 9 | `engine.py::ClippedGLMeshItem` / `ClippedGLVolumeItem` | `geoviz_seismic/gl_clipping.py`（新建） | 同名类 |
| 10 | `engine.py::generate_cylinder_geometry` / `generate_tube_geometry` / `generate_fault_geometry` | `geoviz_plots/geomodel/primitives.py`（新建） | 同名函数 |
| 11 | `borehole_tunnel.py::get_seam_boundaries` / `BoreholeTraceGenerator` / `TunnelMeshGenerator` | `geoviz_plots/geomodel/borehole_tunnel.py`（新建） | 同名符号 |
| 12 | `fault_dislocation.py::FaultCuttingEngine` | `geoviz_plots/geomodel/fault_dislocation.py`（新建） | 同名类 |
| 13 | `engine.py::create_cylinder_mesh` / `create_tube_mesh` / `create_faulted_surface` | — | **删除**（零调用方，死代码） |

### Tier 2 — 明确留在主仓库

| 模块 | 理由 |
|---|---|
| `models.py` | `advisor.py` / `exporters.py` 的领域输入模型；随这两个模块一起留下 |
| `advisor.py` | 规则来自煤田地质业务约定（层位反转、共面断层 5°/15m 阈值），属「业务级 AI 顾问」 |
| `exporters.py` | FLAC3D / Abaqus 属「数值模拟导出」 |

## 4. 影响面分析

### 4.1 生产代码调用方（共 3 处文件）

| 文件 | 受影响导入 | 处理方式 |
|---|---|---|
| `paleo_workbench/viz/__init__.py:3` | `FaultCuttingEngine` | 经 `viz.geomodel` 薄适配层，无需改动 |
| `paleo_workbench/ui/pages/geological_modeling_3d_page.py:32-40` | `ClippedGLMeshItem`, `ClippedGLVolumeItem`, `WellSeismicTieCalibration`, `WellCurve3DGenerator`, `RGBAttributeFusion`, `LithologyCrossplotEngine`, `GridSpec` | 改为 `from geoviz import ...`（新 facade 名）；`GridSpec` 仍来自主仓库 |
| `paleo_workbench/ui/pages/geological_modeling_workers.py:14-19, 179, 206` | `generate_cylinder_geometry`, `generate_tube_geometry`, `generate_fault_geometry`, `GridSpec`, `export_to_*`, `check_*` | 几何三函数改为 `from geoviz import ...`；其余不变 |

`create_cylinder_mesh` / `create_tube_mesh` / `create_faulted_surface` / `Layer` / `BoreholeRecord` /
`FaultRecord` / `TunnelRecord`：**零外部调用方**（`Layer` 等仅在 advisor/exporters 内部使用）。

### 4.2 受影响测试（共 10 个文件）

| 测试文件 | 使用符号 | 风险 |
|---|---|---|
| `tests/test_modeling_fault.py` | `FaultCuttingEngine`（12 处，含异常分支） | 低 — 薄适配层保持同名同签名 |
| `tests/test_modeling_tunnel.py` | `TunnelMeshGenerator` | 低 — 同上 |
| `tests/test_modeling_borehole.py` | `BoreholeTraceGenerator`, `get_seam_boundaries` | 低 — 同上 |
| `tests/test_modeling_well_seismic.py` | `WellSeismicTieCalibration` | 低 — 同上 |
| `tests/test_modeling_curve_3d.py` | `WellCurve3DGenerator` | 低 — 同上 |
| `tests/test_modeling_analysis_advanced.py` | `RGBAttributeFusion`, `LithologyCrossplotEngine`, `CrossWellFenceGenerator`（从 `well_seismic` 直接导入） | **中** — 需改 import 路径到包级 |
| `tests/test_cross_well_fence.py` | `CrossWellFenceGenerator.extract_seismic_slice` | 低 — 薄适配层再导出 |
| `tests/test_geological_modeling_3d_page.py` | 几何三函数 + 导出 + 顾问 | 低 — 薄适配层再导出 |
| `tests/test_geomodel_joint_layout.py` | 页面 chrome | 低 |
| `tests/test_geoviz_package_independence.py` | facade 允许清单 | **必改** — 需追加新导出名 |

### 4.3 结论

**影响面可控，可安全迁移。** 依据：

1. 只有 2 个生产文件真正 import 引擎符号，且都在同一功能域内。
2. 所有被迁移的算法都是**纯 numpy 静态方法/自由函数**，无跨模块状态，行为可逐字保留。
3. 采用「引擎为权威实现 + 主仓库薄适配层再导出同名符号」的方式，现有 29 个 geomodel 测试无需改断言，
   仅 `test_modeling_analysis_advanced.py` 需把 `from ...well_seismic import` 改为包级导入。
4. `geoviz_plots.fence` 已有权威实现的先例（`# Cross-well 3D fence mesh (promoted from ...)`），
   本次沿用同一 promote-down 模式，风险模式已验证。

**唯一破坏性变更**：`paleo_workbench.viz.geomodel.well_seismic` 与 `.fence_generator` 两个**子模块路径**
被删除（符号本身仍从包级 `paleo_workbench.viz.geomodel` 与 `geoviz` facade 可用）。见 §6 迁移说明。

## 5. 迁移后的目标结构

```
geo-viz-engine/packages/
├── geoviz_well_tie/geoviz_well_tie/
│   ├── synthetic.py            + synthetic_from_logs()          ← 主仓库 compute_synthetic
│   ├── auto_tie.py             + correlate_synthetic_to_trace()  ← 主仓库 auto_correlate
│   └── calibration.py          + shift_depths()                 ← 主仓库 align_twt_depth
├── geoviz_well_seismic_3d/geoviz_well_seismic_3d/
│   └── well_geometry.py        + offset_curve_along_trajectory() ← 主仓库 generate_curve_mesh
├── geoviz_seismic/geoviz_seismic/
│   ├── attributes.py           + blend_rgba()                   ← 主仓库 blend_rgb
│   ├── crossplot.py    (新)     analyze_lithology_crossplot()   ← 主仓库 LithologyCrossplotEngine
│   ├── gl_clipping.py  (新)     ClippedGLMeshItem/VolumeItem    ← 主仓库 engine.py
│   └── stratal.py      (新)     build_proportional_surfaces()   ← 阶段 2 新增（等时/比例地层切片纯 numpy 核心）
│                                extract_stratal_slice()
│                                stratal_slice_volume()
│                                validate_horizon_pair()
│   └── renderer_3d.py   + set/get/clear_stratal_slices()         ← 阶段 2 新增（3D 渲染接入）
└── geoviz_plots/geoviz_plots/
    ├── fence/                   （已有权威实现，收敛 3 份重复）
    └── geomodel/       (新)
        ├── primitives.py        cylinder / tube / fault surface  ← 主仓库 engine.py
        ├── borehole_tunnel.py   钻孔分段 + RMF 管道               ← 主仓库 borehole_tunnel.py
        └── fault_dislocation.py FaultCuttingEngine               ← 主仓库 fault_dislocation.py

paleo_workbench/viz/geomodel/     ← 薄适配层
├── __init__.py                   facade 再导出 + 本地 advisor/exporters/models
├── models.py                     领域 dataclass（保留）
├── advisor.py                    业务级 AI 顾问（保留）
└── exporters.py                  数值模拟导出（保留）
```

## 6. 迁移说明（面向调用方）

### 6.1 推荐写法

```python
# 引擎能力：一律走 geoviz facade
from geoviz import (
    ClippedGLMeshItem, ClippedGLVolumeItem,          # GL 三向剖切渲染原语
    generate_cylinder_geometry, generate_tube_geometry, generate_fault_geometry,
    BoreholeTraceGenerator, TunnelMeshGenerator, get_seam_boundaries,
    FaultCuttingEngine,
    CrossWellFenceGenerator, generate_fence_mesh,
    synthetic_from_logs, correlate_synthetic_to_trace, shift_depths,
    offset_curve_along_trajectory,
    blend_rgba, analyze_lithology_crossplot,
)

# 业务能力：留在主仓库
from paleo_workbench.viz.geomodel import (
    GridSpec, check_boreholes, check_coplanar_faults,
    export_to_flac3d, export_to_abaqus,
)
```

### 6.2 已删除的子模块路径

| 旧路径 | 替代 |
|---|---|
| `paleo_workbench.viz.geomodel.engine` | `geoviz` facade（GL 项 + 几何函数）；旧路径已删除 |
| `paleo_workbench.viz.geomodel.well_seismic` | `geoviz` facade（`synthetic_from_logs` 等）；旧路径已删除 |
| `paleo_workbench.viz.geomodel.borehole_tunnel` | `geoviz` facade；旧路径已删除 |
| `paleo_workbench.viz.geomodel.fault_dislocation` | `geoviz` facade；旧路径已删除 |
| `paleo_workbench.viz.geomodel.fence_generator` | `geoviz` facade；旧路径已删除 |

包级 `from paleo_workbench.viz.geomodel import <symbol>` **对所有旧符号仍然可用**（薄适配层再导出），
因此现有测试与调用方无需改动，除非它们 import 了上述子模块路径。

### 6.3 兼容性包装类

为避免现有 29 个测试改断言，薄适配层保留了四个类名作为 facade 函数的静态方法包装：

| 兼容类 | 委托到 |
|---|---|
| `WellSeismicTieCalibration.compute_synthetic` | `geoviz.synthetic_from_logs` |
| `WellSeismicTieCalibration.auto_correlate` | `geoviz.correlate_synthetic_to_trace` |
| `WellSeismicTieCalibration.align_twt_depth` | `geoviz.shift_depths` |
| `WellCurve3DGenerator.generate_curve_mesh` | `geoviz.offset_curve_along_trajectory` |
| `RGBAttributeFusion.blend_rgb` | `geoviz.blend_rgba` |
| `LithologyCrossplotEngine.analyze` | `geoviz.analyze_lithology_crossplot` |

这些包装**不含任何算法**，只做参数转发。新代码请直接用 facade 函数。

## 7. 本地验证方式

引擎的 editable 安装在本工作站指向另一个 checkout（`~/projects/paleo_project/geo-viz-engine`），
直接 `pytest` 会测到错误的代码。使用仓库自带脚本：

```bash
./scripts/run_tests.sh workbench -q -m "not slow"   # 主仓库
./scripts/run_tests.sh engine    -q -m "not slow"   # geo-viz-engine（子模块 checkout）
```

脚本负责：钉住 conda 解释器、`QT_QPA_PLATFORM=offscreen`、`LIBGL_ALWAYS_SOFTWARE=1`、
`unset DISPLAY`（pyqtgraph.opengl 会直接走 GLX 并在本机 `:1` 上崩溃），
并把子模块 checkout 置于 `PYTHONPATH` 首位。

### 迁移前基线

| 目标 | 结果 |
|---|---|
| 主仓库 | 1303 passed, 10 failed, 3 skipped, 29 collection errors |
| geo-viz-engine | 1199 passed, 1 failed, 6 skipped |

主仓库的 10 failed + 29 errors **全部**源于本机 GDAL/spatialite 损坏
（`ModuleNotFoundError: No module named '_gdal'`、`libspatialite.so.8: undefined symbol: xmlNanoHTTPCleanup`），
集中在 mapping / app_shell 相关页面，与本次改动无关。
引擎的 1 failed 是 `test_geoviz_plots.py::test_map_edit_feature_editor_topology_rollback`（既有失败）。

## 8. 阶段 2/3 增量结论（等时/比例地层切片 + 主程序专业化）

### 8.1 引擎新能力（全部在 geo-viz-engine）

| 能力 | 位置 | 公共 API |
|---|---|---|
| 等时/比例地层切片核心算法 | `geoviz_seismic/stratal.py`（纯 numpy） | `build_proportional_surfaces` / `extract_stratal_slice` / `stratal_slice_volume` / `validate_horizon_pair` |
| 3D 渲染接入 | `geoviz_seismic/renderer_3d.py` | `Renderer3D.set_stratal_slices` / `get_stratal_slices` / `set_stratal_visible` / `clear_stratal_slices` |
| facade 导出 | `geoviz/__init__.py` | 上述 4 函数 + `HorizonParser` / `HorizonAxes` |

关键设计：地层切片用 `map_coordinates(order=1)` 线性插值，**修正了** `extract_along_horizon` 的整数截断问题
（比例切片下整数截断会产生可见阶梯）。详见引擎文档 `docs/reference-stratal-slices.md`。

### 8.2 主仓库薄适配层（无算法）

| 模块 | 内容 | 边界判定 |
|---|---|---|
| `paleo_workbench/viz/stratal_adapter.py`（新） | 把 `.dat` horizon 解析为预览体对齐的 sample-index 网格 + 演示体；调 facade 的 `build_proportional_surfaces` | ✅ 工作流胶水，无算法 |
| `geological_modeling_3d_page.py` | 分析标签面板 + stratal 入口 + 模型树 + 跨页信号 | ✅ UI 编排 + 调 facade |
| `well_log_prediction_page.py` | `set_selected_well` 跨页 seam | ✅ UI 编排 |

### 8.3 主程序专业化（不破坏既有双列设计）

- 新增 `_joint_analysis_card`（4 tab）由浮动栏「分析」按钮切换；既有的隐藏右轨（遗留建模 UI）不动。
- 模型树在「井震联合」根组内新增「地层切片体 (geoviz)」子项（不增顶层组）。
- 跨页联动：3D 页 `well_selected = Signal(str)` → `WorkflowController` → `WellLogPredictionPage.set_selected_well`。

### 8.4 验证（迁移后 + 阶段 2/3 后）

| 目标 | 结果 | 说明 |
|---|---|---|
| geo-viz-engine（stratal + 渲染回归） | 199 passed, 1 failed | 1 failed 为既有 offscreen-GL 环境问题（`test_update_slice_planes_for_only_replaces_changed_axis`），非本次回归 |
| 主仓库（stage-3 全回归） | 1319 passed, 10 failed, 29 errors | 失败/错误集与迁移前**逐字一致**（GDAL/spatialite + offscreen-GL 环境问题），0 新增失败 |
| 新增测试 | 算法 63 + 渲染 52 + 适配层 5 + 页面入口 7 + 跨页 4 = 131 passed | |

