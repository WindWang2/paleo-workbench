# 17 — Findings(§5 每个源文件逐公开符号)

> 依据:全文阅读以下源文件/测试/文档后逐符号记录。测试转译为 oracle 案例表
> (见 `generate_crs_units_fixtures.py` 的案例清单);文档约束抄录在各符号下。
> 阅读清单:geometry_units.py、crs_contract.py、crs_chain.py、
> workflow/crs_policy.py、mapping_workspace/crs_gate.py、
> libs/mapping_kernel crs_policy.hpp/.cpp;tests/test_geometry_units_qa.py、
> test_crs_distance_policy.py、test_mapping_crs_idw.py、
> test_v9_interaction_facts.py、test_v9_review_fixes.py、
> test_topo_m0_foundation.py、test_topology_m0_v11.py、
> test_v10_crs_chain_and_identity.py、test_v10_qgis_runtime_health.py、
> test_project_models.py;docs/development/{scientific-interpretation-v6/08,
> qgis-geological-authoring-v9/03+05, qgis-spatial-layer-foundation-v10/02+11,
> qgis-cartography-runtime-v11/10, topological-editing-m0.md,
> specs/topological-editing-migration-spec.md §6}、CONTEXT.md(SourceXY/
> SourceCRS 段)、cpp-conversion-main-plan.md(M7 crs_policy 条目)。

## 文件 1:paleo_workbench/mapping/geological_pipeline/geometry_units.py(94 行)

模块角色:V6 §15 P0-10「几何 QA 单位诚实化」——shoelace 面积/折线长度在
地理 CRS 下是平方度/度,无物理意义;本模块给每个量打单位标签,地理 CRS
给「均值纬度局部尺度 ≈m²/≈m 近似」+ 显式 warning,未声明 CRS 标
unknown-unit。被 polygonization(generate_facies_polygon_layer 的
polygon_qc/area_unit/area_approx_m2)与编图 QA 消费。

### `_METRES_PER_DEGREE_LAT = 111_320.0`
- 常数:每纬度度的米数(赤道子午线近似,非椭球)。面积尺度 =
  (111320·cos(平均纬度))·111320(经度向 cos · 纬度向);长度尺度同理分轴。
- C++:`inline constexpr double kMetresPerDegreeLat = 111320.0;`,oracle 冻结常数值。

### `is_geographic_crs(crs: str | None) -> bool`
- 输入:任意 str/None;`str(crs or "").strip()` 后委托
  `workflow.crs_policy.crs_is_geographic`(try/except → False)。
- 输出:**恒 bool**(bool(None)=False)——与 crs_policy 的三值语义不同:
  未知 id/空白串在 crs_policy 是 None(不可验证),经本函数坍缩为 False
  (非地理)。这是有意的消费侧语义:面积标签走「{crs}-unit²」分支而不是
  伪装成地理近似。
- 分支:builtin 地理表(4326/4269/4267/4214/4610/4490,去重 EPSG:3857
  例外先行)→ True;其余(含 pyproj 缺席)→ False。pyproj 在场时
  "WGS84"/"EPSG:32650" 分别 True/False(test_geometry_units_qa 的
  TestCrsClassification 依赖 pyproj;无 pyproj 环境同为 False 路径)。
- review R2-P1/R3-P1 背景:曾用子串启发式,把 "WGS 84 / UTM zone 48N"
  误判地理——现在是单一谓词委托,"WGS 84 / UTM…" → False 是回归钉子。
- C++:`bool is_geographic_crs(const std::optional<std::string>&)`,
  nullopt/空 → false;调用既有 `pwb::mapping::crs_is_geographic`。
- 测试缺口:pyproj 在场时非 builtin 地理 id(如 WGS84)本函数为 True 的
  分支,无 pyproj 的 oracle 环境冻结不到(kernel 段为 False);记入
  pyproj_env 对照段。

### `area_unit_label(crs: str | None) -> str`
- 分支:is_geographic → "deg²";非空(strip 后)→ f"{strip(crs)}-unit²"
  (用 strip 后的**原串**,不做 EPSG 归一化:" epsg:3857 " →
  "epsg:3857-unit²");空 → "unknown-unit²"。
