# 02-findings — MapDocument / Composer 数据契约（cpp-conv-02）

基线 `35987e13`。本文按 §5 清单逐文件全文通读后写成；每个公开符号给出：
输入 / 输出 / NaN-空-并列边界 / 与既有 C++ 核（mapping_kernel、domain json）的关系 / 测试缺口。
「契约」= Python 产品码的**实际行为**（不是 docstring 声称的行为；两者的偏差单独标注）。

---

## paleo_workbench/mapping/layers.py（716 行，全文已读）

### LayerType(str, Enum)
- 输入/输出：10 个字符串枚举值 vector/grid/contour/well_point/polygon/facies/raster/scalar_grid/raster_source/annotation。
- 契约：仅作类型词汇表；`to_dict` 写出的 `layer_type` 来自**类字段默认值**而非本枚举（见各类）。`facies`/`raster`/`scalar_grid` 三个值没有对应 to_dict 输出类（`from_snapshot` 的路由词表才用它们）。
- C++ 关系：C++ 用 `layer_type` 字符串分类 family，不移植枚举本身。
- 测试缺口：无独立测试（challenger 测试断言 7 类覆盖）。

### _generate_layer_id(prefix="layer") → f"{prefix}_{uuid4().hex[:8]}"
- 随机 id 生成器。MapLayer 默认 `lyr_XXXXXXXX`，MapDocument 默认 `map_XXXXXXXX`。
- NaN/空：无。并列：无。
- C++ 关系：**不移植**（随机性）。C++ 读取缺 id 时记 `""`（决策 D-04）；oracle fixture 一律固定 id。
- 测试缺口：随机性不可冻结，fixture 不覆盖。

### MapLayer（ABC dataclass，基类）
- 字段与默认：`id`（随机）、`name="Untitled Layer"`、`layer_type="vector"`、`extent=(0.0,0.0,1.0,1.0)`（哨兵值！）、`crs=""`、`data_revision=1`、`style_revision=1`、`visible=True`、`opacity=1.0`、`scale_range=None`、`style={}`、`metadata={}`、`source_version_id=""`。
- `bump_data_revision()/bump_style_revision()`：自增并返回新值；`set_visible(v)` 调 `bool(v)` 并 bump style；`set_opacity(o)` 钳制 `max(0,min(1,float(o)))` 并 bump style。
- **to_dict 键序（13 键，全量写出）**：id, name, layer_type, extent(list), crs, data_revision(int), style_revision(int), visible(bool), opacity(float), scale_range(list|None), style(dict 浅拷贝), metadata(dict 浅拷贝), source_version_id。
- 空边界：extent 哨兵 `(0,0,1,1)` 被 MapDocument.recompute_extent 排除聚合；`opacity` 钳制负值→0、>1→1；NaN opacity 经 max/min 传播为 NaN（Python 行为，fixture 不用）。
- C++ 关系：本任务核心——13 键写入契约 + family 化的 features/annotations 扩展键；style/metadata 作为 ordered_json 原样透传。
- 测试缺口：challenger 测试只测 7 类 JSON 可序列化，未测键序（C++ 以 ordered_json 保守复刻键序）。

### VectorMapLayer(MapLayer)
- `layer_type="vector"`；`features: tuple[Mapping,...]`（GeoJSON Feature dict）。
- `__post_init__`：style 为空 → `default_style_for("line").to_dict()`（真实产品默认样式，冻结进 fixture 的就是它）；features 非空且 extent 仍是哨兵 → `recompute_extent()`。
- `set_features`：重建 tuple → recompute_extent → bump data_revision。
- `recompute_extent()`：走 `geometry_planar.extent_of_geometries` 共享内核（mapping_kernel 邻域，**只读不改**）；空/全非法 → ValueError → extent 重置哨兵；退化线（min==max，math.isclose）按 `max(1,|max|)*1e-6` 垫宽。
- to_dict：super 13 键 + `"features": [dict(f)…]`（第 14 键，永远写出，可为 []）。
- C++ 关系：features 原样透传；recompute_extent 的图层级版本**不在本核**（C++ 只做文档级聚合，见 MapDocument.recompute_extent；feature 级 extent 计算依赖 geometry_planar，属另一切片）。
- 测试缺口：垫宽 1e-6 的精确值无 C++ 对账（feature 级内核未在本任务范围）。

### GridMapLayer(MapLayer)
- `layer_type="grid"`；`grid_result`/`grid_z`/`grid_x`/`grid_y`（ndarray）、`color_ramp_name="viridis"`、`value_range=None`、`unit=""`、`nodata=NODATA`（`workflow.factor_grid_result.NODATA == nan`，已实跑确认）。
- `__post_init__`：有 grid_result → `_sync_from_grid_result`（extent/statistics.value_range/CRS/unit 回填）；否则有 z/x/y → extent=min/max 轴包络 + finite 值域；style 为空 → **烘焙** `{"color_ramp","value_range"(list|None),"unit","opacity"}`（键序固定）。
- `_sync_from_grid_result`：`crs = result.crs or self.crs`（falsy 回退）、`unit` 同理；statistics.min/max 均 finite 才写 value_range（NaN 不传播）。
- set_color_ramp/set_value_range：同步 style 内对应键并 bump style_revision。
- rasterize_rgba：渲染路径（色带 LUT 256 级），**非数据契约，不移植**。
- **to_dict：无 override** → 只写基类 13 键；网格数组、nodata、color_ramp_name 字段全部**不入 JSON**（值经由 style 烘焙间接体现）。这是最重要的契约事实。
- C++ 关系：grid 图层 JSON 与基类同形；`"scalar_grid"` 是 snapshot 层型，不出现在 to_dict。
- 测试缺口：test_geological_mapping_pipeline 断言 layer_type 顺序含 "grid"；fixture #3/#4 覆盖烘焙后的 style 形状。

