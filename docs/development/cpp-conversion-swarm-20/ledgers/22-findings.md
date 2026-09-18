# 22-findings — geomodel 契约层(domain/qc/exporters/advisor/lithology/builders 构造器)阅读记录

全部 §5 文件**全文阅读**后逐符号记录。阅读基线:main `422c7e47`(CONV-21 后)。
➤ = 本切片实现范围。

## 范围裁定

- ➤ `domain.py`(815 行,全文)— 纯契约层:numpy + dataclass + threading.RLock,零 Qt/GL/geoviz。
- ➤ `qc.py`(626 行,全文)— 纯审计层;数值核(`_tri_degenerate_fraction`/`_edge_manifold_stats`/`_connected_components`)conv-12 已在 `mesh_qc` 移植,本层是 issue 编排 + 报告。
- ➤ `exporters.py`(739 行,全文)— 纯文本/二进制写器 + 解析验证器;几何核 `build_columnar_hex_mesh` conv-12 已移植。
- ➤ `advisor.py`(167 行,全文)— 纯规则检查(numpy only)。
- ➤ `lithology.py`(39 行,全文)— 纯查找表 + `sample_log_values`。
- ➤ `builders.py` 构造器半:`build_well_trajectory`/`build_simplified_vertical_well`/`build_fault_from_mesh`/`_unique_slug` — 纯 dataclass 构造;几何核全部已在 conv-12(`triangulate_heightfield`/`build_fault_curtain_from_trace`/`build_volume_shell`/`build_columnar_hex_mesh`/`dedupe_stations`/`build_horizon_from_grid`/`_orient_faces_outward`/`_shell_is_closed`/`_points_in_polygon_grid`/`_z_sign`)。
- 不迁:`scene_adapter.py`(737 行)— Qt/GL 桥(`_scene_objects_reachable(widget)` 查 Qt wrapper、`geoviz.generate_tube_geometry`、GL-less 分支);`analysis.py`(200 行)— 全部委托 `geoviz.*` 引擎 + `demo.*` 采样;`demo.py`(135 行)— `geoviz.blend_rgba` + 明确非生产合成器;`models.py` — dataclass 定义由 C++ contract struct 承担,无独立逻辑。

## domain.py — 逐符号

### `_slugify(text, fallback)` / `_SLUG_RE`
- `re.sub(r"[^a-z0-9_.-]+", "-", str(text).strip().lower()).strip("-.")`;空结果回退 fallback。
- Python `str.strip()` 默认字符集 = 全部 Unicode whitespace;`.lower()` 是全 Unicode lower(非 ASCII-only)。`[^a-z0-9_.-]` 字符类按**码点**匹配。
- 输入经 `str()`:int/float/None 先文本化。

### `_clean_ids(ids)` = `tuple(str(i) for i in (ids or ()))`
- `ids or ()`:falsy(空 list/None/0/"") → ();truthy 非序列(如 `5`)→ `for i in 5` TypeError。
- dict 输入按键迭代。

### `Provenance`(frozen dataclass)
- 字段:source_kind="derived"、source_version_ids=()、created_from=""、demo=False。
- `to_meta` → dict 4 键(顺序固定);`from_meta`:`meta or {}` 回退 + `str()`/`bool()` 强转 + `_clean_ids`。

### `DomainObject.__post_init__`
- `not object_id or ":" not in object_id` → DomainError `"object_id must be '<kind>:<slug>', got {object_id!r}"` — 用 `!r`(repr)。
- `not name` → `"{object_id}: name must be non-empty"`。
- `kind` 变量取了但没用于消息(只取 object_id 冒号前段)。

### 各子类 __post_init__(prefix 校验在 DomainObject 之后)
- WellTrajectory:`well:` 前缀;stations (N,4) ndim==2 校验(空数组放行 ndim 检查但 (0,) 1-D 会拒:`st.ndim != 2 or (st.size and st.shape[1]!=4)`);`_require_finite`(NaN+inf 都拒);representation ∈ {measured, simplified_vertical};measured 且 ≥2 行 → `np.diff(md) <= 0` 拒(严格递增)。
- HorizonSurface:`horizon:` 前缀;z_grid ndim==2;`_require_finite_structured`(**NaN 放行、±inf 拒**);confidence 形状必须等 grid;attributes 每元素形状等 grid。
- FaultSurface:`fault:` 前缀;verts (N,3) + `_require_finite`;faces (M,3),非空时 `f.min()<0 or f.max()>=max(len(v),1)` 拒;representation ∈ {triangulated_3d, curtain_2p5d};curtain 必须有 z_extent(truthy 判断?**`is None`**)。
- StratigraphicVolume:`volume:` 前缀;同 FaultSurface verts/faces 校验;facies 长度==verts;properties 每项长度==verts;boundary/cell_mesh/quality 无校验。
- TunnelSection:`tunnel:` 前缀;path (N,3) + `_require_finite`;`radius > 0.0`。
- MeasurementRecord:`measure:` 前缀;measurement_kind ∈ 6 元集合;points (N,3) + `_require_finite`。

