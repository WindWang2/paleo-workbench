# CONV-33 实现账本 — 路线 A1（qc.py + map_qa_rules.py 移植）

分支 `feat/cpp-workflow-orchestration`（worktree `../worktrees/cpp-workflow-orchestration`）。
契约 = 33-findings §A1/§E + 33-decisions D1-D8 + 冻结头
`libs/workflow_runtime/include/pwb/workflow_runtime/{qc,map_qa_rules}.hpp`（未改动）。

## 交付物

| 文件 | 内容 |
|---|---|
| `libs/workflow_runtime/src/qc.cpp` | qc.py 全量实装（除协调者预置的 active_quality_reports，见下） |
| `libs/workflow_runtime/src/map_qa_rules.cpp` | map_qa_rules.py 全量实装 |
| `tools/oracle/generate_workflow_qc_fixtures.py` | 真 Python oracle 生成器（冻结时钟/id 缝） |
| `libs/workflow_runtime/workflow_runtime_tests/fixtures/workflow_qc_oracle.json` | 51 例冻结 fixture（生成器落盘，重跑字节一致） |
| `libs/workflow_runtime/workflow_runtime_tests/qc_test.cpp` | 冻结 replay + 负向自检 + C++ 缝专项检查 |

## 作用域表（Python → C++ parity）

| Python 符号 (行) | C++ 符号 | parity 注记 |
|---|---|---|
| `make_issue` (L27) | `make_issue(rule, severity, message, QcIssueFields)` | 键序 rule/severity/message/feature_id/feature_kind/ref/geometry/centroid/extra 平铺；`if extra:` 空对象跳过，extra 覆盖同名键 |
| `_geometry_centroid` (L60) | `geometry_centroid`（file-local） | 三级兜底链逐字：facade → ValueError→顶点均值 → TypeError/IndexError/KeyError→无定位点。异常类别以 `CentroidErr{kValue,kType}` 建模 |
| `_vertex_mean_locate_point` (L77) | `vertex_mean_locate_point` | Point 拒绝；`_iter_points` 递归：≥2 且 [0]/[1] 为数值（含 bool≈int）为叶，否则递归子节点；空→None |
| `from geoviz import validate_ring` (L198) | `ring_has_self_intersection`（file-local） | 见下方 sourcing 决策。只消费 `code=="self_intersection"` 存在性（L200-201 语义） |
| `_facies_ring` (L104) | `facies_ring` | 环/多边形坐标/geometry.Polygon 三形态 + 首元素为数字→None（含 bool）；返回指针避免拷贝 |
| `_ring_to_polygon_geometry` (L122) | `ring_to_polygon_geometry` | float 归一 + 未闭合补首点（精确浮点比较） |
| `_count_contour_lines` (L129) | `count_contour_lines` | role 或 properties.role/constraint_role == "contour"（truthy-or 链逐字） |
| `_collect_issues` (L142) | `collect_issues` | 六规则中文消息逐字（自 qc.py 抄录，未冻结在头）。井表层位过滤（双方非空才比对）；`feature_id=fid or None`；`qc_z_star` 原样透传；`row.x/y` 经 `parse_float_like`（模型侧不可缺失，Json 缝防御分支=L260-261 的 except） |
| `spatial_issues` (L278) | `spatial_issues` | 与 ui_review `spatial_issues_of` 同语义（truthy geometry/centroid），返回 Json 数组 |
| `issue_layer_geojson` (L289) | `issue_layer_geojson` | report None→无 properties 键；centroid-only issue 不出 Feature（无 dict geometry）；`map_document_id or report.linked_...` |
| `_status_from_issues` (L329) | `status_from_issues` | severity 小写化集合；error/critical→error，warning→warning，else pass |
| `run_basic_qc` (L338) | `run_basic_qc(Json& project, id, bind, QcRunDeps)` | 未知文档→`std::invalid_argument("unknown map document: ...")`（ValueError parity，replay 断言 class+message）；稳定 id upsert（首匹配 linked_map_document_id，id 空则重盖章）；`provenance_registered` 先 False；sink 调用发生在 flag 翻转**前**（report_json 携带 False = Python 临时文件 dump 时点）；null sink ≙ get_catalog()→None（无注册，可见 False）；异常全吞（broad except parity）；活动 run 绑定 stamped via `deps.clock.now_iso()`；coverage {evaluated:6, skipped:0} |
| `active_quality_reports` (L462) | 协调者预置，**保留原样** | A1 复核结论：悬空 active id 落 by_map、by_map 首见键序+后值覆盖、空串 active id 等价路径均与 Python 一致（fixture 5 例覆盖）。首写此文件时误删、后逐字恢复（coordinator 注意：qc.cpp 中该函数体与轮1 种子逐字相同） |
| `run_map_qc` (L475) | `run_map_qc(..., MapQcInputs, QcRunDeps)` | 先跑 base（盖章+upsert+绑定）再收集扩展；merged = base.issues + extended；rule_status = 6 basic 全 evaluated + 9 条 coverage（**composition_incomplete 不进 rule_status**，Python 同：coverage dict 仅 9 键，coverage 合计 15）；id 取 upsert 后首匹配槽 id（=base id）；provenance_registered 继承 base |
| map_qa_rules `_layer_crs_issues` (L56) | `layer_crs_issues` | 图面未声明（map_crs None/""→""）；图层未声明/与图面不一致（图面空不比对）；label 用 `str(layer.name)` |
| `_renderer_class_issues` (L95) | `renderer_class_issues` + `check_categorized_style` | renderer=="categorized"；field_name=`str(style.field or 默认)`（图层默认 ""→跳过，相带默认 "facies_name"）；categories 支持对象键/`[值,...]` 列表首元素；present 值 `is not None`（0/""/false 计入）；missing 排序=码点序（UTF-8 字节序一致）；**消息内 `{missing}` = Python list repr**（`['石灰岩', '砾岩']`，`repr_str` 单引号），`（N 项无法按样式呈现）` 全角括号；extra {missing_classes(排序数组), field}；label 尾随空格逐字（"图层 X 分类样式…" / "相带面 分类样式…"） |
| `_extent_issues` (L164) | `extent_issues` + `flatten_coords` | map_extent（C++ optional 有值≙非 None）或 view_state.extent；len≠4 跳过；越界判定严格 `<xmin or >xmax...`；每要素首越界点即 break；feature_id 三级兜底 `feature_id or id or f"{kind}_{index}"`；越界 issue 携带原 geometry（可能 {}）；`.2f` 格式 = `fmt2`（glibc 正确舍入 = CPython） |
| `_data_health_issues` (L258) | `data_health_issues` | 井表按 id 字典；`well_table_id` 空串跳过；空 rows（含键缺失≙空）→ well_table_empty；`status=="complete"` 且无 truthy `grid_artifact_version_id` → stale_inputs；known_refs 三类解释并集；map_products 逐 ref 比对 → broken_external_reference（extra.product） |
| `_confidence_issues` (L310) | `confidence_issues` | 空/缺 stats→[]；min 数值（含 bool≈int）< threshold 触发；消息 `.2f`；extra {confidence_min: float(min), confidence_mean: 原样（可 null）, threshold: float} |
| `_export_issues` (L338) | `export_issues` | engine∈{fallback, composer_fallback} 或 truthy degraded；reason=`degraded_reason or "未说明"`；中文消息逐字（含破折号"——"） |
| `collect_extended_qc_issues` (L355) | 同名 | 六组顺序拼接（crs→renderer→extent→health→confidence→export） |
| `extended_rule_coverage` (L376) | 同名 | 6 常评 + 3 条件（optional 有值 / Json 非 null）；跳过原因中文逐字（头注释冻结） |
| `composition_qa_issues` (L416) | 同名 | Json 输入 = MapCompositionDocument.to_dict 形态（Python 侧跑真 dataclass——dict 直入 getattr 会全缺，故生成器对拍对象、冻结 to_dict 形态给 C++，语义等价：visible 缺省 true、element_type 已是 `.value` 字符串）；三必选组件中文标签逐字 |
| `cartographic_issues` (L446) | 同名（delegate 注入） | D7 薄委托：直接 `delegate(project, inputs)`，不复述 CARTOGRAPHIC_QA_RULES |

