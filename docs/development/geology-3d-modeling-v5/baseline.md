# 3D Geological Modeling V5 — Baseline（G0 审计）

Branch: `feat/geology-3d-modeling-v5`
Worktree: `/home/kevin/projects/paleo-wt-geology-3d-modeling-v5`
Base: `origin/main` @ `049423ab`（geo-viz-engine @ `aa419790`）
审计日期：2026-09-06

## 1. 架构现状

3D 渲染主体在子模块 geo-viz-engine：
`WellSeismicJointWidget`（`geoviz_well_seismic_3d/joint_widget.py`）= 可见视口，
内含 `Renderer3D`（`geoviz_seismic/renderer_3d.py`，4004 行）+ headless
`WellSeismicScene`（`scene.py`）。主仓 `viz/geomodel/` 是薄适配层（领域
dataclass + advisor + 分析纯函数 + 数值导出），页面
`ui/pages/geological_modeling_3d_page.py`（3493 行）驱动。

### 能力矩阵（G0）

| Object | Domain model | Scene node | Serializable | Pickable | Cataloged | Exportable | QC |
|---|---|---|---|---|---|---|---|
| 井（joint survey 井） | ✗（dict 流，`WellHead` 在引擎） | GLLinePlotItem×2+Scatter+Text（joint widget） | 部分（JointAnalysisState 只存可见性） | ✅ CPU 屏幕空间（`_PickFilter`+`pick_well_name`） | 井资产经 catalog | ✗ | ✗ |
| 井（建模 BoreholeRecord） | 半（dataclass 无 id） | 仅在**隐藏** gl_widget（圆柱 mesh） | ✗ | ✗ | demo run 有标记 | ✗ | advisor.check_boreholes |
| 层位面 | ✗（.dat 网格→preview-index 网格直通） | renderer.add_horizon（单 mesh，additive） | 解释工件 NPZ（stratal 输入） | ✗ | 解释工件有 | ✗ | 无 |
| 断层面 | `FaultRecord(normal,d)`（无限平面！非面片） | 仅隐藏 gl_widget（generate_fault_geometry 穹面） | ✗ | ✗ | ✗ | ✗ | check_coplanar_faults |
| 地层体 | ✗（无体对象；FormationVolumeIntegrator 孤儿） | ✗ | ✗ | ✗ | ✗ | ✗（exporters 现场造网格） | ✗ |
| 巷道/Tunnel | `TunnelRecord(path)` | 仅隐藏 gl_widget（tube） | ✗ | ✗ | ✗ | ✗ | ✗ |
| 测量/标注 | ✗ | renderer.set_annotations（未接线） | ✗ | ✗ | ✗ | ✗ | ✗ |
| 剖切 | slice state 在 scene（正交/时间/stratal） | GL clip planes（仅隐藏视口 mesh） | JointAnalysisState（切片 index+物理线号） | n/a | ✗ | ✗ | ✗ |

### 发现的问题（renderer-only state / 生命周期 / 坐标）

1. **双视口分裂**：`_run_modeling` 全部建模输出渲染进永久 `hide()` 的遗留
   `gl.GLViewWidget`（page :154），用户在可见 joint 视口看不到任何建模结果；
   `active_items`/`mesh_items_map` 等全部 renderer-only、不持久化。
2. **demo 污染真实数据**：`_on_modeling_completed`（:2877）用 4 口硬编码 demo
   井覆盖 `bh_raw_data`，auto-tie/fence/crossplot 随后基于合成数据。
3. **导出与场景脱节**：`exporters.export_to_flac3d/abaqus` 按 GridSpec 现场
   生成结构网格（含硬编码 z 波动 exporters.py:33），导不出用户看到的模型；
   无 VTK/OBJ/STL。
4. **坐标隐式假设**：剖切滑条硬映射 ±80 世界坐标（:3217）；demo stratal 把
   合成体灌进真实 renderer（:1477）无恢复路径。
5. **引擎私有属性 reach-in**：`renderer._view`、`renderer._stratal_surfaces`、
   `widget._index_xyz_to_world`、`renderer._loaded`。
6. **死树键**：`_sync_visibility_from_tree` 特判的多个键在 `_populate_model_tree`
   中不存在，勾选不可达。
7. **既有测试 flake**（origin/main 复现）：
   `test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_clip_and_tie_without_show`
   断言 `splitter.widget(0).maximumWidth() <= 320`，offscreen 下 maximumWidth
   未被布局实现收敛（16777215），环境相关。
8. **scene 重绑语义**：`WellSeismicJointWidget.set_scene` 只重绑；volume 卸载时
   `renderer.clear()`（清 volume/planes/horizons，不涉及未来 overlay 对象管理器）。
9. **real_geological_scene.has_faults 硬编码 False**（:84）→ 无真实断层来源。
10. **基线测试状态**：3D 相关 24 个测试文件；`run_env_g3d.sh` 抽样 7 文件
    80 passed / 3 skipped / 1 failed（即上述 flake）。

## 2. 引擎可用能力（复用，不重做）

- `Renderer3D.add_horizon`（结构网格+NaN 空洞）、`set_isosurface`（单 mesh）、
  `set_stratal_slices`、正交/时间切片、`set_camera_pose`、盒体 ray-AABB 拾取、
  `set_annotations`。
- `ThreeWayClipMixin`：item paint 期间局部启用 GL_CLIP_PLANE0..2（可扩展到
  任意平面、逐对象）。
- 几何纯函数：`generate_cylinder_geometry`、`generate_tube_geometry`（RMF tube
  在 `TunnelMeshGenerator`）、`generate_fence_mesh`、`HorizonParser`（NaN 保持）。
- `WellSeismicScene.world_to_render_xyz_array`：world(XY)+domain(Z) → render
  index 空间（公开）；**反向映射缺失**（拾取命中→domain 需要逆变换）。
- pyqtgraph GLMeshItem 支持 setColor/setGLOptions/setMeshData 动态更新；
  show()/hide() 控制可见性。

## 3. 主仓平台契约（复用）

- Catalog：`catalog.lifecycle.register_modeling_run`（kind="geomodel"，
  demo 诚实无 output version）、`DataCatalogService.register_output`、
  `CatalogPort`（port.py）。
- Project：`ProjectDocument.joint_analysis: JointAnalysisState`（pydantic）；
  保存路径 `ui/project_controller.py:838 _flush_joint_analysis_state` →
  `page.save_joint_analysis_to_project()`；恢复 `page.set_project`。
- `SelectionContext`（selection_context.py）：frozen `SelectionState`，
  `source_widget_id` 源标记，well/horizon/fault 稳定 id 契约。
- `CoordinateTransformHub`：最小曲率轨迹、时深 fail-closed、井↔图↔震。
- 测试：pytest-qt offscreen；`opengl` marker 由 CI Xvfb/llvmpipe leg 跑；
  conda python3.13 + PYTHONPATH 指向 worktree 子模块（`run_env_g3d.sh`）。

## 4. 明确不做（本轮）

- 100GB 地震体 benchmark / 大规模转码。
- 井震联动算法重做（well tie、stratal 核心在引擎，已存在）。
- Catalog 分页/查询引擎、全局 token/QSS、harness Workflow DAG。
- orthographic 相机（pyqtgraph GLViewWidget 仅透视投影；不伪造）。