### meta() / from_meta() — 6 类
- 公共键顺序:object_id→name→crs→(kind 专有)→provenance→version→stats(+horizon 有 stats_extra)。
- WellTrajectory meta:z_unit `self.z_unit or self.unit`(**falsy 回退**);formation_tops `list(t)`;from_meta:z_unit 原样 `meta.get`(None 保留)。
- HorizonSurface meta:origin/spacing/shape `list()`;`stats_extra`={node_count, nan_fraction=`1.0-finite.mean()` if size else 0.0};from_meta **不恢复 z_grid**(Catalog artifact 加载)。
- FaultSurface meta:z_extent/strike_dip `list() if truthy else None`(`self.z_extent` 非 None 判断写成 truthy——`()` 会输出 None;from_meta `if zd` 同 truthy);throw_m 原样(可为 None)。
- StratigraphicVolume meta:has_cell_mesh `is not None`;quality `dict()`。
- TunnelSection meta:radius。
- MeasurementRecord meta:points `[[float(c) for c in row] for row]`(**唯一序列化数组的对象**);result 原样;extra `dict()`。
- from_meta 共性:`str(meta["object_id"])`/`str(meta["name"])` 必填(KeyError 直达);其余 `.get` 默认值 + `str()`/`float()`/`int()` 强转。

### `geometry_stats(obj)` — isinstance 分派
- WellTrajectory:stations[:,1:4];FaultSurface/StratigraphicVolume:verts;TunnelSection:path;MeasurementRecord:points。
- HorizonSurface:finite 节点合成 2 顶点包围盒(origin + (shape-1)*spacing 角点,z=finite.min/max);全 NaN 或空 → `{"vertex_count":0}`。
- 其余:verts 空 → `{"vertex_count":0}`;否则 `{"vertex_count":N, "bounds":[min3+max3]}`。

### `ModelAssembly`
- `_KIND_TO_CLS` 6 类映射(object_id `split(":",1)[0]` 分派)。
- `add`:kind 未注册或 isinstance 不符 → `DomainError("unknown object kind for {object_id!r}")`;重复 id → `"duplicate object_id {object_id!r} — use replace()"`(em-dash)。返回 obj。
- `replace`:未知 id → `"unknown object_id {object_id!r}"`。**不校验 kind/isinstance**。
- `remove`:False/True;连带 `display.pop`。
- `clear(kind)`:按 kind 前缀过滤删除,返回数量。
- `bump_version`:`replace(obj, version=+1)`;未知 id **KeyError**(未捕获)。
- `to_meta`:name/frame/display(`dict(v)` 拷贝)/objects 按 `_order` 顺序逐 meta()。
- `apply_meta`:name/frame/display 回写;逐 entry:`object_id` 缺失→`""`→kind=`""`→跳过;kind 未注册→continue;`cls.from_meta` 抛 (DomainError, KeyError, TypeError, ValueError)→**静默 continue**;成功则 add + 记入 restored。**重复 object_id 的 add DomainError 也在捕获集内**(静默丢)。
- `objects(kind)`/`ids(kind)`:kind=None 全量;否则按 `split(":",1)[0]` 过滤(不过 `_KIND_TO_CLS`)。
- `frame`/`display` 是普通实例属性。

## qc.py — 逐符号

