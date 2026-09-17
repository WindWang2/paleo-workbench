# 12 — Findings：formation_volume / geomodel 纯几何核（逐文件全文阅读）

> 每个公开符号：输入 / 输出 / NaN-空-并列 / 与已有 C++ 核的关系 / 测试缺口。
> 阅读基线：origin/main @ `35987e13`。测试缺口指现有 pytest 覆盖相对本切片
> oracle（§8）所需仍然缺失的部分。

## paleo_workbench/viz/formation_volume.py（128 行，全文读）

### `FormationVolumeIntegrator.compute_closed_volume(top_vertices, bot_vertices, grid_shape=None) -> float`
- 输入：两个形状相同的 (N,3) 顶点数组（文档说 float32；vstack 后统一转
  float64 再累积），`grid_shape=(rows, cols)`。
- 输出：闭合多面体体积的绝对值（float）。
- 校验/失败分支（ValueError，文案逐字）：
  1. `top_vertices.shape != bot_vertices.shape or shape[1] != 3` →
     "top_vertices and bot_vertices must have matching (N, 3) shape"；
  2. `grid_shape is None` → "grid_shape is required: vertex count alone
     cannot identify the (rows, cols) topology (e.g. N=36 is both 4x9 and
     6x6)"（#846：sqrt 推断对多因子分解计数歧义，4x9 与 6x6 都是 36）；
  3. `rows*cols != n_pts` → f"grid_shape {grid_shape} does not match total
     vertices {n_pts}"。
- NaN：不做任何处理（无掩膜）——NaN 输入会静默产出 NaN 体积，调用方契约
  是先清洗。本核不加防护（忠实移植）。
- 数值：faces 由 Python 端生成后 `p0·(p1×p2)/6` 求和再取绝对值；
  np.sum 是成对求和，C++ 用朴素左-to-右和时最后几位 ulp 可不同 → oracle
  比较用相对容差 1e-9（测试缺口：现 pytest 只有 rel=1e-3 的两例）。
- 关系：与 mapping_kernel 无耦合；纯新增 `geomodel::closed_mesh_volume`。
- 测试缺口：4x9 非方阵、UTM 大坐标（float32 输入 + float64 累积）、
  零厚度、上下翻转（体积仍为正）、三个错误分支的**报错文案**均无 pytest。

### `_divergence_theorem_mesh_volume(top_verts, bot_verts, rows, cols) -> float`（私有，行为入 oracle）
- 网格拓扑：顶 [0..N-1]、底 [N..2N-1]；上面片 (i0,i1,i2),(i1,i3,i2)（朝上）、
  底面片 (i0,i2,i1),(i1,i2,i3)（朝下）、四条边带（r=0、r=rows-1、c=0、
  c=cols-1）各 2 三角/段，方向按源码逐字；faces int32。
- 行序：r 外层 c 内层；边带顺序 top→bottom→left→right。C++ 必须复刻同一
  面片生成序（数组 diff 才能为 0）。
- 输出：`abs(sum(signed))`；签名体积单位 = 立方单位。

## paleo_workbench/viz/horizon_sculpting.py（181 行，全文读）

### `SparseDeltaPatch(indices, old_z, new_z)`（dataclass）
- 三等长数组；undo 栈元素。C++ 对应 struct（vector<size_t>/vector<float>×2）。
- 语义要点（#846）：smooth_anneal 只记录**真正变化的顶点**（float32 精确
  != 比较），不能推全量 patch。

### `SculptableHorizonMesh.__init__(vertices, faces=None, grid_shape=None)`
- 校验：`vertices.ndim != 2 or shape[1] != 3` → ValueError "Vertices array
  must have shape (N, 3)"。
- `self.vertices = vertices.astype(np.float32, copy=True)` —— **所有状态是
  float32**；faces 缺省 (0,3) int32；undo/redo 栈空。
- C++：内部以 float 存储，逐位对齐 numpy float32。