### ContourMapLayer(VectorMapLayer)
- `layer_type="contour"`；`levels: list[float]`、`contour_interval: float|None`、`show_labels: bool=True`。
- `__post_init__`：style 空 → `default_style_for("contour").to_dict()`，且若无 labels → 烘焙 `TextStyle(field="level", size=8.0, color="#f8f9fa").to_dict()` 进 `style["labels"]`；再调 super（line 默认不会覆盖，因 style 已非空）。
- **levels/contour_interval/show_labels 不入 to_dict**（无 override；features 走 VectorMapLayer）。
- C++ 关系：JSON 同 vector family；levels 只活在构造期（pipeline fixture 冻结 features 里的 level 属性）。
- 测试缺口：`levels` 值在 JSON 中仅出现于 feature properties.level；fixture 用 pipeline 真实产出。

### WellPointMapLayer(VectorMapLayer)
- `layer_type="well_point"`；`factor_name=""`、`unit=""`（均不入 to_dict）。
- `__post_init__`：style 空 → 硬编码 VectorStyle(fill="#22b8a7", stroke="#182431", stroke_width=1.0, marker=WELL, marker_size=8.0, labels=TextStyle(field="name", size=9.0, color="#ffffff")).to_dict()。
- pipeline.create_well_point_layer 另行构造自己的 style（halo_color="#000000"），覆盖类默认——fixture 用 pipeline 路径。
- 测试缺口：类默认 vs pipeline 默认两套样式并存；fixture 固定用 pipeline 版本，类默认仅经 7-layer challenger 构造路径出现（fixture #21 registry 默认不涉及）。

### PolygonMapLayer(VectorMapLayer)
- `layer_type="polygon"`；`categories: list[dict]`（不入 to_dict）。
- `__post_init__`：style 空 → `default_style_for("facies").to_dict()`。
- from_snapshot 把 snapshot 层型 `polygon|facies` 都路由到本类（layer_type 字段仍是 "polygon"）。

### AnnotationMapLayer(VectorMapLayer)
- `layer_type="annotation"`；`annotations: tuple[Mapping,...]`。
- `__post_init__`：style 空 → `default_style_for("annotation").to_dict()`（含 rotation_field/size_field/color_field 数据定义绑定）；有 annotations 且无 features → `_sync_features_from_annotations`。
- `_sync_features_from_annotations`：每条 ann → GeoJSON Point feature：id=`str(ann.get("id", f"ann_{idx}"))`、coordinates 取 x/longitude、y/latitude（float()）、properties=dict(ann) 且 setdefault("text")。
- `add_annotation(text,x,y,font_size=10.0,color="#f8f9fa",rotation=0.0,**kwargs)`：id=`ann_{uuid4().hex[:6]}`（随机——fixture 冻结实际产出）；同步 features + recompute_extent + bump data。set_annotations/clear_annotations 同理。
- **to_dict：super（13 键 + features）+ `"annotations": [dict(a)…]`（第 15 键，排在 features 之后）**。
- 空边界：annotations 与 features 同时存在的 JSON（手工构造）→ 两键都透传；C++ 不做同步（决策 D-06）。
- 测试缺口：challenger create_sample_annotation_layer 覆盖；无 id 冲突测试。

### RasterMapLayer(MapLayer)
- `layer_type="raster_source"`；`source_path=""`。
- **to_dict 无 override → source_path 完全不入 JSON**（连同基类 13 键写出）。C++ 端绝不能「聪明地」补 source_path 键。
- to_snapshot 特有（renderer_payload=source_path），非本核。

### MapDocument
- 字段默认：`id`（随机 map_XXXXXXXX）、`title="Paleogeographic Map"`、`crs="EPSG:4326"`、`extent=(0,0,1,1)`、`layers=[]`、`metadata={}`、`active_layer_id=None`。
- **to_dict 键序（7 键）**：id, title, crs, extent(list), layers(list), metadata(dict), active_layer_id(None|string)。无 schema_version（对比 composition 有）。**无 from_dict**——Python 没有加载器，读侧契约是本任务 C++ 的定义点（决策 D-03）。
- `input_version_ids` property：`list(metadata.get("input_version_ids") or [])` + 逐层 `source_version_id` 去重（保序，首个出现者胜）。
- `run_id` property：metadata["run_id"] 的 get/set。
- `add_layer(layer, position=None)`：position 在 [0, len] 则 insert 否则 append；`active_layer_id` 为空（None/""）时设为该层 id；然后 recompute_extent；返回 layer。
- `remove_layer(id)`：命中则 pop；若是 active → 改为 `layers[0].id`（删后首层）或 None；recompute_extent；未命中返回 None（无异常）。
- `get_layer(id)`：线性查找，未命中 None。
- `reorder_layers(ids)`：先建 `id_to_layer` dict（**同 id 层重复时保留最后一个**），按给定序列 pop（未知 id 忽略；请求序列中的重复 id 第二次是**静默跳过**，不是异常），剩余层按 dict 插入序（=各 id 首现顺序、每 id 一个）接尾。审核轮 2 更正：初版误记为「第二次 KeyError 会抛异常」——实测 Python 静默跳过。
- `recompute_extent()`：聚合 `visible=True` 且 extent 存在、长度 4 且 **!= 哨兵 (0.0,0.0,1.0,1.0)** 的图层 extent 的 min/max；无有效层 → 保持 self.extent 不变。注意是精确元组不等比较。
- 空边界：layers 全不可见/全哨兵 → extent 不动；active_layer_id=""（空串）在 add_layer 时视为「未设置」被覆盖（falsy 判断）。
- 并列：多文档无交互；同 id 两层 get/remove 取第一个。
- C++ 关系：add/remove/get/reorder/recompute/input_version_ids 全部移植为纯数据操作；逐 op 冻结 Python 结果（fixture ops 表）。
- 测试缺口：pytest 无 MapDocument 增删重排的直接单测（challenger 并发测试隐式覆盖）；C++ oracle ops 表补上（fixture #14–#18）。

