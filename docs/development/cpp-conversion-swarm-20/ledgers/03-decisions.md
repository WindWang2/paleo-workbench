# CONV-03 decisions — 等值线/相带 GeoJSON 图层产物

> 每个非显然选择的理由与被否决的备选。行号引用以本 worktree 为准。

## D1 — clip_ring 不进入 C++ API（含报错文案的失败分支也不留）

**选择：** `generate_contour_layer_product` / `generate_facies_polygon_layer_product` 不携带 clip_ring 参数；Python 的 `_clip_polyline_to_ring` / `_clip_polygon_to_ring` 不迁移。

**理由：** Python 的 clip 内核（`geometry_operations.clip_polyline_to_ring` / `clip_polygon_to_ring`）**硬依赖 shapely**（模块内注释明确 "Requires shapely — a requested clip must never degrade to silently unclipped output"），是 GEOS 多边形交会，其交点坐标由 GEOS 内部（含 snap-rounding/精确谓词）决定，Qt-free C++ 侧无法逐位复刻；冻结 oracle 的验收口径是坐标级一致（与 contouring/polygonization 两个前片的 "坐标 diff 0" 同标准）。M6 第三片已明确 "shapely repair / clip 未移植"。任何手写近似 clip 都会在 oracle 上不可对账，或者把 "静默未裁剪" 的诚实性契约破坏掉。

**备选（否决）：**
- 实现整数/浮点 Sutherland–Hodgman 式 ring-clip：与 shapely 输出坐标不一致，oracle 无法冻结 → 验收造假。
- C++ API 收 clip_ring 并在运行时 throw：留下一个永远不可达成功的分支，属投机 API（Karpathy 反例）。
- 后续若产品需要，正确路径是把 GEOS 交会作为独立工程（vendored Clipper2/GEOS）单独立项。

**影响：** `contour_qc` 的 `clipped_to_domain`/`empty_after_clip` 在 C++ 产物中恒为 0（与 clip_ring=None 的 Python 调用一致，oracle 冻结钉死）；`polygon_qc` 的同名计数同理。

## D2 — 不迁移 style / categories / layer id / name / extent 重算

**选择：** 产物结构体只含 features（GeoJSON Feature 数组）、levels、contour_interval、contour_qc / polygon_qc。

**理由：** 任务边界是 "要素打包（geometry+properties，无样式 UI）"。style（`default_style_for("contour")`、categorized renderer dict）与 categories 是渲染面数据；id 生成（uuid4）非确定性；extent 重算（`VectorMapLayer.recompute_extent`）是图层装配层职责，且 Python 在给定 extent 时本就不重算。消费方 `_contour_child` / `_classification_child`（factor_layer_products.py:272/328）只取 features 与 qc——C++ 产物按同构 JSON 提供即可被未来接线直接消费。

**注意（如实记录）：** `default_style_for("contour")` 因 `_STYLE_FOR_KIND` 无 "contour" 键实际回退 facies 预设——若后续迁样式，须忠实复刻这个回退而非"修正"它。

## D3 — mean_value 复刻 numpy float32 pair-wise 累加（float32_mask_mean 公开）

**选择：** `layer_products.cpp` 实现 numpy 的 pairwise_sum（<8 顺序、≤128 八路累加器、>128 递归对半 8 对齐），sum 与除法都在 float32 完成，再升 double。`float32_mask_mean` 作为公开函数供 oracle 钉语义。

**理由：** Python `mean_val = float(np.mean(grid_z[c_mask]))` 在 float32 数组上以 float32 累加（实测 300 元素随机数组 float32 与 float64 均值差 ~4e-6，`round(x,4)` 不足以可靠掩盖——大网格下有可观的第 4 位翻转概率）。忠实移植消除唯一已知均值分歧源。

**验证：** fixture `mean_units` 冻结 n ∈ {3,7,8,100,127,128,129,200,255,300} 的真实 `float(np.mean(...))`，C++ 按位相等（`==`）对账；类掩膜均值经 26 个 facies 案例端到端对账。

## D4 — length 属性复刻 CPython math.hypot（python_hypot 本地实现）

**选择：** `layer_products.cpp` 内实现 CPython `vector_norm`（幂次缩放 + Veltkamp-Dekker 平方 + Neumaier 补偿和 + 平方根微分修正，fma 版 dl_mul），`python_polyline_length` 用它逐段累加。**不改动已绿的 `contouring.cpp::polyline_length`。**

