# 04 Findings — 环裁剪与自交修复（ring clip & repair，shapely-free 子集）

逐符号事实表（输入 / 输出 / NaN·空·并列 / 与已有 C++ 核的关系 / 测试缺口）。
范围 = 本任务 prompt §5 全部列出的源文件；每符号按「①输入 ②输出 ③边界语义
④C++ 关系 ⑤测试缺口」五行记。行数按符号复杂度 5–20 行。

---

## 1. `paleo_workbench/mapping/geometry_operations.py`（902 行，通读完毕）

统一 GIS 几何门面。引擎链：QGIS 桥 → shapely 回退 → host；每个结果以
`.engine` 如实披露。本任务只关心 **ring-clip 段** 与 **repair 段**。

### ENGINE_QGIS / ENGINE_SHAPELY / ENGINE_HOST（常量）
- ① 无输入。② 字符串 `"qgis"` / `"shapely-fallback"` / `"host"`。
- ③ 无边界。
- ④ C++ 无对应常量需求；oracle 的 `engine` 字段仅为 Python 侧记录。
- ⑤ `test_geometry_operations.py::test_engine_disclosure_on_every_op` 钉值。

### engine_status() -> {"bridge_available": bool, "ops": {name: engine}}
- ① 无输入（探测 `_BRIDGE_PROBE` 全局缓存）。
- ② 22 个 op 的引擎映射：bridge 15 op、shapely-only 3（polygonize/line_merge/dissolve）、host 7。
- ③ 桥缺席时 bridge op 一律报 shapely（`test_unavailable_without_bridge_is_not_silent`）。
- ④ 纯 Python 运行时探测，C++ 核不移植。
- ⑤ 已被钉；无缺口。

### intersection / difference / symdifference / union / dissolve / buffer / clip(bbox) / simplify / smooth / densify / offset_curve / multipart_to_singlepart / singlepart_to_multipart / split_by_line / polygonize / line_merge（桥→shapely 族）
- ① GeoJSON dict（或 dict 序列）+ 操作参数。
- ② GeometryResult{geometry, engine}；list 族返回 GeometryListResult。
- ③ 空结果：`_shapely_binary` 对 empty raise ValueError（如 "intersection produced an empty geometry"）；clip 的 extent 校验报 "4 numbers"/"xmax > xmin"/"finite"（test_clip_extent_validation_loud 钉文案）。
- ④ 全部依赖 GEOS/shapely 数值引擎 → **必须 shapely**，不在本切片。clip(bbox) 是矩形裁剪，与域环裁剪是不同科学操作（docstring 明示）。
- ⑤ 已有 parity 测试；不需要本任务补。

### point_in_polygon(point, polygon)
- ① (x,y) + Polygon/MultiPolygon dict。② ContainsResult{contains, engine=host}。
- ③ 空环 False；非 polygon 类型 raise ValueError（`_polygons_of`）。
- ④ 委托 geometry_planar.point_in_polygon_scalar → 已有 even-odd 核语义（polygonization.cpp `point_in_ring` 同谓词，XOR 奇偶）。
- ⑤ test_geometry_authority_v8 PIP 组已钉；无缺口。

### area_with_unit / length_with_unit / bounding_geometry / nearest_feature / bbox_intersects / centroid / topology_check / crs_transform_xy（host 族）
- ① 几何 dict（+crs / 容差 / 要素列表）。
- ② MeasurementResult / bbox 四元组 / feature dict / bool / (cx,cy) / TopologyReport / (x,y)。
- ③ centroid 对退化面 fail-closed raise；area 把洞按符号减、MultiPolygon 全部件求和（R1-F2/R3-3 回归钉）。
- ④ host 纯 Python 已实现，与 mapping_kernel 无关（面积/长度单位链在 geometry_units.py）。
- ⑤ authority_v8 / units_qa 已钉；无缺口。