---

## paleo_workbench/mapping/composer/（7 文件 2993 行，全文已读）

### composer/models.py

#### COMPOSITION_SCHEMA_VERSION = 2
- to_dict 顶层写 `"schema_version": 2`；from_dict **忽略** payload 的 schema_version（输入 7 → 重写 2）。

#### ElementType(str, Enum)（24 值；审核轮 2 更正：初版误记 25）
- main_map, legend, north_arrow, scale_bar, grid, title, annotation, timescale, text, image, inset_map, stat_chart, metadata, colorbar, neatline, datasource, time_credits, fault_symbols, facies_legend, lithology_legend, strat_labels, subtitle, well_legend, profile。
- to_dict 写 `.value` 字符串；未知字符串进 from_dict 的 TEXT 载体（下）。

#### ELEMENT_PROPERTY_KEYS
- 每 element type 的规范属性键表（文档性词汇表，非校验）。C++ 不移植（properties 是开放 dict 原样透传），仅注释引用。

#### _new_element_id / ComposerElement
- id 默认 `el_{uuid4().hex[:10]}`。
- 字段：id, element_type, x_mm, y_mm, width_mm, height_mm, z_index=0, visible=True, locked=False, properties={}。
- **to_dict 键序（10 键）**：id, element_type, x_mm(float()), y_mm, width_mm, height_mm, z_index(int()), visible(bool()), locked(bool()), properties（先逐值递归 `_serialize_property_value`，再 `pop("_raw_element_type")`；若弹出值非 None 且 element_type is TEXT → element_type 写弹出的 raw 值）。
- **_serialize_property_value**：MapDocument → `{"__ref__":"map_document","id":…,"layer_count":len(layers)}`；MapLayer → `{"__ref__":"map_layer","id":…,"layer_type":…}`；dict/list/tuple 递归（tuple→数组）；str/int/float/bool/None 原样；其余 `str(value)`。
- **from_dict 容忍语义（逐键）**：
  - element_type：`str(payload.get("element_type") or "text")`；不在枚举 → 载体 TEXT，且 `raw_type != "text"` 时 `properties.setdefault("_raw_element_type", raw_type)`（已存在不覆盖）。
  - id：`str(payload.get("id") or 随机)`（空串/None/0 → 随机！fixture 固定 id 规避）。
  - x/y_mm：`float(payload.get("x_mm") or 0.0)` —— falsy（None/0/0.0/""/False）→ 0.0；truthy 字符串走 float()（可解析字符串 "12.5" → 12.5；不可解析 → **抛 ValueError 未捕获**）。
  - width/height_mm：同式默认 **1.0**（注意 `0` 输入 falsy → 1.0，是真实 quirk，fixture 冻结）。
  - z_index：`int(payload.get("z_index") or 0)`（falsy → 0；"3" → 3；2.7 → 2 截断）。
  - visible/locked：`bool(payload.get("visible", True))` —— **get 带默认，非 or**：缺键 → True；`false`/`0`/`""`/None → False；字符串 `"0"`/`"false"`（非空）→ **True**（bool(str) 真值语义）。
  - 未知顶层字段（如未来 rotation_mm）：**静默丢弃**（docstring 声称 preserved，与实现不符——C++ 按 §7.4 改为 extras 保真，见决策 D-08）。

#### PAPER_SIZES_MM
- A5 (148,210) / A4 (210,297) / A3 (297,420) / A2 (420,594) / A1 (594,841) / A0 (841,1189)（短边×长边，portrait 语义）。

#### MapCompositionDocument
- 字段默认：id、title、paper_size="A4"、orientation="landscape"、width_mm=297.0、height_mm=210.0、dpi=300.0、elements=[]、metadata={}（dict[str,str] 注解但不强制）。
- **to_dict 键序（10 键）**：id, title, paper_size, orientation, width_mm, height_mm, dpi, schema_version(=2, int), elements(list), metadata(dict)。注意 width/height/dpi **原样写出不 float() 包装**——dataclass 里已是 float；fixture 保证浮点。
- `add_element`：append 后 `sort(key=z_index)`（**Python stable sort**；同 z 保持插入序——fixture 冻结平局序）。
- `get_element`：线性查 id。
- `set_paper(paper,orientation)`：`PAPER_SIZES_MM.get(str(paper).upper())`，未命中 **raise ValueError(f"unknown paper size {paper_size!r}")**（!r 是 Python repr：`'b5'`）；portrait → (short,long) 否则（任何非 "portrait" 字符串）→ (long,short)；paper_size 存大写；orientation 原样存储。
- **from_dict**：paper/orientation/title 用 `str(x or default)`；width/height/dpi 用 `float(x or default)`（0 → 默认！）；elements 逐 Mapping 走 ComposerElement.from_dict，非 Mapping 项跳过；末尾 `sort(z_index)`（stable）；`metadata = dict(payload.get("metadata") or {})`（**metadata 独立于顶层 extras**——顶层未知键被丢弃，schema_version 不回读；「roundtrips are byte-identical for documents created in-process」只对无未知键文档成立）。