### `sculpt_surface(center_xy, delta_z, radius=5.0) -> vertices`
- 高斯刷：`within = dist <= radius`（含边）；`sigma = radius*0.5`；
  `tail = exp(-(radius/sigma)^2)`（python double）；权重 =
  `(exp(-(d/sigma)^2) - tail) / (1 - tail)`，在 radius 处**精确为 0**（#846）。
- float32 细节：dist=float32 hypot；`exp` 为 float32 np.exp；tail/denom 是
  python double 参与运算时按 NEP50 弱标量折回 float32。C++ 用 float 链路
  + double 的 tail/denom 转float，oracle 以容差对齐（跨 libm 超越函数末位）。
- `radius <= 0` → **no-op 返回原数组**（#897，不再 ZeroDivisionError）。
- 无顶点在半径内 → 不压栈、不清 redo，直接返回。
- 副作用：压 SparseDeltaPatch + 清空 redo 栈。

### `set_heights(flat_indices, new_z)`
- 唯一认可的拾取写路径；一个 patch 记录 old/new；空 indices 直接返回；
  values 转 float32。压栈 + 清 redo。

### `smooth_anneal(iterations=1) -> vertices`
- 需要 `grid_shape`（None → ValueError 文案见源码，#846）。
- 逐次：edge-pad 的 4 邻 + 中心×4 / 8 —— **全程 float32**（numpy 数组运算
  保持 float32；除以 python 标量 8 仍 float32）。C++ 逐位复刻：左到右
  `(A+B+C+D+E*4f)/8f`。
- undo patch 只含 `new_z != old_z` 的索引（np.nonzero 严格 float32 比较，
  行序）；无变化 → 不压栈。最后整体写回 z 列。

### `can_undo/can_redo/undo/redo`
- 栈空返回 False；undo 弹栈写回 old_z 并压入 redo；redo 对称。
- 测试缺口：pytest 未覆盖 set_heights、混合操作序列的 redo 失效、
  smooth_anneal 的稀疏 patch 索引内容（#846 测过 patch 大小但未冻结具体
  索引数组）——本切片 oracle 全部冻结。

### `HorizonSculpting.sculpt_surface(vertices, center_xy, delta_z, radius)` / `.smooth_anneal(z_grid, iterations)`
- 无状态包装：临时 mesh；smooth_anneal 用 meshgrid(arange) 生成 x/y，
  返回 reshape 后的 (rows, cols)。数值与类方法一致，不单独移植
  （C++ 以同一实现暴露）。

## paleo_workbench/viz/fault_displacement.py（94 行，全文读）

### `FaultSpec(fault_line_x, throw_z, fault_line_y=0, throw_x=0, dip_deg=60, strike_deg=0, decay_radius=0)`
- 纯参数簇（#1038：fault_line_y 锚定 UTM Y）。C++ 同名字段 struct。

### `FaultDisplacement.apply_fault_throw(vertices, ..., spec=None) -> ndarray`
- spec 优先（整体覆盖 7 参数）。校验 `(N,3)` → ValueError "Vertices array
  must have shape (N, 3)"。`res = vertices.copy()`（dtype 保持：float32 入
  float32 出 / float64 同理 —— C++ 双模板实例）。
- 法向距离：`nx=cos(strike), ny=sin(strike)`（double）；
  `dist_normal = nx*(x-fault_line_x) + ny*(y-fault_line_y)` —— 双锚定
  （#1038）。**NEP50**：float32 数组与 double 标量运算折回 float32。
- `hanging_wall = dist_normal >= 0`（含 0 → 悬臂）。
- heave：`throw_x==0 且 0<dip<90` → `eff = throw_z/tan(radians(dip))`
  （带符号，#846）；否则 eff=throw_x（dip=0/90 或显式 throw_x 走此路）。
- decay>0：`w=exp(-(dist/(dr*0.5))^2)`（float32 exp），footwall 置 0；
  x+=eff*nx*w, y+=eff*ny*w, z+=throw_z*w。
- decay==0：仅悬臂整量平移三轴。
- 测试缺口：throw_x 显式路径、dip 边界、spec 全字段、float64 输入、
  decay+strike 组合的精确数值 —— oracle 全冻结（容差 1e-6/1e-9 两档）。