### trim_line / extend_line_to_boundary / reverse_geometry（模块公开、不在 __all__）
- ① line dict + boundary dict / max_extend；reverse 接受线/面。
- ② 裁剪= line ∩ boundary（空/非线 → ValueError "trim produced no line segments"）；extend 沿端边方向射线取最近交点（无命中 ValueError）；reverse 递归倒序 + 保持环闭合。
- ③ extend 用 shapely ray∩boundary；reverse 纯 dict 操作（可移植但不在本任务范围——无 ring-clip/repair 语义）。
- ④ trim/extend 必须 shapely；reverse 若未来移植属 UI 编辑切片。
- ⑤ 无专项测试文件（经 test_qgis_* 间接覆盖）；本任务不补。

### _ring_polygon(clip_ring)（私有，clip 的公共前置）
- ① `Sequence[Sequence[float]]`。② shapely Polygon；**invalid 时 make_valid 后再用**。
- ③ 环点 float() 强转；无效环（自交/2 点）→ make_valid 或构造期 ValueError。
- ④ C++ 有界契约：环必须 simple，否则该案例归 shapely_optional（本核不复制 make_valid）。
- ⑤ Python 侧无直接测试；经 clip 公开函数覆盖。

### clip_polyline_to_ring(poly, clip_ring) -> list[list[list[float]]]
- ① 一条折线顶点序列 + 用户域环。② 环内折线片段列表（每段 ≥2 点）；空交集 → `[]`。
- ③ `LineString(poly)` 少于 2 点 → shapely 构造抛 GEOSException（"IllegalArgumentException: point array must contain 0 or >1 elements"，非 ValueError）**向上传播**（无 try/except，调用方炸）；自交折线会被 GEOS 在自交点 noding 成更多片段；GeometryCollection 只挑 LineString/MultiLineString；`len(c) >= 2` 过滤退化片段。要求 shapely——「请求的裁剪绝不静默退化为未裁剪输出」（docstring 原话）。
- ④ **可纯 C++ 子集**：段-环求交（参数化）+ even-odd 内点分类 + 顺序拼接。GEOS 输出顺序是内部实现细节 → oracle 冻结时以「规范化片段多重集」比较（与 test_geotopo_parity 面积多重集同哲学）。
- ⑤ 调用方 `contouring._clip_polyline_to_ring` 无专门 pytest（经 generate_contour_layer clip_ring 参数路径）；本任务以冻结 oracle 补齐。

### clip_polygon_to_ring(geom, clip_ring) -> dict | None
- ① GeoJSON Polygon（shape() 亦接受 MultiPolygon）+ 用户域环。
- ② 交集 Polygon/MultiPolygon dict；空 → None；GeometryCollection 只保留 Polygon/MultiPolygon 并合入一个 MultiPolygon（先纯 Polygon 后展开 MultiPolygon）。
- ③ 结果经 `json.loads(json.dumps(mapping(...)))` 规范化为纯 list；环无效 → `_ring_polygon` 先 make_valid；要求 shapely（同上，绝不静默未裁剪）。
- ④ **可纯 C++ 子集（本切片核心交付）**：subject(含洞) ∩ simple ring 的边界弧拆分/分类/缝合 overlay；自交输入检出后拒入有界契约。
- ⑤ polygonization 调用点（clip_ring 参数）无专门 pytest；冻结 oracle 补齐。

### repair(geometry)（= make_valid 别名）
- ① GeoJSON dict。② GeometryResult。
- ③ 桥优先 `native.make_valid`；回退 `topology.repair_invalid_geometry`，引擎如实标 shapely。桥异常静默落 shapely（有披露不算静默）。
- ④ 入口胶水；可移植核心在 repair_invalid_geometry（见 §3）。
- ⑤ test_repairs_bowtie（面积 50）、test_repair_determinism 钉语义。

---

## 2. `paleo_workbench/mapping/geometry_planar.py`（221 行，通读完毕）

平面几何共享核（v7 §4 去重三重复制的唯一实现）。even-odd 语义族。

### distance_to_segment(point, start, end)
- ① 三点。② 投影距离 float。③ norm≤1e-18 → 点到端点距离。
- ④ 与 map_interaction 复刻版逐字同式；不在本切片。
- ⑤ authority_v8 钉退化端点。无缺口。

