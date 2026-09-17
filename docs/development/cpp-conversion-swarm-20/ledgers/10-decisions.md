# CONV-10 decisions — 非显然选择记录

1. **JSON 记录入参，而不是打类型结构体。** `representative_facies` 的 Python 输入是任意 dict
   （facies/label/name、top/bottom、probability/confidence、stratigraphic_unit/horizon 真值链回落）。
   若 C++ 收类型结构体，真值链语义会被推给调用方，冻结失真。故收 `pwb::domain::Json`
   （mapping_kernel 已依赖 Pwb::Domain，extract.cpp 先例），键回落语义 1:1 留在核内。

2. **多边形级 shapely 裁剪与 repair 不复制。** Python `point_to_surface_features` 的
   `generate_facies_polygon_layer(clip_ring=…)` 在多边形级做 `_clip_polygon_to_ring`
   （shapely intersection）与 `repair_invalid_geometry`（make_valid/orient）。已有 polygonization
   切片的冻结先例是 repair=identity、clip-to-ring 不移植（polygonization.hpp 头注）。
   本切片沿用：C++ descriptor 只复刻 clip_ring=None 的多边形路径；工区裁剪由
   `nearest_neighbor_class_grid` 的 grid 级 NaN 掩膜承担（class_grid_oracle 的 clip_square 已冻结）。
   与 Python 的已知差异 = 环边界格元阶梯不被二次修边，头注与 oracle notes 明示，不做半吊子求交。

3. **extent/clip_ring/crs 由调用方传入，而不是传 project。** Python 签名收 `project`
   （workarea.boundary / coordinate.project_crs）。C++ 核无域模型；`_extent_from_workarea`、
   `_clip_ring` 的纯核心以 `extent_from_workarea_boundary` / `clip_ring_from_boundary` 暴露，
   host 接线切片用它们构造参数。这与 crs_policy 切片「不接 interpolator」的分层纪律一致。

4. **`_task_regions`/`_spatial_point_features`/`point_features` 一并移植。** 用户流程验收是
   「区间记录 → 代表相 → 分类栅格 + GeoJSON 点要素」；`task_regions(summary)` 与
   `spatial_point_features(summary, task_id)` 是 result_summary→记录/点要素 的纯数据桥，
   每个约 20-30 行、与 Python 逐键对应，不做就会在 host 侧重 invent。私名去下划线转公开。

5. **`well_xy`/`_wells_for_task`/`_points_from_intervals`/`well_facies_points` 不移植。**
   依赖 `well_registry`/`entity_ids_for_asset`/`normalize_well_name` 域模型（project/domain.py），
   属 M10 UI/接线层；mapping_kernel 无井域模型，现在造即是投机抽象（Karpathy §2）。
   host 拿到 (xy, records) 后可直接调已移植的 `representative_facies`。

6. **`mean_val` 的 float32 语义。** Python `np.mean(float32 数组)` 返回 float32。C++ 以
   `(double)(float)(sum / n)` 复刻（格值是 0..n-1 的小整数 id，和与序无关精确，仅除法一次舍入；
   double→float 二次舍入在 id 量级与 numpy 逐位一致），再 `round_to(…, 4)` 后进属性。

7. **属性键型严格。** `json_semantically_equal` 对 int/float 类型敏感：facies_id 用整数，
   area/area_percent/mean_value/area_approx_m2 用 double（Python round 总返 float），
   coordinates/geometry 数值全 double。point_features 的 probability/thickness 为 None 时
   键缺席而非 null（Python 条件插入）。

8. **geographic CRS 的 `area_approx_m2` 全量移植。** 常量 111320.0、scale =
   `(111320*cos(radians(Σy/n)))*111320`、按环外减洞，表达式顺序与 geometry_units.py 逐位一致
   （同机 libm，cos/radians 位同）。oracle 以 EPSG:4326 案例钉住；CRS 判定用已冻结的
   `crs_is_geographic`（EPSG:4326 在 builtin 表）。

9. **oracle 全部跑真实 Python。** 生成器 import 真模块；私有函数（`_task_regions`、
   `_spatial_point_features`、`point_features`、`_extent_from_points`、`_extent_from_workarea`、
   `_clip_ring`）直接 import 调用；`point_to_surface_features` 案例按 polygonization 切片先例
   monkeypatch `repair_invalid_geometry` 为 identity 并只用 clip_ring=None 的 project
   （SimpleNamespace 造 coordinate/workarea）。**无手写期望值**。

