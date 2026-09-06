# 3D Geological Modeling V5 — Target State（可勾选验收清单）

Branch: `feat/geology-3d-modeling-v5`

## A. 架构

- [ ] A1 分层成立：Domain（权威）→ SceneAdapter（可重建视图）→ 引擎 renderer → viewport；
      renderer/GPU handle 不再是科学数据 source of truth。
- [ ] A2 `viz/geomodel/domain.py`：WellTrajectory / HorizonSurface / FaultSurface /
      StratigraphicVolume / TunnelSection / MeasurementRecord / ModelAssembly，
      均有稳定 object_id + provenance + to_dict/from_dict（元数据）。
- [ ] A3 `viz/geomodel/scene_adapter.py`：确定性 rebuild（同输入→同场景）、
      对象级增量 sync、visibility/opacity/color/clipping、对象 id 即渲染名。
- [ ] A4 隐藏遗留 gl_widget 建模流移除；建模输出经 adapter 进入**可见** joint 视口；
      双权威消除。
- [ ] A5 UI/页面不再 reach-in 引擎私有属性（`renderer._view`、`_index_xyz_to_world`
      等改走公开 API）。
- [ ] A6 引擎（geo-viz-engine）新增公开 SceneObject API（命名对象、逐对象
      可见性/透明度/剖切平面、ray-mesh 拾取），子模块独立 branch/PR。

## B. 对象能力

- [ ] B1 WellTrajectory：vertical/deviated/horizontal（MD stations，最小曲率参考
      coordinate_hub）；井口名标签；半径/宽度缩放；选中段高亮；简化垂直指示
      （LAS-only 井显式 representation，不伪造轨迹）。
- [ ] B2 井轨迹 QC：MD 非单调 / duplicate stations / missing XYZ / 混合单位 /
      CRS 缺失 / zero-length segment 全部有检查。
- [ ] B3 HorizonSurface：结构网格 + NaN 空洞保留（空洞不生成假三角形）、边界
      裁剪、三角化、法线、属性着色、confidence 覆盖、surface 拾取。
- [ ] B4 FaultSurface：三角网格（imported/derived）与 2.5D curtain（2D trace 推导）
      双表示，representation 显式标记；pick/visibility/style。
- [ ] B5 StratigraphicVolume：top/base+闭合侧面 shell 构建；QC：crossing/
      负厚度/pinch-out/watertight/self-intersection（有界）/missing area；
      display mesh + 计算网格 adapter（柱状六面体）。
- [ ] B6 Facies/property 显示：categorical + continuous 着色（数据来自
      Catalog/versioned artifact；renderer 内无新科学算法）。

## C. 交互

- [ ] C1 统一剖切：X/Y/Z 轴平面、box clip、enable/disable、invert、interactive
      move（由 survey 边界推导范围，不再 ±80 硬编码）、reset；剖切是 view state。
- [ ] C2 剖面交线显示：horizon/fault/井与剖切面交线。
- [ ] C3 拾取闭环：click→选中→高亮→树同步→SelectionContext 广播（带
      source_widget_id）→Inspector；scene selection echo 有 source tagging。
- [ ] C4 Inspector：identity、source version、CRS/domain/unit、QC、provenance、
      geometry stats。
- [ ] C5 测量：point / distance / polyline length / vertical difference /
      thickness（top/base）；结果显示 domain+unit；不用像素距离冒充科学距离。
- [ ] C6 相机：fit all / fit selected / top-front-side / reset / 命名 view preset
      保存+恢复；项目重开后 preset 可恢复。

## D. QC / 导出 / 溯源

- [ ] D1 `viz/geomodel/qc.py`：severity 分级 info/warning/error/blocker；
      geometry/CRS/unit/bounds/NaN/degenerate/non-manifold/crossing/thickness/
      watertight/disconnected/stale 全覆盖（对象适用范围内）。
- [ ] D2 export 前 blocker 阻止导出（错误模型不静默导出）。
- [ ] D3 exporters 重写：FLAC3D/Abaqus 从**真实 StratigraphicVolume** 导出
      （柱状六面体，跳过 inverted cells）；OBJ/STL（网格）；VTK XML .vtp；
      全部带 CRS/unit/node 索引/provenance sidecar。
- [ ] D4 格式验证：FLAC3D/Abaqus/OBJ/STL/VTP 至少 parser 级 round-trip 校验
      （写→读→断言节点/单元数、bounds、索引有效）。
- [ ] D5 建模/导出 run 经 Catalog DataRun/DataVersion 注册（复用
      register_modeling_run/register_output），parameters 带 domain id + QC 摘要；
      不新建 model.db。

## E. 稳定性 / 性能

- [ ] E1 中型项目无每帧 Python 几何重建：adapter 按 token 缓存，仅变更对象重建。
- [ ] E2 synthetic 规模验证：100/500/1000 井、10/50 面、中型网格；记录批量
      rebuild 时间比率与内存趋势（非脆弱毫秒绝对值）。
- [ ] E3 save/reopen/teardown：open→load→close→reopen→switch project→destroy
      viewport→recreate ≥30 循环无 "destroyed C++ object" 复发。
- [ ] E4 native backend unavailable / GL unavailable 降级路径：页面显示不可用态，
      不崩溃（joint widget 已有该模式，新 API 同样守卫）。
- [ ] E5 既有 flake（maximumWidth≤320）修复或改为确定性断言。

## F. 测试

- [ ] F1 domain/builders/qc/measurements/exporters/section 单元测试（headless）。
- [ ] F2 scene_adapter stub-view 测试（diff/增量/泄漏防护/teardown）。
- [ ] F3 页面集成测试（树/Inspector/QC 面板/测量/拾取路由/persistence 往返）。
- [ ] F4 save/reopen 循环测试（≥30 周期）。
- [ ] F5 引擎侧 SceneObjectManager/picking stub 测试（子模块）。
- [ ] F6 全部新旧测试本地通过（targeted→integration 顺序；资源约束 -j2）。