## paleo_workbench/viz/real_geological_scene.py（137 行，全文读）

### `RealSceneLoadResult`（frozen dataclass）
- mode ∈ {real, demo, empty} + 资产布尔位 + warnings 元组 + asset_summary。
- 依赖 `resolve_joint_assets`/`ProjectDocument`/`_repo_root`（工程域）——
  **非纯几何**，本切片不移植（decisions §D2）。

### `_well_head_count(path)`（私有）
- 数 ≥3 词的非 # 行；OSError/缺失 → 0。文件 I/O 域，不移植。

### `classify_project_mode(project)` / `build_real_scene_snapshot(...)`
- 分类规则 + 警告文案（中文）；有 segy/最小资产 → real；无 segy 无井 →
  demo(允许时)/empty；source_id 经 `source_id_for_path`（异常回退路径串）。
- 测试缺口：无需（不移植；调用面在 catalog/project C++ 线，另有切片）。

## paleo_workbench/viz/geomodel/__init__.py（158 行，全文读）
- 引擎 pass-through + 4 个 deprecated shim（WellSeismicTieCalibration、
  WellCurve3DGenerator、RGBAttributeFusion、LithologyCrossplotEngine）——
  全是参数转发，无算法；真正算法在 geo-viz-engine（well tie / blend /
  crossplot）。**不移植**（boundary：docs/agents/geo-viz-boundary.md）。

## paleo_workbench/viz/geomodel/models.py（55 行，全文读）
### `Layer / BoreholeRecord / FaultRecord / TunnelRecord / GridSpec`
- 旧版建模 dataclass（无 id/provenance），喂 advisor 与 legacy exporter。
- GridSpec(nx,ny,nz,dx,dy,dz) 只被 legacy 合成网格用。**不移植**
  （无几何算法；advisor 见下）。

## paleo_workbench/viz/geomodel/lithology.py（39 行，全文读）
### `LITHO_GR/SONIC/DENSITY/AI` 表 + `DEFAULT_*` + `sample_log_values`
- `[top,bottom)` 掩膜赋值，未知岩性用 default，未覆盖深度 0.0，float32。
- 测井曲线域（demo 叠加噪声后进引擎合成记录）——非体积/厚度几何。
  **本切片不移植**（decisions §D2；M8 井相关切片再议）。

## paleo_workbench/viz/geomodel/domain.py（815 行，全文读）

### `DomainError(ValueError)` / `_slugify(text, fallback)`
- slug 正则 `[^a-z0-9_.-]+`→"-"，strip("-.")，空则 fallback。C++ 不移植：
  object_id 由调用方显式传入（无缺省 slug 构造的消费方）。

### `Provenance`（frozen）/ `DomainObject`（frozen base）
- source_kind ∈ {catalog, derived, imported, demo}；to/from_meta JSON 往返。
- DomainObject 校验：object_id 含 ":"、name 非空（DomainError）。
- meta 序列化属持久化域（ADR-03），本切片只移植 builders 用到的构造校验。

### `WellTrajectory` / `HorizonSurface` / `FaultSurface` / `StratigraphicVolume` / `TunnelSection` / `MeasurementRecord`
- 关键几何校验（DomainError，文案逐字进 oracle）：
  - kind 前缀（well:/horizon:/fault:/volume:/tunnel:/measure:）；
  - stations (N,4) 且 measured 且 ≥2 行时 MD 严格递增
    （"measured stations need strictly increasing MD (QC rejects
    duplicates/non-monotonic input)"）；
  - 数组非 finite（±inf 拒绝；结构化网格 NaN 合法 ——
    `_require_finite_structured`："contains +/-inf (NaN is the only allowed
    hole)"）；
  - confidence/attribute 形状一致；faces 索引范围；curtain 必须 z_extent；
    facies/properties 长度=verts；radius>0；measurement_kind 白名单。
- C++ 策略：**不复制 dataclass 层**；builders 直接接收网格/数组参数并在
  几何核里做同一组校验、抛同文案 std::invalid_argument（decisions §D3）。