- `SEVERITY_ORDER`={"info":0,"warning":1,"error":2,"blocker":3}。
- `QCIssue`:code/severity/message/object_id/metric;`to_meta` 5 键。
- `QCReport`:add/extend/of(object_id 过滤)/severities(4 键全初始化为 0,**未知 severity 键也计数**: `counts.get(i.severity,0)+1`)/worst(未知 severity 按 `get(...,0)` 参与,初始 "ok" 视为 -1)/blockers/to_meta(issues+worst+severities)/from_meta(str 强转,metric 原样)。
- `QCBlockerError(report, object_ids)`:消息 `"export refused: blocker-level QC issues in {', '.join(ids)}\n" + "\n".join("  [{oid}] {code}: {msg}")`;`.report` 属性。
- `qc_well_trajectory`:MISSING_CRS(crs∈{"","unknown"}→blocker)→NO_STATIONS(空→blocker,**early return**)→NON_FINITE_STATIONS(error)→NON_MONOTONIC_MD(diff<=0,blocker,metric=diffs.min() 或 None)→ZERO_LENGTH_SEGMENTS(seg<=1e-12 计数,warning)→SPARSE_TRAJECTORY(measured 且 <3,warning)→SIMPLIFIED_VERTICAL(info)→MIXED_UNITS(z_unit 且 !=unit,warning)。
- `qc_horizon_surface`:空 grid→NO_GEOMETRY(blocker,return)→nan_fraction>0.5→LARGELY_MISSING(warning,"{:.0%}");>0→NAN_HOLES(info,"{:.1%}")→inf→NON_FINITE_GRID(error)→CRS+grid_crs 都缺→MISSING_CRS(blocker)→`triangulate_heightfield`(**内部 import builders**)→faces 空→NO_GEOMETRY(return)→degenerate>0→DEGENERATE_TRIANGLES(>0.01 error 否则 warning,"{:.2%}")→nonmanifold>0→NON_MANIFOLD_EDGES(**error**)→MESH_INFO(info,"{v} nodes, {f} triangles, {b} boundary edges, {c} component(s)")→无 source_version_ids+无 horizon_asset_id+非 demo→NO_PROVENANCE(warning)。
- `qc_fault_surface`:MISSING_CRS(blocker)→空 v 或 f→NO_GEOMETRY(blocker,return)→curtain_2p5d→CURTAIN_REPRESENTATION(info)→DEGENERATE_TRIANGLES(同阈值)→NON_MANIFOLD_EDGES(**warning**,与 horizon 不同)。
- `qc_stratigraphic_volume`:MISSING_CRS→MISSING_BOUNDING_SURFACES(top_id 或 base_id falsy,error)→空→NO_GEOMETRY(blocker,return)→nonmanifold>0→NON_MANIFOLD_EDGES(error)→`closed = nonmanifold==0 and boundary==0`→不闭→SHEET_NOT_CLOSED(blocker,metric=boundary+nonmanifold)→闭→WATERTIGHT(info)→DEGENERATE_TRIANGLES→components>1→DISCONNECTED_COMPONENTS(warning)→`q.get("dropped_crossed",0) or 0` int()>0→CROSSED_COLUMNS(<column_count warning 否则 error,**column_count 默认 1**)→`min_thickness <=0`→ZERO_MIN_THICKNESS(warning)→无 source_version_ids+非 demo→NO_PROVENANCE(warning)。
- `qc_tunnel_section`:path<2→NO_GEOMETRY(blocker);MISSING_CRS(blocker);**无 early return,两者可并存**。
- `qc_measurement`:MISSING_CRS(blocker);result is None 且 kind!="point"→NO_RESULT(warning)。
- `qc_object`:`split(":",1)[0]` 分派;未知 kind→UNKNOWN_KIND(error);fn 抛 (IndexError,ValueError,TypeError)→QC_AUDIT_FAILED(blocker,消息含 `{exc}`)。
- `qc_assembly(assembly, known_source_ids)`:逐 qc_object 合并;known 非 None 时,`ids and not (set(ids) & known)`→STALE_SOURCE(warning,`sorted(ids)`)。
- `assert_exportable(objects, report=None)`:report 缺省则逐 qc_object 合并;有 blocker→`QCBlockerError(report, sorted(blocked_ids))`;否则返回 report。

## exporters.py — 逐符号

