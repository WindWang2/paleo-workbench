# CONV-20 Findings — mapping_kernel pybind 门面（逐符号）

worktree：`/home/kevin/project/worktrees/cpp-conv-20-pybind-facade`，BASE=`35987e13`。
覆盖任务 §5 全部清单文件；C++ 侧公开符号语义经全文精读 + 4 个并行探查代理交叉核对。

## 1. paleo_workbench/mapping/CPP_EXTENSION.md（map_edit_core 先例）

- 边界规则（本任务照抄）：跨语言桥走 **feature id + 紧凑坐标缓冲**，不做逐顶点 Python 回调；
  `HAS_CPP` 仅在 `import <module>` 成功时为 True；符号缺失用 `getattr` 逐个回退、每次调用可回退。
- 门面函数 ↔ C++ 符号一一映射（hit_test/snap/move_feature/set_vertex/insert_vertex/delete_vertex/validate）；
  扩展缺失时 HAS_CPP=False、全部走 Python，测试照样绿。
- 构建方式：pybind11 + `pip install -e native/<pkg>`（setup_helpers.Pybind11Extension），源码可驻子模块
  （geo-viz-engine/native/map_edit_core，"source in submodule, build in consumer"）。
- 行为对账：Python 路径测试 + `test_map_edit_core_cpp.py`（缺扩展 skip、编了断言）；CI 可加 HAS_CPP=True 的 job。
- 本任务差异：映射核已以 CMake 静态库形态落在 `libs/mapping_kernel`，故门面构建走仓库根 CMake 的
  `BEGIN CONV-20` 开关 + vendor 头，而不是 setup.py 包（见 decisions D2/D3）。

## 2. map_edit_api.py

- **不存在于本仓**（CPP_EXTENSION.md 描述的目标文件未落地；`paleo_workbench/mapping/` 下无此文件）。
- HAS_CPP 门面真实先例在两处：`paleo_workbench/viz/well_log_api.py`、`viz/seismic_3d_api.py`
  （走 `native_backend.dispatch`），以及 geoviz 子包的 map_edit api（本仓不可见）。
- `native_backend.py` 集中 try-import `seismic_3d_core/well_log_core/map_edit_core/grid_render_core/layer_model_core`，
  用 `native_status()`（fresh/stale/missing）与 `__version__` 元数据挡旧 .so 影子。**该文件不在本任务写入范围**，
  故 mapping_kernel 门面不接入 native_backend，按 CPP_EXTENSION.md 的直接 try/except 模式新开薄门面。

## 3. geo-viz-engine/native/map_edit_core（pybind 先例，子模块未初始化于本 worktree）

- 顶层模块名扁平、`_core` 后缀；pybind11>=2.12 来自根 pyproject `native` extra。
- 本机实证的影子 .so 风险（conftest `_assert_bridge_origin`）：仓库根目录在 sys.path 且优先于包目录，
  编译产物落根目录会遮蔽新构建——**本任务的 .so 一律留在 build 树，用 PYTHONPATH 接入 pytest/ctest**。
- ADR 0059 红线（本核天然满足）：过桥的只有数据（dict/list/标量），无 QObject/QWidget/回调。

## 4. libs/mapping_kernel 公开头（逐公开符号）

### contouring.hpp（Point/Polyline 宿主）
- `Point = std::array<double,2>`；`Polyline = std::vector<Point>`；`Grid{w,h,grid_x,grid_y,grid_z(double,行主序,NaN=nodata)}`。
- `nice_contour_levels(vmin,vmax,target=7)`、`quantile_contour_levels(grid,quantiles={0.1,0.25,0.5,0.75,0.9})`
  （np.nanpercentile linear 语义 + round(v,6) 去重）、`douglas_peucker`、`chaikin_smooth(it=1)`、
  `marching_squares_contours(grid,level,simplify_tol=0,smooth=0)`、`round_to`（Python half-even）、
  `is_close`（rel_tol=1e-9）。本任务不绑定（非三个目标函数），但提供 Point 类型。

