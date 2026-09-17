# 02-decisions — cpp-conv-02 MapDocument / Composer 数据核

每条记录：选择、被否的备选、理由。歧义裁定原则（prompt 头部）：对用户流程更诚实、更少抽象。

## D-01 范围：只做两份文档的 JSON 数据契约；不做渲染/桥/会话
- **选**：MapDocument（layers.py）+ MapCompositionDocument/ComposerElement（composer/models.py）的读、写、文档级操作（add/remove/get/reorder/recompute_extent/add_element/set_paper/get_element/input_version_ids/composition_page_pixels）。
- **否**：composer renderer（SVG 渲染）、export.py 的 Qt 导出、layout_export.build_layout_spec（桥 wire 协议）、CompositionEditSession（undo/redo 行为层）、registry/color_ramps 移植、document_io/map_document_snapshot（依赖 project 域 PaleoMapDocument 的兼容胶水）。
- **理由**：prompt §4 验收只有「Python 写的 JSON C++ 读回语义相等；C++ 写的 Python 读回」+「不做 QgsLayout」。渲染与会话是行为不是数据契约；build_layout_spec 的对账基准在 test_layout_export_mapping，属桥切片。扩大范围 = 无法验证的抽象。

## D-02 库名与位置：`libs/mapping_document`，目标 `pwb_mapping_document`，测试目标 `mapping_document.roundtrip`
- prompt §6/§8 钉死；CMake 仅追加 `BEGIN CONV-02` 块，option `PWB_BUILD_CONV_02`。链接 Pwb::Domain（ordered_json + 语义比较器），与 mapping_kernel 同模式但**不依赖** mapping_kernel（数据核无数值依赖）。

## D-03 MapDocument 读侧契约由本核定义（Python 没有 from_dict）
- **选**：读 = 已知键按 dataclass 默认填充（缺 id → ""，见 D-04）+ 类型相关键（features/annotations）按 layer_type family 归位 + 未知键进 extras；写 = 永远按 Python to_dict 的键序全量写出 13/14/15 键（vector family 恒写 features；annotation 再写 annotations；grid/raster 家族不写两者）+ extras 尾随。
- **理由**：写侧必须复刻 Python to_dict（这是「C++ 写的 Python 能读回」的唯一权威形状）；读侧 Python 无权威，取「填默认 + 全量写出」使 C++ 输出永远是合法 to_dict 形状，且对良构文档 identity。

## D-04 随机 id 不移植
- Python `id` 缺省用 uuid4。C++ 读到缺 id：记 ""（后续 add_layer 的 active 判定等按 falsy 语义处理）。fixture 一律固定 id。生成新 id 属宿主职责（C++ 侧调用者可自带生成器）。

## D-05 layer_type family 分类表
- **选**：vector family（写出 features）= {vector, contour, well_point, polygon, annotation, facies, well}（后两个来自 from_snapshot 的路由词表）；annotation 额外写出 annotations；其余 layer_type（grid/scalar_grid/raster_source/未知）一律 base 形状（无 features/annotations 键）。
- **理由**：Python to_dict 的键集合由**类继承**决定，而 JSON 里只有 layer_type 字符串；读侧需要字符串→形状的反向映射。from_snapshot 的路由词表是 Python 自己给出的字符串→类权威映射，直接沿用；未知类型按最保守的 base 形状处理（渲染器对未知类型也只走 fallback）。
- **边界**：grid 图层 JSON 里出现 features 键 → 按未知键进 extras（不静默丢）。

## D-06 AnnotationMapLayer 的 annotations→features 同步不移植
- Python 的 `_sync_features_from_annotations` 只在构造/突变时运行；JSON 里两键都是既成事实。C++ 读到的成对数据原样透传，不做一致性修复（诚实：不发明）。

## D-07 style/metadata/properties 是不透明 ordered_json
- **选**：不移植 VectorStyle/TextStyle/STYLE_LIBRARY。style 与 metadata、element properties 一律 ordered_json 原样透传（键序、int/float 形态保真）。
- **否**：移植样式类。
- **理由**：Karpathy 最小化。样式默认只在 Python **构造**时烘焙，fixture 里冻结的是烘焙成品；C++ 往返不触发烘焙。移植样式类会引入 to_dict 空集省略契约（categories/ranges/fill_patterns 非空才写）的双向对账负担，而验收流程不经过它。C++ 读手写 QGIS wire 形状 style 时原样保真，比 Python from_dict 的归一读更无损——记录为已知行为差异（C++ 严格保真 ⊇ Python 容忍读）。