**理由：** oracle 首跑暴露 `length` 差 1 ulp（9.763360874515449 vs …453）：CPython 的 math.hypot 不调 libm（自带正确舍入算法），与 glibc `std::hypot` 在部分输入上相差 1 ulp。坐标全同，仅求和不同。既有 contouring 核的 168 案例 oracle 未冻结折线长度，故该核用 `std::hypot` 仍是绿的、也不该由本切片重写；而 `length` 是 layer_products 的产品属性，属本切片语义，需逐位对账。

**验证：** 30.0 万对（随机全量级、极端量级、次正规、特殊值含 nan/inf 组合、等长段模式）CTypes 对拍 0 失败；含 nan+inf 组合的 max 选择语义（`if (x > max)` 使 inf 胜过 nan——`std::max(NaN, y)` 语义不同）。

## D5 — 测试比较前做 dump→parse 规范化（canonical）

**选择：** 测试侧 `canonical(Json)` = `Json::parse(value.dump())` 后再 `json_semantic_diff`。

**理由：** 领域比较器在顶层用 `left.type() != right.type()`，而 nlohmann 把 Python JSON 的非负整数解析为 number_unsigned(6)、C++ 新建 `Json(0)` 为 number_integer(5)——线格式完全相同（dump 文本都是 "0"），只在内存类型枚举上不同。修改 libs/domain 超出本切片写入范围，且 "比较线格式" 才是验收本义；规范化一次即可让既有比较器看见相同内存形态。浮点不受影响（两侧都经 10 进制文本往返）。

## D6 — API 形状：FactorGrid + LayerGridContext 两个轻量结构

**选择：** `LayerGridContext{factor_name, unit, crs}` 携带 FactorGridResult 中 FactorGrid 没有的三个身份字段；产品函数 `generate_contour_layer_product(FactorGrid, ctx, options)` / `generate_facies_polygon_layer_product(FactorGrid, ctx, options)`。

**理由：** FactorGrid（interpolator.hpp）是已绿的 M6 结构，无 factor_name/unit/crs 字段——扩字段会触碰既有头文件并波及其它核；传 ctx 是零侵入。grid_z 保持 float（FactorGrid 原生），与 Python float32 网格逐位一致；核内部 float→double 提升与 Python `float(grid_z[i,j])` 等价。`colors=[]` 显式传入时抛 `std::invalid_argument`（Python 会 ZeroDivisionError 崩溃——fail-closed 对齐）。

## D7 — CMake：根 CMakeLists 唯一 CONV-03 块 + mapping_kernel 追加

**选择：** 根 CMakeLists 在 mapping_kernel gate 前插入 `BEGIN CONV-03` 块：`option(PWB_BUILD_CONV_03 ...)` 且 ON 时置 `PWB_BUILD_MAPPING_KERNEL=ON`（块必须位于 gate 之前才有语义，故是定点插入而非文件尾追加）。`libs/mapping_kernel/CMakeLists.txt` 源列表追加 `src/layer_products.cpp`、测试目录追加 `BEGIN/END CONV-03` 注册块。未动任何既有 CONV 块（根文件此前没有）。

## D8 — oracle 冻结范围：features(type/geometry/properties)+levels+contour_interval+qc；不冻结 style/categories/id

**理由：** 与 D2/D4 口径一致：冻结 "用户流程验收" 需要的 geometry 与关键 properties（Python dict 键序保留在 fixture 中），QC 元数据全量冻结（含 early-return 五键与正常路径的差异、area_warnings 文案、holes_promoted_to_exterior 累加、thresholds_source）。10 个空产物案例覆盖早退分支（flat 显式 levels 保留 levels 但零特征、全 NaN/Inf、1x1、1xN 条带）。

## D9 — 阈值默认语义

**选择：** thresholds 显式输入经 `sorted(set(float(t)))`（乱序/重复输入的规范化由 oracle `facies_ramp8_explicit` 钉死）；默认路径 isclose(vmin,vmax)→[vmin] 否则 ⅓/⅔ 跨度；facies_names 缺省三档文案/均一文案/"相带 N" 逐字复刻（含中文与空格）。类 id cap `min(idx+1, len(names)-1)` 复用 `classify_grid`（已绿核）。