### composer/registry.py
- CATEGORY_BASIC/GEOLOGICAL/CHART = "basic"/"geological"/"chart"；CATEGORY_LABELS 中文名。
- **CHART_COLOR_SEQUENCE**：6 色 `("#4c78a8","#f58518","#e45756","#72b7b2","#54a24b","#eeca3b")`——渲染消费，非文档序列化契约；不移植（决策 D-10）。
- CHART_SERIES_SCHEMAS：8 种 chart_type 的数据形态中文描述（UI 提示用）；不移植。
- PALETTE_ALIASES：lithofacies-v1→jet、paleogeographic-v1→water_depth；resolve_palette → color_ramps（色带内核不属于数据契约；不移植）。
- **ComponentSpec + _build_registry + _REGISTRY**：24 个 ElementType 全量注册（label、category、default_geometry、default_properties、property_schema、renderer_key）。get_spec 未知 → **TEXT spec 降级**（与 from_dict 载体一致）。all_specs/categories 保注册序。
- C++ 关系：registry 的 default_properties 在 fixture #21 中经 CompositionFactory 真实烘焙后冻结（tuple→数组），C++ 只透传 JSON。
- 测试缺口：test_composer_registry 全面覆盖（每个 type 有 spec、默认几何为正、未知降级）；C++ 侧仅对账序列化形状。

### composer/components.py
- DEFAULT_GEOMETRY_MM / DEFAULT_PROPERTIES：registry 视图（deepcopy）。
- ComposerError(RuntimeError)：消息 `f"composition element {id!r} is locked; unlock it before move/scale/configure/remove/duplicate"`（!r → `'el_x'`）。
- **CompositionFactory**：create（registry 默认几何/属性 merge 覆盖）、create_document（`comp_{uuid}`+set_paper）。
- **CompositionEditSession**：命令模式 add/insert/remove/move/scale/configure/duplicate/set_locked/set_element_visible/bring_to_front/send_to_back/raise + undo/redo + revision 计数；scale 校验正尺寸（ValueError "component size must be positive"）；locked 拒绝变更（ComposerError，拒绝不产生历史）；bring_to_front= max z+1、send_to_back= min z-1；undo/redo 各 +1 revision。
- **bind_template**：对每个 element 的 `properties["data_binding"]={"key":…, "fields":[…]}` 从 binding_context 取 updates（deepcopy merge）；fields 过滤；未命中键原样保留；返回 resolved 计数。
- **bind_map_documents**：MAIN_MAP/INSET_MAP 的 `{"__ref__":"map_document","id":…}` stub 经 documents_by_id 换回活对象；未解析保留 stub；返回计数。
- C++ 关系：undo/redo/session 是行为层（非 JSON 数据契约），**不移植**（决策 D-09）；bind_* 依赖活对象图，不移植。stub 形状在 fixture 中作为纯 JSON 透传。
- 测试缺口：session 全套有 pytest；C++ 不对账。

### composer/templates.py
- ElementDefinition / CompositionTemplate（frozen dataclass：template_id/category/label/description/paper_size/orientation/element_definitions/style_bindings/data_bindings）。
- `_base_map_frames`：margin=min(12, w*0.05)、top=24、bottom=34、map=(margin, top, w-2m-88, h-top-bottom)。
- TEMPLATE_LIBRARY：single_factor/contour/heatmap/well_location/seismic_interpretation/isopach/lithofacies/paleogeographic/comprehensive 九模板（A4 landscape，元素几何/properties 全静态字面量）。
- **instantiate_template**：factory.create_document(title/paper/orientation/dpi) → metadata["template_id"]/["template_category"] → 按 z_index 排序的定义逐个 ComposerElement（id 随机 el_…）→ add_element → 有 title 覆盖首个 TITLE 元素 properties["text"]。
- C++ 关系：模板几何是**静态数据**；id 随机 → 不逐字节冻结整文档；fixture 用 `create_geological_factor_map_template`（id 固定 elem_*）覆盖组合构造路径（见 geological_pipeline/templates.py）。
- 测试缺口：模板元素类型全注册有测试；C++ 不对账模板库。

### composer/renderer.py（1341 行）
- MapComposerRenderer.render_to_svg + 24 个 _render_*_svg 分支 + 图表绘制（bar/hbar/line/scatter/pie/donut/histogram/rose）+ legend 提取。
- 契约相关事实：渲染只**读** element/properties/layer JSON 形状（.get 带缺省），对文档零写入零校验；`_render_title` 缺 text → "古地理图"；锁定元素加 `data-locked` 角标；占位诚实（未绑定组件画虚线框）。
- C++ 关系：**渲染输出（SVG）不在本任务**（对应 Python 侧的 QgsLayout/桥接线，本切片明确不做）；本核只需保证 JSON 形状与渲染器读取的词汇表一致。全部符号逐一确认无序列化职责。
- 测试缺口：渲染有大量 SVG 断言测试（composer_registry/units/charts）；C++ 无需对账。