### point_in_ring_scalar(x, y, ring)
- ① 单环（无洞）。② bool（射线穿越奇偶）。
- ③ `_ray_crosses`：`(y1>y)!=(y2>y)` + `x < x1+t*(x2-x1)`；水平边不穿越。
- ④ polygonization.cpp `point_in_ring` 已逐式复刻（含 y1==y2 continue 的等价形态——C++ 把 y1==y2 先短路，Python 由浮点比较自然排除；谓词等价）。
- ⑤ vectorized-scalar 全网格一致性测试钉。无缺口。

### point_in_ring_scalar_inclusive(x, y, ring, *, epsilon=1e-9)
- ① 单环 + 显式 on-edge 容差。② bool；边上/顶点上 True。
- ③ 叉积面积阈值 `|cross| <= epsilon*max(1,seg_len)` + bbox 判据；len<3 False。
- ④ 与 workarea `_point_in_ring` 同语义（历史 project/domain.py 逐字）；不在本切片。
- ⑤ authority_v8 钉边界点。无缺口。

### point_in_polygon_scalar(point, polygon)
- ① GeoJSON Polygon/MultiPolygon。② bool：某 part 外环内 且 不在其洞内（R1-F1：按 part 独立判，不摊平）。
- ③ 空 coordinates False；非 polygon raise ValueError。
- ④ C++ clip 核的洞判定直接复用该语义（B 环内 = 外环内 ∧ 非洞内）。
- ⑤ 钉（hole/multipart/fail-closed）。无缺口。

### points_in_polygon_vectorized(xs, ys, polygon)
- ① 广播兼容数组。② bool 数组。③ 洞按 `part &= ~ring_crossings` 精确减。
- ④ numpy 专用；C++ 无需求。⑤ 与 scalar 逐点一致已钉。

### extent_of_coordinates / extent_of_geometries
- ① 坐标/几何集合。② (xmin,ymin,xmax,ymax) 或 None / ValueError（无坐标）。
- ③ inf 初值 + found 标志。④ 已有用途广；不在本切片。⑤ 钉（空 fail-closed）。

---

## 3. `paleo_workbench/mapping/topology.py::repair_invalid_geometry`（通读，362 行中本函数 50 行 + TopologyService 全文）

### repair_invalid_geometry(geometry) -> dict
- ① GeoJSON dict（仅 Polygon/MultiPolygon 处理，其余原样返回；非 dict 原样返回）。
- ② 修复后的 dict（或原 dict）。
- ③ **三段语义（本任务移植的精确依据）**：
  1. **闭环（纯 dict，shapely-free）**：仅 `type=="Polygon"` 且 `coords` 是 list：对每个 `isinstance(ring,(list,tuple))` 且 `len(ring)>=3` 的环，`r=[list(pt) for pt in ring]`，`r[0]!=r[-1]` 时 append `list(r[0])`；不满足条件的环**原样透传**。MultiPolygon 不闭环。
  2. **shapely 段**：`shape(closed)`；`is_valid` → repaired=cand（**不走 make_valid**）；invalid → make_valid（失败退 buffer(0)）。Polygon→orient(sign=1.0)；MultiPolygon→逐 part orient；GeometryCollection→挑 Polygon，1 个降为 Polygon，>1 合成 MultiPolygon；空 repaired 不进入输出分支。**任何异常 → except: pass → 返回闭环后的 geometry**。
  3. **orient(sign=1.0)（可移植）**：shapely 2.1.2 `orient_polygons(exterior_cw=False)`——外环 CCW（signed area>0）、洞 CW（<0）。实证：2 顶点环 `LinearRing` 构造期 ValueError("A linearring requires at least 4 coordinates") → 落 except 分支返回闭环几何（纯 dict，可移植！）；3 点退化三角 is_valid=False → make_valid → 非平凡 GEOS 输出（shapely_optional）。
- ④ C++ 有界子集：
  - `close_rings`：§3.1 逐字移植（含 <3 环透传、MultiPolygon 不动）；
  - `orient`：valid 路径 signed-area 定向（外环 CCW/洞 CW）；
  - **有界自交拆分**：单一 proper crossing（一对非邻接边恰一次相交）的 bowtie → 在交点处切两瓣 → 各自 orient → MultiPolygon——已实证 GEOS make_valid 对经典 bowtie 输出恰为这两个三角形（(0,10),(5,5),(0,0) 与 (10,0),(5,5),(10,10)，各 25）；
  - 其余 invalid 形态（多 crossing / 顶点触边 / 共线重叠 / 洞越界 / 退化）→ `unsupported` 状态（shapely_optional）。