### interpolator.hpp
- `SamplePoint{x,y,value,qc_flag="ok"}`。
- `InterpolateOptions{method="idw"(!), grid_n=50, power=2.0, max_neighbors?, search_radius?, min_neighbors=1,
  variogram_model="spherical", boundary(空=无掩膜), crs, distance_policy="planar"}`。
  **与 Python `InterpolationOptions.method="kriging"` 默认值分歧**（C++ 核注释未解释；models.py:104 是 Python 契约）。
  门面因此从不依赖 C++ 默认值：选项 dict 由 Python dataclass 显式生成（D8）。
- `GridStatistics{min,max,mean,std(NaN 哨兵),valid_count,total_count}`：finite 格元 float64 mean/std(ddof=0)。
- `FactorGrid`：IDW 路径填 algorithm_id="idw"/method="idw"/power/grid_n/grid_x/grid_y/grid_z(float32 行主序)/
  n_samples/min_neighbors/max_neighbors/search_radius；kriging 路径另填 model/variogram_fit=
  "numpy-grid-ols"/range/sill/nugget/duplicates_merged/variogram_bins + variance_grid。
  两路径都过 apply_domain_mask（domain_masked_cells）与 resolve_distance_policy（distance_policy/annotation）
  及 grid_statistics。**不含 sample_points/degraded/neighborhood 披露块**（Python 侧元数据超集留在纯路径）。
- `grid_statistics(vector<float>)`、`linspace(start,stop,num)`（num<=0 空、num==1 {start}、末点强制=stop）、
  `dataset_extent(points)`（全点 bbox，span 糾缩 0.05、否则 max(0.01,span*0.1)；空→(0,0,1,1)）、
  `valid_points`（finite 值且 qc∈{ok,good,""}）、`validate_dataset`（<2 → "Insufficient sample points (N); at
  least 2 valid points required for spatial interpolation."；全共点 → "All points are collocated at the same
  coordinate."）、`deduplicate_samples(tol=1e-9)`（stable_sort by (x,y)，组内均值）、
  `model_semivariance(h,nugget,psill,r,model)`（r≥1e-9）、
  `interpolate_factor(points,options)`（validate 失败 throw invalid_argument，消息=issues 以 "; " 连接；
  kriging 去重后 n==0 → "kriging requires at least one sample"；boundary 1..2 顶点 →
  "boundary ring needs at least 3 vertices"；std::invalid_argument → pybind 自动映射 ValueError）。
- kNN tie-break=(dist,idx) 升序；radius 语义=**> radius 剔除**（恰好等于 radius 仍是邻居；scipy 是异于 C++ 的
  exclusive 边界——frozen 契约声明只对 unique-distance 邻域集成立，见 decisions D6）。
- 解算梯子：solve→scaled-ridge→**正规方程**（Python 末级是 lstsq/SVD；仅双双奇异才触达，oracle 未覆盖）。

### extract.hpp
- `ExtractOptions{target_horizon, unit(optional<string>: nullopt→FACTOR_DEFAULTS 表，""=显式空), crs}`。
- `FactorPoint{name,value,unit,well_id,well_name,x,y,crs,formation,qc_flag="ok",metadata(Json object)}`。
- `FactorDataset{factor_name,unit,target_horizon,crs,points,metadata(=诊断)}`。
- `extract_factors(const Json& records, factor_name, options={})`：records 非 array 全跳过；非 object 记录跳过；
  坐标族序 project→xy→lnglat→longitude/latitude→surface，第一完整对胜出（0.0 合法、不跨族），
  否则 coordinates[0:2]；数值解析 py_float：number/bool→1.0/0.0/string strip 后 strtod 全串消费；
  值查找 factor_name→"value"→"val"→casefold 别名→嵌套 attributes/properties/metadata（无嵌套 "val"）；
  派生 sand_ratio=100*Hs/Ht（Ht>0）、formation_thickness=base−top（base>top），metadata.derived 记
  rule+sources，diagnostics 计数 derived_points；`coordinate_key_families_used`/`skipped_missing_coordinates`/
  `skipped_invalid_coordinates`，族数>1 加 `coordinate_key_family_mixing=true`。**不抛异常**。
- Python 侧对应混族时 logger.warning（logger 名 `paleo_workbench.mapping.geological_pipeline.pipeline`，
  消息含 "mixed coordinate key families"）——门面 C++ 路径需补发该 warning 保持行为对齐（D9）。