### `ModelAssembly` / `geometry_stats(obj)`
- 有序唯一 id 容器（RLock/display/bump_version/meta 往返）——工作区容器，
  非几何核，不移植。
- `geometry_stats`：HorizonSurface 的 all-NaN 网格报 vertex_count=0；
  bounds=min/max。供 meta/inspector；数值上被 QC/导出使用。本切片以
  mesh_qc 覆盖其几何侧，meta 不移植。

## paleo_workbench/viz/geomodel/builders.py（756 行，全文读）——**移植主目标**

### `_z_sign(vertical_domain) -> float`
- tvdss → -1（更深更负，TVDSS = KB - TVD），其余 → +1。交叉判定乘 zsign。

### `build_well_trajectory` / `build_simplified_vertical_well` / `dedupe_stations`
- 轨迹构造/校验 + MD 排序去重（stable argsort；tol 相对判据
  `|Δmd| <= tol*max(1,|prev|)`）。simplified：两站（depth/tvdss：TD z =
  head.z+TD；twt：TD z = TD）。
- 本切片只移植 `dedupe_stations`（导入去重助手，含相对容差与稳定排序
  语义）；两个 well builder 是 dataclass 构造器、无后续几何消费，不移植
  （decisions D3）。

### `build_horizon_from_grid(...)`
- z_grid 非空 2D 校验 + DomainObject 校验委托；NaN 保留为洞。
- C++：HorizonGrid 结构 {rows, cols, origin(2), spacing(2), z row-major}。

### `triangulate_heightfield(z_grid, origin, spacing) -> (verts (N,3), faces (M,3))`
- 有限节点压缩索引（行主序）；四角全有限的 quad → (a,b,c)+(a,c,d)
  （一致朝上绕向）。NaN 四邻任一 → 整 quad 丢弃（不造洞上三角形）。
- 空/单行 → faces 空。测试缺口：pytest 未冻结具体顶点顺序——oracle 冻结
  全数组 diff=0。

### `build_fault_from_mesh(...)`：校验 + representation 标记——**不移植**
（面片导入构造器，无独立几何算法；错误分支与 faces 越界检查随消费方
切片再议）。

### `build_fault_curtain_from_trace(name, trace_xy, z_top, z_bottom, ...)`
- trace (M,2) M≥2 finite；`z_bottom - z_top <= 0` → DomainError（文案含
  "below"）；verts 2M×3（上 M 行 z_top、下 M 行 z_bottom），faces
  (a,b,c)+(a,c,d) 每段。精确数组冻结。

### `build_volume_shell(top, base, boundary, object_id, ...) -> (volume, qc)`
- 前置：top/base 共 vertical_domain+unit（文案 "must share vertical domain
  and unit"）；boundary (M,2) M≥3 finite；两网格 shape/origin/spacing 一致
  （文案含 "resample first"）；nI,nX ≥ 2。
- 保留单元：4 角 finite；中心（0.25*四角和）inside 边界（even-odd 严格
  射线，经 `mapping.geometry_planar.points_in_polygon_vectorized`——单环
  无洞语义）；任一角 `(bg-tg)*zsign < 0` → crossed 丢弃。
- qc：column_count、dropped_crossed（crossed.sum()，含边界外被丢弃者）、
  dropped_nan_nodes（`~node_finite.sum()`，节点级计数）、
  negative_thickness_count（恒 0）、min/max/mean_thickness（kept 单元
  0.25*|ΣΔz|）、closed（边流形全 2）、unit。全空 → closed=False + 0 统计。
- 网格：node_mask 压缩共享节点（行主序 np.nonzero 序）；verts 前 N 顶片
  后 N 底片；每 kept cell 面 (t00,t01,t11),(t00,t11,t10)+(b00,b11,b01),
  (b00,b10,b11)；侧壁在邻居非 kept 的边：(ta,tb,bb),(ta,bb,ba)。