- 未知 id("EPSG:99999")→ "EPSG:99999-unit²":不因不可验证而改标签,
  标签跟随声明串。上标 ² 是 UTF-8 多字节,oracle 按字节冻结。
- 测试转译:area_unit_label(None) == "unknown-unit²"
  (test_geometry_units_qa::test_empty_is_not_geographic_but_labels_unknown)。

### `ring_area_with_unit(ring, crs) -> (float, str, str | None)`
- 面积核:委托 polygonization.calculate_shoelace_area(0.5·|Σ cross|,
  n<3 → 0,循环 i∈[0,n-1) 不补闭合边——**环须闭合**(首尾重复点),
  未闭合环的「面积」是开链叉积和,语义不同(oracle 冻结同一方环
  closed vs unclosed 两案例钉住该约定)。C++ 复用已绿
  `pwb::mapping::shoelace_area`(逐行同构,已核对 polygonization.cpp:163-175)。
- 地理分支:lats = [float(pt[1]) for pt in ring if len(pt) >= 2]
  (点的 y 平均;**空环 → mean_lat=0 → cos=1 → 满尺度**,面积本身为 0);
  approx = raw·(111320·cos(mean_lat))·111320;
  标签 "≈m² (local-scale approx, geographic CRS)";
  warning = f"CRS {crs!r} is geographic: area is a local-scale approximation
  from the ring's mean latitude; reproject to a projected CRS for exact
  areas"(含 crs 的 Python repr——None → `None`,串 → 带引号原样,**不 strip**)。
- 投影/未知非空分支:(raw, f"{strip(crs)}-unit²", None);未声明:
  (raw, "unknown-unit²", "CRS undeclared: area unit is unknown (not metres)")。
- 数值验证(test_geometry_units_qa):赤道 0.01° 方环 ≈1.2392e6 m²(rel 0.02);
  纬 60 同环 = 赤道环·cos60°(rel 0.01);投影 100² 方环 raw 10000 无 warning。
- 测试缺口:负纬度(对称,cos 同)与空环分支无 pytest;oracle 补
  (生成器直接跑真实函数,非手写)。
- C++ 结构体 `AreaWithUnit{area, unit_label, warning}`;Ring =
  `std::vector<Point>`(Point=array<double,2>)——len(pt)>=2 由类型保证,
  记 decisions。

### `polyline_length_with_unit(vertices, crs) -> (float, str, str | None)`
- pts 全部强转 (float(x), float(y));地理分支:mean_lat 同上(**空顶点表
  也是 mean_lat=0 满尺度**),total = Σ hypot(dx·111320·cos, dy·111320);
  标签 "≈m (local-scale approx, geographic CRS)";warning =
  f"CRS {crs!r} is geographic: length is a local-scale approximation"。
- 平面分支:total = Σ hypot(相邻差)——与 contouring.calculate_polyline_length
  逐行同构,复用 C++ `pwb::mapping::polyline_length`(已核对
  contouring.cpp:213-220);非空 CRS → f"{strip(crs)}-unit" 无 warning;
  未声明 → "unknown-unit" + "CRS undeclared: length unit is unknown
  (not metres)"。
- 空/单点折线 → 0.0(geo 分支仍带 ≈m 标签与 warning)。
- 测试转译:投影 (0,0)→(30,40) = 50;地理 0.01° ≈ 1113.2 m(rel 0.01)。
- C++ 结构体 `LengthWithUnit{length, unit_label, warning}`。

## 文件 2:paleo_workbench/mapping/crs_contract.py(383 行)

模块角色:V9 W3(D1 决议)单一 CRS 谓词/解析权威,收编 4 套并存谓词 +
8 处 quiet-4326。叶模块:stdlib + 可选 pyproj。核心纪律:**未声明永远
带判词,绝不静默 4326**;**不可验证 ≠ 通过**(fail-open 只在域校验,
且只在「可证明失配」处拦截)。

### `normalize_crs(crs: object) -> str`
- `str(crs or "").strip()`;空 → "";否则委托
  map_render_backend._normalize_crs_name:`re.match(r"^(EPSG:\d+)\b",
  text, IGNORECASE)` 命中 → group(1).upper(),否则**原样返回**(不猜)。
- 手移植要点(C++ 无 regex 需求,手写等价解析):锚定起始、大小写无关
  "EPSG:" 前缀、≥1 位十进制数字、`\b` = 数字后继字符 ∈ \w(ASCII
  [A-Za-z0-9_])或串尾才命中;"EPSG:4326x"/"EPSG:4326_X" 回溯后仍无
  边界 → 不命中 → 原串;"EPSG:4326." 命中 → "EPSG:4326";
  "EPSG:0123" 保留前导零;"xxxEPSG:4326" 锚定失败 → 原串。
- 非显然:该函数是全部 CRS 比较的真源链(V9 D1;V10 02-crs-transform §6:
  测试钉 canonical 而非别名形态);**不验证可解析性**——"EPSG:99999"
  原样通过,后续由谓词/域函数诚实降级。

### `crs_is_geographic(crs: object) -> bool | None`
- `str(crs or "").strip() or None` → workflow.crs_policy.crs_is_geographic。
  空白串 → None(经 None 化),与直接委托的差别仅在此;C++ 侧既有
  `pwb::mapping::crs_is_geographic`(crs_policy.hpp)对空串/空白串同样
  nullopt(已核对:token trim 后不中表 → nullopt),**不再重复声明**,
  复用即委托(v9 D1:不重实现轴数学)。
- 三值:True/False = 轴单位已知;None = 不可验证,never a guess。

### `CRSResolution`(frozen dataclass)+ `resolve_crs(value, *, purpose, fallback="")`
- 字段:crs(归一化结果,"" = 未解析)、declared(源带了可用 CRS)、
  degraded_reason;`ok` = declared and bool(crs)。
- 判定:normalize(value) 非空 → (crs, True, "");否则 fallback 归一化
  非空 → (fallback, False, f"{purpose}: CRS 未声明,按记录在案的默认
  {fallback} 处理(降级)");否则 ("", False, f"{purpose}: CRS 未声明且
  无默认——按未知坐标处理(降级)")。
- 判词是**契约**:调用方必须呈现(诊断/状态条/QA 注记),禁止吞掉;
  fallback 只允许「记录在案的 legacy 默认」(V10 §5:服务边界 empty→4326
  由 test_mapping_crs_idw 钉住,是显式契约不是静默猜测)。
- 中文判词逐字节冻结(UTF-8);purpose 进入判词 → C++ 形参
  `const std::string& purpose` 无默认(resolve 调用点都显式给)。
- 测试转译(test_v9_interaction_facts::test_resolve_crs_declared_and_degraded):
  ok/undeclared/fallback 三态 + "未声明"/"默认" 判词子串。

### `panel_publish_crs(value, *, purpose="图层面板发布") -> str`
- resolve_crs 后:**未声明 → 返回 ""**(按原坐标呈现)+ logger.warning
  (降级可查);声明 → 归一化 crs。V9 R1-P1-1:消灭面板快照的
  `or "EPSG:4326"` 伪造路径;工程模型默认值照常声明 4326 是另一回事。
- C++ 内核无 logger:返回 "" 即契约,降级文案经 resolve_crs 可取;
  日志面记 decisions(不移植 logging 副作用)。
- 测试转译(test_v9_review_fixes::test_panel_publish_crs_honest):
  "EPSG:4326"→本身;""→"";None→"";补:描述式/未知 id → 归一化原样。

### `crs_axis_unit_metres(crs) -> bool | None`
- 空 → None;否则 pyproj 解析取第一水平轴 unit_name ∈ {metre, meter, m}
  (strip+lower);异常 → None。按归一化串 lru_cache(64)。
- 用途:诚实比例尺分母的前提——只有**可验证米轴**才给数,其余 0.0。
- C++ 无 pyproj:恒 nullopt(Python `except ImportError → None` 的真实
  路径;与 crs_policy「未知不猜」同纪律)。oracle kernel 段冻结 None;
  pyproj_env 段记录 32650→True/4326→False 对照。

### `scale_denominator_from_pixels(mupp, ppi, crs) -> float`
- `if crs_axis_unit_metres(crs) is not True: return 0.0`;
  `if mupp <= 0 or ppi <= 0: return 0.0`;
  `return mupp * 39.370078740157481 * ppi`(英寸/米常数,QGIS 像素画布
  同公式)。仅回退画布使用(原生走 QgsMapCanvas::scale())。
- C++:三个分支全移植;前两分支在无 pyproj 内核下前者恒真 → 公式行
  不可达(保留:契约完整,后续轴真源落地即活;记 decisions)。
- oracle:kernel 段全 0.0(含负/零 mupp、ppi);pyproj_env 段记录
  (10,96,"EPSG:32650") 的真实公式值。

### `geod_for_crs(crs)`(不移植)
- 地理 CRS → pyproj.Geod(椭球半轴构造);非地理 → None;椭球不可解析
  → 记日志回退 Geod("WGS84")(V9 D8/W8:测地测量 fallback;WGS84 替换
  必须留痕)。消费方:测量工具。
- **不移植理由**:返回 pyproj.Geod 对象(椭球数学库),Qt-free 数值核
  不引入;无 pyproj 环境本函数恒 None(kernel-mode oracle 冻结到该事实),
  消费方保持诚实平面标签。findings 留档,decisions D 编号记录。

### 域契约常量
- `_GEOGRAPHIC_DEGREE_DOMAIN = (-180.0, -90.0, 180.0, 90.0)`(地理轴域是
  解析定义,精确);`_DOMAIN_EPSILON = 1e-9`(贴边不失配);
  `_PROJECTED_DOMAIN_SLACK = 0.02`(投影域是 area_of_use 角点近似框,
  外扩 2%;地理域不外扩)。

### `crs_coordinate_domain(crs) -> (minx, miny, maxx, maxy) | None`
- normalize 后空 → None;`crs_is_geographic(text) is True` → 经纬度全域
  (注意:先 normalize,描述式 "EPSG:4326 / WGS84" 命中);
  其余(投影/未知)→ pyproj area_of_use 角点 4326→CRS 变换(角点
  |x|,|y| < 1e12 才可信,反常 → None)→ min/max + 2% 外扩;无
  area_of_use/无 pyproj/异常 → None(诚实:无法验证 ≠ 通过)。
- C++:地理分支精确移植(常量);投影分支 = ImportError 路径 → nullopt。
- 测试转译(test_topo_m0_foundation::test_geographic_domain_is_degree_axes):
  4326 与描述式 → (-180,-90,180,90);"" → None。

### `DomainMismatch`(frozen)+ `describe()`
- 字段 crs、extent、domain;describe 是中文判词:
  f"声明 CRS {crs} 的有效坐标域为 x[{d0:g}, {d2:g}] / y[{d1:g}, {d3:g}],
  数据实际坐标范围为 x[{e0:g}, {e2:g}] / y[{e1:g}, {e3:g}]"。
- `:g` = C %g(6 位有效数字、去尾零);C++ 用 snprintf("%g") 同源。
- 测试转译:mismatch.describe() 含 "16000"。

### `coordinate_domain_mismatch(crs, extent) -> DomainMismatch | None`
- extent None / 解析失败 / 退化解(xmin>xmax 或 ymin>ymax)→ None;
  domain 不可推导 → None(**fail-open:只拦可证明的失配**,与镜像层
  extent 检查同约定);eps = 1e-9·max(1, |dx_domain|, |dy_domain|);
  四边全部落在 [min-eps, max+eps] 才放行;失配 → 事实(crs 字段 =
  normalize(crs) or str(crs or "")——归一化优先,原串兜底)。
- 测试转译(test_topo_m0_foundation::test_domain_mismatch_clear_cases +
  scenario2):4326+本地坐标 → 失配;域内/None 范围/未声明 → None;
  32650+0..100 失配(**pyproj 依赖**,kernel 段 None、pyproj_env 段
  失配——C++ 按无 pyproj 断言 None);99999 → None。oracle 补:
  贴边 eps 吸收案例(-180.0000001 在 eps 3.6e-7 内 → 放行)、
  超界案例、倒置 extent、None crs、空白 crs。

### `CRSInference`(frozen)+ `infer_crs_from_extent(extent)`
- 字段 suggested_crs(空 = 保持本地)、basis(推断依据文案);
  `suggests_declaration` = bool(suggested_crs)。
- 判定:extent 不可用(None/解析失败/倒置)→ ("", "数据坐标范围不可用
  ——不推断");对 "EPSG:4326" 做 coordinate_domain_mismatch:无失配 →
  ("EPSG:4326", "数据坐标完全落在经纬度域内(地理坐标)");失配 →
  ("", "数据坐标超出经纬度域(本地/投影坐标)——保持本地")。
- M0 §6 推断锁定:推断只是**建议**,用户确认后声明 + crs_locked;新工程
  不预设 4326(test_project_models + test_topo_m0_foundation 钉住)。
- C++ 全量可移植(地理域纯函数);basis 中文文案逐字节冻结。

## 文件 3:paleo_workbench/mapping/crs_chain.py(211 行)

模块角色:V10 M-B/M-C + M0 §6 收敛。CRS truth chain(工程声明 → 契约 →
QgsProject → 画布 → 层 → 变换 → 会话)的两个宿主面:进前段 CRS 门
evaluate_edit_entry + 链状态投影 CrsChainFacts。谓词/归一化全部来自
crs_contract(不重推导)。

### `LayerCrsFacts(layer_id, crs="", extent=None)` + `effective_crs(project_crs)`
- 进前校验的单层事实;有效存储 CRS = normalize(层声明) or
  normalize(工程声明),均未声明 = ""(层声明优先,工程声明是上下文
  不为层级背书——V11 10-topology §2)。

### `CrsEntryVerdict(allowed, reason="", mismatches=(), canvas_crs="", declared_crs="")`
- `__bool__` = allowed;mismatches 携带域失配事实(引导框「受影响层」
  全景数据源);reason 面向用户(域失配判词含首个失配 describe() +
  受影响层 id 列表顿号连接;同 CRS 判词含画布/层双 id)。

### `evaluate_edit_entry(layers, *, canvas_crs, project_crs="", all_layers=None, runtime_crs_capable=False)`
- 判定按序:(1) **域校验**——all_layers(缺省 = candidate)逐层
  effective_crs → coordinate_domain_mismatch,任一失配 → 拒绝 + 全景;
  (2) **同 CRS**——candidate 逐层:画布与存储都已声明且不同 → 拒绝;
  层已声明、画布未知且 runtime_crs_capable → 再查
  `crs_is_geographic(storage) is False`(投影)→ 放行(本地投影
  authid 空 = no-OTF 恒等渲染,不是故障),地理 → fail-closed 拒绝
  (经纬度被按米错绘是真实风险);其余(raw 帧)放行。
- V10 判定表(02-crs-transform §1)+ M0 并入域校验;旧
  evaluate_commit_guard 已退休(测试语义由本函数延续)。
- **本切片不移植**(§6 写入范围只有 geometry_units/crs_contract);
  findings 留档供后续切片。测试缺口:无——test_v10_crs_chain_and_identity
  14 项 + test_topo_m0_foundation scenario2 已密集钉住。

### `CrsChainFacts(project_crs, canvas_crs, storage_crs, runtime_crs_capable)`
- 状态/ToolContext 只读投影:project_declared/canvas_declared
  (= normalize 非空)、consistent/reason(以 <chain> 伪层跑
  evaluate_edit_entry)、as_dict(全部经 normalize;ToolContext v3/v4 的
  诚实空值面:test_v9_interaction_facts —— 未声明 = ""、scale = 0.0)。

### `runtime_crs_capable()`(模块函数)
- qgis_runtime.health.probe_qgis_runtime 的 qgis_available &&
  canvas_crs_available,进程缓存;无桥 → False(诚实降级,
  test_v10_qgis_runtime_health::test_crs_chain_runtime_capable_fails_safe_
  without_bridge)。依赖 QGIS 桥探测——**不移植**(Qt/桥面,非 Qt-free 核)。

## 文件 4:paleo_workbench/workflow/crs_policy.py(191 行;已移植 M7)

### 常量:POLICY_PLANAR/"planar_degrees"/"projected"/"undeclared"、
### DISTANCE_POLICIES、`_KNOWN_GEOGRAPHIC`、`_PROJECTED_EXCEPTIONS`
- builtin 地理 id 表 {4326, 4269 NAD83, 4267 NAD27, 4214 Beijing1954,
  4610 Xian1980, 4490 CGCS2000} + **3857 在表内但被例外表覆盖为投影**
  ("degrees in, projected metres out; the axis units below decide"——
  注释原意:仅凭 id 不够,例外表先行)。C++ crs_policy.cpp:14-26 同表。

### `crs_is_geographic(crs) -> bool | None`
- `if not crs: return None`(None 与 "" ,空白串不短路);token =
  split("/")[0].strip().upper();例外表 → False;builtin → True;
  pyproj → parsed.is_geographic;异常 → None。lru_cache(None)
  (V12-B:每 feature/ring 调用,无缓存时 pyproj 导入失败重试 ~2s/层)。
- **单一谓词权威**:geometry_units.is_geographic_crs、crs_contract、
  qgis_mirror._geographic_auth 全部委托此处(C++ 对应
  pwb::mapping::crs_is_geographic,本任务复用,零改动)。
- 测试转译:已知 id 表 + None/"" → None + 未知 id → None(无 pyproj);
  C++ crs_policy oracle 已冻结 builtin 13 + optional 4。

### `resolve_distance_policy(crs, distance_policy=None) -> dict`
- 返回 {policy, crs, axes_known, annotation, warning}。非法 policy →
  ValueError(消息含 tuple repr + python str repr);crs is None(恒等
  None,空串走不可验证路径)→ planar + "undeclared" 注记;显式
  planar_degrees/projected 按操作员宣言(交叉警告:非地理给
  planar_degrees 警告、地理给 projected 警告);默认 planar:地理 →
  planar_degrees + APPLIED 警告;None → planar + unverifiable 注记 +
  警告(R1/R3 P2:注记不得谎称已确认);投影 → planar 干净。
- C++ crs_policy.cpp 已逐字对齐(interpolator 接线写 FactorGrid);
  本任务**只消费,零改动**。测试:tests/test_crs_distance_policy.py 全文
  已读,断言与 C++ oracle 一致(已知 id、unknown→unverified、
  undeclared、ValueError 文案)。

## 文件 5:paleo_workbench/mapping_workspace/crs_gate.py(136 行)

模块角色:V11 M0(#1285)可编辑层 CRS 契约的宿主侧门禁:声明的有效
坐标域 vs 数据实际范围的失配检测(已知事故形态:4326 + 0..16000 本地
坐标),产出机器可读 CrsDomainCheck + 修复选项;纯函数无 Qt。
**本切片不移植**(§6 范围外),findings 留档。

### `GEOGRAPHIC_AUTHIDS` / `_GEOGRAPHIC_LATLON_PREFIXES` / `_DOMAIN_SLACK`
- 小写 authid 集 {epsg:4326, 4490, 4214, 4610, 4269, 4267, 4230, 4314,
  ogc:crs84};+proj=longlat/latlong 前缀;域容差 1°(球面环绕合法溢出)。
- 与 crs_policy 表的关系:平行的小集(多 4230/4314/crs84;小写匹配;
  含 PROJ 串前缀)——crs_gate 语义是「声明检测」(fail-open 门外),
  不是轴真值;两表并存是 M0 的显式选择(文档注明),不是分叉疏漏。

### `is_geographic_declaration(declared_crs) -> bool`
- strip+lower;authid 集命中或前缀命中 → True;空 → False。
  test_topology_m0_v11:3857/""/"LOCAL" → False。

### `feature_bounds(coords) -> (xmin, ymin, xmax, ymax) | None`
- 坐标流包围盒;len<2 或非 finite 跳过;无有效点 → None。

### `CrsDomainCheck(ok, declared_crs, geographic_declared, bounds, reason)` + `fix_options`
- ok=False 时 fix_options = ("declare_local", "clear")(推荐序);
  reason = crs_mismatch_reason(声明 ±180/±90 vs 数据范围为本地坐标——
  失配声明会污染编辑缓冲几何;%g 格式)。

### `validate_crs_domain(declared_crs, bounds) -> CrsDomainCheck`
- 非地理声明/None bounds → ok=True;地理 + bounds 超 ±180∓1/±90∓1 →
  失配;slack 内(如 -180.5)放行(test: test_small_overflow_within_slack)。

### `crs_mismatch_reason(declared, bounds) -> str`
- 判词模板(f"声明 {declared}(经纬度域 ±180/±90),但数据坐标范围
  x:[{xmin:g}, {xmax:g}]、y:[{ymin:g}, {ymax:g}] 为本地坐标——失配声明
  会污染编辑缓冲几何。")。

### `collect_crs_mismatches(layers) -> dict[layer_id, CrsDomainCheck]`
- 工程打开兜底扫描:(layer_id, declared, coords) 流 → 仅收失配层;
  一次修复永久生效(声明更正后进前门自然放行)。

## 文件 6:libs/mapping_kernel crs_policy.hpp/.cpp(已绿,禁止分叉)

- crs_policy.hpp:文档声明「C++ has no pyproj … Unknown ids are never
  guessed」——本任务的 crs_contract/geometry_units C++ 侧必须保持同一
  立场(unknown → nullopt / False),不得私加 EPSG 表「补全」。
- crs_is_geographic:空/nullopt → nullopt;token(头段 trim+ASCII upper)
  → 例外表 → builtin 表 → nullopt。**无 strip-then-delegate 差异**:
  与 crs_contract.crs_is_geographic 对全部字符串输入等价(空白串两侧
  均 nullopt;" x " 头段 trim 后同)。已逐行核对,复用不重写。
- resolve_distance_policy:错误文案 python_str_repr 兼容(' 单引号优先、
  含 ' 用 "),invalid_argument(ValueError 对应)。该 repr helper 在
  匿名命名空间——geometry_units 的 warning 需要 crs!r,本地复制一份
  小 helper(不为此改已绿文件,decisions 记录)。
- oracle 既有格局:builtin(13 geo + 22 resolve + 4 errors)精确对账,
  pyproj_optional 只断言 nullopt——本任务的 oracle 沿用
  builtin/pyproj 两段思想,但 kernel 段用「pyproj 阻断的真实 Python」,
  C++ **值级对账**(比 crs_policy 测试更强,因为环境确定性)。

## 测试 → oracle 案例表汇总(案例清单的权威在生成器源码内注释)

| pytest 来源 | 转译 |
|---|---|
| test_geometry_units_qa(TestCrsClassification/ RingAreaUnits/ PolylineLength/ ReviewRegressions) | is_geographic/area_label/ring/length 案例表(含 0.01° 赤道/纬 60、投影 100²、R3-P1 投影子串) |
| test_v9_interaction_facts §crs_contract | normalize/resolve 三态/axis_metres/scale_denominator/geographic 谓词案例 |
| test_v9_review_fixes(R1-P1-1) | panel_publish_crs 三态 |
| test_topo_m0_foundation §6 | domain 常量、mismatch 六分支、inference 三分支 |
| test_v10_crs_chain_and_identity | (crs_chain;本切片不移植,留后续切片 oracle) |
| test_topology_m0_v11 §CrsDomainValidation | (crs_gate;本切片不移植) |
| test_crs_distance_policy | (crs_policy 已移植,既有 oracle 覆盖) |
