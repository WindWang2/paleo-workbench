# 13 — findings：prediction/tiled_onnx 移植前置逐符号阅读笔记

基线 `origin/main` = `35987e13`。全部 §5 文件已全文阅读（非 grep 摘录）。
本文按文件索引；**【移植】** 标记本切片进 C++ 的符号，**【胶水】** 标记属服务/
UI 接线层（后续切片），**【 findings-only 】** 标记仅记录契约不移植。

环境事实（本机）：系统 `python3`（3.14，/usr/sbin）无 numpy；仓库无 venv/conda。
oracle 生成器用 `/tmp/pwb-oracle-venv`（numpy 2.5.3 + pydantic，`python3 -m venv`
创建，未触碰 QGIS vendor）。`onnxruntime`/`zarr`/`onnx`/`geoviz_seismic` 均不可
安装复现 → 走 prompt 预设的 stub 路径：monkeypatch `_make_session` + 内存 zarr
替身，调用**真实** `run_tiled_inference`。

---

## 1. `paleo_workbench/prediction/tiled_onnx.py`（625 行，移植目标）

### 1.1 模块常量 【移植】
- `PROVIDER_TILED_ONNX = "tiled_onnx"`：provider 注册名（providers.py 懒注册）。
- `TILE = (64, 128, 128)`：生产 tile (inline, xline, time)。测试/小体可覆盖。
- `DEFAULT_RECEPTIVE_FIELD = 8`：默认重叠（= 感受野半径预算）。可为 0
  （stride==tile，无 halo）；0 与 8 都进 oracle。
- `SOFTMAX_INTERMEDIATE_BUDGET_BYTES = 512*1024*1024`：#1187 预算，512 MiB。
- `ONNX_MODEL_SUFFIX = ".onnx"`、`ONNX_MODEL_MAX_BYTES = 4 GiB`（#1176）。

### 1.2 `TiledInferenceError(RuntimeError)` 【移植】
诚实失败类型：坏模型 I/O 契约、不可用输入、batch=1 仍 OOM。文案用户可见，
oracle 冻结原文（见 §1.9 错误文案表）。C++ 侧为 `std::runtime_error` 子类
（或带 kind 的异常），`what()` 文本逐字节对齐。

### 1.3 `_check_onnx_model_file(model_path)` 【移植】
- 输入：`Path`。`stat` 失败 → `st=None`。
- 拒绝（一个合并条件）：st 为 None / 非常规文件（S_ISREG）/ 后缀（lower）
  ≠ ".onnx" / size ≤ 0 → 报 "refusing to load non-model file as ONNX: {path}
  (regular .onnx files only)"。
- 大小帽：env `PALEO_ONNX_MAX_MODEL_BYTES`（空串/未设 → 4 GiB；非整数 →
  4 GiB）超出 → 报 "ONNX model {path} is {n} bytes, above the {cap}-byte
  load cap (PALEO_ONNX_MAX_MODEL_BYTES overrides)"。
- 返回 binding：`{model_file: name, model_bytes: size, model_sha256:
  sha256_file_or_none}`。sha256 属 provenance，oracle 冻结（stub 文件内容固定）。

### 1.4 `_sha256_file(path)` 【findings-only（生成器直接用 hashlib）】
1 MiB 分块流式 sha256 hex。C++ 不移植（provenance 由调用方冻结值传入）。

### 1.5 `_validate_softmax_budget(batch, classes, tile)` 【移植】
- `tile_voxels = t0*t1*t2`；`bytes_per_unit = max(1, tile_voxels*4)`（float32）；
  `classes_bytes = classes*bytes_per_unit`。
- classes_bytes > 512 MiB → 报 "classes={c} with tile {t} needs {mib} MiB of
  softmax intermediates per batch item (> 512 MiB budget); refusing: class
  count does not match a runnable tile model"（MiB 为 `f:.0f`）。
- `planned = batch*classes_bytes > 预算` → 报 "batch={b} × classes={c} × tile
  {t} would need {mib} MiB ... reduce batch to <= {max_batch}"，
  `max_batch = max(1, budget // classes_bytes)`。
- 语义：显式失败、绝不静默钳制（batch 是调用方旋钮、classes 是模型契约）。