- ⑤ Python 侧缺口：闭环 pass-through（<3 环）、MultiPolygon orient、错误回退分支无专项 pytest——冻结 oracle 全补。

### TopologyService（validate / validate_records / record_validation / refresh_error_count / cached_error_count / forget_error_count / forget_all_error_counts / _bridge_validate_fn / _bridge_validate_many_fn / _shapely_messages / _shapely_available）
- ① VectorLayer 流 + (feature_id, geometry) 记录集。② issues 列表（severity/layer_id/feature_id/message）。
- ③ **环闭合规则在 host 层**：Polygon 每环 `len(points)<4 or points[0]!=points[-1]` → "polygon ring N is not closed"（这解释了为什么 repair 只需闭环、OGC validity 由 shapely 管）；桥批量 validate_many 探测失败整批回退 shapely（P2-2/P2-6 纪律）；无桥无 shapely → "validator_unavailable" + 中文消息。
- ④ 会话缓存/豁免是编辑会话层；不进数值核。
- ⑤ map_topology* 测试钉 UI 面；本任务不补。

---

## 4. `paleo_workbench/mapping/geological_pipeline/contouring.py::_clip_polyline_to_ring`（444 行通读）

### _clip_polyline_to_ring(poly, clip_ring)
- ① 等值线折线 + 域环。② 透传 `geometry_operations.clip_polyline_to_ring`（共享核，v7 §4）。
- ③ 无本地边界处理——全部语义在 facade（见 §1 同名条目）。
- ④ C++ contouring.cpp 已移植 stitch/RDP/Chaikin（注释显式写明 clip NOT ported）；本切片补齐 clip 段后，C++ `generate_contour_layer` 等价物即可接线。
- ⑤ 缺口同 §1 clip_polyline_to_ring。

### 其余 contouring 公开符号（calculate_nice_contour_levels / calculate_quantile_contour_levels / calculate_polyline_length / douglas_peucker_2d / chaikin_smooth / _stitch_segments / _marching_squares_pure_python / generate_contour_layer）
- ①② 已在 M6 首片移植（mapping_kernel contouring，168 冻结案例）。
- ③ saddle 以 v_center>=level 分叉；pt_key round-6；isclose abs_tol=1e-5 闭合判定。
- ④ 只读核——本任务禁止改（红线）。
- ⑤ 既有 oracle 全绿；无缺口。

---

## 5. `paleo_workbench/mapping/geological_pipeline/polygonization.py::_clip_polygon_to_ring`（616 行通读）

### _clip_polygon_to_ring(geom, clip_ring)
- ① 相带 Polygon（栅格描边产物，可能带洞）+ 域环。② 透传 facade `clip_polygon_to_ring`；None → `polygon_qc["empty_after_clip"]` 计数，非 None → `clipped_to_domain` 计数。
- ③ 裁剪在 `min_area` 过滤**之前**（generate_facies_polygon_layer L501-510）；裁剪后再算面积/面积百分比 → 裁剪语义直接决定属性数值。
- ④ 同 §1 clip_polygon_to_ring 的 C++ 子集；这是用户流程验收「相带域裁剪」的真实调用点。
- ⑤ 缺口同上。

### 其余 polygonization 公开符号（calculate_shoelace_area / calculate_signed_area / ring_area_centroid / simplify_collinear_ring / _point_in_ring / _ring_bbox / _hole_vertex_votes / _compute_geometry_area / _polygonize_raster_boundaries / _assign_holes_to_exteriors / _filter_small_polygons / generate_facies_polygon_layer / polygonize_factor_grid / _mapping_to_lists）
- ①② M6 第三片已移植（shoelace/signed/centroid/collinear/描边/洞投票/分类/过滤）。
- ③ 洞投票：顶点多数决、`votes > best_votes` 严格大于（面积升序 + 并列取最小环）、未匹配洞反转提升为外环并计数；`repair_invalid_geometry` 在描边每组后调用（**M6 oracle 把它 monkeypatch 成 identity——本切片解除该限制的 shim**：先冻结 repair 有界子集，描边核不动）。
- ④ 只读——hole vote C++ 实现已通读（`assign_holes_to_exteriors` + bbox 预过滤 + XOR 奇偶），clip 结果的环分类（外环/洞）复用同一「最小包含外环」模式。
- ⑤ 既有 24 案例全绿；无缺口。