### composer/export.py
- **composition_page_pixels(doc, dpi) → (int,int)**：`max(1, round(w_mm/25.4*float(dpi)))` —— **Python round = 银行家舍入**（round(4.5)=4）；除法先于乘（IEEE754 顺序敏感）；C++ 用 std::nearbyint（FE_TONEAREST 同为 half-even）。
- export_composition_svg/png/pdf：Qt/PySide6 路径，不移植。`_composition_svg` 把 width/height 属性改成 mm 字面量。
- export_composition：按后缀/fmt 分发；未知格式 ValueError `f"unsupported composition export format {name!r}"`。
- 测试缺口：page_pixels 无 pytest 直测；fixture 冻结含 half-even 边界（1.143mm@100dpi→4）。

### composer/__init__.py
- 纯 re-export（__all__ 十个名字）；无契约。

---

## paleo_workbench/mapping/document_io.py（167 行）

### features_from_document(doc) → list[dict]
- PaleoMapDocument（project 域，非 MapDocument）→ 统一编辑器 feature 列表：facies_polygons→normalize_facies、well_overlays→normalize_well、line_features→normalize_line、label_features→normalize_label（geometry_schema 内核，只读引用）；单条 normalize 抛异常 → 记 warning 跳过（不中断）。
- 空边界：doc None → []；各集合 None/缺失 → 跳过。
- C++ 关系：依赖 project 域模型 + geometry_schema 规范化（另一条线）；**不移植**；fixture 不覆盖。

### apply_features_to_document(doc, features)
- 编辑器 feature 回写四桶。facies：保 properties/facies/probability/region_id，facies 缺省取 name。well：坐标 <2 元素 → x/y 保留部分 + `coordinate_status` ∈ {invalid,missing}（CoordinateStatus；**永不上游降级**——已有非 ok prior 保留）；len==1 且可解析 → 保留 x。line：id/name/coordinates 原样。label：coordinates <2 或非数值 → **跳过并 warning**（不崩溃）。
- 输出：doc.facies_polygons/well_overlays/line_features/label_features 四列表整体替换。
- NaN/并列：坐标 float() 失败 → invalid 标记。
- C++ 关系：project 域兼容胶水，不移植；findings 留档防后续切片误判范围。
- 测试缺口：由 geometry/readback 系测试覆盖（不在 §5 清单）。

---

## paleo_workbench/mapping/map_document_snapshot.py（409 行）

### document_render_snapshot(document, *, project_crs, visibility=None, records=None, data_revisions=None, cache_owner=None, layer_revisions=None, previous_layers=None)
- legacy PaleoMapDocument → 渲染快照（每 kind 一层：`{document_id}:{kind}`，kind ∈ facies/well/line/label 固定序；名字 Facies/Wells/Lines/Labels；layer_type="vector"）。
- 几何提取 `_geometry_from_record`：facies→Polygon/MultiPolygon（仅透传 type+coordinates）；well/label→Point（_point 校验 [x,y] 有限数值）；line→LineString（≥2 有效点，坏点剔除）。record 顶层 name/facies/text/topology_status 拷入 properties。
- extent：一次走查内联累计各 kind 包络（expand 递归嵌套坐标）；空 → 哨兵 (0,0,1,1)；`_positive_extent` 退化垫宽 `max(1,|…|)*1e-9`（与 layers.py 的 1e-6 不同！）。
- data_revision：显式 revisions 表优先；layer_revisions 的 `"{document_id}:"` 前缀桥接；否则 `_stable_revision(features)`（递归 freeze+hash，进程内稳定）；>1000 features 走 blake2b 快路径（`_fast_feature_collection_hash`，坐标 struct.pack <dd，属性按 key 排序）。
- style：facies = default_style_for("facies") + document.facies_style update；其余 kind 用预设；再 update `_authoring_style`（layer_state.vector_layers 里同 kind 的 style+labels）。style_revision=_stable_revision(style)。
- 缓存：24 项 LRU，键 (id(cache_owner), document_id, kind, revision)，owner 身份校验；previous_layers 的 data_revision 命中直用其 features/extent。
- 空边界：document None → 空快照（project_crs=str(...)）。
- C++ 关系：adapter 层（渲染接缝），数据形状经 fixture 间接对账（snapshot 输出的 feature dict 与 layer JSON 同词汇）；**本核不移植**（依赖 PaleoMapDocument/缓存/弱引用）。findings 留档。
- 测试缺口：test_map_document_snapshot 2 例（分组不变异、data/style revision 分离）——语义已被 Python 测试钉住，C++ 无需对账。

### extent_for_snapshot(snapshot)
- 有 features 的层聚合 min/max → `_positive_extent`；无 → 哨兵。不移植（同上）。

---

## paleo_workbench/mapping/map_styles.py（383 行）

### LinePattern(str, Enum)
- solid/dash/dot/dash_dot/fault/boundary；`dash_pattern(width)` 返回 Qt 笔宽倍数元组：dash=(4,2)、dot=(1,2)、dash_dot=(4,2,1,2)、fault=(6,2)、其余 ()。渲染消费，不移植（数值留档）。

### MarkerSymbol(str, Enum)
- circle/square/triangle/diamond/cross/star/well。词汇表，C++ 以字符串透传。

### TextStyle（frozen dataclass，12 字段）
- field=""、size=9.0、color="#f8f9fa"、font_family=""、bold=False、halo_color="#182431"、halo_width=1.0、visible=True、rotation_field=""、size_field=""、color_field=""、buffer_color=""。
- **to_dict 12 键固定序**；from_dict 容忍：None 忽略、size/halo_width float() 失败跳过（保留默认）、bold/visible bool()、未知键忽略。
- C++ 关系：style dict 是不透明 JSON；本形状只在 Python 构造默认时烘焙，fixture 冻结成品。