- `_orient_faces_outward`：面心-壳心点积 <0 → 翻 (0,2,1)（星形假设）。
- `_shell_is_closed`：无向边计数全 =2（key=lo*(max_hi+1)+hi）。
- 单元遍历序：`sorted(finite_cells)`（(i,j) 字典序）→ 面/厚度序固定。
- 测试缺口：pytest 有 6 例但未冻结 verts/faces 数组、orient 翻转集合、
  thickness 数组、空壳 qc 全值 —— oracle 全冻结。

### `build_columnar_hex_mesh(top, base, boundary, n_layers=4) -> (nodes, hexes, info)`
- 同前校验 + n_layers≥1（"n_layers must be >= 1"）；kept = inside & ~crossed。
- 每单元**私有**节点 (n_layers+1)*4：corner 外层 layer 内层；z = zt+(zb-zt)*f，
  f=np.linspace(0,1,n_layers+1)（步进 i/n，末点精确 1）。hex 节点序：底环
  [(i,j),(i+1,j),(i+1,j+1),(i,j+1)] 后顶环同序。info{n_cells,n_layers,
  n_hexes,skipped_crossed,unit,merge:"none"}。
- `hexes[layer::n_layers]` 的**条带填充序**：切片步长使 hex 行序为
  cell-major（row = cell*n_layers + layer，每个 cell 的 n_layers 个六面体
  连排）。C++ 必须复刻该顺序，数组 diff 才为 0。

### `_points_in_polygon_grid(px, py, poly)`（私有，语义进 oracle）
- 委托 geometry_planar.points_in_polygon_vectorized：单环 even-odd，
  `y1==y2` 跳过、`(y1>y)!=(y2>y)` 跨越、`x < x1+t*(x2-x1)` 严格小于、XOR。
  **边界点语义未定义但确定**（数值命中即计数）——与 mapping_kernel 的
  inclusive 变体不同，不能复用其函数（decisions §D5）。

## paleo_workbench/viz/geomodel/measurements.py（285 行，全文读）——**移植主目标**

### `point_coordinate / distance / polyline_length / vertical_difference`
- 校验 `_pts`（≥min 点、(N,3)、finite；文案 "needs >= N (x, y, z) points" /
  "points must be finite"）。result：norm(b-a) / Σleg 范数 / b.z-a.z。
- extra 携带 {unit}/{legs}/{dz}；object_id 计数器 `measure:<kind>-<n>`
  （线程锁内自增，进程态——C++ oracle 不冻结 id 序，只冻结 result/extra）。

### `thickness_at(x, y, top, base, ...)`
- top/base 必须同 vertical_domain+unit（文案 "thickness: top/base must
  share vertical domain and unit"）。
- `_bilinear_z`：fj=(x-x0)/dx, fi=(y-y0)/dy（dx/dy 为 0 → 0.0）；越界
  (i0<0 / j0<0 / i0>nI-1 / j0>nX-1) → None；**上角钳位 min(i0,nI-2)、
  min(j0,nX-2)**（边缘拾取插值末格而非误报洞）；任一角非有限 → None。
- 洞 → DomainError（文案含 "point falls in a grid hole (NaN) — thickness
  unknown"，fail-closed 不给 0）；result=|zb-zt|，extra.signed=zb-zt。
- 测试缺口：边缘钳位、格中心外（fi∈(0,1)）的**具体插值值**未冻结 ——
  oracle 冻结（1e-12）。

### `plane_orientation(points, ...)`
- 质心去均值 → SVD（gesdd）；normal=vt[-1]，z<0 翻；dip=deg(arccos(|nz|))；
  strike=deg(arctan2(ny,nx))，负值 +180；planarity=s1/s0（s0>0 否则 0）。
- C++：3×3 协方差特征分解（Jacobi）→ 最小特征向量等价 vt[-1]；LAPACK 与
  Jacobi 差异用 1e-6 容差；共面输入特征方向稳定。
- result=dip；extra 三键 + note 文案（format_result 消费）。