---

## 6. `paleo_workbench/mapping/geotopo_service.py`（529 行通读）

控制线构面服务（DCEL 桥优先 / shapely 回退）。GeoTopoError 契约码 PWB-GT-xxx。

### GeoTopoError / GeoTopoPolygon / GeoTopoResult / SharedArc / ReshapePair（数据类型）
- ① frozen dataclass。② 字段见 02-interface-contracts §1。
- ③ error 消息格式 `f"{code}: {message}"`。
- ④ C++ DCEL 核在桥内（geological_topology_core），非本切片范围。
- ⑤ test_geological_topology_core 钉。无缺口。

### _validate_lines / _validate_options
- ① lines 记录集 / tolerance+envelope。② 规范化副本。③ NaN/inf/非 2D/少于 2 点 → PWB-GT-001；tolerance 非正 → PWB-GT-002；envelope 逆序 → PWB-GT-001。
- ④ host 校验层；C++ 桥内核已有等价护栏。⑤ test_invalid_inputs_raise_contract_error_codes 钉。

### polygonize_control_lines(lines, *, tolerance=1e-6, clip_envelope=None, min_ring_area=0.0)
- ① 控制线网络。② GeoTopoResult（每有界面 OGC CCW 外环 + 父线溯源；无界面剔除；clip_envelope 只留完全 within 的面）。
- ③ shapely 路径：set_precision(tolerance) noding → unary_union → polygonize → orient(sign=1.0)；`polygon.area > max(min_ring_area, 0.0)` 过滤。
- ④ DCEL 核（bridge C++）已有；shapely 回退不移植。
- ⑤ parity/fuzz 双引擎矩阵钉（figure-eight 孔洞近似 strict xfail，04-limitations #17）。

### find_shared_arcs / reshape_shared_arc / _open_ring / _chain_points / _interned_sequence / _locate_arc / _ring_signed_area / _chain_length / smooth_curve
- ① 两 Polygon + arc/curve + tolerance。② SharedArc 列表 / ReshapePair（面积和守恒，残差 > tolerance*max(1,链长) 即 PWB-GT-203/204 拒绝）。
- ③ 节点 interned 用 `round(p/tol)` 网格；弧匹配需唯一；smooth_curve 是 Catmull-Rom 过采样（端点保持，每段 t∈[0,1) 无重复末点）。
- ④ 全部 shapely 校验（is_valid/intersection/union 面积）→ 必须 shapely，不移植；纯坐标部分（_interned_sequence/_locate_arc/smooth_curve）如未来需要可在独立切片处理。
- ⑤ parity 钉守恒（容差 1e-9）。

---

## 7. `paleo_workbench/mapping/topology_checker.py`（144 行通读）

### ignore_key(error)
- ① 错误 dict。② (rule, layer_id, feature_id, other_feature_id) 四元组——豁免身份不依赖临时 id。
- ③ str() 强转。④ 纯 Python 会话层。⑤ 无专项（经 save 门禁间接）。不移植。

### TopologyChecker（last_errors / ignore / restore / is_ignored / ignored_keys / add_allowed_gap / blocking_errors / persist / restore_state / run_for_commit / run / fix / fix_all）
- ① 桥 run_geometry_checks 结果 + 豁免/缝隙白名单。② 持久化 snapshot dict / 未豁免错误列表。
- ③ run 的 config 固定 rules=["overlap","gap","is_valid","workspace_remainder","dangle"], precision=8；allowed_gaps 以 FeatureCollection 回传桥并 harvested 覆盖本地。
- ④ 桥胶水；数值在桥内核。不移植。⑤ UI 测试覆盖。

---

## 8. 测试文件通读结论（把断言翻译成 C++ oracle 案例表）