- `ExportError(RuntimeError)`。
- `_mesh_of(obj)`:FaultSurface/StratigraphicVolume → (verts, faces reshape(-1,3));其他 → `ExportError("{oid}: object kind has no triangle mesh to export")`。
- `_write_sidecar`:dict 键序 format→object_id→name→crs→vertical_domain→unit→provenance→indexing(固定文案)→**extra→qc(report.to_meta(),仅 report 非 None)**;文件名 `{stem}.provenance.json`(`path.stem` 规则);`json.dumps(indent=2, ensure_ascii=False)` + utf-8。**目录隐式创建由调用方 mkdir**。
- `export_volume_flac3d(volume, path, top, base, n_layers=4, zone_name="GEOMODEL")`:
  - `assert_exportable([volume])` 先行(QCBlockerError 直通)。
  - `boundary is None`→ExportError("volume has no boundary polygon")。
  - `_sheet_horizons`:top+base 都给则直用;否则 regrid("top")/regrid("base")——verts 前一半/后一半;`np.unique(round(xy,9))` 若 len(xs)*len(ys)==len(pts)→规则格点 searchsorted 放置,origin=(xs[0],ys[0]),spacing=(ys差,xs差);否则中位差推格距 round 放格。产物 HorizonSurface(`horizon:_export_{oid}_{sheet}`)。
  - `build_columnar_hex_mesh(top_like, base_like, boundary, n_layers)`(conv-12 已移植)→(nodes, hexes, info);hexes 空→ExportError("no valid columns to export")。
  - 文件:`* FLAC3D grid exported by PaleoWorkbench\n` + `* object: {oid} ({name}) cells={len(hexes)} nodes={len(nodes)}\n` + `* CRS: {crs}  unit: {unit}\n` + `G {id} {x:.4f} {y:.4f} {z:.4f}\n`×N + `Z B8 {zone_id} {ids 空格连接}\n`×M(1-based)。
  - sidecar extra={zone_name, mesh:info},report=qc_object(volume)。
  - `out.parent.mkdir(parents=True, exist_ok=True)`。
- `export_volume_abaqus`:同构;`*HEADING\n** PaleoWorkbench export: {oid} ({name})\n** CRS: {crs}  unit: {unit}\n*PART, NAME={part_name}\n*NODE\n{id}, {x:.4f}, {y:.4f}, {z:.4f}\n*ELEMENT, TYPE=C3D8, ELSET=EALL\n{zid}, {ids ", "连接}\n*END PART\n`;extra={part_name, mesh:info}。
- `export_mesh_obj(obj, path, label)`:`_mesh_of`→assert→faces 空→ExportError;`# PaleoWorkbench OBJ export: {oid} ({name})\n# CRS: {crs}  unit: {unit}\no {label or name}\nv {x:.6f}…\nf {a+1} {b+1} {c+1}\n`;extra={triangles}。
- `export_mesh_stl`:binary;normals=cross(t1-t0,t2-t0)/len(len=0→1.0 除);header `"PaleoWorkbench STL export: {oid}".encode("ascii","replace")[:80].ljust(80,b"\0")`;`<I count` + 每面 `<3f normal` + 3×`<3f vert` + `<H 0`。
- `export_mesh_vtp(obj, path, point_data)`:ET 手写 XML;`Float64 Points` ascii `{c:.6f}` 连接;connectivity/offsets Int64;PointData 每个 `{v:.6g}`;**point_data 长度不符→ExportError**;`ET.indent(space="  ")`;`ElementTree.write(encoding="utf-8", xml_declaration=True)`;extra={point_data:keys}。
- `read_flac3d_grid`:逐行 split;`G`+≥5 列→nodes;`Z`+≥11 列+B8→zones;无 G 或无 Z→ExportError("no G/Z B8 records parsed");zone id 越界→"zone references missing gridpoint";返回 node_count/zone_count/nodes(按 id 排序)/zones。
- `read_abaqus_inp`:`*NODE`/`*ELEMENT` 段状态机;`*ELEMENT` 不含 C3D8→ExportError("unexpected element type line {line!r}");node 行 4 列/element 行 9 列;空或**行→skip;无→"no C3D8 nodes/elements parsed";id 越界→"element references missing node"。
- `read_obj`:`v`≥4 列→verts;`f`≥4 列→`p.split("/")[0]`-1;无 verts→"no vertices parsed";face 越界→"face index out of range"。
- `read_stl`:bytes;<84→"truncated STL";`expected=84+count*50` 不等→"STL size mismatch";`<12f` 逐面(丢 normal,取 vals[3:6]/[6:9]/[9:12]);attr byte 跳过。
- `read_vtp`:ET.parse;ParseError→"malformed VTK XML ({exc})";tag!=VTKFile 或 type!=PolyData→"not a VTK PolyData XML file";无 Piece→"no Piece element";conn 空→"empty connectivity";pts 空→"empty points";计数不符→"declared counts do not match payload";conn 越界→"connectivity index out of range";PointData 逐 DA→attrs。
- `validate_export(path, obj)`:suffix 分派 .f3grid/.inp/.obj/.stl/.vtp;mesh 类格式比对 face/poly/triangle 数 + bounds `np.allclose(atol=1e-4)`(OBJ min/max 分开消息;STL min/max;VTP 仅 min 合为一条 "VTP bounds mismatch");未知后缀→"unknown export extension {suffix!r}";**.f3grid/.inp 只解析不回比**。
- `_generate_structured_grid(spec)`:meshgrid ij;`z=k*dz + 5.0*(i/max(nx,1))*(j/max(ny,1))`;C3D8 节点序 bottom CCW + top。
- `export_to_flac3d`/`export_to_abaqus`(legacy):同 V2 文本但头部多 `* LEGACY ...`/`** LEGACY ...` 行 + dims 行;**返回 True**;异常重抛(logger.error 后 raise)。