10. **`_finite` 字符串解析的范围。** `float(str)` 的十进制/指数/空白/±inf/nan 词被复刻
    （isfinite 过滤后 inf/nan → None）；Python 3.6+ 的下划线数字字面量（"1_000.5"）不在 JSON
    域出现，不复刻（findings 已记）。probability="abc" 真值但解析失败**不**回落 confidence
    （Python 先选值后 _finite），C++ 同序——oracle 有专案。

11. **CMake 门。** 本分支无既有 CONV 块；`libs/mapping_kernel/CMakeLists.txt` 追加
    `# BEGIN CONV-10`：`option(PWB_BUILD_CONV_10 …)` + `target_sources(pwb_mapping_kernel PRIVATE
    src/representative_facies.cpp)`；`mapping_kernel_tests/CMakeLists.txt` 追加对称块注册
    `mapping_kernel.representative_facies`。OFF 时既有源列表与测试集零变化；不触其他块。

12. **空点 `extent_from_points` 前置条件。** Python 空表会从 `min()` 抛 ValueError；
    C++ 显式 `std::invalid_argument`（仅内部守卫，oracle 不钉文案——Python 文案是解释器实现细节）。
    `point_to_surface_features` 的 `len<1 → []` 在 C++ 入口先行，恒不触发该守卫路径以外暴露。

13. **返回类型用 `std::pair<Json, Json>`。** Python 两函数都返 `list[(geometry, properties)]`
    （surface 版剥掉 Feature 包装、properties 带 source）。C++ 不另造 descriptor 结构体——
    pair 即 Python 元组，ordered_json 保键序，少一层映射。

## 审核轮后追加（2026-09-18）

14. **真值非 dict 的 properties：按丢弃处理（Python 是 dict() 强转或抛错）。**
    Python `dict(record.get("properties") or {})` 对 `properties: [["facies","A"]]`/`"ab"`
    会强转（甚至产出点），对不可强转值抛 TypeError/ValueError。C++ 一律视为空对象 → 记录被
    facies 过滤丢弃。属 JSON 域外的病态输入，头注已写 "dropped, never errors"，此处记录为
    已知偏离，不实现 dict() 强转。

15. **float(str) 的保真边界（审核后修订 #10）。** 现已复刻：PEP 515 下划线数字（"1_0"）、
    strtod ERANGE 容忍（下溢 0.0/次正规、上溢 ±inf，与 Python float() 同值；inf 再被
    isfinite 过滤）。保持不复刻并在此声明：Unicode 十进制数字位（float("１２３")）——
    有界实现，与 name_search 的 ASCII 折叠先例同一纪律。inf/infinity/nan 词在解析层拒绝，
    终态与 Python 一致（_finite(inf/nan) 均为 None）。

16. **strip() 升为 UTF-8 码点级 Python isspace 集。** 审核指出全角空格 U+3000 在中文相名
    真实存在（如 "　三角洲"），ASCII strip 会让同一相分裂成两团。现按 str.isspace() 全集
    （含 \x85、\xa0、U+2000-200A、U+3000 等）解码匹配；oracle 以
    ideographic_space_strips_like_python 钉住。

17. **地理近似面积累加顺序对齐 Python（外环先加、洞按序减）。** 审核发现洞先减的顺序在
    浮点不可结合下可差 1 ulp；已改序并用新案例 geographic_island_holes（地理 CRS × 有洞
    多边形组合）冻结，不再是 oracle 未触路径。

18. **已知未冻结分支（两条，均记录）：** (a) 全格 NaN 的 any_finite 早退——需要 ring 才能触
    发，而带 ring 的多边形级输出被 #2 排除；格级 ring 路径已由 class_grid_oracle 的
    clip_square 冻结。(b) surface 案例不含 min_area/颜色自定义路径——point_to_surface 调用
    点不传这些参数（Python 默认值），移植面如实收窄。

19. **后续（本切片不做）：** extract.cpp 已有 file-local strip/py_truthy（write-scope 禁改），
    第三份出现时提共享内部头；PWB_BUILD_CONV_10 目前仅 opt-in，接入 integrated gate/preset
    属集成切片的显式跟进项。