| 测试文件 | 与本切片相关的断言 → oracle 案例 |
|---|---|
| test_geometry_operations.py | `test_repairs_bowtie`：repair 后面积 50（两瓣三角）→ repair 自交拆分案例；`test_validate_semantics` UNCLOSED 仍 OGC-valid → 闭环+orient 案例（输出为闭合 5 点环）；`test_clip_bbox` 面积 36 → 不适用（bbox 裁剪非环裁剪，只作对照）。 |
| test_geometry_parity_review.py | DONUT∩SQ_B=21、SQ_A∩DONUT=84 → 带洞 subject 裁剪案例的期望面积锚点；`test_clip_extent_validation_loud` → bbox 校验文案（不移植）；`test_repair_determinism` → C++ 核必须确定性（同输入同输出）。 |
| test_geometry_authority_v8.py | PIP 含洞/multipart/边界语义 → clip 内部分类谓词直接复用；corner-hole 质心回归 → 面积矩守恒（不移植，已绿）。 |
| test_map_topology.py / test_map_topology_rebuild.py | UI 场景层（geoviz snap/scene）；`test_self_intersection_detected`（validate_ring bowtie 检出）→ 佐证「自交检出」是既有用户可见语义；merge/split 需 shapely（skipif 钉）→ 与本切片 shapely_optional 哲学一致。 |
| test_geotopo_fuzz.py / test_geotopo_parity.py | 六类病态语料 + 双引擎 parity 面积多重集 → **冻结比较采用多重集/规范化集合的先例**；figure-eight 孔洞近似 xfail → GEOS 输出顺序/结构不可依赖的实证。 |
| test_geometry_schema.py / test_geometry_units_qa.py | normalize/单位链；与本切片无关（读过确认无约束冲突）。 |
| test_geological_topology_core.py | `_ccw_ring` 断言外环 CCW → C++ clip 输出同样取外环 CCW/洞 CW 约定；`test_self_intersecting_figure_eight_yields_two_faces`（面积 4+4）→ 自交拆分面积锚点。 |

---

## 9. ADR / 开发文档约束（全文读过并抄录于 decisions）

- **ADR 0044**（交会填充内核几何）：「内核一次性求交、后端只消费产物」——本切片的 clip 核遵循同一分层：数值核算清，宿主层不做二次几何。
- **ADR 0059**（QGIS authoring core）：geometry ops 专业计算走桥 GEOS，shapely 是**有文档的回退**；`VectorEditSession` 是事务权威、桥不越权改数据 → C++ mapping_kernel 核不承担事务语义，只出纯函数结果。
- **ADR 0057**：seam/许可/数据权威仍有效（读标题级约束，0059 已超集）。
- **geotopo-editor 00-decisions**：D1 容差阶梯（1e-6，round(coord/tol) 网格合并）、D2 自研核不用 GEOS polygonizer 的先例、D3 核心层零 QGIS（POD 纯净）→ 本切片 ring_ops 同样 Qt-free/GEOS-free。
- **01-architecture-rfc**：leftmost-turn 面追踪、ε 膨胀参数化求交、端点钳位 <ε 视为端点 → 本切片 overlay 的求交稳定性参数沿用同思路（有界契约内退化为精确判定）。
- **02-interface-contracts**：错误信封/码段先例 → C++ `unsupported` 状态携带结构化 reason。
- **03-tdd-test-plan / 04-verification / findings / progress / task_plan**：面积多重集 parity、模糊语料不变式（不崩溃不卡死）、xfail 显式钉子哲学 → shapely_optional 显式 skip 记录的直接依据。

---

## 10. C++ 现状（只读确认）

- `libs/mapping_kernel/src/contouring.cpp`：stitch 用 OrderedKeys（Python dict 插入序复刻）+ available[0] 首个未用邻居；`round_to` half-even；isclose rel 1e-9。
- `libs/mapping_kernel/src/polygonization.cpp`：hole vote（bbox 预过滤 + XOR 奇偶 + 严格 >）、描边 walk、`simplify_collinear_ring`；**头注释明确 "Shapely repair_invalid_geometry (make_valid / orient) and clip-to-ring are NOT ported"** —— 本切片的交付正是消除这一缺口，且不动任何已绿核文件。
- `libs/mapping_kernel/CMakeLists.txt`：单 STATIC 库 + BUILD_TESTING 子目录；测试按 `PWB_*_FIXTURE` 宏读 JSON。CMake 追加按 `BEGIN CONV-04` 块（见 decisions D6）。
- `tools/oracle/generate_polygonization_fixtures.py`：`poly.repair_invalid_geometry = _identity_repair` monkeypatch 先例 → 本切片生成器**不** monkeypatch，直接调真实 `repair_invalid_geometry`（shapely 2.1.2 在环境内），portable/shapely_optional 按输入形态分类。

