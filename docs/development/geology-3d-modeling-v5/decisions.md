# 3D Geological Modeling V5 — Decisions (ADR 摘要)

格式：Context / Decision / Consequences。重大决策在此追加。

## ADR-01 可见视口收敛到 joint Renderer3D，移除隐藏遗留 GLViewWidget

- **Context**：页面存在双 3D 栈——可见的 `WellSeismicJointWidget`（引擎）与
  永久隐藏的遗留 `gl.GLViewWidget`（建模输出只进后者，用户不可见）。
  建模 GL 状态（`active_items`/`mesh_items_map`）是 renderer-only 第二权威。
- **Decision**：建模/地质对象经新的 `GeologicalSceneAdapter` 渲染进可见 joint
  视口的 Renderer3D；删除隐藏视口与其 item 记账；demo 路径不再覆盖
  `bh_raw_data`。
- **Consequences**：删除部分遗留页面代码与个别测试断言需更新；视口统一后
  剖切/拾取/测量只需适配一个 renderer。

## ADR-02 引擎新增公开 SceneObject API（子模块分支 + PR）

- **Context**：Renderer3D 现有 overlay 插槽是单用途（add_horizon 单 mesh、
  set_isosurface 单槽），无命名对象、无逐对象剖切、无 mesh 级拾取。页面曾以
  reach-in `renderer._view` 方式拼 item（脆、违边界）。
- **Decision**：geo-viz-engine 新增 `geoviz_seismic.scene_objects.SceneObjectManager`
  ——命名对象（mesh/lines/points/text）、逐对象 visible/opacity/color/pickable/
  clip planes（GL_CLIP_PLANE 任意平面，paint 期间局部启停）、CPU ray-triangle
  拾取、bounds；Renderer3D/WellSeismicJointWidget 委托公开方法。domain→render
  坐标变换仍由调用方完成（引擎保持 CRS 无关）；scene 补公开逆映射
  `render_to_world_xyz_array`。
- **Consequences**：需要子模块 branch/PR + 父仓 gitlink bump（主 PR 列明依赖）；
  引擎 API 面增大，需 stub 测试守卫。备选（主仓 reach-in _view 拼 item）被否：
  违反"UI 不拼 native node"边界且跨版本脆。

## ADR-03 Domain 模型 V2：主仓 dataclass + 元数据序列化，数组走 Catalog

- **Context**：现有 `models.py` dataclass 无 id/provenance/序列化，workers 发射
  raw dict（primitive obsession）。ProjectDocument 只持久化 joint 展示状态。
- **Decision**：新 `viz/geomodel/domain.py`：frozen-ish dataclass（数组字段按
  不可变约定），稳定 object_id（`<kind>:<slug>`），`to_meta/from_meta` 只序列化
  身份/CRS/unit/provenance/统计；顶点/网格数组持久化走 Catalog 版本化工件
  （NPZ），project JSON 只存对象引用与展示状态。旧 `models.py` 保留兼容
  （advisor/exporter 旧签名不变），不并行第二体系。
- **Consequences**：重开时体积对象从 Catalog 工件懒重建，工件缺失则对象标记
  stale（诚实降级）；demo/synthetic 对象明确 `demo=True` 不持久化。

## ADR-04 剖切范围由 survey 边界推导；任意平面走 GL_CLIP_PLANE

- **Context**：现有剖切滑条硬编码 ±80 世界坐标；引擎 ThreeWayClipMixin 只支持
  X/Y/Z 三轴。
- **Decision**：adapter 用 volume/survey AABB 归一化剖切值（页面只存 0-100
  UI 值+方向）；对象剖切平面以 (a,b,c,d) 传入引擎，paint 期间启用
  GL_CLIP_PLANE0..N，core profile 自动降级（复用引擎现有检测）。box clip=6 平面。
- **Consequences**：compatibility profile 下剖切可用（现状一致）；core profile
  下载面剖切不可用为已知限制（引擎一次性告警，不静默伪造）。

## ADR-05 拾取在引擎（相机数学在引擎），测量在主仓（单位/CRS 在 domain）

- **Context**：拾取需要 view/projection 矩阵（pyqtgraph GLViewWidget 公开方法
  但相机语义属引擎）；测量结果必须是 domain 单位。
- **Decision**：引擎 `pick_scene_object(px,py)`：屏幕→ray（与现有盒体拾取同
  约定）→CPU Möller–Trumbore 命中 pickable 对象，返回 name+render 坐标；主仓
  adapter 用 `render_to_world_xyz_array` 逆映射回 domain 坐标再做测量/单位换算。
- **Consequences**：命中测试精度为 CPU 逐三角形（中型网格够用，>百万三角形时
  由 LOD/decimation 预算保护）；不引入 GPU 拾取依赖。

## ADR-06 导出从真实 domain 体构建柱状六面体网格

- **Context**：现 exporters 按 GridSpec 现场生成含硬编码 z 波动的网格，导出物
  与场景无关。
- **Decision**：`export_volume_flac3d/abaqus` 输入 StratigraphicVolume：top/base
  曲面 → (i,j) 柱 → nz 层六面体；跳过 inverted/crossing 柱（QC 先行，blocker
  拦截）；节点坐标=domain CRS+单位；写 provenance sidecar（JSON：对象 id、
  source versions、CRS、QC 摘要、索引约定）。OBJ/STL 导 surface；VTK XML .vtp
  导 surface（含属性数组）。
- **Consequences**：需要 volume 有可信 top/base（QC 保证）；FLAC3D 输出保留
  旧 GridSpec 签名做向后兼容（标记 legacy）。VTK 写手写 XML（无 vtk 依赖），
  parser 校验保证非占位。

## ADR-07 页面状态持久化：新增 Geo3DWorkspaceState section

- **Context**：JointAnalysisState 已承载 joint 展示状态；地质对象/视图状态无
  载体。
- **Decision**：`project/models.py` 新增 `Geo3DWorkspaceState`（pydantic）：
  camera pose、命名 view presets、剖切 view state（UI 0-100 值+方向+启用）、
  对象可见性覆盖、轻量测量记录（点/线坐标，非大数组）；对象本体/网格经
  Catalog 引用（ADR-03）。flush/restore 挂现有 project_controller 钩子。
- **Consequences**：project schema 增 section（extra=allow 兼容旧文件）；
  保存内容全部是 view/reference state，不序列化 GPU/scene handle。

## ADR-08 测量/标注为 domain 对象（轻量），不进 renderer 权威

- **Context**：测量结果若只画在 renderer 就又成 renderer-only state。
- **Decision**：`MeasurementRecord` 是 domain 对象（id、kind、点列、结果、
  单位），adapter 把它渲染为 lines/points/text overlay；随 workspace 保存
  （ADR-07），可删除。
- **Consequences**：测量可重放/可审计；大量测量只影响轻量 line item。