## D-08 未知键 extras 保真（§7.4 硬要求）与 Python 的已知静默丢弃**故意不一致**
- Python `MapCompositionDocument.from_dict` 丢弃未知顶层键与未知 element 字段（docstring 声称 preserved，实现没有——findings 已记）。C++ 按本 prompt §7.4：未知顶层键/element 字段/文档级键进 extras 并在写时尾随还原。
- fixture 中此类案例标注 `roundtrip_only`（期望值 = 输入本身，即「无损」契约的冻结表达，由生成器程序化写出而非手写数值）；生成器另用真实 Python（dataclasses/asdict、from_dict、to_dict、pipeline、模板工厂）产出一切「行为案例」的期望值。两类案例在 fixture 里以 `expectation_source: "identity-contract"` / `"python-product"` 区分——红线「不得手写 oracle 期望值」的行为语义由此显式化。

## D-09 falsy/真值语义逐键复刻（Python `or` vs `get(default)` 的差异是契约）
- x/y/width/height_mm：`float(payload.get(k) or d)`——输入 0/0.0/""/false/null → **默认值**（width_mm=0 → 1.0 的 quirk 冻结）。
- visible/locked：`bool(payload.get(k, default))`——缺键 → 默认；0/false/""/null → False；非空字符串 "0"/"false" → **True**（Python str 真值）。
- z_index：`int(payload.get(k) or 0)`——2.7 → 2（向零截断）；"3" → 3。
- 字符串数值 "12.5" → 12.5（Python float() 子集：strtod + 两端 ASCII 空白裁剪 + 全量消费；inf/nan 词法接受）。不可解析字符串：Python 抛 ValueError（未捕获），C++ 抛 std::invalid_argument（**消息文案不对账**——Python 消息含 repr 细节，冻结它无用户价值；见 D-12）。
- **理由**：这些不是边角——「多余字段/缺字段」验收案例必然踩到缺省路径；语义比较器把 0 vs 0.0 视为类型差，逼着 C++ 复刻 Python 的 int/float 输出形态（z_index int、坐标 float）。

## D-10 registry/模板库不移植为 C++ 数据，只经 fixture 冻结其产出
- registry 的 default_properties、TEMPLATE_LIBRARY 几何都是 Python 内的静态数据，用于**构造**。C++ 核的读/写/改操作不依赖它们；fixture 用真实 CompositionFactory/instantiate_template/create_geological_factor_map_template 生成含默认属性的 JSON（tuple→数组形态由真实 to_dict 产出）。

## D-11 layout_export.build_layout_spec / LayoutExportReport 推迟到桥切片
- 已全文通读并写入 findings（含三桶表、legend 键集、grid 间隔换算公式、消息文案）；其验收基准（test_layout_export_mapping）不依赖文档核。文档核落地后桥切片可直接复用 composition 读模型。

## D-12 错误消息对账范围：只对 `set_paper` 的 ValueError 文案
- `unknown paper size 'b5'`（Python !r 单引号 repr）被 C++ 逐字符复刻（含引号），因为它是**产品定义**的面向用户文案。float()/int() 的解析错误消息是解释器实现细节，不对账（抛同类型异常即可）。

## D-13 composition_page_pixels 的 Python round 复刻为 std::nearbyint
- Python round = half-even；C++ std::nearbyint 在默认 FE_TONEAREST 下同为 half-even；运算顺序固定为 `(w / 25.4) * dpi`（与 Python 表达式同序，IEEE754 逐位一致）；`max(1, …)` 钳制。fixture 含 1.143mm@100dpi→4（half-even 向下）与普通值。

## D-14 元素排序 = stable_sort by z_index
- Python `list.sort` 稳定；`add_element` 与 `from_dict` 末尾都排序。C++ `std::stable_sort`。fixture 冻结同 z 平局保持插入序。

## D-15 `ComposerElement.to_dict` 的 `_raw_element_type` 弹出 quirk 全量复刻
- 写时 pop `_raw_element_type`；弹出非 None 且 element_type==text → 用弹出值作 element_type 输出（即使输入 element_type 本来就是合法 "text"、marker 是普通数据也照弹——Python 实际行为）。读时未知类型 → 载体 TEXT + `properties.setdefault("_raw_element_type", raw)`（已存在不覆盖）。fixture #23/#32 冻结两个方向。

## D-16 fixture 结构：单文件多案例表
- `libs/mapping_document/mapping_document_tests/fixtures/map_document_oracle.json`：
  - `map_document_cases[]`：{id, expectation_source, input, roundtrip, ops[], probes{}}（ops = remove_layer/reorder_layers/add_layer 等经真实 Python 应用后冻结的整文档期望）。
  - `composition_cases[]`：{id, expectation_source, input, roundtrip(=真实 from_dict().to_dict()), ops, probes{}}。
  - `pixel_cases[]`：真实 composition_page_pixels 输出；`set_paper_error`：真实异常文案；`paper_sizes`：PAPER_SIZES_MM。