## validate_ring / centroid sourcing 决策

libs/ 内**无**可直接消费的 C++ 对应面：
- ui_review `qc_issue_rows.cpp` 只镜像了 `spatial_issues` 的 truthy 判定（不含 validate_ring/centroid）；
- mapping_kernel polygonization 未导出头给 workflow_runtime（引入会加一条 lib 依赖，越出冻结契约）；
- geoviz `map_edit` 的 C++ 扩展（`_cpp_fn("validate")`）属 geo-viz-engine 原生树，不在 libs/。

因此按任务预案把两个纯谓词作为 **file-local 最小移植** 收进 qc.cpp，语义源：
1. `ring_has_self_intersection` ← `geo-viz-engine/packages/geoviz_plots/geoviz_plots/map_edit/api.py`
   `_validate_ring_python` + `_ring_points_and_edges` + `_segments_properly_intersect`
   （<4 点/非列表→无 issue；闭合=首尾精确相等；邻接边（共享顶点索引）跳过；首次相交短路；collinear-overlap 计入；`b1 not in (a1,a2)` = 精确浮点相等；`float(p[0])` 数值/可解析字符串）。
2. centroid facade ← `paleo_workbench/mapping/geometry_operations.py::centroid`，内核
   `geological_pipeline/polygonization.py::calculate_signed_area / ring_area_centroid`
   （Point 自身；线=顶点均值；面/多面=shoelace 面积质心 + 洞减面积**减矩**；`part_area>0` 才累计；`area_total<=0`→ValueError→兜底；`math.isclose(area2,0,abs_tol=1e-12)` 含默认 rel_tol=1e-9 精确复刻；非退化短环回退首顶点）。

## deviations（均为不可达/契约外形差异，附依据）