### VectorStyle（frozen dataclass）
- fill="#6c8ebf"、stroke="#26364d"、stroke_width=1.0、line_pattern=SOLID、marker=CIRCLE、marker_size=6.0、renderer="single"、field=""、categories=()（(value,fill,label) 三元组）、ranges=()（(lo,hi,fill,label)）、fill_patterns=()（(value,pattern_id)）、labels=None。
- **to_dict**：前 8 标量键固定序；categories/ranges 仅非空才写（数组套 list）；fill_patterns 仅非空才写（**dict 形式** {value: pattern_id}，顺序=元组序）；labels 非 None 才写。空集省略 = 有损压缩契约（round-trip 无法区分「空」与「缺省」——两者语义相同）。
- from_dict 容忍（关键分支）：categories 同时接受 QGIS wire dict 形式 `{"value":"#color"}`（label 补 ""）与 list/tuple 形式（len≥2，第三位缺省 ""）；ranges 接受 [lo,hi,fill,label] 数组与 {min/max/lo/hi/fill/color/label} dict（float 失败跳过整条）；fill_patterns 接受 dict 与 [value,pattern] 对；stroke_width/marker_size `max(0.0,float(v))` 负值钳 0；未知 line_pattern/marker 值静默保留默认。
- C++ 关系：不移植类；但 from_dict 的「categories dict→数组」等**读侧形状归一**若出现在 fixture 输入（手写 QGIS wire 形状）须能透传——C++ 把 style 当 ordered_json 原样保真，比 Python 更无损（决策 D-07）。

### STYLE_LIBRARY / _STYLE_FOR_KIND / default_style_for(kind)
- 8 个命名预设（facies/well/contour/formation_boundary/fault/line/annotation/label），数值与历史硬编码一致；`default_style_for(kind)`：`_STYLE_FOR_KIND.get(str(kind), "facies")` → **未知 kind 静默落 facies 预设**；annotation/well 等有独立条目（#1052 修复记录）。
- save_style_library/load_style_library：`{"schema_version":1,"styles":{name:to_dict}}` JSON 文件；load 未知条目忽略。
- style_dict_revision(style) → hash(freeze(style))：dict→sorted (str,freeze) 元组递归；进程内稳定（PYTHONHASHSEED 影响——**不可跨进程冻结**，fixture 不用它）。
- C++ 关系：预设值经 fixture 冻结进文档 JSON；C++ 不需要库名表（决策 D-07）。
- 测试缺口：无 style 库直测；经 layers/composer 间接覆盖。

---

## paleo_workbench/mapping/geological_pipeline/templates.py（132 行）

### create_geological_factor_map_template(map_doc, title=None, factor_name="", unit="", paper_size="A4", orientation="landscape")
- 组合 id=**f"comp_{map_doc.id}"**（确定性，fixture 友好）、title= title or map_doc.title or f"{factor_name} 平面分布图"。
- 几何：landscape→297×210 否则 210×297（orientation.lower()=="landscape" 判断，其它字符串一律 portrait）；margin_x=12、margin_y=10、title_h=14；map=(12, 24, w-74, h-34)；legend=(map 右 +5, map_y, 45, min(map_h,80))。
- 元素（add_element 即 z 排序）：elem_title（TITLE, z=10, properties={"text": doc_title}）、elem_main_map（MAIN_MAP, z=1, properties={"map_document": map_doc 活对象, "extent": map_doc.extent 元组}——**to_dict 时序列化为 __ref__ stub**！extent 元组→数组）、elem_north_arrow（z=15, properties={}）、elem_scale_bar（z=15, length_km=max(5,int(span/4)) if span>10 else 10，span=|xmax-xmin|）、elem_legend（z=10, properties={}）。
- NaN/空：extent 哨兵 → span=1 → length_km=10。
- C++ 关系：**id 固定 + 属性静态** → 整文档可逐字节冻结（fixture #22 主来源）；活对象序列化 stub 形状由 to_dict 契约给出。
- 测试缺口：test_geological_mapping_pipeline 只断言元素数 ≥4；fixture 冻结全量 JSON。

---

## paleo_workbench/mapping/geological_pipeline/pipeline.py（594 行）

### _COORDINATE_KEY_FAMILIES / _FACTOR_ALIAS_GROUPS / _find_matching_aliases
- 5 个 CRS 一致坐标键族（project/xy/lnglat×2/surface，project 优先）；10 组因素别名（中英文助记符）。`_find_matching_aliases`：strip+lower 精确匹配组键或别名 → 别名列表；未命中 → [原名, lower]。
- C++ 关系：extract_factors 已在 mapping_kernel extract.cpp 移植（只读，不重复移植）。

### _first_present(rec, *keys)
- 键存在且非 None 的首个值（0.0 合法）——#1150 审计产物。