- 生成器 `tools/oracle/generate_map_document_fixtures.py` 强制 sys.path 注入本 worktree、真实 import 产品码、写盘前自校验（roundtrip 幂等断言）。

## D-17 extras 键序
- 语义比较器键序无关，但 house 约定（domain json.hpp 注释）是「声明字段在前 extras 尾随」。C++ 写出遵守该序；fixture 对良构文档断言 identity（键序天然一致），对 extras 文档只断言语义相等。

## D-18 语义比较复用 `pwb::domain::json_semantically_equal`
- 不另写比较器。已知约束：int vs float 类型差 → C++ 模型对 Python 的 int 字段（data_revision/style_revision/z_index/schema_version）用整数写出、float 字段用双精度写出；fixture 输入的 extent/坐标一律由生成器保证为 float 形态（Python 构造时用浮点字面量，与生产路径一致）。

## D-19 subagent 预算用法
- #1 general-purpose：对抗性 spec 审核（对照 Python 源与 §8）；#2 general-purpose：Karpathy/代码质量审核。#3 保留。实现由父代理完成。

## 审核轮 2 追加决策（对抗性 spec 审核后的修正）

## D-20 input_version_ids：metadata 种子原样透传（审核轮 2 修正 P1-2）
- Python `input_version_ids` property 把 `metadata["input_version_ids"]` **原样**作为种子（内部不去重、条目不筛选），只对后续 layer `source_version_id` 做「不在列表中才追加」。C++ 初版对种子也去重并只收字符串——已改为返回 `Json` 数组：metadata 数组逐字复制，layer id 以 JSON 值语义查重后追加。metadata 值非数组（如字符串被 Python `list()` 拆字符）超出产品契约，C++ 报空数组。

## D-21 案例标注三分法（审核轮 2 修正 P1-3）
- `python-product`：期望值与 probes 全部来自真实产品码/活对象。
- `identity-contract`：仅限真无损案例（输入原样透传）。
- `cpp-read-contract`：钉住 Python 产品码不定义的读侧行为（MapDocument 无 loader 的标量默认填充；缺 element id 记 ""；schema_version 再规范化+extras 保留）。期望值由生成器按决策文档程序化构建，不冒充产品行为。初版把两例混标 identity-contract，已更正。

## D-22 像素折算平局钉死（审核轮 2 修正 P1-1）
- 新增 (13.97mm,150dpi)→82.5→82、(24.13mm,150dpi)→142.5→142（二进制精确 x.5，实跑验证 Python round 半舍入到偶、C++ nearbyint 一致）；fixture 同时冻结 `raw` 双精度值以钉死 `(w/25.4)*dpi` 求值顺序。D-13 初版文案「1.143→4」有误（FP 实际 4.500000000000001→5），以本条为准。

## D-23 py_float 拒绝十六进制字面量（审核轮 2 修正 P2-2）
- Python `float("0x1A")` 抛 ValueError 而 glibc strtod 接受；py_float 在 strtod 前拒绝 `0x`/`0X` 前缀。已知残留偏差（不可达荒谬输入，记录不修）：`nan(n-char-seq)` glibc 词法、`int("1_0")` 下划线字面量、py_str 对容器走 JSON dump 而非 Python repr、set_paper 错误文案对含引号参数的 repr 边界、reorder 请求外的重复 id 已按 dict 语义对齐（保留最后出现、首现位置接尾）。

## D-24 审核轮 3 采纳与保留（Karpathy 审核后的取舍）
- 采纳：`*_or` 强制转换 helpers 下沉到唯一消费者 composition.cpp；extras 收集收敛为 `collect_extras`；`find_layer`/`remove_layer` 返回值进入测试行使（remove 返回值经 fixture `"returns"` 字段对账）；模型名去 `_Model` 后缀（对齐 mapping_kernel 裸名风格）；`is_vector_family`/`is_known_element_type` 移入 .cpp；删除零调用的 `operator==`/公共 `paper_size_mm`/死 using/死 errno/恒真分支。
- 保留（记录）：根 CMakeLists 的 `option(PWB_BUILD_CONV_02)` 留在 BEGIN CONV-02 块内（prompt §3 的模板形态优先于文件内 option 集中区，且块外零改动）。`dump_layer` 对 style/metadata 的 object 守卫保留——dump 是公共 API，接受程序化构造的模型（其 Json 成员默认为 null），守卫使 dump 全态化而非死防御。