## advisor.py — 逐符号

- `check_boreholes(list)`:dict/record 混收;逐孔:xy 非 finite→error;total_depth<=0→error;逐层 top>bottom→error;`top < last_bottom - 1e-5`→warning(last_bottom=max 滚动);last_bottom>td+1e-5→warning。返回 {checked_boreholes, issues[{type,borehole,message}], status PASS|FAIL}。
- `check_coplanar_faults`:O(n²) 对;n 归一(**零向量除零→NaN,不崩**);`|abs(dot)-1|<0.05`→平行;d 按法向长度调整(`d2_adj` dot<0 取负);`dist_diff<15.0`→warning(消息含 `arccos(min(abs(dot),1.0))` 角度 + dist_diff `:.2f`)。status PASS|WARNING。
- `_ensure_*`:dict→record(l.get("top",0.0) 等默认);其他类型→TypeError。

## lithology.py — 逐符号

- 4 表(中文键):LITHO_GR/SONIC/DENSITY/AI + 4 DEFAULT。
- `sample_log_values(layers, depths, table, default)`:zeros(len)→逐层 mask `[top,bottom)` 覆盖赋值 `table.get(lithology, default)`(**后者覆盖前者**);返回 float32。

## builders.py 构造器剩余 — 逐符号

- `build_well_trajectory(name, stations, ...)`:ndim/形状/MD 递增校验(消息 `{name}:` 前缀,**非 object_id**);oid=`well:{_unique_slug(name)}`。
- `build_simplified_vertical_well(name, head_xyz, total_depth, ...)`:head shape==(3,) 且 finite;td>0;vertical_domain ∈{depth,tvdss}→z+td,否则 twt→z=td;2 站 [0,hx,hy,hz]+[td,txx]。oid 同上。
- `build_fault_from_mesh(name, verts, faces, ...)`:形状校验;oid=`fault:{slug}`。
- `_unique_slug`=`_slugify(name, "obj")`。**构造器不查重**(assembly 职责)。

## 既有 C++ 资产(本切片复用)

- `pwb_geomodel`:HorizonGrid/TriMesh/VolumeShell/HexMesh、triangulate_heightfield、build_columnar_hex_mesh、dedupe_stations、tri_degenerate_fraction、edge_manifold_stats、connected_components(scipy 语义:孤立顶点计入)。
- `Pwb::Domain`:Json(nlohmann ordered_json)、json_semantic_diff/semantic_equal。
- `pwb_ingest`:`py_parse_float`/`py_strip` 等 py_compat 原语(CONV-19)。
- 仓内惯例:`%.4f`/`%.6f`/`%.6g` 文本格式化、dump/parse 归一化比较、`$FX` 路径占位、`indent=1 ensure_ascii=False` 冻结。

## 测试缺口(现 pytest vs 本切片 oracle)

- meta()/from_meta 全键序与类型(int/float/str/bool/None)逐字节冻结——现测试只查少数字段。
- DomainError 消息逐字(`!r` repr、em-dash、shape 元组形态)。
- QC issue 序列全量(code/severity/message/metric 顺序)——现测试抽查 code。
- 写器输出**逐字节**(空格、%.4f、1-based、XML indent)。
- read_* 失败消息逐字。
- _sheet_horizons regrid 双路径(规则格点/非格点)。
- legacy 写器 True 返回 + 头部行。
- assembly apply_meta 的静默吞错(restored 列表)。