### GeologicalMappingPipeline
- `__init__(interpolator=None)`：默认 KrigingInterpolator。
- `extract_factors(records, factor_name, *, target_horizon="", unit=None, crs="")`：已在 mapping_kernel（extract.cpp，22 冻结案例全绿）——**只读**。
- `interpolate(dataset, options)`：委托 interpolate_factor（mapping_kernel interpolator.cpp，只读）。
- `create_grid_layer(grid_result, color_ramp=None, opacity=0.85, layer_id=None, name=None)`：GridMapLayer，id=f"grid_{factor_name}"、name=f"{factor} 连续分布栅格"、ramp=FACTOR_DEFAULTS[factor].color_ramp 或 "viridis"、crs/unit 回填。**Fixture 直接消费此层对象→to_dict**。
- `create_contour_layer` / `create_polygon_layer`：委托 contouring/polygonization（mapping_kernel，只读）生成 Contour/Polygon 层。
- `create_well_point_layer(dataset, …)`：valid_points → GeoJSON Point features（properties: name/well_id/value/unit/factor/formation/qc_flag）；style=VectorStyle(fill #22b8a7 … halo_color "#000000").to_dict()；id=f"wells_{factor}"、name=f"{factor} 井位与取值"、extent=dataset.extent。
- **build_factor_map_document(dataset, options=None, *, include_grid=True, include_contours=True, include_wells=True, include_polygons=False, include_annotations=False, annotations=None, title=None, run_id=None, input_version_ids=None)**：
  - interpolate → grid_result；effective_run_id/input_version_ids 回填 grid_result（原引用为空才写）。
  - doc id=**f"map_{dataset.factor_name}"**（确定性）；title= title or f"{target_horizon} {factor} 分布图"；crs=dataset.crs or opts.crs；extent=grid_result.extent。
  - metadata：factor_name/target_horizon/unit/algorithm_id/n_samples(+run_id 仅非 None、input_version_ids 仅非空)。
  - 层序（自下而上）：grid→polygon→contour→well_point→annotation；每层无 source_version_id 时补 primary_source_version_id（=input_version_ids[0] 或 ""）；末尾 recompute_extent。
  - 空边界：include_* 全 False → 0 层文档，extent 保持 grid extent；annotation 层 id=f"annotations_{factor}"。
- `build_factor_composition(map_doc, title=None, paper="A4", orientation="landscape")`：从 metadata 取 factor_name/unit → create_geological_factor_map_template。
- C++ 关系：pipeline 数值链在 mapping_kernel 已绿；**本核消费其文档输出形状**（fixture 经真实 Python pipeline 生成 MapDocument/Composition JSON）。
- 测试缺口：pytest 覆盖 4 层文档形状；composition JSON 形状无直测——fixture 补。

---

## paleo_workbench/mapping/layout_export.py（690 行）

### _NATIVE_TYPES / _HYBRID_TYPES / _LEGEND_BACKED_GATES / _LEGEND_ITEM_KEYS
- 原生映射表（11 型 → 桥 item type）；硬混合边界 6 型（timescale/inset_map/stat_chart/profile/fault_symbols/lithology_legend）；legend 后备 3 型（colorbar/facies_legend/well_legend）；桥能解析的 legend 键全集（type/x/y/w/h/map_item/title/resize_to_contents/background/filter_layers）。import 时 assert 三桶并集 == set(ElementType) 且两两不交。

### _mirror_proves(element_type, mirror_layers) / _legend_filter_doc_ids / _legend_backed_types
- COLORBAR 需镜像含 scalar_grid；FACIES_LEGEND 需 polygon/facies 或 renderer=="categorized" 的 vector；WELL_LEGEND 需 well_point/well。filter 表取同词汇层 id（FACIES 分支含 categorized vector）。
- mirror_layers 接受 snapshot 对象（.layers）或裸层序列；Mapping 判空。

### hybrid_element_types(composition, *, mirror_layers=None) → sorted list[str]
- 可见元素中「非原生且非已证明 legend 后备」的类型值去重排序——全或无回退的显式边界清单。

### LayoutExportReport
- engine/path/format/dpi/ok/warnings/unmapped_elements/items/hybrid_items；**to_dict 9 键固定序**（engine,path,format,dpi,ok,warnings,unmapped_elements,items,hybrid_items）。
- C++ 关系：报告形状是纯数据；随 build_layout_spec 一起**暂不移植**（桥 wire 协议切片，决策 D-11）。

### build_layout_spec(composition, *, map_extent, crs, warnings=None, mirror_layers=None)
- 可见元素按 z 序；未映射可见元素 → ValueError（消息含排序类型名）；GRID 折入 map item 的 grid.interval_x/y = spacing_mm*extent_w/main_map.width_mm（无主图 → warning 丢弃）；LABEL 族（METADATA fields 为 Mapping 时逐行 "k: v"）；IMAGE 无 image_path → ValueError；NEATLINE → shape frame；legend 键只 emit 桥键集；COLORBAR title 拼 units。page={width_mm,height_mm}。
- **不移植本切片**（对应 layout_service.cpp 的桥协议；本核不做 QgsLayout——prompt §4）。
- 测试缺口：test_layout_export_mapping / test_qgis_layout_export 全面覆盖；留待桥切片对账。

### export_composition_reported(...)
- 预算检查（MAX_EXPORT_PIXELS=2e8，超限 ValueError 建议 dpi）→ hybrid 清单 → stack 可用则 build spec + stack.layout_export（异常回退 composer）→ 报告。Qt/桥路径，不移植。

---

## tests/（全部相关文件全文已读）

### test_geological_mapping_pipeline.py（595 行）
- 断言表→C++ oracle 映射：4 层文档层序 ["grid","polygon","contour","well_point"]；composition 元素 ≥4；extract 坐标键族诊断（families_used/skipped_mixing）；NaN 网格 0 features；常量网格 1 多边形 area_percent==100.0；鞍点两种连接；DP 简化端点保留；Chaikin 首末不动。数值部分已由 mapping_kernel fixture 覆盖；文档部分进本任务 fixture（#4 pipeline 全家桶）。

### test_map_document_snapshot.py（70 行）
- 4 kind 分组、id="map-1:kind"、LineString 坏点剔除、extent 聚合 (-2,0,12,10)、文档不变异、data/style revision 分离。→ 不移植（adapter 层），留档。

### test_map_document_panel.py / test_layout_persistence.py / test_layout_presets.py / test_geomodel_joint_layout.py（共 676 行）
- 全部 UI 层（qtbot/QSettings/页面控件）。与数据契约零交集；确认本切片边界（不做 UI）。

### test_layout_export_mapping.py（303 行）
- 三桶完整性与互斥；colorbar 标题拼单位 "砂地比 (%)"；filter_layers 判定词汇；未证明 → hybrid ["colorbar"] + ValueError "colorbar"；裸 dict 序列镜像可用；报告 hybrid_items 排序 + "×N" 计数 warning。→ build_layout_spec 切片的验收基准，本切片只留档。

### test_qgis_layout_export.py（220 行）
- 真桥路径（qgis marker）；spec page/types/grid 间隔换算 25*10/180；不可映射拒绝；PDF/SVG/PNG 输出存在。→ 同上留档。

### test_composer_registry.py（507 行）
- registry 全覆盖断言；**locked 序列化往返：payload→from_dict→to_dict == payload**；missing locked → False；未知类型 → TEXT spec；工厂默认=registry 默认；chart 6 色首色 #4c78a8。→ 序列化往返语义进 C++ fixture（locked/未知类型载体）。

### test_composer_units.py（374 行）
- 96dpi 物理尺寸折算（MM_PER_PX=25.4/96）、to_target dpi 盲、QGIS wire label px→pt（12px→9pt）。→ 渲染折算，不移植；留档。

### test_composer_charts.py（564 行）
- 8 chart_type 渲染标记、坏数据诚实占位、**ROUNDTRIP_CASES 7 组 properties 经 to_dict/from_dict 不丢键不变形 + 二次序列化逐字节一致**（bar/line_xy/scatter_pairs/donut/histogram/rose/colors）——直接进 C++ fixture（properties 开放 dict 保真）。hole_ratio 缺省 0.55 钳制 0~0.9。

### test_challenger_m2_iter3_concurrency_composer.py（731 行）
- 7 层类型 to_snapshot/from_snapshot 类重建断言；**to_dict 的 json.dumps 可序列化**（numpy/tuple 不得泄漏——GridMapLayer 数组不入 dict 契约的间接证明）；深度快照不可变性。→ JSON 形状语义进 fixture（7 层全家桶案例）。

---

## docs/development/qgis-cartography-runtime-v11/（14 文件 972 行，全文已读）

- 00/01：V11 边界与运行时审计——**布局导出曾只走 root children**（组内层静默消失，P0）；顺序约定冲突（bottom-up vs top-first）无平价测试。→ 约束：C++ 数据核不引入第二顺序权威。
- 02/03/04：权威模型（QGIS 树是唯一运行时结构权威；Paleo 拥有 intent/truth）+ LayerTreePlan + 分数序键。→ 约束：MapDocument JSON 核是「truth/intent」侧纯数据，不做运行时树。
- 05/06/07/08：树 diff/原生事务/五目标/阶段语义。→ 与本切片无文档契约交集。
- 09/10：镜像台账/拓扑 M0。→ 同上。
- **11-layout-legend：mirrorTreeOrderTopFirst 全树 DFS 是画布=树=图例=布局的唯一顺序来源**。→ C++ 核遵守：文档 JSON 中的层序即契约，聚合/导出顺序不在此重排。
- 12-scale：结构性断言清单。→ 本核复杂度目标一致（无 O(N²)）。
- 13/14：未做清单与验证矩阵——「C++ 未走 CI，PR 需声明本机构建验证」直接约束本 PR 正文。

## libs/qgis/src/layout_service.cpp（110 行，全文已读）
- QgsPrintLayout 装配：page=spec.page_*，map item、全树 layerOrder 反转（top-first→bottom-first 绘制序，V11 平价）、legend 可选绑定、pdf/svg/png 导出、失败删输出文件。
- 消费的是 **C++ LayoutSpec 结构体**（非 Python build_layout_spec JSON）。→ 本核不重复 QgsLayout；文档核输出 JSON 与该桥的对接属后续接线切片。

## libs/domain/include/pwb/domain/json.hpp（46 行）+ src/support.cpp
- `pwb::domain::Json = nlohmann::ordered_json`（键序保真）；`json_semantically_equal`（对象键集相等+键序无关；数组保序；**int vs float 是类型差**；null/缺失键不等价）；`dump_json_python_compatible`（ensure_ascii=false, indent=2）。
- → 本核直接复用：fixture 对账统一走该比较器；C++ 写出必须复刻 Python 的 int/float 区分（z_index int、x_mm float 等）。

## 既有 C++ 约定（mapping_kernel/CMake/tests/oracle generator，全文已读）
- 静态库 `pwb_mapping_kernel` + `Pwb::MappingKernel` alias + `PWB_BUILD_MAPPING_KERNEL` option；测试为独立可执行文件 `mapping_kernel.<name>`，fixture 经 `PWB_*_FIXTURE` 编译期宏定位；oracle generator `tools/oracle/generate_*_fixtures.py` 用 REPO_ROOT sys.path 注入 + 系统 venv python 真实 import 产品码。→ 本任务沿用全部模式（CONV-02 option、`mapping_document.roundtrip` 目标名）。