### `format_result(record) -> str`
- 六 kind 分支的**逐字文案**（含 "°"、正号 "+"、"(N legs)"、
  "(vertical thickness)"、"(planarity x.xx)"）——oracle 全冻结字符串。

## paleo_workbench/viz/geomodel/analysis.py（200 行，全文读）
- `_well_depth_axis`（linspace 采样轴）、`generate_well_curve_overlays`、
  `run_auto_tie`、`generate_cross_well_fence`、`run_lithology_crossplot`：
  全部委托 geoviz 引擎（synthetic_from_logs / offset_curve / fence /
  crossplot）+ demo 噪声；`generate_seismic_slice_overlay`、
  `generate_rgb_fusion_slice` 纯 demo。**引擎域，不移植**
  （geo-viz-boundary）。测试缺口：无需。

## paleo_workbench/viz/geomodel/qc.py（626 行，全文读）
- 四级阶梯（info/warning/error/blocker）+ `assert_exportable` 导出门禁
  （ADR-06，blocker 才拒）+ 六个 per-object 审计 + `QCReport` meta 往返。
- 几何数值子核（**本切片移植**，供 shell/面片审计）：
  - `_tri_degenerate_fraction`：最短边 ≤ 1e-12*max(最长,1e-12) 比例；
  - `_edge_manifold_stats`：boundary=count==1、nonmanifold=count>2
    （key 同 `_shell_is_closed`）；
  - `_connected_components`：scipy csgraph，缺 scipy 回退 union-find
    （计数等价；C++ 用并查集实现同计数）。
- 阶梯/文案/STALE_SOURCE/导出门禁属业务层，**不移植**（decisions §D4）。
- 测试缺口：degenerate/edge stats 的具体数值未被 pytest 断言（只断言
  code/severity）——oracle 冻结数值。

## paleo_workbench/viz/geomodel/section.py（209 行，全文读）——**移植主目标**

### `Plane(normal, d)` / `axis_plane` / `plane_from_normal_point` / `clip_planes_for_box`
- 构造时归一（|n|<1e-12 → ValueError "plane normal must be non-zero"）；
  d 同除 |n|。`signed_distance = p·n - d`。
- `as_clip_equation(invert=False)`：s=±1，(s·n, s·-d)（GL 约定保留 n·p<=d）。
  axis_plane 非法轴 → ValueError（f"axis must be x/y/z, got {axis!r}"）。
  box → 6 方程（+x,-x,+y,-y,+z,-z 朝内）。

### `intersect_plane_with_triangles(plane, verts, faces) -> list[(2,3)]`
- 逐三角形（faces reshape(-1,3)，空 → []）：零点 ≥2 → 直接连两零点；
  1 零点 + 有正有负 → 零点入列；全部 +/− 对按 (a,b) 双循环序
  `t = d[a]/(d[a]-d[b])` 线性插值。edge_pts ≥2 → 输出 [p0,p1]。
- 未排序段列表 → `_chain_segments` 贪心链化：容差
  `max(1e-9, 全点最大绝对值*1e-9)`；四方向匹配（尾接尾/头接尾/尾接头/
  头接头，np.max(np.abs(·)) < tol 严格）；pop(0) 起始、顺序扫描。

### `horizon_plane_intersection` / `mesh_plane_intersection` / `well_plane_crossing`
- 前两者 = 三角化/裸网格 → 段 → 链。井穿越：np.sign 分类，sign==0 立即
  返回该点；相邻异号（且后者非 0）→ `t=d[k]/(d[k]-d[k+1])` 插值；否则 None。
- 测试缺口：链化顺序、零点简并（顶点恰在面上）、invert 方程值 —— oracle
  全冻结（1e-9）。

## paleo_workbench/viz/geomodel/advisor.py（167 行，全文读）
### `check_boreholes(boreholes)` / `check_coplanar_faults(faults)`
- 确定性业务规则（层序重叠 1e-5 容差、深度非正、坐标非有限；法向平行
  |‖·‖-1|<0.05 后 d/|n| 距离差 <15 判共面，#897）。dict 兼容转换层。
- 属业务规则层（无体积/厚度），**本切片不移植**（decisions §D4）。