### 1.6 `tile_starts(n, tile, overlap) -> list[int]` 【移植·核心】
- `tile <= overlap` → TiledInferenceError("tile {tile} must exceed overlap
  {overlap}")。
- `stride = tile - overlap`；`n <= tile` → `[0]`（单 tile 覆盖全轴）。
- 否则 `list(range(0, n - overlap, stride))`：起点严格 < n-overlap。
  **覆盖性**：末起点 s ≥ n-overlap-stride = n-tile ⇒ s+tile ≥ n，末片（截断到
  n）总是够到轴尾。例（真实运行验证）：(100,30,8)→[0,22,44,66,88]；
  (7,8,4)→[0]；(5,4,1)→[0,3]；(1,1,0)→[0]。
- 注意 range 右端开区间：n=9,tile=4,overlap=0 → range(0,9,4)=[0,4,8]，8+4=12
  截到 9 —— 末片可以几乎全在 pad 区（真实行为，C++ 必须一致）。

### 1.7 `authoritative_range(i, starts, stride, overlap, n) -> (lo, hi)` 【移植·核心】
- `lo = 0 if i==0 else starts[i] + overlap//2`（注意 floor 除，奇数 overlap 时
  不对称：overlap=5 → 偏 2）。
- `hi = n if i==len(starts)-1 else starts[i+1] + overlap//2`。
- 结果：所有 tile 的 [lo,hi) 构成 [0,n) 的**精确划分**（无缝无叠、每体素恰好
  一次权威预测）。测试 test_tile_partition_covers_exactly_once 用
  (100,30,8),(26,8,4),(7,8,4),(128,64,8) 四组钉死。
- 例：starts=[0,4,8,12,16,20]（26,8,4）→ (0,6),(6,10),(10,14),(14,18),(18,22),
  (22,26)。

### 1.8 `_make_session(model_path, prefer_gpu)` 【不移植（ORT 接线层）】
providers 列表 [CUDA?, CPU]；ORT 会话线程数来自 resource_governor
（try/except 包住，失败用默认）；GPU 会话失败且 prefer_gpu → CPU 重试并返回
mode="cpu"；成功时 `mode = "cuda" if any("CUDA" in p) else "cpu"`。
**诚实模式上报**的语义在 C++ stub 里以 mode="cpu" 固定。

### 1.9 `run_tiled_inference(reader, model_path, *, classes, work_root,
overlap=8, batch=1, prefer_gpu=True, tile=(64,128,128), progress=None,
cancel=None) -> dict` 【移植·核心】
校验顺序（先到先报，oracle 逐条冻结）：
1. `model_path.is_file()` 否 → "ONNX model not found: {path}"。
2. `_check_onnx_model_file`（§1.3）。
3. `tile = tuple(int(t))`；`len(tile)!=3 or 任一 <=0` → "tile must be a
   positive (il, xl, t) triple: {tile}"。
4. `classes <= 0` → "classes must be > 0, got {classes}"。
5. `batch = int(batch)`；`batch < 1` → **ValueError**（非 TiledInferenceError！）
   "batch must be >= 1, got {batch}; refusing to silently clamp"。
6. `_validate_softmax_budget(batch, classes, tile)`。
7. `_make_session`（stub 替换点）。
8. `input_name = sess.get_inputs()[0].name`、`output_name =
   sess.get_outputs()[0].name`。

主体几何：
- `shape = tuple(int(x) for x in reader.shape)`（3 轴）；work 目录
  `mkdir(parents=True, exist_ok=True)`；输出存储 `work/classmap`（uint8）、
  `work/probmap`（float16）；`open_or_create`：已有 `zarr.json` → 追加打开
  （resume 语义），否则新建 chunks=(64,128,128)。
- `starts = [tile_starts(n,t,overlap) for n,t in zip(shape,tile)]`（逐轴独立）；
  `stride = [t-overlap for t in tile]`。
- `done_dir = work/tiles.done`（mkdir）。tiles 列表按
  `for i for j for k`（inline 最外层）字典序展开。
- `completed = {p.name for p in done_dir.iterdir() if startswith("t_")}` ——
  **resume**：marker 名 `t_{i:05d}_{j:05d}_{k:05d}`。
- 批量组预算（#1081）：`active_budget().streaming_buffer_bytes`（try/except →
  5 GiB）；`_max_batch = max(1, budget // (classes*tile_voxels*4*6))`；超出则
  logger.warning + `current_batch = _max_batch`（**这是唯一的静默钳制**，资源
  守卫性质；本机 62 GiB → 5 GiB 预算，oracle 小 tile 永不触发。**不移植进
  C++ 数值核**，理由记 decisions）。
- 主循环 `while idx < len(tiles)`：
  - `cancel()` 为真 → 返回协议完整 dict：mode/tiles_total/tiles_done/
    cancelled=True/elapsed_s/batch/shape/class_map/prob_map/classes/overlap
    （#1167：可恢复取消 ≠ 失败；resumable 部分进度在盘上）。
  - `group = tiles[idx:idx+current_batch]`，过滤掉已 completed 的；
    `group` 空 → `idx += current_batch` 继续（**done_count 不加**）。
  - `_run_tile_group` 抛异常：`current_batch>1 且 _looks_like_oom(exc)` →
    `current_batch //= 2`，sleep 0.5/current_batch，重试同 idx（**OOM 半退避**，
    组重新按新 batch 切）；否则 re-raise。
  - 组内每 tile 写 marker `tile_key(t)` 内容 "ok"，然后 fsync done_dir
    （OSError 吞掉）。`done_count += len(group)`；`idx += current_batch`；
    progress(done_count/max(total,1), f"{done_count}/{total} tiles")。
- 返回 stats：mode/tiles_total/tiles_done/cancelled=False/elapsed_s/batch/
  class_map/prob_map/shape(list)/classes/overlap/model_binding。

### 1.10 `_looks_like_oom(exc)` 【移植】
`f"{type.__name__}: {exc}".lower()` 含 "out of memory" 或 "oom"，或
（"alloc" 且 "fail"）。注意 Python 运算符优先级：`a or b or c and d` =
`a or b or (c and d)`。C++ 需复刻该优先级。

### 1.11 `_run_tile_group(reader, sess, ..., group, tile)` 【移植·核心】
每 tile：
- `s = starts[axis][idx]`；`e = min(s+tile[axis], shape[axis])`；
  `block = reader.read_voxel_window(s0,e0,s1,e1,s2,e2)`（截断窗口，非 pad 窗）。
- **零填充**：`pads=[(0, tile[a]-block.shape[a]) for a in 3]`，仅高地址端补 0
  （constant 0.0）。理由（源码注释）：'same'-padding 卷积模型在体边界看到零；
  内部切面绝不 pad —— 重叠 halo 携带真实数据。
- `batch_np = np.stack(batch_tiles)[:, None].astype(np.float32)` → (N,1,D,H,W)。
- `out = sess.run([output_name], {input_name: batch_np})[0]`；ndim==5 通过；
  ndim==4 → TiledInferenceError("model output ndim=4; tiled seismic expects
  (N,C,64,128,128)")；其他 → "model output ndim={n} unsupported"。
- `n_cls = out.shape[1]`；`n_cls > 1` → softmax（沿 axis=1，max-subtracted，
  float32）；`n_cls == 1` → `np.concatenate([1.0-out, out], axis=1)`
  （sigmoid 二类展开）。
- 每 tile：`seg = probs[bi][:, off_a0:off_a1, ...]`（**channel 保留，空间裁
  权威窗**）；`am = seg.argmax(axis=0).astype(uint8)`（numpy argmax 首最大，
  NaN 全通道时落在首个 NaN 通道——探针验证）；`mp = seg.max(axis=0)
  .astype(float16)`（RNE，NaN→NaN，±inf→inf）。
- 写 `class_out[lo0:hi0, lo1:hi1, lo2:hi2] = am`、`prob_out[...] = mp`。

### 1.12 `_same_file(left, right)` 【胶水】
resolve() 相等；TypeError/OSError → False。

### 1.13 `_verify_model_identity(model_path, parameters, actual_sha256)` 【胶水】
#1176 模型身份绑定：`_registered_model`（服务端注入）+ `model_checksum`
（调用方 pin，P3）。checksum 不符 → 中文拒绝文案；有身份无 checksum → 按
artifact_uri 路径绑定；无身份 → `registered=False, verified=bool(pin)`、
真实 sha256。属 catalog/run 接线，本切片 findings-only（测试
test_identity_* 4 个用例对应）。

### 1.14 `TiledOnnxProvider` 【胶水（provider 壳）】
- `model_id="tiled-onnx-seismic"`, `model_version="tiled-onnx-v1"`,
  `demo_only=False`。
- `run(inputs, parameters, *, context=None, cancel=None)`：inputs 第一个值取
  path；无 inputs → "tiled inference needs a seismic input version"；路径不
  存在 → "input volume not found: {path}"；`model_path`/`classes>0` 缺 →
  "parameters must include model_path and classes (> 0)"。
- 参数：`receptive_field`（`or 0`）、`batch`（None/"" → 1，真值透传，B5）、
  `tile`（参数覆盖或 TILE）、`work_root`（缺省 `path.parent/{name}.inference`）、
  `prefer_gpu`（默认 True）、cancel 从参数/context 取。
- `open_volume(path)`（geoviz_seismic）→ reader；`run_tiled_inference`；
  cancelled → TaskCancelled；payload 组装（source/generator_version/
  device_mode/model_binding/tiles/cancelled/elapsed_s/class_map/prob_map/
  shape/classes/model_provenance/volume_outputs[classmap uint8 + probmap
  float16]）；mode=="cpu" → 附 "cpu_mode_note": "CUDAExecutionProvider
  unavailable — ran on CPU"。

### 1.15 测试缺口（tiled_onnx）
- ndim==4/其他 ndim 的报错文案无 pytest 覆盖（本切片 oracle 补上）。
- `_check_onnx_model_file` 的后缀/大小帽/非常规文件拒绝无直接 pytest
  （oracle 补）。
- OOM 半退避路径无 pytest（stub 可复现 → oracle 补）。
- group 全部已 completed 时 `idx += current_batch`（done_count 不加）的
  resume 细节无显式断言（oracle 冻结 tiles_done）。

---

## 2. `paleo_workbench/prediction/providers.py`（700 行）

### 2.1 `InferenceInputError` / `DuplicateProviderError` 【胶水】
无可用输入的诚实失败；同名异类注册拒绝（#1184）。

### 2.2 `_clamp_int(value, default, min, max)` 【胶水】
int() 失败/None → default；再夹 [min,max]（#1144 超时上界）。

### 2.3 `ModelProvider`（Protocol, runtime_checkable）【胶水】
`model_id/model_version/demo_only` + `run(inputs, parameters)`；MAY 加
keyword-only `cancel`（#1167）。inputs: version_id → {path,name,asset_type,
format,version_id}。

### 2.4 `DemoModelProvider` 【findings-only】
seeded random.Random(seed)；4 区域 0.55+rng*0.35；全诚实标记；demo_only=True。
测试 test_demo_provider_marks_demo_output。

### 2.5 `LocalAssetProvider` 【findings-only】
包装 run_heuristic_facies；无可用输入 → InferenceInputError 中文文案
"无可用输入数据：未找到可读的测井（LAS）或地震数据，无法运行启发式预测"；
evidence 权重按绑定资产 0.5/0.3/0.2 或 0.1 归一化 round 3。

### 2.6 `GeoVizOnlineProvider` 【findings-only】
单井 HTTP provider：env 决定 endpoint/model_version（run 参数仅展示快照
#1144/#1184）；full-resolution 载入（#1193）；按层厚加权平均概率 round 3；
adapter_kind="http"。

### 2.7 `PROVIDER_BY_NAME` + `_install_bundled_providers` 【胶水】
demo/local_asset/geoviz_online 直接注册；tiled_onnx **懒注册**（import 失败
静默跳过 —— 无 onnxruntime 时注册表里没有 tiled_onnx，get_provider 报
"Unknown model provider: 'tiled_onnx'"）；mock 两件套注册。

### 2.8 `register_provider` / `unregister_provider` / `get_provider` 【胶水】
同类重注册幂等；异类抛 DuplicateProviderError；非类抛 TypeError。
**BASE 已知缺陷**：源码 529–558 行存在不可达死代码 —— 第一个
`unregister_provider` 函数体内 return 之后跟着一段旧的 register 体，然后
555 行有第二个模块级 `def unregister_provider` 覆盖前者（语法合法、两者行为
相同均为 pop）。不在本切片修复（surgical）；记录备后续清理 PR。

### 2.9 `ensure_geoviz_online_model` / `ensure_default_models` / `_ensure_model_version` / `_existing_model` 【胶水】
幂等种子注册（status="demo"，绝不晋升）；已存在模型绝不重写。

---

## 3. `paleo_workbench/prediction/inference_service.py`（749 行）【全胶水】

- `INFERENCE_GENERATOR="inference-service-v1"`；`_RESERVED_KEYS`；
  `PAYLOAD_RESERVED_KEYS`（#1152 服务方拥有的信封键，provider 结果先过滤再
  合并、信封最后重申 —— 防 provider 伪造身份）。
- `_snapshot_hash`：json.dumps(sort_keys, ensure_ascii=False) → sha256。
- `_input_info`：trashed 版本 → CatalogError("Input version {id} is trashed
  (H5-a)")。
- `resolve_prediction_inputs(project, service, resource_ids=None)`：
  well_log/seismic 资源 → 当前版本 id（asset id / legacy bridge /
  catalog_asset_id / 源 URI 唯一匹配）；未 scope 时附加 factor_map 任务版本。
- `resolve_prediction_postprocess_inputs`：well_stratification 版本。
- `resolve_inputs_for_model`：Stage-13 schema 驱动（转 input_contract）。
- `_resolve_resource_version_id`：四级解析（id/legacy/catalog_asset_id/
  source_uri 唯一）。
- `start_inference`：run.parameters 记 model 元数据 + seed +
  `_input_snapshot_hash`（输入集合排序去重 → 置换不变，H5-e）。
- `_provider_accepts_cancel`：签名含 VAR_KEYWORD 或 "cancel"。
- `execute_run`：terminal run 拒绝重执（CatalogError）；provider 异常 →
  TaskCancelled 记 cancelled、其余记 failed（`{Type}: {msg}`）+ 无输出；
  provider 结果 cancelled=True → cancelled；spatial_output_type 声明时
  validate_spatial_result；payload 信封 schema_version=1.0/model/...
  再 **provider_payload 展开**；`_persist_result`：volume_outputs 先做工作区
  包含校验（B1，逃逸 → PermissionError → failed），JSON 临时文件 →
  register_result_asset（DERIVED）→ register_derived_store（zarr-v3，
  prediction-volume）。
- 失败发生在已注册输出之后 → 尽力标 complete（防"failed run 挂着可用输出"，
  Agent L P2）。
- `_cancel_run`：cancelled + tiles_done/elapsed_s 附加。
- `link_run_to_domain_task`；`materialize_prediction_task`：PredictionTask
  承载诚实标记 + model_metadata + bounded summary。

---

## 4. `paleo_workbench/prediction/input_contract.py`（366 行）【全胶水】

- `InputContractError(ValueError)`。
- `_RECOGNIZED_SCHEMA_KEYS`（10 个识别键；未识别结构 strict 下 fail-closed
  H5-b）。
- `parse_input_schema`：required_asset_types|asset_types（str → [str]）、
  optional_asset_types、required_curves|curves、4 个 require_* bool、
  min_wells int、raw 原样。字符串 strip 后去空。
- `resolve_model_inputs`：空 schema → legacy 全局 gather；声明了必需类型 →
  按类型收集（factor_map 走 complete 任务版本；correlation/horizon/fault 走
  current_version_id）；strict 缺失 → 中文报错（对比解释/层位解释/断层解释/
  目标层位/至少 N 口井/缺少必需输入类型/缺少必需曲线）。
- `_enforce_required_curves`：parsed_summary["curves"] 优先，LAS/WITSML 头
  兜底（不受预览截断限制）；不可读/缺曲线 fail-closed；曲线名 upper 比较。
- `_curve_names_from_resource_path`、`_asset_type_for_version`。

---

## 5. `paleo_workbench/prediction/spatial_result.py`（224 行）【胶水（Stage 13 空间契约）】

- `spatial_type_of`：payload → summary → output_schema → summary.spatial 四级
  探测 `spatial_output_type`；spatial dict 含 features/polygons →
  VECTOR_POLYGONS，intervals/well_intervals → WELL_INTERVALS，grid/classes →
  CLASSIFIED_RASTER；否则 NONE。
- `extract_polygon_features`：仅保留 geometry.type ∈ {Polygon, MultiPolygon}
  且 coordinates 非空的 Feature。
- `validate_spatial_result`：未知类型报 "unknown spatial_output_type: {t!r}"；
  VECTOR_POLYGONS 需有效 ring（有限坐标、≥4 点）+ crs + 拒绝 demo 固定方块
  (114, 22.5, 0.04)；WELL_INTERVALS 需 intervals 或带 top/bottom 的 regions；
  CLASSIFIED_RASTER 需 grid/artifact_path + crs + 6 元 geotransform。
- `bounded_result_summary`：grid 摘出，留 grid_shape + grid_omitted。
- `is_map_compilable`、`_has_finite_ring`、`_looks_like_demo_square`
  （math.isclose abs_tol 1e-6）。

---

## 6. `paleo_workbench/prediction/model_package.py`（365 行）【胶水】

- 常量 SPATIAL_*（4 类）+ KNOWN_SPATIAL_TYPES。
- `ModelPackageManifest` dataclass + `to_dict`。
- `load_manifest_dict`：dict 透传 / 路径读 JSON / 根必须 object。
- `_strict_bool`（H4-1）：仅真 bool 或 "true"/"false" 字符串，否则
  ModelPackageError。
- `parse_model_package_manifest`：model_id/name/capability/provider 必填；
  相对 artifact 相对 base_dir resolve；output_schema 缺 spatial_output_type
  时补。
- `validate_model_package`：NON_PROMOTABLE provider/model_type、demo_only、
  scientific=false 均不可注册生产（H4-3b）；artifact 存在 + checksum 匹配
  （无 checksum 则回填）；input_schema 必填。
- `register_model_package`：版本再注册的身份冲突检查（checksum/schemas/
  preprocessing/deterministic/demo_only，H4-2）；status="production" →
  promote_model 安全门。

---

## 7. `paleo_workbench/prediction/postprocess.py`（262 行）【胶水（在线预测后处理，未来候选切片）】

- `_EPSILON=1e-6`；`_UNSPECIFIED_STRATUM="未标定层位"`。
- `postprocess_prediction_regions`：按 (top,bottom) 排序 → 每层位界先切分
  （层位是硬边界，绝不跨越）→ 相邻同 facies 且**显示精度概率相等**合并
  （`_display_probability`：`int(f"{p:.0%}"[:-1])/100`，与百分比渲染锁步）→
  merged_sample_count 累加 → region_id 重排 `inference_api_post_{n}`；
  summary {applied, confidence_display_precision:"1%", raw/split/
  postprocessed_region_count, formation_boundary_count}。
- `resolve_formation_boundaries`：well_stratification（parse_well_tops）+
  LAS formation intervals；坏文件只记 diagnostics 不弃预测。
- `_normalize_boundaries`：(round(depth,6), name) 去重 → 同深度多标签取
  字典序第一（确定标签）。`_split_bounds`、`_stratum_at`、`_touches`、
  `_finite_number`（NaN/inf → None）、`_well_key`（stem.casefold + 去
  非词字符）。
- pytest 对应 test_prediction_postprocess.py 4 例（含 0.531/0.534/0.532/
  0.531 → 全 0.53 合并两组、层位切 1000.5、不同相/不同显示概率不合并、
  分层文件按井名匹配）。

---

## 8. `paleo_workbench/prediction/adapters.py`（414 行）【findings-only】

- `_FACIES_SAND/_FACIES_MUD` 8 相词表；GENERATOR_VERSION="mock-prediction-v1"、
  LOCAL="local-asset-prediction-v1"。
- `_snapshot_hash` 同 inference_service。
- `_resolve_resource_path`：绝对/相对 project_root 解析。
- `run_heuristic_facies`：前 3 口可读井 → LAS GR（或首曲线）统计分区
  （`_regions_from_las`：中值分界、窗口均值、沙/泥相 + 0.55–0.95 概率、
  seed+int(median*10)%1000 抖动）；仅地震 → seeded 模板（is_mock=True 诚实）；
  无输入 → source_kind="mock" 空 regions。
- `MockPredictionAdapter` / `LocalAssetPredictionAdapter`：PredictionTask
  工厂 + register_prediction_run（catalog 失败不吞）。

---

## 9. `paleo_workbench/prediction/mock_facies.py`（297 行）【findings-only】

- MOCK_FACIES_CLASSES=("扇三角洲","三角洲前缘","滨浅湖","湖相泥")；
  `_FALLBACK_INTERVAL=(600.0,800.0)`；`_HONESTY` 全标记 dict。
- `MockWellFaciesProvider`：每井一区间（td 有值 → 0.6td–0.8td，round 2；
  否则 fallback）；rng 两抽：相（`min(int(draw*4),3)`）+ 概率
  （0.55+rng*0.35 round 3）；`well_detail` 带 rng_draw。
- `MockSeismicFaciesProvider`：12 锚点最近邻 → grid_n×grid_n float32 栅格
  （np.linspace/argmin）→ 可选 clip_ring（inclusive PIP，复用
  mapping.geometry_planar）→ `generate_facies_polygon_layer`
  （thresholds=i+0.5）→ GeoJSON Feature 列表；`mock_grid` 中间产物。
- `ensure_mock_facies_models`：幂等注册，demo_only=True 永不晋升。
  注：与 `libs/mapping_kernel` 已绿的 polygonization/class_grid 核相邻
  （generate_facies_polygon_layer / point_in_ring_scalar_inclusive），
  后续切片可复用，本切片不动。

---

## 10. `paleo_workbench/prediction/geoviz_online.py`（552 行）【findings-only（网络客户端）】

- 端点/密钥/模型版本全部 env 驱动（PALEO_GEOVIZ_ONLINE_BASE_URL / _ENDPOINT /
  PALEO_GEOVIZ_API_KEY / PALEO_GEOVIZ_MODEL_VERSION_ID）；默认 HTTPS 端点
  `https://118.178.238.153:3100/api/v1`。
- `require_secure_endpoint`（#1145）：明文 HTTP 仅 loopback / RFC2606 测试
  后缀 / 显式 PALEO_ALLOW_PLAINTEXT_ENDPOINT=1。
- `build_single_well_payload`：只送 schema 声明的曲线；行保留条件 = 深度有限
  且全部必需曲线值有限（`for...else` 全有才 append）；按深度升序；
  {"深度": depth, 曲线: 值}；行数 < minimum_rows → 中文窗口报错。
- `run_single_well_prediction`：GET /models 发现 inputSchema（curves/window）
  → POST /predict → 202 轮询（pollUrl 同源校验 `_trusted_poll_url`、
  pollAfterMs 夹 [0.05,10]s、deadline 检查、≤0.2s 可中断切片睡眠 #1169、
  cancel → TaskCancelled）；failed/canceled → `_terminal_error`（截 1000 字）。
- `response_records`：depth/label/confidence 有限才收；region_id=
  inference_api_{n}；`normalize_sampled_prediction_regions(force=True)` 中点
  邻接化；`_curve_maps` casefold 键、重复助记符后者胜、NaN 值保留为 None。

---

## 11. `paleo_workbench/prediction/inference_worker.py`（38 行）【UI 胶水】
`InferenceWorker(QObject)`：completed(object)/failed(str)/terminal() 三信号，
execute_run 包 try/except。Qt 层，转换后期 M10。

## 12. `paleo_workbench/prediction/__init__.py`（6 行）
仅 re-export LocalAssetPredictionAdapter / MockPredictionAdapter。
**注意**：import `paleo_workbench.prediction.tiled_onnx` 会先执行包
`__init__` → adapters → project.models → pydantic。oracle 生成器因此需要
pydantic 可用（venv 已装）。

## 13. `paleo_workbench/services/prediction_service.py`（25 行）【findings-only】
已删除的假 "ResNet3D_Facies_v1" 的诚实替代：re-export Demo/LocalAsset/
InferenceInputError。

## 14. `paleo_workbench/viz/prediction_helpers.py`（430 行）【胶水】

- `field_value`（dict/attr 双协议）、`active_prediction_task`（取最后一个）。
- `lithology_name_for_facies`：子串启发（砂→砂岩、泥→泥岩、三角洲→砂岩…），
  未命中 "未分类岩性"。
- `regions_to_depth_intervals`：有 top/bottom → clamp 到 [top,bottom]、
  b<=t 丢弃、round 3、附 lithology；否则均分 span（step=span/n，round 3）。
- `normalize_sampled_prediction_regions`：<2 条（force 单条 → ±0.5）；
  非 force 且非全 inference_api_ 前缀 → 原样；中心点取 depth 或区间中点；
  排序后非严格递增 → 原样；非 force 且无真实重叠 → 原样；边界=相邻中点，
  首条向外半差、末条同；clamp min/max depth；b<=t → 整体原样（回滚）；
  round 6。
- `merge_prediction_onto_well_log` / `build_ai_prediction_tracks` /
  `well_log_data_from_prediction`（合成 0–100 m 轴 + 预测概率曲线）/ 
  `export_well_canvas`（PNG/SVG/PDF + record_export）。

## 15. `paleo_workbench/viz/prediction_tracks.py`（273 行）【UI 胶水（QPainter）】
`_FACIES_STYLES` 有序关键词表（首个命中胜）；`facies_style_for` 未命中灰。
`SvgOutputTextureCache`：svg_output/textures 80px 样片裁 (4,4,12,12) 平铺。
`FaciesTextureTrack`（分类 + 纹理）、`ConfidenceHeatmapTrack`（连续 0–1
浅蓝→深蓝、lightness<128 反白）。M10 UI 层。

## 16. `paleo_workbench/viz/seismic_prediction_helpers.py`（19 行）【findings-only】
`seismic_volume_from_prediction(task, shape=(8,10,12))`：
np.random.default_rng(seed or 0).normal(0, 0.18) float32 + 每 region 概率
加到 `index % shape[0]` 层。演示用。

## 17. 支撑模块（非 §5 列举但被 tiled_onnx 依赖）
- `runtime/resource_budget.py`：`active_budget()` 惰性单例；本机 62 GiB →
  `for_total_ram_gb(62)` → scale=min(1,62/32)=1 → streaming_buffer_bytes=
  5 GiB；PALEO_BUDGET_RAM_GB 可覆盖。**结论：oracle 小 tile 不触发批量钳制；
  C++ 数值核不含该守卫**（见 decisions）。
- `catalog/checksum.py`：`sha256_file_or_none`（OSError → None）。
- `runtime/task_scheduler.py`：`TaskCancelled(Exception)`。
- ADR-0001：ClassMap/ProbMap 双张量（alpha 置信叠加）+ BinGridGeometry
  观察者 —— C++ 渲染侧消费本核输出的既有架构依据。
- `docs/agents/stage13-prediction-audit.md`：仓库零生产模型；promote 门；
  schema 驱动输入；生产地图拒 demo 方块 —— 本切片不动这些门。

---

## 18. 测试 → oracle 案例表（移植相关）

| pytest（test_tiled_onnx.py） | 断言 | 本切片 oracle 对应 |
|---|---|---|
| test_tile_partition_covers_exactly_once | (100,30,8),(26,8,4),(7,8,4),(128,64,8) 精确划分 | cases: tile_starts/auth 单元组（含 (5,4,1) 奇 overlap、(1,1,0)、(9,4,0) 尾截） |
| test_tiled_equals_whole_volume_inference | sign(overlap 0)/conv(overlap 4) 与整卷一致；probmap atol 1e-3 | cases: run_sign_ov0 / run_conv_ov4 / run_conv_ov8 / 多批（batch 2/3） |
| test_resume_skips_completed_tiles | cancel 后部分 marker；resume 补全且结果一致 | cases: run_cancel_protocol / run_resume |
| test_provider_cancel_returns_protocol_complete_dict | cancelled=True + shape/classes/tiles=0 | case: run_cancel_immediate（cancel 恒真） |
| test_softmax_budget_rejects_oversized_batch/classes | 显式报错 match "batch"/"classes" | cases: err_softmax_batch / err_softmax_classes（冻文案） |
| test_batch_below_one_is_explicit_valueerror_never_clamped | 0/-3 → ValueError match "batch" | case: err_batch_zero |
| test_identity_* 4 例 / provider 契约 | checksum/工件/无身份 | 不移植（胶水），findings 记录 |

其他 pytest 文件：prediction_service/viz/page/panel/overlay/production 等
覆盖 catalog 生命周期与 UI（胶水），其中数值断言（postprocess 合并规则、
normalize 中点邻接、representative_facies 厚度求和、mock 锚点最近邻）列为
后续切片候选，不在本切片 oracle。

## 19. 已知风险与 FP 对齐策略
1. np.exp(float32) vs std::exp —— 允许 1 ulp 内偏差；类图设计保证 argmax
   边界远离噪声（见 decisions：stub 通道间隔 ≥ 大裕度 + 精确平局用例单独
   构造 dyadic 值）。
2. fp16 量化：冻结 Python fp16 值，C++ 对账容差 = 2^-9 相对 + 4e-4 绝对
   （约 1 fp16 ulp）；NaN/inf 逐位等价比较。
3. 元素级 FP 顺序：Python `0.25*L + 0.5*C + 0.25*R`（左结合）与 C++ 同表达式
   逐元素一致；C++ 编译对该 TU 关 FP 收缩（-ffp-contract=off），禁 FMA。
4. softmax 的 `e / e.sum(axis=1)`：C 类 ≤4，numpy 对短轴求和即顺序累加；
   C++ 按同序 `(e0+e1)+e2`。max-subtract 同步实现。
5. `np.argmax` NaN 行为：NaN 视为最大、取首个 NaN 通道（探针验证 2.5.3）；
   C++ argmax 复刻（遇 NaN 立即胜出）。
6. 1.0 - out（C=1 路径）：python float 1.0 与 float32 数组运算保持 float32
   （weak scalar）；C++ 用 `1.0f - v`。0.5 精确平局 → 类 0（首最大）。