1. **map_extent 类型外形**：Python 可传任意长度 `map_extent`（len≠4 时 coverage 仍 evaluated=True 但不发 issue）；冻结头为 `optional<array<double,4>>`，无法表达畸形长度 —— fixture 不含畸形长度（契约外形不可表达，越出冻结契约）。
2. **崩溃路径**：Python 在 extent 元素不可 float（`float("abc")`）或 categories 为裸数字（`c[0]`）时**抛异常**；C++ 对前者抛 `std::invalid_argument`（保持失败、不猜），对后者跳过该项。fixture 均未触及。
3. **几何类型的深角落**：coordinates 为字符串/数字等非数组形态时，Python 的 str/int 下标行为（如 `"ab"[0]`→ValueError→兜底、`list(5)`→TypeError）在 C++ 以 `CentroidErr::kType` 统一归"无定位点"；两者最终可观测结果（有无 centroid）一致，但异常类别路径不可逐类对拍。fixture 未含此类输入。
4. **confidence_threshold 类型**：MapQcInputs 为 double；Python 传 int 时 extra 里存 int（`1` vs C++ `1.0`）。生成器恒传 float（0.5/0.75/0.9），类型面一致。
5. **非对象 facies/line 元素**：Python `(feature or {})` 只兜 None，truthy 非字典会 AttributeError；C++ 按空对象处理。模型侧 dump 恒为字典，不可达。
6. **run_qc 数据形状**：QcProvenanceSink 的 C++ 等价面把"临时文件 OUTPUT 注册"收敛为缝实现侧职责（头注释裁决）；sink 收到的 `report_json` 携带 `provenance_registered=false`（与 Python 临时文件 dump 时点一致）。

## 负向自检清单（qc_test.cpp `comparator_self_check`）

对真实冻结例 `mapqc.all_skip_inputs` 的期望输出在内存篡改 3 处，断言比较**必败**：
1. `report.status` → "pass"；
2. `report.coverage.skipped` → 1（整数篡改）；
3. `issues[3].message` → "篡改的消息"（中文逐字消息守卫）。
结果：3/3 被抓（`comparator self-check: OK (3 tampers caught)`）。

另有 C++ 缝专项（Python 类型化模型不可达，直接断言，非冻结对拍）：
- sink 成功注册 → `provenance_registered=true` + 缝载荷（name=`QC <doc.name>`、source_task_ids=[doc.id]、domain_task_id=linked_prediction_task_id 回退 doc.id、parameters={map_document_id, qc_status}、report_json.id 一致且 flag=false）；
- sink 返回 nullopt → false；sink 抛异常 → 不逃逸且 false；
- 井表行缺 x/y（Json 缝防御分支）→ 非空间 issue（无 geometry/centroid）；
- cartographic delegate 转发同一性（project/inputs 原样到达 + 返回值直传）。

## 验证记录

- 生成器：`QT_QPA_PLATFORM=offscreen /tmp/pwb-oracle-venv/bin/python tools/oracle/generate_workflow_qc_fixtures.py`
  → 51 例；重跑 `diff` 字节一致（确定性：显式 id/时间戳 + `pm.datetime` 冻结子类 + `pm._id` 顺序工厂，冻结时钟随 case 记录进 `input.clock` 供 C++ `ModelClock` 注入）。
- fixture 分布：make_issue 13 / run_basic_qc 8 / active_quality_reports 5 / run_map_qc 10 / collect_extended 2 / extended_rule_coverage 4 / composition 4 / spatial 2 / issue_layer_geojson 3（含 2 例 raise parity：basic+mapqc unknown doc）。
- 构建：`cmake -S . -B /tmp/conv33-a1-build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DPWB_BUILD_CONV_33=ON -DPALEO_QGIS_{SOURCE,SDK,BUILD}_DIR=...`；
  `cmake --build /tmp/conv33-a1-build -j3 --target workflow_runtime_qc_test pwb_workflow_runtime` 通过。
- ctest `workflow_runtime\.qc` **两次全绿**（51 cases / 56 checks，含负向与缝自检）；附带
  `workflow_runtime.contracts` 无回归（同 lib 链接）。
- `g++ -std=c++20 -Wall -Wextra -Werror -fPIC -fsyntax-only`（include 集 + `-Ilibs/factor_host/include`，python_compat.hpp 传递依赖）：
  qc.cpp / map_qa_rules.cpp / qc_test.cpp 三个 TU 零警告。

## 给协调者的注意项

1. **qc.cpp 的 `active_quality_reports` 在 A1 首版误删后已逐字恢复**（与轮1 种子相同）——review 时无需对照其他副本，其 parity 由 fixture 5 例背书。
2. A2/A4 并发改动 service/versioning/orchestrator/recipe 等文件，与 A1 文件集零交集；A1 期间其文件曾处于中间态，A1 的 lib 构建仅依赖自己 TU 编译通过即链接成功，未受阻塞。
3. `_renderer_class_issues` 的 `missing` 列表 repr 依赖 `pycompat::repr_str`（单引号 Python repr）——若后续有人在消息里遇到带 `'` 的类目名，repr 会切双引号（Python 行为，已由 repr_str 承载）。