## paleo_workbench/viz/geomodel/demo.py（135 行，全文读）
- `gr_noise / seismic_slice_geometry / rgb_fusion_geometry /
  synthetic_field_trace / crossplot_samples`：显式合成数据（固定种子）。
- 文件头自述 **NOT production code**。**不移植**。

## paleo_workbench/viz/geomodel/scene_adapter.py（737 行，全文读）
- Domain→engine 场景同步（token 缓存、可见性/不透明/剖切/拾取回映、
  decimation、facies 调色、blake2b checksum）——**渲染适配层，不迁**
  （§4 明确排除 3D 渲染/GL）。`_finite_checksum`（nan→0 规范化）若未来
  C++ 场景层需要时另切片。

## docs/development/geology-3d-modeling-v5/（4 文件全文读——约束抄录）
- baseline.md：能力矩阵（转换前）；renderer-only 状态问题清单；
  引擎可复用能力（add_horizon NaN 保持等）；明确不做：大规模转码、
  井震联动算法重做。
- target-state.md：B5（shell 构建 + QC + 柱状六面体）、C5（测量 domain
  单位、不用像素距离）、D1-D4（QC 阶梯、blocker 门禁、真实体导出、
  parser 往返）为本切片 C++ 对应面的 Python 侧完成态。
- decisions.md：ADR-03（meta 序列化 vs 数组走 Catalog）、ADR-06（export
  从真实体）、ADR-08（测量是 domain 对象）、ADR-09 修订（shell 法线按
  形心统一朝外，覆盖 depth/TVDSS 双约定；QC 与方向无关）——C++ 实现的
  `_orient_faces_outward`/zsign 语义依据。
- verification.md：headless 用例分布（domain 23/builders 19/qc 18/
  exporters 16/measure+section 14）；三维渲染/teardown 域不属本切片。

## 相关 pytest（全文读，断言→oracle 案例表）
- test_formation_volume.py：盒体 2000、形变面 2000（rel 1e-3）→ oracle
  升级为 1e-9 相对 + 增加 4x9/UTM/零厚度/错误分支。
- test_horizon_sculpting.py：形变>105、远场不变、undo/redo 往返、方差
  下降 → oracle 冻结逐顶点 z 数组（float32 逐位）+ patch 索引。
- test_fault_displacement.py / _utm.py：悬臂 85/90、衰减序、UTM 锚定、
  strike 30/45 平移不变、heave 符号、spec 字段 → oracle 冻结逐顶点。
- test_geomodel_builders.py：计数（50 三角、16 列、9 crossed、25 cell、
  hex 4 层）、TVDSS 三例、失配报错 → oracle 冻结数组 + qc 全键。
- test_geomodel_measure_section.py：3-4-5、polyline 2、vert -15、厚度
  50 + 洞报错、平面 0<dip<45、clip 方程、z 剖面单链、洞分裂、井穿越
  -150 → oracle 冻结（含 format_result 串）。
- test_geomodel_qc.py：好井 ok、非单调 blocker（构造绕过路径）、
  空网格/开壳 blocker、crossed 警告、STALE_SOURCE → 几何数值子核入
  oracle；阶梯业务层不移植。
- test_geomodel_domain.py：meta 往返/slug（"well:w-1"）、inf 拒绝、faces
  越界 → slug + 校验文案入 oracle；meta 层不移植。
- test_geomodel_exporters_v2.py / test_issues_825_829_846.py（几何相关）：
  `_generate_structured_grid` 的 C3D8 面序 + 散度体积（legacy 合成网格）
  ——导出/legacy 域不移植（decisions §D6），其余 #825/#846 用例为 LOD/
  相关引擎，不属本切片。
- test_issue_897_misc_batch.py（#3 sculpt radius no-op、#4 advisor 归一）：
  radius no-op 入 sculpt oracle；advisor 不移植。
- test_geomodel_analysis_services.py / test_geomodel_page_v5.py 等：
  引擎/页面域，不移植（读毕确认无本切片数值断言）。