---

## 11. 分类表：geometry_operations / repair 的「可纯 C++ vs 必须 shapely」（§7.1 交付）

| 符号 | 判定 | 理由 |
|---|---|---|
| repair_invalid_geometry 闭环段 | **可纯 C++** | 纯 dict 手术（§3.1） |
| repair_invalid_geometry orient 段（valid 路径） | **可纯 C++** | signed-area 定向；shapely 2.1.2 orient=exterior CCW/holes CW 实证 |
| repair bowtie（单一 proper crossing） | **可纯 C++（有界）** | 交点切两瓣；GEOS make_valid 输出实证吻合（§3.④） |
| repair 其余 invalid（多交点/触边/共线重叠/洞越界/退化/空） | 必须 shapely | make_valid 的 GEOS 语义不可复制；检出即 unsupported |
| clip_polygon_to_ring（simple subject × simple ring，无退化） | **可纯 C++（有界）** | 弧拆分+分类+缝合 overlay（decisions D2） |
| clip_polygon_to_ring（自交环/顶点触边/共线重叠/无效环） | 必须 shapely | `_ring_polygon` make_valid + GEOS robust overlay |
| clip_polyline_to_ring（simple 线 × simple 环，无退化） | **可纯 C++（有界）** | 参数化求交 + even-odd 分类 + 顺序拼接 |
| clip_polyline_to_ring（<2 点 / 切线穿越 / 过环顶点） | 必须 shapely | ValueError 传播 / GEOS 节点化 |
| 桥 15 op / polygonize / line_merge / dissolve | 必须 shapely(或桥) | GEOS 引擎族 |
| host 7 op（PIP/面积/长度/bbox/nearest/topology_check/crs） | 已有实现（host） | 不属本切片 |

## 12. 逐文件测试缺口 → oracle 案例数（已生成：51 案例 = 35 portable + 16 shapely_optional）

| 源 | 冻结案例（op × 形态） |
|---|---|
| repair_invalid_geometry（19 案例） | valid 不变、CW 外环、CCW 洞、CW 洞、未闭合 CW、未闭合 CCW、空 coordinates（Polygon/Multi）、Multi 混向（不相交 parts）、Multi 未闭合环、<3 坐标环恒等回退（单面 2 环形态 / 3 坐标未闭合 / Multi 短环）、3 坐标零面积环（optional：make_valid→LineString）、bowtie 对角 + 非对称（可移植拆分，含 8/3,4/3 非整交点）、五角星多交点（optional）、洞越界（optional）、尖刺环（optional）、Multi parts 重叠（optional：make_valid 并集）、Multi 未闭合 3 坐标三角形（可移植：shapely 自动闭合后走 orient） |
| clip_polygon_to_ring（17 案例） | 环在 subject 内（恒等）、环含 subject（恒等）、重叠、L 凹环、C 环分带（两件 MultiPolygon）、斜置四边形（非整交点）、带洞 subject 右半（洞被环边界切开成凹槽）、环落在洞内（None）、MultiPolygon subject（单件保留 Polygon）、Multi 两件都保留、不相交（None）、CW 环同结果、顶点触边（optional）、共线重叠（optional）、环 2 点（error：_ring_polygon 构造 ValueError）、自交环（optional） |
| clip_polyline_to_ring（12 案例） | 单段穿越、完全在内、完全在外（[]）、C 环两件、折线两进两出、闭合环线在内恒等、单点（error：GEOS IllegalArgumentException）、折线零长段（optional）、环 2 点（error）、干净对角双交点（更名 line_diagonal_two_crossings）、穿环顶点（optional）、自交折线（optional：GEOS 在自交点 noding 成多片段）、与边共线（optional）、擦角触边（optional） |