### class_grid.hpp
- `FaciesPoint{x,y,facies}`；`ClassGrid{grid_x,grid_y,grid_z(float32 行主序,clip 外 NaN),facies_names}`。
- `point_in_ring_inclusive(x,y,ring,eps=1e-9)`（on-edge True；与 interpolator even-odd 在环边分歧，oracle 钉死）。
- `nearest_neighbor_class_grid(points,extent,grid_n=80,clip_ring={})`：空点 → invalid_argument
  "point-to-surface needs at least one well facies point"；first-seen 相 id；n=max(2,grid_n)；
  严格 `<` 最近距离 → tie 取先出现点（=np.argmin）。

### crs_policy.hpp / sample_normalization.hpp（间接面）
- `resolve_distance_policy(crs?, distance_policy?)`：DistancePolicy{policy,crs?,axes_known?,annotation,warning?}；
  非法 policy → invalid_argument，文本=`distance_policy must be one of ('planar', 'planar_degrees', 'projected'), got <python repr>`。
  **builtin 表无 pyproj**：仅 6 个地理 id + EPSG:3857 例外；其余 id axes_known=nullopt → "unverifiable" 注释。
  Python 侧同函数有 pyproj 时 EPSG:32650 会得到 "projected/verified planar metres" 注释 → **两面对非 builtin id
  的 annotation 文本分歧** → 门面统一用 Python `resolve_distance_policy` 结果覆盖 C++ 注释（D10），数值不受影响。
- `normalize_factor_samples(Json points, policy="mean")`：本任务不绑定（非目标函数）。

## 5. libs/domain/include/pwb/domain/json.hpp

- `using Json = nlohmann::ordered_json`（**ordered**，键序保持）；vendor 单头在
  `libs/data_suite/third_party/nlohmann/json.hpp`（3.12.0，含版本宏校验），include 路径由
  libs/domain 的 `PWB_VENDOR_DIR` 提供；`Pwb::MappingKernel` PUBLIC 依赖 `Pwb::Domain` → 链接即得。
- 数字按 token 存 int64/uint64/double，**1 与 1.0 是类型差异**（json_semantically_equal 亦如此）；
  `Json::parse(string)`；null≠缺键。绑定层需 ordered_json↔py 双向递归转换器（D5）。

## 6. pyproject.toml（extras/native）

- `native = ["pybind11>=2.12"]`；`qgis-renderer` 另加 ninja。requires-python `>=3.12,<3.13`（注释：cp312/cp313
  混装曾致 .so 遮蔽）——本机 conv12 venv 是 3.14，构建产物 SOABI=cpython-314，与注释教训一致：**.so 不入库、
  不落根目录**（.gitignore 已 ignore `*.cpython-3*-x86_64-linux-gnu.so` 与 `build/`）。
- pytest 配置：testpaths=tests+geoviz 五包；`pythonpath=[".", …geoviz 子包]`；qt_api=pyside6；
  markers 含 qgis/welllog_binding；conftest 顶层 import PySide6 → **tests/ 下任何 pytest 会话硬依赖 PySide6**。
- v3.1.0 是 pybind11 当前最新 tag；vendor 头树（BSD-3）入 `libs/mapping_bind/_vendor/pybind11/`（D3）。

## 7. tests/test_geological_mapping_pipeline.py 等（断言→oracle 案例表）

- 范式（`test_map_edit_core_cpp.py`）：
  `pytestmark = pytest.mark.skipif(not api.HAS_CPP, reason="... not installed")`；首测
  `assert api.HAS_CPP is True`；parity 用 `pytest.approx` 对原始 C++ 调用。
- interpolate_factor 断言面（本任务 pytest 复用同 dataset 同参数对比，不重抄全部）：shape=(grid_n,grid_n)、
  axes 全有限且长度=grid_n、grid_z 全有限（无 radius/knn 时）、variance≥0、常值场全≈常量、
  重复点 kriging 均值合并 duplicates_merged==2、min_neighbors>可用邻居 → NaN、determinism
  byte-identical、domain mask 后环外全非有限 + params["domain_mask"]=="user_boundary"、
  distance_policy/annotation 落 params、空数据集 ValueError 含 "Insufficient"、全共点 ValueError 含 "collocated"。
- extract_factors 断言面：别名三语解析（POR/porosity/孔隙度…）、单位权威表（probability→"1"、砂地比→"%"、
  古水深→"m"、未知→""）、0.0 坐标合法、族隔离（x+lat → skip 且 families={}）、project 优先于 xy、
  派生砂地比/厚度 provenance、混族 → metadata 标志+warning、坏记录跳过计数。
- nearest_neighbor_class_grid：仅经 `point_to_surface_features` 间接测（grid_n=20、两相都出现）；
  直接契约（返回 4 元组、first-seen id、argmin tie、inclusive clip、空点 ValueError 文案）由 oracle
  `class_grid_oracle.json` 钉死，本任务 pytest 沿用同 dataset 直比。
- 错误文案全集（门面必须逐字）：`"point-to-surface needs at least one well facies point"`、
  `"Insufficient sample points (N); at least 2 valid points required for spatial interpolation."`、
  `"All points are collocated at the same coordinate."`、
  `"distance_policy must be one of ('planar', 'planar_degrees', 'projected'), got 'X'"`。

## 8. FactorGridResult / resolve_distance_policy / geometry_planar（门面回填面）

- `FactorGridResult`（workflow/factor_grid_result.py）：grid_z float32 (h,w) NaN=nodata、grid_x/grid_y float64、
  `__post_init__→_finalise` 自动重算 statistics=GridStatistics.from_grid（故门面统计天然一致）、
  variance_grid 同规、boundary 收 finite float 对、`algorithm_parameters` 自由 dict；
  `input_points` 属性读 params["sample_points"] → 门面 kriging/idw params 需含 sample_points。
- `resolve_distance_policy(crs, distance_policy)`：返回 5 键 dict（policy/crs/axes_known/annotation/warning）；
  geographic CRS + 默认 planar → 升级 planar_degrees 且 logger.warning（门面调用同函数 → 侧效应一致）。
- `point_in_ring_scalar_inclusive`（Python）与 C++ `point_in_ring_inclusive` 已对齐（eps=1e-9）。

## 9. 测试缺口（如实）

- C++ 末级解算（双双奇异→正规方程 vs Python SVD）无 oracle 覆盖；门面 parity 测试不构造该病态输入。
- scipy cKDTree tie 序与 exactly-at-radius 边界无 oracle；本任务 pytest 不含 tie/边界齐平数据（与 frozen
  契约 "unique-distance neighbour sets" 一致）。
- geoviz 引擎 WLS 路径无 C++ 对应（见 decisions D7 的分流规则）；conv12 venv 无 geoviz，本地 parity 为全路径。
- extract 的 inf 坐标（"1e999"）：两面都在 GeologicalFactor.__post_init__ 抛 ValueError（Python float("1e999")=inf
  通过 try；C++ strtod 得 inf）——行为一致但无冻结案例；pytest 不新增该边。

## 10. 环境事实修正（审核轮发现）

- conv12 venv **有 geoviz**（editable 安装；早前 §7 探测遗漏）。生成器本就以
  `sys.modules["geoviz"]=None` 钉 numpy-grid-OLS，冻结不受影响；pytest 的 kriging parity 需要
  `no_geoviz` fixture 做同一 pin，否则纯路径走引擎 WLS、门面按 estimator 门控留纯路径（行为正确但
  C++ kriging 分支不被测）。
- conv12 venv 无 shapely：`tests/test_well_prediction_surface.py::test_point_to_surface_assigns_nearest_well_facies`
  在无扩展时同样 `ModuleNotFoundError: shapely`（polygonization clip 路径的既有环境限制；系统无 geos，
  无法廉价补装）。该失败与 CONV-20 无关，双态一致。
- pytest 8.4.2 + pluggy 1.6.0 + iniconfig 2.3.0 + pygments 2.19.2（github 克隆纯 Python 拷入
  site-packages；pluggy/_pytest 各需手写 `_version.py`；pytest 需 `src/py.py` 垫片）。
